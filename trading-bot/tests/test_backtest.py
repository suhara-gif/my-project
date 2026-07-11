import unittest
from datetime import date, timedelta

from sma_bot.backtest import run_backtest
from sma_bot.config import Config
from sma_bot.strategy import Bar


def make_bars(closes: list[float], start: date = date(2024, 1, 1)) -> list[Bar]:
    bars = []
    day = start
    for close in closes:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        bars.append(Bar(day=day, open=close, high=close * 1.01, low=close * 0.99, close=close))
        day += timedelta(days=1)
    return bars


def base_config(**overrides) -> Config:
    cfg = Config(
        symbols=["TEST"],
        fast_period=3,
        slow_period=6,
        position_fraction=0.5,
        take_profit_pct=10.0,  # デフォルトでは発動しないよう大きく
        stop_loss_pct=10.0,
        daily_loss_limit_pct=0.03,
        slippage_pct=0.0,
        commission_pct=0.0,
    )
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


class TestBacktest(unittest.TestCase):
    def test_golden_cross_opens_position_next_day(self):
        closes = [100.0 - i for i in range(10)] + [95.0 + i * 3 for i in range(10)]
        result = run_backtest({"TEST": make_bars(closes)}, base_config())
        self.assertGreaterEqual(len(result.trades), 1)
        trade = result.trades[0]
        # シグナル当日ではなく翌営業日の始値で約定していること (ルックアヘッド防止)
        bars = make_bars(closes)
        signal_days = [b.day for b in bars]
        self.assertIn(trade.entry_day, signal_days)
        entry_index = signal_days.index(trade.entry_day)
        self.assertAlmostEqual(trade.entry_price, bars[entry_index].open)

    def test_stop_loss_closes_position(self):
        # 上昇でエントリーさせ、その後急落させて損切りを踏ませる
        closes = [100.0 - i for i in range(10)] + [95.0 + i * 3 for i in range(10)] + [60.0] * 5
        cfg = base_config(stop_loss_pct=0.07)
        result = run_backtest({"TEST": make_bars(closes)}, cfg)
        closed = result.closed_trades
        self.assertTrue(closed)
        self.assertIn(closed[0].reason, ("stop_loss", "stop_loss_gap"))
        # 損失は損切りライン近傍で止まっている
        self.assertGreater(closed[0].return_pct, -0.45)

    def test_take_profit_closes_position(self):
        closes = [100.0 - i for i in range(10)] + [95.0 + i * 4 for i in range(15)]
        cfg = base_config(take_profit_pct=0.10)
        result = run_backtest({"TEST": make_bars(closes)}, cfg)
        closed = result.closed_trades
        self.assertTrue(closed)
        self.assertIn(closed[0].reason, ("take_profit", "take_profit_gap"))
        self.assertGreater(closed[0].return_pct, 0.08)

    def test_no_trades_on_flat_data(self):
        result = run_backtest({"TEST": make_bars([100.0] * 60)}, base_config())
        self.assertEqual(len(result.trades), 0)
        self.assertAlmostEqual(result.final_equity, result.initial_cash)

    def test_equity_conserved_without_friction(self):
        # 摩擦コストゼロなら 最終資産 = 初期資金 + 全トレード損益 + 未決済ポジションの含み損益
        closes = [100.0 - i for i in range(10)] + [95.0 + i * 3 for i in range(10)] + [110.0 - i for i in range(10)]
        result = run_backtest({"TEST": make_bars(closes)}, base_config())
        realized = sum(t.pnl for t in result.closed_trades)
        bars = make_bars(closes)
        unrealized = sum(
            (bars[-1].close - t.entry_price) * t.qty for t in result.trades if t.exit_price is None
        )
        self.assertAlmostEqual(result.final_equity, result.initial_cash + realized + unrealized, places=6)

    def test_max_drawdown_positive_on_losing_series(self):
        closes = [100.0 - i for i in range(10)] + [95.0 + i * 3 for i in range(10)] + [130.0 - i * 2 for i in range(20)]
        result = run_backtest({"TEST": make_bars(closes)}, base_config())
        self.assertGreater(result.max_drawdown_pct, 0.0)


if __name__ == "__main__":
    unittest.main()
