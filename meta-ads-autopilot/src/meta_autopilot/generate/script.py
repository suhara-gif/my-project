"""勝ちパターン仮説から動画CRの台本を生成する(Claude Opus 5.5)。

求人広告なので、数字(年収・休日数・件数など)や条件は**人が渡した facts 以外を書かせない**。
職業安定法の的確表示義務に反する誇大表示を生成しないため、生成後に機械チェックも行う(validate_facts)。
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

DEFAULT_MODEL = "claude-opus-5-5"


class Scene(BaseModel):
    start_sec: float
    duration_sec: float
    visual: str = Field(description="画面に映すもの。撮影/素材選定の指示として具体的に")
    visual_tag: str = Field(description="素材ライブラリ検索用の短いタグ(英小文字とハイフン。例: mechanic-selfie)")
    on_screen_text: str = Field(description="テロップ。無ければ空文字")
    narration: str = Field(description="ナレーション(TTSで読み上げる)。無ければ空文字")


class VideoScript(BaseModel):
    title: str
    hypothesis: str = Field(description="この台本で検証する仮説(1文)")
    aspect_ratio: Literal["9:16", "4:5", "1:1"]
    total_sec: float
    hook_type: str
    appeal_axis: str
    scenes: list[Scene]
    cta: str
    compliance_notes: str = Field(description="事実確認が必要な表現、誇大表示リスクのある箇所")


SYSTEM = """あなたは自動車整備士向け求人広告の動画ディレクターです。Meta広告(リール/ストーリーズ)用の縦型動画の台本を作ります。

厳守:
- 数字・給与・休日・待遇・実績は、ユーザーが渡す「使ってよい事実」に書かれたものだけを使う。無いものは作らない。
- 「必ず」「誰でも」「日本一」等の断定・最上級は使わない。
- 指定された勝ちパターン(特徴量の組み合わせ)を必ず満たす。冒頭の秒数指定があれば守る。
- 既存勝ちCRとの差分は仮説で指定された要素だけにし、それ以外は既存CRの構成を踏襲する(差分を1つに絞るため)。"""


def build_prompt(pattern: dict, control_features: dict, facts: list[str], hypothesis: str, variant_note: str = "") -> str:
    fact_lines = "\n".join(f"- {f}" for f in facts) or "- (なし。数字・条件は一切使わない)"
    pat = "\n".join(f"- {k}: {v}" for k, v in pattern.items())
    ctl = "\n".join(f"- {k}: {v}" for k, v in control_features.items())
    return (
        f"## 検証する仮説\n{hypothesis}\n\n"
        f"## 満たすべき勝ちパターン\n{pat}\n\n"
        f"## 既存勝ちCR(コントロール)の特徴\n{ctl}\n\n"
        f"## 使ってよい事実\n{fact_lines}\n\n"
        f"{variant_note}\n15〜30秒の台本を作ってください。"
    )


def generate_script(
    pattern: dict,
    control_features: dict,
    facts: list[str],
    hypothesis: str,
    *,
    model: str = DEFAULT_MODEL,
    effort: str = "high",
    variant_note: str = "",
    client=None,
) -> VideoScript:
    import anthropic

    client = client or anthropic.Anthropic()
    resp = client.messages.parse(
        model=model,
        max_tokens=16000,
        system=SYSTEM,
        output_config={"effort": effort},
        messages=[{"role": "user", "content": build_prompt(pattern, control_features, facts, hypothesis, variant_note)}],
        output_format=VideoScript,
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"台本生成を拒否された: {resp.stop_details}")
    return resp.parsed_output


_NUM = re.compile(r"[0-9０-９][0-9０-９,，.．万千百]*")


def _norm(s: str) -> str:
    return s.translate(str.maketrans("０１２３４５６７８９，．", "0123456789,.")).replace(",", "")


def validate_facts(script: VideoScript, facts: list[str]) -> list[str]:
    """台本中の数字が facts のどれかに含まれているかを調べ、含まれない数字を返す。

    空リストなら合格。数字以外の誇張(最上級表現等)は検出できないので、人の確認は省略しない。
    """
    # 部分一致だと「30」が「300万」に含まれて素通りするので、数字トークン単位で照合する
    fact_nums = {_norm(m).rstrip(".") for f in facts for m in _NUM.findall(f)}
    problems = []
    texts = [script.cta] + [x for s in script.scenes for x in (s.on_screen_text, s.narration)]
    for t in texts:
        for m in _NUM.findall(t):
            n = _norm(m).rstrip(".")
            if n and n not in fact_nums:
                problems.append(f"事実リストに無い数字「{m}」: {t}")
    return problems


def check_pattern(script: VideoScript, pattern: dict) -> list[str]:
    """生成台本が指定パターンを満たしているかの機械チェック(満たせる項目のみ)。"""
    problems = []
    if "hook_type" in pattern and script.hook_type != pattern["hook_type"]:
        problems.append(f"hook_type が {script.hook_type}(指定 {pattern['hook_type']})")
    if "appeal_axis" in pattern and script.appeal_axis != pattern["appeal_axis"]:
        problems.append(f"appeal_axis が {script.appeal_axis}(指定 {pattern['appeal_axis']})")
    if pattern.get("early_exposure") == "yes":
        first = next((s for s in script.scenes if s.on_screen_text or s.narration), None)
        if first is None or first.start_sec > 2:
            problems.append("冒頭2秒以内に求人・条件の露出が無い")
    if script.scenes and abs(sum(s.duration_sec for s in script.scenes) - script.total_sec) > 0.5:
        problems.append("シーン尺の合計が total_sec と一致しない")
    return problems
