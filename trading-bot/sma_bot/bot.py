"""1日1回実行する売買判定 (ペーパートレード/本番共通)。

流れ:
1. 安全装置チェック — 当日の損失が daily_loss_limit_pct を超えていたら新規買いを停止
2. 各銘柄の日足を取得し、SMA クロスのシグナルを判定
3. BUY: ブラケット注文 (買い + 利確 + 損切りを同時発注)
   SELL: ポジションをクローズ

cron 等で市場が開いている時間帯に1日1回動かす想定。
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from .broker import AlpacaClient
from .config import Config
from .data import fetch_alpaca_daily_bars
from .strategy import Signal, crossover_signal

logger = logging.getLogger("sma_bot")


def daily_loss_exceeded(client: AlpacaClient, cfg: Config) -> bool:
    """当日の資産減少が上限を超えたかどうか。超えていたら新規エントリーを止める。"""
    account = client.account()
    equity = float(account["equity"])
    last_equity = float(account["last_equity"])
    if last_equity <= 0:
        return False
    change = equity / last_equity - 1.0
    logger.info("口座資産: %.2f (前日比 %+.2f%%)", equity, change * 100)
    if change <= -cfg.daily_loss_limit_pct:
        logger.warning(
            "本日の損失 %.2f%% が上限 %.2f%% を超えたため、新規注文を停止します",
            -change * 100,
            cfg.daily_loss_limit_pct * 100,
        )
        return True
    return False


def run_once(cfg: Config, client: AlpacaClient | None = None, dry_run: bool = True) -> list[str]:
    """全銘柄を1回判定する。実行した(または実行予定だった)アクションの一覧を返す。"""
    client = client or AlpacaClient()
    mode = "DRY-RUN" if dry_run else ("PAPER" if client.is_paper else "LIVE")
    logger.info("=== SMA Bot 実行 (%s) ===", mode)
    if not client.is_paper and dry_run is False:
        logger.warning("本番口座で実行しています。")

    actions: list[str] = []
    halt_new_buys = daily_loss_exceeded(client, cfg)
    account = client.account()
    equity = float(account["equity"])
    cash = float(account["cash"])

    end = date.today()
    start = end - timedelta(days=cfg.slow_period * 3)  # 休場日を考慮して多めに取る

    for symbol in cfg.symbols:
        try:
            bars = fetch_alpaca_daily_bars(symbol, start, end)
        except Exception:
            logger.exception("%s: データ取得に失敗。この銘柄はスキップします", symbol)
            continue
        closes = [b.close for b in bars]
        if len(closes) < cfg.slow_period + 1:
            logger.info("%s: データ不足 (%d本)。スキップ", symbol, len(closes))
            continue

        signal = crossover_signal(closes, cfg.fast_period, cfg.slow_period)
        held_qty = client.position_qty(symbol)
        price = closes[-1]
        logger.info("%s: 終値 %.2f / シグナル %s / 保有 %d株", symbol, price, signal.value, held_qty)

        if signal is Signal.BUY and held_qty == 0:
            if halt_new_buys:
                actions.append(f"SKIP BUY {symbol} (1日の損失上限に到達)")
                continue
            budget = min(cash, equity * cfg.position_fraction)
            qty = int(budget / price)
            if qty <= 0:
                actions.append(f"SKIP BUY {symbol} (資金不足)")
                continue
            tp = price * (1 + cfg.take_profit_pct)
            sl = price * (1 - cfg.stop_loss_pct)
            desc = f"BUY {symbol} {qty}株 成行 (利確 {tp:.2f} / 損切り {sl:.2f})"
            if dry_run:
                actions.append(f"[dry-run] {desc}")
            else:
                client.submit_bracket_buy(symbol, qty, take_profit_price=tp, stop_loss_price=sl)
                cash -= qty * price
                actions.append(desc)

        elif signal is Signal.SELL and held_qty > 0:
            desc = f"SELL {symbol} {held_qty}株 (デッドクロス)"
            if dry_run:
                actions.append(f"[dry-run] {desc}")
            else:
                client.cancel_open_orders(symbol)  # ブラケットの残り注文を先に取り消す
                client.close_position(symbol)
                actions.append(desc)

    for action in actions or ["本日は取引なし"]:
        logger.info("%s", action)
    return actions
