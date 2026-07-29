"""Transactional email.

Two backends, chosen by ``EMAIL_BACKEND``:

``console``
    Logs the message instead of sending it. The default for development so the
    signup and reset flows are fully exercisable with no provider account.

``smtp``
    Real delivery. Works with any provider that speaks SMTP (Resend, Postmark,
    SendGrid, SES). Required in production - the config validator rejects
    ``console`` there, because a silently-unsent verification email looks
    identical to a working system until users start complaining.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage

from packages.shared_core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    text: str


class EmailSender:
    def send(self, message: Email) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class ConsoleEmailSender(EmailSender):
    """Writes the message to the log. Never use in production."""

    def send(self, message: Email) -> None:
        logger.warning(
            "EMAIL NOT SENT (console backend)\nTo: %s\nSubject: %s\n\n%s",
            message.to,
            message.subject,
            message.text,
        )


class SmtpEmailSender(EmailSender):
    def send(self, message: Email) -> None:
        s = get_settings()
        msg = EmailMessage()
        msg["From"] = s.email_from
        msg["To"] = message.to
        msg["Subject"] = message.subject
        msg.set_content(message.text)

        if s.smtp_use_tls:
            context = ssl.create_default_context()
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as server:
                server.starttls(context=context)
                if s.smtp_username:
                    server.login(s.smtp_username, s.smtp_password or "")
                server.send_message(msg)
        else:  # pragma: no cover - only for local relays
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as server:
                server.send_message(msg)
        logger.info("sent %s email to %s", message.subject, message.to)


def get_email_sender() -> EmailSender:
    return SmtpEmailSender() if get_settings().email_backend == "smtp" else ConsoleEmailSender()
