import type { ReactNode } from "react";
import { Icon, type IconName } from "../icons";
import styles from "./BottomNav.module.css";

export type NavItem = {
  id: string;
  label: string;
  icon: IconName;
  href?: string;
  active?: boolean;
};

export type BottomNavProps = {
  items: NavItem[];
  /** The one primary action, drawn as the accent circle beside the pill. */
  action?: ReactNode;
};

/**
 * The tab bar. Items render as links when given an `href` and as buttons
 * otherwise, so the same component works before and after routing exists.
 */
export function BottomNav({ items, action }: BottomNavProps) {
  return (
    <nav className={styles.wrap} aria-label="Primary">
      <div className={styles.pill}>
        {items.map((item) => {
          const className = [styles.item, item.active ? styles.active : ""]
            .filter(Boolean)
            .join(" ");
          const content = (
            <>
              <Icon name={item.icon} size={20} />
              <span className={styles.label}>{item.label}</span>
            </>
          );

          return item.href ? (
            <a
              key={item.id}
              href={item.href}
              className={className}
              aria-current={item.active ? "page" : undefined}
            >
              {content}
            </a>
          ) : (
            <button
              key={item.id}
              type="button"
              className={className}
              aria-current={item.active ? "page" : undefined}
            >
              {content}
            </button>
          );
        })}
      </div>
      {action}
    </nav>
  );
}

export type NavActionProps = {
  icon?: IconName;
  label: string;
  href?: string;
};

/** The accent circle beside the tab pill. */
export function NavAction({ icon = "play", label, href }: NavActionProps) {
  const content = <Icon name={icon} size={22} />;
  return href ? (
    <a className={styles.action} href={href} aria-label={label}>
      {content}
    </a>
  ) : (
    <button type="button" className={styles.action} aria-label={label}>
      {content}
    </button>
  );
}
