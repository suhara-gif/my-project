from meta_autopilot.lifecycle.decide import Decision, LifecyclePolicy, decide
from meta_autopilot.lifecycle.execute import should_execute
from meta_autopilot.models import FunnelTotals as F

CONTROL = F(300_000, 150_000, 1_800, 1_500, 40)  # CPA 7,500, CTR 1.2%
T = 8_000


def test_learning_phase_continues():
    r = decide("n", F(3_000, 1_500, 10, 8, 0), CONTROL, target_cpa=T)
    assert r.decision == Decision.CONTINUE and r.prob_better is None


def test_early_stop_on_bad_ctr():
    r = decide("n", F(10_000, 10_000, 40, 30, 0), CONTROL, target_cpa=T)  # CTR 0.4%
    assert r.decision == Decision.STOP


def test_scale_clear_winner():
    r = decide("n", F(40_000, 20_000, 300, 250, 12), CONTROL, target_cpa=T)
    assert r.decision == Decision.SCALE


def test_stop_clear_loser():
    r = decide("n", F(40_000, 20_000, 240, 200, 0), CONTROL, target_cpa=T)
    assert r.decision == Decision.STOP


def test_max_spend_within_target_keeps_running():
    r = decide("n", F(33_000, 16_000, 190, 160, 5), CONTROL, target_cpa=T, policy=LifecyclePolicy(max_spend_x=4.0))
    # 決着はしないが CPA 6,600 は目標内 → 本配信に残す
    assert r.decision == Decision.CONTINUE and "上限費用" in r.reason


def test_hypothesis_mentions_feature_diff():
    r = decide("n", F(40_000, 20_000, 300, 250, 12), CONTROL, target_cpa=T, feature_diff={"hook_type": ("anxiety", "number")})
    assert "hook_type" in r.next_hypothesis


def test_execute_gate():
    r = decide("n", F(40_000, 20_000, 240, 200, 0), CONTROL, target_cpa=T)
    assert not should_execute(r, dry_run=True, auto_execute=["STOP"])
    assert should_execute(r, dry_run=False, auto_execute=["STOP"])
    assert not should_execute(r, dry_run=False, auto_execute=[])
    s = decide("n", F(40_000, 20_000, 300, 250, 12), CONTROL, target_cpa=T)
    assert not should_execute(s, dry_run=False, auto_execute=["STOP", "SCALE"])  # 横展は自動実行しない
