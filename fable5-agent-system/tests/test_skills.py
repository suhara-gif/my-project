from fable5 import (
    MemoryStore,
    Skill,
    SkillAutoGenerator,
    SkillsLibrary,
    SONNET,
)


def make_skill(**overrides) -> Skill:
    defaults = dict(
        id="skill_001",
        name="競合分析レポート生成",
        type="workflow",
        category="marketing",
        trigger_patterns=[r"競合.*分析", r"competitor.*analysis"],
        system_prompt_template="あなたは競合分析の専門家です。比較表とSWOTを含めてください。",
        avg_quality_score=0.9,
    )
    defaults.update(overrides)
    return Skill(**defaults)


def test_register_and_match(tmp_path):
    lib = SkillsLibrary(tmp_path / "skills.json")
    lib.register(make_skill())
    relevant = lib.get_relevant({"description": "競合5社の分析レポートを作成"})
    assert len(relevant) == 1
    assert relevant[0].id == "skill_001"
    assert lib.get_relevant({"description": "天気を教えて"}) == []


def test_persistence(tmp_path):
    path = tmp_path / "skills.json"
    SkillsLibrary(path).register(make_skill())
    reloaded = SkillsLibrary(path)
    assert reloaded.get_by_id("skill_001") is not None


def test_record_usage_updates_stats(tmp_path):
    lib = SkillsLibrary(tmp_path / "skills.json")
    lib.register(make_skill(avg_quality_score=0.0, usage_count=0))
    lib.record_usage("skill_001", 0.9, True)
    lib.record_usage("skill_001", 0.7, False)
    skill = lib.get_by_id("skill_001")
    assert skill.usage_count == 2
    assert skill.avg_quality_score == 0.8
    assert skill.success_rate == 0.5


def test_prompt_section_includes_template(tmp_path):
    lib = SkillsLibrary(tmp_path / "skills.json")
    lib.register(make_skill())
    section = lib.build_prompt_section({"description": "競合の分析をお願いします"})
    assert "利用可能なスキル" in section
    assert "競合分析の専門家" in section


def test_auto_generator_creates_skill_from_successes(tmp_path):
    memory = MemoryStore(tmp_path / "memory")
    for i in range(4):
        memory.store_episode(
            {"type": "analysis", "description": f"競合他社のSNS戦略を分析する({i})"},
            "高品質な出力",
            {"success": True, "quality_score": 0.92, "model": SONNET, "cost": 0.1},
        )
    lib = SkillsLibrary(tmp_path / "skills.json")
    generated = SkillAutoGenerator(memory, lib).scan_and_generate()
    assert len(generated) == 1
    assert generated[0].created_by == "auto"
    assert generated[0].category == "analysis"
    # 二重登録されない
    assert SkillAutoGenerator(memory, lib).scan_and_generate() == []


def test_auto_generator_ignores_low_success_rate(tmp_path):
    memory = MemoryStore(tmp_path / "memory")
    for i in range(4):
        memory.store_episode(
            {"type": "writing", "description": f"記事執筆 {i}"},
            "",
            {"success": True, "quality_score": 0.5, "model": SONNET, "cost": 0.1},
        )
    lib = SkillsLibrary(tmp_path / "skills.json")
    assert SkillAutoGenerator(memory, lib).scan_and_generate() == []
