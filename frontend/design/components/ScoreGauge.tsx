"use client";

import { useId } from "react";
import type { CSSProperties, ReactNode } from "react";
import { Icon } from "../icons";
import styles from "./ScoreGauge.module.css";

export type ScoreGaugeProps = {
  /** The score itself. Computed in Python — this only draws it. */
  value: number;
  max?: number;
  label?: ReactNode;
  caption?: ReactNode;
  /** 0-3 filled markers under the number, for a coarse "how good is this". */
  rating?: number;
  /** Degrees of arc. 250 leaves the gap at the bottom where the label sits. */
  sweep?: number;
  size?: number;
  thickness?: number;
};

/**
 * The headline dial: one open arc, the number inside it, and nothing else
 * competing for the centre of the screen.
 */
export function ScoreGauge({
  value,
  max = 100,
  label,
  caption,
  rating,
  sweep = 250,
  size = 220,
  thickness = 12,
}: ScoreGaugeProps) {
  const gradientId = `${useId()}-gauge`;
  const radius = (size - thickness) / 2;
  const circumference = 2 * Math.PI * radius;
  const arc = (circumference * sweep) / 360;
  const fraction = max > 0 ? Math.min(Math.max(value / max, 0), 1) : 0;

  // A circle's dash pattern starts at 3 o'clock; rotating back by half the gap
  // plus a quarter turn puts the arc's midpoint at the top.
  const rotation = -90 - sweep / 2;
  const centre = size / 2;

  return (
    <div className={styles.wrap} style={{ width: size, height: size }}>
      <svg
        className={styles.svg}
        viewBox={`0 0 ${size} ${size}`}
        role="img"
        aria-label={`${label ? `${label}: ` : ""}${value} of ${max}`}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="1" x2="1" y2="0">
            <stop offset="0%" stopColor="var(--v-accent-deep)" />
            <stop offset="60%" stopColor="var(--v-accent)" />
            <stop offset="100%" stopColor="var(--v-accent-bright)" />
          </linearGradient>
        </defs>
        <g transform={`rotate(${rotation} ${centre} ${centre})`}>
          <circle
            className={styles.track}
            cx={centre}
            cy={centre}
            r={radius}
            fill="none"
            strokeWidth={thickness}
            strokeLinecap="round"
            strokeDasharray={`${arc} ${circumference}`}
          />
          {/*
            The lit arc draws itself from empty on mount. Written as an offset
            rather than an animated dash length because a keyframe cannot read the
            computed value: the dash is fixed at its final size and the offset —
            handed to CSS as a custom property — slides it into view.

            The transition stays for the case where the value changes in place.
          */}
          <circle
            className={styles.value}
            data-motion="draw"
            style={{ "--v-draw-from": `${arc * fraction}px` } as CSSProperties}
            cx={centre}
            cy={centre}
            r={radius}
            fill="none"
            stroke={`url(#${gradientId})`}
            strokeWidth={thickness}
            strokeLinecap="round"
            strokeDasharray={`${arc * fraction} ${circumference}`}
          />
        </g>
      </svg>

      <div className={styles.center} data-motion="settle">
        <span className={styles.number}>{value}</span>
        {label ? <span className={styles.label}>{label}</span> : null}
        {typeof rating === "number" ? (
          <span className={styles.stars} aria-label={`${rating} of 3`}>
            {[0, 1, 2].map((index) => (
              <Icon
                key={index}
                name="sparkle"
                size={11}
                variant="fill"
                className={index < rating ? undefined : styles.starOff}
              />
            ))}
          </span>
        ) : null}
        {caption ? <span className={styles.caption}>{caption}</span> : null}
      </div>
    </div>
  );
}
