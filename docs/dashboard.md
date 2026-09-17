# The dashboard — phase 6

Three screens, rendered on the server, drawn entirely with the design system.

```
Today      the score, its four pillars, and the measurements behind them
Breakdown  the waterfall: every contribution and the points it is worth
Trends     the score over a window, and the derived series behind it
```

## The boundary this phase had to respect

`docs/design-system.md` draws the line: `frontend/design/**` is design work, `frontend/app/**`
is feature work, and they meet through one import path. Phase 6 added six files under
`app/` and **changed nothing under `design/`** — `git status frontend/design/` is the
check, and it comes back clean.

The other half of that contract is that components take *formatted values, never raw
records*, and the root README's rule is that Python owns the arithmetic. So the API
sends `"7h 20m"`, `"−0.17 kg / week"`, `"81"`, and the page renders them. There is not a
single calculation in `app/` — no unit conversion, no rounding, no percentage. The two
things the browser does compute are the viewer's date locale and which icon stands for
"sleep", because neither is a fact about the data.

That rule earned its keep immediately: the score gauge draws its number *from the value
it is given*, so sending the raw float put `65.27882299171765` on screen. The fix was in
Python — the API rounds what it sends — not a `.toFixed()` in a component.

## One endpoint per screen

| Endpoint | Screen |
|---|---|
| `GET /today` | score, pillars, headline measurements, a fortnight of trend |
| `GET /score/explain` | the day's full waterfall, biggest contribution first |
| `GET /trends?days=` | the score series plus six derived series |

Not one endpoint per table. A phone on a train pays for round trips, and the Today view
needs four tables' worth of data — which is one query plan here and four waterfalls of
latency if the client assembles it.

## Auth without a credential in the browser

Every fetch happens on the server, inside a React Server Component, with the token in
the web service's environment as `VITALS_API_TOKEN`. The browser never holds it, never
sees it, and never makes a cross-origin request. For a single-user app that is both
simpler than shipping a token to the client and strictly safer.

```bash
vitals auth token --email you@example.com --days 90   # mint it
# then set VITALS_API_TOKEN on the Railway web service
```

Rotating it is minting a new one and updating one variable.

## Saying why, instead of showing dashes

A new account and a broken API look identical if both render an em dash. So the API
distinguishes them and the UI prints the difference:

- no data at all → *"No data yet — connect Garmin and run a sync."*
- silver but no score → *"No score yet — run `vitals score`."*
- API unreachable → the URL it tried and what went wrong
- token rejected → *"The API rejected the token. Mint a new one."*

And when a score exists but is thin, the Breakdown screen says so in words rather than
letting a confident number stand alone.

## Chart choices

The score renders as **bars up to a month** — each one a readable day against the full
0–100 scale — and as a **line beyond that**. Ninety bars on a phone is a picket fence,
and past a month the shape of the season is what the screen is for. Everything on
Trends is auto-scaled, because those series have no meaningful zero.

## Running it

```bash
cd backend && uv run uvicorn vitals.api.main:app --reload
cd frontend && API_URL=http://localhost:8000 VITALS_API_TOKEN=<token> npm run dev
```

`/design` still renders the style guide from the same exports the app imports, which
remains the fastest way to see a token change land on every primitive at once.

## Not yet done

**Installability.** `manifest.webmanifest` has no icons, so the PWA installs without a
home-screen icon. That needs artwork, which is design work rather than feature work.

**Offline.** No service worker. A cached last-known score would be genuinely useful on
a train, and it is the natural next increment.

**Interaction.** Everything is a server-rendered read. Logging a meal (phase 11) and the
coach (phase 8) are the first screens that will need to write.
