import type { ReactNode } from "react";
import { Icon, type IconName } from "../icons";
import styles from "./Card.module.css";

export type CardProps = {
  /** `accent` tints the card with the lime wash; `glass` floats it over media. */
  variant?: "solid" | "glass" | "accent" | "flat";
  padding?: "sm" | "md" | "lg";
  /** Render as a link/button with the pressed-state affordance. */
  href?: string;
  className?: string;
  children: ReactNode;
};

const padClass = { sm: styles["pad-sm"], md: "", lg: styles["pad-lg"] } as const;

export function Card({
  variant = "solid",
  padding = "md",
  href,
  className,
  children,
}: CardProps) {
  const variantClass =
    variant === "glass"
      ? styles.glass
      : variant === "accent"
        ? styles.accent
        : variant === "flat"
          ? styles.flat
          : "";

  const classes = [
    styles.card,
    variantClass,
    padClass[padding],
    href ? styles.interactive : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  if (href) {
    return (
      <a className={classes} href={href}>
        {children}
      </a>
    );
  }
  return <div className={classes}>{children}</div>;
}

export type CardHeaderProps = {
  title: ReactNode;
  subtitle?: ReactNode;
  icon?: IconName;
  action?: ReactNode;
};

export function CardHeader({ title, subtitle, icon, action }: CardHeaderProps) {
  return (
    <div className={styles.header}>
      {icon ? (
        <span className={styles.headerIcon}>
          <Icon name={icon} size={15} />
        </span>
      ) : null}
      <div className={styles.headerText}>
        <div className={styles.headerTitle}>{title}</div>
        {subtitle ? <div className={styles.headerSub}>{subtitle}</div> : null}
      </div>
      {action}
    </div>
  );
}

export type SectionHeaderProps = {
  title: ReactNode;
  action?: ReactNode;
  actionHref?: string;
};

/** The uppercase label that separates runs of cards. */
export function SectionHeader({ title, action, actionHref }: SectionHeaderProps) {
  return (
    <div className={styles.section}>
      <h2 className={styles.sectionTitle}>{title}</h2>
      {action ? (
        actionHref ? (
          <a className={styles.sectionAction} href={actionHref}>
            {action}
          </a>
        ) : (
          <span className={styles.sectionAction}>{action}</span>
        )
      ) : null}
    </div>
  );
}

export type ListRowProps = {
  label: ReactNode;
  meta?: ReactNode;
  value?: ReactNode;
  icon?: IconName;
  href?: string;
  /** Show the disclosure chevron. Implied by `href`. */
  chevron?: boolean;
};

export function ListRow({ label, meta, value, icon, href, chevron }: ListRowProps) {
  const showChevron = chevron ?? Boolean(href);
  const content = (
    <>
      {icon ? (
        <span className={styles.rowIcon}>
          <Icon name={icon} size={17} />
        </span>
      ) : null}
      <span className={styles.rowBody}>
        <span className={styles.rowLabel}>{label}</span>
        {meta ? <span className={styles.rowMeta}>{meta}</span> : null}
      </span>
      {value ? <span className={styles.rowValue}>{value}</span> : null}
      {showChevron ? (
        <Icon name="chevronRight" size={16} className={styles.rowChevron} />
      ) : null}
    </>
  );

  return href ? (
    <a className={styles.row} href={href}>
      {content}
    </a>
  ) : (
    <div className={styles.row}>{content}</div>
  );
}
