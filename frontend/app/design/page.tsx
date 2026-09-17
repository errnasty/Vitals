import type { Metadata } from "next";
import { StyleGuide } from "@/design/preview/StyleGuide";

export const metadata: Metadata = {
  title: "Vitals — design system",
  description: "Tokens, primitives and reference screens for the Vitals UI",
};

/**
 * The design system, rendered from the same exports the app uses. Kept out of
 * the sitemap: it is a working reference, not a page of the product.
 */
export default function DesignPage() {
  return <StyleGuide />;
}
