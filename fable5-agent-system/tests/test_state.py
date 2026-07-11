import pytest

from fable5 import CostLimitExceeded, SONNET, StateManager


def test_checkpoint_and_resume(tmp_path):
    state = StateManager("sess_001", tmp_path)
    state.checkpoint("research", {"companies": 3})
    assert state.can_resume_from("research") == {"companies": 3}
    assert state.can_resume_from("unknown") is None

    # 別プロセスを模して再ロード
    resumed = StateManager("sess_001", tmp_path)
    assert resumed.state["status"] == "resumed"
    assert resumed.can_resume_from("research") == {"companies": 3}


def test_cost_limit_raises(tmp_path):
    state = StateManager("sess_002", tmp_path, cost_limit_usd=0.001)
    with pytest.raises(CostLimitExceeded):
        # Sonnet で 100K 入力 + 100K 出力 → $1.8 で上限超過
        state.track_cost(100_000, 100_000, SONNET)
    assert state.state["status"] == "halted_cost_limit"


def test_cost_accumulates(tmp_path):
    state = StateManager("sess_003", tmp_path, cost_limit_usd=100.0)
    state.track_cost(10_000, 2_000, SONNET)
    state.track_cost(10_000, 2_000, SONNET)
    assert state.get_total_cost() == pytest.approx(2 * (0.01 * 3.0 + 0.002 * 15.0))


def test_state_md_is_rendered(tmp_path):
    state = StateManager("sess_004", tmp_path)
    state.checkpoint("planning", {})
    state.record_error("テストエラー")
    md = state.md_path.read_text(encoding="utf-8")
    assert "# STATE.md" in md
    assert "sess_004" in md
    assert "planning" in md
    assert "テストエラー" in md
