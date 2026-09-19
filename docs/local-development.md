# Local development

## Running the whole thing

Five steps, and the third is the one people miss.

**1. Configuration, once.** Everything reads a single `.env` at the repository root —
the CLI, the API and the sync job all find it, so there is nothing to re-export per
shell.

```bash
cp .env.example .env
```

Fill in three values:

```bash
DATABASE_URL=postgresql+asyncpg://vitals:vitals@localhost:5432/vitals
VITALS_ALLOWED_EMAILS=you@example.com
# python -c "import secrets; print(secrets.token_urlsafe(48))"
VITALS_AUTH_JWT_SECRET=...
# python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
VITALS_ENCRYPTION_KEY=...
```

To work against the deployed database instead of a local one, put Railway's
`DATABASE_PUBLIC_URL` in `DATABASE_URL` and skip step 2. One backfill then lands where
the cron will keep it fresh, rather than in a local database you would have to redo.

**2. Database and API.**

```bash
docker compose up -d db
cd backend && uv sync --all-groups
uv run alembic upgrade head
uv run vitals doctor                 # everything should be PASS or a phase-7 WARN
uv run uvicorn vitals.api.main:app --reload
```

**3. Sign in once — this is the step that is easy to miss.**

Nothing else works until an `app_user` row exists, because identity comes from an
authenticated request and never from a sync command. Skipping it is why a freshly
deployed cron fails with `no accounts exist yet`.

```bash
TOKEN=$(uv run vitals auth token --email you@example.com --days 90)
curl -H "Authorization: Bearer $TOKEN" localhost:8000/auth/me
```

Keep that token: the frontend uses it in step 5.

**4. Connect Garmin and pull the history.** Password and MFA are prompted; this is the
only command that touches Garmin's SSO, and it runs from your machine rather than the
cloud. See [garmin.md](garmin.md).

```bash
uv run vitals garmin login --email you@garmin-account
uv run vitals garmin test
uv run vitals backfill --start 2019-01-01 --dry-run   # ~320 requests for 7 years
uv run vitals backfill --start 2019-01-01             # ~15 minutes, governed
uv run vitals normalize && uv run vitals recompute && uv run vitals score
uv run vitals brief                                   # the day's note
```

`vitals brief` needs no API key. Without `OPENROUTER_API_KEY` it composes the note in
Python from the same ranked signals a model would have been given — plainer, and never
wrong. Add the key when you want it written as prose; `vitals brief --digest` shows
exactly what the model would be handed, and writes nothing. See [ai.md](ai.md).

**5. The dashboard.**

```bash
cd frontend
npm install
cat > .env.local <<EOF
API_URL=http://localhost:8000
VITALS_API_TOKEN=$TOKEN
EOF
npm run dev                          # http://localhost:3000
```

Every fetch happens on the server, so the token stays in the web process and the
browser never holds a credential. Before step 4 the screens say so in words — *"No data
yet — connect Garmin and run a sync"* — rather than rendering a convincing row of
dashes.

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
npm run dev                          # needs API_URL and VITALS_API_TOKEN in .env.local
npm run build && npx tsc --noEmit    # what CI runs
```

`/design` renders the style guide from the same exports the app imports, which is the
fastest way to see a token change land on every primitive at once.

## Everything at once

```bash
docker compose up --build            # db + migrate + api + web
docker compose run --rm sync         # the cron job, one-shot, as it runs on Railway
```

The `web` container reads `VITALS_API_TOKEN` from the root `.env`, so put the token
from step 3 there before bringing the stack up.

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
