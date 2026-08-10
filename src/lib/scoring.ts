// Audit-readiness questionnaire scoring (b-02).
//
// Pure function — deterministic, no network calls, no AI. Computes a 0-100
// score, a ranked gap list, and an estimated back-pay exposure range from the
// free /score questionnaire answers. Never call into src/lib/ai.ts from here:
// stack.ai is scoped to prose polish only, not score computation.

export type NoticeCoverage = "all" | "some" | "none";
export type OvertimeBasis = "cash_wage" | "full_minimum_wage";
export type NewHireProcess = "consistent" | "inconsistent" | "none";

export interface ScoringInput {
  /** Two-letter US state code. */
  state: string;
  /** Whether the restaurant currently claims the tip credit. */
  claimsTipCredit: boolean;
  /** Fraction of tipped staff with a signed tip-credit notice on file. */
  noticeCoverage: NoticeCoverage;
  /** Whether the tip pool includes a manager or back-of-house worker. */
  tipPoolIncludesIneligibleWorkers: boolean;
  /** Whether overtime is computed off the cash wage (violation) or full minimum wage (compliant). */
  overtimeBasis: OvertimeBasis;
  /** Whether new hires consistently receive a notice before their first shift. */
  newHireProcess: NewHireProcess;
  /** Number of tipped staff, used to scale the exposure estimate. */
  staffCount: number;
}

export type GapId =
  | "missing_signed_notices"
  | "ineligible_tip_pool"
  | "overtime_on_subminimum"
  | "inconsistent_new_hire_process";

export interface GapFinding {
  id: GapId;
  label: string;
  severity: "critical" | "high" | "medium";
  pointsDeducted: number;
}

export interface ExposureRange {
  low: number;
  high: number;
}

export interface ScoringResult {
  /** 0-100, higher is more audit-ready. */
  score: number;
  /** Ranked by pointsDeducted descending (most severe gap first). */
  gaps: GapFinding[];
  estimatedExposureUsd: ExposureRange;
}

const EXPOSURE_PER_EMPLOYEE_LOW_USD = 1_500;
const EXPOSURE_PER_EMPLOYEE_HIGH_USD = 5_000;
const MAX_GAP_RULES = 4;

export function scoreAuditReadiness(input: ScoringInput): ScoringResult {
  const gaps: GapFinding[] = [];

  // Every gap rule below only applies when the restaurant is actually
  // claiming the tip credit — a restaurant paying full minimum wage has no
  // tip-credit-notice exposure to close.
  if (input.claimsTipCredit) {
    if (input.noticeCoverage !== "all") {
      gaps.push({
        id: "missing_signed_notices",
        label: "One or more tipped employees do not have a signed tip-credit notice on file",
        severity: "critical",
        pointsDeducted: input.noticeCoverage === "none" ? 40 : 20,
      });
    }

    if (input.tipPoolIncludesIneligibleWorkers) {
      gaps.push({
        id: "ineligible_tip_pool",
        label: "The tip pool includes a manager or back-of-house worker who is not eligible to share tips",
        severity: "critical",
        pointsDeducted: 25,
      });
    }

    if (input.overtimeBasis === "cash_wage") {
      gaps.push({
        id: "overtime_on_subminimum",
        label: "Overtime is calculated off the $2.13 cash wage instead of the full minimum wage",
        severity: "critical",
        pointsDeducted: 20,
      });
    }

    if (input.newHireProcess !== "consistent") {
      gaps.push({
        id: "inconsistent_new_hire_process",
        label: "New hires are not consistently given a tip-credit notice before their first shift",
        severity: input.newHireProcess === "none" ? "high" : "medium",
        pointsDeducted: input.newHireProcess === "none" ? 15 : 8,
      });
    }
  }

  const totalDeducted = gaps.reduce((sum, gap) => sum + gap.pointsDeducted, 0);
  const score = Math.max(0, Math.min(100, 100 - totalDeducted));

  const rankedGaps = [...gaps].sort((a, b) => b.pointsDeducted - a.pointsDeducted);

  return {
    score,
    gaps: rankedGaps,
    estimatedExposureUsd: estimateExposureUsd(input, gaps.length),
  };
}

function estimateExposureUsd(input: ScoringInput, gapCount: number): ExposureRange {
  if (!input.claimsTipCredit || gapCount === 0) return { low: 0, high: 0 };
  const staff = Math.max(input.staffCount, 0);
  // Scales linearly with how many of the four gap rules fired — more open
  // gaps means more of the workforce's hours are potentially exposed.
  const severityFactor = Math.min(gapCount, MAX_GAP_RULES) / MAX_GAP_RULES;
  return {
    low: Math.round(staff * EXPOSURE_PER_EMPLOYEE_LOW_USD * severityFactor),
    high: Math.round(staff * EXPOSURE_PER_EMPLOYEE_HIGH_USD * severityFactor),
  };
}
