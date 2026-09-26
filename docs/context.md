# Context — what the watch cannot know

Every other layer in this app is device data. This one is the only place the user says
anything, and it exists because the physiology cannot explain itself: the watch can
tell you your HRV fell eleven points and has no idea you were on a plane.

```
vitals log          the screen, ~8 seconds to fill in
   ↓
day_context         one row per tag per day, closed vocabulary
day_note            free text, never analysed
   ↓
insights            what actually moves your numbers (next)
```

## Four decisions

**The vocabulary is closed.** Free text cannot be correlated against anything. "Had a
few beers", "drinks with J" and "🍺🍺" are one fact to a human and three to a
statistic, and an app that collects the first while promising the second is lying
about what it can do. A tag outside `context/canonical.py` is rejected, not stored.

**Every tag is a yes/no you already know the answer to.** This gets filled in at 11pm
or not at all. Nothing asks you to rate, estimate or remember — except alcohol, where
one drink and six are different enough to be different facts.

**Context is never scored.** Tagging a day as drinking does not lower your Vitals
Score. The score reads the body; this reads the day, and its whole job is to explain
what the score already found. An app that docked you points for telling it the truth
would stop being told the truth.

**The note is not data.** It is never parsed, never correlated, and never shown to a
model. A closed vocabulary cannot hold everything and a day sometimes needs a
sentence — but text that looks like data invites an app to guess at it, and a guess
about someone's health is worse than an admission that this field is just for them.

## Why it is stored apart from silver

`metric_daily` is rebuildable from bronze at any time. **This is not.** Nobody can
re-derive last Tuesday's mood from a watch, so `day_context` and `day_note` are the
only tables in the app that are never dropped and rebuilt with the layers above them,
and the only ones an export absolutely has to carry.

It is also why the tag list is worth adding to early rather than perfectly: a tag
added next year has no history behind it, and you cannot retroactively remember
whether you drank on a Tuesday in March.

## The tags

| Tag | Fires on | Amount |
|---|---|---|
| `alcohol` | any drinking | drinks |
| `late_meal` | ate within ~3h of bed | |
| `late_caffeine` | caffeine after mid-afternoon | |
| `stress` | a stressful day, however caused | |
| `poor_environment` | too hot, bright, loud, or not your bed | |
| `travel` | flight, long drive, time-zone change | |
| `illness` | cold through fever | |
| `injury` | anything that changed how you moved or slept | |
| `menstruation` | one of the strongest cyclical effects on the numbers | |

Each has to plausibly move something the watch measures. A tag that cannot would
produce nothing but false positives once the analysis starts testing them in bulk,
and every tag costs a multiple-comparisons correction against every other.

## API

```
GET /context?day=            the day, plus the vocabulary to draw it with
PUT /context/tags?day=       replace the day's tags with exactly this set
PUT /context/note?day=       write or clear the note
```

The vocabulary ships with every response, so the client never keeps its own copy and
a new tag appears on screen the moment it appears in the canonical list.

Writes **replace** rather than merge: the screen sends the whole day, and a tag just
unticked has to disappear. Tags are validated before anything is written, so one bad
name rejects the request instead of writing half of it.
