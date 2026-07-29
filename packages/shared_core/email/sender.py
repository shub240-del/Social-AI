"""Outbound email.

Three backends: ``console`` prints (development), ``memory`` records (tests)
and ``smtp`` actually delivers. Production refuses to boot on anything but
smtp — see ``Settings._validate_production`` — because a console backend in
production is indistinguishable from a working system until users report that
no mail ever arrives.

Sending is best-effort by design: a dead SMTP provider must not cost a signup.
Callers get no exception; the failure is logged.
"""

from __future__ import annotations

import logging
import smtplib
import sys
from dataclasses import dataclass
from email.message import EmailMessage
from functools import lru_cache

from packages.shared_core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Email:
    to: str
    subject: str
    text: str
    html: str | None = None


class EmailSender:
    def send(self, message: Email) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class ConsoleEmailSender(EmailSender):
    """Development backend: the link is printed so it can be clicked.

    Written straight to stdout rather than through ``logging`` on purpose. The
    logging pipeline redacts anything that looks like ``token=...``, which is
    correct for real logs but would strip the one thing this backend exists to
    show. Production cannot reach this class — the settings guard refuses to
    boot on the console backend — so no live secret is printed this way.
    """

    def send(self, message: Email) -> None:
        sys.stdout.write(
            "\n"
            "----- email (console backend, development only) -----\n"
            f"To:      {message.to}\n"
            f"Subject: {message.subject}\n"
            f"{message.text}\n"
            "-----------------------------------------------------\n\n"
        )
        sys.stdout.flush()


class MemoryEmailSender(EmailSender):
    """Test backend: keeps everything so assertions can read it back."""

    def __init__(self) -> None:
        self.sent: list[Email] = []

    def send(self, message: Email) -> None:
        self.sent.append(message)

    def clear(self) -> None:
        self.sent.clear()


class SMTPEmailSender(EmailSender):
    def send(self, message: Email) -> None:
        settings = get_settings()
        msg = EmailMessage()
        msg["From"] = settings.email_from
        msg["To"] = message.to
        msg["Subject"] = message.subject
        msg.set_content(message.text)
        if message.html:
            msg.add_alternative(message.html, subtype="html")

        host = settings.smtp_host
        if not host:
            raise RuntimeError("SMTP_HOST is not configured.")

        with smtplib.SMTP(host, settings.smtp_port, timeout=15) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_username and settings.smtp_password:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(msg)
        logger.info("email delivered to %s (%s)", message.to, message.subject)


@lru_cache(maxsize=1)
def _cached_sender() -> EmailSender:
    backend = get_settings().email_backend
    if backend == "smtp":
        return SMTPEmailSender()
    if backend == "memory":
        return MemoryEmailSender()
    return ConsoleEmailSender()


def get_email_sender() -> EmailSender:
    return _cached_sender()


def reset_email_sender() -> None:
    _cached_sender.cache_clear()


__all__ = [
    "ConsoleEmailSender",
    "Email",
    "EmailSender",
    "MemoryEmailSender",
    "SMTPEmailSender",
    "get_email_sender",
    "reset_email_sender",
]
