/**
 * The app's tab bar. Only routes that exist appear here — a tab that leads
 * nowhere is worse than a missing one.
 */

import type { NavItem } from "@/design";

export const NAV_ITEMS: NavItem[] = [
  { id: "today", label: "Today", icon: "home", href: "/" },
  { id: "trends", label: "Trends", icon: "chart", href: "/trends" },
  { id: "score", label: "Score", icon: "target", href: "/score" },
  { id: "log", label: "The day", icon: "plus", href: "/log" },
  { id: "insights", label: "Patterns", icon: "sparkle", href: "/insights" },
];

export const navFor = (active: string): NavItem[] =>
  NAV_ITEMS.map((item) => ({ ...item, active: item.id === active }));
