#!/usr/bin/env python3
"""バックテストを実行する。

使い方:
  python run_backtest.py                          # data/sample/ の合成データで実行
  python run_backtest.py --data-dir data/real     # 自分で取得したCSVで実行
  python run_backtest.py --fetch --start 2020-01-01  # Alpaca から実データを取得して実行 (要APIキー)
  python run_backtest.py --fast 10 --slow 30      # パラメータを変えて再検証
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from sma_bot.backtest import format_report, run_backtest
from sma_bot.config import PROJECT_ROOT, Config
from sma_bot.data import fetch_alpaca_daily_bars, load_csv, save_csv
from sma_bot.strategy import Bar

SAMPLE_DIR = PROJECT_ROOT / "data" / "sample"


def main() -> int:
    parser = argparse.ArgumentParser(description="SMAクロス戦略のバックテスト")
    parser.add_argument("--data-dir", default=str(SAMPLE_DIR), help="銘柄ごとのCSVを置いたディレクトリ")
    parser.add_argument("--fetch", action="store_true", help="Alpaca APIから実データを取得して data/real に保存")
    parser.add_argument("--start", default="2020-01-01", help="--fetch 時の取得開始日")
    parser.add_argument("--symbols", nargs="*", help="対象銘柄 (省略時は config.json)")
    parser.add_argument("--fast", type=int, help="短期SMA期間 (省略時は config.json)")
    parser.add_argument("--slow", type=int, help="長期SMA期間 (省略時は config.json)")
    parser.add_argument("--cash", type=float, default=100_000.0, help="初期資金")
    args = parser.parse_args()

    cfg = Config.load()
    if args.symbols:
        cfg.symbols = args.symbols
    if args.fast:
        cfg.fast_period = args.fast
    if args.slow:
        cfg.slow_period = args.slow
    cfg.validate()

    data_dir = Path(args.data_dir)
    data: dict[str, list[Bar]] = {}

    if args.fetch:
        data_dir = PROJECT_ROOT / "data" / "real"
        for symbol in cfg.symbols:
            print(f"{symbol}: Alpaca からデータ取得中...")
            bars = fetch_alpaca_daily_bars(symbol, date.fromisoformat(args.start), date.today())
            save_csv(data_dir / f"{symbol}.csv", bars)
            data[symbol] = bars
    else:
        for symbol in cfg.symbols:
            path = data_dir / f"{symbol}.csv"
            if not path.exists():
                print(f"警告: {path} がありません。スキップします", file=sys.stderr)
                continue
            data[symbol] = load_csv(path)

    if not data:
        print("エラー: データがありません。--fetch で取得するか、CSVを配置してください", file=sys.stderr)
        return 1

    if data_dir.resolve() == SAMPLE_DIR.resolve():
        print("注意: data/sample/ の【合成データ】を使用しています。実在銘柄の実際の価格ではありません。\n")

    result = run_backtest(data, cfg, initial_cash=args.cash)
    first = min(b[0].day for b in data.values() if b)
    last = max(b[-1].day for b in data.values() if b)
    print(f"期間: {first} 〜 {last} / 銘柄: {', '.join(sorted(data))}\n")
    print(format_report(result, cfg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
