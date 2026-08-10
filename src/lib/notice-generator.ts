// Per-employee tip-credit notice rendering (b-05).
//
// Pure function — resolves the state rule via state-rules.ts and fills a
// notice from it. No AI, no network. Prose polish of this text (if ever
// applied) is a strictly downstream, optional step via src/lib/ai.ts — the
// disclaimer below is never conditioned on whether that step ran, and no
// caller may claim attorney certification.

import {
  resolveStateRule,
  type EligibleStateRule,
  type NoTipCreditStateRule,
} from "./state-rules";

type ResolvedStateRule = EligibleStateRule | NoTipCreditStateRule;

export const COUNSEL_REVIEW_DISCLAIMER =
  "This notice was generated from TipGuard's state tip-credit rule library. " +
  "It has not been reviewed or certified by an attorney. Review by your counsel before distribution.";

export interface EmployeeNoticeInput {
  employeeName: string;
  employerName: string;
  /** Two-letter US state code. */
  state: string;
  cashWagePaid: number;
}

export interface GeneratedNotice {
  employeeName: string;
  employerName: string;
  state: string;
  ruleVersion: string;
  tipCreditClaimed: boolean;
  cashWagePaid: number;
  maxTipCredit: number;
  noticeText: string;
  disclaimer: string;
  generatedAt: string;
}

export interface UnsupportedStateNoticeError {
  error: "unsupported_state";
  state: string;
}

export function generateEmployeeNotice(
  input: EmployeeNoticeInput
): GeneratedNotice | UnsupportedStateNoticeError {
  const rule = resolveStateRule(input.state);

  if (rule.eligibility === "unsupported_state") {
    // Explicit unsupported result — never fabricate a notice from federal
    // defaults for a state we have not verified.
    return { error: "unsupported_state", state: rule.state };
  }

  const tipCreditClaimed = rule.eligibility === "eligible";
  const noticeText = renderNoticeText(input, rule, tipCreditClaimed);

  return {
    employeeName: input.employeeName,
    employerName: input.employerName,
    state: rule.state,
    ruleVersion: rule.ruleVersion,
    tipCreditClaimed,
    cashWagePaid: input.cashWagePaid,
    maxTipCredit: tipCreditClaimed ? rule.maxTipCredit : 0,
    noticeText,
    disclaimer: COUNSEL_REVIEW_DISCLAIMER,
    generatedAt: new Date().toISOString(),
  };
}

function renderNoticeText(
  input: EmployeeNoticeInput,
  rule: ResolvedStateRule,
  tipCreditClaimed: boolean
): string {
  const lines: string[] = [];
  lines.push(`TIP CREDIT NOTICE — ${input.employerName}`);
  lines.push(`Employee: ${input.employeeName}`);
  lines.push(`State: ${rule.state}`);
  lines.push(`Rule version: ${rule.ruleVersion}`);
  lines.push("");

  if (tipCreditClaimed) {
    lines.push(`Cash wage paid: $${input.cashWagePaid.toFixed(2)}/hr`);
    lines.push(`Tip credit claimed: $${rule.maxTipCredit.toFixed(2)}/hr`);
    lines.push(`Full applicable minimum wage: $${rule.standardMinimumWage.toFixed(2)}/hr`);
    lines.push("");
    lines.push("Required notice elements:");
    rule.requiredNoticeElements.forEach((element, i) => {
      lines.push(`${i + 1}. ${element}`);
    });
  } else {
    lines.push(
      `${rule.state} does not permit a tip credit. You are paid the full state ` +
        `minimum wage of $${rule.standardMinimumWage.toFixed(2)}/hr regardless of tips received.`
    );
  }

  lines.push("");
  lines.push(COUNSEL_REVIEW_DISCLAIMER);

  return lines.join("\n");
}
