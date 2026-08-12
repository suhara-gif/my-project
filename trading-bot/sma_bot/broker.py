"""Alpaca Trading API クライアント (標準ライブラリのみ)。

デフォルトはペーパートレード (paper-api.alpaca.markets)。
本番口座に切り替えるには環境変数 ALPACA_LIVE=1 と
ALPACA_LIVE_CONFIRM=yes-i-understand-the-risk の両方が必要 (config.py 参照)。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .config import api_credentials, trading_base_url


class AlpacaError(RuntimeError):
    pass


class AlpacaClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or trading_base_url()
        self._key, self._secret = api_credentials()

    @property
    def is_paper(self) -> bool:
        return "paper" in self.base_url

    def _request(self, method: str, path: str, params: dict | None = None, body: dict | None = None) -> Any:
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "APCA-API-KEY-ID": self._key,
                "APCA-API-SECRET-KEY": self._secret,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            raise AlpacaError(f"{method} {path} -> HTTP {e.code}: {detail}") from e
        return json.loads(raw) if raw else None

    # --- 口座・ポジション ---

    def account(self) -> dict:
        return self._request("GET", "/v2/account")

    def clock(self) -> dict:
        return self._request("GET", "/v2/clock")

    def positions(self) -> list[dict]:
        return self._request("GET", "/v2/positions")

    def position_qty(self, symbol: str) -> int:
        try:
            pos = self._request("GET", f"/v2/positions/{urllib.parse.quote(symbol)}")
            return int(float(pos["qty"]))
        except AlpacaError as e:
            if "404" in str(e):
                return 0
            raise

    # --- 注文 ---

    def submit_market_order(self, symbol: str, qty: int, side: str) -> dict:
        if side not in ("buy", "sell"):
            raise ValueError("side は buy か sell")
        if qty <= 0:
            raise ValueError("qty は正の整数")
        return self._request(
            "POST",
            "/v2/orders",
            body={
                "symbol": symbol,
                "qty": str(qty),
                "side": side,
                "type": "market",
                "time_in_force": "day",
            },
        )

    def submit_bracket_buy(self, symbol: str, qty: int, take_profit_price: float, stop_loss_price: float) -> dict:
        """買いと同時に利確/損切り注文を取引所側に置くブラケット注文。

        Bot が止まっている間も利確/損切りが機能するので、成行買い + Bot 側監視より安全。
        """
        return self._request(
            "POST",
            "/v2/orders",
            body={
                "symbol": symbol,
                "qty": str(qty),
                "side": "buy",
                "type": "market",
                "time_in_force": "gtc",
                "order_class": "bracket",
                "take_profit": {"limit_price": f"{take_profit_price:.2f}"},
                "stop_loss": {"stop_price": f"{stop_loss_price:.2f}"},
            },
        )

    def close_position(self, symbol: str) -> dict:
        return self._request("DELETE", f"/v2/positions/{urllib.parse.quote(symbol)}")

    def cancel_open_orders(self, symbol: str) -> None:
        for order in self._request("GET", "/v2/orders", params={"status": "open", "symbols": symbol}):
            self._request("DELETE", f"/v2/orders/{order['id']}")
