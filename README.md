# Social AI

An AI social-media content platform: workspaces, brands, campaigns, and an
LLM-backed chat assistant, behind self-hosted RS256 authentication.

FastAPI + SQLAlchemy (async) on the backend, Next.js 14 App Router on the
frontend, PostgreSQL for storage, NVIDIA NIM for completions.

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
    ai/                    NVIDIA NIM client, retry/backoff, mock provider
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

With no `NVIDIA_API_KEY` set and `ALLOW_MOCK_LLM=true`, chat responds from a mock
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
poetry run ruff check .
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
mock-LLM flag, a missing NVIDIA key, wildcard or plaintext CORS origins, a
console email backend, or a non-HTTPS frontend URL.

---

## Known limitations

- Rate limiting is an in-process fixed window, so the effective limit is the
  configured value multiplied by the replica count. A shared store is required
  before scaling horizontally.
- Next.js carries an open advisory for the Image Optimizer and RSC
  deserialization with no fixed stable release at time of writing. This app
  configures no `remotePatterns`, so the image path is not reachable.

## Security notice

A live NVIDIA API key was committed to `.env.production` in this public
repository's history. The file has been removed from the working tree, but
**the key remains in git history**. It must be revoked at build.nvidia.com and
purged:

```bash
git filter-repo --path .env.production --invert-paths
git push --force
```

## License

See [LICENSE](LICENSE).
