# Garmin connector — phase 2

The riskiest part of the whole project, and the reason it is quarantined behind an
immutable raw store.

## Why this way

The official Garmin Health API is not available: the Connect Developer Program is for
legal entities, excludes personal use, and is currently closed to new registrations.
The commercial aggregators (Terra, Vital, ROOK) are B2B, sales-led, and priced per
connected user. That leaves the unofficial Connect API through
[`python-garminconnect`](https://github.com/cyberjunky/python-garminconnect), which
became the only viable option once `garth` was deprecated in March 2026 — Garmin changed
the auth flow, and the library now carries its own SSO strategy chain with `curl_cffi`
TLS-fingerprint impersonation.

An unofficial API can break without warning. So the design assumes it will:

* every response is written to **bronze** (`raw_payload`) verbatim before anything
  interprets it, because a payload not captured today may be unobtainable tomorrow;
* the request rate is **governed**, because the library fails fast on 429 with no retry
  and an account lockout would end the project;
* authentication is **never performed from the cloud**, for reasons below.

## The login that happens once a year, on your laptop

`vitals garmin login` is the only command that touches Garmin's SSO endpoint, and it is
meant to run on your own machine:

```bash
# locally, against the same DATABASE_URL Railway uses
vitals garmin login --email you@garmin-account
```

Garmin's SSO sits behind Cloudflare, which treats datacenter IP ranges far more harshly
than residential ones. The OAuth token it returns lasts about a year, and the short-lived
DI token refreshes over the ordinary API — so Railway only ever refreshes and calls,
never logs in. That converts the single riskiest recurring operation into a manual step
you do roughly annually.

The command warns if `ENVIRONMENT` is not `local`. Nothing stops you overriding that;
the warning is the point.

### ...and the same login from the app, when there is no laptop

`/connect` does the same thing from a phone. It exists because a connector you cannot
connect from the device you have on you is not much of a connector — not because the
IP problem went away. The request leaves Railway, Cloudflare sees a datacenter, and
the screen says so before you type anything.

The mechanics are the interesting part. `prompt_mfa` blocks inside `login()` until a
callback produces a code, which is fine for a terminal and impossible for a web
request: the HTTP response has to go back before the user can read their code. So the
web path uses the library's `return_on_mfa`, which hands the half-finished login out
as a `client_state` instead, and `resume_login(client_state, code)` picks it up. Two
requests, minutes apart, possibly different processes — a Railway container is free to
sleep in between.

Which means nothing can be held in memory:

| | |
|---|---|
| Where the half-finished login lives | `credential`, encrypted, under `garmin.pending_login` |
| How long | 10 minutes, then it is deleted |
| What it holds | the resumable state, the email, and the password |
| Attempt cap | 5 failures, then a 15-minute lockout |

The password is the uncomfortable one, and it is deliberate: rebuilding the client for
the resume needs it. It is encrypted under the same Fernet key as everything else and
deleted the moment the login resolves either way. That is a smaller promise than
`--store-password`, which keeps it indefinitely on purpose — but it is not *no*
promise, and if that trade is not worth it to you, use the CLI.

The attempt cap is the part that actually protects the account. A web form turns "one
careful annual login" into something that can be retried thirty times in a minute, and
thirty SSO attempts from a datacenter IP is how an account gets locked.

```
POST /garmin/connect       {email, password}  -> "connected" | "mfa_required"
POST /garmin/connect/mfa   {code}             -> "connected"
GET  /garmin/status                           -> connected, awaiting_mfa, locked_until
POST /garmin/disconnect                       -> forgets the tokens, keeps the data
```

`GET /today` carries `source_connected` too, so the home screen can offer the link in
every state — including the one where there is plenty of old data on the page and
nothing new has arrived for a week.

### Tokens have to survive the container

Railway's filesystem is ephemeral and the library caches tokens to a file, so a naive
deploy would re-login through SSO on every push — the exact path to a rate-limited
account. Instead:

1. tokens are stored encrypted in `credential` (Fernet, under `VITALS_ENCRYPTION_KEY`,
   which lives only in the Railway environment — a database leak alone is not enough);
2. a run resumes with `login(tokenstore=<inline JSON>)`, which the library accepts
   directly, no file involved;
3. after every run the client's `dumps()` is read back and re-stored **if it changed**.

Step 3 is not bookkeeping. The library refreshes the DI token before expiry and only
writes it to disk when the tokenstore was a path — so with inline JSON that refresh
exists purely in memory. Capturing it is the difference between a token that lives a
year and one that dies with the process.

## What a sync costs

Everything is planned before anything is fetched, so the cost is inspectable:

```bash
vitals sync --dry-run                                  # ~29 requests
vitals backfill --start 2019-01-01 --dry-run           # ~320 requests for 7+ years
```

The daily run re-fetches a **trailing 7-day window** on the range endpoints. That is
what catches Garmin's retroactive revisions — sleep scores and training status get
recomputed days later — and thanks to bronze's content hashing, the days that did not
change cost a request and no rows.

History comes from **range endpoints only**. `get_rhr_daily(start, end)` covers a year
in one request where a per-day loop would take 365. The per-day endpoints
(`training_readiness`, `sleep_detail`, …) have no range variant, so they run for recent
days only and their history accrues from the day you connect.

Long spans are chunked by *us*, not by the library: `get_sleep_daily` and
`get_daily_steps` chunk internally at Garmin's 28-day limit, which would turn one call
into a hundred requests the governor never sees.

## Rate governance

`sources/garmin/governor.py`, because the library retries 5xx and network errors but
deliberately does not retry 401 or 429:

| Mechanism | Default | What it prevents |
|---|---|---|
| token bucket | 20 req/min, burst 5 | a burst that looks like scraping |
| jitter | 1–3 s between calls | a metronome signature |
| backoff + cooldown | 5 min, doubling, capped at 6 h | racing back after a 429 |
| circuit breaker | 5 consecutive failures | hammering a broken endpoint |
| request budget | 2000 per run | a loop bug becoming 10,000 requests |

The cooldown and failure count are persisted on `source_connection`, so a Railway
redeploy in the middle of a cooldown does not restart the stampede. A run checks them
*before* connecting, since resuming a session is itself a network call.

## Failure modes

| Connection status | Meaning | What to do |
|---|---|---|
| `active` | normal | nothing |
| `degraded` | rate limited, or repeated failures; a cooldown may be running | wait; `vitals garmin status` shows until when |
| `needs_reauth` | tokens rejected or missing | `vitals garmin login`, locally |
| `disabled` | switched off by hand | re-enable in the database |

A single endpoint failing does not fail the run: the rest of the window still lands and
the run closes as `partial`. Only a rate limit, an auth failure or the breaker stop
everything — the three cases where continuing makes things worse.

Whatever happens, data already in bronze is untouched. If Garmin breaks auth outright
tomorrow, the app degrades to read-only analysis over the history you already hold.

## Commands

```bash
vitals garmin login    --email you@garmin        # local, once a year
vitals garmin test                               # one authenticated call from THIS host
vitals garmin status                             # connection, tokens, bronze coverage
vitals garmin logout                             # delete stored tokens
vitals sync            [--days 7] [--dry-run]    # what the Railway cron runs
vitals backfill        --start 2019-01-01 [--dry-run]
vitals doctor                                    # includes a garmin section
```

`vitals garmin test` exists for one question: does *this host* work? Run it on Railway
(`railway run --service sync vitals garmin test`) to find out whether Cloudflare
tolerates the datacenter IP before a real sync depends on it. If it does not, the sync
service is deliberately location-independent — it needs only `DATABASE_URL` and
`VITALS_ENCRYPTION_KEY`, so run that same container at home against the same Postgres
and leave `api` and `web` on Railway.

## Bronze

```
raw_payload(user_id, source, endpoint, calendar_date, entity_key, payload, payload_hash)
unique (…, payload_hash) NULLS NOT DISTINCT
```

Range responses are split into one row per day, so a week-long response does not
rewrite itself whenever a single day in it changes. Unrecognised shapes are stored whole
— bronze is verbatim, and phase 3's normalizers are where payloads are finally
interpreted. `calendar_date` always comes from the *request*, never from the payload's
`*Local` fields, which the library documents as double-offset on some accounts.

Re-storing an identical payload bumps `last_seen_at` instead of inserting; a changed one
lands beside the original, giving a revision history nobody had to design for.

## What is not covered by tests

The connector is tested end to end against a fake Garmin and a real Postgres: the plan,
the governor, bronze dedup, revision capture, activity de-duplication, the token
round-trip and every failure transition. What no test can cover without an account:

* whether the stored tokens actually authenticate,
* whether Cloudflare tolerates the host the sync runs on,
* the real shape of each payload — the splitter falls back to storing responses whole,
  which is safe but means phase 3 will be the first code to look closely at real data,
* whether the 365-day chunk is acceptable to every range endpoint (if one objects, it
  degrades that endpoint to a warning, and the fix is one number in `endpoints.py`).

Those are exactly the four things `vitals garmin login` followed by
`vitals backfill --start … --dry-run` and then a real backfill will tell you in about
ten minutes.

## FIT files

`download_activity(..., ORIGINAL)` archives the full-resolution timeseries the JSON
endpoints downsample away. It lands in phase 3, together with a Railway bucket and the
`fitdecode` parser — there is nowhere durable to put the bytes until then, and Railway's
filesystem is not it.
