#!/usr/bin/env python3
"""売買判定を1回実行する (cron から呼ぶ想定)。

使い方:
  python run_bot.py             # dry-run: 判定だけして注文は出さない
  python run_bot.py --trade     # ペーパートレード口座に実際に発注する
"""

from __future__ import annotations

import argparse
import logging
import sys

from sma_bot.bot import run_once
from sma_bot.broker import AlpacaClient
from sma_bot.config import Config


def main() -> int:
    parser = argparse.ArgumentParser(description="SMAクロスBotの1回実行")
    parser.add_argument("--trade", action="store_true", help="実際に注文を出す (省略時はdry-run)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    cfg = Config.load()
    client = AlpacaClient()

    clock = client.clock()
    if not clock.get("is_open"):
        logging.info("市場が閉まっています (次の開場: %s)。何もせず終了します", clock.get("next_open"))
        return 0

    run_once(cfg, client=client, dry_run=not args.trade)
    return 0


if __name__ == "__main__":
    sys.exit(main())
