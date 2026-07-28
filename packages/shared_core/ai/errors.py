"""Mapping provider HTTP failures onto the application's exception types.

The exception classes themselves stay in :mod:`packages.shared_core.exceptions`
and are only re-exported here. Defining a second, parallel hierarchy inside the
AI package would mean the global error handler in ``main.py`` no longer
recognises these errors, and every provider fault would surface as an
unhandled 500 instead of a mapped response.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.shared_core.exceptions import (
    LLMError,
    LLMNotConfiguredError,
    LLMRateLimitError,
    LLMTimeoutError,
)

logger = logging.getLogger(__name__)

#: Statuses worth trying again. A 429 is included because it is usually a
#: transient burst limit -- except for the quota cases handled below, which are
#: 429s that no amount of waiting will clear.
RETRY_STATUS: frozenset[int] = frozenset({408, 409, 429, 500, 502, 503, 504})

#: OpenAI-style ``error.type`` values that mean "your account cannot spend",
#: not "you are going too fast". Sakana returns ``usage_limit_reached`` with a
#: 429 when the key is valid but has no active subscription. Retrying that
#: burns the caller's request timeout to arrive at the same answer, so it is
#: raised immediately as a configuration fault.
QUOTA_ERROR_TYPES: frozenset[str] = frozenset(
    {"usage_limit_reached", "insufficient_quota", "billing_not_active"}
)


def extract_error(body: Any) -> tuple[str | None, str | None]:
    """Return ``(type, message)`` from an OpenAI-shaped error envelope."""
    if not isinstance(body, dict):
        return None, None
    err = body.get("error")
    if not isinstance(err, dict):
        return None, None
    etype = err.get("type")
    message = err.get("message")
    return (
        etype if isinstance(etype, str) else None,
        message if isinstance(message, str) else None,
    )


def is_quota_error(body: Any) -> bool:
    etype, _ = extract_error(body)
    return etype in QUOTA_ERROR_TYPES


def raise_for_status(provider: str, status: int, body: Any) -> None:
    """Translate a non-200 provider response into an application error.

    Returns normally only when the status is retryable and the caller still
    has attempts left to spend.
    """
    etype, message = extract_error(body)
    detail = message or f"HTTP {status}"

    # A revoked or wrong key cannot be fixed by waiting.
    if status in (401, 403):
        logger.error("%s rejected our credentials (%s): %s", provider, status, detail)
        raise LLMNotConfiguredError(
            "The AI provider rejected our credentials. The API key is missing, "
            "revoked, or lacks access to this model."
        )

    # A valid key with no billing behind it. Surfaced as a configuration fault
    # so the operator sees the cause instead of a generic "try again later".
    if is_quota_error(body):
        logger.error("%s quota exhausted: %s", provider, detail)
        raise LLMNotConfiguredError(
            f"The AI provider has no available quota: {detail}",
            details={"provider": provider, "error_type": etype},
        )

    if status == 404:
        raise LLMError(
            f"The AI provider does not recognise the requested model: {detail}",
            details={"status": status},
        )

    if status in (400, 422):
        raise LLMError(
            f"The AI provider rejected the request: {detail}",
            details={"status": status},
        )

    if status not in RETRY_STATUS:
        raise LLMError(
            f"The AI provider returned {status}.",
            details={"status": status},
        )


def exhausted(provider: str, status: int | None, last_error: str) -> LLMError:
    """The error to raise once every retry has been spent."""
    if status == 429:
        return LLMRateLimitError()
    return LLMError(
        f"The AI provider is unavailable ({last_error}).",
        details={"provider": provider, "status": status},
    )


__all__ = [
    "QUOTA_ERROR_TYPES",
    "RETRY_STATUS",
    "LLMError",
    "LLMNotConfiguredError",
    "LLMRateLimitError",
    "LLMTimeoutError",
    "exhausted",
    "extract_error",
    "is_quota_error",
    "raise_for_status",
]
