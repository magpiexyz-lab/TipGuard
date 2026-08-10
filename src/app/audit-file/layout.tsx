import type { Metadata } from "next";

const title = "Audit File — Your Tip-Credit Record | TipGuard";
const description =
  "Every signed tip-credit notice with signer, timestamp, and frozen text, plus the cover index of employees, notice status, and state rule version.";

export const metadata: Metadata = {
  title,
  description,
  // Owner-scoped compliance records — never indexable.
  robots: { index: false, follow: false },
};

export default function AuditFileLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return children;
}
