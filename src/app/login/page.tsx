import { Suspense } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { FileSignature } from "lucide-react";
import { LoginForm } from "./login-form";

export const metadata: Metadata = {
  title: "Log in to TipGuard",
  description:
    "Sign in to your tip-credit compliance file — notices, signed acknowledgments, open findings, and your audit export.",
  robots: { index: false, follow: true },
};

export default function LoginPage() {
  return (
    <div className="texture-rule min-h-screen">
      <div className="mx-auto w-full max-w-[26rem] px-6 py-16 sm:py-24">
        <p className="eyebrow">Returning operator</p>
        <h1 className="mt-5 font-display text-4xl leading-[1.04] tracking-[-2px]">
          Open your file
        </h1>
        <p className="mt-4 text-lg leading-[1.55] text-muted-foreground">
          Pick up where your compliance file left off &mdash; notices, signatures,
          and open findings.
        </p>

        <div className="mt-10">
          <Suspense fallback={<LoginFormSkeleton />}>
            <LoginForm />
          </Suspense>
        </div>

        {/* Employees who received a tokenized signing email routinely land here
            looking for an account they were never given one for. b-07 signing
            is token-authorised, not session-authorised. */}
        <section
          aria-labelledby="employee-signing-heading"
          className="mt-14 border-t border-border pt-8"
        >
          <span className="inline-flex h-11 w-11 items-center justify-center rounded-full bg-brass/15">
            <FileSignature className="h-5 w-5 text-brass-deep" aria-hidden="true" />
          </span>
          <h2
            id="employee-signing-heading"
            className="mt-4 font-display text-xl leading-[1.15] tracking-[-1.2px]"
          >
            Signing a notice, not managing one?
          </h2>
          <p className="mt-3 text-sm leading-[1.55] text-muted-foreground">
            Employees do not need a TipGuard account. Open the signing link in the
            email your employer sent &mdash; it carries its own single-use token and
            takes you straight to the notice text you are acknowledging.
          </p>
          <p className="mt-3 font-mono text-[11px] uppercase tracking-[0.14em] text-brass-deep">
            No link? Ask your employer to resend it
          </p>
        </section>

        <p className="mt-10 text-sm text-muted-foreground">
          Ready to start a file instead?{" "}
          <Link
            href="/signup"
            className="font-medium text-foreground underline decoration-brass decoration-2 underline-offset-4 transition-colors duration-[140ms] hover:text-brass-deep"
          >
            Create an account
          </Link>
        </p>
      </div>
    </div>
  );
}

/** Ruled skeleton on the 32px ledger rhythm — holds layout during hydration. */
function LoginFormSkeleton() {
  return (
    <>
      <p className="sr-only">Loading the sign-in form</p>
      <div aria-hidden="true" className="animate-pulse">
        <div className="h-4 w-16 rounded-sm bg-muted" />
        <div className="mt-2 h-11 w-full rounded-md bg-muted" />
        <div className="mt-5 h-4 w-24 rounded-sm bg-muted" />
        <div className="mt-2 h-11 w-full rounded-md bg-muted" />
        <div className="mt-6 h-11 w-full rounded-full bg-muted" />
        <div className="mt-7 h-px w-full bg-border" />
        <div className="mt-7 h-11 w-full rounded-md bg-muted" />
      </div>
    </>
  );
}
