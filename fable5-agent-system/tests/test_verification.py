from fable5 import MockLLMClient, VerificationEngine


def test_good_analysis_passes():
    engine = VerificationEngine()
    output = (
        "# 競合分析\n\n"
        "## 投稿頻度の比較\n- A社: 週5回\n- B社: 週3回\n\n"
        "## エンゲージメント率\n- B社が最も高い\n\n"
        "## 示唆\n1. 質が頻度に勝る\n2. 動画比率を上げる\n"
    )
    task = {
        "type": "analysis",
        "description": "競合SNS分析",
        "required_keywords": ["投稿頻度", "エンゲージメント"],
        "min_chars": 50,
    }
    result = engine.verify(output, task)
    assert result["passed"]
    assert result["improvement_prompt"] is None


def test_missing_keywords_fails_with_improvement_prompt():
    engine = VerificationEngine()
    result = engine.verify(
        "短い出力です。",
        {
            "type": "analysis",
            "description": "競合分析",
            "required_keywords": ["投稿頻度", "エンゲージメント", "KPI"],
            "min_chars": 200,
        },
    )
    assert not result["passed"]
    assert "改善が必要な点" in result["improvement_prompt"]


def test_empty_output_fails():
    result = VerificationEngine().verify("", {"type": "writing", "description": "x"})
    assert not result["passed"]


def test_json_check_for_code_tasks():
    engine = VerificationEngine()
    task = {"type": "code", "description": "JSON設定を生成", "expects_json": True}
    good = engine.verify('```json\n{"key": "value"}\n```', task)
    bad = engine.verify("```json\n{broken\n```", task)
    assert good["total_score"] > bad["total_score"]


def test_llm_verifier_blends_score():
    llm = MockLLMClient(['{"score": 0.2, "issues": ["論理が飛躍している"], "passed": false}'])
    engine = VerificationEngine(llm=llm)
    output = "# 分析\n\n- 十分に長い構造化された出力 " * 20
    result = engine.verify(output, {"type": "analysis", "description": "分析"})
    # ヒューリスティックは高得点でも LLM の低評価と平均されて不合格になる
    assert not result["passed"]
    assert "論理が飛躍している" in result["llm_issues"]
