"""配信量の偏り(どこに費用が寄っているか)を検知する。

ASC/CBO では Meta 側が費用配分を決めるため、成績の悪いCRに費用が寄ることがある。
単に「寄っている」だけでは異常ではない(勝ちCRに寄るのは正常)ので、
**寄っている先の CPA が、同じキャンペーン内の他CR合計より確からしく悪い**ときだけ警報にする。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Alert, FunnelTotals, Severity
from ..stats import compare_cost_efficiency, shrunk_cpa


@dataclass(frozen=True)
class AdWindow:
    ad_id: str
    ad_name: str
    current: FunnelTotals  # 直近期間(既定: 7日)
    baseline: FunnelTotals  # 比較期間(既定: その前の21日)


@dataclass(frozen=True)
class DeliveryThresholds:
    top_share: float = 0.60  # 直近の費用シェアがこれ以上の広告を「寄り先」とみなす
    share_jump_pt: float = 0.25  # 基準期間からのシェア上昇幅(ポイント)
    prob_worse: float = 0.80  # 寄り先の CPA が他より悪い確率
    min_campaign_spend: float = 30_000


def hhi(shares: list[float]) -> float:
    """ハーフィンダール指数(0〜1)。1 に近いほど1本に集中。"""
    return float(sum(s * s for s in shares))


def detect_delivery_skew(
    campaign_scope: str,
    ads: list[AdWindow],
    *,
    target_cpa: float,
    th: DeliveryThresholds = DeliveryThresholds(),
) -> list[Alert]:
    total_cur = sum(a.current.spend for a in ads)
    total_base = sum(a.baseline.spend for a in ads)
    if total_cur < th.min_campaign_spend or len(ads) < 2:
        return []

    alerts: list[Alert] = []
    shares_cur = {a.ad_id: a.current.spend / total_cur for a in ads}
    shares_base = {a.ad_id: (a.baseline.spend / total_base if total_base else 0.0) for a in ads}

    for a in ads:
        share = shares_cur[a.ad_id]
        jump = share - shares_base[a.ad_id]
        if share < th.top_share and jump < th.share_jump_pt:
            continue
        rest = FunnelTotals.zero()
        for o in ads:
            if o.ad_id != a.ad_id:
                rest = rest + o.current
        if rest.spend == 0:
            continue
        cmp = compare_cost_efficiency(
            a.current.cv, a.current.spend, rest.cv, rest.spend, prior_cpa=target_cpa
        )
        prob_worse = 1 - cmp.prob_better
        if prob_worse < th.prob_worse:
            continue
        a_cpa = shrunk_cpa(a.current.cv, a.current.spend, prior_cpa=target_cpa)
        rest_cpa = shrunk_cpa(rest.cv, rest.spend, prior_cpa=target_cpa)
        alerts.append(
            Alert(
                kind="delivery_skew",
                severity=Severity.CRITICAL if share >= 0.8 else Severity.WARN,
                scope=campaign_scope,
                title=f"配信が成績の悪いCRに寄っている: {a.ad_name}(費用シェア {share:.0%})",
                cause=(
                    f"この広告の CPA(縮約後) ¥{a_cpa:,.0f} は同キャンペーン他CR合計 ¥{rest_cpa:,.0f} より"
                    f"悪い確率 {prob_worse:.0%}。シェアは基準期間から {jump:+.0%}pt。"
                    "Meta の配分がCTR等の上流指標で寄せている可能性がある。"
                ),
                actions=[
                    "この広告を停止するか、同キャンペーン内で予算の上限を持つ広告セットへ分離",
                    "他CRに配信が回るか 2〜3日観察(停止直後は学習で CPA がぶれる)",
                ],
                evidence={
                    "ad_id": a.ad_id,
                    "share_current": round(share, 3),
                    "share_baseline": round(shares_base[a.ad_id], 3),
                    "hhi_current": round(hhi(list(shares_cur.values())), 3),
                    "prob_worse": round(prob_worse, 3),
                },
            )
        )
    return alerts
