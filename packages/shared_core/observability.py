"""Error monitoring.

Sentry is initialised only when ``SENTRY_DSN`` is set, and the SDK is an
optional dependency: a missing package logs a warning instead of preventing
start-up, so observability can never take the service down.

Without this, the only record of a production 500 is a log line in Railway
that nobody is watching.
"""

from __future__ import annotations

import logging

from packages.shared_core.config import get_settings

logger = logging.getLogger(__name__)

# Query strings and headers can carry tokens; keep them out of the tracker.
_SCRUB_KEYS = {
    "authorization",
    "cookie",
    "set-cookie",
    "password",
    "new_password",
    "token",
    "refresh_token",
    "access_token",
    "sakana_api_key",
    "jwt_private_key",
}


def _scrub(event: dict, _hint: dict) -> dict:
    """Best-effort redaction before anything leaves the process."""

    def walk(node):
        if isinstance(node, dict):
            return {
                k: ("[redacted]" if k.lower() in _SCRUB_KEYS else walk(v))
                for k, v in node.items()
            }
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(event)


def init_error_monitoring() -> bool:
    """Returns True when a tracker was wired up."""
    settings = get_settings()
    dsn = settings.sentry_dsn
    if not dsn:
        if settings.is_production:
            logger.warning(
                "SENTRY_DSN is not set: production errors will only appear in logs"
            )
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
    except ImportError:
        logger.warning("SENTRY_DSN is set but sentry-sdk is not installed; skipping")
        return False

    sentry_sdk.init(
        dsn=dsn,
        environment=settings.environment,
        release=settings.release_version,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        # PII stays out by default; the scrubber is the second line of defence.
        send_default_pii=False,
        before_send=_scrub,
        integrations=[StarletteIntegration(), FastApiIntegration()],
    )
    logger.info("error monitoring enabled (environment=%s)", settings.environment)
    return True
