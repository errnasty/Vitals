# The daily brief — phase 7

Two or three sentences a day, written from numbers Python already computed, with every
number in them checked before they are stored.

```
GOLD     derived_daily · vitals_score · score_pillar · score_contribution
   ↓     digest — one day, compact, every value already formatted
AI       OpenRouter → grounding validator → daily_brief
```

```bash
vitals brief             # write today's, or read back an unchanged one
vitals brief --digest    # exactly what the model is shown, and nothing written
vitals brief --force     # rewrite an unchanged day, after editing the prompt
vitals brief --day 2026-09-14
```

## The rule this phase exists to keep

The README's rule — **the LLM never does arithmetic** — is a promise, and a promise
nothing enforces is a hope. `grounding.py` is the enforcement, and it applies one
sentence:

> Every number in the brief must appear in the digest the brief was written from.

Not "must be close to", not "must be derivable from". Derivable is exactly the failure
being prevented. If the digest says `7h 16m` and the brief says `7.3 hours`, that
conversion is arithmetic the model did, it is unverifiable by the person reading it,
and it is rejected.

The check is mechanical — no model judges another model's output, because a checker
that can be talked out of its answer is not a checker. The permitted set is extracted
from the rendered digest with the same extractor that reads the brief, so the two
cannot disagree about what a number is.

It also checks the verdict word. The screen says *Balanced*; a brief that opens with
"a Strong day" is two surfaces disagreeing about the same number, which is the small
incoherence `score/verdict.py` exists to prevent.

## Two guarantees

**The brief always exists.** No API key, no credit, a provider outage, a model that
cannot stop rounding — in every one of those cases the reader gets a brief, composed in
Python from the same ranked signals the model would have been given. It is plainer. It
is never wrong. A health app that goes quiet when a vendor has a bad night has taught
its user not to rely on it.

**The brief is never stored ungrounded.** If the validator rejects both attempts, the
model's text is discarded — not stored with a warning label, not shown behind a
disclaimer. A number Python did not compute does not reach the screen.

```
digest → (unchanged? stop) → model → check → retry once, fault named → store
                                       ↓ still ungrounded
                                    compose in Python
```

One retry, not a loop. A model told exactly which number it invented will usually fix
it; one that does it twice is the wrong model for the job, and a third opinion costs
money.

## Quiet is decided in Python

A model asked "write a note about this day" will always find something to say, every
day, because that is the task it was given. An app built that way nags.

So `signals.py` decides first, with published thresholds, and hands the model at most
three ranked observations — or tells it plainly that there are none.

| Signal | Fires when | Anchor |
|---|---|---|
| `thin_data` | coverage below the trusted floor | said first; it qualifies everything else |
| `score_moved` | ≥ 5 points from the 14-day mean | day-to-day variance sits well under this |
| `low_pillar` | the weakest pillar is below 50 | the `verdict.py` band for "Mixed" |
| `load_balance` | ACWR outside 0.8–1.3 | Gabbett; a spike outranks a lull |
| `sleep_debt` | ≥ 3h cumulative | about where a deficit stops being one bad night |
| `monotony` | above 2.0 | Foster; tracks with illness and overreaching |
| `drag` | the weakest line scores below 40 | |
| `lift` | the strongest scores above 85, **and nothing else fired** | on a bad day this reads as consolation |

Each signal carries its own finished sentence. That text is what the model is shown,
what it is allowed to quote, and what the Python fallback is assembled from — so the
three can never drift apart.

## What the model is not shown

**Weight and body composition.** `score/pillars.py` refuses to score them because there
is no direction that is right without knowing someone's goal, and a daily note that
mentions them is a verdict whatever words it reaches for. A prompt asking a model not
to comment on someone's weight is a request; leaving the number out of what it can see
is a guarantee.

**Any timeseries.** The digest summarises a fortnight of scores into one mean and one
direction. The architecture's gold→AI boundary is a compact digest, and this is where
it is enforced.

## What it costs

Roughly 900 tokens in and 60 out, once a day. Three things keep it there:

- **The fingerprint.** `daily_brief.digest_fingerprint` is a content hash of the
  rendered digest. A re-run over a day whose facts have not moved is read back from
  storage, not rewritten — which matters most during a backfill that recomputes a year
  of scores.
- **The API never generates.** `/today` and `/brief` read the stored row. A page load
  that spends money and waits on a third party is a page that is sometimes slow and
  sometimes expensive; the cron writes, the API reads.
- **The output cap.** `VITALS_AI_MAX_TOKENS` defaults to 300 as a runaway guard. Sixty
  words needs nowhere near it.

## Configuration

| Variable | Default | |
|---|---|---|
| `OPENROUTER_API_KEY` | unset | Unset is a supported state: briefs are composed in Python. |
| `VITALS_AI_MODEL` | `anthropic/claude-sonnet-5` | An OpenRouter slug, as its catalogue lists it. |
| `VITALS_AI_MAX_TOKENS` | `300` | Output cap. |
| `VITALS_AI_TIMEOUT_S` | `30` | |
| `VITALS_AI_FORCE` | `false` | Rewrite every day regardless of the fingerprint. |

The model is a swappable part on purpose. The brief is sixty words written from numbers
Python already computed, so the difference between frontier models on this task is
small and the difference in price is not. Nothing above `openrouter.py` knows which
model wrote anything. `vitals doctor` prints the configured slug.

## Shape of the code

```
ai/
  digest.py      one day → a compact payload; renders once, to text
  signals.py     what is worth raising, and the sentence for each
  openrouter.py  one endpoint, three error kinds: Unavailable / Refused / Transient
  grounding.py   every number in the brief must be in the digest
  brief.py       generate → check → retry → store, or compose in Python
  prompts/
    brief.md     the rules the model is given
```

`db/models/brief.py` stores the prose beside its provenance: who wrote it, whether it
was checked, which digest it was written from, and how many attempts were rejected. A
row reading `source='python', attempts=2` is the system working.

## Known limits

- **Incidental digits are permitted.** The allowed set is *every* number in the
  rendered digest, so `7h 16m` makes `7` sayable. The alternative is a curated
  whitelist of "the numbers that count" — a second thing to keep in step with the
  digest, wrong the first time a contribution is added. The hole is small, deliberate
  and asserted in `test_ai_grounding.py`.
- **Units and claims are not checked.** "Your resting heart rate is 48 kg" is grounded
  and wrong. The mitigation until phase 8 is that the model is handed finished
  sentences to quote rather than fields to assemble.
- **The default model slug is a guess at your catalogue.** If OpenRouter does not know
  it you get a `Refused` with its own message, the brief falls back to Python, and
  `vitals brief` prints why.

## Phase 9: asking a question

The daily brief writes from a fixed digest. A question is not fixed, so something has
to decide what facts to load — and that something is Python, reading the question's
words, not a model choosing its own retrieval.

### Why not a tool-calling loop

A model that chooses what to fetch can choose to fetch nothing and answer from memory.
On health data that is *the* failure: the answer looks identical, sounds more fluent,
and is about nobody. Routing in Python means what was loaded is knowable, testable,
and is simultaneously the context the model is given **and** the set of numbers it is
permitted to state.

The routing is keyword matching, deliberately. It is legible, it costs nothing, and
when it is wrong the answer carries a few extra facts rather than a wrong one. When
nothing matches, the day's own score is included, which is what most questions turn
out to need.

### The same guarantee as the brief

Generate → check every number against the pack → retry once naming the fault → fall
back to Python. `ai/grounding.py` is reused unchanged. The fallback is not a degraded
mode here: for most questions the facts themselves *are* the answer, just without
prose around them, and the screen says which of the two you are reading. An answer
composed in Python because the model invented a number must not look identical to one
the model wrote and passed.

Staleness goes into the pack as a fact. An answer written confidently about "today"
from a week-old sync is the single most misleading thing this feature could produce.

### Similar days, without pgvector

See `analytics/similar.py`. The short version: exact nearest-neighbour over a few
thousand days by a dozen standardised features is under a millisecond, so the
extension — and the loss of Railway's managed backups that adopting it would have
cost — was never necessary.

Two details that decide whether the answer is meaningful. Features are divided by
their own spread, because resting heart rate moves over a range of ten and steps move
over a range of ten thousand, and unscaled distance is a step-count search with
rounding noise attached. And days within three days of the target are excluded:
yesterday resembles today because it *is* nearly today, and a list of the four days
either side is a true answer that tells you nothing.

### Journal fusion, and a promise that was already made

Phase 3's Log screen told the person, on the screen where they typed the text, that
their note is "never analysed and never shown to a model". Phase 9 wanted to show it
to one.

A promise made where the data was entered is not one a later phase gets to withdraw
quietly. So:

* `app_user.share_notes_with_ai` is **off by default**, and off means the original
  promise is exactly what happens — not a word reaches the model.
* The Log screen's wording is conditional on the setting. It changes with the
  behaviour rather than staying reassuring while the behaviour moves underneath it.
* The note is still never *analysed*. Nothing is derived from it, nothing is
  correlated against it, and it never reaches silver, gold or the score. Free text
  cannot be correlated — that is why the tag vocabulary is closed — so the only honest
  use for a note is as something a model may read while answering, which is precisely
  what the setting grants and nothing more.
* When shared, it reaches back a fortnight. Far enough for "last week", short enough
  that a question about today does not hand over a year of someone's diary.
