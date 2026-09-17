import type { ReactNode } from "react";
import styles from "./ProgressRing.module.css";

export type ProgressRingProps = {
  value: number;
  max?: number;
  size?: number;
  thickness?: number;
  /** Drawn in the hole. Falls back to the rounded percentage. */
  children?: ReactNode;
  label?: string;
};

/** A closed ring, for a goal that is genuinely "x of y". */
export function ProgressRing({
  value,
  max = 100,
  size = 64,
  thickness = 6,
  children,
  label,
}: ProgressRingProps) {
  const radius = (size - thickness) / 2;
  const circumference = 2 * Math.PI * radius;
  const fraction = max > 0 ? Math.min(Math.max(value / max, 0), 1) : 0;
  const centre = size / 2;

  return (
    <div className={styles.wrap} style={{ width: size, height: size }}>
      <svg
        className={styles.svg}
        width={size}
        height={size}
        role="img"
        aria-label={label ?? `${Math.round(fraction * 100)} percent`}
      >
        <circle
          className={styles.track}
          cx={centre}
          cy={centre}
          r={radius}
          fill="none"
          strokeWidth={thickness}
        />
        <circle
          className={styles.value}
          cx={centre}
          cy={centre}
          r={radius}
          fill="none"
          strokeWidth={thickness}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - fraction)}
        />
      </svg>
      <div className={styles.center} style={{ fontSize: Math.max(11, size * 0.22) }}>
        {children ?? <span className={styles.number}>{Math.round(fraction * 100)}</span>}
      </div>
    </div>
  );
}
