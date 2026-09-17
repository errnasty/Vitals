/**
 * The design system's public surface.
 *
 * App code imports from `@/design` and nothing deeper. That single import path
 * is the whole contract: components can be split, renamed or restyled inside
 * this directory without touching a line of feature code.
 */

export { AppShell, Gutter, Stack, Grid2 } from "./components/AppShell";
export type { AppShellProps } from "./components/AppShell";

export { TopBar } from "./components/TopBar";
export type { TopBarProps } from "./components/TopBar";

export { BottomNav, NavAction } from "./components/BottomNav";
export type { BottomNavProps, NavActionProps, NavItem } from "./components/BottomNav";

export { Card, CardHeader, SectionHeader, ListRow } from "./components/Card";
export type {
  CardProps,
  CardHeaderProps,
  SectionHeaderProps,
  ListRowProps,
} from "./components/Card";

export { Button, IconButton } from "./components/Button";
export type { ButtonProps, ButtonLinkProps, IconButtonProps } from "./components/Button";

export { Chip, ChipRow, SegmentedControl, Badge } from "./components/Chip";
export type { ChipProps, SegmentedControlProps } from "./components/Chip";

export { Stat, Delta, StatGroup } from "./components/Stat";
export type { StatProps, DeltaProps } from "./components/Stat";

export { ScoreGauge } from "./components/ScoreGauge";
export type { ScoreGaugeProps } from "./components/ScoreGauge";

export { ProgressRing } from "./components/ProgressRing";
export type { ProgressRingProps } from "./components/ProgressRing";

export { BarSeries, Sparkline } from "./components/BarSeries";
export type { Bar, BarSeriesProps, SparklineProps } from "./components/BarSeries";

export { RouteMap } from "./components/RouteMap";
export type { RouteMapProps, RouteLabel } from "./components/RouteMap";

export { Hero } from "./components/Hero";
export type { HeroProps } from "./components/Hero";

export { ThemeToggle } from "./components/ThemeToggle";
export {
  THEME_INIT_SCRIPT,
  THEME_COLOR,
  THEME_STORAGE_KEY,
  resolveColorScheme,
  setColorScheme,
  clearColorScheme,
} from "./color-scheme";
export type { ColorScheme } from "./color-scheme";

export { Icon, iconNames } from "./icons";
export type { IconName, IconProps } from "./icons";

export { seriesVar, seriesVars, toneVar } from "./tokens";
export type { Tone } from "./tokens";
