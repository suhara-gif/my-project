"""Verification Engine — 出力品質の自動検証。

決定論的なヒューリスティック検証(高速・無料)を基本とし、
LLM ベースの検証(Verifier エージェント)をオプションで重ねられる。
Executor と Verifier に別モデルを使うのが原則(同一モデルは同じバイアスを持つため)。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

from .models import HAIKU

PASS_THRESHOLD = 0.85
CRITERION_THRESHOLD = 0.8


@dataclass
class VerificationCriteria:
    name: str
    weight: float
    checker: Callable[[str, dict], float]  # (output, task) -> 0.0..1.0
    threshold: float = CRITERION_THRESHOLD


# ---- ヒューリスティックチェッカー --------------------------------------------


def _check_nonempty(output: str, task: dict) -> float:
    return 1.0 if output.strip() else 0.0


def _check_length(output: str, task: dict) -> float:
    min_chars = int(task.get("min_chars", 50))
    max_chars = int(task.get("max_chars", 200_000))
    n = len(output)
    if n < min_chars:
        return n / min_chars
    if n > max_chars:
        return max(0.0, 1.0 - (n - max_chars) / max_chars)
    return 1.0


def _check_keyword_coverage(output: str, task: dict) -> float:
    keywords = task.get("required_keywords") or []
    if not keywords:
        return 1.0
    hit = sum(1 for k in keywords if re.search(re.escape(k), output, re.IGNORECASE))
    return hit / len(keywords)


def _check_structure(output: str, task: dict) -> float:
    """分析・レポート系: 見出しや箇条書きなどの構造があるか。"""
    signals = 0
    if re.search(r"^#{1,4} ", output, re.MULTILINE):
        signals += 1
    if re.search(r"^[-*] ", output, re.MULTILINE):
        signals += 1
    if re.search(r"^\d+[.)] ", output, re.MULTILINE):
        signals += 1
    return min(1.0, signals / 2)


def _check_json_valid(output: str, task: dict) -> float:
    """code/json 系: 出力に有効な JSON ブロックが含まれるか。"""
    if not task.get("expects_json"):
        return 1.0
    match = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", output, re.DOTALL)
    candidate = match.group(1) if match else output.strip()
    try:
        json.loads(candidate)
        return 1.0
    except (json.JSONDecodeError, ValueError):
        return 0.0


def _check_no_placeholder(output: str, task: dict) -> float:
    """TODO / FIXME / <placeholder> の残留を検出。"""
    bad = re.findall(r"TODO|FIXME|XXX|<[a-z_]+をここに>|\[要記入\]", output)
    return max(0.0, 1.0 - 0.25 * len(bad))


_CRITERIA_SETS: dict[str, list[VerificationCriteria]] = {
    "code": [
        VerificationCriteria("nonempty", 0.2, _check_nonempty),
        VerificationCriteria("json_valid", 0.3, _check_json_valid),
        VerificationCriteria("keyword_coverage", 0.3, _check_keyword_coverage),
        VerificationCriteria("no_placeholder", 0.2, _check_no_placeholder),
    ],
    "analysis": [
        VerificationCriteria("nonempty", 0.15, _check_nonempty),
        VerificationCriteria("length", 0.2, _check_length),
        VerificationCriteria("keyword_coverage", 0.35, _check_keyword_coverage),
        VerificationCriteria("structure", 0.3, _check_structure),
    ],
    "writing": [
        VerificationCriteria("nonempty", 0.2, _check_nonempty),
        VerificationCriteria("length", 0.3, _check_length),
        VerificationCriteria("keyword_coverage", 0.4, _check_keyword_coverage),
        VerificationCriteria("no_placeholder", 0.1, _check_no_placeholder),
    ],
}

_DEFAULT_CRITERIA = [
    VerificationCriteria("nonempty", 0.3, _check_nonempty),
    VerificationCriteria("length", 0.3, _check_length),
    VerificationCriteria("keyword_coverage", 0.4, _check_keyword_coverage),
]

_LLM_VERIFY_PROMPT = """\
あなたは出力品質を検証する Verifier です。感情ではなく基準で評価してください。

【タスク】
{description}

【出力(先頭2000字)】
{output}

以下の JSON だけを返してください:
{{"score": 0.0から1.0, "issues": ["問題点1", "..."], "passed": true/false}}
"""


class VerificationEngine:
    """タスクタイプ別の基準セットで出力を採点し、改善指示を生成する。"""

    def __init__(self, llm=None, verifier_model: str = HAIKU):
        self.llm = llm
        self.verifier_model = verifier_model

    def verify(self, output: str, task: dict) -> dict:
        task_type = task.get("type", "general")
        criteria = _CRITERIA_SETS.get(task_type, _DEFAULT_CRITERIA)

        results = []
        for criterion in criteria:
            score = float(criterion.checker(output, task))
            results.append(
                {
                    "criterion": criterion.name,
                    "score": round(score, 3),
                    "weight": criterion.weight,
                    "passed": score >= criterion.threshold,
                }
            )
        total = sum(r["score"] * r["weight"] for r in results)

        # LLM Verifier(任意): ヒューリスティックと平均を取る
        llm_issues: list[str] = []
        if self.llm is not None:
            llm_result = self._llm_verify(output, task)
            if llm_result is not None:
                total = (total + llm_result["score"]) / 2
                llm_issues = llm_result.get("issues", [])

        passed = total >= PASS_THRESHOLD
        failed = [r for r in results if not r["passed"]]
        return {
            "passed": passed,
            "total_score": round(total, 3),
            "criteria_results": results,
            "llm_issues": llm_issues,
            "improvement_prompt": (
                None if passed else self._improvement_prompt(failed, llm_issues, task)
            ),
            "recommendation": "proceed" if passed else "revise",
        }

    def _llm_verify(self, output: str, task: dict) -> dict | None:
        prompt = _LLM_VERIFY_PROMPT.format(
            description=task.get("description", ""), output=output[:2000]
        )
        try:
            result = self.llm.complete(prompt, model=self.verifier_model, max_tokens=1024)
            match = re.search(r"\{.*\}", result.text, re.DOTALL)
            if not match:
                return None
            data = json.loads(match.group(0))
            return {
                "score": max(0.0, min(1.0, float(data.get("score", 0.0)))),
                "issues": [str(i) for i in data.get("issues", [])],
            }
        except Exception:
            return None  # Verifier の失敗で本体を止めない

    @staticmethod
    def _improvement_prompt(failed: list[dict], llm_issues: list[str], task: dict) -> str:
        lines = [
            f"- {c['criterion']}: スコア {c['score']:.2f}(基準 {CRITERION_THRESHOLD})"
            for c in failed
        ]
        lines += [f"- {issue}" for issue in llm_issues]
        failures = "\n".join(lines) or "- 総合スコアが基準に達していません"
        return (
            "前回の出力は品質基準を満たしませんでした。以下を修正した改善版を出力してください。\n\n"
            f"【改善が必要な点】\n{failures}\n\n"
            f"【元のタスク】\n{task.get('description', '')}"
        )
