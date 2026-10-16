"""移動平均クロスオーバー戦略。

やっていることは「短期SMAが長期SMAを上抜けたら買い、下抜けたら売り」の判定だけ。
計算は引き算と比較のみで、どんなPCでも一瞬で終わる。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


class Signal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass(frozen=True)
class Bar:
    """日足1本分。"""

    day: date
    open: float
    high: float
    low: float
    close: float
    volume: int = 0


def sma(values: list[float], period: int) -> list[float | None]:
    """単純移動平均。データが period 本たまるまでは None。"""
    if period <= 0:
        raise ValueError("period は正の整数で指定してください")
    out: list[float | None] = [None] * len(values)
    window_sum = 0.0
    for i, value in enumerate(values):
        window_sum += value
        if i >= period:
            window_sum -= values[i - period]
        if i >= period - 1:
            out[i] = window_sum / period
    return out


def crossover_signal(closes: list[float], fast_period: int, slow_period: int) -> Signal:
    """終値系列の最新バーに対するシグナルを返す。

    ゴールデンクロス(短期が長期を下から上へ抜けた瞬間)で BUY、
    デッドクロス(上から下へ抜けた瞬間)で SELL、それ以外は HOLD。
    「抜けた瞬間」だけを検出するので、クロス済みの状態が続いても連続シグナルは出ない。
    """
    if fast_period >= slow_period:
        raise ValueError("fast_period は slow_period より小さくしてください")
    if len(closes) < slow_period + 1:
        return Signal.HOLD

    fast = sma(closes, fast_period)
    slow = sma(closes, slow_period)
    prev_fast, prev_slow = fast[-2], slow[-2]
    cur_fast, cur_slow = fast[-1], slow[-1]
    if None in (prev_fast, prev_slow, cur_fast, cur_slow):
        return Signal.HOLD

    if prev_fast <= prev_slow and cur_fast > cur_slow:
        return Signal.BUY
    if prev_fast >= prev_slow and cur_fast < cur_slow:
        return Signal.SELL
    return Signal.HOLD


def signals_for_series(closes: list[float], fast_period: int, slow_period: int) -> list[Signal]:
    """バックテスト用: 全バーに対するシグナル列を返す。

    各バー i のシグナルは i 時点までの終値だけから計算する(未来のデータは見ない)。
    """
    fast = sma(closes, fast_period)
    slow = sma(closes, slow_period)
    out = [Signal.HOLD] * len(closes)
    for i in range(1, len(closes)):
        if None in (fast[i - 1], slow[i - 1], fast[i], slow[i]):
            continue
        if fast[i - 1] <= slow[i - 1] and fast[i] > slow[i]:
            out[i] = Signal.BUY
        elif fast[i - 1] >= slow[i - 1] and fast[i] < slow[i]:
            out[i] = Signal.SELL
    return out
