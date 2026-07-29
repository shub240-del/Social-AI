"""Logging setup.

JSON in production so a log aggregator can index fields; human-readable lines
in development. Secrets are filtered on the way out — a stray
``logger.info("payload=%s", body)`` must not put a password in the log.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

from packages.shared_core.config import get_settings

_SENSITIVE = re.compile(
    r"(?i)\b(password|new_password|current_password|token|refresh_token|access_token|"
    r"authorization|api[_-]?key|secret)\b(\"?\s*[:=]\s*\"?)([^\s,\"}]+)"
)


def redact(text: str) -> str:
    return _SENSITIVE.sub(r"\1\2[redacted]", text)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        # Only strings are rewritten. Coercing every argument to str would
        # break numeric format specifiers such as "%.1f", which raises inside
        # logging and loses the record entirely.
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: (redact(v) if isinstance(v, str) else v) for k, v in record.args.items()
                }
            else:
                record.args = tuple(
                    redact(a) if isinstance(a, str) else a for a in record.args
                )
        return True


class JSONFormatter(logging.Formatter):
    RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in self.RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    settings = get_settings()
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RedactingFilter())
    handler.setFormatter(
        JSONFormatter()
        if settings.is_production
        else logging.Formatter("%(levelname)-8s %(name)s: %(message)s")
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())

    # Access logs are emitted by RequestContextMiddleware with timing already.
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("httpx").setLevel(logging.WARNING)


__all__ = ["JSONFormatter", "RedactingFilter", "configure_logging", "redact"]
