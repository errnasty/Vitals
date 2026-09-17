import type { ReactNode } from "react";
import styles from "./AppShell.module.css";

export type AppShellProps = {
  /** Rendered above the scrolling body — typically <TopBar />. */
  header?: ReactNode;
  /** Rendered floating over the body — typically <BottomNav />. */
  nav?: ReactNode;
  children: ReactNode;
};

/**
 * The frame every screen sits in: a centred phone-width column, a fixed header
 * slot, a scrolling body that clears the floating nav, and the nav itself.
 */
export function AppShell({ header, nav, children }: AppShellProps) {
  return (
    <div className={styles.shell}>
      {header}
      <div className={[styles.body, nav ? "" : styles.noNav].filter(Boolean).join(" ")}>
        {children}
      </div>
      {nav}
    </div>
  );
}

/** Horizontal page gutter. Wrap anything that should not be full-bleed. */
export function Gutter({ children }: { children: ReactNode }) {
  return <div className={styles.gutter}>{children}</div>;
}

/** Vertical rhythm for a run of cards. */
export function Stack({ children }: { children: ReactNode }) {
  return <div className={styles.stack}>{children}</div>;
}

/** The two-up tile row used for paired metrics. */
export function Grid2({ children }: { children: ReactNode }) {
  return <div className={styles.grid2}>{children}</div>;
}
