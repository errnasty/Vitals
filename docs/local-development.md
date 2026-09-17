# Local development

## Backend

```bash
cd backend
uv sync --all-groups
cp ../.env.example ../.env          # then edit
uv run alembic upgrade head
uv run vitals doctor                # config + DB + pgvector + migration state
uv run uvicorn vitals.api.main:app --reload
```

Checks, all of which CI also runs:

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest -q
```

`vitals doctor` is the fastest way to tell a config problem from a database problem —
it prints redacted config, how tokens are verified, the Postgres version, whether
pgvector is available, and whether the schema is at Alembic head.

## Auth, with no identity provider

There is nothing to sign up for: this deployment signs its own tokens, and
`vitals auth token` mints one that the production code path verifies unchanged.

```bash
export VITALS_AUTH_JWT_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
export VITALS_ALLOWED_EMAILS=you@example.com

TOKEN=$(uv run vitals auth token --email you@example.com)
uv run vitals auth verify "$TOKEN"
curl -H "Authorization: Bearer $TOKEN" localhost:8000/auth/me
```

The same commands work against the deployed API with the same secret. Minting is refused
only when an external OIDC provider is configured — there the provider is the one
entitled to sign. For UI work, `VITALS_AUTH_DISABLED=true` turns auth off entirely —
local-only. See [auth.md](auth.md).

## Garmin

```bash
vitals sync --dry-run            # the request plan, without touching Garmin
vitals garmin status             # connection, tokens, how much history has landed
```

`--dry-run` needs no credentials, which makes the fetch plan and its request cost
reviewable before anything is connected. Connecting for real is a local, once-a-year
step — see [garmin.md](garmin.md).

## Tests and Postgres

The connector's storage tests need a real Postgres (JSONB, `ON CONFLICT`,
`NULLS NOT DISTINCT`), and skip cleanly when there is none:

```bash
docker compose up -d db
uv run pytest -q                 # creates and drops its own <database>_test
```

They never touch the database `DATABASE_URL` points at — the fixture derives a `_test`
database and creates it if needed, so pointing `DATABASE_URL` at a real project is not
one `pytest` away from losing it.

## Frontend

```bash
cd frontend
npm install
npm run dev                          # http://localhost:3000, expects API_URL
```

## Everything at once

```bash
docker compose up --build            # db + migrate + api + web
docker compose run --rm sync         # the cron job, one-shot, as it runs on Railway
```

The compose file uses the same Dockerfiles and start commands as Railway, so a local
pass means something about the deployed shape.

## A note on Postgres images

Local dev and CI use `pgvector/pgvector:pg17`. Railway's official Postgres image is
version 18 and ships **no pgvector** — so the initial migration enables the extension
only where it is actually available, and `/healthz` reports `present: false` rather than
failing. Nothing before phase 9 reads a vector.

The practical consequence: a migration that assumes pgvector will pass locally and fail
on Railway. When phase 9 arrives, either move Railway to a pgvector-capable image (and
take over backups, since managed PITR needs the official one) or keep vectors out of
Postgres. `VITALS_REQUIRE_PGVECTOR=true` turns the absence back into a hard failure once
something depends on it.
