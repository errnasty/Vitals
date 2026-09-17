/**
 * Theme resolution.
 *
 * `data-theme` on <html> is the override; without it the OS preference decides
 * and dark is the fallback. The tokens implement all three cases in CSS — this
 * module only handles the part CSS cannot do: remembering a choice.
 */

export type ColorScheme = "light" | "dark";

export const THEME_STORAGE_KEY = "vitals-theme";

/** The canvas colour per theme, mirrored from tokens.css for <meta theme-color>. */
export const THEME_COLOR: Record<ColorScheme, string> = {
  light: "#f6f7f2",
  dark: "#090a09",
};

/**
 * Runs in <head> before first paint. Without it a stored light preference would
 * flash the dark canvas on every navigation, which is worse than no toggle.
 *
 * Deliberately tiny and dependency-free: it is inlined into the HTML.
 */
export const THEME_INIT_SCRIPT = `(function(){try{var t=localStorage.getItem(${JSON.stringify(
  THEME_STORAGE_KEY,
)});if(t==="light"||t==="dark"){document.documentElement.dataset.theme=t}}catch(e){}})()`;

/** What the page is actually showing right now. Browser only. */
export function resolveColorScheme(): ColorScheme {
  const override = document.documentElement.dataset.theme;
  if (override === "light" || override === "dark") return override;
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

/** Apply a theme, remember it, and keep the browser chrome in step. */
export function setColorScheme(scheme: ColorScheme): void {
  document.documentElement.dataset.theme = scheme;
  try {
    localStorage.setItem(THEME_STORAGE_KEY, scheme);
  } catch {
    // Private mode or blocked storage: the choice still applies to this page.
  }
  const meta = document.querySelector('meta[name="theme-color"]:not([media])');
  if (meta) meta.setAttribute("content", THEME_COLOR[scheme]);
}

/** Forget the choice and follow the operating system again. */
export function clearColorScheme(): void {
  delete document.documentElement.dataset.theme;
  try {
    localStorage.removeItem(THEME_STORAGE_KEY);
  } catch {
    // Nothing to forget.
  }
}
