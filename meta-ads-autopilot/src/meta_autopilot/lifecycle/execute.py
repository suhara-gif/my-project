"""判定を Meta に反映する(書き込み)。

安全側の既定:
- config.dry_run が True の間は何もしない(ログだけ)。
- 自動実行してよい判定は config.lifecycle.auto_execute に明示したものだけ(既定 ["STOP"])。
- 実行できるのは「広告の一時停止」だけ。削除・予算増額・新規入稿はここでは行わない
  (取り消しにくい/お金が増える操作は、人が Ads Manager か入稿フローで行う)。
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

from .decide import Decision, LifecycleResult


def pause_ad(ad_id: str, *, access_token: str, api_version: str) -> None:
    data = urllib.parse.urlencode({"status": "PAUSED", "access_token": access_token}).encode()
    req = urllib.request.Request(f"https://graph.facebook.com/{api_version}/{ad_id}", data=data, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        body = json.loads(r.read().decode("utf-8"))
        if not body.get("success"):
            raise RuntimeError(f"広告 {ad_id} の停止に失敗: {body}")


def should_execute(result: LifecycleResult, *, dry_run: bool, auto_execute: list[str]) -> bool:
    return (not dry_run) and result.decision == Decision.STOP and "STOP" in auto_execute
