"""設定の読み込み。

config.json に戦略・リスク管理のパラメータ、.env に Alpaca の API キーを置く。
キーをコードや設定ファイルに直書きしないこと。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PAPER_BASE_URL = "https://paper-api.alpaca.markets"
LIVE_BASE_URL = "https://api.alpaca.markets"
DATA_BASE_URL = "https://data.alpaca.markets"


@dataclass
class Config:
    symbols: list[str] = field(default_factory=lambda: ["AAPL"])
    fast_period: int = 20
    slow_period: int = 50
    # 1回のエントリーで使う口座資産の割合 (0.1 = 10%)
    position_fraction: float = 0.10
    # 買値からの利確/損切りライン (0.15 = +15% で利確, 0.07 = -7% で損切り)
    take_profit_pct: float = 0.15
    stop_loss_pct: float = 0.07
    # 1日の損失がこの割合を超えたら新規注文を停止する (0.03 = -3%)
    daily_loss_limit_pct: float = 0.03
    # バックテスト用の摩擦コスト
    slippage_pct: float = 0.0005
    commission_pct: float = 0.0

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        path = Path(path) if path else PROJECT_ROOT / "config.json"
        cfg = cls()
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            for key, value in raw.items():
                if not hasattr(cfg, key):
                    raise KeyError(f"config.json に未知のキーがあります: {key}")
                setattr(cfg, key, value)
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if self.fast_period >= self.slow_period:
            raise ValueError("fast_period は slow_period より小さくしてください")
        if not (0 < self.position_fraction <= 1):
            raise ValueError("position_fraction は 0〜1 の範囲で指定してください")
        for name in ("take_profit_pct", "stop_loss_pct", "daily_loss_limit_pct"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} は正の値で指定してください")


def load_env(path: str | Path | None = None) -> dict[str, str]:
    """.env を読み、環境変数にも反映して dict で返す。既存の環境変数を優先する。"""
    path = Path(path) if path else PROJECT_ROOT / ".env"
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    for key, value in values.items():
        os.environ.setdefault(key, value)
    return values


def api_credentials() -> tuple[str, str]:
    load_env()
    key = os.environ.get("ALPACA_API_KEY", "")
    secret = os.environ.get("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        raise RuntimeError(
            "ALPACA_API_KEY / ALPACA_SECRET_KEY が設定されていません。"
            " .env.example をコピーして .env を作成してください。"
        )
    return key, secret


def trading_base_url() -> str:
    """デフォルトはペーパートレード。本番口座は環境変数で明示的に2段階の同意が必要。"""
    load_env()
    if os.environ.get("ALPACA_LIVE") == "1" and os.environ.get("ALPACA_LIVE_CONFIRM") == "yes-i-understand-the-risk":
        return LIVE_BASE_URL
    return PAPER_BASE_URL
