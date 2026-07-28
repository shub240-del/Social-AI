# Deployment

| Component | Target | Config |
| --- | --- | --- |
| Database | Supabase or Neon PostgreSQL 16 | — |
| Backend | Railway (Docker) | `Dockerfile`, `railway.toml` |
| Frontend | Vercel | `apps/web/vercel.json` |

Earlier revisions of this guide specified Aurora Serverless, a Redis Enterprise
cluster, a ClickHouse cluster and Argo Rollouts, and ran
`docker compose run --rm backend alembic upgrade head` against a `backend`
service that was never defined. None of that infrastructure is used by this
codebase. What follows is the procedure that matches the repository.

---

## 0. Before anything else: rotate the leaked key

A live NVIDIA API key was committed to `.env.production` in this public
repository. It is out of the working tree but still in git history.

1. Revoke it at <https://build.nvidia.com> and issue a replacement.
2. Purge it from history:

```bash
pip install git-filter-repo
git filter-repo --path .env.production --invert-paths
git push --force --all
```

Never put the replacement in a file. It belongs in Railway variables only.

---

## 1. Database

Create a PostgreSQL 16 instance. From Supabase you need **two** connection
strings, because the application and the migration runner use different drivers:

| Purpose | Port | Driver | Variable |
| --- | --- | --- | --- |
| Application runtime | 6543 (transaction pooler) | `asyncpg` | `DATABASE_URL` |
| Alembic migrations | 5432 (direct/session) | `psycopg2` | `MIGRATION_DATABASE_URL` |

```
DATABASE_URL=postgresql+asyncpg://postgres.REF:PASSWORD@aws-0-REGION.pooler.supabase.com:6543/postgres?prepared_statement_cache_size=0
MIGRATION_DATABASE_URL=postgresql+psycopg2://postgres.REF:PASSWORD@aws-0-REGION.pooler.supabase.com:5432/postgres
```

Both details matter:

- Alembic runs synchronously and will fail immediately on an `+asyncpg` URL.
- `prepared_statement_cache_size=0` is required on the `:6543` pooler. Without
  it asyncpg fails intermittently under load with
  `prepared statement "_asyncpg_..." already exists`.
- DDL must not go through the transaction pooler, hence the `:5432` endpoint
  for migrations.

---

## 2. Generate the JWT keypair

Authentication is self hosted and signs RS256. Production will not boot without
both halves.

```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out jwt.pem
openssl rsa -in jwt.pem -pubout -out jwt.pub
```

Paste the PEM contents into `JWT_PRIVATE_KEY` and `JWT_PUBLIC_KEY`. Rotating
these invalidates every issued access and refresh token, logging out all users.
Do not commit `jwt.pem`; `*.pem` is gitignored.

---

## 3. Backend on Railway

Create a service from this repository. `railway.toml` supplies the rest:

- builder: `DOCKERFILE`
- `preDeployCommand`: `python -m alembic upgrade head` — runs once per deploy,
  before the new version takes traffic, rather than on every container start
  where replicas would race each other
- `startCommand`: gunicorn with `SecureUvicornWorker`, which suppresses the
  `Server: uvicorn` banner and trusts `X-Forwarded-*` from the platform proxy
- `healthcheckPath`: `/healthz`

Set every variable listed in `.env.production.example` in the Railway UI. The
minimum that will actually boot:

```
ENVIRONMENT=production
DATABASE_URL=...
MIGRATION_DATABASE_URL=...
JWT_PRIVATE_KEY=...
JWT_PUBLIC_KEY=...
NVIDIA_API_KEY=...            # the rotated key
ALLOW_MOCK_LLM=false
ALLOWED_ORIGINS=https://<your-vercel-domain>
FRONTEND_BASE_URL=https://<your-vercel-domain>
EMAIL_BACKEND=smtp
SMTP_HOST=...
SMTP_USERNAME=...
SMTP_PASSWORD=...
```

`packages/shared_core/config.py` validates these at import time. With
`ENVIRONMENT=production` the process exits rather than starting when it finds a
SQLite URL, absent JWT keys, `ALLOW_MOCK_LLM=true`, a missing or placeholder
NVIDIA key, empty/wildcard/`http://` CORS origins, a console or memory email
backend, `smtp` without a host, a non-HTTPS `FRONTEND_BASE_URL`, or a half
configured Auth0. A failed boot here is the guard working.

### Capacity

`WEB_CONCURRENCY` workers × (`POSTGRES_POOL_SIZE` + `POSTGRES_MAX_OVERFLOW`)
is the per-replica connection ceiling. The defaults, 4 × (5 + 5), reach 40
connections per replica. Check that against your database plan before raising
either value.

---

## 4. Frontend on Vercel

Root directory `apps/web`. `vercel.json` pins the install and build commands and
adds HSTS, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy` and
`Permissions-Policy`.

One variable:

```
NEXT_PUBLIC_API_URL=https://<your-railway-domain>
```

This is compiled into the client bundle, so a change requires a redeploy. The
browser calls the API cross-origin, so that Vercel domain must appear verbatim
in the backend's `ALLOWED_ORIGINS`.

---

## 5. Verify the deployment

```bash
python tests/post_deploy_verify.py \
  --api https://<railway-domain> \
  --web https://<vercel-domain>
```

This gate checks liveness and readiness, TLS, the security header set, that
untrusted origins are not reflected by CORS, the `{"error": {...}}` envelope
shape, that unauthenticated access to protected routes is refused, that the
OpenAPI schema and docs are closed in production, and that the deployment is not
quietly serving mock LLM output.

Exit code 0 means every check passed. Warnings are printed but do not fail.

For a full functional pass against a non-production environment:

```bash
python tests/e2e_journey.py --api https://<host> --log <server log>
```

---

## 6. Rollback

Railway keeps previous deployments; redeploy the prior build from the
deployments list.

Migrations are not rolled back automatically. The initial revision implements
`downgrade`, so if a release must be reverted across a schema change:

```bash
MIGRATION_DATABASE_URL=... python -m alembic downgrade -1
```

Take a database snapshot first. Any migration that drops a column is not
recoverable by `downgrade` alone.

---

## 7. Local production-like run

```bash
docker compose up --build
```

Starts Postgres and the API image, running migrations first. This is the closest
local approximation to the Railway deployment; it runs with development settings
so the production guard does not apply.
