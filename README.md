# Social AI

AI social-media content platform. FastAPI API + Next.js web app, multi-tenant by
workspace, with brand-grounded chat generation.

> **Provenance.** This tree was generated to match the architecture described in
> `socialai-architecture-report.html`. The original application source was never
> supplied — only root config files — so this is a working implementation, not a
> patch against an existing repo. Diff it against your tree before merging.

## Layout

```
packages/shared_core/     config, db, security, ai, middleware, logging
services/identity_service/ FastAPI app: auth, workspaces, brands, campaigns, chat
migrations/               Alembic (env reads MIGRATION_DATABASE_URL, then DATABASE_URL)
apps/web/                 Next.js 14 App Router frontend
tests/                    backend unit + integration + live-server API E2E
apps/web/tests/           UI journey against a live backend
```

## Run it locally

Backend:

```bash
python -m venv .venv && source .venv/bin/activate
pip install '.[dev]'
cp .env.example .env
export PYTHONPATH=.
alembic upgrade head
uvicorn services.identity_service.main:app --reload --port 8000
```

With no `NVIDIA_API_KEY` set, the AI layer serves deterministic mock
completions so the whole product is usable offline. `/readyz` reports this as
`ai: degraded/mock`.

Frontend:

```bash
cd apps/web
npm ci
cp .env.local.example .env.local   # points at http://127.0.0.1:8000
npm run dev
```

## Tests

| Suite | Command | Count |
|---|---|---|
| Backend unit + integration | `pytest tests -q` | 98 |
| API end-to-end (live server) | `python tests/e2e_flow.py` | 49 |
| Security probes (live server) | `python tests/security_probe.py` | 64 |
| Performance budget (live server) | `python tests/perf_probe.py` | 9 endpoints |
| UI journey + account flows (live server) | `cd apps/web && npx vitest run` | 26 |
| Lint | `ruff check .` / `npx next lint` | — |
| Types | `cd apps/web && npx tsc --noEmit` | — |
| Schema drift | `alembic check` | — |
| Post-deploy (needs a deployment) | `python tests/post_deploy_verify.py --api … --web …` | 24 |

The live-server suites need the API running on `127.0.0.1:8000` with the
rate limits relaxed. The account-flow UI tests additionally read the
verification and reset links out of the server log, so send its output to a
file and point `SERVER_LOG` at it:

```bash
RATE_LIMIT_AUTH_PER_MINUTE=500 RATE_LIMIT_CHAT_PER_MINUTE=500 \
RATE_LIMIT_DEFAULT_PER_MINUTE=5000 ALLOW_MOCK_LLM=true \
EMAIL_BACKEND=console FRONTEND_BASE_URL=http://127.0.0.1:3000 \
uvicorn services.identity_service.main:app --port 8000 > /tmp/server.log 2>&1

# then, in apps/web
SERVER_LOG=/tmp/server.log npx vitest run
```

The UI journey covers the full path: homepage → register → dashboard →
workspace → create brand → create campaign → chat → prompt → AI response →
history → reload/persistence → logout → login again.

`tests/account.test.tsx` covers the parts that need an inbox: requesting a
verification link, confirming it, expiry and reuse of both link types, and a
password reset that leaves the old password dead and every session revoked.

## Security model

- **Tokens.** RS256 access (15 min) + rotating refresh (14 d). Refresh tokens are
  stored hashed; reuse of a rotated token revokes the family. Logout revokes.
- **Tenant isolation.** Every workspace-scoped query is filtered by membership.
  Cross-tenant reads return **404, not 403**, so existence is not disclosed.
- **Privilege escalation.** A member may only grant roles strictly below their
  own rank; granting an equal rank is refused.
- **Rate limits.** Separate buckets for credential endpoints, chat, and
  everything else, keyed per client. In-process only — move the counters to
  Redis before running more than a couple of replicas.
- **Config.** Production start-up fails on SQLite, missing JWT keys, wildcard
  CORS, a missing `NVIDIA_API_KEY`, or `ALLOW_MOCK_LLM=true`.
- **Prompt grounding.** Brand and campaign lookups are workspace-scoped, so an
  id from another tenant is rejected rather than leaking that tenant's
  positioning into the prompt. User text is wrapped in a `<user_request>`
  boundary.

## Deploy

**Database — Supabase.** Two URLs, and the distinction matters:

- `DATABASE_URL` → port **6543** (transaction pooler) for runtime. The engine
  sets `statement_cache_size=0`, which asyncpg requires against the pooler.
- `MIGRATION_DATABASE_URL` → port **5432** (direct) for Alembic. DDL through the
  pooler is unreliable.

**Backend — Railway.** `railway.toml` builds the `Dockerfile` and runs
`alembic upgrade head` before starting gunicorn, so a bad migration fails the
deploy rather than half-upgrading the fleet. Health check is `/readyz`. Set
every variable from `.env.example`; at minimum `ENVIRONMENT=production`,
`DATABASE_URL`, `MIGRATION_DATABASE_URL`, `JWT_PRIVATE_KEY`, `JWT_PUBLIC_KEY`,
`NVIDIA_API_KEY`, `ALLOW_MOCK_LLM=false`, and `ALLOWED_ORIGINS` set to your
Vercel origin.

Generate the keypair:

```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out private.pem
openssl rsa -in private.pem -pubout -out public.pem
```

**Frontend — Vercel.** Root directory `apps/web`. Set `NEXT_PUBLIC_API_URL` to
the Railway URL. This value is inlined at build time, so changing it requires a
redeploy, not just an env edit.

## Verifying a deployment

`tests/post_deploy_verify.py` is the post-deploy gate. It checks the things
that can only be wrong once the app is public: TLS and the http redirect, the
production config guards having actually taken effect, security headers
surviving the platform proxy, CORS matching the real frontend origin, the
OpenAPI schema being closed, and every replica accepting a token minted by
another one.

```bash
python tests/post_deploy_verify.py \
  --api https://api.example.com \
  --web https://app.example.com \
  --write        # optional: real signup + chat, leaves an account behind
```

`--write` also asserts the reply did not come from the mock LLM provider,
which is the cheapest way to catch `ALLOW_MOCK_LLM` reaching production.
A non-zero exit means the deployment is not verified.

## Known limits

- Rate limiting is per process, so the effective limit is `limit × replicas`.
- `REQUIRE_EMAIL_VERIFICATION` ships as `false`. Turning it on before SMTP is
  configured and before existing users have verified will lock them all out.
- There is no separate "project" entity: a **campaign** is the unit of work
  inside a workspace, and it is what scopes a chat. If the product needs the
  word "project", that is a rename, not a new table.
- Error monitoring is an optional extra (`pip install -e '.[monitoring]'`) and
  is inert unless `SENTRY_DSN` is set.
- The frontend keeps tokens in `localStorage`, which is XSS-readable. Moving to
  httpOnly cookies requires a same-site deployment or a CORS credential setup.
- `alembic upgrade head` in the start command serialises deploys; for zero
  downtime, split it into a dedicated release job.
