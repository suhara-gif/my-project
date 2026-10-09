"""Routine から BigQuery を直接叩く小さな CLI(コネクタの OAuth が外れても動く経路)。

認証は環境変数 BQ_SERVICE_ACCOUNT_JSON(無ければ ADC)。コネクタ経由だと、
(1) OAuth が外れる (2) 35日分のJSONや18KBのINSERT文がモデルの文脈を通る、という問題があるため、
ファイル入出力に閉じ込める。

  python -m meta_autopilot.bqtool ping --account 1280868240318718
  python -m meta_autopilot.bqtool export-rows --account 1280868240318718 --out rows.json
  python -m meta_autopilot.bqtool load-rows --account 1280868240318718 --since 2026-10-02 --until 2026-10-08 --in raw.json

終了コード: 0=成功 / 2=認証・接続の失敗(コネクタ経路へ切り替える合図) / 1=その他の失敗。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from .ingest import bq

PROJECT = "upty-meta-ads"
DATASET = "meta_ads"
MECHANIC_DEF = "mechanic_lead_unavailable_via_meta_ads_mcp"

EXPORT_SQL = f"""
SELECT TO_JSON_STRING(ARRAY_AGG(STRUCT(
  CAST(date AS STRING) AS date, campaign_id, campaign_name, ad_id, ad_name, spend, impressions,
  link_clicks, landing_page_views AS lpv, cv, cv_definition, frequency) ORDER BY date, ad_id)) AS j
FROM `{PROJECT}.{DATASET}.raw_ad_daily`
WHERE account_id=@account
  AND date > DATE_SUB((SELECT MAX(date) FROM `{PROJECT}.{DATASET}.raw_ad_daily`), INTERVAL @days DAY)
"""

_REQUIRED = ("date", "ad_id", "spend", "impressions", "cv_definition")


def validate_rows(rows: list[dict], account_id: str, since: str, until: str) -> None:
    """取り込み前の機械チェック(routine の規則): cv の NULL は Mechanic_Lead 広告だけ許す。"""
    if not rows:
        raise ValueError("0行です(既存データは消しません)")
    lo, hi = date.fromisoformat(since), date.fromisoformat(until)
    for i, r in enumerate(rows):
        miss = [k for k in _REQUIRED if k not in r]
        if miss:
            raise ValueError(f"{i}行目に列がありません: {', '.join(miss)}")
        d = date.fromisoformat(str(r["date"]))
        if not lo <= d <= hi:
            raise ValueError(f"{i}行目の日付 {d} が期間 {since}〜{until} の外です")
        if r.get("account_id", account_id) != account_id:
            raise ValueError(f"{i}行目の account_id が違います")
        r.setdefault("account_id", account_id)
        if r.get("cv") is None and r["cv_definition"] != MECHANIC_DEF:
            raise ValueError(f"{i}行目: cv が NULL。結果が無い日は 0 を入れる(NULL は判定から外れる)")


def _cmd_ping(a) -> int:
    rows = bq.query(PROJECT, f"SELECT CAST(MAX(date) AS STRING) AS max_date FROM `{PROJECT}.{DATASET}.raw_ad_daily` WHERE account_id=@a", {"a": a.account})
    print(json.dumps({"ok": True, "max_date": rows[0]["max_date"], "auth": "service_account" if bq.service_account_info() else "adc"}))
    return 0


def _cmd_export(a) -> int:
    rows = bq.query(PROJECT, EXPORT_SQL, {"account": a.account, "days": a.days})
    data = json.loads(rows[0]["j"] or "[]")
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    print(json.dumps({"ok": True, "rows": len(data), "out": a.out}))
    return 0


def _cmd_load(a) -> int:
    with open(a.infile, encoding="utf-8") as f:
        rows = json.load(f)
    validate_rows(rows, a.account, a.since, a.until)
    n = bq.upsert_ad_daily(PROJECT, DATASET, rows, a.since, a.until, a.account)
    print(json.dumps({"ok": True, "loaded": n}))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="bqtool")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("ping", _cmd_ping), ("export-rows", _cmd_export), ("load-rows", _cmd_load)):
        sp = sub.add_parser(name)
        sp.add_argument("--account", required=True)
        sp.set_defaults(fn=fn)
        if name == "export-rows":
            sp.add_argument("--out", required=True)
            sp.add_argument("--days", type=int, default=35)
        if name == "load-rows":
            sp.add_argument("--since", required=True)
            sp.add_argument("--until", required=True)
            sp.add_argument("--in", dest="infile", required=True)
    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except ValueError as e:  # 入力・設定の誤り(鍵の中身は含めない)
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except Exception as e:  # 認証・接続系はクラス名だけ出す(メッセージに鍵やトークンが混ざらないように)
        print(json.dumps({"ok": False, "error": type(e).__name__, "hint": "認証/接続の失敗。コネクタ経路へ切り替える"}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
