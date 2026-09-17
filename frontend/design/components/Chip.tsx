import type { ReactNode } from "react";
import { Icon, type IconName } from "../icons";
import styles from "./Chip.module.css";

export type ChipProps = {
  children: ReactNode;
  icon?: IconName;
  /** A coloured dot instead of an icon — states, moods, tags. */
  dot?: boolean;
  selected?: boolean;
  href?: string;
};

export function Chip({ children, icon, dot, selected = false, href }: ChipProps) {
  const classes = [styles.chip, selected ? styles.selected : ""]
    .filter(Boolean)
    .join(" ");
  const content = (
    <>
      {icon ? <Icon name={icon} size={15} /> : null}
      {dot && !icon ? <span className={styles.dot} /> : null}
      <span>{children}</span>
    </>
  );

  return href ? (
    <a className={classes} href={href} aria-current={selected ? "true" : undefined}>
      {content}
    </a>
  ) : (
    <button className={classes} type="button" aria-pressed={selected}>
      {content}
    </button>
  );
}

/** A horizontally scrolling run of chips that bleeds past the gutter. */
export function ChipRow({ children }: { children: ReactNode }) {
  return <div className={styles.row}>{children}</div>;
}

export type SegmentedControlProps = {
  options: { value: string; label: string }[];
  value: string;
  /** Rendered as links when given — keeps the control usable without state. */
  hrefFor?: (value: string) => string;
  fill?: boolean;
};

export function SegmentedControl({
  options,
  value,
  hrefFor,
  fill = false,
}: SegmentedControlProps) {
  return (
    <div className={[styles.segmented, fill ? styles.fill : ""].filter(Boolean).join(" ")}>
      {options.map((option) => {
        const classes = [styles.segment, option.value === value ? styles.segmentOn : ""]
          .filter(Boolean)
          .join(" ");
        return hrefFor ? (
          <a key={option.value} className={classes} href={hrefFor(option.value)}>
            {option.label}
          </a>
        ) : (
          <button
            key={option.value}
            type="button"
            className={classes}
            aria-pressed={option.value === value}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

export function Badge({
  children,
  tone = "accent",
  icon,
}: {
  children: ReactNode;
  tone?: "accent" | "neutral";
  icon?: IconName;
}) {
  return (
    <span
      className={[styles.badge, tone === "neutral" ? styles.badgeNeutral : ""]
        .filter(Boolean)
        .join(" ")}
    >
      {icon ? <Icon name={icon} size={12} /> : null}
      {children}
    </span>
  );
}
