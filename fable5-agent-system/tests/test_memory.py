from fable5 import HAIKU, MemoryStore, SONNET


def make_store(tmp_path):
    return MemoryStore(tmp_path / "memory")


def test_store_and_persist(tmp_path):
    store = make_store(tmp_path)
    store.store_episode(
        {"type": "analysis", "description": "競合分析"},
        "分析結果...",
        {"success": True, "quality_score": 0.9, "model": SONNET, "cost": 0.05},
    )
    reloaded = make_store(tmp_path)
    assert len(reloaded.episodic) == 1
    assert reloaded.episodic[0]["task"]["type"] == "analysis"


def test_find_similar_prefers_same_type_and_description(tmp_path):
    store = make_store(tmp_path)
    store.store_episode(
        {"type": "analysis", "description": "SNS 競合分析レポート"},
        "",
        {"success": True, "quality_score": 0.9, "model": SONNET, "cost": 0.1},
    )
    store.store_episode(
        {"type": "writing", "description": "ブログ記事の執筆"},
        "",
        {"success": True, "quality_score": 0.9, "model": SONNET, "cost": 0.1},
    )
    similar = store.find_similar({"type": "analysis", "description": "SNS の競合を分析"})
    assert len(similar) == 1
    assert similar[0]["task"]["type"] == "analysis"


def test_best_model_balances_quality_and_cost(tmp_path):
    store = make_store(tmp_path)
    for _ in range(3):
        store.store_episode(
            {"type": "verification", "description": "チェック"},
            "",
            {"success": True, "quality_score": 0.88, "model": HAIKU, "cost": 0.001},
        )
    store.store_episode(
        {"type": "verification", "description": "チェック"},
        "",
        {"success": False, "quality_score": 0.4, "model": SONNET, "cost": 0.05},
    )
    best = store.get_best_model_for_type("verification")
    assert best["model"] == HAIKU
    assert best["success_rate"] == 1.0


def test_context_injection_includes_high_quality_successes(tmp_path):
    store = make_store(tmp_path)
    store.store_episode(
        {"type": "analysis", "description": "市場規模の分析"},
        "",
        {"success": True, "quality_score": 0.92, "model": SONNET, "cost": 0.1},
    )
    store.working["収集済みデータ"] = "競合3社分"
    section = store.build_context_injection({"type": "analysis", "description": "市場分析"})
    assert "過去の類似タスク成功例" in section
    assert "作業記憶" in section


def test_count_similar_successes(tmp_path):
    store = make_store(tmp_path)
    for _ in range(3):
        store.store_episode(
            {"type": "analysis", "description": "競合他社のSNS分析"},
            "",
            {"success": True, "quality_score": 0.9, "model": SONNET, "cost": 0.1},
        )
    n = store.count_similar_successes(
        {"type": "analysis", "description": "競合他社のSNSを分析する"}
    )
    assert n == 3
