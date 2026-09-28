"""日次パイプラインの各ステップ。BigQuery/Meta/Slack との入出力はここに集め、判定ロジックは純関数側に置く。"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .config import Config
from .detect.delivery import AdWindow, detect_delivery_skew
from .detect.fatigue import AdHistory, detect_winner_fatigue
from .detect.funnel import detect_funnel_breaks
from .ingest import bq
from .ingest.meta_insights import fetch_ad_daily, refetch_window, to_bq_row
from .models import Alert, FunnelTotals, Severity
from .notify import slack

JST = timezone(timedelta(hours=9))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _totals(r: dict, suffix: str) -> FunnelTotals:
    return FunnelTotals(
        spend=float(r[f"spend{suffix}"] or 0),
        impressions=float(r[f"impressions{suffix}"] or 0),
        link_clicks=float(r[f"link_clicks{suffix}"] or 0),
        lpv=float(r[f"lpv{suffix}"] or 0),
        cv=float(r[f"cv{suffix}"] or 0),
    )


# ---------- 1. 取り込み ----------

def ingest(cfg: Config, today: date | None = None) -> dict[str, int]:
    today = today or datetime.now(JST).date()
    since, until = refetch_window(today, cfg.refetch_days)
    counts = {}
    for acc in cfg.accounts:
        rows = [
            to_bq_row(r, primary_conversion=acc.primary_conversion, fetched_at=_now())
            for r in fetch_ad_daily(acc.account_id, since, until, access_token=cfg.meta_access_token, api_version=cfg.graph_api_version)
        ]
        counts[acc.label] = bq.upsert_ad_daily(cfg.gcp_project, cfg.bq_dataset, rows, since.isoformat(), until.isoformat(), acc.account_id)
    return counts


# ---------- 2. 異常検知 ----------

_WINDOW_SQL = """
WITH latest AS (SELECT MAX(date) AS d FROM `{t}`)
SELECT {keys},
  {agg}
FROM `{t}` r CROSS JOIN latest l
WHERE r.date > DATE_SUB(l.d, INTERVAL 35 DAY)
GROUP BY {keys}
"""


def _agg_cols(cur_days: int, base_from: int, base_to: int) -> str:
    cols = []
    for src, name in (("spend", "spend"), ("impressions", "impressions"), ("link_clicks", "link_clicks"),
                      ("landing_page_views", "lpv"), ("cv", "cv")):
        cols.append(f"SUM(IF(r.date > DATE_SUB(l.d, INTERVAL {cur_days} DAY), r.{src}, 0)) AS {name}_cur")
        cols.append(
            f"SUM(IF(r.date <= DATE_SUB(l.d, INTERVAL {base_from} DAY) AND r.date > DATE_SUB(l.d, INTERVAL {base_to} DAY), r.{src}, 0)) AS {name}_base"
        )
    return ",\n  ".join(cols)


def detect(cfg: Config) -> list[Alert]:
    t = f"{cfg.gcp_project}.{cfg.bq_dataset}.raw_ad_daily"
    alerts: list[Alert] = []
    alerts += _detect_data_gaps(cfg, t)

    # (a) キャンペーン単位のファネル分解: 直近7日 vs その前21日
    camp_rows = bq.query(
        cfg.gcp_project,
        _WINDOW_SQL.format(t=t, keys="r.account_id, r.campaign_id", agg="ANY_VALUE(r.campaign_name) AS campaign_name,\n  " + _agg_cols(7, 7, 28)),
    )
    for r in camp_rows:
        scope = f"{cfg.account(r['account_id']).label} / campaign:{r['campaign_id']} {r['campaign_name']}"
        alerts += detect_funnel_breaks(scope, _totals(r, "_cur"), _totals(r, "_base"))

    # (b) 配信の偏り: キャンペーン内の広告別 直近7日 vs その前21日
    ad_rows = bq.query(
        cfg.gcp_project,
        _WINDOW_SQL.format(t=t, keys="r.account_id, r.campaign_id, r.ad_id",
                           agg="ANY_VALUE(r.campaign_name) AS campaign_name, ANY_VALUE(r.ad_name) AS ad_name,\n  " + _agg_cols(7, 7, 28)),
    )
    by_camp: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in ad_rows:
        by_camp[(r["account_id"], r["campaign_id"])].append(r)
    for (acc_id, camp_id), rows in by_camp.items():
        acc = cfg.account(acc_id)
        ads = [AdWindow(r["ad_id"], r["ad_name"], _totals(r, "_cur"), _totals(r, "_base")) for r in rows]
        alerts += detect_delivery_skew(f"{acc.label} / campaign:{camp_id} {rows[0]['campaign_name']}", ads, target_cpa=acc.target_cpa)

    # (c) 勝ちCRの失速: 基準 = 8〜35日前、現在 = 直近7日、CTR は直近14日の日次
    alerts += _detect_fatigue(cfg, t)
    return alerts


def _detect_data_gaps(cfg: Config, t: str) -> list[Alert]:
    """前日の費用が0/欠落しているアカウント。原因は断定しない(配信停止・取得漏れ・遅延・実測0 の4通りがある)。"""
    rows = bq.query(
        cfg.gcp_project,
        f"""
        WITH d AS (SELECT account_id, date, SUM(spend) AS spend FROM `{t}`
                   WHERE date >= DATE_SUB(CURRENT_DATE('Asia/Tokyo'), INTERVAL 8 DAY) GROUP BY account_id, date)
        SELECT account_id,
               SUM(IF(date = DATE_SUB(CURRENT_DATE('Asia/Tokyo'), INTERVAL 1 DAY), spend, 0)) AS spend_y,
               AVG(IF(date < DATE_SUB(CURRENT_DATE('Asia/Tokyo'), INTERVAL 1 DAY), spend, NULL)) AS spend_avg7
        FROM d GROUP BY account_id
        """,
    )
    seen = {r["account_id"] for r in rows}
    alerts = []
    for acc in cfg.accounts:
        r = next((x for x in rows if x["account_id"] == acc.account_id), None)
        if acc.account_id not in seen or (r and (r["spend_avg7"] or 0) > 3000 and (r["spend_y"] or 0) == 0):
            alerts.append(
                Alert(
                    kind="data_gap",
                    severity=Severity.WARN,
                    scope=acc.label,
                    title="前日の費用が0または欠落",
                    cause="配信停止(正常)/API取得漏れ/計上遅延/実測0 のいずれか。この情報だけでは区別できない",
                    actions=["Ads Manager で前日の配信状態を確認", "取り込みジョブのログを確認し、必要なら ingest を再実行"],
                )
            )
    return alerts


def _detect_fatigue(cfg: Config, t: str) -> list[Alert]:
    rows = bq.query(
        cfg.gcp_project,
        f"""
        WITH latest AS (SELECT MAX(date) AS d FROM `{t}`)
        SELECT r.account_id, r.ad_id, ANY_VALUE(r.ad_name) AS ad_name,
          {_agg_cols(7, 7, 35)},
          SAFE_DIVIDE(SUM(IF(r.date <= DATE_SUB(l.d, INTERVAL 7 DAY), r.frequency * r.impressions, 0)),
                      SUM(IF(r.date <= DATE_SUB(l.d, INTERVAL 7 DAY), r.impressions, 0))) AS freq_base,
          SAFE_DIVIDE(SUM(IF(r.date > DATE_SUB(l.d, INTERVAL 7 DAY), r.frequency * r.impressions, 0)),
                      SUM(IF(r.date > DATE_SUB(l.d, INTERVAL 7 DAY), r.impressions, 0))) AS freq_cur,
          ARRAY_AGG(IF(r.date > DATE_SUB(l.d, INTERVAL 14 DAY),
                       STRUCT(r.date AS date, SAFE_DIVIDE(r.link_clicks, r.impressions) AS ctr, r.impressions AS imp), NULL)
                    IGNORE NULLS ORDER BY r.date) AS daily
        FROM `{t}` r CROSS JOIN latest l
        WHERE r.date > DATE_SUB(l.d, INTERVAL 35 DAY)
        GROUP BY r.account_id, r.ad_id
        """,
    )
    alerts = []
    for r in rows:
        acc = cfg.account(r["account_id"])
        daily = [d for d in r["daily"] if d["ctr"] is not None]
        h = AdHistory(
            ad_id=r["ad_id"], ad_name=r["ad_name"],
            baseline=_totals(r, "_base"), current=_totals(r, "_cur"),
            daily_ctr=[d["ctr"] for d in daily], daily_impressions=[d["imp"] for d in daily],
            frequency_baseline=r["freq_base"], frequency_current=r["freq_cur"],
        )
        alerts += detect_winner_fatigue(f"{acc.label} / ad:{r['ad_id']}", h, target_cpa=acc.target_cpa)
    return alerts


def notify(cfg: Config, alerts: list[Alert], header: str) -> dict:
    payload = slack.format_alerts(alerts, header=header)
    if cfg.slack_webhook_url:
        slack.post(cfg.slack_webhook_url, payload)
    return payload


# ---------- 3. 新CRの判定 ----------

def lifecycle(cfg: Config) -> list[dict]:
    """入稿済みの生成CRを、親(コントロール)の同期間実績と比べて判定する。"""
    from .lifecycle.decide import LifecyclePolicy, decide
    from .lifecycle.execute import pause_ad, should_execute

    ds = f"{cfg.gcp_project}.{cfg.bq_dataset}"
    targets = bq.query(
        cfg.gcp_project,
        f"SELECT generated_id, ad_id, parent_ad_ids FROM `{ds}.generated_creatives` WHERE status = 'uploaded' AND ad_id IS NOT NULL",
    )
    policy = LifecyclePolicy(**cfg.lifecycle.get("policy", {}))
    auto_execute = cfg.lifecycle.get("auto_execute", ["STOP"])
    out = []
    for g in targets:
        # 比較は「新CRが配信された日」に揃える(期間が違うと季節・競合の影響が混ざる)
        rows = bq.query(
            cfg.gcp_project,
            f"""
            WITH live AS (SELECT DISTINCT date FROM `{ds}.raw_ad_daily` WHERE ad_id = @ad_id AND impressions > 0)
            SELECT IF(ad_id = @ad_id, 'new', 'control') AS arm, ANY_VALUE(account_id) AS account_id,
                   SUM(spend) AS spend, SUM(impressions) AS impressions, SUM(link_clicks) AS link_clicks,
                   SUM(landing_page_views) AS lpv, SUM(cv) AS cv
            FROM `{ds}.raw_ad_daily` JOIN live USING (date)
            WHERE ad_id = @ad_id OR ad_id IN UNNEST(SPLIT(@parents))
            GROUP BY arm
            """,
            {"ad_id": g["ad_id"], "parents": ",".join(g["parent_ad_ids"] or [])},
        )
        arms = {r["arm"]: r for r in rows}
        if "new" not in arms or "control" not in arms:
            continue
        acc = cfg.account(arms["new"]["account_id"])
        res = decide(g["ad_id"], _totals(arms["new"], ""), _totals(arms["control"], ""), target_cpa=acc.target_cpa, policy=policy)
        executed = False
        if should_execute(res, dry_run=cfg.dry_run, auto_execute=auto_execute):
            pause_ad(res.ad_id, access_token=cfg.meta_access_token, api_version=cfg.graph_api_version)
            executed = True
        row = {
            "decided_at": _now(), "ad_id": res.ad_id, "control_ad_ids": g["parent_ad_ids"] or [],
            "decision": res.decision.value, "reason": res.reason, "prob_better": res.prob_better,
            "spend": res.spend, "cv": res.cv, "next_hypothesis": res.next_hypothesis,
            "executed": executed, "evidence_json": json.dumps(res.evidence, ensure_ascii=False),
        }
        out.append(row)
    bq.insert_rows(cfg.gcp_project, cfg.bq_dataset, "cr_decisions", out)
    return out


def lifecycle_alerts(rows: list[dict]) -> list[Alert]:
    sev = {"STOP": Severity.WARN, "SCALE": Severity.INFO, "CONTINUE": Severity.INFO, "EXTEND_TEST": Severity.INFO}
    return [
        Alert(
            kind="cr_lifecycle",
            severity=sev[r["decision"]],
            scope=f"ad:{r['ad_id']}",
            title=f"新CR判定: {r['decision']}" + ("(停止を実行済み)" if r["executed"] else ""),
            cause=r["reason"],
            actions=[r["next_hypothesis"]] + (["横展は人の承認後に実施(自動では予算を増やさない)"] if r["decision"] == "SCALE" else []),
        )
        for r in rows
    ]


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
