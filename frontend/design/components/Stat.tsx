import type { ReactNode } from "react";
import { Icon, type IconName } from "../icons";
import styles from "./Stat.module.css";

export type StatProps = {
  label?: ReactNode;
  /** Pre-formatted. Python does the arithmetic; the UI only renders. */
  value: ReactNode;
  unit?: ReactNode;
  /** The "/ 1750 kcal" goal shown beside the value. */
  target?: ReactNode;
  caption?: ReactNode;
  icon?: IconName;
  size?: "xs" | "sm" | "md" | "lg";
  accent?: boolean;
  /** Put the label under the number instead of over it. */
  labelBelow?: boolean;
};

/**
 * A labelled number. Every headline figure in the app is one of these, which is
 * what keeps digits aligned and units consistent across screens.
 */
export function Stat({
  label,
  value,
  unit,
  target,
  caption,
  icon,
  size = "md",
  accent = false,
  labelBelow = false,
}: StatProps) {
  return (
    <div
      className={[
        styles.stat,
        styles[size],
        accent ? styles.accent : "",
        labelBelow ? styles.below : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {label ? (
        <div className={styles.label}>
          {icon ? <Icon name={icon} size={13} className={styles.labelIcon} /> : null}
          <span>{label}</span>
        </div>
      ) : null}
      <div className={styles.value}>
        <span className={styles.number}>{value}</span>
        {unit ? <span className={styles.unit}>{unit}</span> : null}
        {target ? <span className={styles.target}>/ {target}</span> : null}
      </div>
      {caption ? <div className={styles.caption}>{caption}</div> : null}
    </div>
  );
}

export type DeltaProps = {
  /** Sign decides the arrow; the caller decides whether up is good. */
  value: ReactNode;
  direction: "up" | "down" | "flat";
  /** Set when a rise is the bad outcome — resting HR, body fat, load ramp. */
  invert?: boolean;
};

export function Delta({ value, direction, invert = false }: DeltaProps) {
  const good = invert ? direction === "down" : direction === "up";
  const tone = direction === "flat" ? styles.flat : good ? styles.up : styles.down;

  return (
    <span className={[styles.delta, tone].join(" ")}>
      {direction === "flat" ? null : (
        <Icon name={direction === "up" ? "arrowUp" : "arrowDown"} size={13} />
      )}
      {value}
    </span>
  );
}

/** Two or three stats across a card, optionally hairline-divided. */
export function StatGroup({
  children,
  divided = false,
}: {
  children: ReactNode;
  divided?: boolean;
}) {
  return (
    <div className={[styles.group, divided ? styles.divided : ""].filter(Boolean).join(" ")}>
      {children}
    </div>
  );
}
