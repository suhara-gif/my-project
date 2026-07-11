"""Orchestrator — 全コンポーネントを束ねるエントリーポイント。

使い方:
    from fable5 import Orchestrator

    orch = Orchestrator(session_id="sns_analysis_001", budget_usd=5.0)
    result = orch.run_task({
        "type": "analysis",
        "description": "競合3社のSNS戦略を分析し比較表を作成する",
        "required_keywords": ["投稿頻度", "エンゲージメント"],
    })

ワークフロー(複数タスクの直列実行)はチェックポイントから再開できる。
"""

from __future__ import annotations

from pathlib import Path

from .drift import DriftMonitor
from .llm import AnthropicLLMClient, LLMClient
from .loop import ExecutionLoop, LoopResult
from .memory import MemoryStore
from .router import Router
from .skills import SkillAutoGenerator, SkillsLibrary
from .state import StateManager
from .verification import VerificationEngine


class Orchestrator:
    def __init__(
        self,
        session_id: str,
        llm: LLMClient | None = None,
        base_dir: str | Path = ".fable5",
        budget_usd: float = 10.0,
        max_retries: int = 3,
        use_llm_verifier: bool = False,
        goal: str | None = None,
    ):
        base = Path(base_dir)
        self.llm = llm or AnthropicLLMClient()
        self.memory = MemoryStore(base / "memory")
        self.skills = SkillsLibrary(base / "skills.json")
        self.state = StateManager(session_id, base / "sessions", cost_limit_usd=budget_usd)
        self.router = Router(memory=self.memory)
        self.verifier = VerificationEngine(llm=self.llm if use_llm_verifier else None)
        self.drift = DriftMonitor(goal, llm=self.llm) if goal else None
        self.loop = ExecutionLoop(
            llm=self.llm,
            router=self.router,
            verifier=self.verifier,
            memory=self.memory,
            skills=self.skills,
            state=self.state,
            max_retries=max_retries,
        )
        self.auto_skills = SkillAutoGenerator(self.memory, self.skills, llm=self.llm)

    # ---- 単一タスク -------------------------------------------------------------

    def run_task(self, task: dict) -> LoopResult:
        result = self.loop.run(task)
        self.router.update_routing_knowledge(
            result.routing,
            {
                "success": result.status == "success",
                "quality_score": result.final_score,
                "cost": result.cost_usd,
            },
        )
        if self.drift is not None and result.output:
            drift = self.drift.check_drift(
                result.output, current_phase=self.state.state.get("current_phase") or ""
            )
            if drift["drift_detected"]:
                self.state.record_error(
                    f"drift_detected (score {drift['alignment_score']:.2f})"
                )
        return result

    # ---- ワークフロー ------------------------------------------------------------

    def run_workflow(self, phases: list[dict]) -> dict:
        """phases: [{"id": "research", "task": {...}}, ...] を直列実行。

        完了済みフェーズはチェックポイントからスキップして再開する。
        """
        self.state.update_status("running")
        results: dict[str, LoopResult | dict] = {}
        for phase in phases:
            phase_id = phase["id"]
            cached = self.state.can_resume_from(phase_id)
            if cached is not None:
                results[phase_id] = cached
                continue
            result = self.run_task(phase["task"])
            results[phase_id] = result
            self.state.checkpoint(
                phase_id,
                {
                    "status": result.status,
                    "score": result.final_score,
                    "model": result.routing.model,
                    "output_preview": result.output[:300],
                },
            )
            if result.status != "success" and phase.get("on_failure") != "skip_and_continue":
                self.state.update_status("escalated")
                break
        else:
            self.state.update_status("completed")
        return results

    # ---- 自己改善バッチ ----------------------------------------------------------

    def improve(self) -> list:
        """メモリを走査してスキルを自動生成する(定期実行を推奨)。"""
        return self.auto_skills.scan_and_generate()
