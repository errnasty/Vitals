/**
 * A typed mirror of the tokens that TypeScript genuinely needs — chart series
 * that get indexed, and the swatch lists the style guide renders.
 *
 * CSS is still the source of truth. Anything drawn in the DOM (SVG included)
 * should reference `var(--v-accent)` directly; reach for this file only when a
 * value has to be picked in JavaScript.
 */

export const seriesVars = [
  "var(--v-series-1)",
  "var(--v-series-2)",
  "var(--v-series-3)",
  "var(--v-series-4)",
  "var(--v-series-5)",
] as const;

/** Series colour for an index, wrapping rather than running out. */
export function seriesVar(index: number): string {
  return seriesVars[index % seriesVars.length];
}

/** Token groups, used by the style guide to render itself from the tokens. */
export const tokenGroups = {
  surface: ["--v-bg", "--v-surface-1", "--v-surface-2", "--v-surface-3"],
  text: ["--v-text", "--v-text-dim", "--v-text-faint"],
  accent: ["--v-accent-deep", "--v-accent", "--v-accent-bright"],
  semantic: ["--v-ok", "--v-warn", "--v-bad", "--v-info"],
  series: ["--v-series-1", "--v-series-2", "--v-series-3", "--v-series-4", "--v-series-5"],
} as const;

export const radii = [
  "--v-r-xs",
  "--v-r-sm",
  "--v-r-md",
  "--v-r-lg",
  "--v-r-xl",
  "--v-r-2xl",
] as const;

export const typeScale = [
  { token: "--v-t-display", label: "display", sample: "40:28" },
  { token: "--v-t-h1", label: "h1", sample: "Morning" },
  { token: "--v-t-h2", label: "h2", sample: "Current State" },
  { token: "--v-t-h3", label: "h3", sample: "Section title" },
  { token: "--v-t-body", label: "body", sample: "Body copy" },
  { token: "--v-t-sm", label: "small", sample: "Supporting detail" },
  { token: "--v-t-xs", label: "label", sample: "LABEL" },
] as const;

/** Tone drives accent vs. muted treatment across every primitive. */
export type Tone = "accent" | "neutral" | "ok" | "warn" | "bad" | "info";

export const toneVar: Record<Tone, string> = {
  accent: "var(--v-accent)",
  neutral: "var(--v-text)",
  ok: "var(--v-ok)",
  warn: "var(--v-warn)",
  bad: "var(--v-bad)",
  info: "var(--v-info)",
};
