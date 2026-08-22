# Vitals

Analytical all-in-one health platform. Pulls everything a Garmin watch records, keeps it
forever, computes real sports-science metrics on it, distils that into **one daily Vitals
Score**, and uses an LLM to turn the result into personalised coaching — without nagging.

The rule that keeps it trustworthy: **the LLM never does arithmetic.** Python computes
every number; the model only selects, prioritises, explains and personalises.

## Status

**Phase 0 — deployment skeleton.** The pipeline is deployed and provably wired up
(web → api → Supabase) before any feature is built, because cloud integration problems are
cheap in week one and expensive in week ten.

| Phase | Deliverable | State |
|---|---|---|
| 0 | Scaffold + deploy skeleton, Alembic, config, CI | **in progress** |
| 1 | Supabase Auth + JWT middleware | |
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
    api/          routers, dependencies
    workers/      jobs invoked by the Railway cron service
    cli.py        vitals doctor | sync | (later) auth, backfill, score, coach
    sources/      garmin (pull) · healthkit (push)      — phase 2, 10
    ingest/       raw store, pipeline, source resolver   — phase 3
    analytics/    training load, recovery, sleep, body, longevity, score
    ai/           digest, OpenRouter client, grounding, coach
  alembic/        migrations
frontend/         Next.js App Router (PWA)
docs/             deployment runbook, local development
docker-compose.yml  local dev only
```

## Quick start

```bash
cd backend && uv sync --all-groups
uv run alembic upgrade head
uv run vitals doctor
uv run uvicorn vitals.api.main:app --reload
```

See [docs/local-development.md](docs/local-development.md) and
[docs/deployment.md](docs/deployment.md).

## Notes

Garmin data is read through the unofficial Connect API (`python-garminconnect`): the
official Health API does not support personal use, and commercial aggregators are B2B
only. That path is fragile, so an immutable raw store and a conservative rate governor
are load-bearing architecture rather than nice-to-haves. Single-account personal use.

Not a medical device. Nothing here is diagnosis.
