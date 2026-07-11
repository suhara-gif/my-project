"""3層メモリシステム。

- Working Memory: セッション内の一時情報(dict、揮発)
- Episodic Memory: 実行履歴(JSON 永続化、類似検索)
- Procedural Memory: SkillsLibrary が担当(skills.py)
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

MAX_EPISODES = 1000


def _tokenize(text: str) -> set[str]:
    """日本語・英語混在テキストの雑なトークン化(類似度計算用)。"""
    words = set(re.findall(r"[A-Za-z0-9]{2,}", text.lower()))
    # 日本語は 2-gram
    ja = re.sub(r"[^぀-ヿ一-鿿]", "", text)
    words |= {ja[i : i + 2] for i in range(len(ja) - 1)}
    return words


def _similarity(a: str, b: str) -> float:
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


class MemoryStore:
    def __init__(self, base_path: str | Path = ".fable5/memory"):
        self.base = Path(base_path)
        self.base.mkdir(parents=True, exist_ok=True)
        self.episodic_path = self.base / "episodic.json"
        self.working: dict = {}
        self.episodic: list[dict] = self._load()

    # ---- Episodic -----------------------------------------------------------

    def store_episode(self, task: dict, output: str, outcome: dict) -> dict:
        episode = {
            "id": self._episode_id(task),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task": {
                "type": task.get("type", "general"),
                "description": task.get("description", ""),
            },
            "output_preview": output[:500],
            "outcome": outcome,  # success / quality_score / model / cost / attempts
        }
        self.episodic.append(episode)
        self._save()
        return episode

    def find_similar(self, task: dict, limit: int = 5) -> list[dict]:
        task_type = task.get("type")
        description = task.get("description", "")
        candidates = [
            ep for ep in self.episodic if not task_type or ep["task"]["type"] == task_type
        ]
        scored = sorted(
            candidates,
            key=lambda ep: (
                _similarity(description, ep["task"]["description"]),
                ep["outcome"].get("quality_score", 0.0),
            ),
            reverse=True,
        )
        return scored[:limit]

    def count_similar_successes(self, task: dict, min_similarity: float = 0.3) -> int:
        description = task.get("description", "")
        return sum(
            1
            for ep in self.episodic
            if ep["task"]["type"] == task.get("type", "general")
            and ep["outcome"].get("success")
            and _similarity(description, ep["task"]["description"]) >= min_similarity
        )

    def get_best_model_for_type(self, task_type: str) -> dict | None:
        """同種タスクで品質/コスト比が最も良いモデルを返す。"""
        episodes = [ep for ep in self.episodic if ep["task"]["type"] == task_type]
        if not episodes:
            return None
        stats: dict[str, dict] = {}
        for ep in episodes:
            outcome = ep["outcome"]
            model = outcome.get("model")
            if not model:
                continue
            s = stats.setdefault(
                model, {"count": 0, "successes": 0, "quality": 0.0, "cost": 0.0}
            )
            s["count"] += 1
            s["successes"] += 1 if outcome.get("success") else 0
            s["quality"] += float(outcome.get("quality_score", 0.0))
            s["cost"] += float(outcome.get("cost", 0.0))
        if not stats:
            return None
        best_model, best = max(
            stats.items(),
            key=lambda kv: (
                (kv[1]["quality"] / kv[1]["count"]) * 0.7
                - (kv[1]["cost"] / kv[1]["count"]) * 0.3
            ),
        )
        return {
            "model": best_model,
            "success_rate": best["successes"] / best["count"],
            "avg_quality": best["quality"] / best["count"],
            "sample_size": best["count"],
        }

    def store_routing_outcome(self, outcome: dict) -> None:
        """Router から返される実行結果を軽量エピソードとして記録する。"""
        self.store_episode(
            {"type": outcome.get("task_type", "general"), "description": ""},
            "",
            {
                "success": outcome.get("success", False),
                "quality_score": outcome.get("quality_score", 0.0),
                "model": outcome.get("model"),
                "cost": outcome.get("cost", 0.0),
            },
        )

    # ---- コンテキスト注入 ----------------------------------------------------

    def build_context_injection(self, task: dict, limit: int = 2) -> str:
        """システムプロンプトに注入する過去の成功例セクションを組み立てる。"""
        sections: list[str] = []
        good = [
            ep
            for ep in self.find_similar(task, limit=limit * 2)
            if ep["outcome"].get("success")
            and ep["outcome"].get("quality_score", 0) > 0.85
            and ep["task"]["description"]
        ][:limit]
        if good:
            sections.append("## 過去の類似タスク成功例(参考)")
            for ep in good:
                sections.append(
                    f"- タスク: {ep['task']['description'][:100]} "
                    f"(品質 {ep['outcome']['quality_score']:.2f}, "
                    f"モデル {ep['outcome'].get('model')})"
                )
        if self.working:
            sections.append("## 作業記憶")
            for key, value in self.working.items():
                sections.append(f"- {key}: {str(value)[:200]}")
        return "\n".join(sections)

    # ---- 永続化 --------------------------------------------------------------

    def _load(self) -> list[dict]:
        if self.episodic_path.exists():
            try:
                return json.loads(self.episodic_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return []
        return []

    def _save(self) -> None:
        if len(self.episodic) > MAX_EPISODES:
            self.episodic = self.episodic[-MAX_EPISODES:]
        self.episodic_path.write_text(
            json.dumps(self.episodic, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _episode_id(task: dict) -> str:
        content = json.dumps(
            {k: task.get(k) for k in ("type", "description")}, sort_keys=True
        )
        return hashlib.md5(content.encode()).hexdigest()[:12]
