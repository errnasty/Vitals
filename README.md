# Vitals

Analytical all-in-one health platform. Pulls everything a Garmin watch records, keeps it
forever, computes real sports-science metrics on it, distils that into **one daily Vitals
Score**, and uses an LLM to turn the result into personalised coaching — without nagging.

The rule that keeps it trustworthy: **the LLM never does arithmetic.** Python computes
every number; the model only selects, prioritises, explains and personalises.

## Status

**Phase 7 — the daily brief.** Two or three sentences a day, written from a compact
digest of numbers Python already computed, with **every number in them checked against
that digest before they are stored**. A conversion the model performed itself — `7h 16m`
written as "7.3 hours" — is rejected, retried once with the fault named, and failing
that the brief is composed in Python instead. It works with no API key at all.
See [docs/ai.md](docs/ai.md).

Phases 0-7 are complete in code and covered by CI, and deployed on Railway. Garmin can
be connected either from a terminal (`vitals garmin login`) or from the app itself at
`/connect`, for when the only device to hand is a phone — see
[docs/garmin.md](docs/garmin.md) for why the terminal is still the better one. Still
pending: a first login against a live Garmin account, and the FIT parsing half of
phase 3.

| Phase | Deliverable | State |
|---|---|---|
| 0 | Scaffold + deploy skeleton, Alembic, config, CI | **code complete** |
| 1 | JWT auth: self-issued tokens, pluggable OIDC provider | **code complete** |
| 2 | Garmin connector: local SSO login, encrypted DB token store, rate governor, backfill | **code complete** |
| 3 | Normalizers → canonical silver model | **code complete** |
| 3b | FIT download, storage and parsing | **code complete** |
| 4 | Analytics engine (training load, recovery, sleep, body, longevity) | **code complete** |
| 5 | Vitals Score: pillars, coverage, calibration, contributions waterfall | **code complete** |
| 6 | Next.js dashboard: Today, Breakdown, Trends | **code complete** |
| 7 | AI: digest, OpenRouter, grounding validator, quiet daily brief | **code complete** |
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
          one canonical vocabulary, fixed units, rebuildable from bronze
   ↓ deterministic Python — all the maths
GOLD      derived_daily · VITALS SCORE (4 pillars, fully decomposed) · response_profile
          every row carries the coverage it was computed from
   ↓ compact digest (never raw timeseries)
AI        quiet daily brief · coach · agentic Q&A · similar-day RAG
   ↓
FastAPI (REST + SSE, JWT guarded) → Next.js PWA
```

Deployed entirely on **Railway**: Postgres (official image, managed backups), an
`api` service, and a `sync` cron. No second provider — the app issues its own tokens,
and file storage (FIT, photos) lands on a Railway bucket when phase 3 needs it.

## Repository layout

```
backend/          FastAPI + SQLAlchemy 2.0 + Alembic, uv-managed
  src/vitals/
    config.py     one settings object for every service
    db/           engine, session, models
    auth/         JWT verification, JWKS cache, allowlist, user provisioning
    security/     credential vault (encrypted at rest, provider-agnostic)
    api/          routers, dependencies
    workers/      jobs invoked by the Railway cron service
    cli.py        vitals doctor | auth | garmin | sync | backfill | (later) score, coach
    sources/      garmin: client, rate governor, endpoint catalog, plan · healthkit — phase 10
    ingest/       raw store (bronze), pipeline
    normalize/    canonical vocabulary, per-endpoint normalizers, runner, resolver
    analytics/    maths, derived vocabulary, five modules, engine
    score/        curves, the four pillars, composition, engine
    ai/           digest, OpenRouter client, grounding, coach
  alembic/        migrations
frontend/
  app/            the product's screens — feature work only
  design/         the UI template: tokens, both themes, primitives, style guide
docs/             deployment, local dev, auth, garmin, silver, analytics, score, ai,
                  context,
                  dashboard, design-system
docker-compose.yml  local dev only
```

## Quick start

```bash
cd backend && uv sync --all-groups
uv run alembic upgrade head
uv run vitals doctor
uv run uvicorn vitals.api.main:app --reload

# no identity provider needed — this deployment signs its own tokens:
export VITALS_AUTH_JWT_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
export VITALS_ALLOWED_EMAILS=you@example.com
curl -H "Authorization: Bearer $(uv run vitals auth token --email you@example.com)" \
     localhost:8000/auth/me

# once bronze holds anything, build the layers above it (both safe to re-run):
uv run vitals normalize    # bronze -> silver
uv run vitals recompute    # silver -> gold
uv run vitals score        # gold -> the Vitals Score
uv run vitals explain      # the waterfall behind the latest day
```

See [docs/local-development.md](docs/local-development.md),
[docs/auth.md](docs/auth.md), [docs/deployment.md](docs/deployment.md) and
[docs/design-system.md](docs/design-system.md).

## Design

The UI template lives in `frontend/design/` and is kept separate from
application code on purpose: design work and the phase 3-12 feature branches
never edit the same lines. The app's entire design surface is one `@import`, the
theme-colour metadata in `layout.tsx`, and the components pages import from
`@/design`.

Dark by default with a lime accent; a light theme with a deep-green accent that
clears WCAG AA, since lime on white is unreadable. Both palettes are defined
once, in `frontend/design/tokens.css`. Set in Source Serif 4, self-hosted, for
its tabular figures and optical-size axis.

`npm run dev` and open `/design` for the living style guide: tokens, every
primitive, and three reference screens, rendered from the same exports the app
uses. See [frontend/design/README.md](frontend/design/README.md) for the rules
and [docs/design-system.md](docs/design-system.md) for the merge policy.

## Notes

Garmin history lands in `raw_payload` verbatim and is never re-scraped: everything in
silver and gold is re-derivable from it, so a normalizer bug is a recompute rather than
data loss. Re-fetching an unchanged week writes nothing; a day Garmin revised lands
beside the original.

Health data is gated by `VITALS_ALLOWED_EMAILS`, enforced on every request whatever
issued the token. The API will not start outside local development unless both a
verification method and an allowlist are configured. Tokens are self-issued by default
(`vitals auth token`); pointing `VITALS_AUTH_ISSUER` / `VITALS_AUTH_JWKS_URL` at an OIDC
provider swaps in a real identity provider without a code change.

Garmin data is read through the unofficial Connect API (`python-garminconnect`): the
official Health API does not support personal use, and commercial aggregators are B2B
only. That path is fragile, so an immutable raw store and a conservative rate governor
are load-bearing architecture rather than nice-to-haves. Single-account personal use.

Not a medical device. Nothing here is diagnosis.
