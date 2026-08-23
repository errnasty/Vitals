# Vitals

Analytical all-in-one health platform. Pulls everything a Garmin watch records, keeps it
forever, computes real sports-science metrics on it, distils that into **one daily Vitals
Score**, and uses an LLM to turn the result into personalised coaching — without nagging.

The rule that keeps it trustworthy: **the LLM never does arithmetic.** Python computes
every number; the model only selects, prioritises, explains and personalises.

## Status

**Phase 1 — authentication.** Every route below the health endpoints requires a Supabase
JWT, verified locally on each request, and the API refuses to start unprotected outside
local development. Verification is stateless, so the whole layer is built and tested
before the Supabase project exists — including key rotation, outages and the
algorithm-confusion attacks. See [docs/auth.md](docs/auth.md).

Both phases below are complete in code and covered by CI; the Railway + Supabase deploy
is pending the Supabase project.

| Phase | Deliverable | State |
|---|---|---|
| 0 | Scaffold + deploy skeleton, Alembic, config, CI | **code complete** |
| 1 | Supabase Auth + JWT middleware | **code complete** |
| 2 | Garmin connector: local SSO login, encrypted DB token store, rate governor, backfill | |
| 3 | Normalizers → canonical silver model, FIT parsing | |
| 4 | Analytics engine (training load, recovery, sleep, body, longevity) | |
| 5 | Vitals Score: pillars, coverage, calibration, contributions waterfall | |
| 6 | Next.js dashboard (PWA) | |
| 7 | AI: digest, OpenRouter, grounding validator, quiet daily brief | |
| 8 | AI coach: response profile, ranked interventions, N-of-1 experiments | |
| 9 | Agentic Q&A, pgvector similar-days, journal fusion | |
| 10 | Apple Health push ingest | |
| 11 | Meal logging by photo | |
| 12 | Multi-user: per-user vault, RLS, rate budgets | |

## Architecture

Five layers, strictly one-directional. The point of the separation is that the fragile
part (scraping an unofficial API) is isolated from the valuable part (your history and the
analysis built on it).

```
SOURCES   GarminSource (pull, cron) · HealthKitSource (push, webhook)
   ↓ verbatim provider JSON
BRONZE    raw_payload (JSONB, immutable, hash-deduped) — never lost, never re-scraped
   ↓ normalizers (source-specific, pure)
SILVER    metric_daily · metric_sample · sleep_session · activity — source-agnostic
   ↓ deterministic Python — all the maths
GOLD      derived_daily · VITALS SCORE (4 pillars, fully decomposed) · response_profile
   ↓ compact digest (never raw timeseries)
AI        quiet daily brief · coach · agentic Q&A · similar-day RAG
   ↓
FastAPI (REST + SSE, Supabase-JWT guarded) → Next.js PWA
```

Deployed on **Railway** (`api`, `web`, `sync` cron); data in **Supabase**
(Postgres + pgvector, Auth, Storage).

## Repository layout

```
backend/          FastAPI + SQLAlchemy 2.0 + Alembic, uv-managed
  src/vitals/
    config.py     one settings object for every service
    db/           engine, session, models
    auth/         JWT verification, JWKS cache, allowlist, user provisioning
    api/          routers, dependencies
    workers/      jobs invoked by the Railway cron service
    cli.py        vitals doctor | sync | auth | (later) backfill, score, coach
    sources/      garmin (pull) · healthkit (push)      — phase 2, 10
    ingest/       raw store, pipeline, source resolver   — phase 3
    analytics/    training load, recovery, sleep, body, longevity, score
    ai/           digest, OpenRouter client, grounding, coach
  alembic/        migrations
frontend/         Next.js App Router (PWA)
docs/             deployment runbook, local development, auth
docker-compose.yml  local dev only
```

## Quick start

```bash
cd backend && uv sync --all-groups
uv run alembic upgrade head
uv run vitals doctor
uv run uvicorn vitals.api.main:app --reload

# no Supabase project needed to work on the API:
export SUPABASE_JWT_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
export VITALS_ALLOWED_EMAILS=you@example.com
curl -H "Authorization: Bearer $(uv run vitals auth token --email you@example.com)" \
     localhost:8000/auth/me
```

See [docs/local-development.md](docs/local-development.md),
[docs/auth.md](docs/auth.md) and [docs/deployment.md](docs/deployment.md).

## Notes

Health data sits behind two independent gates: Supabase sign-ups are disabled, and
`VITALS_ALLOWED_EMAILS` is enforced on every request. The API will not start outside
local development unless both a verification method and an allowlist are configured.

Garmin data is read through the unofficial Connect API (`python-garminconnect`): the
official Health API does not support personal use, and commercial aggregators are B2B
only. That path is fragile, so an immutable raw store and a conservative rate governor
are load-bearing architecture rather than nice-to-haves. Single-account personal use.

Not a medical device. Nothing here is diagnosis.
