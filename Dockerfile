# syntax=docker/dockerfile:1
# Backend image. Deployed to Railway; also runs locally with `docker run`.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

# Build deps for asyncpg/cryptography wheels are not needed on slim + manylinux,
# but curl is kept for the container healthcheck.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# The project must be present before `pip install .`: package discovery runs at
# install time, so installing from pyproject.toml alone would produce a
# dependencies-only environment with none of the application modules.
COPY pyproject.toml ./
COPY packages ./packages
COPY services ./services
RUN pip install --upgrade pip && pip install .

COPY migrations ./migrations
COPY alembic.ini ./

# Never run as root.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:${PORT:-8000}/healthz || exit 1

# Railway injects $PORT. Uvicorn workers under gunicorn give us process
# supervision plus an async worker class.
CMD ["sh", "-c", "gunicorn services.identity_service.main:app \
     --worker-class services.identity_service.worker.SocialAIWorker \
     --workers ${WEB_CONCURRENCY:-2} \
     --bind 0.0.0.0:${PORT:-8000} \
     --timeout 120 \
     --graceful-timeout 30 \
     --access-logfile - \
     --error-logfile -"]
