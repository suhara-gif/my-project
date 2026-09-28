"""パイプライン全体で使う共通のデータ型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


@dataclass(frozen=True)
class FunnelTotals:
    """ある期間・ある単位(広告/キャンペーン等)のファネル合計値。

    CPA = CPM/1000 ÷ (CTR × LPV率 × CVR) が恒等的に成り立つよう、各段の分母は1つ前の段の分子にする。
      CTR    = link_clicks / impressions
      LPV率  = lpv / link_clicks
      CVR    = cv / lpv
    """

    spend: float
    impressions: float
    link_clicks: float
    lpv: float
    cv: float

    @property
    def cpm(self) -> float:
        return self.spend / self.impressions * 1000 if self.impressions else float("nan")

    @property
    def ctr(self) -> float:
        return self.link_clicks / self.impressions if self.impressions else float("nan")

    @property
    def lpv_rate(self) -> float:
        return self.lpv / self.link_clicks if self.link_clicks else float("nan")

    @property
    def cvr(self) -> float:
        return self.cv / self.lpv if self.lpv else float("nan")

    @property
    def cpa(self) -> float:
        return self.spend / self.cv if self.cv else float("inf")

    def __add__(self, other: "FunnelTotals") -> "FunnelTotals":
        return FunnelTotals(
            spend=self.spend + other.spend,
            impressions=self.impressions + other.impressions,
            link_clicks=self.link_clicks + other.link_clicks,
            lpv=self.lpv + other.lpv,
            cv=self.cv + other.cv,
        )

    @staticmethod
    def zero() -> "FunnelTotals":
        return FunnelTotals(0.0, 0.0, 0.0, 0.0, 0.0)


@dataclass(frozen=True)
class AdDailyRow:
    """広告×日の1行(BigQuery の v_ad_daily と同じ粒度)。"""

    date: date
    account_id: str
    campaign_id: str
    campaign_name: str
    adset_id: str
    ad_id: str
    ad_name: str
    creative_id: str | None
    totals: FunnelTotals
    frequency: float | None = None


class Severity(str, Enum):
    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"


@dataclass
class Alert:
    """Slack に流す1件の異常。原因と対応案を必ずセットで持つ。"""

    kind: str  # funnel_break / delivery_skew / winner_fatigue / data_gap など
    severity: Severity
    scope: str  # 例: "campaign:1234 ASC_ブランド訴求"
    title: str
    cause: str
    actions: list[str]
    evidence: dict = field(default_factory=dict)
