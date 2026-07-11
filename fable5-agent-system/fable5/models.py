"""実在の Claude モデルのカタログとコスト計算。

記事中の架空モデル(claude-opus-5 / claude-haiku-5 / gpt-5.5 等)は
実在の Claude API モデル ID に置き換えてある。
料金は 2026-06 時点の USD / 1M tokens。
"""

from __future__ import annotations

from dataclasses import dataclass

OPUS = "claude-opus-4-8"
SONNET = "claude-sonnet-5"
HAIKU = "claude-haiku-4-5"


@dataclass(frozen=True)
class ModelProfile:
    id: str
    tier: str
    speed: int  # 1 (slow) - 5 (fast)
    quality: int  # 1 - 5
    cost_input: float  # USD per 1M input tokens
    cost_output: float  # USD per 1M output tokens
    supports_adaptive_thinking: bool
    supports_effort: bool


MODEL_PROFILES: dict[str, ModelProfile] = {
    OPUS: ModelProfile(OPUS, "flagship", 2, 5, 5.00, 25.00, True, True),
    SONNET: ModelProfile(SONNET, "balanced", 4, 4, 3.00, 15.00, True, True),
    HAIKU: ModelProfile(HAIKU, "fast", 5, 3, 1.00, 5.00, False, False),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """トークン数から推定コスト(USD)を返す。未知のモデルは最高額で見積もる。"""
    profile = MODEL_PROFILES.get(model)
    if profile is None:
        profile = MODEL_PROFILES[OPUS]
    cost = (
        input_tokens / 1_000_000 * profile.cost_input
        + output_tokens / 1_000_000 * profile.cost_output
    )
    return round(cost, 6)


def cheaper_alternative(model: str) -> str:
    """指定モデルより1段安いモデルを返す(既に最安なら据え置き)。"""
    order = [OPUS, SONNET, HAIKU]
    try:
        idx = order.index(model)
    except ValueError:
        return SONNET
    return order[min(idx + 1, len(order) - 1)]
