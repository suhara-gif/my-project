#!/usr/bin/env python3
"""バックテスト動作確認用の【合成】日足データを生成する。

実在銘柄の実際の価格ではない。シード固定の幾何ブラウン運動に
強気/弱気/横ばいのレジーム切り替えを加えたもので、data/sample/ に出力する。
実データでの検証は run_backtest.py --fetch (要 Alpaca APIキー) を使うこと。
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from sma_bot.config import PROJECT_ROOT
from sma_bot.data import save_csv
from sma_bot.strategy import Bar

OUT_DIR = PROJECT_ROOT / "data" / "sample"

# (銘柄名, シード, 初期価格, 年率ドリフト, 年率ボラティリティ)
SPECS = [
    ("DEMO_TECH1", 11, 150.0, 0.16, 0.30),
    ("DEMO_TECH2", 23, 300.0, 0.14, 0.28),
    ("DEMO_SEMI", 37, 450.0, 0.22, 0.45),
    ("DEMO_RETAIL", 41, 120.0, 0.10, 0.25),
    ("DEMO_ENERGY", 53, 80.0, 0.06, 0.35),
]

START = date(2020, 7, 1)
YEARS = 5
TRADING_DAYS_PER_YEAR = 252


def generate(seed: int, s0: float, drift: float, vol: float) -> list[Bar]:
    rng = random.Random(seed)
    bars: list[Bar] = []
    day = START
    price = s0
    dt = 1 / TRADING_DAYS_PER_YEAR
    regime = 0.0  # レジームによるドリフト補正
    regime_left = 0

    for _ in range(YEARS * TRADING_DAYS_PER_YEAR):
        while day.weekday() >= 5:  # 土日はスキップ
            day += timedelta(days=1)
        if regime_left <= 0:
            regime = rng.choice([-0.35, -0.15, 0.0, 0.15, 0.30])
            regime_left = rng.randint(30, 120)
        regime_left -= 1

        mu = drift + regime
        shock = rng.gauss(0, 1)
        open_ = price * (1 + rng.gauss(0, vol * 0.15) * dt**0.5)
        close = price * (2.718281828 ** ((mu - vol**2 / 2) * dt + vol * dt**0.5 * shock))
        hi_span = abs(rng.gauss(0, vol * 0.6)) * dt**0.5 * price
        high = max(open_, close) + hi_span
        low = max(0.01, min(open_, close) - abs(rng.gauss(0, vol * 0.6)) * dt**0.5 * price)
        bars.append(
            Bar(
                day=day,
                open=round(open_, 4),
                high=round(high, 4),
                low=round(low, 4),
                close=round(close, 4),
                volume=int(rng.uniform(1e6, 5e7)),
            )
        )
        price = close
        day += timedelta(days=1)
    return bars


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for symbol, seed, s0, drift, vol in SPECS:
        bars = generate(seed, s0, drift, vol)
        save_csv(OUT_DIR / f"{symbol}.csv", bars)
        print(f"{symbol}: {len(bars)}本 ({bars[0].day} 〜 {bars[-1].day}) -> {OUT_DIR / f'{symbol}.csv'}")
    readme = OUT_DIR / "README.md"
    readme.write_text(
        "# 合成サンプルデータ\n\n"
        "このディレクトリのCSVは `gen_sample_data.py` が生成した**合成データ**です。\n"
        "実在銘柄の実際の価格ではありません。バックテストエンジンの動作確認・学習専用です。\n\n"
        "実データで検証するには Alpaca の APIキーを `.env` に設定して\n"
        "`python run_backtest.py --fetch --symbols AAPL MSFT` を実行してください。\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
