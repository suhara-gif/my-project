"""CPA 悪化をファネル段階(CPM→CTR→LPV率→CVR)に分解し、どこで崩れたかを判定する。

分解は対数で行う。CPA = CPM/1000 / (CTR × LPV率 × CVR) なので

    ln(CPA現/CPA基) = ln(CPM比) − ln(CTR比) − ln(LPV率比) − ln(CVR比)

が厳密に成り立ち、各項を「CPA悪化への寄与」として足し算で読める。
寄与が大きいだけでは不十分で、その段の変化が統計的に確からしい(prob_worse が高い)ことも要求する。
CV が少ない段(CVR)は prob_worse が上がりにくいので、上流の段ほど早く検知できる設計になっている。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..models import Alert, FunnelTotals, Severity
from ..stats import compare_rates

STAGES = ("cpm", "ctr", "lpv_rate", "cvr")

STAGE_LABEL = {
    "cpm": "CPM(配信単価)",
    "ctr": "CTR(クリック率)",
    "lpv_rate": "LPV率(クリック→LP表示)",
    "cvr": "CVR(LP表示→CV)",
}

# 段ごとの一次原因候補と対応案。原因の断定はせず「まず見る場所」を示す。
STAGE_PLAYBOOK = {
    "cpm": (
        "オークション競合の上昇、オーディエンス枯渇、配置の変化、または品質ランキングの低下",
        [
            "Ads Manager で品質・エンゲージメント・コンバージョン率ランキングを確認",
            "フリークエンシーが上がっていればオーディエンス拡張か新CR投入",
            "配置別の CPM を比較し、特定配置への寄りを確認",
        ],
    ),
    "ctr": (
        "CRの摩耗(同一ユーザーへの反復表示)、冒頭フックの弱さ、または配信先の変化",
        [
            "フリークエンシーと勝ちCRの CTR 推移を確認(winner_fatigue アラートも参照)",
            "冒頭2秒のフック違いの新CRを投入",
        ],
    ),
    "lpv_rate": (
        "LP の表示速度悪化・リンク切れ・計測タグの不具合、または誤タップの多い配置への寄り",
        [
            "LP を実機で開いて表示速度とリンク先を確認",
            "ピクセル/LPVイベントの発火を Events Manager で確認",
            "Audience Network 等の配置寄りがないか確認",
        ],
    ),
    "cvr": (
        "LP・フォームの変更、求人内容とCR訴求のズレ、または CV 計測の不具合",
        [
            "直近の LP・フォーム変更有無を確認",
            "CV イベント(Mechanic_Lead / 登録完了)の発火数をサイト側の登録数と突き合わせる",
            "CRの訴求と LP のファーストビューが一致しているか確認",
        ],
    ),
}


@dataclass(frozen=True)
class StageResult:
    stage: str
    current: float
    baseline: float
    log_contribution: float  # CPA の対数変化への寄与(正 = CPA を悪化させた)
    prob_worse: float  # その段が悪化している確率(CPM は「上昇」確率の代用値)


@dataclass(frozen=True)
class FunnelDecomposition:
    cpa_current: float
    cpa_baseline: float
    log_cpa_change: float
    stages: tuple[StageResult, ...]

    @property
    def primary(self) -> StageResult | None:
        """寄与が最大の悪化段。悪化段が無ければ None。"""
        worse = [s for s in self.stages if s.log_contribution > 0]
        return max(worse, key=lambda s: s.log_contribution) if worse else None


def _log_ratio(cur: float, base: float) -> float:
    if not (cur > 0 and base > 0) or math.isinf(cur) or math.isinf(base):
        return float("nan")
    return math.log(cur / base)


def _cpm_prob_worse(cur: FunnelTotals, base: FunnelTotals) -> float:
    """CPM はコストなので二項モデルが使えない。インプレッションが十分なら点推定で十分安定するため、
    上昇していれば 1、下降していれば 0 を返す簡易値にする(インプレッション数のガードは呼び出し側)。"""
    return 1.0 if cur.cpm > base.cpm else 0.0


def decompose(cur: FunnelTotals, base: FunnelTotals, *, seed: int | None = 0) -> FunnelDecomposition:
    """現在期間と基準期間のファネルを比較して段階別寄与を返す。

    CV が 0 の期間は CPA が無限大になり対数分解できないので、CVR 段は nan になる。
    その場合も上流3段の寄与と確率は計算される(上流で崩れていれば CV 0 件でも検知できる)。
    """
    ctr = compare_rates(cur.link_clicks, cur.impressions, base.link_clicks, base.impressions, seed=seed)
    lpv = compare_rates(cur.lpv, cur.link_clicks, base.lpv, base.link_clicks, seed=seed)
    cvr = compare_rates(cur.cv, cur.lpv, base.cv, base.lpv, seed=seed)

    stages = (
        StageResult("cpm", cur.cpm, base.cpm, _log_ratio(cur.cpm, base.cpm), _cpm_prob_worse(cur, base)),
        StageResult("ctr", cur.ctr, base.ctr, -_log_ratio(cur.ctr, base.ctr), ctr.prob_worse),
        StageResult("lpv_rate", cur.lpv_rate, base.lpv_rate, -_log_ratio(cur.lpv_rate, base.lpv_rate), lpv.prob_worse),
        StageResult("cvr", cur.cvr, base.cvr, -_log_ratio(cur.cvr, base.cvr), cvr.prob_worse),
    )
    return FunnelDecomposition(
        cpa_current=cur.cpa,
        cpa_baseline=base.cpa,
        log_cpa_change=_log_ratio(cur.cpa, base.cpa),
        stages=stages,
    )


@dataclass(frozen=True)
class FunnelThresholds:
    min_impressions_current: int = 3_000  # これ未満の単位は判定しない
    min_relative_worsening: float = 0.20  # 段の悪化が 20% 未満なら無視
    min_prob_worse: float = 0.90  # 段の悪化確率がこれ未満なら無視
    critical_prob_worse: float = 0.98


def detect_funnel_breaks(
    scope: str,
    cur: FunnelTotals,
    base: FunnelTotals,
    th: FunnelThresholds = FunnelThresholds(),
) -> list[Alert]:
    """確からしい悪化段ごとに Alert を返す(最大寄与の段を先頭に)。"""
    if cur.impressions < th.min_impressions_current:
        return []
    d = decompose(cur, base)
    hits: list[tuple[StageResult, float]] = []
    for s in d.stages:
        if math.isnan(s.log_contribution) or s.log_contribution <= 0:
            continue
        rel = math.exp(s.log_contribution) - 1  # この段だけで CPA を何%押し上げたか
        if rel < th.min_relative_worsening or s.prob_worse < th.min_prob_worse:
            continue
        hits.append((s, rel))
    hits.sort(key=lambda h: h[0].log_contribution, reverse=True)

    alerts = []
    for s, rel in hits:
        cause, actions = STAGE_PLAYBOOK[s.stage]
        fmt = (lambda v: f"¥{v:,.0f}") if s.stage == "cpm" else (lambda v: f"{v:.2%}")
        alerts.append(
            Alert(
                kind="funnel_break",
                severity=Severity.CRITICAL if s.prob_worse >= th.critical_prob_worse else Severity.WARN,
                scope=scope,
                title=f"{STAGE_LABEL[s.stage]}で崩れ: {fmt(s.baseline)} → {fmt(s.current)}",
                cause=f"この段だけで CPA を約{rel:.0%}押し上げ。候補: {cause}",
                actions=list(actions),
                evidence={
                    "stage": s.stage,
                    "prob_worse": round(s.prob_worse, 3),
                    "cpa_current": d.cpa_current,
                    "cpa_baseline": d.cpa_baseline,
                    "impressions_current": cur.impressions,
                    "cv_current": cur.cv,
                },
            )
        )
    return alerts
