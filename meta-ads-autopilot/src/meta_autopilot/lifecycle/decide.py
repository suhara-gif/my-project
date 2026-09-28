"""新CRを既存勝ちCR(コントロール)と比べて、停止・継続・横展・次の仮説を決める。

判定の原則:
1. 費用が「目標CPAの何倍か」で段階を分ける。CV は少ないので、費用が貯まるまでは CPA で判定しない。
2. 早期に見られるのは上流(CTR・LPV率)だけ。上流が確からしく大きく悪いときだけ早期停止する。
3. CPA 判定は Gamma-Poisson で「新CRの効率がコントロールより良い確率」を使う。
4. 上限費用まで使っても決着しなければ打ち切る(ずるずる続けない)。
5. 判定は提案として記録する。Meta への反映(停止・予算変更)は dry_run=false かつ
   auto_execute に含まれる判定だけ。既定は STOP のみ自動可、SCALE は人の承認を必須にする。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ..detect.funnel import STAGE_LABEL, decompose
from ..models import FunnelTotals
from ..stats import compare_cost_efficiency, compare_rates


class Decision(str, Enum):
    STOP = "STOP"
    CONTINUE = "CONTINUE"
    SCALE = "SCALE"  # 横展: 予算増・別キャンペーン/別アカウントへの複製
    EXTEND_TEST = "EXTEND_TEST"  # 判定保留のまま上限まで継続


@dataclass(frozen=True)
class LifecyclePolicy:
    early_look_spend_x: float = 0.5  # 目標CPA×0.5 から上流指標だけ見る
    decide_spend_x: float = 2.0  # 目標CPA×2 から CPA で判定
    max_spend_x: float = 4.0  # 目標CPA×4 で打ち切り判定
    early_stop_ctr_prob_worse: float = 0.97
    early_stop_ctr_rel: float = -0.35  # CTR がコントロール比 -35% 以下
    scale_prob_better: float = 0.90
    stop_prob_better: float = 0.15


@dataclass
class LifecycleResult:
    ad_id: str
    decision: Decision
    reason: str
    prob_better: float | None
    spend: float
    cv: float
    next_hypothesis: str
    evidence: dict = field(default_factory=dict)


def decide(
    ad_id: str,
    new: FunnelTotals,
    control: FunnelTotals,
    *,
    target_cpa: float,
    policy: LifecyclePolicy = LifecyclePolicy(),
    feature_diff: dict[str, tuple[str, str]] | None = None,
) -> LifecycleResult:
    """feature_diff は {特徴量名: (新CRの値, コントロールの値)}。仮説文の材料にする。"""
    spend_x = new.spend / target_cpa
    ctr = compare_rates(new.link_clicks, new.impressions, control.link_clicks, control.impressions)
    eff = compare_cost_efficiency(new.cv, new.spend, control.cv, control.spend, prior_cpa=target_cpa)
    ev = {
        "spend_x_target": round(spend_x, 2),
        "ctr_new": ctr.rate_current,
        "ctr_control": ctr.rate_baseline,
        "ctr_prob_worse": round(ctr.prob_worse, 3),
        "prob_better": round(eff.prob_better, 3),
        "lift_median": round(eff.lift_median, 3),
    }
    hyp = next_hypothesis(new, control, feature_diff or {})

    def result(d: Decision, reason: str, p: float | None = eff.prob_better) -> LifecycleResult:
        return LifecycleResult(ad_id, d, reason, p, new.spend, new.cv, hyp, ev)

    if spend_x < policy.early_look_spend_x:
        return result(Decision.CONTINUE, f"学習中(費用が目標CPAの{spend_x:.1f}倍)", None)

    if spend_x < policy.decide_spend_x:
        if (
            ctr.prob_worse >= policy.early_stop_ctr_prob_worse
            and ctr.relative_change <= policy.early_stop_ctr_rel
        ):
            return result(
                Decision.STOP,
                f"早期停止: CTR がコントロール比 {ctr.relative_change:+.0%}(悪化確率 {ctr.prob_worse:.0%})。"
                "冒頭で止まっていないので CV まで待つ価値が低い",
            )
        return result(Decision.CONTINUE, f"上流指標は許容範囲。CPA 判定は費用が目標CPAの{policy.decide_spend_x:.0f}倍に達してから")

    if eff.prob_better >= policy.scale_prob_better:
        return result(
            Decision.SCALE,
            f"コントロールより CPA が良い確率 {eff.prob_better:.0%}(効率 {eff.lift_median:.2f}倍)。横展候補",
        )
    if eff.prob_better <= policy.stop_prob_better:
        return result(Decision.STOP, f"コントロールより CPA が良い確率 {eff.prob_better:.0%}。停止")
    if spend_x >= policy.max_spend_x:
        cpa = new.cpa
        if cpa <= target_cpa:
            return result(
                Decision.CONTINUE,
                f"上限費用に到達。コントロールとは差が付かないが CPA ¥{cpa:,.0f} は目標内なので本配信に残す",
            )
        return result(Decision.STOP, f"上限費用に到達し決着せず、CPA も目標超過(¥{cpa:,.0f})。打ち切り")
    return result(Decision.EXTEND_TEST, f"判定保留(良い確率 {eff.prob_better:.0%})。上限の目標CPA×{policy.max_spend_x:.0f}まで継続")


def next_hypothesis(new: FunnelTotals, control: FunnelTotals, feature_diff: dict[str, tuple[str, str]]) -> str:
    """ファネルのどの段で差が出たか × 特徴量の差分 から、次に試す仮説を1文で作る。

    ルールベースで作る(LLM に任せると、差分に無い要素を理由に挙げがちなため)。
    文章を整える必要があれば generate.script 側で LLM に渡す。
    """
    if new.impressions == 0 or control.impressions == 0:
        return "データ不足のため仮説なし"
    d = decompose(new, control)
    diffs = "、".join(f"{k}: {a}(既存 {b})" for k, a, b in ((k, *v) for k, v in feature_diff.items())) or "特徴量差分なし"
    better = [s for s in d.stages if s.log_contribution == s.log_contribution and s.log_contribution < -0.1]
    worse = [s for s in d.stages if s.log_contribution == s.log_contribution and s.log_contribution > 0.1]
    parts = []
    if better:
        parts.append("良かった段: " + "・".join(STAGE_LABEL[s.stage] for s in better))
    if worse:
        parts.append("悪かった段: " + "・".join(STAGE_LABEL[s.stage] for s in worse))
    stage_names = {s.stage for s in worse}
    if {"ctr"} & stage_names:
        idea = "冒頭フックを既存勝ちCRの型に戻し、それ以外の差分(訴求軸等)だけを残して再検証"
    elif {"cvr", "lpv_rate"} & stage_names and any(s.stage == "ctr" for s in better):
        idea = "クリックは取れているので、CRの訴求とLPファーストビューの一致を高めた版(同じフック)を検証"
    elif not worse and better:
        idea = "良かった段を生んだ差分を維持し、次は別アカウント/別キャンペーンへ横展して再現性を確認"
    else:
        idea = "差分が複数あり原因が切り分けられないので、差分を1つだけにした派生CRで再検証"
    return f"{' / '.join(parts) or '段階差なし'}。差分: {diffs}。次の仮説: {idea}"
