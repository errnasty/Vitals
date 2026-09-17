import type { ReactNode } from "react";
import styles from "./Hero.module.css";

export type HeroProps = {
  /** Small accent line above the greeting. */
  eyebrow?: ReactNode;
  /** The greeting itself, e.g. "Morning," / "Steve". */
  title: ReactNode;
  /** One sentence. The daily brief's opening line belongs here. */
  body?: ReactNode;
  /** Background photo URL. Without it the hero draws its own gradient cover. */
  image?: string;
  /** Top-left slot — a model badge, a date, a source chip. */
  topLeft?: ReactNode;
  /** Top-right slot — usually an IconButton. */
  topRight?: ReactNode;
  /** Full-bleed row under the copy, typically a <ChipRow />. */
  chips?: ReactNode;
  /** Bottom-right controls. */
  actions?: ReactNode;
};

/**
 * The opening screen: a full-bleed cover, a greeting, and the one sentence that
 * says how today is going. Everything measured lives below the fold on purpose.
 */
export function Hero({
  eyebrow,
  title,
  body,
  image,
  topLeft,
  topRight,
  chips,
  actions,
}: HeroProps) {
  return (
    <section className={styles.hero}>
      <div
        className={[styles.media, image ? "" : styles.placeholder].filter(Boolean).join(" ")}
        style={image ? { backgroundImage: `url(${image})` } : undefined}
      />
      <div className={styles.grain} />
      <div className={styles.scrim} />

      {topLeft || topRight ? (
        <div className={styles.top}>
          <div>{topLeft}</div>
          <div>{topRight}</div>
        </div>
      ) : null}

      <div>
        {eyebrow ? <div className={styles.eyebrow}>{eyebrow}</div> : null}
        <h1 className={styles.greeting}>{title}</h1>
        {body ? <p className={styles.body}>{body}</p> : null}
        {chips}
        {actions ? (
          <div className={styles.footer}>
            <div />
            <div className={styles.actions}>{actions}</div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
