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

`vitals sync` runs it automatically over the window it just fetched, so the Railway
cron keeps silver current without a second scheduled job. `--no-normalize` skips it.
A normalizer that raises is logged and swallowed rather than failing the sync: bronze
is already written by then, and it is the copy that cannot be re-fetched.

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

## Phase 3b: the FIT file

Everything above comes from Garmin's *summary* of an activity. The FIT file is the
recording itself — a heart rate, a position and a power reading for every second the
watch was running — and it answers questions the summary has already thrown away.

### Where the bytes live, and why not a bucket

In Postgres, as `raw_file`: gzipped, hash-deduped, one row per activity. The original
plan said a Railway bucket, and the numbers argued against it. A compressed FIT file
is around a hundred kilobytes; a decade of daily training is under half a gigabyte.
Keeping it in Postgres puts it inside the managed backups and the point-in-time
recovery that are already paid for, with no second service to provision, authenticate
against, or lose. The trade reverses when the artefacts are photographs rather than
recordings — phase 11 is where a bucket earns its place.

### No per-second row reaches Postgres

An hour's run is 3,600 samples across eight channels. A few years of training would be
tens of millions of rows earning their keep about twice a year. So `normalize/fit.py`
decodes the streams in memory, reduces them to the handful of facts that cannot be
recovered from a mean, and drops them:

| Fact | Why it needs the recording |
|---|---|
| Normalized power | The fourth-power rolling average; a ride of surges costs more than its mean |
| Variability index | NP over average power: how ragged the effort was |
| Aerobic decoupling | Speed per heartbeat, first half against second. Invisible in any average |
| Heart-rate drift | The raw bpm behind the decoupling |
| Ascent and descent | From the altimeter, with a threshold under the GPS noise floor |
| Moving time | From the speed channel rather than the watch's opinion |
| Route | Projected to an SVG path in the design system's 380x300 box |

The file is kept verbatim, so a better reduction next year is `vitals recordings
--rebuild` rather than two thousand re-downloads. That is the whole reason the bytes
are worth storing.

### What is deliberately *not* computed here

Anything that needs to know *your* maximum heart rate — time in zones, most obviously.
A zone boundary guessed from 220-minus-age is a number that looks precise and is not,
so zones belong with the response profile in phase 8, not in a decoder.

### The download is capped per run

A summary endpoint returns a year in one call; a FIT file is one call per activity,
forever. Five years of daily training is a couple of thousand of them, which at the
governor's twenty requests a minute is nearly two hours of a container staying awake —
on a plan where staying awake is the bill. So `FIT_PER_RUN` takes a slice and the next
run takes the next one. The history arrives over a fortnight of ordinary syncs, and
nothing is lost by waiting: the files do not expire, and the dashboard never needed
them to render.

The download pass is deliberately separate from the JSON-detail pass above it. That
one skips an activity whose summary is already in bronze, which is right for JSON and
wrong here — every activity recorded before this feature existed has the summary and
no recording, so sharing the skip would have meant the back catalogue was never
downloaded, and nothing would have reported it.
