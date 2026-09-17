/**
 * The small amount of presentation the API deliberately does not decide.
 *
 * Icon names belong to the design system, and which icon stands for "sleep" is a
 * choice about this app's screens rather than about its data — so the API stays
 * design-agnostic and the mapping lives here. Same for the date in the title bar:
 * it is the viewer's locale, not the server's.
 *
 * There is no arithmetic in this file, and there should never be any.
 */

import type { IconName } from "@/design";

const PILLAR_ICONS: Record<string, IconName> = {
  recovery: "bolt",
  sleep: "moon",
  training: "run",
  longevity: "heart",
};

const HEADLINE_ICONS: Record<string, IconName> = {
  sleep: "moon",
  resting_hr: "heart",
  body: "scale",
  fitness: "flame",
};

export const pillarIcon = (name: string): IconName => PILLAR_ICONS[name] ?? "target";
export const headlineIcon = (key: string): IconName => HEADLINE_ICONS[key] ?? "pulse";

/** `2026-08-21` → `Friday, 21 August`. Parsed as a plain date, never as an instant. */
export function longDate(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
    timeZone: "UTC",
  });
}

/** `2026-08-21` → `21 Aug`, for axis ends where the full date would not fit. */
export function shortDate(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}
