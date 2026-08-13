// Canonical finding presentation model + demo fixtures for /violations (b-09).
//
// This module is the single source of truth for how a raw `violations` row
// becomes something an owner can ACT on: a plain-English title, an explanation
// of what was actually broken, and one concrete fix. Detection is owned
// entirely by `src/lib/violation-rules.ts` (pure, deterministic, unit-tested) —
// nothing here re-derives a finding, it only renders one. Per b-09 the UI never
// surfaces a raw rule citation.
//
// /dashboard imports from here too (open-finding summary + total exposure), so
// this file deliberately carries no "use client" directive and no React import.

import type {
  ViolationRow,
  ViolationRuleClass,
  ViolationSeverity,
  ViolationStatus,
} from "@/lib/types";

// --- Rule-class presentation ------------------------------------------------

export interface RuleClassMeta {
  /** Plain-English name. Never a CFR / statute citation. */
  title: string;
  /** One-line scannable summary for the ledger row. */
  summary: string;
  /** What was broken and why it costs money, in an operator's language. */
  explanation: string;
  /** The single concrete action that closes this finding. */
  fixAction: string;
  /** Where the owner goes to perform the fix. */
  fixHref: string;
  fixLabel: string;
}

export const RULE_CLASS_META: Record<ViolationRuleClass, RuleClassMeta> = {
  overtime_base: {
    title: "Overtime was paid on the tipped wage",
    summary: "Overtime premium computed off the cash wage instead of the full minimum wage",
    explanation:
      "Overtime for a tipped employee has to be figured on the full minimum wage — not on the reduced cash wage you actually hand them. Paying time-and-a-half on the lower number underpays every overtime hour, and it is the single easiest thing for an investigator to recompute from your own payroll export.",
    fixAction:
      "Recalculate the overtime premium at 1.5x the full minimum wage for each affected pay period and issue the difference as back pay on the next payroll run.",
    fixHref: "/staff",
    fixLabel: "Review affected pay periods",
  },
  ineligible_tip_pool: {
    title: "A non-tipped role is sharing the tip pool",
    summary: "A manager or back-of-house worker is taking a share of the pool",
    explanation:
      "Only staff who customarily and regularly receive tips may share a tip pool. The moment a manager or a back-of-house employee takes a share, the tip credit is void for everyone in that pool — not just for the ineligible person. One name on the wrong list converts the whole pool into exposure.",
    fixAction:
      "Remove the flagged employee from the tip pool, redistribute their share to eligible staff for the affected periods, and re-run the scan to confirm the pool is clean.",
    fixHref: "/staff",
    fixLabel: "Edit tip-pool roles",
  },
  subminimum_shortfall: {
    title: "Cash wage plus tips fell below minimum wage",
    summary: "A workweek closed below the applicable minimum wage after tips",
    explanation:
      "A tipped employee has to finish every workweek at or above the full applicable minimum wage once tips are counted. When tips come up short, you owe the difference — a slow week is the employer's cost, not the employee's. Unpaid shortfalls carry liquidated damages on top of the back pay.",
    fixAction:
      "Pay the shortfall for each flagged workweek, then add a per-period top-up check so a slow week is caught before payroll closes instead of after.",
    fixHref: "/staff",
    fixLabel: "Open the pay-period ledger",
  },
  missing_notice: {
    title: "An employee has no signed tip-credit notice",
    summary: "No current, signed acknowledgment on file for this employee",
    explanation:
      "The tip credit only applies to an employee who received the notice before the work was done and acknowledged it. With no signed notice on file, the reduced cash rate was never valid for that person — retroactively, for every tipped hour they have ever worked for you. This is the first document an investigator asks for.",
    fixAction:
      "Generate this employee's state-specific notice and send it for signature. The signed copy lands in the vault with a timestamp and becomes part of your audit file.",
    fixHref: "/notices",
    fixLabel: "Send the notice for signature",
  },
};

// --- Severity presentation --------------------------------------------------

export interface SeverityMeta {
  label: string;
  /** Status-chip classes: 12% tint background, full-strength semantic text. */
  chipClass: string;
  /** Severity rank used as the tie-break when exposure is equal. */
  rank: number;
}

export const SEVERITY_META: Record<ViolationSeverity, SeverityMeta> = {
  critical: {
    label: "Critical",
    chipClass: "bg-destructive/10 text-destructive",
    rank: 3,
  },
  high: {
    label: "High",
    chipClass: "bg-primary/15 text-brass-deep dark:text-primary",
    rank: 2,
  },
  medium: {
    label: "Medium",
    chipClass: "bg-muted text-muted-foreground",
    rank: 1,
  },
};

// --- The view model the pages render ---------------------------------------

export interface FindingView {
  id: string;
  ruleClass: ViolationRuleClass;
  severity: ViolationSeverity;
  status: ViolationStatus;
  estimatedExposureUsd: number;
  /** Detector-authored plain-English detail (from src/lib/violation-rules.ts). */
  detail: string;
  /** Pre-formatted on the server so a client re-render cannot drift. */
  detectedLabel: string;
  daysOpen: number;
  employeeName: string | null;
  employeeRole: string | null;
}

const MS_PER_DAY = 86_400_000;

/** Whole days between an ISO timestamp and `now`. Pure — `now` is injected. */
export function daysSince(isoDate: string, now: number): number {
  const then = Date.parse(isoDate);
  if (Number.isNaN(then)) return 0;
  return Math.max(0, Math.floor((now - then) / MS_PER_DAY));
}

export function formatUsd(amount: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(amount);
}

/** Stable UTC formatting — identical on the server and after hydration. */
export function formatRecordDate(isoDate: string): string {
  const parsed = Date.parse(isoDate);
  if (Number.isNaN(parsed)) return "—";
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "UTC",
    year: "numeric",
    month: "short",
    day: "2-digit",
  }).format(new Date(parsed));
}

/**
 * Exposure display. A missing-notice finding is scored at $0 by the detector
 * because it voids the credit rather than producing a computable delta — show
 * that honestly instead of implying the finding is harmless.
 */
export function exposureLabel(finding: FindingView): string {
  if (finding.estimatedExposureUsd > 0) return formatUsd(finding.estimatedExposureUsd);
  return "Unquantified";
}

export function toFindingView(
  row: ViolationRow,
  employee: { name: string; role: string } | null,
  now: number
): FindingView {
  return {
    id: row.id,
    ruleClass: row.rule_class,
    severity: row.severity,
    status: row.status,
    estimatedExposureUsd: Number(row.estimated_exposure_usd) || 0,
    detail: row.detail,
    detectedLabel: formatRecordDate(row.detected_at),
    daysOpen: daysSince(row.resolved_at ?? row.detected_at, now),
    employeeName: employee?.name ?? null,
    employeeRole: employee?.role ?? null,
  };
}

/** b-09: open findings are ranked by estimated exposure, severity breaks ties. */
export function byExposureDesc(a: FindingView, b: FindingView): number {
  if (b.estimatedExposureUsd !== a.estimatedExposureUsd) {
    return b.estimatedExposureUsd - a.estimatedExposureUsd;
  }
  return SEVERITY_META[b.severity].rank - SEVERITY_META[a.severity].rank;
}

export function totalExposure(findings: readonly FindingView[]): number {
  return findings.reduce((sum, f) => sum + f.estimatedExposureUsd, 0);
}

// --- Demo fixtures ----------------------------------------------------------

/**
 * True when no real Supabase project is wired up (local `npm run build`,
 * preview deploys, DEMO_MODE). Mirrors the placeholder detection inside
 * `src/lib/supabase-server.ts` exactly: when that module falls back to its
 * demo client, `.from()` returns generic seed rows that do not match the
 * TipGuard schema, so the pages read from the fixtures below instead of
 * rendering nonsense.
 */
export function usesDemoData(): boolean {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
  const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";
  return (
    process.env.DEMO_MODE === "true" ||
    !url ||
    !anon ||
    url === "https://placeholder.supabase.co"
  );
}

interface FindingSeed {
  id: string;
  ruleClass: ViolationRuleClass;
  severity: ViolationSeverity;
  status: ViolationStatus;
  estimatedExposureUsd: number;
  detail: string;
  daysOpen: number;
  employeeName: string | null;
  employeeRole: string | null;
}

/**
 * Canonical demo findings. Every `detail` string below is the exact shape
 * `src/lib/violation-rules.ts` emits for that rule class — the fixtures model
 * the real detector output rather than inventing a parallel vocabulary.
 */
export const SAMPLE_FINDING_SEEDS: readonly FindingSeed[] = [
  {
    id: "demo-finding-ot",
    ruleClass: "overtime_base",
    severity: "critical",
    status: "open",
    estimatedExposureUsd: 4180,
    detail:
      "Overtime premium was calculated at $3.20/hr instead of the required $10.88/hr (1.5x the full minimum wage).",
    daysOpen: 9,
    employeeName: "Marisol Vega",
    employeeRole: "Server",
  },
  {
    id: "demo-finding-pool",
    ruleClass: "ineligible_tip_pool",
    severity: "critical",
    status: "open",
    estimatedExposureUsd: 2940,
    detail: '"Kitchen Manager" is not an eligible tipped role and must not share in the tip pool.',
    daysOpen: 4,
    employeeName: "Devon Pryce",
    employeeRole: "Kitchen Manager",
  },
  {
    id: "demo-finding-shortfall",
    ruleClass: "subminimum_shortfall",
    severity: "high",
    status: "open",
    estimatedExposureUsd: 1265,
    detail:
      "Cash wage plus tips ($284.60) fell short of the required minimum-wage earnings ($377.00) for the workweek by $92.40.",
    daysOpen: 2,
    employeeName: "Ana Okafor",
    employeeRole: "Bartender",
  },
  {
    id: "demo-finding-notice",
    ruleClass: "missing_notice",
    severity: "critical",
    status: "open",
    estimatedExposureUsd: 0,
    detail: "The tip-credit notice has not been signed by the employee.",
    daysOpen: 6,
    employeeName: "Theo Brandt",
    employeeRole: "Server",
  },
  {
    id: "demo-finding-resolved",
    ruleClass: "missing_notice",
    severity: "critical",
    status: "resolved",
    estimatedExposureUsd: 0,
    detail: "No tip-credit notice has been generated for this employee.",
    daysOpen: 11,
    employeeName: "Priya Raman",
    employeeRole: "Busser",
  },
];

/** Deterministic given `now` — no hidden clock reads, so SSR output is stable. */
export function buildSampleFindings(now: number): FindingView[] {
  return SAMPLE_FINDING_SEEDS.map((seed) => {
    const detectedIso = new Date(now - seed.daysOpen * MS_PER_DAY).toISOString();
    return {
      id: seed.id,
      ruleClass: seed.ruleClass,
      severity: seed.severity,
      status: seed.status,
      estimatedExposureUsd: seed.estimatedExposureUsd,
      detail: seed.detail,
      detectedLabel: formatRecordDate(detectedIso),
      daysOpen: seed.daysOpen,
      employeeName: seed.employeeName,
      employeeRole: seed.employeeRole,
    };
  });
}
