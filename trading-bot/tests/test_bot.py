"""bot.run_once の安全装置をモックのブローカーで検証する。"""

import unittest
from datetime import date, timedelta
from unittest import mock

from sma_bot import bot
from sma_bot.config import Config
from sma_bot.strategy import Bar, Signal, signals_for_series


class FakeClient:
    is_paper = True

    def __init__(self, equity=100_000.0, last_equity=100_000.0, held=0):
        self.equity = equity
        self.last_equity = last_equity
        self.held = held
        self.orders = []

    def account(self):
        return {"equity": str(self.equity), "last_equity": str(self.last_equity), "cash": str(self.equity)}

    def position_qty(self, symbol):
        return self.held

    def submit_bracket_buy(self, symbol, qty, take_profit_price, stop_loss_price):
        self.orders.append(("buy", symbol, qty))
        return {}

    def cancel_open_orders(self, symbol):
        pass

    def close_position(self, symbol):
        self.orders.append(("close", symbol))
        return {}


def golden_cross_bars() -> list[Bar]:
    """最新バーがちょうどゴールデンクロスになる日足列を作る。"""
    closes = [100.0 - i for i in range(30)] + [72.0 + i * 3 for i in range(25)]
    sigs = signals_for_series(closes, 5, 20)
    first_buy = sigs.index(Signal.BUY)
    closes = closes[: first_buy + 1]
    day = date(2024, 1, 1)
    bars = []
    for c in closes:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        bars.append(Bar(day=day, open=c, high=c, low=c, close=c))
        day += timedelta(days=1)
    return bars


def config() -> Config:
    return Config(symbols=["TEST"], fast_period=5, slow_period=20)


class TestRunOnce(unittest.TestCase):
    def test_dry_run_submits_no_orders(self):
        client = FakeClient()
        with mock.patch.object(bot, "fetch_alpaca_daily_bars", return_value=golden_cross_bars()):
            actions = bot.run_once(config(), client=client, dry_run=True)
        self.assertEqual(client.orders, [])
        self.assertTrue(any("dry-run" in a and "BUY" in a for a in actions))

    def test_trade_mode_submits_bracket_buy(self):
        client = FakeClient()
        with mock.patch.object(bot, "fetch_alpaca_daily_bars", return_value=golden_cross_bars()):
            actions = bot.run_once(config(), client=client, dry_run=False)
        self.assertEqual(len(client.orders), 1)
        self.assertEqual(client.orders[0][0], "buy")
        self.assertTrue(any(a.startswith("BUY TEST") for a in actions))

    def test_daily_loss_limit_halts_new_buys(self):
        # 前日比 -5% (上限 3%) なので新規買いは止まる
        client = FakeClient(equity=95_000.0, last_equity=100_000.0)
        with mock.patch.object(bot, "fetch_alpaca_daily_bars", return_value=golden_cross_bars()):
            actions = bot.run_once(config(), client=client, dry_run=False)
        self.assertEqual(client.orders, [])
        self.assertTrue(any("損失上限" in a for a in actions))

    def test_no_buy_when_already_holding(self):
        client = FakeClient(held=10)
        with mock.patch.object(bot, "fetch_alpaca_daily_bars", return_value=golden_cross_bars()):
            actions = bot.run_once(config(), client=client, dry_run=False)
        self.assertEqual(client.orders, [])
        self.assertEqual(actions, [])


if __name__ == "__main__":
    unittest.main()
