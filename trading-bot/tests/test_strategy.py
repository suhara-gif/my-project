import unittest

from sma_bot.strategy import Signal, crossover_signal, sma, signals_for_series


class TestSMA(unittest.TestCase):
    def test_sma_basic(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = sma(values, 3)
        self.assertEqual(result[:2], [None, None])
        self.assertAlmostEqual(result[2], 2.0)
        self.assertAlmostEqual(result[3], 3.0)
        self.assertAlmostEqual(result[4], 4.0)

    def test_sma_period_one(self):
        self.assertEqual(sma([5.0, 6.0], 1), [5.0, 6.0])

    def test_sma_invalid_period(self):
        with self.assertRaises(ValueError):
            sma([1.0], 0)


class TestCrossover(unittest.TestCase):
    def test_golden_cross_fires_buy(self):
        # 下落してから急騰させ、短期SMAが長期SMAを上抜ける形を作る
        closes = [100.0 - i for i in range(10)] + [95.0 + i * 3 for i in range(8)]
        sigs = signals_for_series(closes, 3, 6)
        self.assertIn(Signal.BUY, sigs)

    def test_dead_cross_fires_sell(self):
        closes = [100.0 + i for i in range(10)] + [105.0 - i * 3 for i in range(8)]
        sigs = signals_for_series(closes, 3, 6)
        self.assertIn(Signal.SELL, sigs)

    def test_no_repeated_signals_while_crossed(self):
        # 上抜け後に上昇が続いても BUY は1回だけ
        closes = [100.0 - i for i in range(10)] + [95.0 + i * 2 for i in range(20)]
        sigs = signals_for_series(closes, 3, 6)
        self.assertEqual(sigs.count(Signal.BUY), 1)

    def test_insufficient_data_holds(self):
        self.assertEqual(crossover_signal([1.0, 2.0, 3.0], 2, 5), Signal.HOLD)

    def test_latest_signal_matches_series(self):
        closes = [100.0 - i for i in range(10)] + [95.0 + i * 3 for i in range(8)]
        sigs = signals_for_series(closes, 3, 6)
        for i in range(len(closes)):
            self.assertEqual(crossover_signal(closes[: i + 1], 3, 6), sigs[i])

    def test_invalid_periods(self):
        with self.assertRaises(ValueError):
            crossover_signal([1.0] * 20, 10, 5)


if __name__ == "__main__":
    unittest.main()
