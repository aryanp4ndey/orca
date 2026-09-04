"""Provider-agnostic LLM clients (OpenAI-compatible and Anthropic Messages).

Both are optional and configured entirely from the environment; no key means
:class:`NullLLM` and the deterministic path.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.config.settings import Settings
from app.llm.base import LLMClient, LLMUnavailable, NullLLM, extract_json
from app.providers.http import get_http_client


class OpenAICompatibleLLM(LLMClient):
    name = "openai_compatible"

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.model)

    async def _chat(self, system: str, user: str, timeout_ms: int,
                    max_tokens: int) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": 0.0,
            "max_tokens": max_tokens,
        }
        resp = await asyncio.wait_for(
            get_http_client().post(
                f"{self.base_url}/chat/completions", json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"}),
            timeout=timeout_ms / 1000.0)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    async def complete_json(self, system: str, user: str, timeout_ms: int) -> dict:
        return extract_json(await self._chat(system, user, timeout_ms, 500))

    async def complete_text(self, system: str, user: str, timeout_ms: int,
                            max_tokens: int = 400) -> str:
        return await self._chat(system, user, timeout_ms, max_tokens)


class AnthropicLLM(LLMClient):
    name = "anthropic"

    def __init__(self, api_key: str, model: str,
                 base_url: str = "https://api.anthropic.com") -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.model)

    async def _messages(self, system: str, user: str, timeout_ms: int,
                        max_tokens: int) -> str:
        resp = await asyncio.wait_for(
            get_http_client().post(
                f"{self.base_url}/v1/messages",
                json={"model": self.model, "max_tokens": max_tokens,
                      "temperature": 0.0, "system": system,
                      "messages": [{"role": "user", "content": user}]},
                headers={"x-api-key": self.api_key,
                         "anthropic-version": "2023-06-01"}),
            timeout=timeout_ms / 1000.0)
        resp.raise_for_status()
        blocks = resp.json().get("content", [])
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")

    async def complete_json(self, system: str, user: str, timeout_ms: int) -> dict:
        return extract_json(await self._messages(system, user, timeout_ms, 500))

    async def complete_text(self, system: str, user: str, timeout_ms: int,
                            max_tokens: int = 400) -> str:
        return await self._messages(system, user, timeout_ms, max_tokens)


def build_llm(settings: Settings) -> LLMClient:
    if settings.llm_provider == "openai_compatible" and settings.llm_api_key:
        return OpenAICompatibleLLM(
            settings.llm_base_url or "https://api.openai.com/v1",
            settings.llm_api_key, settings.llm_model or "gpt-4o-mini")
    if settings.llm_provider == "anthropic" and settings.llm_api_key:
        return AnthropicLLM(settings.llm_api_key,
                            settings.llm_model or "claude-sonnet-4-5",
                            settings.llm_base_url or "https://api.anthropic.com")
    return NullLLM()


__all__ = ["OpenAICompatibleLLM", "AnthropicLLM", "build_llm", "LLMUnavailable"]
