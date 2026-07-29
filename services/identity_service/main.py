"""FastAPI application factory.

Every error leaves through one of the handlers below, so the response shape is
always ``{"error": {"code", "message"}}``. Unhandled exceptions are logged with
a stack trace and answered with a generic 500: an internal message can name a
table, a file path or a library version.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from packages.shared_core.config import get_settings
from packages.shared_core.db.base import dispose_engine
from packages.shared_core.exceptions import AppError
from packages.shared_core.logging import configure_logging
from packages.shared_core.middleware import (
    RateLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from packages.shared_core.observability import init_error_monitoring
from services.identity_service.routers import (
    account,
    admin,
    auth,
    brands,
    campaigns,
    chat,
    health,
    workspaces,
)

logger = logging.getLogger(__name__)

DESCRIPTION = """
Social AI — AI social media content platform.

Authenticate with `POST /api/v1/auth/register` or `/auth/login`, then send the
returned `access_token` as `Authorization: Bearer <token>`.

Every resource lives inside a workspace and is reachable only by its members.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging()
    init_error_monitoring()

    logger.info(
        "starting identity_service",
        extra={
            "environment": settings.environment,
            "llm": "sakana" if settings.llm_enabled else "mock",
            "email_backend": settings.email_backend,
        },
    )
    if not settings.is_production and not settings.llm_enabled:
        logger.warning("no SAKANA_API_KEY configured; chat will use the mock provider")

    yield

    await dispose_engine()
    logger.info("identity_service stopped")


def _error_response(status_code: int, code: str, message: str, **extra: object) -> JSONResponse:
    payload: dict[str, object] = {"code": code, "message": message}
    payload.update(extra)
    return JSONResponse(status_code=status_code, content={"error": payload})


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Social AI API",
        description=DESCRIPTION,
        version=settings.release_version,
        docs_url=settings.docs_url,
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=settings.openapi_url,
        lifespan=lifespan,
        contact={"name": "Social AI Engineering", "email": "engineering@socialai.io"},
        license_info={"name": "MIT"},
    )

    # Order matters: the outermost middleware is added last, so security
    # headers wrap (and therefore apply to) rate-limit rejections too.
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,   # never "*" in production
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "X-Response-Time"],
        max_age=600,
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)

    # ---- error handlers ------------------------------------------------
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error("%s: %s", exc.code, exc.message, exc_info=exc)
        return _error_response(
            exc.status_code,
            exc.code,
            exc.message,
            **({"details": exc.details} if exc.details else {}),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        fields = [
            {
                "field": ".".join(str(p) for p in err["loc"][1:]) or "body",
                "message": err["msg"],
            }
            for err in exc.errors()
        ]
        return _error_response(
            422, "validation_error", "The submitted data is not valid.", details={"fields": fields}
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {401: "unauthenticated", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}
        return _error_response(
            exc.status_code,
            codes.get(exc.status_code, "http_error"),
            str(exc.detail) if exc.detail else "The request could not be completed.",
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        # Never surface the exception text: it can name internals.
        return _error_response(
            500,
            "internal_error",
            "Something went wrong on our side. Please try again.",
            **({"request_id": request_id} if request_id else {}),
        )

    # ---- routes ---------------------------------------------------------
    app.include_router(health.router)

    prefix = settings.api_v1_prefix
    app.include_router(auth.router, prefix=prefix)
    app.include_router(account.router, prefix=prefix)
    app.include_router(workspaces.router, prefix=prefix)
    app.include_router(brands.router, prefix=prefix)
    app.include_router(campaigns.router, prefix=prefix)
    app.include_router(chat.router, prefix=prefix)
    app.include_router(admin.router, prefix=prefix)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "service": "Social AI API",
            "version": settings.release_version,
            "health": "/healthz",
            "docs": settings.docs_url or "disabled in production",
        }

    return app


app = create_app()

__all__ = ["app", "create_app"]
