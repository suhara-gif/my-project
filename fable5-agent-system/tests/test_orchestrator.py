from fable5 import MockLLMClient, Orchestrator

GOOD = (
    "# 分析結果\n\n## 投稿頻度\n- データあり\n\n## エンゲージメント\n"
    "- B社が最高\n\n## 示唆\n1. 質重視\n2. 動画強化\n"
)


def make_orch(tmp_path, responses, session="wf_test"):
    return Orchestrator(
        session_id=session,
        llm=MockLLMClient(responses),
        base_dir=tmp_path,
        budget_usd=100.0,
    )


PHASES = [
    {
        "id": "research",
        "task": {
            "type": "analysis",
            "description": "SNSデータを調査する",
            "required_keywords": ["投稿頻度", "エンゲージメント"],
            "min_chars": 30,
        },
    },
    {
        "id": "report",
        "task": {
            "type": "analysis",
            "description": "調査結果を分析しレポート化する",
            "required_keywords": ["示唆"],
            "min_chars": 30,
        },
    },
]


def test_workflow_completes(tmp_path):
    orch = make_orch(tmp_path, [GOOD, GOOD])
    results = orch.run_workflow(PHASES)
    assert results["research"].status == "success"
    assert results["report"].status == "success"
    assert orch.state.state["status"] == "completed"


def test_workflow_resumes_from_checkpoint(tmp_path):
    orch = make_orch(tmp_path, [GOOD, GOOD])
    orch.run_workflow(PHASES)

    # 同じセッション ID で再構築 → 両フェーズともチェックポイントから復元
    resumed = make_orch(tmp_path, [], session="wf_test")
    results = resumed.run_workflow(PHASES)
    assert isinstance(results["research"], dict)
    assert isinstance(results["report"], dict)
    assert len(resumed.llm.calls) == 0  # LLM は一度も呼ばれない


def test_workflow_escalates_and_stops(tmp_path):
    orch = make_orch(tmp_path, ["だめ"] * 3)
    results = orch.run_workflow(PHASES)
    assert results["research"].status == "escalate"
    assert "report" not in results
    assert orch.state.state["status"] == "escalated"


def test_routing_knowledge_is_updated(tmp_path):
    orch = make_orch(tmp_path, [GOOD, GOOD])
    orch.run_workflow(PHASES)
    best = orch.memory.get_best_model_for_type("analysis")
    assert best is not None
    assert best["success_rate"] > 0
