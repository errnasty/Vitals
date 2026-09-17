"use client";

import { useEffect, useState } from "react";
import { Icon } from "../icons";
import { resolveColorScheme, setColorScheme, type ColorScheme } from "../color-scheme";
import styles from "./Button.module.css";

/**
 * Switches between the two palettes and remembers the choice.
 *
 * Renders nothing until it has read the live theme: the server cannot know
 * which one the browser resolved, and guessing would show the wrong icon for a
 * frame on every load.
 */
export function ThemeToggle({ size = "md" }: { size?: "md" | "lg" }) {
  const [scheme, setScheme] = useState<ColorScheme | null>(null);

  useEffect(() => {
    setScheme(resolveColorScheme());
  }, []);

  const next: ColorScheme = scheme === "light" ? "dark" : "light";
  const classes = [styles.icon, size === "lg" ? styles.iconLg : ""]
    .filter(Boolean)
    .join(" ");

  return (
    <button
      type="button"
      className={classes}
      aria-label={scheme ? `Switch to ${next} mode` : "Switch colour theme"}
      onClick={() => {
        setColorScheme(next);
        setScheme(next);
      }}
    >
      {/* aria-hidden on the icon; the button carries the label. */}
      <span style={{ opacity: scheme ? 1 : 0, transition: "opacity var(--v-dur)" }}>
        <Icon name={scheme === "light" ? "moon" : "sun"} size={size === "lg" ? 20 : 18} />
      </span>
    </button>
  );
}
