from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI


def message_text(message: Any) -> str:
    """Read normal output, then LM Studio/Qwen's structured-output fallback."""
    if message.content:
        return message.content
    model_extra = getattr(message, "model_extra", None) or {}
    reasoning = model_extra.get("reasoning_content")
    return reasoning if isinstance(reasoning, str) else ""


class LMStudioClient:
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self.model = model

    async def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.1) -> str:
        response = await self.client.chat.completions.create(
            model=self.model, messages=messages, temperature=temperature, stream=False,
            max_tokens=700,
        )
        return message_text(response.choices[0].message)

    async def chat_json(
        self, messages: list[dict[str, str]], schema: dict[str, Any], *, attempts: int = 2,
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for _ in range(attempts):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model, messages=messages, temperature=0, stream=False,
                    max_tokens=600,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {"name": "audit_result", "strict": True, "schema": schema},
                    },
                )
                return json.loads(message_text(response.choices[0].message) or "{}")
            except Exception as exc:
                last_error = exc
        raise RuntimeError("LM Studio did not return valid structured output") from last_error

    async def healthy(self) -> bool:
        try:
            await self.client.models.list()
            return True
        except Exception:
            return False
