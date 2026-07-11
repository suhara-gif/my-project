"""State Manager — 長時間実行のチェックポイント・再開・コスト管理。

状態は 2 形式で永続化する:
- state.json  … 機械可読(再開用の正)
- STATE.md    … 人間可読(記事の STATE.md に相当。常に state.json から再生成)
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from .models import estimate_cost


class CostLimitExceeded(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StateManager:
    def __init__(
        self,
        session_id: str,
        base_dir: str | Path = ".fable5/sessions",
        cost_limit_usd: float = 10.0,
    ):
        self.session_id = session_id
        self.dir = Path(base_dir) / session_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.json_path = self.dir / "state.json"
        self.md_path = self.dir / "STATE.md"
        self._start = time.monotonic()
        self.state = self._load(cost_limit_usd)

    # ---- ライフサイクル -------------------------------------------------------

    def update_status(self, status: str) -> None:
        self.state["status"] = status
        self._persist()

    def checkpoint(self, phase: str, data: dict | None = None) -> None:
        self.state["checkpoints"].append(
            {
                "phase": phase,
                "timestamp": _now(),
                "elapsed_seconds": self.get_elapsed_seconds(),
                "data": data or {},
            }
        )
        self.state["current_phase"] = phase
        if phase not in self.state["completed_phases"]:
            self.state["completed_phases"].append(phase)
        self._persist()

    def can_resume_from(self, phase: str) -> dict | None:
        for cp in reversed(self.state["checkpoints"]):
            if cp["phase"] == phase:
                return cp["data"]
        return None

    # ---- コスト --------------------------------------------------------------

    def track_cost(self, input_tokens: int, output_tokens: int, model: str) -> float:
        cost = estimate_cost(model, input_tokens, output_tokens)
        tracker = self.state["cost_tracker"]
        tracker["tokens"] += input_tokens + output_tokens
        tracker["cost_usd"] = round(tracker["cost_usd"] + cost, 6)
        self._persist()
        if tracker["cost_usd"] >= tracker["limit_usd"]:
            self.update_status("halted_cost_limit")
            raise CostLimitExceeded(
                f"コスト上限に達しました: ${tracker['cost_usd']:.2f} / "
                f"${tracker['limit_usd']:.2f}"
            )
        return cost

    def get_total_cost(self) -> float:
        return self.state["cost_tracker"]["cost_usd"]

    def get_elapsed_seconds(self) -> int:
        return round(time.monotonic() - self._start)

    # ---- 記録 ----------------------------------------------------------------

    def record_error(self, message: str) -> None:
        self.state["errors"].append({"timestamp": _now(), "message": message})
        self._persist()

    def record_retry(self, attempt: int, verification: dict) -> None:
        self.state["retries"].append(
            {
                "timestamp": _now(),
                "attempt": attempt,
                "score": verification.get("total_score"),
            }
        )
        self._persist()

    # ---- 永続化 ---------------------------------------------------------------

    def _load(self, cost_limit_usd: float) -> dict:
        if self.json_path.exists():
            try:
                state = json.loads(self.json_path.read_text(encoding="utf-8"))
                state["status"] = "resumed"
                return state
            except (json.JSONDecodeError, OSError):
                pass
        return {
            "session_id": self.session_id,
            "status": "initialized",
            "start_time": _now(),
            "current_phase": None,
            "completed_phases": [],
            "checkpoints": [],
            "cost_tracker": {"tokens": 0, "cost_usd": 0.0, "limit_usd": cost_limit_usd},
            "errors": [],
            "retries": [],
        }

    def _persist(self) -> None:
        self.json_path.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.md_path.write_text(self._render_md(), encoding="utf-8")

    def _render_md(self) -> str:
        s = self.state
        tracker = s["cost_tracker"]
        lines = [
            "# STATE.md — 実行状態",
            "",
            "## メタデータ",
            f"- **Session ID**: {s['session_id']}",
            f"- **開始時刻**: {s['start_time']}",
            f"- **最終更新**: {_now()}",
            f"- **ステータス**: {s['status']}",
            f"- **現在フェーズ**: {s['current_phase']}",
            "",
            "## 完了フェーズ",
        ]
        lines += [f"- [x] {p}" for p in s["completed_phases"]] or ["- (なし)"]
        lines += [
            "",
            "## コスト追跡",
            f"- 使用トークン: {tracker['tokens']:,}",
            f"- 推定コスト: ${tracker['cost_usd']:.4f}",
            f"- コスト上限: ${tracker['limit_usd']:.2f}",
            f"- 残余予算: ${max(0.0, tracker['limit_usd'] - tracker['cost_usd']):.4f}",
        ]
        if s["errors"]:
            lines += ["", "## エラー"]
            lines += [f"- {e['timestamp']}: {e['message']}" for e in s["errors"][-10:]]
        if s["checkpoints"]:
            last = s["checkpoints"][-1]
            lines += [
                "",
                "## 最終チェックポイント",
                "```json",
                json.dumps(last, ensure_ascii=False, indent=2),
                "```",
            ]
        return "\n".join(lines) + "\n"
