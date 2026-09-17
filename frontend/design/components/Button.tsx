import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from "react";
import { Icon, type IconName } from "../icons";
import styles from "./Button.module.css";

type Variant = "primary" | "secondary" | "ghost" | "quiet";
type Size = "sm" | "md" | "lg";

type Common = {
  variant?: Variant;
  size?: Size;
  /** Stretch to the container width — the bottom-of-sheet call to action. */
  block?: boolean;
  icon?: IconName;
  /** Put the icon after the label instead of before it. */
  iconAfter?: boolean;
  children: ReactNode;
};

export type ButtonProps = Common &
  Omit<ButtonHTMLAttributes<HTMLButtonElement>, keyof Common | "type"> & {
    href?: undefined;
    type?: "button" | "submit" | "reset";
  };

export type ButtonLinkProps = Common &
  Omit<AnchorHTMLAttributes<HTMLAnchorElement>, keyof Common> & { href: string };

function classesFor(variant: Variant, size: Size, block: boolean, extra?: string) {
  return [styles.base, styles[variant], styles[size], block ? styles.block : "", extra]
    .filter(Boolean)
    .join(" ");
}

export function Button(props: ButtonProps | ButtonLinkProps) {
  const {
    variant = "primary",
    size = "md",
    block = false,
    icon,
    iconAfter = false,
    children,
    className,
    ...rest
  } = props as Common & { className?: string; href?: string };

  const glyph = icon ? <Icon name={icon} size={size === "lg" ? 20 : 17} /> : null;
  const content = (
    <>
      {iconAfter ? null : glyph}
      <span>{children}</span>
      {iconAfter ? glyph : null}
    </>
  );
  const classes = classesFor(variant, size, block, className);

  if (typeof rest.href === "string") {
    const { href, ...anchorRest } = rest as AnchorHTMLAttributes<HTMLAnchorElement> & {
      href: string;
    };
    return (
      <a className={classes} href={href} {...anchorRest}>
        {content}
      </a>
    );
  }

  const buttonRest = rest as ButtonHTMLAttributes<HTMLButtonElement>;
  return (
    <button className={classes} type={buttonRest.type ?? "button"} {...buttonRest}>
      {content}
    </button>
  );
}

export type IconButtonProps = {
  icon: IconName;
  /** Required: an icon-only control has no other accessible name. */
  label: string;
  tone?: "default" | "accent";
  size?: "md" | "lg";
  href?: string;
};

export function IconButton({
  icon,
  label,
  tone = "default",
  size = "md",
  href,
}: IconButtonProps) {
  const classes = [
    styles.icon,
    tone === "accent" ? styles.iconAccent : "",
    size === "lg" ? styles.iconLg : "",
  ]
    .filter(Boolean)
    .join(" ");
  const glyph = <Icon name={icon} size={size === "lg" ? 20 : 18} />;

  return href ? (
    <a className={classes} href={href} aria-label={label}>
      {glyph}
    </a>
  ) : (
    <button className={classes} type="button" aria-label={label}>
      {glyph}
    </button>
  );
}
