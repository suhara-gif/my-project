from fable5 import HAIKU, OPUS, SONNET, MemoryStore, Router, TaskComplexity


def test_verification_tasks_route_to_haiku():
    decision = Router().route({"type": "verification", "description": "事実確認を行う"})
    assert decision.model == HAIKU


def test_critical_tasks_route_to_opus():
    decision = Router().route({"description": "本番用の最終レポートを最高品質で作成"})
    assert decision.complexity == TaskComplexity.CRITICAL
    assert decision.model == OPUS


def test_required_quality_overrides_description():
    decision = Router().route(
        {"description": "短い要約を作成", "required_quality": "critical"}
    )
    assert decision.model == OPUS


def test_moderate_analysis_routes_to_sonnet():
    decision = Router().route({"description": "競合他社のデータを分析して比較する"})
    assert decision.model == SONNET


def test_simple_tasks_route_to_haiku():
    decision = Router().route({"description": "この文章を要約してください"})
    assert decision.model == HAIKU


def test_complex_code_routes_to_opus():
    decision = Router().route(
        {"type": "code", "description": "システム全体のアーキテクチャを設計し実装する"}
    )
    assert decision.model == OPUS


def test_budget_constraint_downgrades_model(tmp_path):
    decision = Router().route(
        {
            "description": "本番用の最終レポートを作成",
            "estimated_tokens": 1_000_000,
            "budget_usd": 0.01,
        }
    )
    # Opus では 1M トークンは $0.01 に収まらないため安いモデルへ落ちる
    assert decision.model != OPUS
    assert any("budget" in o for o in decision.overrides)


def test_memory_success_overrides_default(tmp_path):
    memory = MemoryStore(tmp_path / "memory")
    for _ in range(5):
        memory.store_episode(
            {"type": "analysis", "description": "分析タスク"},
            "output",
            {"success": True, "quality_score": 0.95, "model": OPUS, "cost": 0.1},
        )
    decision = Router(memory=memory).route(
        {"type": "analysis", "description": "データを分析する"}
    )
    assert decision.model == OPUS
    assert any("memory" in o for o in decision.overrides)
