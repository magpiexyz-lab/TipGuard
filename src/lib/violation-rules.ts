// Compliance-scan rule classes (b-08).
//
// Four independent pure functions, one per rule class. Each returns a
// ViolationFinding on a violation, or null when the input is compliant.
// No network, no AI — the finding's `detail` text is plain-English by
// construction, not model-generated.

export type ViolationRuleClass =
  | "overtime_base"
  | "ineligible_tip_pool"
  | "subminimum_shortfall"
  | "missing_notice";

export type ViolationSeverity = "critical" | "high" | "medium";

export interface ViolationFinding {
  ruleClass: ViolationRuleClass;
  severity: ViolationSeverity;
  estimatedExposureUsd: number;
  detail: string;
}

// --- Rule 1: overtime computed off the sub-minimum cash wage ---

export interface OvertimeBasisInput {
  /** Applicable full (non-tipped) minimum wage for the pay period's state. */
  fullMinimumWage: number;
  /** Overtime hours worked in the pay period. */
  overtimeHours: number;
  /** The overtime premium rate actually paid (dollars/hour). */
  overtimeRateUsed: number;
}

/**
 * Overtime must be calculated at 1.5x the full minimum wage, never 1.5x the
 * reduced cash wage the employer pays a tipped employee.
 */
export function checkOvertimeBasis(input: OvertimeBasisInput): ViolationFinding | null {
  if (input.overtimeHours <= 0) return null;

  const requiredOvertimeRate = input.fullMinimumWage * 1.5;
  if (input.overtimeRateUsed >= requiredOvertimeRate) return null; // compliant

  const shortfallPerHour = requiredOvertimeRate - input.overtimeRateUsed;
  return {
    ruleClass: "overtime_base",
    severity: "critical",
    estimatedExposureUsd: round2(shortfallPerHour * input.overtimeHours),
    detail:
      `Overtime premium was calculated at $${input.overtimeRateUsed.toFixed(2)}/hr instead of ` +
      `the required $${requiredOvertimeRate.toFixed(2)}/hr (1.5x the full minimum wage).`,
  };
}

// --- Rule 2: ineligible manager/BOH worker in the tip pool ---

export interface TipPoolEligibilityInput {
  employeeRole: string;
  isInTipPool: boolean;
  eligibleRoles: readonly string[];
  /** Optional — the employee's average weekly tip-pool share, used to size exposure. */
  weeklyTipPoolShareUsd?: number;
}

/**
 * Only employees who customarily and regularly receive tips (servers,
 * bartenders, bussers, etc.) may share in a tip pool. Managers and
 * back-of-house workers voiding the credit for every pooled employee.
 */
export function checkTipPoolEligibility(input: TipPoolEligibilityInput): ViolationFinding | null {
  if (!input.isInTipPool) return null;

  const normalizedRole = input.employeeRole.trim().toLowerCase();
  const eligible = input.eligibleRoles.some((role) => role.toLowerCase() === normalizedRole);
  if (eligible) return null;

  return {
    ruleClass: "ineligible_tip_pool",
    severity: "critical",
    estimatedExposureUsd: round2(input.weeklyTipPoolShareUsd ?? 0),
    detail: `"${input.employeeRole}" is not an eligible tipped role and must not share in the tip pool.`,
  };
}

// --- Rule 3: sub-minimum-wage shortfall after tips ---

export interface SubminimumShortfallInput {
  cashWagePaid: number;
  hoursWorked: number;
  tipsReceived: number;
  applicableMinimumWage: number;
}

/**
 * Cash wage plus tips actually received must equal or exceed the full
 * applicable minimum wage for every hour worked in the pay period — the
 * employer, not the customer, is on the hook for any shortfall.
 */
export function checkSubminimumShortfall(input: SubminimumShortfallInput): ViolationFinding | null {
  const totalEarnings = input.cashWagePaid * input.hoursWorked + input.tipsReceived;
  const requiredEarnings = input.applicableMinimumWage * input.hoursWorked;
  if (totalEarnings >= requiredEarnings) return null; // compliant

  const shortfall = round2(requiredEarnings - totalEarnings);
  return {
    ruleClass: "subminimum_shortfall",
    severity: "high",
    estimatedExposureUsd: shortfall,
    detail:
      `Cash wage plus tips ($${totalEarnings.toFixed(2)}) fell short of the required minimum-wage ` +
      `earnings ($${requiredEarnings.toFixed(2)}) for the workweek by $${shortfall.toFixed(2)}.`,
  };
}

// --- Rule 4: missing or unsigned notice ---

export interface NoticeStatusInput {
  noticeExists: boolean;
  noticeStatus?: "draft" | "sent" | "signed";
  noticeRuleVersion?: string;
  currentRuleVersion: string;
}

/**
 * Every employee for whom the tip credit is claimed must have a signed
 * notice on file for the CURRENT rule version — a stale or unsigned notice
 * voids the credit exactly like a missing one.
 */
export function checkNoticeStatus(input: NoticeStatusInput): ViolationFinding | null {
  if (!input.noticeExists) {
    return {
      ruleClass: "missing_notice",
      severity: "critical",
      estimatedExposureUsd: 0,
      detail: "No tip-credit notice has been generated for this employee.",
    };
  }
  if (input.noticeStatus !== "signed") {
    return {
      ruleClass: "missing_notice",
      severity: "critical",
      estimatedExposureUsd: 0,
      detail: "The tip-credit notice has not been signed by the employee.",
    };
  }
  if (input.noticeRuleVersion !== input.currentRuleVersion) {
    return {
      ruleClass: "missing_notice",
      severity: "critical",
      estimatedExposureUsd: 0,
      detail: "The signed notice is for an outdated rule version and must be reissued and re-signed.",
    };
  }
  return null; // compliant — notice exists, signed, current rule version
}

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}
