"""NVIDIA NIM chat-completion client.

Talks to the OpenAI-compatible endpoint at ``integrate.api.nvidia.com``.

Three things this handles that a bare ``httpx.post`` does not:

* **Retries** on 429 and 5xx with exponential backoff and jitter, honouring
  ``Retry-After``. Jitter matters because without it every worker that hit the
  same rate limit retries in lockstep and re-triggers it.
* **Error mapping** onto the application's exception types, so a provider
  outage becomes a 502 with a stable code rather than an unhandled 500.
* **A mock provider** for development and tests. It is refused in production by
  the settings guard, so it can never silently serve canned text to users.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from packages.shared_core.config import get_settings
from packages.shared_core.exceptions import (
    LLMError,
    LLMNotConfiguredError,
    LLMRateLimitError,
    LLMTimeoutError,
)

logger = logging.getLogger(__name__)

RETRY_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})
MAX_BACKOFF_SECONDS = 8.0


@dataclass(slots=True)
class ChatMessage:
    role: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(slots=True)
class Completion:
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    provider: str = "nvidia"
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def _backoff(attempt: int, retry_after: str | None) -> float:
    if retry_after:
        try:
            return min(float(retry_after), MAX_BACKOFF_SECONDS)
        except ValueError:
            pass
    return min(2.0**attempt, MAX_BACKOFF_SECONDS) * (0.5 + random.random() / 2)


class MockLLMClient:
    """Deterministic stand-in used when no API key is configured.

    Every response says "mock" on purpose: the post-deploy check asserts that
    production output does *not* contain it, which turns an accidentally
    mock-configured production deploy into a failed verification.
    """

    provider = "mock"

    def __init__(self, model: str = "mock/social-ai") -> None:
        self.model = model

    def _reply(self, messages: list[ChatMessage]) -> str:
        prompt = next(
            (m.content for m in reversed(messages) if m.role == "user"), "your request"
        )
        trimmed = prompt.strip()[:180]
        return (
            f"[mock completion] Here is a draft responding to: {trimmed}\n\n"
            "1. Lead with the outcome, not the feature.\n"
            "2. Keep it under two sentences.\n"
            "3. Close with one clear call to action.\n\n"
            "Set NVIDIA_API_KEY and ALLOW_MOCK_LLM=false for real generations."
        )

    async def complete(
        self, messages: list[ChatMessage], **_: Any
    ) -> Completion:
        started = time.perf_counter()
        await asyncio.sleep(0)  # keep the call genuinely awaitable
        text = self._reply(messages)
        return Completion(
            content=text,
            model=self.model,
            prompt_tokens=sum(len(m.content.split()) for m in messages),
            completion_tokens=len(text.split()),
            latency_ms=int((time.perf_counter() - started) * 1000),
            provider=self.provider,
        )

    async def stream(self, messages: list[ChatMessage], **_: Any) -> AsyncIterator[str]:
        for word in self._reply(messages).split(" "):
            await asyncio.sleep(0)
            yield word + " "


class NvidiaClient:
    """Thin async client over the NVIDIA OpenAI-compatible chat API."""

    provider = "nvidia"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 60.0,
        max_retries: int = 3,
        max_output_tokens: int = 1024,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_output_tokens = max_output_tokens

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _payload(
        self, messages: list[ChatMessage], *, stream: bool, temperature: float, model: str | None
    ) -> dict[str, Any]:
        return {
            "model": model or self.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature,
            "max_tokens": self.max_output_tokens,
            "stream": stream,
        }

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.7,
        model: str | None = None,
    ) -> Completion:
        payload = self._payload(messages, stream=False, temperature=temperature, model=model)
        started = time.perf_counter()
        last_error: str = "unknown error"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(self.max_retries + 1):
                try:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        json=payload,
                        headers=self._headers(),
                    )
                except httpx.TimeoutException as exc:
                    last_error = f"timeout: {exc}"
                    if attempt == self.max_retries:
                        raise LLMTimeoutError(
                            f"The AI provider did not respond within {self.timeout:.0f}s."
                        ) from exc
                except httpx.RequestError as exc:
                    last_error = f"transport: {exc}"
                    if attempt == self.max_retries:
                        raise LLMError(f"Could not reach the AI provider: {exc}") from exc
                else:
                    if response.status_code == 200:
                        return self._parse(response.json(), started)

                    # 401/403 are configuration faults; retrying cannot fix a
                    # revoked key and only delays a clear error.
                    if response.status_code in (401, 403):
                        logger.error("NVIDIA rejected our credentials (%s)", response.status_code)
                        raise LLMNotConfiguredError(
                            "The AI provider rejected our credentials. The API key is "
                            "missing, revoked or lacks access to this model."
                        )
                    if response.status_code not in RETRY_STATUS:
                        raise LLMError(
                            f"The AI provider returned {response.status_code}.",
                            details={"status": response.status_code},
                        )

                    last_error = f"http {response.status_code}"
                    if attempt == self.max_retries:
                        if response.status_code == 429:
                            raise LLMRateLimitError()
                        raise LLMError(
                            f"The AI provider is failing ({response.status_code}).",
                            details={"status": response.status_code},
                        )
                    delay = _backoff(attempt, response.headers.get("retry-after"))
                    logger.warning(
                        "NVIDIA %s; retry %d/%d in %.2fs",
                        response.status_code,
                        attempt + 1,
                        self.max_retries,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                delay = _backoff(attempt, None)
                logger.warning(
                    "NVIDIA %s; retry %d/%d in %.2fs",
                    last_error,
                    attempt + 1,
                    self.max_retries,
                    delay,
                )
                await asyncio.sleep(delay)

        raise LLMError(f"The AI provider could not be reached ({last_error}).")

    def _parse(self, body: dict[str, Any], started: float) -> Completion:
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("The AI provider returned an unreadable response.") from exc
        usage = body.get("usage") or {}
        return Completion(
            content=content,
            model=body.get("model", self.model),
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            latency_ms=int((time.perf_counter() - started) * 1000),
            provider=self.provider,
            raw=body,
        )

    async def stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.7,
        model: str | None = None,
    ) -> AsyncIterator[str]:
        """Yield content deltas as server-sent events arrive."""
        import json

        payload = self._payload(messages, stream=True, temperature=temperature, model=model)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=self._headers(),
                ) as response:
                    if response.status_code != 200:
                        await response.aread()
                        if response.status_code in (401, 403):
                            raise LLMNotConfiguredError()
                        if response.status_code == 429:
                            raise LLMRateLimitError()
                        raise LLMError(f"The AI provider returned {response.status_code}.")
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data in ("", "[DONE]"):
                            if data == "[DONE]":
                                break
                            continue
                        try:
                            chunk = json.loads(data)
                            delta = chunk["choices"][0]["delta"].get("content")
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue  # keepalives and partial frames are normal
                        if delta:
                            yield delta
            except httpx.TimeoutException as exc:
                raise LLMTimeoutError() from exc
            except httpx.RequestError as exc:
                raise LLMError(f"Could not reach the AI provider: {exc}") from exc


def get_llm_client() -> NvidiaClient | MockLLMClient:
    """Pick a provider from configuration.

    Production can only reach the real client: the settings guard refuses to
    boot with ALLOW_MOCK_LLM or without a key.
    """
    settings = get_settings()
    if settings.llm_enabled:
        return NvidiaClient(
            api_key=settings.nvidia_api_key or "",
            base_url=settings.nvidia_api_base_url,
            model=settings.default_llm_model,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            max_output_tokens=settings.llm_max_output_tokens,
        )
    if settings.allow_mock_llm:
        return MockLLMClient()
    raise LLMNotConfiguredError(
        "NVIDIA_API_KEY is not set and the mock provider is disabled."
    )


__all__ = [
    "ChatMessage",
    "Completion",
    "MockLLMClient",
    "NvidiaClient",
    "get_llm_client",
]
