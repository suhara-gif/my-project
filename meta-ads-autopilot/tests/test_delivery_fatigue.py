from meta_autopilot.detect.delivery import AdWindow, detect_delivery_skew, hhi
from meta_autopilot.detect.fatigue import AdHistory, detect_winner_fatigue
from meta_autopilot.models import FunnelTotals as F


def test_hhi():
    assert hhi([1.0]) == 1.0 and hhi([0.5, 0.5]) == 0.5


def test_skew_to_loser_alerts():
    ads = [
        AdWindow("a", "負けCR", F(80_000, 40_000, 400, 300, 1), F(20_000, 10_000, 100, 80, 1)),
        AdWindow("b", "勝ちCR", F(20_000, 10_000, 150, 120, 6), F(60_000, 30_000, 400, 330, 12)),
    ]
    alerts = detect_delivery_skew("camp", ads, target_cpa=8_000)
    assert len(alerts) == 1 and alerts[0].evidence["ad_id"] == "a"


def test_skew_to_winner_is_fine():
    ads = [
        AdWindow("a", "勝ちCR", F(80_000, 40_000, 400, 300, 14), F(20_000, 10_000, 100, 80, 3)),
        AdWindow("b", "他", F(20_000, 10_000, 100, 80, 2), F(60_000, 30_000, 300, 250, 6)),
    ]
    assert detect_delivery_skew("camp", ads, target_cpa=8_000) == []


def test_winner_fatigue_needs_ctr_or_frequency_signal():
    base = F(200_000, 100_000, 1_500, 1_200, 30)
    cur = F(70_000, 35_000, 300, 240, 2)
    kw = dict(ad_id="w", ad_name="勝ち", baseline=base, current=cur)
    falling = AdHistory(**kw, daily_ctr=[0.015, 0.014, 0.012, 0.011, 0.010, 0.009, 0.008], daily_impressions=[5000] * 7)
    flat = AdHistory(**kw, daily_ctr=[0.009, 0.0085, 0.009, 0.0085, 0.009, 0.0085, 0.009], daily_impressions=[5000] * 7)
    assert detect_winner_fatigue("s", falling, target_cpa=8_000)
    assert detect_winner_fatigue("s", flat, target_cpa=8_000) == []


def test_non_winner_is_ignored():
    h = AdHistory("x", "x", F(200_000, 100_000, 1_000, 800, 5), F(70_000, 35_000, 200, 150, 0), [0.01] * 7, [1000] * 7)
    assert detect_winner_fatigue("s", h, target_cpa=8_000) == []
