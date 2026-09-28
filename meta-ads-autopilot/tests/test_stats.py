from meta_autopilot.stats import compare_cost_efficiency, compare_rates, shrunk_cpa, slope_prob_negative


def test_rates_clear_drop_is_detected():
    r = compare_rates(50, 10_000, 150, 10_000)
    assert r.prob_worse > 0.99
    assert round(r.relative_change, 2) == -0.67


def test_rates_tiny_sample_is_not_confident():
    # 1/20 vs 2/20 は点推定で半減だが、確信できる差ではない
    r = compare_rates(1, 20, 2, 20)
    assert r.prob_worse < 0.8


def test_rates_clamps_success_over_trials():
    r = compare_rates(12, 10, 5, 10)
    assert r.rate_current == 1.0


def test_cost_efficiency_zero_cv_not_extreme():
    # 目標CPA 1万円で 5千円使って CV0 → まだ何も言えない
    c = compare_cost_efficiency(0, 5_000, 10, 100_000, prior_cpa=10_000)
    assert 0.2 < c.prob_better < 0.6


def test_cost_efficiency_clear_winner():
    c = compare_cost_efficiency(20, 100_000, 5, 100_000, prior_cpa=10_000)
    assert c.prob_better > 0.99


def test_shrunk_cpa_finite_with_zero_cv():
    assert shrunk_cpa(0, 30_000, prior_cpa=10_000) == 40_000


def test_slope_negative():
    slope, p = slope_prob_negative([0.02, 0.019, 0.017, 0.016, 0.014, 0.012, 0.011])
    assert slope < 0 and p > 0.95


def test_slope_too_short():
    assert slope_prob_negative([0.1, 0.2]) == (0.0, 0.5)
