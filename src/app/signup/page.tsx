import type { Metadata } from "next";
import { SignupClient } from "./signup-client";

export const metadata: Metadata = {
  title: "Create your TipGuard account",
  description:
    "Save your audit-readiness score and start the tip-credit file — state-specific notices, signed acknowledgments, and a dated export.",
  robots: { index: false, follow: true },
};

export default function SignupPage() {
  return (
    <div className="min-h-screen">
      <SignupClient />
    </div>
  );
}
