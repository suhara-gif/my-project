"""バックテストエンジン。

ルールと前提:
- シグナルは各日の終値時点で判定し、約定は【翌営業日の始値】(ルックアヘッド防止)。
- 買値から take_profit_pct 上で利確、stop_loss_pct 下で損切り。日中の高値/安値で判定し、
  そのライン価格で約定したとみなす (ギャップで始値がラインを飛び越えた場合は始値で約定)。
- 全注文にスリッページと手数料を摩擦コストとして乗せる。
- 1銘柄1ポジション。エントリー金額は「その時点の総資産 × position_fraction」を現金の範囲で。

これは過去データ上のシミュレーションであり、将来の利益を保証しない。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .config import Config
from .strategy import Bar, Signal, signals_for_series


@dataclass
class Trade:
    symbol: str
    entry_day: date
    entry_price: float
    qty: int
    exit_day: date | None = None
    exit_price: float | None = None
    reason: str = ""

    @property
    def pnl(self) -> float:
        if self.exit_price is None:
            return 0.0
        return (self.exit_price - self.entry_price) * self.qty

    @property
    def return_pct(self) -> float:
        if self.exit_price is None:
            return 0.0
        return self.exit_price / self.entry_price - 1.0


@dataclass
class BacktestResult:
    initial_cash: float
    final_equity: float
    trades: list[Trade]
    equity_curve: list[tuple[date, float]]
    buy_hold_return_pct: float

    @property
    def total_return_pct(self) -> float:
        return self.final_equity / self.initial_cash - 1.0

    @property
    def closed_trades(self) -> list[Trade]:
        return [t for t in self.trades if t.exit_price is not None]

    @property
    def win_rate(self) -> float:
        closed = self.closed_trades
        if not closed:
            return 0.0
        return sum(1 for t in closed if t.pnl > 0) / len(closed)

    @property
    def avg_win_pct(self) -> float:
        wins = [t.return_pct for t in self.closed_trades if t.pnl > 0]
        return sum(wins) / len(wins) if wins else 0.0

    @property
    def avg_loss_pct(self) -> float:
        losses = [t.return_pct for t in self.closed_trades if t.pnl <= 0]
        return sum(losses) / len(losses) if losses else 0.0

    @property
    def max_drawdown_pct(self) -> float:
        peak = float("-inf")
        max_dd = 0.0
        for _, equity in self.equity_curve:
            peak = max(peak, equity)
            max_dd = max(max_dd, 1.0 - equity / peak)
        return max_dd


@dataclass
class _Position:
    qty: int
    entry_price: float
    trade: Trade


def run_backtest(data: dict[str, list[Bar]], cfg: Config, initial_cash: float = 100_000.0) -> BacktestResult:
    """複数銘柄の日足でSMAクロス戦略をシミュレーションする。"""
    signals: dict[str, list[Signal]] = {}
    index_by_day: dict[str, dict[date, int]] = {}
    for symbol, bars in data.items():
        closes = [b.close for b in bars]
        signals[symbol] = signals_for_series(closes, cfg.fast_period, cfg.slow_period)
        index_by_day[symbol] = {b.day: i for i, b in enumerate(bars)}

    all_days = sorted({b.day for bars in data.values() for b in bars})
    cash = initial_cash
    positions: dict[str, _Position] = {}
    trades: list[Trade] = []
    equity_curve: list[tuple[date, float]] = []
    # 前日の終値時点で出たシグナルを翌営業日の始値で執行するためのキュー
    pending: dict[str, Signal] = {}

    def buy_fill(price: float) -> float:
        return price * (1 + cfg.slippage_pct + cfg.commission_pct)

    def sell_fill(price: float) -> float:
        return price * (1 - cfg.slippage_pct - cfg.commission_pct)

    def mark_to_market(day: date) -> float:
        total = cash
        for symbol, pos in positions.items():
            i = index_by_day[symbol].get(day)
            price = data[symbol][i].close if i is not None else pos.entry_price
            total += pos.qty * price
        return total

    for day in all_days:
        # 1) 前日のシグナルを始値で執行
        for symbol, sig in list(pending.items()):
            i = index_by_day[symbol].get(day)
            if i is None:
                continue  # この銘柄は本日休場扱い。次の営業日に持ち越す
            bar = data[symbol][i]
            del pending[symbol]
            if sig is Signal.BUY and symbol not in positions:
                budget = min(cash, mark_to_market(day) * cfg.position_fraction)
                price = buy_fill(bar.open)
                qty = int(budget / price)
                if qty > 0:
                    cash -= qty * price
                    trade = Trade(symbol=symbol, entry_day=day, entry_price=price, qty=qty)
                    trades.append(trade)
                    positions[symbol] = _Position(qty=qty, entry_price=price, trade=trade)
            elif sig is Signal.SELL and symbol in positions:
                pos = positions.pop(symbol)
                price = sell_fill(bar.open)
                cash += pos.qty * price
                pos.trade.exit_day, pos.trade.exit_price, pos.trade.reason = day, price, "dead_cross"

        # 2) 保有ポジションの利確/損切りを日中値で判定
        for symbol, pos in list(positions.items()):
            i = index_by_day[symbol].get(day)
            if i is None or pos.trade.entry_day == day:
                continue  # エントリー当日は判定しない
            bar = data[symbol][i]
            tp_line = pos.entry_price * (1 + cfg.take_profit_pct)
            sl_line = pos.entry_price * (1 - cfg.stop_loss_pct)
            exit_price, reason = None, ""
            # ギャップダウン/アップで始値が既にラインを越えていたら始値で約定
            if bar.open <= sl_line:
                exit_price, reason = bar.open, "stop_loss_gap"
            elif bar.open >= tp_line:
                exit_price, reason = bar.open, "take_profit_gap"
            elif bar.low <= sl_line:
                exit_price, reason = sl_line, "stop_loss"
            elif bar.high >= tp_line:
                exit_price, reason = tp_line, "take_profit"
            if exit_price is not None:
                positions.pop(symbol)
                price = sell_fill(exit_price)
                cash += pos.qty * price
                pos.trade.exit_day, pos.trade.exit_price, pos.trade.reason = day, price, reason
                pending.pop(symbol, None)

        # 3) 本日の終値でシグナルを判定し、翌営業日の執行キューへ
        for symbol, bars in data.items():
            i = index_by_day[symbol].get(day)
            if i is None:
                continue
            sig = signals[symbol][i]
            if sig is Signal.BUY and symbol not in positions:
                pending[symbol] = sig
            elif sig is Signal.SELL and symbol in positions:
                pending[symbol] = sig

        equity_curve.append((day, mark_to_market(day)))

    # 期末に残ったポジションは最終終値で評価済み (equity_curve に反映)
    final_equity = equity_curve[-1][1] if equity_curve else initial_cash

    # 比較用: 同じ銘柄群を初日に均等買いして持ちっぱなしにした場合
    bh_returns = []
    for bars in data.values():
        if len(bars) >= 2:
            bh_returns.append(bars[-1].close / bars[0].open - 1.0)
    buy_hold = sum(bh_returns) / len(bh_returns) if bh_returns else 0.0

    return BacktestResult(
        initial_cash=initial_cash,
        final_equity=final_equity,
        trades=trades,
        equity_curve=equity_curve,
        buy_hold_return_pct=buy_hold,
    )


def format_report(result: BacktestResult, cfg: Config) -> str:
    closed = result.closed_trades
    lines = [
        "=== バックテスト結果 ===",
        f"戦略            : SMA {cfg.fast_period}日 / {cfg.slow_period}日 クロス",
        f"利確 / 損切り   : +{cfg.take_profit_pct:.1%} / -{cfg.stop_loss_pct:.1%}",
        f"初期資金        : {result.initial_cash:,.0f}",
        f"最終資産        : {result.final_equity:,.0f}",
        f"トータルリターン: {result.total_return_pct:+.1%}",
        f"バイ&ホールド比較: {result.buy_hold_return_pct:+.1%} (同銘柄を均等買いして放置した場合)",
        f"最大ドローダウン: -{result.max_drawdown_pct:.1%}",
        f"取引回数        : {len(closed)} (未決済 {len(result.trades) - len(closed)})",
        f"勝率            : {result.win_rate:.1%}",
        f"平均勝ちトレード: {result.avg_win_pct:+.1%}",
        f"平均負けトレード: {result.avg_loss_pct:+.1%}",
        "",
        "※過去データのシミュレーションであり、将来の利益を保証するものではありません。",
    ]
    return "\n".join(lines)
