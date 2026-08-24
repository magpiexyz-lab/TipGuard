import type { Metadata } from "next";

// Server component wrapper: page.tsx is a client component (the questionnaire is
// entirely interactive) and therefore cannot export `metadata` itself.
// `/score` is the public entry hook, so it gets its own indexable title.

export const metadata: Metadata = {
  title: "Free Tip-Credit Audit-Readiness Score | TipGuard",
  description:
    "Answer seven questions about how you run tipped pay and get a 0-100 audit-readiness score, a ranked list of your tip-credit gaps, and an estimated back-pay exposure range. Free with a TipGuard account.",
  openGraph: {
    title: "Free Tip-Credit Audit-Readiness Score | TipGuard",
    description:
      "Score your restaurant against the items a wage-and-hour investigator opens with: signed notices, tip-pool composition, overtime basis, and new-hire process.",
  },
};

export default function ScoreLayout({ children }: { children: React.ReactNode }) {
  return children;
}
