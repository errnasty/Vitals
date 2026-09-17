# The silver layer — phase 3

Bronze speaks Garmin. Silver speaks one language, and everything above it reads only
the translation.

```
BRONZE   raw_payload — verbatim provider JSON, immutable, hash-deduped
   ↓     normalizers (pure functions, one per endpoint)
SILVER   metric_daily · metric_sample · sleep_session · activity
   ↓     resolver (source preference, applied per day)
GOLD     phase 4 onwards
```

## The property that matters

**Silver is disposable.** Every row is a deterministic function of a bronze payload, so
dropping all four tables and running `vitals normalize` rebuilds them identically. That
is the whole reason the raw store came first: a normalizer bug is a recompute, never
data loss, and a field ignored today is still sitting in bronze when a later phase
wants it.

It follows that the runner is idempotent. Every write is an upsert on the natural key —
`(user, metric, day, source)`, `(user, source, night)`, `(user, source, activity id)` —
so running it twice is indistinguishable from running it once. There is no "already
normalized" flag to drift out of step with reality.

```bash
vitals normalize                      # everything
vitals normalize --since 2026-01-01   # one window, after fixing a normalizer
vitals normalize --endpoints sleep_detail --dry-run
```

## The tables

| Table | Grain | Holds |
|---|---|---|
| `metric_daily` | one metric, one day, one source | 55 canonical metrics: resting HR, steps, VO2max, sleep duration, weight… |
| `metric_sample` | one instant | intraday stress, body battery, SpO2, respiration |
| `sleep_session` | one night | start/end, stage seconds, score, overnight HRV |
| `activity` | one recorded activity | type, duration, distance, HR, power, training effect |

Sleep gets its own table *and* its headline numbers mirrored into `metric_daily`. The
duplication is deliberate: a night is a thing with a structure that phase 4 asks
structural questions about, but a year-long chart of sleep duration should be one
indexed scan rather than a join.

Activities are keyed by Garmin's own `activityId`, never by start time. Garmin revises
an activity when a device syncs late or you edit it in Connect, and matching on time
would create a duplicate instead of updating the original.

## The vocabulary

`vitals.normalize.canonical` declares every metric before anything may emit it, with a
fixed unit. Normalizers convert *to* that unit — Garmin reports weight in grams, and
nothing above silver should ever have to ask which unit it is holding.

The registry is enforced, not documentation: the test suite runs every normalizer over
a representative payload and fails if it emits a name the vocabulary does not define,
or puts an intraday metric in the daily table. A typo is a red test rather than a
column that silently never fills.

## Precedence, and why it is explicit

Several endpoints report the same thing. Resting heart rate is in both `user_summary`
and `rhr_daily`; VO2max is in both `max_metrics` and `training_status`. Silver holds one
value per metric per day per source, so something has to win.

Each normalizer declares a `priority`, and the runner processes endpoints in ascending
order so the highest-priority writer goes last. Within one endpoint, rows are processed
oldest-first, so a day Garmin revised overwrites the original rather than racing it.

| Priority | Endpoints |
|---|---|
| 30 | `user_summary`, `sleep_detail` — the authoritative daily summary and night |
| 25 | `rhr_daily`, `calories_daily`, `daily_steps` — dedicated range endpoints |
| 20 | everything else |
| 10 | `sleep_daily` — the range summary, superseded by `sleep_detail` |
| 5 | `training_status` — VO2max fallback only |

## Reading it

`metric_daily` keeps one row per source rather than resolving at write time, so a day
the watch was charging and the phone was in a pocket keeps both readings. `daily_series`
applies the preference (`garmin`, then `healthkit`) per day, so a gap in the preferred
source falls through instead of leaving a hole. That ranking lives in exactly one
place; phase 4 asks for a series and never learns sources exist.

## Tolerance, and the number to watch

This is an unofficial API. The field names in `normalize/garmin.py` are the ones
`python-garminconnect` documents today, and firmware or a subscription change can
rename any of them. So every read tries several aliases and returns nothing rather than
raising, and a recompute of seven years never dies on one odd payload.

Which makes **barren payloads** the number to watch. `vitals normalize` reports, per
endpoint, how many payloads produced no rows at all:

```
coverage
  [PASS] sleep_detail: 412 payload(s) -> 2884 row(s)
  [WARN] respiration: 30 payload(s) -> 0 row(s), 30 produced nothing
```

A `WARN` line means a normalizer written from the library's documented shape has met a
different one. The fix is to adjust the aliases and re-run — the payloads are already
in bronze, so nothing was lost while the normalizer was wrong. `no normalizer for: …`
lists endpoints being captured in bronze that nothing reads yet, which is a to-do list
rather than an error.

Run it once after the first real backfill and read that report closely. Normalizers
written against documentation are a hypothesis until real data tests them.

## Not yet done

**FIT parsing.** The per-second streams inside an activity's FIT file — heart rate,
power, cadence, GPS — are what phase 4's training-load work ultimately wants, and the
summary endpoints downsample them away. It needs three things this slice does not
have: `download_activity` in the client, somewhere to put the blobs now that Supabase
Storage is gone (a Railway bucket, or bytea in Postgres), and a parser. It is
independent of everything above — the silver schema does not change — so it lands next
rather than blocking the analytics work.

**Weekly aggregates.** `weekly_stress` and `weekly_intensity_minutes` are captured in
bronze and deliberately not normalized: they are week-grain values that would be
misleading filed under a single day, and phase 4 can compute them from the daily series
it already has.
