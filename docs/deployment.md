# Deployment runbook — phases 0 to 2

Phase 0 deploys before the app does anything useful. Railway and Supabase integration
problems are cheap to fix in week one and expensive in week ten.

Target shape:

| Service | Railway type | Root directory | Config file |
|---|---|---|---|
| `api` | always-on | `backend` | `railway.json` |
| `web` | always-on | `frontend` | `railway.json` |
| `sync` | cron | `backend` | `railway.sync.json` (set `RAILWAY_CONFIG_FILE`) |

All three build from a Dockerfile, so what CI builds is what Railway runs.

---

## 1. Supabase

1. Create a project (region close to you). Note the database password.
2. **Database → Extensions**: enable `vector`. The initial migration also issues
   `CREATE EXTENSION IF NOT EXISTS vector`, but enabling it from the dashboard first
   avoids a permissions surprise on a fresh project.
3. **Connection string**: use the **session pooler**, port **5432**.
   Not the transaction pooler on 6543 — it does not support prepared statements, and
   asyncpg creates them unconditionally. That mismatch produces the
   `prepared statement "asyncpg_stmt_x" does not exist` class of bug, and
   `statement_cache_size=0` alone is not a reliable fix.
   The URL arrives as `postgresql://...?sslmode=require`; `vitals.config` rewrites the
   scheme to `postgresql+asyncpg://` and translates `sslmode` to `ssl` automatically, so
   paste it unchanged.
4. **Authentication → Providers → Email**: **disable public sign-ups**, and allowlist
   only your own address. A public URL otherwise means anyone can create an account on
   your health app. This is the single most important deployment setting; phase 1 depends
   on it.
5. **Storage**: create a private bucket `vitals` (FIT files from phase 3, meal photos
   from phase 11). Railway's filesystem is ephemeral, so nothing durable can live there.

## 2. Railway

Workspace: `Ernest Ng's Projects`. One project, three services, all from this repo.

```
api    root=backend    → generate a domain
web    root=frontend   → generate a domain
sync   root=backend    → RAILWAY_CONFIG_FILE=railway.sync.json, cron 0 */6 * * *
```

Shared variables (project level):

```
DATABASE_URL=<supabase session pooler URL, port 5432>
ENVIRONMENT=production
VITALS_ENCRYPTION_KEY=<fernet key>     # needed from phase 2
SUPABASE_URL / SUPABASE_ANON_KEY / SUPABASE_SERVICE_ROLE_KEY / SUPABASE_JWT_SECRET
VITALS_ALLOWED_EMAILS=<your address>   # the api refuses to start without it
```

`SUPABASE_URL` is what enables JWKS verification for a current project;
`SUPABASE_JWT_SECRET` covers legacy HS256 projects. Setting both is fine — each token is
verified by the path its own header selects. See [auth.md](auth.md).

Service-specific:

```
api:  CORS_ORIGINS=https://<web domain>
web:  API_URL=https://<api domain>
```

Notes on the cron service:

- Railway cron granularity is 5 minutes and schedules are evaluated in **UTC**.
- If a run is still going when the next tick arrives, the new run is **skipped, not
  stacked** — exactly the semantic a rate-limited scraper wants.
- `sync` bills only the minutes it actually runs. Only `api` and `web` are always-on.
- Backfill stays a manual one-off. Never put it on cron.

Migrations run as the api service's `preDeployCommand` (`alembic upgrade head`), so a
failed migration blocks the deploy instead of shipping a broken schema. Because
`DATABASE_URL` is the session pooler, that satisfies the "never migrate through the
transaction pooler" rule.

## 3. Verify

```bash
curl -sf https://<api>.up.railway.app/livez      # process up, no DB involved
curl -sf https://<api>.up.railway.app/healthz    # DB + pgvector reachable FROM Railway
open  https://<web>.up.railway.app               # web -> api -> db, rendered
railway run --service sync vitals doctor         # same checks from the cron container
```

`/healthz` returns 503 when the database is unreachable; `/livez` never touches the
database and is what Railway's healthcheck polls, so a Supabase blip cannot cycle the
deploy.

Phase-0 exit criteria:

- [ ] both domains resolve and return 200
- [ ] `/healthz` reports `database.ok` **and** `pgvector.ok` from Railway
- [ ] the web page renders the api's health, i.e. web → api → Supabase works end to end
- [ ] Supabase sign-ups are **disabled** with only your email allowlisted
- [ ] `alembic upgrade head` ran against the session pooler, not 6543
- [ ] `sync` cron ran once and wrote a `sync_run` row

Phase-1 exit criteria:

- [ ] `curl https://<api>/auth/me` without a token returns **401** `missing_credentials`
- [ ] signing in through Supabase and presenting the access token returns **200** with
      your `app_user` row
- [ ] a token for any other address returns **403** `forbidden`
- [ ] `railway run --service api vitals doctor` reports the JWKS key set and a non-empty
      allowlist

## 4. Connecting Garmin

Do this **from your own machine**, not from Railway, against the same `DATABASE_URL`:

```bash
export DATABASE_URL=<supabase session pooler URL>
export VITALS_ENCRYPTION_KEY=<the same key Railway holds>
vitals garmin login --email you@garmin-account     # password + MFA prompt
vitals garmin test                                  # confirms the stored tokens work
```

Garmin's SSO sits behind Cloudflare, which is markedly harsher on datacenter IPs. The
token lasts about a year and refreshes over the ordinary API, so this is the only time
anything logs in — Railway never does. Full reasoning in [garmin.md](garmin.md).

Then confirm the datacenter IP is tolerated **before** the cron depends on it:

```bash
railway run --service sync vitals garmin test
railway run --service sync vitals sync --dry-run    # the plan, no requests
```

If that fails with a Cloudflare block, move only the `sync` service (section 5) — it
needs nothing but `DATABASE_URL` and `VITALS_ENCRYPTION_KEY`.

Backfill is a manual one-off, never a cron:

```bash
vitals backfill --start 2019-01-01 --dry-run        # ~320 requests for 7 years
vitals backfill --start 2019-01-01                  # ~15 minutes, governed and jittered
```

Phase-2 exit criteria:

- [ ] `vitals garmin login` stored tokens, and `vitals garmin status` shows `active`
- [ ] `vitals garmin test` passes **from Railway**, not just locally
- [ ] a redeploy followed by `vitals sync` still works — proving tokens survived the
      ephemeral filesystem, which is the failure this design exists to prevent
- [ ] backfill landed multi-year history: `vitals garmin status` reports the date range
- [ ] a second `vitals sync` over the same window stores 0 new payloads
- [ ] the `sync` cron ran on schedule and wrote a `sync_run` with `status=success`

## 5. The fallback worth knowing now

The `sync` service is deliberately location-independent: it needs only `DATABASE_URL`
and `VITALS_ENCRYPTION_KEY`. If Garmin's Cloudflare layer ever blocks Railway's
datacenter IPs (phase 2 tests this explicitly), run the same container at home — Pi, NAS,
laptop cron — against the same Supabase, and `api` + `web` stay on Railway untouched.
No rearchitecting, just moving one service. That is the main reason sync is a separate
service rather than a thread inside the API.
