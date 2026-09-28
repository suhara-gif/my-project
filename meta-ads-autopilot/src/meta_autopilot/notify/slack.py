"""Slack 通知(Incoming Webhook)。依存を増やさないよう標準ライブラリのみで送る。"""

from __future__ import annotations

import json
import urllib.request

from ..models import Alert, Severity

_ICON = {Severity.CRITICAL: ":red_circle:", Severity.WARN: ":large_orange_circle:", Severity.INFO: ":white_circle:"}
_ORDER = {Severity.CRITICAL: 0, Severity.WARN: 1, Severity.INFO: 2}


def format_alerts(alerts: list[Alert], *, header: str, max_items: int = 15) -> dict:
    """Block Kit のペイロードを作る。重大度順、上限件数を超えた分は件数だけ示す。"""
    alerts = sorted(alerts, key=lambda a: _ORDER[a.severity])
    blocks: list[dict] = [{"type": "header", "text": {"type": "plain_text", "text": header[:150]}}]
    if not alerts:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "異常なし"}})
    for a in alerts[:max_items]:
        actions = "\n".join(f"• {x}" for x in a.actions)
        text = f"{_ICON[a.severity]} *{a.title}*\n`{a.scope}`\n*原因:* {a.cause}\n*対応案:*\n{actions}"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text[:2900]}})
        blocks.append({"type": "divider"})
    if len(alerts) > max_items:
        blocks.append(
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"ほか {len(alerts) - max_items} 件は BigQuery の alerts を参照"}]}
        )
    return {"text": header, "blocks": blocks}


def post(webhook_url: str, payload: dict) -> None:
    req = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        if r.status != 200:
            raise RuntimeError(f"Slack 送信失敗: HTTP {r.status}")
