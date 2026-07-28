# =============================================================================
# Backend image — Social AI API (services/identity_service)
# No Dockerfile existed in the repository; deployment.md's `docker compose build`
# and `docker compose run --rm backend ...` could not have worked.
# =============================================================================

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_VERSION=1.8.3 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1

WORKDIR /app

# --- dependencies -----------------------------------------------------------
# Copied separately so the dependency layer caches independently of source.
FROM base AS deps

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential curl \
 && rm -rf /var/lib/apt/lists/*

RUN pip install "poetry==${POETRY_VERSION}"

COPY pyproject.toml poetry.lock* README.md ./

# --no-root: the project's own packages are added via COPY below and resolved
# from /app on sys.path. Installing the root package here would fail because
# packages/ and services/ are not present in this layer.
# --only main: dev dependencies (pytest, ruff, mypy) are not shipped to prod.
# --extras monitoring: sentry-sdk is an optional extra, but observability.py
# only activates Sentry when SENTRY_DSN is set, so shipping it costs nothing
# and avoids a "sentry-sdk is not installed" warning in production.
RUN poetry install --only main --no-root --extras monitoring

# --- runtime ----------------------------------------------------------------
FROM base AS runtime

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 appuser

COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

COPY --chown=appuser:appuser pyproject.toml alembic.ini ./
COPY --chown=appuser:appuser packages ./packages
COPY --chown=appuser:appuser services ./services
COPY --chown=appuser:appuser migrations ./migrations

# Imports resolve from /app, matching `prepend_sys_path = .` in alembic.ini and
# the extraPaths in pyrightconfig.json.
ENV PYTHONPATH=/app

USER appuser

EXPOSE 8000

# Railway/Vercel style platforms inject PORT. Default for local `docker run`.
ENV PORT=8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/healthz" || exit 1

# Multiple workers: the previous single uvicorn process could be stalled by one
# synchronous 70B-model call. Overridden by railway.toml [deploy].startCommand.
CMD ["sh", "-c", "gunicorn services.identity_service.main:app \
     -k services.identity_service.worker.SecureUvicornWorker \
     -w ${WEB_CONCURRENCY:-4} \
     -b 0.0.0.0:${PORT} \
     --timeout 120 --graceful-timeout 30 --access-logfile -"]
