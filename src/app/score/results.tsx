"use client";

// Results surface for the free audit-readiness score (b-02).
//
// Everything rendered here is derived from two pure functions:
//   scoreAuditReadiness()  (src/lib/scoring.ts)      -> score, ranked gaps, exposure
//   resolveStateRule()     (src/lib/state-rules.ts)  -> cash wage floor, rule version
// No model output, no network call, no arithmetic invented in this file.

import Image from "next/image";
import Link from "next/link";
import { AlertTriangle, ArrowRight, FileSignature, RotateCcw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import type { GapId, ScoringResult } from "@/lib/scoring";
import { RULE_VERSION, resolveStateRule } from "@/lib/state-rules";

import { ScoreDial, bandForScore } from "./score-dial";
import { STATE_OPTIONS, type Answers } from "./questions";

// Two formatters, deliberately different precisions.
//
// `usd` — the exposure range. It is an order-of-magnitude estimate, so whole
// dollars is the honest precision; cents there would imply a false accuracy.
const usd = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

// `wage` — statutory figures quoted back to the user as legal fact. These are
// exact to the cent ($2.13, $7.25, $16.50) and are the same numbers shown on
// the state cards in the questionnaire. Rounding them misstates the rule: it
// turned California's $16.50 floor into "$17" and Texas's $2.13 into "$2".
const wage = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const GAP_GUIDANCE: Record<GapId, { consequence: string; fix: string }> = {
  missing_signed_notices: {
    consequence:
      "An investigator opens with this file. Without a signed, dated notice the tip credit was never valid for that employee, so the difference between the cash wage and the full minimum wage is owed back for every hour they worked.",
    fix: "Generate the state-specific notice for each employee, send it for e-signature, and keep the dated acknowledgment in the vault.",
  },
  ineligible_tip_pool: {
    consequence:
      "One ineligible participant invalidates the entire pool, not just that person's share. Every employee who contributed can claim the full value of the tips redistributed out of it.",
    fix: "Remove managers, supervisors, and back-of-house staff from the pool, then re-issue notices that state exactly who participates.",
  },
  overtime_on_subminimum: {
    consequence:
      "The overtime premium has to be computed on the full minimum wage and the tip credit subtracted afterward. Computing it on the cash wage underpays every overtime hour, and it repeats on every pay period.",
    fix: "Correct the overtime basis in payroll and settle the shortfall for the periods already run.",
  },
  inconsistent_new_hire_process: {
    consequence:
      "The notice must precede the first tipped shift. A file that was complete last quarter is not a defense for anyone hired since, and turnover makes that gap reopen continuously.",
    fix: "Put notice generation and signature into onboarding so a new hire cannot reach their first shift unsigned.",
  },
};

const SEVERITY_STYLE: Record<string, string> = {
  critical: "bg-ember/12 text-ember dark:text-ember-soft",
  high: "bg-brass/18 text-brass-deep dark:text-brass",
  medium: "bg-muted text-muted-foreground",
};

function stateLabel(code: string): string {
  return STATE_OPTIONS.find((option) => option.value === code)?.label ?? code;
}

function verdictSentence(result: ScoringResult, claimsTipCredit: boolean): string {
  if (!claimsTipCredit) {
    return "You do not claim the tip credit, so there is no credit to void.";
  }
  const count = result.gaps.length;
  if (count === 0) return "These seven checks came back clean.";
  if (count === 1) return "One open gap puts your tip credit at risk.";
  const words = ["", "One", "Two", "Three", "Four"];
  return `${words[count] ?? count} open gaps put your tip credit at risk.`;
}

/**
 * The paragraph under the verdict. The zero-gap case needs its own sentence:
 * the deduction copy ("a document you cannot currently produce") is addressed
 * to someone who lost points, and reads as an accusation when nothing was
 * deducted — at the exact moment a clean scorer should feel rewarded.
 */
function verdictBody(result: ScoringResult, claimsTipCredit: boolean): string {
  if (!claimsTipCredit) {
    return "Paying the full minimum wage in cash removes the tip-credit exposure entirely. The checks below still matter if you ever move to a sub-minimum cash wage.";
  }
  if (result.gaps.length === 0) {
    return "Nothing was deducted — every condition your tip credit depends on held. What an investigator asks for next is the paperwork that proves it, employee by employee.";
  }
  return "Every point deducted below maps to a specific document an investigator can ask for and you cannot currently produce.";
}

export function ScoreResults({
  result,
  answers,
  onRestart,
}: {
  result: ScoringResult;
  answers: Answers;
  onRestart: () => void;
}) {
  const claimsTipCredit = answers.claimsTipCredit === "yes";
  const staffCount = answers.staffCount ?? 0;
  const stateCode = answers.state ?? "OTHER";
  const rule = resolveStateRule(stateCode);
  // Narrowed once so the JSX below can read cash-wage figures without repeating
  // the discriminant check — an unsupported state has no figures to show.
  const supportedRule = rule.eligibility === "unsupported_state" ? null : rule;
  const band = bandForScore(result.score);
  const hasGaps = result.gaps.length > 0;
  // Headline and button carry the same words — the promise the visitor clicks.
  // With nothing flagged there are no gaps to "fix", so the ask becomes the file.
  const ctaLabel = hasGaps
    ? "Save my score and fix these gaps"
    : "Save my score and build the file";
  const claimingWhereProhibited = claimsTipCredit && rule.eligibility === "no_tip_credit_state";

  return (
    <div className="pb-24">
      {/* --- Verdict ------------------------------------------------------ */}
      <section aria-labelledby="verdict-heading" className="mx-auto max-w-[1120px] px-6 pt-10">
        <div className="grid items-center gap-8 rounded-xl bg-card p-6 ring-1 ring-foreground/10 sm:p-8 md:grid-cols-[240px_1fr] md:gap-12">
          <ScoreDial score={result.score} className="mx-auto md:mx-0" />

          <div>
            <p className="eyebrow">Audit-readiness — {band.label}</p>
            <h2
              id="verdict-heading"
              className="mt-3 text-3xl leading-tight tracking-[-1px] [word-spacing:0.06em] sm:text-[44px] sm:leading-[1.1] sm:tracking-[-1.6px]"
            >
              {verdictSentence(result, claimsTipCredit)}
            </h2>
            <p className="mt-4 max-w-xl text-base leading-relaxed text-muted-foreground">
              {verdictBody(result, claimsTipCredit)}
            </p>

            <div className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-3">
              <span className="inline-flex items-center gap-2">
                <span data-evidence className="text-sm text-muted-foreground">
                  {stateLabel(stateCode)}
                </span>
                <Separator orientation="vertical" className="h-4" />
                <span data-evidence className="text-sm text-muted-foreground">
                  {staffCount} tipped staff
                </span>
                <Separator orientation="vertical" className="h-4" />
                <span data-evidence className="text-sm text-muted-foreground">
                  RULE {RULE_VERSION}
                </span>
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* --- Exposure evidence strip (full-bleed ink band) ---------------- */}
      <section aria-label="Estimated exposure" className="mt-10">
        <div className="surface-ink texture-rule bloom-brass">
          <div className="mx-auto grid max-w-[1120px] gap-px px-6 py-10 sm:grid-cols-3">
            <div className="sm:border-r sm:border-[rgba(243,240,230,0.14)] sm:pr-6">
              <p className="eyebrow">Estimated back pay — low</p>
              <p data-evidence className="mt-3 text-4xl font-medium text-[#ECE8DA]">
                {usd.format(result.estimatedExposureUsd.low)}
              </p>
            </div>
            <div className="pt-6 sm:border-r sm:border-[rgba(243,240,230,0.14)] sm:px-6 sm:pt-0">
              <p className="eyebrow">Estimated back pay — high</p>
              <p data-evidence className="mt-3 text-4xl font-medium text-brass">
                {usd.format(result.estimatedExposureUsd.high)}
              </p>
            </div>
            <div className="pt-6 sm:pl-6 sm:pt-0">
              <p className="eyebrow">Before liquidated damages</p>
              <p className="mt-3 text-sm leading-relaxed text-[#A8AF9B]">
                Willful violations carry an equal additional amount in liquidated damages, and
                defense costs sit on top of both.
              </p>
              <p data-evidence className="mt-2 text-xs text-[#A8AF9B]">
                29 U.S.C. §216(b)
              </p>
            </div>
          </div>
          <div className="mx-auto max-w-[1120px] px-6 pb-10">
            <p className="text-xs leading-relaxed text-[#A8AF9B]">
              Range is an order-of-magnitude estimate: {staffCount} tipped staff scaled by how many
              of the four checks failed. It is not a legal opinion and not a calculation of what any
              specific employee is owed.
            </p>
          </div>
        </div>
      </section>

      {/* --- State rule note ---------------------------------------------- */}
      <section aria-labelledby="state-rule-heading" className="mx-auto max-w-[1120px] px-6 pt-14">
        <p className="eyebrow">Rule library</p>
        <h2
          id="state-rule-heading"
          className="mt-3 text-2xl tracking-[-0.8px] [word-spacing:0.06em] sm:text-3xl sm:tracking-[-1.6px]"
        >
          What {stateLabel(stateCode)} requires
        </h2>

        {claimingWhereProhibited && supportedRule ? (
          <div
            role="alert"
            className="mt-5 flex items-start gap-3 rounded-lg bg-ember/10 p-5 ring-1 ring-ember/30"
          >
            <AlertTriangle aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-ember" />
            <div>
              <h3 className="text-base font-medium text-ember dark:text-ember-soft">
                {stateLabel(stateCode)} does not permit a tip credit
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-foreground">
                You told us you pay some tipped staff below the full minimum wage. In this state the
                full minimum wage of{" "}
                <span data-evidence>{wage.format(supportedRule.standardMinimumWage)}</span> must be
                paid in cash before tips. This is a wage shortfall on every tipped hour, not a paperwork
                gap, and it is the first thing to fix.
              </p>
            </div>
          </div>
        ) : null}

        <div className="mt-5 grid gap-4 sm:grid-cols-3">
          {!supportedRule ? (
            <div className="rounded-lg bg-card p-5 ring-1 ring-foreground/10 sm:col-span-3">
              <h3 className="text-base font-medium">Not in the rule library yet</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                Your score above is state-independent — it measures the paperwork and pay practices
                that the federal rule requires everywhere. Your state&apos;s specific cash-wage
                floor and notice wording are not in the library yet, so TipGuard will not guess
                them. Create an account and we will map your state before generating a single
                notice.
              </p>
            </div>
          ) : (
            <>
              <RuleCell label="Cash wage floor" value={wage.format(supportedRule.cashWageFloor)} />
              <RuleCell
                label="Full minimum wage"
                value={wage.format(supportedRule.standardMinimumWage)}
              />
              <RuleCell
                label="Maximum tip credit"
                value={wage.format(supportedRule.maxTipCredit)}
                caption={
                  supportedRule.eligibility === "no_tip_credit_state"
                    ? "Tip credit eliminated in this state"
                    : `${supportedRule.requiredNoticeElements.length} required notice elements`
                }
              />
            </>
          )}
        </div>
      </section>

      {/* --- Ranked gaps --------------------------------------------------- */}
      <section aria-labelledby="gaps-heading" className="mx-auto max-w-[1120px] px-6 pt-14">
        <p className="eyebrow">{hasGaps ? "Ranked by points lost" : "Nothing deducted"}</p>
        <h2
          id="gaps-heading"
          className="mt-3 text-2xl tracking-[-0.8px] [word-spacing:0.06em] sm:text-3xl sm:tracking-[-1.6px]"
        >
          {hasGaps ? "Your open gaps" : "No open gaps in these checks"}
        </h2>

        {hasGaps ? (
          <ol className="mt-6 space-y-4">
            {result.gaps.map((gap, index) => {
              const guidance = GAP_GUIDANCE[gap.id];
              return (
                <li
                  key={gap.id}
                  className={cn(
                    "group/gap relative rounded-xl bg-card p-6 ring-1 ring-foreground/10",
                    "transition-[box-shadow,transform] duration-[var(--duration-fast)] ease-[var(--ease-stamp)]",
                    "hover:-translate-y-0.5 hover:shadow-[var(--shadow-ledger-2)]",
                  )}
                >
                  <div className="flex flex-wrap items-center gap-3">
                    <span
                      data-evidence
                      className="text-sm text-muted-foreground"
                      aria-hidden="true"
                    >
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <Badge
                      variant="secondary"
                      className={cn(
                        "h-5 rounded-sm px-2 font-mono text-[11px] tracking-[0.1em] uppercase",
                        SEVERITY_STYLE[gap.severity],
                      )}
                    >
                      {gap.severity}
                    </Badge>
                    <span data-evidence className="ml-auto text-sm text-muted-foreground">
                      {gap.pointsDeducted} pts deducted
                    </span>
                  </div>

                  <h3 className="mt-3 text-xl leading-snug">{gap.label}</h3>

                  <div className="mt-4 grid gap-5 md:grid-cols-2">
                    <div className="md:border-r md:border-border md:pr-5">
                      <p className="eyebrow">What this costs you</p>
                      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                        {guidance.consequence}
                      </p>
                    </div>
                    <div>
                      <p className="eyebrow">How TipGuard closes it</p>
                      <p className="mt-2 text-sm leading-relaxed text-foreground">
                        {guidance.fix}
                      </p>
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>
        ) : (
          <div className="mt-6 flex flex-col items-center gap-6 rounded-xl bg-card p-10 text-center ring-1 ring-foreground/10 sm:p-14">
            {/* The asset ships on a #f3f0e6 (--paper) field, which reads as a
                grey rectangle when dropped straight onto a --paper-raised card.
                Framing it in a --background inset makes the tonal step
                intentional and the seam disappears. */}
            <div className="rounded-xl bg-background p-5 ring-1 ring-foreground/10">
              <Image
                src="/images/empty-state.webp"
                alt=""
                aria-hidden
                width={800}
                height={608}
                className="h-auto w-full max-w-[240px]"
              />
            </div>
            <div className="max-w-xl">
              <h3 className="text-xl text-seal dark:text-seal-soft">
                Nothing flagged in the seven checks
              </h3>
              <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
                A clean questionnaire is not the same as a complete file. It means the practices you
                described are correct today — an investigator will still ask you to produce the
                signed notice for every named employee, dated before their first shift. Create an
                account to turn these answers into the file itself and keep it correct as staff turn
                over.
              </p>
            </div>
          </div>
        )}
      </section>

      {/* --- Conversion band ---------------------------------------------- */}
      <section aria-label="Save your score" className="mx-auto max-w-[1120px] px-6 pt-14">
        <div className="overflow-hidden rounded-xl">
          <div className="surface-ink texture-rule bloom-brass p-8 sm:p-12">
            <p className="eyebrow">Next step</p>
            <h2 className="mt-3 max-w-2xl text-3xl leading-tight tracking-[-1px] [word-spacing:0.06em] text-[#ECE8DA] sm:text-[40px] sm:tracking-[-1.6px]">
              {ctaLabel}
            </h2>
            <p className="mt-4 max-w-2xl text-base leading-relaxed text-[#A8AF9B]">
              {hasGaps
                ? "Creating an account carries this score and gap list onto your restaurant, then generates the state-specific notices your staff can sign. Free — the $79/mo plan is for the audit-file export, not for closing the gaps."
                : "Creating an account carries this score onto your restaurant and generates the state-specific notice each employee signs — so a clean answer becomes a file you can actually produce, and stays clean as staff turn over. Free — the $79/mo plan is for the audit-file export."}
            </p>

            <div className="mt-8 flex flex-col gap-4 sm:flex-row sm:items-center">
              <Link
                href="/signup"
                className={cn(
                  buttonVariants(),
                  "h-11 rounded-full px-6 text-base font-medium",
                  "transition-transform duration-[var(--duration-fast)] ease-[var(--ease-stamp)] hover:-translate-y-0.5",
                )}
              >
                <FileSignature aria-hidden="true" className="size-4" />
                {ctaLabel}
                <ArrowRight aria-hidden="true" className="size-4" />
              </Link>
              <span data-evidence className="text-sm text-[#A8AF9B]">
                Score held in this browser until you do
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* --- Disclaimer + restart ----------------------------------------- */}
      <section aria-label="Disclaimer and restart" className="mx-auto max-w-[1120px] px-6 pt-10">
        <Separator />
        <div className="mt-6 flex flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
          <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
            This score is a self-assessment tool, not legal advice, and TipGuard is not your
            attorney. Every notice TipGuard generates carries a review-by-your-counsel disclaimer
            and should be reviewed by your own counsel before distribution.
          </p>
          <Button
            variant="ghost"
            onClick={onRestart}
            className="h-11 shrink-0 self-start px-4 text-base"
          >
            <RotateCcw aria-hidden="true" className="size-4" />
            Start over
          </Button>
        </div>
      </section>
    </div>
  );
}

function RuleCell({
  label,
  value,
  caption,
}: {
  label: string;
  value: string;
  caption?: string;
}) {
  return (
    <div className="rounded-lg bg-card p-5 ring-1 ring-foreground/10">
      <p className="eyebrow">{label}</p>
      <p data-evidence className="mt-2 text-2xl font-medium">
        {value}
      </p>
      {caption ? <p className="mt-2 text-xs text-muted-foreground">{caption}</p> : null}
    </div>
  );
}
