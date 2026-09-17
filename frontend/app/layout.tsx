import type { Metadata, Viewport } from "next";
import { THEME_COLOR, THEME_INIT_SCRIPT } from "@/design";
import "./globals.css";

export const metadata: Metadata = {
  title: "Vitals",
  description: "Analytical all-in-one health platform",
  manifest: "/manifest.webmanifest",
};

export const viewport: Viewport = {
  // Follows the OS by default; ThemeToggle rewrites the unmediated tag when a
  // theme is chosen explicitly.
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: THEME_COLOR.light },
    { media: "(prefers-color-scheme: dark)", color: THEME_COLOR.dark },
  ],
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        {/* Applies a remembered theme before first paint, so a light-mode user
            never sees a frame of the dark canvas. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
        <meta name="theme-color" content={THEME_COLOR.dark} />
      </head>
      <body>{children}</body>
    </html>
  );
}
