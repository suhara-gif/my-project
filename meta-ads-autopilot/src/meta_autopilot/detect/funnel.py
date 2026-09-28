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


# 段ごとの (分子, 分母) の取り出し方。CPM は「費用 / インプレッション」で、上がるほど悪い。
_STAGE_PARTS = {
    "cpm": (lambda t: t.spend, lambda t: t.impressions),
    "ctr": (lambda t: t.link_clicks, lambda t: t.impressions),
    "lpv_rate": (lambda t: t.lpv, lambda t: t.link_clicks),
    "cvr": (lambda t: t.cv, lambda t: t.lpv),
}


@dataclass(frozen=True)
class AdGap:
    ad_id: str
    ad_name: str
    share_of_gap: float  # 段の不足分(CVR なら「基準のCVRなら取れていたはずのCV」)のうち、この広告が占める割合
    is_new: bool  # 基準期間にほとんど配信されていなかった広告
    share_shift: float  # その段の分母(CVRならLPV)に占めるシェアの変化(現在 − 基準)
    cpa_current: float


def attribute_stage_gap(stage: str, ads: list, base_campaign: FunnelTotals, *, new_share_max: float = 0.05) -> list[AdGap]:
    """キャンペーンの段の悪化を、どの広告が生んだかに分ける。

    各広告について「現在の分母 × (キャンペーン基準の率 − その広告の現在の率)」を不足分とする
    (CPM は逆向き)。合計はキャンペーン全体の不足分に一致する。
    勝ちCRの停止や新CRへの配信の寄りで率が下がったケースを、LP・計測の問題と取り違えないために使う。
    """
    num, den = _STAGE_PARTS[stage]
    base_den = den(base_campaign)
    if not base_den:
        return []
    base_rate = num(base_campaign) / base_den
    total_base_den = sum(den(a.baseline) for a in ads) or 1.0
    total_cur_den = sum(den(a.current) for a in ads) or 1.0
    gaps = []
    for a in ads:
        d_cur = den(a.current)
        if not d_cur:
            continue
        gap = d_cur * base_rate - num(a.current)
        if stage == "cpm":
            gap = -gap  # 費用が基準より多くかかった分
        gaps.append((a, gap))
    total = sum(g for _, g in gaps)
    if total <= 0:
        return []
    out = [
        AdGap(
            a.ad_id,
            a.ad_name,
            g / total,
            den(a.baseline) / total_base_den <= new_share_max,
            den(a.current) / total_cur_den - den(a.baseline) / total_base_den,
            a.current.cpa,
        )
        for a, g in gaps
        if g > 0
    ]
    return sorted(out, key=lambda x: -x.share_of_gap)


def detect_funnel_breaks(
    scope: str,
    cur: FunnelTotals,
    base: FunnelTotals,
    th: FunnelThresholds = FunnelThresholds(),
    *,
    ads: list | None = None,
    shift_pt: float = 0.20,
) -> list[Alert]:
    """確からしい悪化段ごとに Alert を返す(最大寄与の段を先頭に)。

    ads(detect.delivery.AdWindow のリスト)を渡すと、不足分の内訳を広告別に出し、
    1本の広告で過半を説明できるときは原因をその広告に絞る。
    """
    if cur.impressions < th.min_impressions_current:
        return []
    d = decompose(cur, base)
    # 他の段の改善で相殺され、CPA 全体は悪化していないなら通知しない
    if not math.isnan(d.log_cpa_change) and math.exp(d.log_cpa_change) - 1 < th.min_relative_worsening:
        return []
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
        cause_text = f"この段だけで CPA を約{rel:.0%}押し上げ。候補: {cause}"
        actions = list(actions)
        gaps = attribute_stage_gap(s.stage, ads, base) if ads else []
        if gaps:
            top = gaps[0]
            breakdown = "、".join(f"{g.ad_name} {g.share_of_gap:.0%}" for g in gaps[:3])
            shifted = top.is_new or top.share_shift >= shift_pt
            if top.share_of_gap >= 0.5 and shifted:
                kind = "新しく配信が始まったCR" if top.is_new else f"配信シェアが{top.share_shift:+.0%}pt増えたCR"
                cause_text = (
                    f"この段だけで CPA を約{rel:.0%}押し上げ。不足分の{top.share_of_gap:.0%}は{kind}「{top.ad_name}」。"
                    f"LP・計測よりも、配信構成の変化(このCRへの寄り)が主因の可能性が高い。内訳: {breakdown}"
                )
                first = (
                    f"「{top.ad_name}」の停止、または予算上限のある広告セットへの分離を検討"
                    if top.cpa_current > d.cpa_baseline
                    else f"「{top.ad_name}」の CPA 自体は基準以内なので停止はしない。他CRの配信減の理由を確認"
                )
                actions = [first, "直前まで成果を出していたCRが止まっていないか確認(winner_dropout アラートも参照)"] + actions[:1]
            elif top.share_of_gap >= 0.5:
                cause_text = (
                    f"この段だけで CPA を約{rel:.0%}押し上げ。不足分の{top.share_of_gap:.0%}は「{top.ad_name}」自体の悪化"
                    f"(配信シェアはほぼ変わらず)。候補: {cause}"
                )
                actions = [f"「{top.ad_name}」の {STAGE_LABEL[s.stage]} の日次推移を確認"] + actions
            else:
                cause_text += f"。内訳: {breakdown}"
        # CPM は確率モデルを持たない簡易判定なので critical にしない
        critical = s.prob_worse >= th.critical_prob_worse and s.stage != "cpm"
        fmt = (lambda v: f"¥{v:,.0f}") if s.stage == "cpm" else (lambda v: f"{v:.2%}")
        alerts.append(
            Alert(
                kind="funnel_break",
                severity=Severity.CRITICAL if critical else Severity.WARN,
                scope=scope,
                title=f"{STAGE_LABEL[s.stage]}で崩れ: {fmt(s.baseline)} → {fmt(s.current)}",
                cause=cause_text,
                actions=actions,
                evidence={
                    "stage": s.stage,
                    "prob_worse": round(s.prob_worse, 3),
                    "cpa_current": d.cpa_current,
                    "cpa_baseline": d.cpa_baseline,
                    "impressions_current": cur.impressions,
                    "cv_current": cur.cv,
                    "gap_by_ad": [(g.ad_id, round(g.share_of_gap, 3)) for g in gaps[:5]],
                },
            )
        )
    return alerts
