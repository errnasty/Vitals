# The Vitals Score — phase 5

One number a day, composed from four pillars, every one of them decomposed down to the
readings that moved it.

```
GOLD     derived_daily — 25 metrics, each with its coverage
   ↓     four pillars, each a weighted mean of scored contributions
SCORE    vitals_score · score_pillar · score_contribution
```

A score nobody can interrogate is a score nobody should trust, so the decomposition is
stored rather than recomputed. `vitals explain` reads it back from the database — the
waterfall is a query.

```bash
vitals score                     # everything gold covers
vitals score --since 2026-06-01  # one window, after a recalibration
vitals explain                   # the waterfall behind the latest day
vitals explain --day 2026-08-14
```

## The invariant

**Every contribution's `effect` is the points of the final score it is responsible for,
and they sum to the score.** Not a rough attribution, not a share of its pillar — the
actual decomposition, computed in Python and stored.

```
2026-08-21   Vitals Score 70
coverage 100%

Recovery          69   coverage 100%   weight 30
    hrv_deviation                     1.79    100 pts   12.00 of score
    rhr_deviation                    -0.41     96 pts    8.68 of score
    tsb                             -39.59      0 pts    0.00 of score
...
total          69.92
```

That is what lets the phase-7 model say "your form cost you twelve points" without
being handed a formula and asked to do arithmetic — the root README's rule, enforced
one layer further up. It is tested against 200 randomised combinations of values,
coverage and missing inputs, because a waterfall that does not reconcile is worse than
no waterfall at all.

## Coverage is weight, not a footnote

An input nobody has data for does **not** quietly redistribute its weight to the
others as if it had never been intended. It drags its pillar's coverage down, and the
score says so:

- below `MIN_CONTRIBUTION_COVERAGE` (25%) a reading is left out entirely — it says
  more about the gap than about the person;
- a pillar's coverage is measured against everything it *intends* to use;
- below `MIN_TRUSTED_COVERAGE` (50%) the day is still scored and stored, but
  `trusted` is false. A new account sees a number and is told how much to believe it,
  rather than seeing nothing for two months or a confident fiction.

Both constants are published from `vitals.score` so the UI, the API and the phase-7
prompt agree on one answer.

## Calibration: anchored where there is an anchor, personal where there is not

| | |
|---|---|
| **Anchored** | The WHO's 150 weekly minutes. The 7-9 hours adults are advised. 85% sleep efficiency. The step count where the mortality curve flattens. These defer to an external reference, and the reference is named in the code so it can be argued with. |
| **Personal** | A chronic training load of 80 is a strong base for one person and a deload for another; a VO2max of 45 means nothing without an age, and this app holds neither age nor sex. These score as a percentile against that individual's own recent history — 180 days for fitness, a year for VO2max. |

Personal percentiles need 20 observations before they say anything. Below that the
contribution is not scored and counts as uncovered — not as zero.

## The four pillars

| Pillar | Weight | Contributions |
|---|---|---|
| Recovery | 30 | overnight HRV deviation (40), resting HR deviation (30), form/TSB (30) |
| Sleep | 25 | 7-night duration (35), debt (25), regularity (25), efficiency (15) |
| Training | 20 | fitness percentile (40), load balance/ACWR (35), variety/monotony (25) |
| Longevity | 25 | VO2max percentile (40), weekly activity (35), daily movement (25) |

Weights are a starting calibration, not a finding. Phase 8 fits them to the individual;
until then they are one defensible reading of the evidence, in one readable file.

## Two things deliberately not scored

**Body weight.** There is no direction that is right without knowing someone's goal, and
a daily health score that silently rewards weight loss is the kind of thing that harms
people with a history of disordered eating. Weight and body-fat trends stay visible in
the app as trends. They do not become a verdict.

**Sleep stages.** Wrist-based deep and REM estimates agree with polysomnography only
moderately. Scoring them would spend the user's attention on the least trustworthy
number on the screen.

Both are decisions rather than omissions, which is why they are written down here and
at the top of `score/pillars.py`.

## Shape of the code

```
score/
  curves.py    ramp, band, percentile — a float in, a float out
  pillars.py   the four pillars and every calibration claim, in one file
  compose.py   pure: gold readings in, a decomposed score out
  engine.py    load, walk the days, upsert three tables
```

`compose` is pure, so the whole score is checkable without a database. The engine
writes contributions by delete-and-rewrite rather than upsert: a recalibration can
*remove* a line, and an upsert would leave the old one behind — silently breaking the
one property the waterfall promises.

## Not yet done

**Per-user weights.** Phase 8's response profile is what turns these constants into
something fitted to the person, and the calibration is already isolated in one file so
that change is a substitution.

**Score trend.** A single day's score is noisier than the 7-day average nobody has
computed yet. The table is there; the metric is not.

## The detail screens — phase 7b

`/score` and `/score/{pillar}` answer three questions, in the order people ask them:
what is this number, what is it made of, and what would move it.

None of it is a calculation. The score was already stored decomposed, so "what carried
this pillar" is `order by points` and "what would help most" is `order by headroom`.

### Headroom

`score_contribution.headroom` is the points of the **final score** a line would add if
it scored 100 from where it is — computed in `compose.py`, where the weighting factor
is already in hand, for exactly the reason `effect` is:

> a screen that answers "what would help most" by multiplying weights itself is a
> screen doing arithmetic, and a second place for that sum to be wrong.

It is also why the advice ranks by headroom rather than by what scored worst. A
monotony of 2.4 scoring 7 out of 100 looks alarming and is worth 0.2 points; sending
someone to fix that instead of their sleep debt would be actively unhelpful. Anything
under half a point is left off the screen entirely.

### Targets come from the calibration, not from prose

`ramp_at`, `band_at` and `against_yourself` carry their anchors as a `Target` rather
than hiding them in a lambda. The app grades your sleep against 8 hours, so 8 hours is
what it shows you — and it cannot drift, because the screen reads the same object the
scorer used.

Three curves, three honest kinds of answer:

| Curve | What the screen says |
|---|---|
| `ramp_at` | one direction is better, so there is a number to aim for, and the scale it sits on |
| `band_at` | a range earns full marks; someone already inside it is told **nothing** |
| `against_yourself` | no fixed target exists, and it says so — a VO₂max means nothing without an age |

### Not every input is a dial

`Contribution.lever` is the note about what actually moves a line, and
`Contribution.observed` marks the ones that are readings rather than choices.

"Get your overnight HRV to +0.5 SD" is not advice. It is a number you do not control,
and an app that presents it as a target is teaching you to chase a reading instead of
the sleep and training that produce it. Observed lines get no target and no gap
sentence — only the note about what they answer to.


## The Sleep pillar is not Garmin's sleep score

They are different measurements, and the app now shows both rather than leaving the
reader to assume one is broken.

| | Garmin's sleep score | the Sleep pillar |
|---|---|---|
| Scope | last night | the week |
| Built from | Garmin's own model of stages and quality | duration, debt, regularity, efficiency |
| Windows | one night | 7 days, and 14 for debt and regularity |

Both can be right at the same time — a good night inside a ragged fortnight scores well
on one and poorly on the other, which is the whole point of measuring the week.

The pillar deliberately does **not** score Garmin's number. It is a proprietary model
that changes without notice, and building on it would make this app a relabelling of
Garmin's opinion rather than a second one. But not *showing* it, while displaying a
different number under the word "Sleep", was worse: two numbers with one label and no
explanation reads as a bug, and reasonably so. `/score/pillar/sleep` now carries the
device's own score, the night it was measured on, and a sentence about why the two
differ.

The same page shows the raw night — time asleep, deep, REM, awake — because a score
nobody can check against a measurement is a score nobody should trust.
