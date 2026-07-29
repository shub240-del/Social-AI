"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from packages.shared_core.ai.nvidia_client import get_ai_client
from packages.shared_core.config import get_settings
from packages.shared_core.db.base import dispose_engine
from packages.shared_core.exceptions import AppError
from packages.shared_core.logging import configure_logging
from packages.shared_core.middleware.core import (
    RateLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from packages.shared_core.observability import init_error_monitoring
from services.identity_service.routers import (
    account,
    auth,
    brands,
    campaigns,
    chat,
    health,
    workspaces,
)

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_error_monitoring()
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.is_production)
    logger.info(
        "starting %s (env=%s, ai=%s)",
        settings.service_name,
        settings.environment,
        "nvidia" if settings.llm_enabled else "mock",
    )
    await get_ai_client().startup()
    try:
        yield
    finally:
        await get_ai_client().shutdown()
        await dispose_engine()
        logger.info("shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Social AI API",
        version="1.0.0",
        description="AI social media content platform.",
        lifespan=lifespan,
        # Interactive docs are disabled in production; the schema is still
        # generated for client codegen.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        # The schema enumerates every endpoint and payload shape. Useful in
        # development, needless attack-surface disclosure in production.
        openapi_url=None if settings.is_production else f"{API_PREFIX}/openapi.json",
    )

    # Order matters: the outermost middleware is added last.
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "X-Response-Time-ms"],
        max_age=600,
    )

    # ---- error handlers ------------------------------------------------
    # Every failure returns the same envelope: {"error": {"code", "message"}}.

    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error("%s: %s", exc.code, exc.message)
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "The request payload is invalid.",
                    "details": {"fields": exc.errors()},
                }
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": "http_error", "message": str(exc.detail)}},
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Never leak internals to the client; the traceback goes to the log.
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected error occurred.",
                }
            },
        )

    # ---- routes --------------------------------------------------------
    app.include_router(health.router)
    for module in (auth, account, workspaces, brands, campaigns, chat):
        app.include_router(module.router, prefix=API_PREFIX)

    @app.get("/", include_in_schema=False)
    async def root() -> dict:
        return {
            "service": settings.service_name,
            "version": app.version,
            "docs": app.docs_url,
            "health": "/healthz",
        }

    return app


app = create_app()
