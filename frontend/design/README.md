# Vitals design system

Everything about how the app looks lives in this directory. Nothing about what
it does lives here.

That split is the point. Feature work (phases 3-12) lands in `backend/` and
`frontend/app/`; design work lands here. The two touch each other through one
import path and one line of CSS, so a design change and a feature branch can
land in either order without meeting in the same hunk.

## The contract

| Rule | Why |
|---|---|
| App code imports from `@/design`, never a deeper path | The internals can be renamed, split or rewritten without a single change outside this directory |
| No colour, radius, duration or type size outside `tokens.css` | Retheming is editing one file |
| No data fetching, routing, auth or business logic in here | A component that knows where its numbers come from cannot be restyled independently |
| Components take formatted values, never raw records | Python does the arithmetic (see the root README); these only draw |
| `app/globals.css` stays one `@import` line | Design and feature branches never both edit a stylesheet |

The app's entire design surface is three files:

```
frontend/app/globals.css   @import "../design/theme.css";  <- one line
frontend/app/layout.tsx    theme-color + the pre-paint theme script
frontend/app/design/page.tsx  renders <StyleGuide />
```

Everything else is `frontend/design/**`.

## Layout

```
theme.css        the single stylesheet the app loads (imports the three below)
fonts.css        @font-face for Source Serif 4, self-hosted
tokens.css       every colour, radius, space, type size, duration - both themes
base.css         resets and element defaults
tokens.ts        the few token values TypeScript needs (chart series, the guide)
color-scheme.ts  theme resolution, persistence, and the pre-paint script
icons.tsx        the icon set - components take a name, never an imported SVG
index.ts         the public surface; app code imports from here and nowhere else
components/      primitives, each with a co-located CSS module
preview/         the style guide and three reference screens (not shipped UI)
fonts/           the committed woff2 files
```

## Themes

Two palettes, one definition. Every themed value is written once in
`tokens.css` as `light-dark(<light>, <dark>)`.

Light is **not** an inversion of dark. The lime accent that carries the dark
theme is unreadable on white (about 1.2:1), so the light theme takes a deep
green of the same family. Every text colour in both themes clears WCAG AA
against its own canvas and its own card surface:

| | Dark | Light |
|---|---|---|
| Canvas | `#090a09` | `#f6f7f2` |
| Accent | `#c9f73f` lime | `#3d7a12` deep green |
| Accent contrast | 15.9:1 on canvas | 4.9:1 on canvas, 5.3:1 white-on-accent |
| Body text | 17.8:1 | 16.3:1 |
| Faint labels | 5.1:1 | 4.7:1 |

Which theme applies:

1. `data-theme="light"` or `"dark"` on `<html>` wins, whatever the OS says.
   It sets `color-scheme`, which is what `light-dark()` actually reads.
2. Otherwise the OS preference.
3. Otherwise dark — including on any browser without `light-dark()`, which
   gets the plain dark values from the fallback block.

`<ThemeToggle />` writes the override and remembers it; `THEME_INIT_SCRIPT`
(inlined in `layout.tsx`) applies the remembered choice before first paint so a
light-mode user never sees a frame of the dark canvas.

## Type

Source Serif 4, self-hosted from `fonts/`. A transitional serif in the Times
New Roman lineage, drawn for screens. Two properties earned it the slot over
Times itself:

- **Tabular figures** (`tnum`). Most of this UI is numbers, and `base.css` asks
  for tabular digits; a face without them ignores that silently and readouts
  jitter as values change.
- **An optical-size axis.** Sturdier stems on the 10px uppercase labels, finer
  ones on the 52px readouts — the difference between a serif that survives at
  label sizes and one that goes to mush.

The files are committed rather than fetched by `next/font/google`, so a build
never depends on reaching Google, and the face is part of the template like
everything else.

`--v-font` and `--v-font-display` are separate tokens. Pointing the display one
at another face, or the small uppercase labels back at a sans, is a one-line
change.

## The style guide

`/design` renders the tokens, every primitive, and three reference screens,
from the same exports the app uses — so it cannot drift. If a component
changes, that page changes with it.

```bash
cd frontend && npm run dev   # then open /design
```

## Adding a component

1. `components/Thing.tsx` + `components/Thing.module.css`.
2. Style only with `var(--v-*)`. If you need a value that does not exist, add a
   token — do not inline it.
3. Export it from `index.ts`.
4. Add it to `preview/StyleGuide.tsx` so it is visible and reviewable.

Components stay server-renderable unless they genuinely need a hook;
`ScoreGauge` and `ThemeToggle` are the only two that do.
