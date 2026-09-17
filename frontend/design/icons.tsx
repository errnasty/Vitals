/**
 * The icon set. Stroke-drawn on a 24-unit grid, inheriting `currentColor` and
 * sizing from the `size` prop, so an icon never needs its own colour rule.
 *
 * Adding one means adding a path here — components take an icon *name*, never
 * an imported SVG, so the set stays enumerable and the style guide can render
 * all of it without a manifest to keep in sync.
 */

import type { SVGProps } from "react";

const paths = {
  home: "M4 10.2 12 4l8 6.2V19a1 1 0 0 1-1 1h-4v-5h-6v5H5a1 1 0 0 1-1-1z",
  pulse: "M3 12h3.5l2-5.5 3.5 11 2.5-7 1.5 1.5H21",
  chart: "M4 20V9m5 11V4m5 16v-7m5 7V8",
  calendar:
    "M4 8h16M7 4v3m10-3v3M5 8h14a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z",
  user: "M5 20a7 7 0 0 1 14 0M12 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z",
  play: "M8.5 5.5 18 12l-9.5 6.5z",
  pause: "M9 5v14M15 5v14",
  heart: "M12 20s-7.5-4.6-7.5-9.4A4.1 4.1 0 0 1 12 8a4.1 4.1 0 0 1 7.5 2.6C19.5 15.4 12 20 12 20z",
  flame: "M12 21c3.3 0 5.5-2.2 5.5-5.2 0-3.9-4-5.3-3.2-9.8-2.6 1-4.2 3.2-4.2 5.2 0 1.3.5 2 .5 2.7 0 1-.8 1.6-1.6 1.6-1 0-1.7-.8-1.9-1.9-.7 1-1.1 2.2-1.1 3.4C6 18.8 8.4 21 12 21z",
  moon: "M20 14.5A8.2 8.2 0 0 1 9.5 4 8.3 8.3 0 1 0 20 14.5z",
  sun: "M12 16.5a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9zM12 2.5v2m0 15v2M4.2 4.2l1.4 1.4m12.8 12.8 1.4 1.4M2.5 12h2m15 0h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
  dumbbell: "M6.5 8.5v7M3.5 10v4m14-5.5v7m3-5.5v4M6.5 12h11",
  run: "M13.5 5.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM8 21l3-5-2.5-3 1-5.5 3 2 3 1M6 10l2.5-2.5M11.5 16l3.5 1.5 1 3.5",
  share: "M12 15V4m0 0L8.5 7.5M12 4l3.5 3.5M5 14v5a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-5",
  chevronRight: "m10 6 6 6-6 6",
  chevronLeft: "m14 6-6 6 6 6",
  chevronDown: "m6 10 6 6 6-6",
  plus: "M12 5v14M5 12h14",
  grid: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",
  bolt: "M13 3 5 13.5h6L10.5 21 19 10.5h-6z",
  clock: "M12 7v5l3.5 2M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z",
  target: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zm0-4.5a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9zM12 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2z",
  sparkle: "M12 3.5 13.8 9 19 10.8 13.8 12.6 12 18l-1.8-5.4L5 10.8 10.2 9zM18.5 16l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z",
  check: "m5 12.5 4.5 4.5L19 7.5",
  arrowUp: "M12 19V5m0 0-6 6m6-6 6 6",
  arrowDown: "M12 5v14m0 0 6-6m-6 6-6-6",
  scale: "M12 4v16M7 8h10M6 20h12M9 8l-3 6a3 3 0 0 0 6 0zM15 8l-3 6a3 3 0 0 0 6 0z",
  drop: "M12 21a6 6 0 0 0 6-6c0-4-6-11-6-11S6 11 6 15a6 6 0 0 0 6 6z",
  lungs: "M12 4v9M8.5 9C6.5 9.8 5 12 5 15v3a2 2 0 0 0 2.6 1.9L10 19V9.6zm7 0c2 .8 3.5 3 3.5 6v3a2 2 0 0 1-2.6 1.9L14 19V9.6z",
  map: "M9 4 3.5 6.2V20L9 17.8m0-13.8 6 2.2m-6-2.2v13.8m6-11.6 5.5-2.2V17.8L15 20m0-13.8V20m-6-2.2L15 20",
  settings:
    "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm8-3a8 8 0 0 0-.2-1.7l2-1.5-2-3.4-2.3 1a8 8 0 0 0-3-1.7L14 2h-4l-.5 2.7a8 8 0 0 0-3 1.7l-2.3-1-2 3.4 2 1.5a8 8 0 0 0 0 3.4l-2 1.5 2 3.4 2.3-1a8 8 0 0 0 3 1.7L10 22h4l.5-2.7a8 8 0 0 0 3-1.7l2.3 1 2-3.4-2-1.5c.1-.5.2-1.1.2-1.7z",
} as const;

/** Every icon this design system draws. */
export type IconName = keyof typeof paths;

export const iconNames = Object.keys(paths) as IconName[];

/** Icons that read better filled than stroked. */
const filled = new Set<IconName>(["play", "bolt", "grid"]);

export type IconProps = Omit<SVGProps<SVGSVGElement>, "name"> & {
  name: IconName;
  size?: number | string;
  /** Force fill/stroke rendering when the default for the glyph is wrong. */
  variant?: "stroke" | "fill";
};

export function Icon({ name, size = 20, variant, ...rest }: IconProps) {
  const isFilled = variant ? variant === "fill" : filled.has(name);

  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill={isFilled ? "currentColor" : "none"}
      stroke={isFilled ? "none" : "currentColor"}
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      <path d={paths[name]} />
    </svg>
  );
}
