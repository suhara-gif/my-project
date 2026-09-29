"""勝ちCRの失速(クリエイティブ疲弊)を検知する。

勝ちCR = 基準期間で CV が一定数あり、縮約CPAが目標以下だった広告。
失速 = 直近で CPA が基準より確からしく悪化し、かつ CTR の下落傾向 or フリークエンシー上昇を伴う。
CTR/フリークエンシーの裏付けを要求するのは、CVR 側の悪化(LP・計測起因)を CR 疲弊と誤認しないため。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Alert, FunnelTotals, Severity
from ..stats import compare_cost_efficiency, shrunk_cpa, slope_prob_negative


@dataclass(frozen=True)
class AdHistory:
    ad_id: str
    ad_name: str
    baseline: FunnelTotals
    current: FunnelTotals
    daily_ctr: list[float]  # 直近14日の日次CTR(古い順)
    daily_impressions: list[float]
    frequency_baseline: float | None = None
    frequency_current: float | None = None


@dataclass(frozen=True)
class FatigueThresholds:
    winner_min_cv: float = 3
    prob_worse: float = 0.85
    ctr_slope_prob_negative: float = 0.90
    frequency_jump: float = 0.30


def is_winner(h: AdHistory, *, target_cpa: float, th: FatigueThresholds = FatigueThresholds()) -> bool:
    return h.baseline.cv >= th.winner_min_cv and shrunk_cpa(
        h.baseline.cv, h.baseline.spend, prior_cpa=target_cpa
    ) <= target_cpa


def detect_winner_fatigue(
    scope: str,
    h: AdHistory,
    *,
    target_cpa: float,
    th: FatigueThresholds = FatigueThresholds(),
) -> list[Alert]:
    if not is_winner(h, target_cpa=target_cpa, th=th):
        return []
    cmp = compare_cost_efficiency(
        h.current.cv, h.current.spend, h.baseline.cv, h.baseline.spend, prior_cpa=target_cpa
    )
    prob_worse = 1 - cmp.prob_better
    if prob_worse < th.prob_worse:
        return []

    signals = []
    _, p_neg = slope_prob_negative(h.daily_ctr, h.daily_impressions)
    if p_neg >= th.ctr_slope_prob_negative:
        signals.append(f"CTR が下落傾向(確率 {p_neg:.0%})")
    if h.frequency_baseline and h.frequency_current:
        jump = h.frequency_current / h.frequency_baseline - 1
        if jump >= th.frequency_jump:
            signals.append(f"フリークエンシー {h.frequency_baseline:.2f} → {h.frequency_current:.2f}")
    if not signals:
        # CPA は悪化しているが疲弊の裏付けが無い → ファネル分解側で扱う
        return []

    return [
        Alert(
            kind="winner_fatigue",
            severity=Severity.WARN,
            scope=scope,
            title=f"勝ちCRの失速: {h.ad_name}",
            cause=(
                f"CPA ¥{shrunk_cpa(h.baseline.cv, h.baseline.spend, prior_cpa=target_cpa):,.0f}"
                f" → ¥{shrunk_cpa(h.current.cv, h.current.spend, prior_cpa=target_cpa):,.0f}"
                f"(悪化確率 {prob_worse:.0%})。" + "、".join(signals) + "。CR の摩耗が疑われる。"
            ),
            actions=[
                "同じ訴求軸・構成のまま冒頭フックだけ変えた派生CRを投入(creative 特徴量の差分から生成)",
                "即停止はしない。派生CRが基準CPAに届くまで並走させ、配信が移ってから停止判断",
            ],
            evidence={"ad_id": h.ad_id, "prob_worse": round(prob_worse, 3), "ctr_slope_p_neg": round(p_neg, 3)},
        )
    ]


def detect_winner_dropout(
    scope: str,
    h: AdHistory,
    *,
    target_cpa: float,
    baseline_days: int = 28,
    current_days: int = 7,
    max_spend_ratio: float = 0.2,
    baseline_spend_share: float | None = None,
    major_share: float = 0.15,
    th: FatigueThresholds = FatigueThresholds(),
) -> list[Alert]:
    """勝ちCR、または基準期間にキャンペーン費用の major_share 以上を占めた主力CRの配信停止を検知する。

    主力CRは CPA が目標より悪くても対象にする(費用は CV と違いノイズが小さく、最大費用CRが
    消えると配信構成が変わって上流の指標が動くため)。この場合は勝ちCRとは書かず「主力CR」とする。

    失速(detect_winner_fatigue)は配信が続いている前提なので、費用が0になった勝ちCRは拾えない。
    手動停止・Meta の配分変更・審査落ち・予算変更のどれかだが、この情報だけでは区別できないので
    原因は断定せず、意図した停止かの確認を促す。
    """
    winner = is_winner(h, target_cpa=target_cpa, th=th)
    major = baseline_spend_share is not None and baseline_spend_share >= major_share
    if not (winner or major):
        return []
    daily_base = h.baseline.spend / baseline_days
    daily_cur = h.current.spend / current_days
    if daily_base <= 0 or daily_cur / daily_base > max_spend_ratio:
        return []
    return [
        Alert(
            kind="winner_dropout" if winner else "major_dropout",
            severity=Severity.WARN,
            scope=scope,
            title=f"{'勝ちCR' if winner else '主力CR'}の配信がほぼ止まった: {h.ad_name}",
            cause=(
                f"基準期間は1日平均 ¥{daily_base:,.0f}・CV {h.baseline.cv:.0f}件、直近{current_days}日は1日平均 ¥{daily_cur:,.0f}。"
                "手動停止・Meta の配分変更・審査・予算変更のいずれか(この情報だけでは区別できない)"
            ),
            actions=[
                "意図した停止かを確認(Ads Manager の配信ステータスと変更履歴)",
                "意図しない停止なら再開、配分で外れたなら別広告セットへ複製して配信を確保",
                "同キャンペーンで配信が移った先のCRの CPA を確認",
            ],
            evidence={"ad_id": h.ad_id, "daily_spend_baseline": round(daily_base), "daily_spend_current": round(daily_cur)},
        )
    ]
