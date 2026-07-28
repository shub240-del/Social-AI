# Social AI

An AI social-media content platform: workspaces, brands, campaigns, and an
LLM-backed chat assistant, behind self-hosted RS256 authentication.

FastAPI + SQLAlchemy (async) on the backend, Next.js 14 App Router on the
frontend, PostgreSQL for storage, Sakana AI (Fugu) for completions.

---

## What is actually here

Earlier revisions of this README described `ai_core`, `ai_agents`,
`api_gateway`, `workflow_engine`, `publishing_service`, `analytics_service` and
`billing_service`. None of those existed. The list below is the repository as it
stands; every directory named is present and covered by tests.

```
apps/
  web/                     Next.js 14 frontend (App Router, Tailwind)
packages/
  shared_core/
    ai/                    provider abstraction: base, sakana, mock, factory
    db/                    async engine, session, ORM models
    email/                 console / memory / SMTP senders
    middleware/            request context, security headers, rate limiting
    security/              password hashing, RBAC permission matrix
    config.py              settings + fail-fast production validation
    logging.py             structured logging with secret redaction
    observability.py       optional Sentry wiring
services/
  identity_service/
    auth/                  token issuing, request dependencies
    routers/               auth, account, health, workspaces, brands,
                           campaigns, chat, admin
    services/              user provisioning
    schemas.py             request/response models
    main.py                app factory, error handlers, middleware order
    worker.py              gunicorn worker that suppresses the Server header
migrations/                Alembic revisions
tests/                     unit, integration, live journey, deploy verification
```

### Data model

Nine tables: `users`, `refresh_tokens`, `verification_tokens`, `workspaces`,
`memberships`, `brands`, `campaigns`, `conversations`, `messages`.

Primary keys are 36-character string UUIDs so the same schema runs on both
SQLite (local/CI) and PostgreSQL (deployed) with no branching.

### AI provider

The application depends only on `BaseAIProvider`. `routers/chat.py` calls
`get_llm_client()` and never names a vendor, so replacing the provider is a
change to `packages/shared_core/ai/` alone:

```
ai/base.py            the contract: complete(), stream(), message validation
ai/types.py           ChatMessage / Completion, provider-neutral
ai/errors.py          provider HTTP status -> application exception
ai/retry.py           capped exponential backoff with jitter
ai/sakana_client.py   Sakana AI (Fugu), OpenAI-compatible chat completions
ai/mock_client.py     deterministic provider for dev, tests and CI
ai/factory.py         the single place that chooses one
```

Sakana's Fugu is a multi-agent system that orchestrates several frontier models
per request, so it is much slower than a single-model API; the default timeout
is 120s. A key with no active subscription authenticates successfully but
answers every completion with `429 usage_limit_reached`. That is a billing
state rather than a burst limit, so it is raised immediately as a configuration
error instead of being retried.

### Authentication

Self-hosted RS256 JWTs. Access tokens are short lived; refresh tokens rotate
within a `family_id`, and presenting an already-rotated token revokes the entire
family as replay defence.

Auth0 settings remain as an optional legacy path for verifying externally minted
tokens. They are unset by default.

---

## Quick start

Requires Python 3.12+, Node 20+, and pnpm 9.

### Backend

```bash
cp .env.example .env
poetry install --extras monitoring

# Defaults in .env.example point at Postgres. For a zero-dependency start,
# override with sqlite:
export DATABASE_URL="sqlite+aiosqlite:///./socialai_dev.db"
export MIGRATION_DATABASE_URL="sqlite:///./socialai_dev.db"

poetry run alembic upgrade head
poetry run uvicorn services.identity_service.main:app --reload --port 8000
```

- API: <http://127.0.0.1:8000>
- OpenAPI docs: <http://127.0.0.1:8000/docs> (disabled when `ENVIRONMENT=production`)
- Liveness: `/healthz` · Readiness (checks the database): `/readyz`

With no `SAKANA_API_KEY` set and `ALLOW_MOCK_LLM=true`, chat responds from a mock
provider whose output always contains the word "mock", so a misconfigured deploy
is detectable rather than plausible.

With `EMAIL_BACKEND=console`, verification and password-reset emails print to
stdout; copy the link from the server log.

### Frontend

```bash
pnpm install
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 pnpm run dev
```

Opens on <http://127.0.0.1:3000>. Keep that origin in `ALLOWED_ORIGINS`.

### Everything at once

```bash
docker compose up --build     # Postgres + API, migrations run on start
```

---

## Testing

```bash
poetry run pytest -q                     # unit + integration
poetry run ruff check .                  # lint + import order + formatting rules
poetry run mypy packages services tests  # strict; enforced in CI
pnpm run lint && pnpm run typecheck && pnpm run build

# Against a running server:
poetry run python tests/e2e_journey.py --api http://127.0.0.1:8000 --log api.log
poetry run python tests/post_deploy_verify.py --api https://api.example.com
```

`e2e_journey.py` walks a real user through registration, email verification,
login, workspace/brand/campaign creation, chat, token refresh, logout and
re-login. It reads verification links out of the server log, so it needs
`--log` pointed at the console-email output.

`post_deploy_verify.py` is the release gate: it checks health, TLS, security
headers, CORS behaviour, error-envelope shape, that docs are closed in
production, and that the deployment is not silently running the mock LLM.

Migration drift is enforced in CI with `alembic check`, which fails when the ORM
models and the migration history disagree.

`ruff` is the only Python formatter and linter; `black` was removed because
`ruff-format` already covers it and running both meant two formatters competing
for the same files. `mypy` is the only type checker, and CI runs it — it was
configured `strict` from the start but never invoked, which had let 27 type
errors accumulate unnoticed.

---

## Deployment

| Component | Target |
| --- | --- |
| Frontend | Vercel (`apps/web`) |
| Backend | Railway (`Dockerfile`, `railway.toml`) |
| Database | Supabase or Neon PostgreSQL |

See [DEPLOYMENT.md](DEPLOYMENT.md) for the full procedure.

Two details that cause most first-deploy failures:

1. Alembic cannot use the `asyncpg` driver. `MIGRATION_DATABASE_URL` must be a
   `postgresql+psycopg2://` URL against the direct `:5432` endpoint, while
   `DATABASE_URL` uses `postgresql+asyncpg://` against the `:6543` pooler.
2. On the `:6543` transaction pooler, append
   `?prepared_statement_cache_size=0` or asyncpg will intermittently fail with
   "prepared statement already exists".

`ENVIRONMENT=production` refuses to boot on a SQLite URL, missing JWT keys, a
mock-LLM flag, a missing Sakana key, wildcard or plaintext CORS origins, a
console email backend, or a non-HTTPS frontend URL.

---

## Known limitations

- Rate limiting is an in-process fixed window over three per-client buckets
  (credential, chat, default), so the effective limit is the configured value
  multiplied by the replica count. A shared store is required before scaling
  horizontally.
- Next.js carries an open advisory for the Image Optimizer and RSC
  deserialization with no fixed stable release at time of writing. This app
  configures no `remotePatterns`, so the image path is not reachable.

## Security notice

A live NVIDIA API key was committed to `.env.production` in this public
repository's history. NVIDIA is no longer used, but removing the file from the
working tree did not remove the key: **it remains in git history** and must be
revoked at build.nvidia.com and purged:

```bash
git filter-repo --path .env.production --invert-paths
git push --force
```

## License

See [LICENSE](LICENSE).
