from fable5 import (
    ExecutionLoop,
    MemoryStore,
    MockLLMClient,
    Router,
    SkillsLibrary,
    StateManager,
    VerificationEngine,
)

GOOD_OUTPUT = (
    "# 競合分析\n\n## 投稿頻度\n- A社: 週5回\n\n## エンゲージメント\n"
    "- B社が最高\n\n## 示唆\n1. 質が頻度に勝る\n2. 動画比率を上げる\n"
)

TASK = {
    "type": "analysis",
    "description": "競合SNS戦略を分析する",
    "required_keywords": ["投稿頻度", "エンゲージメント"],
    "min_chars": 50,
}


def make_loop(tmp_path, llm, max_retries=3):
    memory = MemoryStore(tmp_path / "memory")
    skills = SkillsLibrary(tmp_path / "skills.json")
    state = StateManager("test", tmp_path / "sessions", cost_limit_usd=100.0)
    return (
        ExecutionLoop(
            llm=llm,
            router=Router(memory=memory),
            verifier=VerificationEngine(),
            memory=memory,
            skills=skills,
            state=state,
            max_retries=max_retries,
        ),
        memory,
        state,
    )


def test_success_first_attempt(tmp_path):
    loop, memory, state = make_loop(tmp_path, MockLLMClient([GOOD_OUTPUT]))
    result = loop.run(TASK)
    assert result.status == "success"
    assert result.attempts == 1
    assert result.final_score >= 0.85
    # 成功はエピソード記憶に記録される
    assert len(memory.episodic) == 1
    assert memory.episodic[0]["outcome"]["success"]
    assert state.get_total_cost() > 0


def test_retry_with_improvement_prompt(tmp_path):
    llm = MockLLMClient(["短すぎる出力", GOOD_OUTPUT])
    loop, memory, _ = make_loop(tmp_path, llm)
    result = loop.run(TASK)
    assert result.status == "success"
    assert result.attempts == 2
    # 2回目のプロンプトには改善指示が入っている
    assert "改善が必要な点" in llm.calls[1]["prompt"]


def test_escalates_after_max_retries(tmp_path):
    llm = MockLLMClient(["だめ", "だめ", "だめ"])
    loop, memory, state = make_loop(tmp_path, llm, max_retries=3)
    result = loop.run(TASK)
    assert result.status == "escalate"
    assert result.attempts == 3
    assert not memory.episodic[0]["outcome"]["success"]
    assert state.state["errors"]  # エスカレーションが記録される


def test_relevant_skill_is_injected_into_system_prompt(tmp_path):
    from fable5 import Skill

    llm = MockLLMClient([GOOD_OUTPUT])
    loop, _, _ = make_loop(tmp_path, llm)
    loop.skills.register(
        Skill(
            id="skill_001",
            name="競合分析",
            type="prompt",
            category="analysis",
            trigger_patterns=[r"競合"],
            system_prompt_template="比較表とSWOTを必ず含めること。",
        )
    )
    loop.run(TASK)
    assert "比較表とSWOT" in llm.calls[0]["system"]
