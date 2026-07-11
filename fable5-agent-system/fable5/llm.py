"""LLM クライアント層。

- AnthropicLLMClient: 実際の Claude API を呼ぶ(anthropic SDK)。
- MockLLMClient: オフラインテスト・デモ用のスクリプト応答クライアント。

どちらも同じ ``complete()`` インターフェースを持ち、上位層(ExecutionLoop /
DriftMonitor / SkillAutoGenerator)から差し替え可能。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import MODEL_PROFILES, OPUS


@dataclass
class LLMResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    stop_reason: str = "end_turn"


class LLMClient(Protocol):
    def complete(
        self,
        prompt: str,
        *,
        model: str = OPUS,
        system: str | None = None,
        max_tokens: int = 4096,
        effort: str | None = None,
    ) -> LLMResult: ...


class AnthropicLLMClient:
    """anthropic SDK を使う本番クライアント。

    認証は SDK の標準解決順(ANTHROPIC_API_KEY → ANTHROPIC_AUTH_TOKEN →
    `ant auth login` プロファイル)に従う。
    """

    def __init__(self, client=None):
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self._client = client

    def complete(
        self,
        prompt: str,
        *,
        model: str = OPUS,
        system: str | None = None,
        max_tokens: int = 4096,
        effort: str | None = None,
    ) -> LLMResult:
        profile = MODEL_PROFILES.get(model)
        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        if profile and profile.supports_adaptive_thinking:
            kwargs["thinking"] = {"type": "adaptive"}
        if effort and profile and profile.supports_effort:
            kwargs["output_config"] = {"effort": effort}

        # 大きな max_tokens は HTTP タイムアウト回避のためストリーミングで取得する
        if max_tokens > 16_000:
            with self._client.messages.stream(**kwargs) as stream:
                response = stream.get_final_message()
        else:
            response = self._client.messages.create(**kwargs)

        text = "".join(
            block.text for block in response.content if block.type == "text"
        )
        return LLMResult(
            text=text,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            stop_reason=response.stop_reason or "end_turn",
        )


class MockLLMClient:
    """テスト・オフラインデモ用。応答をキューで返す。"""

    def __init__(self, responses: list[str] | None = None):
        self.responses = list(responses or [])
        self.calls: list[dict] = []

    def queue(self, *responses: str) -> None:
        self.responses.extend(responses)

    def complete(
        self,
        prompt: str,
        *,
        model: str = OPUS,
        system: str | None = None,
        max_tokens: int = 4096,
        effort: str | None = None,
    ) -> LLMResult:
        self.calls.append(
            {"prompt": prompt, "model": model, "system": system, "effort": effort}
        )
        text = self.responses.pop(0) if self.responses else "(mock response)"
        return LLMResult(
            text=text,
            model=model,
            input_tokens=max(1, len(prompt) // 4),
            output_tokens=max(1, len(text) // 4),
        )
