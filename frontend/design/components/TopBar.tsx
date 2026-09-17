import type { ReactNode } from "react";
import styles from "./TopBar.module.css";

export type TopBarProps = {
  title?: ReactNode;
  /** Small uppercase line above the title — a date, a source, a context. */
  eyebrow?: ReactNode;
  left?: ReactNode;
  right?: ReactNode;
  /** Centre the title and shrink it — the detail-screen treatment. */
  centered?: boolean;
  /** Drop the background so a hero image shows through. */
  transparent?: boolean;
};

export function TopBar({
  title,
  eyebrow,
  left,
  right,
  centered = false,
  transparent = false,
}: TopBarProps) {
  const className = [
    styles.bar,
    centered ? styles.centered : "",
    transparent ? styles.transparent : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <header className={className}>
      <div className={styles.side}>{left}</div>
      <div className={styles.title}>
        {eyebrow ? <span className={styles.eyebrow}>{eyebrow}</span> : null}
        {title}
      </div>
      <div className={styles.side}>{right}</div>
    </header>
  );
}
