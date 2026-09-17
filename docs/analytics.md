# The analytics engine — phase 4

Silver holds what a device observed. Gold holds what those observations *mean*.

```
SILVER   metric_daily · metric_sample · sleep_session · activity
   ↓     five pure modules: training · recovery · sleep · body · longevity
GOLD     derived_daily — value, unit, and how much data it rests on
   ↓
phase 5  the Vitals Score composes these into four pillars
```

This is where the root README's rule stops being a slogan. **Python computes every
number here.** The model that arrives in phase 7 selects, prioritises and explains what
this package produced; it never does arithmetic on it.

## Coverage, and why every row carries it

A 42-day fitness figure computed from 41 days and one computed from 6 are both a
number, and nothing about the number says which you are holding. So every row in
`derived_daily` carries `coverage` — the fraction of its declared window that actually
held an observation — and `inputs`, the raw count behind it, because "3 of 42" explains
itself in a way "0.07" does not.

Phase 5 is required to respect it: a pillar cannot count for more than its coverage
allows. That is the mechanism that stops a brand-new account being told, confidently,
that its fitness is declining.

```bash
vitals recompute                      # everything silver covers
vitals recompute --since 2026-06-01   # one window, after changing a formula
vitals recompute --dry-run
```

`vitals sync` runs it after normalizing, so the Railway cron keeps gold current. Gold
is a projection of silver in exactly the way silver is a projection of bronze: drop the
table, run it again, get the same numbers.

## Training load

The standard impulse-response model — a 42-day exponentially weighted average standing
for fitness (CTL), a 7-day one for fatigue (ATL), their difference for form (TSB). Forty
years old, shipped by every endurance platform, and useful for its trend rather than its
absolute value.

Per-activity load uses Garmin's own `activityTrainingLoad` where it exists and falls
back to Banister's TRIMP — minutes weighted by heart-rate reserve — where it does not.
A session with no heart rate is *absent* rather than counted as an easy one.

The judgement call worth stating plainly:

> A day the watch was worn with no workout is a **zero**.
> A day the watch was not worn at all is **unknown**.

Fitness decays through the first and holds through the second. Conflating them is the
difference between a rest week reading as recovery and reading as data loss.

`monotony` and `strain` are Foster's: the week's mean load over its spread, and that
ratio multiplied back by the total. Two weeks with identical totals are not equivalent —
the one that put it all in two sessions is the one that gets people hurt. A week of
*identical* sessions makes the ratio divide by zero, and since that is the most
monotonous week there is, it is reported at a ceiling rather than dropped.

`acwr` is published because it is asked for, and should be read as a trend rather than
a threshold. The "danger zone" literature it comes from has not held up well.

## Recovery

Everything here is a z-score against a rolling personal baseline, never a population
norm. An overnight HRV of 40ms and one of 120ms are both perfectly healthy in different
people, so the only meaningful scale is that person's own spread.

The baseline is 60 days and deliberately **ends yesterday**. Including today in the
average today is compared against would damp exactly the excursion worth noticing.
Below 14 observations no baseline is published at all — a baseline from five nights is
noise wearing a baseline's clothes.

## Sleep

Duration is the number everyone quotes and the least interesting of the three.

- `sleep_debt` accrues shortfalls against an 8-hour need over 14 days. Surpluses do not
  refund it; the literature is clear that the debt does not settle that cleanly.
- `sleep_consistency` is the spread of the sleep midpoint — and it is **circular**.
  Someone who sleeps at 23:50 one night and 00:10 the next is twenty minutes apart, and
  ordinary arithmetic puts them 1420 apart and reports a wildly erratic sleeper.
- `sleep_efficiency` and the stage percentages come from `sleep_session`, because
  `metric_daily` cannot carry a start and an end.

## Body

Day-to-day scale weight moves by more than a week of real change. What is published is
a smoothed trend (roughly the Hacker's Diet constant) and its slope in kg/week; the raw
value stays in silver for anyone who wants it. Reporting the daily number invites
reacting to hydration.

## Longevity

The handful of numbers with the strongest all-cause mortality evidence behind them.

- **VO2max trend and slope.** Across large cohorts cardiorespiratory fitness separates
  outcomes more sharply than smoking status, and unlike most risk factors it is directly
  trainable — which makes its trend arguably the single most useful number this app
  computes. The slope is per *year*, because the decline it is measured against (roughly
  10% a decade untrained) is an annual quantity.
- **Weekly activity minutes**, counted as the WHO counts them: 150 minutes a week, with
  vigorous minutes worth double.
- **Steps**, a 7-day mean, because the dose-response is real and it is the number people
  actually act on.

## Shape of the code

```
analytics/
  math.py        ewma, rolling stats, slope, z-score, circular spread — pure floats
  canonical.py   the 25 derived metrics, each with the window it needs
  series.py      silver -> dense daily arrays, plus nights and per-day activity load
  training.py    recovery.py  sleep.py  body.py  longevity.py
  engine.py      window, load once, walk days, coverage, upsert
```

The five modules are pure functions of `(Inputs, day)`. They do not fetch, store or
explain — which is why the sports science is testable by handing one a fortnight of
numbers and checking the answer by hand, with no database in sight. The engine chunks
by 90 days and always loads the longest declared window *behind* the window being
written, so recomputing the last three days still produces a correct six-week CTL.

A module that raises is logged and skipped rather than sinking the run: one bad formula
must not cost the other four their output.

## Not yet done

**Per-user constants.** The 8-hour sleep need, the TRIMP coefficient and the default
max heart rate are population values. They belong in the phase-8 response profile,
fitted to the individual — the code already isolates them as named constants so that
change is a substitution rather than a rewrite.

**Intraday analysis.** `metric_sample` holds stress and body battery at minute
resolution and nothing here reads it yet. It is what the phase-3b FIT work will feed,
and it is where questions like "how much of today's stress was the meeting" get
answered.
