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
