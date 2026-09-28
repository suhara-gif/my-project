"""BigQuery から取り出した広告×日の行(JSON)に検知ロジックをかけ、Slack 用の本文を作る。

トークンを使わずコネクタ(Meta Ads MCP / BigQuery / Slack)だけで毎朝回す運用(Routine)のための入口。
取り込みと Slack 送信はコネクタ側で行い、ここは判定だけを担う。

  python -m meta_autopilot.offline --rows rows.json --target-cpa 5800 --label TW

rows.json は raw_ad_daily から date, campaign_id, campaign_name, ad_id, ad_name, spend, impressions,
link_clicks, lpv, cv, cv_definition, frequency を取り出した配列。最も多い cv_definition と違う行は判定から外す。
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from .detect.delivery import AdWindow, detect_delivery_skew
from .detect.fatigue import AdHistory, detect_winner_dropout, detect_winner_fatigue
from .detect.funnel import detect_funnel_breaks
from .models import Alert, FunnelTotals, Severity

_ICON = {Severity.CRITICAL: "🔴", Severity.WARN: "🟠", Severity.INFO: "⚪"}


def _f(v) -> float:
    return float(v or 0)


def _totals(rows: list[dict]) -> FunnelTotals:
    return FunnelTotals(
        sum(_f(r["spend"]) for r in rows),
        sum(_f(r["impressions"]) for r in rows),
        sum(_f(r["link_clicks"]) for r in rows),
        sum(_f(r["lpv"]) for r in rows),
        sum(_f(r["cv"]) for r in rows),
    )


def _wfreq(rows: list[dict]) -> float | None:
    imp = sum(_f(r["impressions"]) for r in rows)
    return sum(_f(r.get("frequency")) * _f(r["impressions"]) for r in rows) / imp if imp else None


def detect_rows(rows: list[dict], *, target_cpa: float) -> tuple[list[Alert], dict]:
    # CV 定義(cv_definition)が最も多いものだけで判定する。定義の違う広告を混ぜると CPA が比較できない。
    # 空欄の cv は「0件」と区別できないので、定義が一致していても判定から外す(取り込み側で 0 を入れること)。
    defs = [r.get("cv_definition") for r in rows if r.get("cv_definition")]
    main_def = max(set(defs), key=defs.count) if defs else None
    ok = [r for r in rows if r.get("cv") is not None and r.get("cv_definition") == main_def]
    excluded = sorted({r["ad_name"] for r in rows} - {r["ad_name"] for r in ok})
    rows = ok
    if not rows:
        return [], {"excluded": excluded}
    latest = max(date.fromisoformat(str(r["date"])) for r in rows)

    def age(r: dict) -> int:
        return (latest - date.fromisoformat(str(r["date"]))).days

    alerts: list[Alert] = []
    by_camp: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        by_camp[(r["campaign_id"], r["campaign_name"])].append(r)
    for (_, cname), rs in by_camp.items():
        by_ad: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for r in rs:
            by_ad[(r["ad_id"], r["ad_name"])].append(r)
        ads = [
            AdWindow(i, n, _totals([r for r in a if age(r) < 7]), _totals([r for r in a if 7 <= age(r) < 28]))
            for (i, n), a in by_ad.items()
        ]
        scope = f"キャンペーン {cname}"
        cur = sum((a.current for a in ads), FunnelTotals.zero())
        base = sum((a.baseline for a in ads), FunnelTotals.zero())
        alerts += detect_funnel_breaks(scope, cur, base, ads=ads)
        alerts += detect_delivery_skew(scope, ads, target_cpa=target_cpa)
        for (i, n), a in by_ad.items():
            a = sorted(a, key=lambda r: str(r["date"]))
            last14 = [r for r in a if age(r) < 14 and _f(r["impressions"]) > 0]
            h = AdHistory(
                i, n,
                _totals([r for r in a if 7 <= age(r) < 35]), _totals([r for r in a if age(r) < 7]),
                [_f(r["link_clicks"]) / _f(r["impressions"]) for r in last14],
                [_f(r["impressions"]) for r in last14],
                _wfreq([r for r in a if 7 <= age(r) < 35]), _wfreq([r for r in a if age(r) < 7]),
            )
            alerts += detect_winner_fatigue(f"広告 {n}", h, target_cpa=target_cpa)
            alerts += detect_winner_dropout(f"広告 {n}", h, target_cpa=target_cpa)

    last7 = _totals([r for r in rows if age(r) < 7])
    prev21 = _totals([r for r in rows if 7 <= age(r) < 28])
    summary = {"latest": latest.isoformat(), "last7": last7, "prev21": prev21, "excluded": excluded}
    return alerts, summary


def _yen(v: float) -> str:
    return "—" if v == float("inf") else f"¥{v:,.0f}"


def format_text(label: str, alerts: list[Alert], summary: dict, *, target_cpa: float) -> str:
    order = {Severity.CRITICAL: 0, Severity.WARN: 1, Severity.INFO: 2}
    lines = [f"*Meta広告デイリー {label}*(〜{summary.get('latest', '?')})"]
    if "last7" in summary:
        c, p = summary["last7"], summary["prev21"]
        lines.append(
            f"直近7日: 費用 {_yen(c.spend)} / 登録 {c.cv:.0f}件 / CPA {_yen(c.cpa)}"
            f"(前21日 CPA {_yen(p.cpa)}、目標 {_yen(target_cpa)})"
        )
    if not alerts:
        lines.append("異常なし")
    for a in sorted(alerts, key=lambda a: order[a.severity]):
        lines.append(f"\n{_ICON[a.severity]} *{a.title}*\n{a.scope}\n原因: {a.cause}")
        lines += [f"• {x}" for x in a.actions]
    if summary.get("excluded"):
        lines.append("\n(CV定義が違うため判定から除外: " + "、".join(summary["excluded"]) + ")")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="meta_autopilot.offline")
    ap.add_argument("--rows", required=True)
    ap.add_argument("--target-cpa", type=float, required=True)
    ap.add_argument("--label", default="")
    args = ap.parse_args(argv)
    rows = json.loads(Path(args.rows).read_text(encoding="utf-8"))
    alerts, summary = detect_rows(rows, target_cpa=args.target_cpa)
    print(format_text(args.label, alerts, summary, target_cpa=args.target_cpa))


if __name__ == "__main__":
    main()
