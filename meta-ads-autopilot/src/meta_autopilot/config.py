"""設定の読み込み。秘密情報は設定ファイルに書かず、環境変数から読む。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class AccountConfig:
    account_id: str  # 数値のみ(act_ は付けない)
    label: str  # CW / CWA / TW 等
    target_cpa: float  # 判定の事前分布と勝ち判定に使う目標CPA(円)
    # CV とみなす action。"actions:" または "conversions:" の接頭辞でどちらのリストかを指定する。
    # 例: conversions:offsite_conversion.fb_pixel_custom.Mechanic_Lead
    primary_conversion: str = "actions:offsite_conversion.fb_pixel_complete_registration"


@dataclass
class Config:
    gcp_project: str
    bq_dataset: str
    accounts: list[AccountConfig]
    graph_api_version: str = "v23.0"  # [要確認] 運用開始時点の最新版に合わせる
    refetch_days: int = 7  # アトリビューションの遅延計上に備えて毎回再取得する日数
    lifecycle: dict = field(default_factory=dict)
    generation: dict = field(default_factory=dict)
    dry_run: bool = True  # True の間は Meta への書き込み(停止・入稿)を一切行わない

    # 秘密情報(環境変数)
    @property
    def meta_access_token(self) -> str:
        return _require_env("META_ACCESS_TOKEN")

    @property
    def slack_webhook_url(self) -> str | None:
        return os.environ.get("SLACK_WEBHOOK_URL")

    def account(self, account_id: str) -> AccountConfig:
        for a in self.accounts:
            if a.account_id == account_id:
                return a
        raise KeyError(f"未設定のアカウント: {account_id}")


def _require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"環境変数 {name} が未設定です")
    return v


def load_config(path: str | Path) -> Config:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    accounts = [AccountConfig(**a) for a in raw.pop("accounts")]
    return Config(accounts=accounts, **raw)
