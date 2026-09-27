/**
 * The app's tab bar. Only routes that exist appear here — a tab that leads
 * nowhere is worse than a missing one.
 *
 * Five is the ceiling. Patterns is deliberately not a tab: it is the evidence
 * behind the coach's ranking rather than a separate destination, so it is reached
 * from Coach and lights the Coach tab while you are on it. A sixth tab at phone
 * width makes every label unreadable to gain one tap.
 */

import type { NavItem } from "@/design";

export const NAV_ITEMS: NavItem[] = [
  { id: "today", label: "Today", icon: "home", href: "/" },
  { id: "trends", label: "Trends", icon: "chart", href: "/trends" },
  { id: "score", label: "Score", icon: "target", href: "/score" },
  { id: "coach", label: "Coach", icon: "bolt", href: "/coach" },
  { id: "log", label: "The day", icon: "plus", href: "/log" },
];

export const navFor = (active: string): NavItem[] =>
  NAV_ITEMS.map((item) => ({ ...item, active: item.id === active }));
