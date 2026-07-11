"""Execution Loop — Executor → Verifier → (改善して再試行) のループ。

成功時は Episodic Memory に記録し、同種タスクの成功が閾値を超えたら
SkillAutoGenerator によるスキル化の対象になる。
"""

from __future__ import annotations

from dataclasses import dataclass

from .llm import LLMClient
from .memory import MemoryStore
from .router import Router, RoutingDecision
from .skills import SkillsLibrary
from .state import StateManager
from .verification import VerificationEngine

_BASE_SYSTEM = (
    "あなたは自己改善型エージェントシステム上で動作する高性能 AI エージェントです。"
    "以下の参照情報を活用し、タスクを高品質に完了してください。"
)


@dataclass
class LoopResult:
    status: str  # "success" | "escalate"
    output: str
    attempts: int
    final_score: float
    routing: RoutingDecision
    cost_usd: float
    history: list


class ExecutionLoop:
    def __init__(
        self,
        llm: LLMClient,
        router: Router,
        verifier: VerificationEngine,
        memory: MemoryStore,
        skills: SkillsLibrary,
        state: StateManager,
        max_retries: int = 3,
    ):
        self.llm = llm
        self.router = router
        self.verifier = verifier
        self.memory = memory
        self.skills = skills
        self.state = state
        self.max_retries = max_retries

    def run(self, task: dict) -> LoopResult:
        routing = self.router.route(task)
        system = self._build_system_prompt(task)
        used_skills = self.skills.get_relevant(task)

        prompt = task.get("description", "")
        history: list[dict] = []
        cost = 0.0
        best: dict | None = None

        for attempt in range(1, self.max_retries + 1):
            self.state.update_status(f"executing_attempt_{attempt}")
            result = self.llm.complete(
                prompt,
                model=routing.model,
                system=system,
                max_tokens=int(task.get("max_tokens", 4096)),
                effort=task.get("effort"),
            )
            cost += self.state.track_cost(
                result.input_tokens, result.output_tokens, result.model
            )

            verification = self.verifier.verify(result.text, task)
            record = {
                "attempt": attempt,
                "output": result.text,
                "verification": verification,
            }
            history.append(record)
            if best is None or verification["total_score"] > best["verification"]["total_score"]:
                best = record

            if verification["passed"]:
                self._on_success(task, result.text, verification, routing, attempt, cost, used_skills)
                return LoopResult(
                    status="success",
                    output=result.text,
                    attempts=attempt,
                    final_score=verification["total_score"],
                    routing=routing,
                    cost_usd=round(cost, 6),
                    history=history,
                )

            self.state.record_retry(attempt, verification)
            prompt = verification["improvement_prompt"] or prompt

        # 最大試行回数超過 → 人間へエスカレーション(最良の出力を添えて)
        self._on_failure(task, best, routing, cost, used_skills)
        return LoopResult(
            status="escalate",
            output=best["output"] if best else "",
            attempts=self.max_retries,
            final_score=best["verification"]["total_score"] if best else 0.0,
            routing=routing,
            cost_usd=round(cost, 6),
            history=history,
        )

    # ---- 内部処理 --------------------------------------------------------------

    def _build_system_prompt(self, task: dict) -> str:
        sections = [_BASE_SYSTEM]
        skills_section = self.skills.build_prompt_section(task)
        if skills_section:
            sections.append(skills_section)
        memory_section = self.memory.build_context_injection(task)
        if memory_section:
            sections.append(memory_section)
        return "\n\n".join(sections)

    def _on_success(self, task, output, verification, routing, attempts, cost, used_skills):
        outcome = {
            "success": True,
            "quality_score": verification["total_score"],
            "model": routing.model,
            "cost": round(cost, 6),
            "attempts": attempts,
        }
        self.memory.store_episode(task, output, outcome)
        for skill in used_skills:
            self.skills.record_usage(skill.id, verification["total_score"], True)

    def _on_failure(self, task, best, routing, cost, used_skills):
        score = best["verification"]["total_score"] if best else 0.0
        self.memory.store_episode(
            task,
            best["output"] if best else "",
            {
                "success": False,
                "quality_score": score,
                "model": routing.model,
                "cost": round(cost, 6),
                "attempts": self.max_retries,
            },
        )
        self.state.record_error(
            f"max_retries_exceeded: {task.get('description', '')[:80]} "
            f"(best score {score:.2f})"
        )
        for skill in used_skills:
            self.skills.record_usage(skill.id, score, False)
