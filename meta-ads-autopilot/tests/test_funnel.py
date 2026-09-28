import math

from meta_autopilot.detect.funnel import decompose, detect_funnel_breaks
from meta_autopilot.models import FunnelTotals


def test_log_decomposition_is_exact():
    base = FunnelTotals(spend=100_000, impressions=100_000, link_clicks=1_000, lpv=800, cv=20)
    cur = FunnelTotals(spend=120_000, impressions=90_000, link_clicks=700, lpv=500, cv=12)
    d = decompose(cur, base)
    assert math.isclose(sum(s.log_contribution for s in d.stages), d.log_cpa_change, rel_tol=1e-9)


def test_ctr_break_is_primary():
    base = FunnelTotals(spend=100_000, impressions=100_000, link_clicks=1_500, lpv=1_200, cv=30)
    cur = FunnelTotals(spend=100_000, impressions=100_000, link_clicks=800, lpv=640, cv=16)
    alerts = detect_funnel_breaks("c1", cur, base)
    assert alerts and alerts[0].evidence["stage"] == "ctr"
    assert all(a.evidence["stage"] != "cvr" for a in alerts)  # CVR は変わっていない


def test_lpv_break_detected_even_with_zero_cv():
    base = FunnelTotals(spend=50_000, impressions=50_000, link_clicks=800, lpv=700, cv=10)
    cur = FunnelTotals(spend=50_000, impressions=50_000, link_clicks=800, lpv=300, cv=0)
    stages = [a.evidence["stage"] for a in detect_funnel_breaks("c1", cur, base)]
    assert "lpv_rate" in stages


def test_small_volume_is_skipped():
    base = FunnelTotals(10_000, 5_000, 50, 40, 2)
    cur = FunnelTotals(10_000, 1_000, 2, 1, 0)
    assert detect_funnel_breaks("c1", cur, base) == []


def test_stable_funnel_no_alert():
    base = FunnelTotals(100_000, 100_000, 1_000, 800, 20)
    cur = FunnelTotals(33_000, 33_000, 330, 265, 7)
    assert detect_funnel_breaks("c1", cur, base) == []


from meta_autopilot.detect.delivery import AdWindow
from meta_autopilot.detect.funnel import attribute_stage_gap


def _asc_like():
    # 実データ(TW ASC 2026-09)を単純化: 勝ちCRが止まり、新CRに配信が寄って CVR が崩れた
    winner = AdWindow("w", "勝ちCR", FunnelTotals(0, 0, 0, 0, 0), FunnelTotals(170_000, 70_000, 420, 350, 13))
    new = AdWindow("n", "新CR", FunnelTotals(60_000, 30_000, 170, 150, 1), FunnelTotals(200, 100, 1, 1, 0))
    old = AdWindow("o", "既存CR", FunnelTotals(40_000, 20_000, 120, 100, 0), FunnelTotals(200_000, 90_000, 520, 430, 5))
    return [winner, new, old]


def test_gap_attributed_to_new_ad():
    ads = _asc_like()
    base = sum((a.baseline for a in ads), FunnelTotals.zero())
    gaps = attribute_stage_gap("cvr", ads, base)
    assert gaps[0].ad_id == "n" and gaps[0].is_new
    assert abs(sum(g.share_of_gap for g in gaps) - 1) < 1e-9


def test_funnel_alert_points_to_ad_not_lp():
    ads = _asc_like()
    cur = sum((a.current for a in ads), FunnelTotals.zero())
    base = sum((a.baseline for a in ads), FunnelTotals.zero())
    alerts = detect_funnel_breaks("c", cur, base, ads=ads)
    cvr = next(a for a in alerts if a.evidence["stage"] == "cvr")
    assert "新CR" in cvr.cause and "新CR" in cvr.actions[0]


def test_compensated_stage_not_alerted_and_cpm_not_critical():
    # CPM は上がったが CTR が改善して CPA はほぼ横ばい → 通知しない
    base = FunnelTotals(100_000, 30_000, 480, 400, 24)
    cur = FunnelTotals(100_000, 18_000, 450, 380, 23)
    assert detect_funnel_breaks("c", cur, base) == []
    # CPA も悪化していれば通知するが、CPM は warn 止まり
    cur2 = FunnelTotals(100_000, 18_000, 290, 240, 14)
    cpm = [a for a in detect_funnel_breaks("c", cur2, base) if a.evidence["stage"] == "cpm"]
    assert cpm and all(a.severity.value == "warn" for a in cpm)


def test_same_ad_worsening_is_not_called_mix_shift():
    # 前から配信の大半を占めていた勝ちCRで CPM が上がった(実データ TW AI動画 A1 の形)
    a1 = AdWindow("a1", "A1", FunnelTotals(90_000, 16_000, 400, 300, 17), FunnelTotals(90_000, 28_000, 450, 380, 22))
    c1 = AdWindow("c1", "C1", FunnelTotals(10_000, 2_500, 40, 30, 1), FunnelTotals(10_000, 3_000, 40, 32, 1))
    cur, base = a1.current + c1.current, a1.baseline + c1.baseline
    alerts = detect_funnel_breaks("c", cur, base, ads=[a1, c1])
    cpm = next(a for a in alerts if a.evidence["stage"] == "cpm")
    assert "自体の悪化" in cpm.cause and "停止" not in cpm.actions[0]
