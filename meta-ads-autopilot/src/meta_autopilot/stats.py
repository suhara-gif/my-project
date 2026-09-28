"""少数データでも誤判定しにくい比較のための統計ヘルパー。

Meta広告の実データ(例: トヨワク直近28日で広告約20本・CV計約49件)では、広告×日の
CVは0〜1件が大半になる。点推定の CPA/CVR を閾値と比べると、ほぼノイズで警報が鳴る。
そこで以下の2つの共役モデルで「悪化している確率」を出し、確率と変化幅の両方で判定する。

- 率(CTR・LPV率・CVR): Beta-Binomial
- コストあたりCV(CPAの逆数): Gamma-Poisson (CV ~ Poisson(費用 × λ))

scipy に依存しないよう、事後分布の比較はモンテカルロで行う(乱数シードは固定)。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_DEFAULT_DRAWS = 20_000


def _rng(seed: int | None) -> np.random.Generator:
    return np.random.default_rng(0 if seed is None else seed)


@dataclass(frozen=True)
class RateComparison:
    """2つの率の比較結果。"""

    rate_current: float
    rate_baseline: float
    relative_change: float  # (現在/基準) - 1。基準が0なら nan
    prob_worse: float  # 現在の真の率が基準より低い確率
    n_current: int
    n_baseline: int


def compare_rates(
    succ_cur: float,
    trials_cur: float,
    succ_base: float,
    trials_base: float,
    *,
    prior_a: float = 1.0,
    prior_b: float = 1.0,
    draws: int = _DEFAULT_DRAWS,
    seed: int | None = None,
) -> RateComparison:
    """Beta-Binomial で「現在の率が基準より低い確率」を求める。

    succ > trials になるデータ(アトリビューションの都合で起こりうる)は trials で頭打ちにする。
    """
    trials_cur = max(float(trials_cur), 0.0)
    trials_base = max(float(trials_base), 0.0)
    succ_cur = min(max(float(succ_cur), 0.0), trials_cur)
    succ_base = min(max(float(succ_base), 0.0), trials_base)

    rng = _rng(seed)
    cur = rng.beta(prior_a + succ_cur, prior_b + trials_cur - succ_cur, draws)
    base = rng.beta(prior_a + succ_base, prior_b + trials_base - succ_base, draws)

    rate_cur = succ_cur / trials_cur if trials_cur else float("nan")
    rate_base = succ_base / trials_base if trials_base else float("nan")
    rel = rate_cur / rate_base - 1 if rate_base and rate_base == rate_base else float("nan")
    return RateComparison(
        rate_current=rate_cur,
        rate_baseline=rate_base,
        relative_change=rel,
        prob_worse=float(np.mean(cur < base)),
        n_current=int(trials_cur),
        n_baseline=int(trials_base),
    )


@dataclass(frozen=True)
class CostEfficiencyComparison:
    """費用あたりCV(λ)の比較。CPA = 1/λ。"""

    cpa_current: float
    cpa_baseline: float
    prob_better: float  # 現在の λ が基準より高い(=CPAが良い)確率
    lift_median: float  # λ_現在 / λ_基準 の事後中央値
    cv_current: float
    spend_current: float


def gamma_posterior_samples(
    cv: float,
    spend: float,
    *,
    prior_cv: float,
    prior_spend: float,
    draws: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """λ(1円あたりCV)の事後サンプル。事前分布は「prior_spend 円で prior_cv 件」相当。"""
    shape = prior_cv + max(float(cv), 0.0)
    rate = prior_spend + max(float(spend), 0.0)
    return rng.gamma(shape, 1.0 / rate, draws)


def compare_cost_efficiency(
    cv_cur: float,
    spend_cur: float,
    cv_base: float,
    spend_base: float,
    *,
    prior_cpa: float,
    prior_strength_cv: float = 1.0,
    draws: int = _DEFAULT_DRAWS,
    seed: int | None = None,
) -> CostEfficiencyComparison:
    """Gamma-Poisson で CPA を比較する。

    prior_cpa は目標CPAなど「平均的にはこのくらい」という値。prior_strength_cv 件ぶんの
    重みで両者を同じ事前分布へ縮約するので、CV 0〜2 件の広告が極端な判定を受けにくい。
    """
    rng = _rng(seed)
    prior_spend = prior_cpa * prior_strength_cv
    cur = gamma_posterior_samples(
        cv_cur, spend_cur, prior_cv=prior_strength_cv, prior_spend=prior_spend, draws=draws, rng=rng
    )
    base = gamma_posterior_samples(
        cv_base, spend_base, prior_cv=prior_strength_cv, prior_spend=prior_spend, draws=draws, rng=rng
    )
    return CostEfficiencyComparison(
        cpa_current=spend_cur / cv_cur if cv_cur else float("inf"),
        cpa_baseline=spend_base / cv_base if cv_base else float("inf"),
        prob_better=float(np.mean(cur > base)),
        lift_median=float(np.median(cur / base)),
        cv_current=float(cv_cur),
        spend_current=float(spend_cur),
    )


def shrunk_cpa(cv: float, spend: float, *, prior_cpa: float, prior_strength_cv: float = 1.0) -> float:
    """事後平均ベースのCPA(縮約済み)。CV0件でも無限大にならない。"""
    return (prior_cpa * prior_strength_cv + spend) / (prior_strength_cv + cv)


def slope_prob_negative(values: list[float], weights: list[float] | None = None) -> tuple[float, float]:
    """時系列(日次CTR等)の単回帰の傾きと、傾きが負である近似確率を返す。

    重み(例: インプレッション)付き最小二乗。点が3未満なら (0, 0.5)。
    正規近似なので厳密ではない。失速の「兆候」を拾う用途に限る。
    """
    y = np.asarray(values, dtype=float)
    n = len(y)
    if n < 3:
        return 0.0, 0.5
    w = np.ones(n) if weights is None else np.asarray(weights, dtype=float)
    w = np.where(w > 0, w, 0.0)
    if w.sum() == 0:
        return 0.0, 0.5
    x = np.arange(n, dtype=float)
    xm = np.average(x, weights=w)
    ym = np.average(y, weights=w)
    sxx = np.sum(w * (x - xm) ** 2)
    if sxx == 0:
        return 0.0, 0.5
    slope = np.sum(w * (x - xm) * (y - ym)) / sxx
    resid = y - (ym + slope * (x - xm))
    dof = max(n - 2, 1)
    sigma2 = np.sum(w * resid**2) / dof / (w.sum() / n)
    se = np.sqrt(sigma2 / (sxx / (w.sum() / n))) if sigma2 > 0 else 0.0
    if se == 0:
        return float(slope), 1.0 if slope < 0 else 0.0
    z = slope / se
    # 標準正規の CDF(-z)
    from math import erf, sqrt

    prob_negative = 0.5 * (1 + erf(-z / sqrt(2)))
    return float(slope), float(prob_negative)
