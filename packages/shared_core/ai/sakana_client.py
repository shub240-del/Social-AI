"""Sakana AI (Fugu) chat-completion client.

Sakana exposes an OpenAI-compatible surface at ``https://api.sakana.ai/v1``,
authenticated with ``Authorization: Bearer $SAKANA_API_KEY``. This client uses
the Chat Completions endpoint, which is what the conversation flow needs.

Two Sakana-specific behaviours are worth knowing:

* **Fugu is a multi-agent system, not a single forward pass.** It orchestrates
  frontier models across several steps, so latency is far higher than a plain
  chat model and Sakana's own documentation recommends raising client
  timeouts. The default here is 120s rather than the 60s used for a
  single-model provider.
* **A valid key with no subscription answers 429 ``usage_limit_reached``.**
  That is a billing state, not a burst limit, so it is raised immediately
  instead of being retried. See :mod:`packages.shared_core.ai.errors`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from packages.shared_core.ai.base import BaseAIProvider
from packages.shared_core.ai.errors import (
    LLMError,
    LLMTimeoutError,
    exhausted,
    raise_for_status,
)
from packages.shared_core.ai.retry import backoff_delay
from packages.shared_core.ai.types import ChatMessage, Completion

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.sakana.ai/v1"

#: Reasoning levels Fugu accepts. ``fugu-ultra-v1.1`` additionally supports
#: "max"; the others accept it but map it onto "xhigh". Anything else is
#: rejected by the API, so an unknown value is dropped rather than forwarded.
VALID_REASONING_EFFORTS: frozenset[str] = frozenset({"high", "xhigh", "max"})


class SakanaClient(BaseAIProvider):
    """Async client over Sakana's OpenAI-compatible chat API."""

    provider = "sakana"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        model: str = "fugu",
        timeout: float = 120.0,
        max_retries: int = 3,
        max_output_tokens: int = 1024,
        reasoning_effort: str | None = None,
    ) -> None:
        if not api_key:
            # Guarded here as well as in the factory: constructing a client
            # with no credential can only produce a confusing 401 later.
            raise LLMError("SakanaClient requires an API key.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_output_tokens = max_output_tokens
        self.reasoning_effort = (
            reasoning_effort if reasoning_effort in VALID_REASONING_EFFORTS else None
        )

    # ---- request building ------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _payload(
        self,
        messages: list[ChatMessage],
        *,
        stream: bool,
        temperature: float,
        model: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature,
            "max_tokens": self.max_output_tokens,
            "stream": stream,
        }
        if self.reasoning_effort:
            payload["reasoning"] = {"effort": self.reasoning_effort}
        return payload

    @staticmethod
    def _body_of(response: httpx.Response) -> Any:
        """Parse an error body without letting a non-JSON page raise."""
        try:
            return response.json()
        except ValueError:
            return {"error": {"message": response.text[:300]}}

    # ---- completion ------------------------------------------------------

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.7,
        model: str | None = None,
    ) -> Completion:
        self.validate_messages(messages)
        payload = self._payload(messages, stream=False, temperature=temperature, model=model)
        started = time.perf_counter()
        last_error = "unknown error"
        last_status: int | None = None

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

                    # Raises for anything permanent; returns for retryables.
                    raise_for_status(
                        self.provider, response.status_code, self._body_of(response)
                    )

                    last_status = response.status_code
                    last_error = f"http {response.status_code}"
                    if attempt == self.max_retries:
                        raise exhausted(self.provider, last_status, last_error)

                    delay = backoff_delay(attempt, response.headers.get("retry-after"))
                    logger.warning(
                        "sakana %s; retry %d/%d in %.2fs",
                        response.status_code,
                        attempt + 1,
                        self.max_retries,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                delay = backoff_delay(attempt)
                logger.warning(
                    "sakana %s; retry %d/%d in %.2fs",
                    last_error,
                    attempt + 1,
                    self.max_retries,
                    delay,
                )
                await asyncio.sleep(delay)

        raise exhausted(self.provider, last_status, last_error)

    def _parse(self, body: Any, started: float) -> Completion:
        """Validate and normalise a 200 response.

        A 200 carrying an unusable body is treated as a provider failure rather
        than allowed to surface later as an AttributeError deep in the router.
        """
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("The AI provider returned an unreadable response.") from exc

        if not isinstance(content, str) or not content.strip():
            raise LLMError("The AI provider returned an empty response.")

        usage = body.get("usage") or {}
        return Completion(
            content=content,
            model=body.get("model", self.model),
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
            latency_ms=int((time.perf_counter() - started) * 1000),
            provider=self.provider,
            raw=body if isinstance(body, dict) else {},
        )

    # ---- streaming -------------------------------------------------------

    async def stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.7,
        model: str | None = None,
    ) -> AsyncIterator[str]:
        """Yield content deltas from the server-sent event stream.

        Not retried: once the response has begun the client has already emitted
        tokens downstream, and replaying the request would duplicate them.
        """
        self.validate_messages(messages)
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
                        body = self._body_of(response)
                        raise_for_status(self.provider, response.status_code, body)
                        # Retryable status, but a stream has no second attempt.
                        raise exhausted(
                            self.provider, response.status_code, f"http {response.status_code}"
                        )

                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        if not data:
                            continue
                        try:
                            chunk = json.loads(data)
                            delta = chunk["choices"][0]["delta"].get("content")
                        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                            # Keepalives, role-only first frames and partial
                            # frames are all normal in an SSE stream.
                            continue
                        if delta:
                            yield delta
            except httpx.TimeoutException as exc:
                raise LLMTimeoutError() from exc
            except httpx.RequestError as exc:
                raise LLMError(f"Could not reach the AI provider: {exc}") from exc


__all__ = ["DEFAULT_BASE_URL", "VALID_REASONING_EFFORTS", "SakanaClient"]
