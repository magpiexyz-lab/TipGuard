// Questionnaire definition for the free audit-readiness score (b-02).
//
// This file is DATA ONLY. It declares the seven questions, their option copy,
// and the mapping from collected answers to the ScoringInput consumed by
// src/lib/scoring.ts. It deliberately contains no scoring arithmetic — the score
// is a deterministic pure function with legal consequence and lives in one place.

import type { NewHireProcess, NoticeCoverage, ScoringInput } from "@/lib/scoring";

// --- Answer shape ----------------------------------------------------------
// Answers are stored as the raw option keys the user clicked, not as
// ScoringInput values, so the questionnaire can be re-rendered exactly as it
// was answered (the left rail shows the chosen label on every answered step).

export type ClaimsAnswer = "yes" | "no";
export type TipPoolAnswer = "includes_ineligible" | "tipped_only" | "no_pool";
export type OvertimeAnswer = "full_minimum_wage" | "cash_wage" | "unsure";

export interface Answers {
  state?: string;
  claimsTipCredit?: ClaimsAnswer;
  noticeCoverage?: NoticeCoverage;
  tipPool?: TipPoolAnswer;
  overtimeBasis?: OvertimeAnswer;
  newHireProcess?: NewHireProcess;
  staffCount?: number;
}

// --- Question model --------------------------------------------------------

export interface ChoiceOption {
  value: string;
  label: string;
  detail: string;
  /** Short mono figure rendered on the right edge of the option row. */
  hint?: string;
}

export interface Question {
  id: keyof Answers;
  /** Short label for the left-rail step index. */
  railLabel: string;
  prompt: string;
  help: string;
  /** Evidence note shown beside the question — real statutory grounding. */
  note: string;
  citation: string;
  kind: "choice" | "number";
  options?: ChoiceOption[];
  /** Grid density for the option cluster. */
  columns?: 1 | 2;
  /** Questions only asked when this predicate holds. */
  when?: (answers: Answers) => boolean;
}

/**
 * The rule library in src/lib/state-rules.ts covers these six states today.
 * "OTHER" is an explicit, honest escape hatch — never a silent fallback that
 * would imply we know a state's cash-wage floor when we do not.
 */
export const STATE_OPTIONS: ChoiceOption[] = [
  { value: "TX", label: "Texas", detail: "Federal tip credit", hint: "$2.13" },
  { value: "FL", label: "Florida", detail: "State tip credit", hint: "$8.98" },
  { value: "NY", label: "New York", detail: "State tip credit", hint: "$10.65" },
  { value: "CA", label: "California", detail: "No tip credit permitted", hint: "$16.50" },
  { value: "WA", label: "Washington", detail: "No tip credit permitted", hint: "$16.66" },
  { value: "MN", label: "Minnesota", detail: "No tip credit permitted", hint: "$11.13" },
  {
    value: "OTHER",
    label: "Another state",
    detail: "Scored against the federal baseline",
    hint: "$2.13",
  },
];

const claimsTipCredit = (a: Answers) => a.claimsTipCredit === "yes";

export const QUESTIONS: Question[] = [
  {
    id: "state",
    railLabel: "Location",
    prompt: "Where do you run the tipped operation?",
    help: "The cash-wage floor, the maximum credit, and the notice wording all change at the state line.",
    note: "Several states have eliminated the tip credit outright. Claiming it there is a wage violation on every tipped hour, not a paperwork gap.",
    citation: "29 U.S.C. §203(m)(2)(A)",
    kind: "choice",
    columns: 2,
    options: STATE_OPTIONS,
  },
  {
    id: "claimsTipCredit",
    railLabel: "Tip credit",
    prompt: "Do you pay any tipped staff below the full minimum wage?",
    help: "That is the tip credit. If every employee is paid full minimum wage in cash, there is no credit to void.",
    note: "The tip credit is conditional, not automatic. Every condition below has to hold for the sub-minimum cash wage to be valid.",
    citation: "29 CFR §531.59",
    kind: "choice",
    options: [
      {
        value: "yes",
        label: "Yes — we claim the tip credit",
        detail: "Some staff are paid a cash wage below the full minimum wage.",
      },
      {
        value: "no",
        label: "No — everyone gets full minimum wage in cash",
        detail: "Tips are on top of the full minimum wage for every employee.",
      },
    ],
  },
  {
    id: "noticeCoverage",
    railLabel: "Signed notices",
    prompt: "How many tipped employees have a signed tip-credit notice on file?",
    help: "A dated acknowledgment, signed by the employee, that you can produce on request.",
    note: "The missing per-employee notice is the most-cited tip-credit failure. Without it the credit was never valid — retroactively, for every hour that employee ever worked.",
    citation: "29 CFR §531.59(b)",
    kind: "choice",
    when: claimsTipCredit,
    options: [
      {
        value: "all",
        label: "All of them",
        detail: "Every current tipped employee has a signed, dated notice you can produce.",
      },
      {
        value: "some",
        label: "Some of them",
        detail: "The file is partial — older hires, or a batch that was never collected.",
      },
      {
        value: "none",
        label: "None, or I am not sure",
        detail: "No signed file exists, or nobody can say where it is.",
      },
    ],
  },
  {
    id: "tipPool",
    railLabel: "Tip pool",
    prompt: "Who shares in the tip pool?",
    help: "Managers, supervisors, and back-of-house staff are not eligible to share tips in a tip-credit pool.",
    note: "One ineligible participant invalidates the whole pool. A working owner or a shift manager taking a share is the classic finding.",
    citation: "29 CFR §531.54(c)",
    kind: "choice",
    when: claimsTipCredit,
    options: [
      {
        value: "tipped_only",
        label: "Only customarily tipped roles",
        detail: "Servers, bartenders, bussers, hosts, runners, barbacks.",
      },
      {
        value: "includes_ineligible",
        label: "A manager or back-of-house worker shares it",
        detail: "A supervisor, owner, cook, or dishwasher takes part of the pool.",
      },
      {
        value: "no_pool",
        label: "There is no tip pool",
        detail: "Every employee keeps their own tips.",
      },
    ],
  },
  {
    id: "overtimeBasis",
    railLabel: "Overtime basis",
    prompt: "What wage is overtime calculated from?",
    help: "Overtime premium is computed on the full minimum wage, then the tip credit is subtracted — never the other way round.",
    note: "Time-and-a-half on the $2.13 cash wage is the single most common payroll error in tipped operations, and it recurs on every overtime hour.",
    citation: "29 CFR §531.60",
    kind: "choice",
    when: claimsTipCredit,
    options: [
      {
        value: "full_minimum_wage",
        label: "The full minimum wage",
        detail: "The premium is computed on the full minimum wage, then the credit is applied.",
      },
      {
        value: "cash_wage",
        label: "The sub-minimum cash wage",
        detail: "Time-and-a-half is computed on the cash wage the employee is paid.",
      },
      {
        value: "unsure",
        label: "I am not sure",
        detail:
          "Counted as a gap. In an audit you have to demonstrate the basis, and an unverified answer cannot be demonstrated.",
      },
    ],
  },
  {
    id: "newHireProcess",
    railLabel: "New hires",
    prompt: "Do new hires sign the notice before their first shift?",
    help: "The notice must be given before the tip credit is taken — it does not apply retroactively.",
    note: "Turnover is what makes a complete file go stale. A file that was correct last quarter is not a defense for a server hired in March.",
    citation: "29 CFR §531.59(b)",
    kind: "choice",
    when: claimsTipCredit,
    options: [
      {
        value: "consistent",
        label: "Always, before the first shift",
        detail: "It is a fixed step in onboarding and it is signed and filed.",
      },
      {
        value: "inconsistent",
        label: "Usually, but not every time",
        detail: "It happens when someone remembers, or it is signed late.",
      },
      {
        value: "none",
        label: "There is no process",
        detail: "New hires start without a notice.",
      },
    ],
  },
  {
    id: "staffCount",
    railLabel: "Staff count",
    prompt: "How many tipped employees do you have?",
    help: "Across every location. This scales the exposure estimate — back pay is owed per employee, per hour.",
    note: "Back-pay liability is multiplied by liquidated damages, so the headcount is the multiplier on everything above.",
    citation: "29 U.S.C. §216(b)",
    kind: "number",
  },
];

export const MIN_STAFF_COUNT = 1;
export const MAX_STAFF_COUNT = 500;

/** The questions actually asked, given the answers so far. */
export function visibleQuestions(answers: Answers): Question[] {
  return QUESTIONS.filter((question) => !question.when || question.when(answers));
}

export function isAnswered(question: Question, answers: Answers): boolean {
  const value = answers[question.id];
  if (question.id === "staffCount") {
    return typeof value === "number" && Number.isFinite(value);
  }
  return typeof value === "string" && value.length > 0;
}

/** Human-readable answer for the left-rail summary. */
export function answerLabel(question: Question, answers: Answers): string | null {
  if (!isAnswered(question, answers)) return null;
  if (question.kind === "number") return String(answers.staffCount);
  const raw = answers[question.id] as string;
  return question.options?.find((option) => option.value === raw)?.label ?? raw;
}

/**
 * Maps collected answers onto the ScoringInput contract. Two deliberate
 * translations, both disclosed in the option copy the user reads:
 *   - "no tip pool" and "only tipped roles" both mean no ineligible participant.
 *   - "I am not sure" about the overtime basis is treated as the sub-minimum
 *     basis, because an unverifiable basis is exactly what fails in an audit.
 */
export function toScoringInput(answers: Answers): ScoringInput {
  return {
    state: answers.state ?? "OTHER",
    claimsTipCredit: answers.claimsTipCredit === "yes",
    noticeCoverage: (answers.noticeCoverage ?? "none") as NoticeCoverage,
    tipPoolIncludesIneligibleWorkers: answers.tipPool === "includes_ineligible",
    overtimeBasis: answers.overtimeBasis === "full_minimum_wage" ? "full_minimum_wage" : "cash_wage",
    newHireProcess: (answers.newHireProcess ?? "none") as NewHireProcess,
    staffCount: answers.staffCount ?? 0,
  };
}
