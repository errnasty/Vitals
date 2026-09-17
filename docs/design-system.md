# Design system and merge policy

The UI template lives in `frontend/design/` and is deliberately isolated from
application code, so that design work and the phase 3-12 feature branches never
edit the same lines.

`frontend/design/README.md` is the reference for the system itself — tokens,
themes, type, components. This file records the repository-level policy.

## Why it is separate

Phases 3 through 12 are mostly backend work with a thin UI surface, landing on
long-lived branches that merge in an order nobody controls. A design change that
reached into pages, or a page that carried its own styling, would put both kinds
of work in the same hunks.

So the boundary is drawn where merges happen, not where components happen:

```
frontend/design/**        design work only.  No feature branch should touch it.
frontend/app/**           feature work only. No design branch should touch it,
                          apart from the three files below.
backend/**                never touched by design work at all.
```

The whole app-side design surface is three files, all of which are stable:

| File | What design owns in it |
|---|---|
| `frontend/app/globals.css` | One `@import` line. Nothing else ever goes here. |
| `frontend/app/layout.tsx` | `themeColor` and the pre-paint theme script |
| `frontend/app/design/page.tsx` | Four lines that render the style guide |

Pages import components from `@/design` and pass formatted values in. That is
the entire coupling.

## Conflict expectations

| Change | Conflicts with feature branches? |
|---|---|
| Retheming, new tokens, new light/dark values | No — `tokens.css` only |
| New or restyled component | No — `design/components/` only |
| New icon | No — `design/icons.tsx` only |
| Swapping the typeface | No — `fonts.css` + one token |
| A page using a new component | Yes, in that page — which is the intended place |

`package.json` and `package-lock.json` are deliberately untouched by the design
system: it uses CSS Modules and CSS custom properties, both built into Next.js,
and self-hosts its own font files. No design change can produce a lockfile
conflict.

## Rules worth keeping

- **No colour, radius, spacing, duration or type size outside `tokens.css`.**
  A hard-coded value is a value that cannot be rethemed and will be wrong in one
  of the two themes.
- **No business logic in `design/`.** Components take formatted strings. The
  root README's rule — Python computes every number — means the UI layer has no
  arithmetic in it either.
- **App code imports `@/design`, never `@/design/components/Thing`.** The deep
  paths are free to change.
- **Check both themes.** `/design` has a toggle; the light theme is a distinct
  palette, not an inversion, so a change can easily look right in one and wrong
  in the other.

## Verifying

```bash
cd frontend
npm run build      # CI runs this plus `tsc --noEmit`
npm run dev        # then open /design
```

The style guide renders from the same exports the app uses, so it is the fastest
way to see the effect of a token change on every primitive at once.
