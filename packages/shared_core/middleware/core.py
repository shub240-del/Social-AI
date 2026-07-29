"""Cross-cutting HTTP middleware: request IDs, access logs, rate limiting."""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from packages.shared_core.config import get_settings

logger = logging.getLogger("socialai.access")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request id, expose it as a header, and log the outcome."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration = (time.perf_counter() - started) * 1000
            logger.exception(
                "request failed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round(duration, 2),
                },
            )
            raise
        duration = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-ms"] = f"{duration:.2f}"
        logger.info(
            "%s %s -> %s (%.2fms)",
            request.method,
            request.url.path,
            response.status_code,
            duration,
            extra={"request_id": request_id},
        )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        # The API returns JSON only; a restrictive CSP costs nothing and blocks
        # rendering of any content that is reflected back to a browser.
        response.headers.setdefault(
            "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
        )
        # Announcing the exact server makes CVE matching trivial for scanners.
        response.headers["Server"] = "socialai"
        if get_settings().is_production:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
            )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window-per-key limiter.

    In-process only: each replica keeps its own counters, so the effective
    global limit is (limit x replicas). Adequate as an abuse floor for launch;
    move the counters to Redis before scaling out horizontally.
    """

    def __init__(self, app) -> None:
        super().__init__(app)
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    # Only endpoints that accept credentials get the strict bucket. /auth/me and
    # /auth/logout are ordinary authenticated calls - /auth/me in particular is
    # hit on every dashboard load, so throttling it at the credential rate
    # locks out normal users.
    CREDENTIAL_PATHS = (
        "/api/v1/auth/login",
        "/api/v1/auth/register",
        "/api/v1/auth/refresh",
        # Unauthenticated and email-sending: without the strict bucket these
        # are a free spam relay and a user-enumeration oracle.
        "/api/v1/auth/verify/request",
        "/api/v1/auth/verify/confirm",
        "/api/v1/auth/password/forgot",
        "/api/v1/auth/password/reset",
        "/api/v1/auth/password/change",
    )

    def _bucket_for(self, path: str) -> tuple[str, int]:
        """Return (bucket name, limit).

        The bucket must be identified by name rather than by its limit value:
        keying on the number alone silently merges two buckets whenever their
        configured limits happen to be equal, which would let chat traffic
        consume the default allowance and vice versa.
        """
        s = get_settings()
        if path in self.CREDENTIAL_PATHS:
            return "auth", s.rate_limit_auth_per_minute
        if path.endswith("/chat") or path.endswith("/chat/stream"):
            return "chat", s.rate_limit_chat_per_minute
        return "default", s.rate_limit_default_per_minute

    @staticmethod
    def _client_key(request: Request) -> str:
        # X-Forwarded-For is set by Railway/Vercel edge; fall back to peer.
        fwd = request.headers.get("X-Forwarded-For")
        ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")
        auth = request.headers.get("Authorization", "")
        # Bucket authenticated callers by token so a shared NAT egress IP does
        # not cause one tenant to rate-limit another.
        suffix = auth[-24:] if auth else "anon"
        return f"{ip}:{suffix}"

    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        path = request.url.path
        if not settings.rate_limit_enabled or path in ("/healthz", "/readyz"):
            return await call_next(request)

        bucket, limit = self._bucket_for(path)
        key = f"{self._client_key(request)}:{bucket}"
        now = time.monotonic()
        window = self._hits[key]
        while window and now - window[0] > 60.0:
            window.popleft()

        if len(window) >= limit:
            retry_after = max(1, int(60.0 - (now - window[0])))
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
