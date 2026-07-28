"""Application error hierarchy.

Every error the API returns is an ``AppError``. Each carries a stable machine
``code`` alongside a human message, because clients need to branch on
something that will not change when the wording is improved. The response
envelope is always::

    {"error": {"code": "...", "message": "...", "details": {...}}}

Messages are written for end users and deliberately avoid leaking whether an
account exists, which table failed, or what a token contained.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for every expected failure."""

    status_code: int = 400
    code: str = "bad_request"
    message: str = "The request could not be completed."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return {"error": payload}


# ---- 400 / 422 -------------------------------------------------------


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"
    message = "The submitted data is not valid."


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    message = "That resource already exists."


# ---- 401 -------------------------------------------------------------


class AuthenticationError(AppError):
    status_code = 401
    code = "unauthenticated"
    message = "Authentication is required."


class InvalidCredentialsError(AuthenticationError):
    code = "invalid_credentials"
    # Identical for an unknown address and a wrong password, so the endpoint
    # cannot be used to enumerate registered users.
    message = "Incorrect email or password."


class InvalidTokenError(AuthenticationError):
    code = "invalid_token"
    message = "This token is invalid."


class TokenExpiredError(AuthenticationError):
    code = "token_expired"
    message = "This token has expired."


class EmailNotVerifiedError(AuthenticationError):
    code = "email_not_verified"
    message = "Confirm your email address before logging in."


# ---- 403 -------------------------------------------------------------


class AuthorizationError(AppError):
    status_code = 403
    code = "forbidden"
    message = "You do not have permission to do that."


class PermissionDeniedError(AuthorizationError):
    code = "permission_denied"


# ---- 404 -------------------------------------------------------------


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "That resource does not exist."


# ---- 429 / 5xx -------------------------------------------------------


class RateLimitError(AppError):
    status_code = 429
    code = "rate_limited"
    message = "Too many requests. Please slow down."


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"
    message = "A dependency is unavailable. Please try again shortly."


class LLMError(AppError):
    status_code = 502
    code = "llm_error"
    message = "The AI provider could not complete this request."


class LLMTimeoutError(LLMError):
    status_code = 504
    code = "llm_timeout"
    message = "The AI provider took too long to respond."


class LLMRateLimitError(LLMError):
    status_code = 429
    code = "llm_rate_limited"
    message = "The AI provider is rate limiting us. Please retry shortly."


class LLMNotConfiguredError(LLMError):
    status_code = 503
    code = "llm_not_configured"
    message = "No AI provider is configured."


__all__ = [
    "AppError",
    "AuthenticationError",
    "AuthorizationError",
    "ConflictError",
    "EmailNotVerifiedError",
    "InvalidCredentialsError",
    "InvalidTokenError",
    "LLMError",
    "LLMNotConfiguredError",
    "LLMRateLimitError",
    "LLMTimeoutError",
    "NotFoundError",
    "PermissionDeniedError",
    "RateLimitError",
    "ServiceUnavailableError",
    "TokenExpiredError",
    "ValidationError",
]
