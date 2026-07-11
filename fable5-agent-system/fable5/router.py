"""Router — タスクの性質からモデルを動的に選択する。

判定順序:
  1. タスクタイプ別ルール(verification → Haiku、code → 複雑度で分岐)
  2. 複雑度 → モデルティアのマッピング
  3. Memory に蓄積された「同種タスクで最も成功したモデル」による上書き(学習効果)
  4. 予算制約チェック(超過時は1段安いモデルへフォールバック)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from .models import HAIKU, OPUS, SONNET, cheaper_alternative, estimate_cost


class TaskComplexity(Enum):
    TRIVIAL = 1
    SIMPLE = 2
    MODERATE = 3
    COMPLEX = 4
    CRITICAL = 5


_COMPLEXITY_PATTERNS: dict[TaskComplexity, list[str]] = {
    TaskComplexity.CRITICAL: [r"最高品質", r"本番", r"critical", r"production", r"最終"],
    TaskComplexity.COMPLEX: [r"設計", r"アーキテクチャ", r"戦略", r"design", r"strategy", r"architect"],
    TaskComplexity.MODERATE: [r"分析", r"比較", r"analyze", r"compare", r"evaluate", r"調査"],
    TaskComplexity.SIMPLE: [r"要約", r"分類", r"翻訳", r"summarize", r"classify", r"translate"],
    TaskComplexity.TRIVIAL: [r"format", r"convert", r"変換", r"整形"],
}

_TYPE_PATTERNS: dict[str, list[str]] = {
    "verification": [r"検証", r"verify", r"check", r"validate", r"fact.?check"],
    "code": [r"コード", r"実装", r"code", r"implement", r"script", r"program"],
    "writing": [r"執筆", r"記事", r"write", r"draft", r"report", r"レポート"],
    "planning": [r"分解", r"計画", r"plan", r"decompose"],
}


@dataclass
class RoutingDecision:
    model: str
    complexity: TaskComplexity
    task_type: str
    estimated_cost: float
    reasoning: str
    overrides: list[str] = field(default_factory=list)


class Router:
    def __init__(self, memory=None):
        self.memory = memory

    def route(self, task: dict) -> RoutingDecision:
        description = task.get("description", "")
        task_type = task.get("type") or self._detect_task_type(description)
        complexity = self._estimate_complexity(description, task)
        estimated_tokens = int(task.get("estimated_tokens", 2000))
        budget = task.get("budget_usd")

        model = self._base_model(task_type, complexity)
        overrides: list[str] = []

        # 学習効果: 過去に高成功率だったモデルを優先
        if self.memory is not None:
            best = self.memory.get_best_model_for_type(task_type)
            if best and best["success_rate"] > 0.9 and best["model"] != model:
                model = best["model"]
                overrides.append(
                    f"memory: {task_type} で成功率 {best['success_rate']:.0%} の "
                    f"{best['model']} を採用"
                )

        # 予算制約: 見積もりが予算を超えるなら安いモデルへ
        cost = self._estimate(model, estimated_tokens)
        while budget is not None and cost > budget:
            cheaper = cheaper_alternative(model)
            if cheaper == model:
                break
            model = cheaper
            cost = self._estimate(model, estimated_tokens)
            overrides.append(f"budget: 予算 ${budget} 制約により {model} へ変更")

        return RoutingDecision(
            model=model,
            complexity=complexity,
            task_type=task_type,
            estimated_cost=cost,
            reasoning=(
                f"type={task_type}, complexity={complexity.name} → {model}"
            ),
            overrides=overrides,
        )

    def _base_model(self, task_type: str, complexity: TaskComplexity) -> str:
        if task_type == "verification":
            return HAIKU
        if task_type == "code":
            return OPUS if complexity.value >= 4 else SONNET
        return {
            TaskComplexity.TRIVIAL: HAIKU,
            TaskComplexity.SIMPLE: HAIKU,
            TaskComplexity.MODERATE: SONNET,
            TaskComplexity.COMPLEX: SONNET,
            TaskComplexity.CRITICAL: OPUS,
        }[complexity]

    def _estimate_complexity(self, description: str, task: dict) -> TaskComplexity:
        if task.get("required_quality") in ("critical", "production"):
            return TaskComplexity.CRITICAL
        for complexity in sorted(
            _COMPLEXITY_PATTERNS, key=lambda c: c.value, reverse=True
        ):
            patterns = _COMPLEXITY_PATTERNS[complexity]
            if any(re.search(p, description, re.IGNORECASE) for p in patterns):
                return complexity
        return TaskComplexity.MODERATE

    def _detect_task_type(self, description: str) -> str:
        for task_type, patterns in _TYPE_PATTERNS.items():
            if any(re.search(p, description, re.IGNORECASE) for p in patterns):
                return task_type
        return "general"

    @staticmethod
    def _estimate(model: str, tokens: int) -> float:
        # 入力7割 / 出力3割の想定で概算
        return estimate_cost(model, int(tokens * 0.7), int(tokens * 0.3))

    def update_routing_knowledge(self, decision: RoutingDecision, result: dict) -> None:
        """実行結果を Memory に返し、次回のルーティングに反映させる。"""
        if self.memory is None:
            return
        self.memory.store_routing_outcome(
            {
                "model": decision.model,
                "task_type": decision.task_type,
                "success": bool(result.get("success")),
                "quality_score": float(result.get("quality_score", 0.0)),
                "cost": float(result.get("cost", 0.0)),
            }
        )
