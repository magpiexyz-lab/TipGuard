/**
 * Static content + arithmetic constants for `/pricing` (behavior b-10).
 *
 * Every dollar figure used to anchor the price is either (a) a statutory rate
 * with a citation, or (b) derived arithmetic from those rates. No unsourced
 * "customers save $X" claims, no fabricated social proof — the visual brief
 * forbids figures without a source, and a compliance buyer will check.
 */

/** Federal cash wage floor for tipped employees — 29 U.S.C. §203(m)(2)(A). */
export const FEDERAL_CASH_WAGE_FLOOR = 2.13;

/** Federal standard minimum wage — 29 U.S.C. §206(a)(1). */
export const FEDERAL_MINIMUM_WAGE = 7.25;

/**
 * Maximum federal tip credit: $7.25 − $2.13. Hard-coded rather than computed
 * so binary float noise never reaches a legal figure on screen.
 */
export const FEDERAL_MAX_TIP_CREDIT = 5.12;

/** Two-year FLSA lookback (three years if the violation is willful) — 29 U.S.C. §255(a). */
export const LOOKBACK_WEEKS = 104;

export const SHIELD_MONTHLY_PRICE = 79;
export const SHIELD_ANNUAL_PRICE = SHIELD_MONTHLY_PRICE * 12;

/** Defaults for the exposure model — a mid-size independent full-service room. */
export const DEFAULT_TIPPED_STAFF = 18;
export const DEFAULT_WEEKLY_TIPPED_HOURS = 25;

export const MIN_TIPPED_STAFF = 1;
export const MAX_TIPPED_STAFF = 200;
export const MIN_WEEKLY_TIPPED_HOURS = 1;
export const MAX_WEEKLY_TIPPED_HOURS = 60;

const usdFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

export function formatUsd(value: number): string {
  return usdFormatter.format(value);
}

export interface ExposureModel {
  /** Unpaid wages owed if the tip credit is voided across the lookback. */
  backPay: number;
  /** Liquidated damages in an equal amount — 29 U.S.C. §216(b). */
  liquidatedDamages: number;
  /** Back pay + liquidated damages, before the statute's fee-shifting. */
  minimumExposure: number;
  /** Total tipped hours inside the lookback window. */
  tippedHours: number;
  /** How many years of TipGuard Shield the minimum exposure would buy. */
  priceRatio: number;
}

/**
 * Pure exposure model. Voiding the tip credit means the employer owes the
 * difference between the cash wage paid and the full minimum wage for every
 * tipped hour inside the lookback — the credit was never validly claimed.
 */
export function modelExposure(
  tippedStaff: number,
  weeklyTippedHours: number
): ExposureModel {
  const tippedHours = tippedStaff * weeklyTippedHours * LOOKBACK_WEEKS;
  const backPay = Math.round(tippedHours * FEDERAL_MAX_TIP_CREDIT);
  const liquidatedDamages = backPay;
  const minimumExposure = backPay + liquidatedDamages;
  return {
    backPay,
    liquidatedDamages,
    minimumExposure,
    tippedHours,
    priceRatio: Math.max(1, Math.round(minimumExposure / SHIELD_ANNUAL_PRICE)),
  };
}

export interface PlanLine {
  label: string;
  /** `kept` renders a seal check, `locked` renders a brass lock. */
  state: "kept" | "locked";
}

/**
 * What the free tier keeps — stated exactly, per b-10's first test. The rule
 * is simple and it is the honest one: nothing you have already done is taken
 * away. Only the assembled export and the ongoing watch are paid.
 */
export const FREE_PLAN_LINES: PlanLine[] = [
  { label: "Your audit-readiness score and ranked gap list", state: "kept" },
  { label: "Roster import for your tipped staff (CSV)", state: "kept" },
  { label: "State-specific tip-credit notice generation", state: "kept" },
  { label: "Send notices for e-signature", state: "kept" },
  {
    label: "Signed acknowledgments stay in the dated vault — signer, timestamp, frozen notice text",
    state: "kept",
  },
  { label: "Compliance findings from your first scan", state: "kept" },
  { label: "The audit file, in locked preview — index visible, export disabled", state: "locked" },
];

export const SHIELD_PLAN_LINES: PlanLine[] = [
  { label: "Everything the free tier keeps", state: "kept" },
  {
    label: "One-click audit file export — every signed notice, its frozen text, and the signature metadata",
    state: "kept",
  },
  { label: "Dated cover index: employee, notice status, and the state rule version applied", state: "kept" },
  { label: "Continuous violation scanning across all four tip-credit rule classes", state: "kept" },
  { label: "State rule-version monitoring — notices flagged when your state's rules move", state: "kept" },
  { label: "Re-notice workflow for new hires and rule changes", state: "kept" },
];

export interface FaqEntry {
  id: string;
  question: string;
  answer: string;
}

export const PRICING_FAQ: FaqEntry[] = [
  {
    id: "free-tier",
    question: "What exactly does the free tier keep?",
    answer:
      "Everything you have already done. Your readiness score, your gap list, your imported roster, every notice TipGuard generated, every notice you sent, and every signed acknowledgment in the vault stay yours on the free tier. The one thing the free tier cannot do is export the assembled audit file — you can see its cover index, but the download is disabled.",
  },
  {
    id: "what-you-buy",
    question: "So what does $79 a month actually buy?",
    answer:
      "The assembled file and the ongoing watch. Shield builds the dated export on demand, re-scans your roster and pay data for the four tip-credit rule classes as new pay periods land, and tracks your state's rule version so a notice signed under last year's rules gets flagged for re-notice instead of quietly going stale.",
  },
  {
    id: "not-legal-advice",
    question: "Is this legal advice?",
    answer:
      "No. TipGuard generates notices from a versioned state rule library and stamps each one with the rule version used. Every generated notice carries an explicit disclaimer: it has not been reviewed or certified by an attorney, and it should be reviewed by your counsel before distribution. TipGuard maintains the record — your counsel makes the legal call.",
  },
  {
    id: "exposure-math",
    question: "Where does the exposure figure come from?",
    answer:
      "It is arithmetic, not an estimate we invented. If the tip credit is voided, the employer owes the difference between the cash wage paid and the full minimum wage for every tipped hour in the lookback window — up to $5.12 an hour under federal rates — plus liquidated damages in an equal amount under 29 U.S.C. §216(b), plus the plaintiff's attorney fees, which the statute shifts to the employer. The calculator uses federal figures; adjust the staff count and hours to your own room.",
  },
  {
    id: "state-coverage",
    question: "Which states are covered?",
    answer:
      "The rule library carries per-state cash wage floors, maximum tip credits, tip-pool eligibility, and required notice elements, each stamped with a rule version. States that have eliminated the tip credit generate a no-tip-credit notice instead. A state that is not yet in the library returns an explicit unsupported result — TipGuard never silently applies federal figures to a state it has not verified.",
  },
  {
    id: "cancel",
    question: "What happens to my records if I cancel?",
    answer:
      "Signature records are immutable by design — there is no path in the product that edits notice text after it has been acknowledged. They stay in the vault and stay readable on the free tier. Cancelling costs you the one-click export and the continuous scanning, not the evidence. Shield is month to month; there is no annual commitment.",
  },
];

export interface ShieldStep {
  marker: string;
  title: string;
  body: string;
}

export const SHIELD_TIMELINE: ShieldStep[] = [
  {
    marker: "Day 1",
    title: "Export the file as it stands today",
    body: "Every signed acknowledgment with its signer name, UTC timestamp, and the exact notice text acknowledged — plus the cover index of who is signed, who is not, and which rule version applied.",
  },
  {
    marker: "Every pay period",
    title: "The scan runs again",
    body: "Overtime computed off the sub-minimum base, ineligible workers in the tip pool, sub-minimum shortfalls after tips, and missing or unsigned notices — each finding ranked by estimated exposure with the fix path attached.",
  },
  {
    marker: "When the rules move",
    title: "Stale notices get flagged",
    body: "A notice signed under rule version 2025.2 is not evidence under 2026.1. Shield tracks the version stamp on every signed notice and surfaces the ones that need re-issuing before the gap widens.",
  },
];
