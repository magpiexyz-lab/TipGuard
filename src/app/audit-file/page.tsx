"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ArrowRight, LogIn, RotateCcw } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Progress, ProgressLabel, ProgressValue } from "@/components/ui/progress";
import { BlurFade } from "@/components/magicui/blur-fade";
import { MagicEffects } from "@/components/magicui/effects";
import { cn } from "@/lib/utils";
import {
  formatUtc,
  loadAuditFilePreview,
  type AuditFileLoadResult,
} from "./audit-file-contract";
import { CoverIndex } from "./cover-index";
import { ExportPanel } from "./export-panel";
import { LedgerSkeleton } from "./ledger-skeleton";
import { SignedNotices } from "./signed-notices";

/**
 * `/audit-file` — behavior b-12, hypothesis h-06.
 *
 * Authenticated and owner-scoped. Shows the file exactly as it will export:
 * a cover index of every employee with notice status and the state rule
 * version applied, then every signed acknowledgment with signer, UTC
 * timestamp, and the frozen notice text. Every signed-in account can build
 * and download it — there is no plan gate (see b-10/b-11).
 *
 * Wire dependency (scaffold-wire, STATE 14): `GET`/`POST /api/audit-file` —
 * the full contract is documented in `./audit-file-contract.ts`.
 */
export default function AuditFilePage() {
  const [result, setResult] = useState<AuditFileLoadResult | null>(null);

  const load = useCallback(() => {
    setResult(null);
    let cancelled = false;
    loadAuditFilePreview().then((next) => {
      if (!cancelled) setResult(next);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => load(), [load]);

  const preview = result?.status === "ready" ? result.preview : null;
  const counts = preview?.counts;
  const completeness =
    counts && counts.employee_count > 0
      ? Math.round((counts.signed_notice_count / counts.employee_count) * 100)
      : 0;

  return (
    <div className="min-h-screen">
      <MagicEffects />

      {/* ---------------- Header (full-bleed ink) ---------------- */}
      <section
        aria-labelledby="audit-file-heading"
        className="surface-ink texture-grain relative overflow-hidden"
      >
        <div className="bloom-brass pointer-events-none absolute inset-0" aria-hidden="true" />
        <div
          className="texture-rule pointer-events-none absolute inset-0 [mask-image:linear-gradient(to_bottom,black,transparent)]"
          aria-hidden="true"
        />

        <div className="relative mx-auto max-w-[1120px] px-6 py-16 sm:py-20">
          <div className="flex flex-wrap items-center gap-3">
            <p className="eyebrow text-brass">Dossier — tip-credit compliance</p>
            {preview ? (
              <Badge
                variant="outline"
                className={cn(
                  "h-6 rounded-md border-transparent font-mono text-[11px] tracking-[0.1em] uppercase",
                  "bg-seal/20 text-seal-soft"
                )}
              >
                Export ready
              </Badge>
            ) : null}
          </div>

          {/* The global h1 rule tracks -2px, which is a display measure. At the
              36px mobile size that is -5.5% and the words close up; scale the
              tracking with the type instead. */}
          <h1 className="mt-5 max-w-3xl text-4xl leading-[1.04] font-bold tracking-[-0.02em] sm:text-[60px] sm:tracking-[-0.033em]">
            Your audit file
          </h1>
          <p className="mt-6 max-w-2xl text-lg leading-[1.55] text-paper/70">
            One dated export holding every signed tip-credit notice, its signer
            and UTC timestamp, the exact text acknowledged, and a cover index of
            who is covered under which state rule version.
          </p>

          {/* Counts strip */}
          <dl className="mt-12 grid gap-0 border-t border-paper/12 pt-8 sm:grid-cols-3">
            <div className="sm:pr-8">
              <dt className="text-sm text-paper/70">Employees in the file</dt>
              <dd className="mt-2 font-mono text-4xl leading-[1.1] tabular-nums">
                {counts ? counts.employee_count.toLocaleString("en-US") : "—"}
              </dd>
            </div>
            <div className="mt-8 border-t border-paper/12 pt-8 sm:mt-0 sm:border-t-0 sm:border-l sm:border-paper/12 sm:px-8 sm:pt-0">
              <dt className="text-sm text-paper/70">Signed acknowledgments</dt>
              <dd className="mt-2 font-mono text-4xl leading-[1.1] tabular-nums text-seal-soft">
                {counts ? counts.signed_notice_count.toLocaleString("en-US") : "—"}
              </dd>
            </div>
            <div className="mt-8 border-t border-paper/12 pt-8 sm:mt-0 sm:border-t-0 sm:border-l sm:border-paper/12 sm:pt-0 sm:pl-8">
              <dt className="text-sm text-paper/70">Open findings</dt>
              <dd
                className={cn(
                  "mt-2 font-mono text-4xl leading-[1.1] tabular-nums",
                  counts && counts.open_violation_count > 0
                    ? "text-ember-soft"
                    : "text-paper"
                )}
              >
                {counts ? counts.open_violation_count.toLocaleString("en-US") : "—"}
                {counts && counts.open_violation_count > 0 ? (
                  <Link
                    href="/violations"
                    className="mt-2 block font-sans text-sm text-brass underline underline-offset-4"
                  >
                    Work the findings before you export
                  </Link>
                ) : null}
              </dd>
            </div>
          </dl>

          {counts && counts.employee_count > 0 ? (
            <div className="mt-10 max-w-xl">
              <Progress value={completeness} className="gap-2">
                <ProgressLabel className="text-sm text-paper/70">
                  Notice coverage
                </ProgressLabel>
                <ProgressValue className="font-mono text-sm tabular-nums text-paper" />
              </Progress>
            </div>
          ) : null}
        </div>
      </section>

      {/* ---------------- Body ---------------- */}
      <div className="mx-auto max-w-[1120px] px-6 py-14 sm:py-20">
        {/* Loading */}
        {result === null ? (
          <div className="flex flex-col gap-10">
            <LedgerSkeleton rows={3} label="Assembling your audit file" />
            <LedgerSkeleton rows={5} label="Loading the cover index" />
          </div>
        ) : null}

        {/* Not signed in */}
        {result?.status === "unauthenticated" ? (
          <div className="rounded-xl bg-card p-8 ring-1 ring-foreground/10">
            <h2 className="font-heading text-2xl leading-[1.15] tracking-[-0.02em]">
              Sign in to open your audit file
            </h2>
            <p className="mt-3 max-w-xl text-sm leading-[1.55] text-ink-soft">
              The file holds employee records and signed acknowledgments, so it
              is scoped to the account that owns them. Nothing here is public.
            </p>
            <Link
              href="/login"
              className={cn(
                buttonVariants(),
                "mt-6 h-11 rounded-full px-6 text-base font-medium"
              )}
            >
              <LogIn className="size-4" aria-hidden="true" />
              Sign in
            </Link>
          </div>
        ) : null}

        {/* Service unavailable */}
        {result?.status === "unavailable" ? (
          <Alert variant="destructive" className="p-5">
            <AlertTriangle aria-hidden="true" />
            <AlertTitle className="text-base">
              The audit file could not be assembled
            </AlertTitle>
            <AlertDescription className="mt-1">
              <p>{result.detail}</p>
              <Button
                variant="outline"
                onClick={load}
                className="mt-4 h-11 rounded-md px-5 text-sm"
              >
                <RotateCcw className="size-4" aria-hidden="true" />
                Try again
              </Button>
            </AlertDescription>
          </Alert>
        ) : null}

        {/* Ready */}
        {preview ? (
          <div className="flex flex-col gap-14">
            <ExportPanel
              counts={preview.counts}
              generatedAtLabel={formatUtc(preview.generatedAt)}
            />

            <BlurFade>
            <section aria-labelledby="cover-index-heading">
              <div className="flex flex-wrap items-end justify-between gap-4">
                <div>
                  <p className="eyebrow">Section one</p>
                  <h2
                    id="cover-index-heading"
                    className="mt-3 text-3xl tracking-[-0.022em]"
                  >
                    Cover index
                  </h2>
                  <p className="mt-2 max-w-2xl text-sm leading-[1.55] text-ink-soft">
                    Every employee, the status of their notice, and the state
                    rule version the notice was generated under.
                  </p>
                </div>
                {preview.ruleVersions.length > 0 ? (
                  <p className="font-mono text-[11px] tracking-[0.14em] text-brass-deep uppercase dark:text-brass">
                    Rule versions applied: {preview.ruleVersions.join(", ")}
                  </p>
                ) : null}
              </div>

              <div className="mt-6">
                <CoverIndex entries={preview.coverIndex} />
              </div>
            </section>
            </BlurFade>

            <BlurFade delay={55}>
            <section aria-labelledby="signed-notices-heading">
              <p className="eyebrow">Section two</p>
              <h2
                id="signed-notices-heading"
                className="mt-3 text-3xl tracking-[-0.022em]"
              >
                Signed acknowledgments
              </h2>
              <p className="mt-2 max-w-2xl text-sm leading-[1.55] text-ink-soft">
                Each record carries the signer&rsquo;s legal name, the UTC
                timestamp of the signature, and a frozen copy of the exact
                notice text acknowledged.
              </p>

              <div className="mt-6">
                <SignedNotices entries={preview.signedNotices} />
              </div>
            </section>
            </BlurFade>

            {/* Legal footnote — deliberately NOT a fourth raised card. A ruled
                marginal note reads as the caveat it is, and breaks the card
                stack above it. */}
            <section
              aria-labelledby="disclaimer-heading"
              className="border-t-2 border-brass/35 pt-8 md:grid md:grid-cols-[minmax(0,15rem)_minmax(0,1fr)] md:gap-10"
            >
              <div>
                <p className="eyebrow">Standing caveat</p>
                <h2
                  id="disclaimer-heading"
                  className="mt-3 font-heading text-xl leading-[1.15] tracking-[-0.015em] text-balance"
                >
                  What this file is, and what it is not
                </h2>
              </div>
              <div className="mt-4 md:mt-0">
                <p className="max-w-3xl text-sm leading-[1.55] text-ink-soft">
                  This export is a record of the notices TipGuard generated from a
                  versioned state rule library and the acknowledgments your staff
                  signed. It has not been reviewed or certified by an attorney and
                  it is not legal advice. Have your counsel review the notice
                  templates and this file before you rely on either.
                </p>
                <Link
                  href="/notices"
                  className="mt-2 inline-flex min-h-11 items-center gap-2 py-2 text-sm text-brass-deep underline underline-offset-4 transition-colors duration-[140ms] hover:text-ink dark:text-brass dark:hover:text-paper"
                >
                  Review the notices behind this file
                  <ArrowRight className="size-4" aria-hidden="true" />
                </Link>
              </div>
            </section>
          </div>
        ) : null}
      </div>
    </div>
  );
}
