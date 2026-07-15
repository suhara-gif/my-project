#!/usr/bin/env python3
"""research.sh 用の軽量エピソード記憶。

fable5-agent-system の MemoryStore と同じ考え方(問いの類似検索・成功実績の
蓄積)を、依存ゼロの単体スクリプトとして second-brain キットに移植したもの。
install.sh でホームディレクトリへコピーされた後も単体で動くよう、標準ライブラリ
のみを使う(fable5-agent-system をインポートしない)。

使い方(research.sh から呼ばれる想定):
    research_memory.py check  <state_dir> <question>
        → 類似の過去リサーチが見つかれば1行の TSV を stdout に出す(無ければ何も出さない)
    research_memory.py record <state_dir> <question> <output_md_path>
        → 生成された Markdown を読み、エピソードとして記憶に追加する
    research_memory.py list   <state_dir> [n]
        → 直近 n 件(既定10件)を人間向けに表示する
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

MAX_EPISODES = 500
SIMILARITY_THRESHOLD = 0.15


def _tokenize(text: str) -> set[str]:
    words = set(re.findall(r"[A-Za-z0-9]{2,}", text.lower()))
    ja = re.sub(r"[^ぁ-んァ-ヶ一-龠]", "", text)
    words |= {ja[i : i + 2] for i in range(len(ja) - 1)}
    return words


def _similarity(a: str, b: str) -> float:
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _memory_path(state_dir: Path) -> Path:
    return state_dir / "research-memory.json"


def _load(state_dir: Path) -> list[dict]:
    path = _memory_path(state_dir)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save(state_dir: Path, episodes: list[dict]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    if len(episodes) > MAX_EPISODES:
        episodes = episodes[-MAX_EPISODES:]
    _memory_path(state_dir).write_text(
        json.dumps(episodes, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _parse_frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        return {}
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        m = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
        if m:
            fields[m.group(1)] = m.group(2).strip().strip('"')
    return fields


def _count_bullets(text: str, heading: str) -> int:
    """指定見出し配下、次の `## ` までの `- ` 箇条書き行数を数える。"""
    match = re.search(
        rf"^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)",
        text,
        re.DOTALL | re.MULTILINE,
    )
    if not match:
        return 0
    return len(re.findall(r"^\s*-\s+\S", match.group(1), re.MULTILINE))


def _quality_score(text: str) -> float:
    survived = _count_bullets(text, "検証済みの知見(生き残り)")
    uncertain = _count_bullets(text, "単一ソース・要検証")
    unresolved = _count_bullets(text, "矛盾・未解決")
    total = survived + uncertain + unresolved
    if total == 0:
        return 0.5  # 判定不能。過大評価も過小評価もしない中間値。
    return round(survived / total, 3)


def _episode_id(question: str) -> str:
    return hashlib.md5(question.encode("utf-8")).hexdigest()[:12]


def cmd_check(state_dir: Path, question: str) -> None:
    episodes = _load(state_dir)
    today = date.today().isoformat()
    candidates = []
    for ep in episodes:
        expires = ep.get("expires", "")
        if expires and expires < today:
            continue  # 失効済みは提案しない(古いAI助言は害になりうる)
        score = _similarity(question, ep.get("question", ""))
        if score >= SIMILARITY_THRESHOLD:
            candidates.append((score, ep))
    if not candidates:
        return
    candidates.sort(key=lambda c: (c[0], c[1].get("quality_score", 0)), reverse=True)
    _, best = candidates[0]
    fields = [
        "FOUND",
        f"{best.get('quality_score', 0):.2f}",
        best.get("date", ""),
        best.get("question", ""),
        best.get("output_path", ""),
        best.get("summary", ""),
    ]
    print("\t".join(f.replace("\t", " ") for f in fields))


def cmd_record(state_dir: Path, question: str, output_path: str) -> None:
    path = Path(output_path)
    if not path.exists():
        return  # 生成物が無ければ記録しない(失敗時に嘘の実績を積まない)
    text = path.read_text(encoding="utf-8")
    fields = _parse_frontmatter(text)
    episode = {
        "id": _episode_id(question),
        "date": fields.get("date", date.today().isoformat()),
        "question": question,
        "summary": fields.get("summary", ""),
        "expires": fields.get("expires", ""),
        "output_path": str(path),
        "quality_score": _quality_score(text),
    }
    episodes = _load(state_dir)
    episodes.append(episode)
    _save(state_dir, episodes)


def cmd_list(state_dir: Path, limit: int = 10) -> None:
    episodes = _load(state_dir)[-limit:]
    if not episodes:
        print("(リサーチ記憶はまだありません)")
        return
    for ep in reversed(episodes):
        print(
            f"{ep.get('date', '?')}  品質{ep.get('quality_score', 0):.2f}  "
            f"{ep.get('question', '')}"
        )
        if ep.get("summary"):
            print(f"    → {ep['summary']}")


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 1
    subcommand, state_dir_arg = argv[1], argv[2]
    state_dir = Path(state_dir_arg)

    if subcommand == "check" and len(argv) >= 4:
        cmd_check(state_dir, argv[3])
    elif subcommand == "record" and len(argv) >= 5:
        cmd_record(state_dir, argv[3], argv[4])
    elif subcommand == "list":
        limit = int(argv[3]) if len(argv) >= 4 else 10
        cmd_list(state_dir, limit)
    else:
        print(__doc__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
