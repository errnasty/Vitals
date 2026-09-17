# Deployment runbook — phases 0 to 2

Everything runs on Railway: Postgres, the API, the cron. There is no second provider to
configure, no second dashboard to keep in sync, and nothing that pauses when it has not
been used for a week.

Target shape:

| Service | Railway type | Root directory | Always on |
|---|---|---|---|
| `Postgres` | database (official image) | — | yes |
| `api` | web, Serverless enabled | `backend` | sleeps when idle |
| `sync` | cron, `0 */6 * * *` | `backend` | runs ~1 min |
| `web` | web, Serverless enabled | `frontend` | optional — see below |

All the app services build from a Dockerfile, so what CI builds is what Railway runs.

**Service settings live in Railway, not in this repo.** Railway deprecated Config as
Code (`railway.json` / `railway.toml`): new services cannot opt into it at all, and
existing files stop being read on **2026-12-01**. The `railway.json` files this repo
used to carry were deleted for that reason — they would have silently done nothing.
Section 2 records every setting instead, and `railway config pull` will capture the live
project into `.railway/railway.ts` when you want it version-controlled again.

---

## 0. What it costs

This matters more than usual if you are on Hobby, because the $5/month subscription
includes exactly $5 of usage and everything in your workspace draws from it.

Railway bills by the minute for what you actually consume:

| Resource | Rate |
|---|---|
| RAM | $10 / GB / month |
| CPU | $20 / vCPU / month |
| Volume storage | $0.15 / GB / month — **used**, not provisioned |
| Egress | $0.05 / GB |

Measured on this project's own services:

| Service | Idle footprint | ≈ / month |
|---|---|---|
| `Postgres` | 89 MB RAM, ~0 vCPU | **$0.90** |
| volume | ~50 MB used of 5 GB | **$0.01** |
| `api` with Serverless | only while you use it | **~$0.05** |
| `sync` cron, 4×/day | ~1 min per run | **~$0.01** |
| `web` on Railway | 150–250 MB, and Next.js telemetry keeps it awake | **$1.50–2.50** |

So the backend costs roughly **$1 a month**; the frontend is what actually threatens
the budget. During the prototype, run the dashboard locally (`npm run dev` against the
deployed API) or put it on a static host's free tier, and skip the `web` service
entirely. Add it to Railway when the dashboard is worth a dollar a month to you.

Two settings do most of the saving, and both are easy to forget:

- **Serverless** (formerly App Sleeping) on `api`. Railway judges idleness by *outbound*
  packets and sleeps a container 5–10 minutes after the last one.
- **`VITALS_DB_POOL_MODE=none`** on any service with Serverless enabled. A warm
  SQLAlchemy pool holds Postgres connections open, and Railway counts that as outbound
  traffic — a pooled API never sleeps and bills around the clock, quietly. With
  `none`, each connection closes with the request that opened it; at one user that
  costs a few milliseconds. `vitals doctor` warns when it sees a warm pool on Railway.

Watch the real number in the project's **Usage** tab rather than trusting this table.

## 1. Postgres

Deploy the official **PostgreSQL** template into the project (`ghcr.io/railwayapp-templates/postgres-ssl`).

The official image is the one worth having: Railway's managed backups and
point-in-time recovery only work on it. What it does **not** ship is `pgvector`, which
phase 9 wants for similar-day search — and nothing before phase 9 touches a vector. So
the initial migration enables the extension only when the server actually has it, and
`/healthz` reports its absence instead of failing:

```json
"pgvector": {"ok": true, "present": false, "version": null, "required": false}
```

When phase 9 lands, either move to a pgvector-capable image (and take over backups with
`pg_dump`, since PITR needs the official image) or keep vectors out of Postgres. Set
`VITALS_REQUIRE_PGVECTOR=true` at that point and the same absence becomes a hard
failure, in the migration and in the healthcheck.

**Turn on backups now, while the database is empty and it costs nothing.** Backups tab →
enable scheduled volume backups, and PITR if you want a four-week restore window. This
is a health history you intend to keep forever; Supabase did daily backups for you and
Railway does not until you ask.

## 2. Railway services

Workspace: `Ernest Ng's Projects`. One project, `vitals`, everything inside it.

`api` — Settings → Source: this repo, root directory `backend`. Then:

| Setting | Value |
|---|---|
| Start command | `sh -c "uvicorn vitals.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"` |
| Pre-deploy command | `alembic upgrade head` |
| Healthcheck path | `/livez` (never touches the database) |
| Healthcheck timeout | 60 |
| Restart policy | `ON_FAILURE`, max 5 |
| Serverless | **on** |
| Public domain | generate one |

The `sh -c` wrapper is load-bearing. Railway execs the start command directly rather
than through a shell, so a bare `--port $PORT` reaches uvicorn as the literal string
`$PORT` and the container crash-loops on `Invalid value for '--port'`. The Dockerfile's
own `CMD` already wraps it correctly — leaving the start command blank and letting the
image decide works just as well.

`sync` — same repo, same root directory `backend`. Then:

| Setting | Value |
|---|---|
| Start command | `vitals sync` |
| Cron schedule | `0 */6 * * *` (UTC) |
| Restart policy | `NEVER` |
| Serverless | off — a cron runs to completion |
| Public domain | none |

`web` — root `frontend`, optional; run it locally during the prototype.

Shared variables (project level):

```
DATABASE_URL=${{Postgres.DATABASE_URL}}   # a reference, so a password rotation follows
ENVIRONMENT=production
VITALS_ENCRYPTION_KEY=<fernet key>
VITALS_AUTH_JWT_SECRET=<48+ random bytes>
VITALS_ALLOWED_EMAILS=<your address>      # the api refuses to start without it
VITALS_DB_POOL_MODE=none
```

Service-specific:

```
api:  CORS_ORIGINS=https://<web domain, or http://localhost:3000 while it runs locally>
web:  API_URL=https://<api domain>
      NEXT_TELEMETRY_DISABLED=1           # telemetry is outbound traffic; it blocks sleep
```

Generate the two secrets:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`DATABASE_URL` as a reference variable resolves to the **private** network
(`postgres.railway.internal`), which is free and unreachable from outside the project.
Use the public proxy URL only from your laptop.

Notes on the cron service:

- Railway cron granularity is 5 minutes and schedules are evaluated in **UTC**.
- If a run is still going when the next tick arrives, the new run is **skipped, not
  stacked** — exactly the semantic a rate-limited scraper wants.
- `sync` bills only the minutes it actually runs.
- Backfill stays a manual one-off. Never put it on cron.
- `railway.sync.json` ships `0 */6 * * *`. Garmin revises days retroactively, so the
  trailing window catches revisions either way — change it to `0 3 * * *` there if you
  would rather sync once a day. The cost difference is cents; the politeness towards a
  rate-limited unofficial API is the better argument.

Migrations run as the api service's `preDeployCommand` (`alembic upgrade head`), so a
failed migration blocks the deploy instead of shipping a broken schema.

## 3. Verify

```bash
curl -sf https://<api>.up.railway.app/livez      # process up, no DB involved
curl -sf https://<api>.up.railway.app/healthz    # DB reachable FROM Railway
railway run --service sync vitals doctor         # same checks from the cron container
```

`/healthz` returns 503 when the database is unreachable; `/livez` never touches the
database and is what Railway's healthcheck polls, so a database blip cannot cycle the
deploy.

Phase-0 exit criteria:

- [ ] the api domain resolves and returns 200
- [ ] `/healthz` reports `database.ok` from Railway
- [ ] `alembic upgrade head` ran against the private `DATABASE_URL`
- [ ] `sync` cron ran once and wrote a `sync_run` row
- [ ] scheduled backups are on
- [ ] the Usage tab shows what you expected it to show

## 4. Signing in

There is no identity provider. This deployment signs its own tokens, and
`VITALS_ALLOWED_EMAILS` decides whose:

```bash
# from your laptop, against the same VITALS_AUTH_JWT_SECRET Railway holds
vitals auth token --email you@example.com --days 90
curl -H "Authorization: Bearer <token>" https://<api>.up.railway.app/auth/me
```

Keep the token in your password manager and mint a new one when it expires. Details and
the migration path to a real provider: [auth.md](auth.md).

## 5. Connecting Garmin

Do this **from your own machine**, not from Railway, against the **public proxy** URL:

```bash
export DATABASE_URL=<Postgres → Variables → DATABASE_PUBLIC_URL>
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

If that fails with a Cloudflare block, move only the `sync` service (section 7).

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

## 6. Moving data off Supabase

Only if a Supabase project already holds rows worth keeping. Nothing here is
Supabase-specific — it is an ordinary logical dump between two Postgres servers.

```bash
pg_dump --no-owner --no-acl --format=custom \
        --dbname="<supabase session pooler URL>" --file=vitals.dump

# --no-owner --no-acl because the roles differ between the two servers
pg_restore --no-owner --no-acl --clean --if-exists \
           --dbname="<railway DATABASE_PUBLIC_URL>" vitals.dump
```

If the dump contains a `vector` column or a `CREATE EXTENSION vector`, the restore will
fail on Railway's image; nothing before phase 9 creates one. Afterwards:

```bash
DATABASE_URL=<railway public URL> vitals doctor    # migrations at head, row counts sane
```

Then point Railway's `DATABASE_URL` at `${{Postgres.DATABASE_URL}}` and redeploy. Keep
the Supabase project until a `sync` run and a sign-in both work against Railway.

## 7. The fallback worth knowing now

The `sync` service is deliberately location-independent: it needs only `DATABASE_URL`
and `VITALS_ENCRYPTION_KEY`. If Garmin's Cloudflare layer ever blocks Railway's
datacenter IPs (phase 2 tests this explicitly), run the same container at home — Pi, NAS,
laptop cron — against the same Postgres public URL, and `api` stays on Railway
untouched. No rearchitecting, just moving one service. That is the main reason sync is a
separate service rather than a thread inside the API.

The same lever cuts cost: the cheapest possible shape is Postgres on Railway and
everything else on hardware you already own.
