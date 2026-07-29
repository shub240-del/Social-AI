"""Application exception taxonomy.

Every error carries a stable machine-readable ``code`` so the frontend can
branch on failures without string-matching human-readable messages.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for all handled application errors."""

    status_code: int = 500
    code: str = "internal_error"
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"error": {"code": self.code, "message": self.message}}
        if self.details:
            payload["error"]["details"] = self.details
        return payload


# ---- 400 family ------------------------------------------------------


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"
    message = "The request payload is invalid."


class BadRequestError(AppError):
    status_code = 400
    code = "bad_request"
    message = "The request could not be processed."


# ---- auth ------------------------------------------------------------


class AuthenticationError(AppError):
    status_code = 401
    code = "unauthenticated"
    message = "Authentication is required."


class InvalidCredentialsError(AuthenticationError):
    code = "invalid_credentials"
    message = "Email or password is incorrect."


class EmailNotVerifiedError(AuthenticationError):
    code = "email_not_verified"
    message = "Confirm your email address before logging in."


class TokenExpiredError(AuthenticationError):
    code = "token_expired"
    message = "The access token has expired."


class InvalidTokenError(AuthenticationError):
    code = "invalid_token"
    message = "The access token is invalid."


class AuthorizationError(AppError):
    status_code = 403
    code = "forbidden"
    message = "You do not have permission to perform this action."


# ---- resources -------------------------------------------------------


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "The requested resource was not found."


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    message = "The resource already exists."


class RateLimitError(AppError):
    status_code = 429
    code = "rate_limited"
    message = "Too many requests. Please slow down."


# ---- downstream ------------------------------------------------------


class UpstreamError(AppError):
    status_code = 502
    code = "upstream_error"
    message = "An upstream service failed."


class LLMError(UpstreamError):
    code = "llm_error"
    message = "The AI provider could not complete the request."


class LLMTimeoutError(LLMError):
    status_code = 504
    code = "llm_timeout"
    message = "The AI provider timed out."


class LLMRateLimitError(LLMError):
    status_code = 429
    code = "llm_rate_limited"
    message = "The AI provider rate limit was reached. Try again shortly."
