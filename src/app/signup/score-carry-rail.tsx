"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import type { PendingScore } from "@/app/score/pending-score";
import { formatUsd, recordStamp, scoreBand } from "./score-format";

/**
 * Right-hand evidence rail on `/signup`.
 *
 * Two jobs, both load-bearing for b-03 → h-03:
 *  1. When the visitor carried a score over from the anonymous `/score`
 *     questionnaire, show the exact record that is about to be attached to the
 *     new account — score, ranked gaps, exposure range, capture stamp. The
 *     account is the file; this is a preview of the file.
 *  2. When there is no carried score, do not show an empty box. Show what the
 *     file holds, each line carrying its statutory citation, and route the
 *     visitor back to the free score.
 *
 * `pending === undefined` means "sessionStorage not yet read" — a ruled
 * skeleton holds the layout so the panel never jumps.
 */
export function ScoreCarryRail({
  pending,
}: {
  pending: PendingScore | null | undefined;
}) {
  return (
    // Two things had to change for this panel to render the depth it declares.
    //
    // 1. `texture-rule` and `bloom-brass` both write `background-image`, so
    //    stacking them on one element silently drops whichever the cascade
    //    orders first — the ruling never painted. They go on separate overlays,
    //    the same way the audit-file dossier band composes them.
    // 2. `.texture-rule` paints `var(--rule-color)`, which resolves to a
    //    near-black hairline in the light scope and is therefore invisible on
    //    `--ink`. `dark` swaps it for the bone hairline, as on the dashboard
    //    ink band.
    <aside
      aria-label="Audit-readiness record"
      className="dark surface-ink relative flex flex-col justify-center overflow-hidden px-6 py-16 sm:px-12 lg:min-h-screen lg:px-14"
    >
      <div className="bloom-brass pointer-events-none absolute inset-0" aria-hidden="true" />
      <div className="texture-rule pointer-events-none absolute inset-0" aria-hidden="true" />

      <div className="relative mx-auto w-full max-w-md">
        {pending === undefined ? (
          <RailSkeleton />
        ) : pending ? (
          <CarriedScore pending={pending} />
        ) : (
          <FileContents />
        )}
      </div>
    </aside>
  );
}

/* -------------------------------------------------------------------------- */
/* Carried score                                                              */
/* -------------------------------------------------------------------------- */

const BAND_COPY = {
  critical: {
    label: "CRITICAL EXPOSURE",
    text: "text-ember-soft",
    bar: "[&_[data-slot=progress-indicator]]:bg-ember-soft",
    summary: "Your tip credit is not currently defensible.",
  },
  "at-risk": {
    label: "AT RISK",
    text: "text-brass",
    bar: "[&_[data-slot=progress-indicator]]:bg-brass",
    summary: "Parts of your file would not survive a records request.",
  },
  clear: {
    label: "LARGELY CLEAR",
    text: "text-seal-soft",
    bar: "[&_[data-slot=progress-indicator]]:bg-seal-soft",
    summary: "Close the remaining gaps and keep the file current.",
  },
} as const;

const SEVERITY_CHIP = {
  critical: "bg-ember-soft/20 text-ember-soft",
  high: "bg-brass/20 text-brass",
  medium: "bg-[rgba(243,240,230,0.10)] text-[#a8af9b]",
} as const;

function CarriedScore({ pending }: { pending: PendingScore }) {
  const band = BAND_COPY[scoreBand(pending.readinessScore)];
  const { low, high } = pending.estimatedExposureUsd;

  return (
    <div className="animate-in fade-in-0 slide-in-from-bottom-2 duration-500">
      <div className="flex items-baseline justify-between gap-4">
        <p className="eyebrow min-w-0 text-brass">Carried from your free score</p>
        {/* A record number that breaks across two lines stops reading as a
            record number. The label wraps instead. */}
        <span className="shrink-0 whitespace-nowrap font-mono text-[11px] tracking-[0.14em] text-[#a8af9b]">
          {recordStamp(pending.savedAt)}
        </span>
      </div>

      <h2 className="mt-5 font-display text-3xl leading-[1.1] tracking-[-1.2px] text-[#ece8da]">
        This record attaches to your account
      </h2>

      {/* Readiness figure — legal/financial data is always mono + tabular. */}
      <div className="mt-9">
        <div className="flex items-end justify-between gap-6">
          <div className="flex items-baseline gap-1">
            <span
              className={cn(
                "font-mono text-[64px] font-medium leading-[1.1] tracking-[-0.2px] tabular-nums",
                band.text,
              )}
            >
              {pending.readinessScore}
            </span>
            <span className="font-mono text-xl tabular-nums text-[#a8af9b]">
              /100
            </span>
          </div>
          <span
            className={cn(
              "rounded-sm px-2 py-1 font-mono text-[11px] font-medium uppercase tracking-[0.1em]",
              band.text,
              "bg-[rgba(243,240,230,0.08)]",
            )}
          >
            {band.label}
          </span>
        </div>

        <Progress
          value={pending.readinessScore}
          aria-label={`Audit-readiness score: ${pending.readinessScore} out of 100`}
          className={cn(
            "mt-4",
            "[&_[data-slot=progress-track]]:h-2 [&_[data-slot=progress-track]]:bg-[rgba(243,240,230,0.14)]",
            "[&_[data-slot=progress-indicator]]:transition-[width] [&_[data-slot=progress-indicator]]:duration-700 [&_[data-slot=progress-indicator]]:ease-[cubic-bezier(0.32,0.72,0.22,1)]",
            band.bar,
          )}
        />

        <p className="mt-4 text-sm leading-[1.5] text-[#a8af9b]">
          {band.summary} Scored for{" "}
          <span className="font-mono uppercase tabular-nums text-[#ece8da]">
            {pending.state}
          </span>{" "}
          rules.
        </p>
      </div>

      <Separator className="my-8 bg-[rgba(243,240,230,0.12)]" />

      {/* Ranked gap ledger */}
      <p className="eyebrow text-brass">
        {pending.gaps.length > 0
          ? `${pending.gaps.length} open ${pending.gaps.length === 1 ? "gap" : "gaps"}`
          : "No open gaps"}
      </p>

      {pending.gaps.length > 0 ? (
        <ul className="mt-4 divide-y divide-[rgba(243,240,230,0.12)]">
          {pending.gaps.map((gap, index) => (
            // Three fixed columns, not a flex row: intrinsic-width severity
            // chips put every gap label on a different left edge, which is the
            // one thing a ledger cannot do. The severity column is sized to the
            // widest chip so the labels read as a single ruled column.
            <li
              key={gap.id}
              style={{ animationDelay: `${index * 55}ms` }}
              className="animate-in fade-in-0 slide-in-from-bottom-1 fill-mode-backwards grid min-h-11 grid-cols-[4.75rem_1fr_auto] items-start gap-x-3 py-3 duration-300"
            >
              <span
                className={cn(
                  "mt-0.5 justify-self-start rounded-sm px-1.5 py-0.5 font-mono text-[11px] font-medium uppercase tracking-[0.1em]",
                  SEVERITY_CHIP[gap.severity],
                )}
              >
                {gap.severity}
              </span>
              <span className="text-sm leading-[1.5] text-[#ece8da]">
                {gap.label}
              </span>
              <span className="justify-self-end font-mono text-sm tabular-nums text-[#a8af9b]">
                &minus;{gap.pointsDeducted}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-4 text-sm leading-[1.5] text-[#a8af9b]">
          Nothing was flagged by the questionnaire. Your account keeps it that
          way as staff and state rules change.
        </p>
      )}

      <Separator className="my-8 bg-[rgba(243,240,230,0.12)]" />

      <dl className="grid gap-1">
        <dt className="eyebrow text-brass">Estimated back-pay exposure</dt>
        <dd className="font-mono text-2xl font-medium tabular-nums tracking-[-0.2px] text-[#ece8da]">
          {high > 0 ? `${formatUsd(low)} – ${formatUsd(high)}` : "None estimated"}
        </dd>
        <dd className="mt-2 text-sm leading-[1.5] text-[#a8af9b]">
          Unliquidated estimate across your tipped staff. Liquidated damages can
          double it{" "}
          <span className="font-mono text-brass">29 U.S.C. §216(b)</span>.
        </dd>
      </dl>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* No carried score                                                           */
/* -------------------------------------------------------------------------- */

const FILE_CONTENTS = [
  {
    title: "A signed tip-credit notice for every tipped employee",
    detail: "The first document an investigator asks for.",
    citation: "29 CFR §531.59(b)",
  },
  {
    title: "Dated acknowledgments with the exact text acknowledged",
    detail: "Signer, UTC timestamp, and a frozen copy — evidence, not a summary.",
    citation: "29 CFR §516.28",
  },
  {
    title: "The cash wage you actually paid, per state",
    detail: "The federal floor is $2.13; your state may set it higher.",
    citation: "29 U.S.C. §203(m)",
  },
  {
    title: "Overtime computed off the full minimum wage",
    detail: "Not off the sub-minimum cash wage — the most common miscalculation.",
    citation: "29 CFR §531.60",
  },
] as const;

function FileContents() {
  return (
    <div className="animate-in fade-in-0 slide-in-from-bottom-2 duration-500">
      <p className="eyebrow text-brass">What your file holds</p>
      <h2 className="mt-5 font-display text-3xl leading-[1.1] tracking-[-1.2px] text-[#ece8da]">
        Your account is the file you hand over
      </h2>
      <p className="mt-4 text-sm leading-[1.55] text-[#a8af9b]">
        Payroll calculates wages and tip apps distribute payouts. Neither keeps
        the record below.
      </p>

      <ul className="mt-8 divide-y divide-[rgba(243,240,230,0.12)]">
        {FILE_CONTENTS.map((item, index) => (
          <li
            key={item.citation}
            style={{ animationDelay: `${index * 55}ms` }}
            className="animate-in fade-in-0 slide-in-from-bottom-1 fill-mode-backwards py-4 duration-300"
          >
            <p className="text-sm font-medium leading-[1.5] text-[#ece8da]">
              {item.title}
            </p>
            <p className="mt-1 text-sm leading-[1.5] text-[#a8af9b]">
              {item.detail}
            </p>
            <p className="mt-2 font-mono text-[11px] tracking-[0.14em] text-brass">
              {item.citation}
            </p>
          </li>
        ))}
      </ul>

      <Link
        href="/score"
        className="group mt-8 inline-flex min-h-11 items-center gap-2 text-sm font-medium text-brass transition-colors duration-[140ms] hover:text-[#ece8da] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-brass"
      >
        <span className="border-b border-transparent pb-0.5 transition-colors duration-[140ms] group-hover:border-brass">
          Haven&rsquo;t scored yet? Take the free 2-minute score first
        </span>
        <ArrowRight
          className="h-4 w-4 transition-transform duration-[140ms] group-hover:translate-x-0.5"
          aria-hidden="true"
        />
      </Link>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Skeleton                                                                   */
/* -------------------------------------------------------------------------- */

function RailSkeleton() {
  return (
    <>
      <p className="sr-only">Loading your carried audit-readiness score</p>
      <div aria-hidden="true" className="animate-pulse">
        <div className="h-3 w-40 rounded-sm bg-[rgba(243,240,230,0.14)]" />
        <div className="mt-6 h-8 w-full rounded-sm bg-[rgba(243,240,230,0.10)]" />
        <div className="mt-9 h-14 w-32 rounded-sm bg-[rgba(243,240,230,0.14)]" />
        <div className="mt-4 h-2 w-full rounded-full bg-[rgba(243,240,230,0.10)]" />
        <div className="mt-10 divide-y divide-[rgba(243,240,230,0.12)]">
          {/* Column track matches the live ledger below so the panel does not
              re-flow when the carried record arrives. */}
          {[0, 1, 2, 3].map((row) => (
            <div
              key={row}
              className="grid h-11 grid-cols-[4.75rem_1fr] items-center gap-x-3"
            >
              <div className="h-4 w-[3.25rem] rounded-sm bg-[rgba(243,240,230,0.14)]" />
              <div className="h-4 rounded-sm bg-[rgba(243,240,230,0.08)]" />
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
