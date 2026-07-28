"""Backoff policy shared by every provider client."""

from __future__ import annotations

import random

MAX_BACKOFF_SECONDS = 8.0


def backoff_delay(attempt: int, retry_after: str | None = None) -> float:
    """Seconds to wait before retry number ``attempt`` (zero based).

    ``Retry-After`` wins when the provider sends it, capped so a hostile or
    mistaken header cannot pin a request open for minutes.

    Otherwise exponential with jitter. The jitter is not cosmetic: without it
    every worker that tripped the same rate limit wakes at the same instant and
    re-trips it, turning one burst into a synchronised stampede.
    """
    if retry_after:
        try:
            return min(max(float(retry_after), 0.0), MAX_BACKOFF_SECONDS)
        except ValueError:
            pass
    return min(2.0**attempt, MAX_BACKOFF_SECONDS) * (0.5 + random.random() / 2)


__all__ = ["MAX_BACKOFF_SECONDS", "backoff_delay"]
