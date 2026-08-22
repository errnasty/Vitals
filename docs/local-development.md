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
it prints redacted config, the Postgres version, whether pgvector is enabled, and
whether the schema is at Alembic head.

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

## A note on Postgres versions

Local dev uses `pgvector/pgvector:pg17`; Supabase runs its own build with `vector`
available as an extension. The migration enables the extension either way, so the two
stay in step.
