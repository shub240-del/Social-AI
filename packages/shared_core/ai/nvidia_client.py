"""NVIDIA NIM chat client (OpenAI-compatible API).

Talks to ``/v1/chat/completions`` over httpx directly rather than through the
OpenAI SDK, so timeout, retry and error-mapping behaviour is explicit and
testable. When no API key is configured a deterministic local provider is used
instead, which keeps the whole product flow exercisable without credentials.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from packages.shared_core.config import Settings, get_settings
from packages.shared_core.exceptions import (
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
)

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


@dataclass(slots=True)
class ChatMessage:
    role: str
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(slots=True)
class ChatResult:
    content: str
    model: str
    tokens: int
    provider: str


class NvidiaClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: httpx.AsyncClient | None = None

    # ---- lifecycle ---------------------------------------------------

    async def startup(self) -> None:
        if self.settings.llm_enabled and self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.settings.nvidia_api_base_url.rstrip("/"),
                timeout=httpx.Timeout(self.settings.llm_timeout_seconds, connect=10.0),
                headers={
                    "Authorization": f"Bearer {self.settings.nvidia_api_key}",
                    "Accept": "application/json",
                },
                limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
            )

    async def shutdown(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def provider(self) -> str:
        return "nvidia" if self.settings.llm_enabled else "mock"

    def health(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.settings.default_llm_model,
            "configured": self.settings.llm_enabled,
        }

    # ---- public API --------------------------------------------------

    async def complete(
        self, messages: list[ChatMessage], *, model: str | None = None
    ) -> ChatResult:
        if not self.settings.llm_enabled:
            return _mock_completion(messages, self.settings)
        model = model or self.settings.default_llm_model
        payload = {
            "model": model,
            "messages": [m.as_dict() for m in messages],
            "max_tokens": self.settings.llm_max_output_tokens,
            "temperature": 0.7,
            "stream": False,
        }
        data = await self._post_with_retry("/chat/completions", payload)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("Malformed response from AI provider.") from exc
        usage = data.get("usage") or {}
        return ChatResult(
            content=content,
            model=data.get("model", model),
            tokens=int(usage.get("total_tokens", 0) or 0),
            provider="nvidia",
        )

    async def stream(
        self, messages: list[ChatMessage], *, model: str | None = None
    ) -> AsyncIterator[str]:
        """Yield content deltas as they arrive."""
        if not self.settings.llm_enabled:
            for chunk in _mock_stream(messages, self.settings):
                await asyncio.sleep(0)
                yield chunk
            return

        assert self._client is not None, "startup() was not awaited"
        model = model or self.settings.default_llm_model
        payload = {
            "model": model,
            "messages": [m.as_dict() for m in messages],
            "max_tokens": self.settings.llm_max_output_tokens,
            "temperature": 0.7,
            "stream": True,
        }
        try:
            async with self._client.stream(
                "POST", "/chat/completions", json=payload
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", "replace")
                    raise _map_status(response.status_code, body)
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data in ("", "[DONE]"):
                        continue
                    try:
                        delta = json.loads(data)["choices"][0]["delta"]
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    piece = delta.get("content")
                    if piece:
                        yield piece
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError() from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"AI provider transport error: {exc}") from exc

    # ---- internals ---------------------------------------------------

    async def _post_with_retry(self, path: str, payload: dict) -> dict:
        assert self._client is not None, "startup() was not awaited"
        attempts = self.settings.llm_max_retries + 1
        last: Exception | None = None

        for attempt in range(attempts):
            try:
                response = await self._client.post(path, json=payload)
                if response.status_code < 400:
                    return response.json()
                if response.status_code in RETRYABLE_STATUS and attempt < attempts - 1:
                    await self._backoff(attempt, response)
                    continue
                raise _map_status(response.status_code, response.text)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = exc
                if attempt < attempts - 1:
                    await self._backoff(attempt, None)
                    continue
                if isinstance(exc, httpx.TimeoutException):
                    raise LLMTimeoutError() from exc
                raise LLMError(f"AI provider transport error: {exc}") from exc

        raise LLMError("AI provider request failed.") from last

    @staticmethod
    async def _backoff(attempt: int, response: httpx.Response | None) -> None:
        # Honour Retry-After when the provider supplies it.
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    await asyncio.sleep(min(float(retry_after), 10.0))
                    return
                except ValueError:
                    pass
        # Exponential backoff with jitter to avoid synchronised retries.
        delay = min(2**attempt * 0.5, 8.0) * (0.5 + random.random() / 2)
        logger.warning("Retrying AI provider call in %.2fs (attempt %d)", delay, attempt + 1)
        await asyncio.sleep(delay)


def _map_status(status: int, body: str) -> LLMError:
    snippet = body[:300]
    if status == 429:
        return LLMRateLimitError()
    if status in (401, 403):
        # Never surface the upstream body here; it can echo the API key.
        logger.error("AI provider rejected credentials (status %s)", status)
        return LLMError("AI provider authentication failed.", code="llm_auth_failed")
    if status == 408 or status == 504:
        return LLMTimeoutError()
    logger.error("AI provider error %s: %s", status, snippet)
    return LLMError(f"AI provider returned status {status}.")


# ---- deterministic fallback provider ---------------------------------


def _mock_reply(messages: list[ChatMessage]) -> str:
    prompt = next(
        (m.content for m in reversed(messages) if m.role == "user"), ""
    ).strip()
    system = next((m.content for m in messages if m.role == "system"), "")
    brand = ""
    if "Brand:" in system:
        brand = system.split("Brand:", 1)[1].split("\n", 1)[0].strip()
    header = f"[local preview{' · ' + brand if brand else ''}]"
    return (
        f"{header} Here are three post ideas for: \u201c{prompt[:160]}\u201d\n\n"
        "1. Lead with the outcome, not the feature. Open on the result your "
        "audience wants and let the product be the mechanism.\n"
        "2. Show the work. A short behind-the-scenes clip consistently "
        "outperforms a polished promo on most feeds.\n"
        "3. Close with one clear ask. A single call to action beats three "
        "competing ones.\n\n"
        "Set NVIDIA_API_KEY to generate with "
        "meta/llama-3.1-70b-instruct instead of this local preview."
    )


def _mock_completion(messages: list[ChatMessage], settings: Settings) -> ChatResult:
    text = _mock_reply(messages)
    return ChatResult(
        content=text,
        model=f"{settings.default_llm_model} (mock)",
        tokens=len(text.split()),
        provider="mock",
    )


def _mock_stream(messages: list[ChatMessage], settings: Settings) -> list[str]:
    text = _mock_reply(messages)
    return [text[i : i + 24] for i in range(0, len(text), 24)]


_client: NvidiaClient | None = None


def get_ai_client() -> NvidiaClient:
    global _client
    if _client is None:
        _client = NvidiaClient()
    return _client
