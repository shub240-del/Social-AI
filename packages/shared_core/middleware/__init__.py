"""HTTP middleware: request identity, security headers, rate limiting."""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from packages.shared_core.config import get_settings

logger = logging.getLogger(__name__)

RequestHandler = Callable[[Request], Awaitable[Response]]

# Static policy. connect-src stays 'self' because the browser talks to the API
# through the same origin in production (Vercel rewrite) or an explicit origin.
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request id and log one line per request with its duration."""

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = request_id
        started = time.perf_counter()

        response = await call_next(request)

        duration_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{duration_ms:.1f}ms"
        logger.info(
            "%s %s -> %s in %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            extra={"request_id": request_id, "status_code": response.status_code},
        )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Defence-in-depth headers.

    The platform edge may set some of these too; setting them here means they
    are correct even when the app is reached directly.
    """

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        response = await call_next(request)
        settings = get_settings()

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-site"
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        # Naming the stack and version tells an attacker which CVEs to try.
        response.headers["Server"] = "socialai"

        if settings.is_production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains; preload"
            )
        # Auth responses carry tokens; keep them out of shared caches.
        if request.url.path.startswith(f"{settings.api_v1_prefix}/auth"):
            response.headers["Cache-Control"] = "no-store"
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window limiter keyed on client IP.

    In-process only: the effective limit is ``limit x replicas``. That is
    acceptable at one or two workers and must move to Redis before scaling
    out — it is a speed bump against brute force, not a quota system.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    @staticmethod
    def _client_key(request: Request) -> str:
        # Trust the left-most XFF entry only behind a proxy that sets it.
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _limit_for(self, path: str) -> int:
        settings = get_settings()
        # Credential endpoints get a much tighter budget than normal reads.
        sensitive = ("/auth/login", "/auth/register", "/auth/password", "/auth/verify")
        if any(part in path for part in sensitive):
            return settings.auth_rate_limit_per_minute
        return settings.rate_limit_per_minute

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        settings = get_settings()
        if not settings.rate_limit_enabled or request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if path in ("/healthz", "/readyz", "/livez"):
            return await call_next(request)

        limit = self._limit_for(path)
        key = f"{self._client_key(request)}:{limit}"
        now = time.monotonic()
        window = self._hits[key]
        while window and now - window[0] > 60.0:
            window.popleft()

        if len(window) >= limit:
            retry_after = max(1, int(60.0 - (now - window[0])))
            logger.warning("rate limit hit for %s on %s", key, path)
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "rate_limited",
                        "message": "Too many requests. Please slow down.",
                    }
                },
                headers={"Retry-After": str(retry_after)},
            )

        window.append(now)
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - len(window)))
        return response


__all__ = [
    "RateLimitMiddleware",
    "RequestContextMiddleware",
    "SecurityHeadersMiddleware",
]
