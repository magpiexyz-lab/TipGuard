// Versioned per-state tip-credit rule library (b-05).
//
// Pure function, no network. Every dollar figure below is a starting point
// for the MVP and MUST be verified against current state DOL guidance before
// a notice generated from it is distributed — see notice-generator.ts's
// COUNSEL_REVIEW_DISCLAIMER, which is attached to every notice regardless of
// which branch resolved.
//
// Three resolution outcomes:
//   - "eligible"          — state permits a tip credit; cashWageFloor < standardMinimumWage.
//   - "no_tip_credit_state" — state has eliminated the tip credit; full minimum wage in cash.
//   - "unsupported_state"  — state is not yet in the library. This is an EXPLICIT
//     unsupported result, never a silent fallback to federal figures — silently
//     applying federal rules to an unmapped state could understate the required
//     cash wage and create the exact compliance gap this product exists to close.

export const RULE_VERSION = "2026.1";

const FEDERAL_REQUIRED_NOTICE_ELEMENTS = [
  "The cash wage the employer is paying the tipped employee",
  "The additional amount claimed by the employer as a tip credit (which cannot exceed the value of tips actually received)",
  "That the tip credit claimed cannot exceed the amount of tips actually received by the employee",
  "That all tips received by the employee must be retained by the employee, except for a valid tip pooling arrangement limited to employees who customarily and regularly receive tips",
  "That the tip credit does not apply to any employee who has not been informed of these requirements",
] as const;

const TIP_POOL_ELIGIBLE_ROLES = ["server", "bartender", "busser", "host", "runner", "barback"] as const;

export interface EligibleStateRule {
  state: string;
  ruleVersion: string;
  eligibility: "eligible";
  cashWageFloor: number;
  standardMinimumWage: number;
  maxTipCredit: number;
  tipPoolEligibleRoles: readonly string[];
  requiredNoticeElements: readonly string[];
}

export interface NoTipCreditStateRule {
  state: string;
  ruleVersion: string;
  eligibility: "no_tip_credit_state";
  cashWageFloor: number; // equals standardMinimumWage — no credit permitted
  standardMinimumWage: number;
  maxTipCredit: 0;
  tipPoolEligibleRoles: readonly string[];
  requiredNoticeElements: readonly string[];
}

export interface UnsupportedStateResult {
  state: string;
  eligibility: "unsupported_state";
}

export type StateRuleResult = EligibleStateRule | NoTipCreditStateRule | UnsupportedStateResult;

type LibraryEntry = Omit<EligibleStateRule, "state"> | Omit<NoTipCreditStateRule, "state">;

// Illustrative starting figures — verify against current state DOL guidance.
const STATE_RULE_LIBRARY: Record<string, LibraryEntry> = {
  // --- States that follow (or track close to) the federal tip credit ---
  TX: {
    ruleVersion: RULE_VERSION,
    eligibility: "eligible",
    cashWageFloor: 2.13,
    standardMinimumWage: 7.25,
    maxTipCredit: 5.12,
    tipPoolEligibleRoles: TIP_POOL_ELIGIBLE_ROLES,
    requiredNoticeElements: FEDERAL_REQUIRED_NOTICE_ELEMENTS,
  },
  FL: {
    ruleVersion: RULE_VERSION,
    eligibility: "eligible",
    cashWageFloor: 8.98,
    standardMinimumWage: 13.0,
    maxTipCredit: 4.02,
    tipPoolEligibleRoles: TIP_POOL_ELIGIBLE_ROLES,
    requiredNoticeElements: FEDERAL_REQUIRED_NOTICE_ELEMENTS,
  },
  NY: {
    ruleVersion: RULE_VERSION,
    eligibility: "eligible",
    cashWageFloor: 10.65,
    standardMinimumWage: 15.5,
    maxTipCredit: 4.85,
    tipPoolEligibleRoles: TIP_POOL_ELIGIBLE_ROLES,
    requiredNoticeElements: FEDERAL_REQUIRED_NOTICE_ELEMENTS,
  },
  // --- States that have eliminated the tip credit ---
  CA: {
    ruleVersion: RULE_VERSION,
    eligibility: "no_tip_credit_state",
    cashWageFloor: 16.5,
    standardMinimumWage: 16.5,
    maxTipCredit: 0,
    tipPoolEligibleRoles: TIP_POOL_ELIGIBLE_ROLES,
    requiredNoticeElements: FEDERAL_REQUIRED_NOTICE_ELEMENTS,
  },
  WA: {
    ruleVersion: RULE_VERSION,
    eligibility: "no_tip_credit_state",
    cashWageFloor: 16.66,
    standardMinimumWage: 16.66,
    maxTipCredit: 0,
    tipPoolEligibleRoles: TIP_POOL_ELIGIBLE_ROLES,
    requiredNoticeElements: FEDERAL_REQUIRED_NOTICE_ELEMENTS,
  },
  MN: {
    ruleVersion: RULE_VERSION,
    eligibility: "no_tip_credit_state",
    cashWageFloor: 11.13,
    standardMinimumWage: 11.13,
    maxTipCredit: 0,
    tipPoolEligibleRoles: TIP_POOL_ELIGIBLE_ROLES,
    requiredNoticeElements: FEDERAL_REQUIRED_NOTICE_ELEMENTS,
  },
};

export function resolveStateRule(stateCode: string): StateRuleResult {
  const state = stateCode.trim().toUpperCase();
  const entry = STATE_RULE_LIBRARY[state];
  if (!entry) {
    return { state, eligibility: "unsupported_state" };
  }
  return { ...entry, state } as StateRuleResult;
}

export function isStateSupported(stateCode: string): boolean {
  return resolveStateRule(stateCode).eligibility !== "unsupported_state";
}
