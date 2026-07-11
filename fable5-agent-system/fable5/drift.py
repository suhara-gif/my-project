"""Drift Monitor — 当初の目標からの逸脱(コンテキストドリフト)を監視する。

LLM(既定は Haiku)に目標と直近出力の整合度を採点させる。
LLM 未設定時はトークン重なりによるヒューリスティックにフォールバックする。
"""

from __future__ import annotations

import json
import re

from .memory import _similarity
from .models import HAIKU

_PROMPT = """\
当初の目標: {goal}
現在のフェーズ: {phase}
直近の出力(先頭500字): {output}

目標との整合度を評価し、以下の JSON だけを返してください:
{{"alignment_score": 0.0から1.0, "drift_detected": true/false, "drift_description": "..."}}
"""


class DriftMonitor:
    def __init__(self, original_goal: str, llm=None, verifier_model: str = HAIKU):
        self.goal = original_goal
        self.llm = llm
        self.verifier_model = verifier_model

    def check_drift(self, last_output: str, current_phase: str = "") -> dict:
        result = self._llm_check(last_output, current_phase)
        if result is None:
            score = min(1.0, _similarity(self.goal, last_output) * 4)
            result = {"alignment_score": round(score, 3), "drift_description": ""}

        score = result["alignment_score"]
        drift = score < 0.7
        return {
            "drift_detected": drift,
            "alignment_score": score,
            "severity": ("high" if score < 0.5 else "medium") if drift else "none",
            "correction": self._correction(result) if drift else None,
        }

    def _llm_check(self, last_output: str, current_phase: str) -> dict | None:
        if self.llm is None:
            return None
        prompt = _PROMPT.format(
            goal=self.goal, phase=current_phase, output=last_output[:500]
        )
        try:
            text = self.llm.complete(
                prompt, model=self.verifier_model, max_tokens=512
            ).text
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                return None
            data = json.loads(match.group(0))
            return {
                "alignment_score": max(0.0, min(1.0, float(data.get("alignment_score", 0)))),
                "drift_description": str(data.get("drift_description", "")),
            }
        except Exception:
            return None

    def _correction(self, result: dict) -> str:
        description = result.get("drift_description") or "出力が当初の目標から逸脱しています"
        return (
            f"【軌道修正】{description}\n"
            f"当初の目標を再確認してください: {self.goal}\n"
            "以降の作業はこの目標に直結する内容に限定してください。"
        )
