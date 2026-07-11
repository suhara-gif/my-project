"""Skills Library(手続き記憶)と Skills 自動生成。

スキル = 再利用可能な実行パターン。trigger_patterns にマッチするタスクへ
system_prompt_template を注入して再利用する。

SkillAutoGenerator は Episodic Memory を走査し、同種タスクが規定回数以上
高品質で成功していたらスキル候補として自動登録する(Level 4 の自己改善)。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Skill:
    id: str
    name: str
    type: str  # "prompt" | "workflow" | "code"
    category: str
    trigger_patterns: list[str]
    system_prompt_template: str
    created_by: str = "manual"  # "manual" | "auto"
    created_at: str = ""
    success_rate: float = 0.0
    avg_quality_score: float = 0.0
    usage_count: int = 0
    steps: list[str] = field(default_factory=list)

    def matches(self, description: str) -> bool:
        return any(
            re.search(p, description, re.IGNORECASE) for p in self.trigger_patterns
        )


class SkillsLibrary:
    def __init__(self, path: str | Path = ".fable5/skills.json"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.skills: dict[str, Skill] = self._load()

    def register(self, skill: Skill) -> None:
        if not skill.created_at:
            skill.created_at = datetime.now(timezone.utc).isoformat()
        self.skills[skill.id] = skill
        self._save()

    def get_by_id(self, skill_id: str) -> Skill | None:
        return self.skills.get(skill_id)

    def get_relevant(self, task: dict, top_k: int = 3) -> list[Skill]:
        description = task.get("description", "")
        matched = [s for s in self.skills.values() if s.matches(description)]
        matched.sort(key=lambda s: (s.avg_quality_score, s.usage_count), reverse=True)
        return matched[:top_k]

    def has_similar(self, name: str) -> bool:
        return any(s.name == name for s in self.skills.values())

    def record_usage(self, skill_id: str, quality_score: float, success: bool) -> None:
        skill = self.skills.get(skill_id)
        if skill is None:
            return
        n = skill.usage_count
        skill.avg_quality_score = (skill.avg_quality_score * n + quality_score) / (n + 1)
        skill.success_rate = (skill.success_rate * n + (1.0 if success else 0.0)) / (n + 1)
        skill.usage_count = n + 1
        self._save()

    def build_prompt_section(self, task: dict, top_k: int = 3) -> str:
        skills = self.get_relevant(task, top_k=top_k)
        if not skills:
            return ""
        lines = ["## 利用可能なスキル"]
        for skill in skills:
            lines.append(f"\n### {skill.name}(成功率 {skill.success_rate:.0%})")
            if skill.steps:
                lines.extend(f"{i + 1}. {step}" for i, step in enumerate(skill.steps))
            lines.append(skill.system_prompt_template)
        return "\n".join(lines)

    def _load(self) -> dict[str, Skill]:
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                return {d["id"]: Skill(**d) for d in raw}
            except (json.JSONDecodeError, TypeError, KeyError, OSError):
                return {}
        return {}

    def _save(self) -> None:
        data = [asdict(s) for s in self.skills.values()]
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )


class SkillAutoGenerator:
    """成功パターンをスキルへ抽象化する(夜間バッチ等での定期実行を想定)。"""

    def __init__(
        self,
        memory,
        skills: SkillsLibrary,
        llm=None,
        min_occurrences: int = 3,
        min_success_rate: float = 0.8,
    ):
        self.memory = memory
        self.skills = skills
        self.llm = llm
        self.min_occurrences = min_occurrences
        self.min_success_rate = min_success_rate

    def scan_and_generate(self) -> list[Skill]:
        generated: list[Skill] = []
        for candidate in self._identify_candidates():
            name = f"auto: {candidate['task_type']} タスクの成功パターン"
            if self.skills.has_similar(name):
                continue
            skill = self._abstract_to_skill(candidate, name)
            if skill is not None:
                self.skills.register(skill)
                generated.append(skill)
        return generated

    def _identify_candidates(self) -> list[dict]:
        groups: dict[str, list[dict]] = {}
        for ep in self.memory.episodic:
            if not ep["outcome"].get("success") or not ep["task"]["description"]:
                continue
            groups.setdefault(ep["task"]["type"], []).append(ep)

        candidates = []
        for task_type, episodes in groups.items():
            if len(episodes) < self.min_occurrences:
                continue
            high_quality = [
                ep for ep in episodes if ep["outcome"].get("quality_score", 0) > 0.8
            ]
            success_rate = len(high_quality) / len(episodes)
            if success_rate >= self.min_success_rate:
                candidates.append(
                    {
                        "task_type": task_type,
                        "episodes": sorted(
                            episodes,
                            key=lambda e: e["outcome"].get("quality_score", 0),
                            reverse=True,
                        ),
                        "success_rate": success_rate,
                    }
                )
        return candidates

    def _abstract_to_skill(self, candidate: dict, name: str) -> Skill | None:
        episodes = candidate["episodes"][:5]
        task_type = candidate["task_type"]

        if self.llm is not None:
            template = self._llm_abstract(episodes)
        else:
            # ヒューリスティック: 最高品質エピソードのタスク記述をテンプレート化
            best = episodes[0]
            template = (
                f"過去に高品質({best['outcome'].get('quality_score', 0):.2f})で完了した"
                f"同種タスクの例:\n{best['task']['description'][:300]}\n"
                "同じ水準の構造・網羅性で出力してください。"
            )
        if not template:
            return None

        triggers = self._extract_triggers(episodes)
        return Skill(
            id=f"skill_auto_{task_type}",
            name=name,
            type="prompt",
            category=task_type,
            trigger_patterns=triggers or [re.escape(task_type)],
            system_prompt_template=template,
            created_by="auto",
            success_rate=candidate["success_rate"],
            avg_quality_score=sum(
                e["outcome"].get("quality_score", 0) for e in episodes
            )
            / len(episodes),
        )

    def _llm_abstract(self, episodes: list[dict]) -> str:
        examples = "\n".join(
            f"- {ep['task']['description'][:150]} "
            f"(品質 {ep['outcome'].get('quality_score', 0):.2f})"
            for ep in episodes
        )
        prompt = (
            "以下の成功した実行パターンを分析し、再利用可能なプロンプトテンプレート"
            "(200字以内)に抽象化してください。テンプレート本文のみを返してください。\n\n"
            f"【成功パターン群】\n{examples}"
        )
        try:
            from .models import HAIKU

            return self.llm.complete(prompt, model=HAIKU, max_tokens=1024).text.strip()
        except Exception:
            return ""

    @staticmethod
    def _extract_triggers(episodes: list[dict]) -> list[str]:
        """エピソード記述に共通して現れる語をトリガーパターンにする。"""
        from collections import Counter

        counter: Counter[str] = Counter()
        for ep in episodes:
            desc = ep["task"]["description"]
            counter.update(set(re.findall(r"[A-Za-z]{3,}|[぀-ヿ一-鿿]{2,4}", desc)))
        common = [w for w, c in counter.most_common(5) if c >= max(2, len(episodes) // 2)]
        return [re.escape(w) for w in common[:3]]
