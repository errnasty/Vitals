import type { ReactNode } from "react";
import styles from "./PhoneFrame.module.css";

/**
 * A device bezel for the style guide. Preview furniture only — the app itself
 * never renders inside one.
 */
export function PhoneFrame({
  children,
  caption,
}: {
  children: ReactNode;
  caption?: string;
}) {
  return (
    <div className={styles.item}>
      <div className={styles.frame}>
        <div className={styles.notch} />
        <div className={styles.screen}>{children}</div>
      </div>
      {caption ? <div className={styles.caption}>{caption}</div> : null}
    </div>
  );
}
