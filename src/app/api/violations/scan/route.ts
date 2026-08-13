import { NextResponse } from "next/server";
import { resolveAccount } from "@/lib/api-auth";
import { trackServerEvent } from "@/lib/analytics-server";
import { resolveStateRule, RULE_VERSION } from "@/lib/state-rules";
import {
  checkNoticeStatus,
  checkOvertimeBasis,
  checkSubminimumShortfall,
  checkTipPoolEligibility,
  type ViolationFinding,
} from "@/lib/violation-rules";
import type { EmployeeRow, NoticeRow, PayPeriodRow } from "@/lib/types";

export const dynamic = "force-dynamic";

/**
 * b-08 (actor: system) — run the tip-credit rule set over roster, hours and
 * notice records.
 *
 * Detection is entirely the four pure functions in
 * `src/lib/violation-rules.ts`; this route is plumbing. Nothing here calls the
 * AI module — a finding that determines back-pay exposure has to be
 * reproducible and unit-testable, not model output.
 *
 * Re-running replaces the OPEN findings and leaves RESOLVED ones untouched, so
 * a fixed problem stays in the audit record while a problem that no longer
 * exists stops being reported.
 */

export type ScanViolationsResponse = {
  open_finding_count: number;
  detected: number;
  scanned_at: string;
};

interface PendingFinding extends ViolationFinding {
  employeeId: string | null;
}

export async function POST() {
  const resolved = await resolveAccount({ create: true });
  if (!resolved.ok) {
    if (resolved.reason === "unauthenticated") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json({ error: "Service unavailable" }, { status: 503 });
  }
  const { account, db, userId } = resolved.ctx;

  const [employeesResult, periodsResult, noticesResult] = await Promise.all([
    db
      .from("employees")
      .select("id, name, role, hourly_rate, state, in_tip_pool")
      .eq("account_id", account.id),
    db
      .from("pay_periods")
      .select(
        "id, employee_id, period_start, period_end, hours_worked, overtime_hours, overtime_rate_used, tips_reported, cash_wage_paid"
      )
      .eq("account_id", account.id),
    db
      .from("notices")
      .select("id, employee_id, status, rule_version")
      .eq("account_id", account.id),
  ]);

  if (employeesResult.error || periodsResult.error || noticesResult.error) {
    console.error(
      "[violations/scan] Supabase error:",
      employeesResult.error ?? periodsResult.error ?? noticesResult.error
    );
    return NextResponse.json({ error: "The compliance scan could not run" }, { status: 500 });
  }

  const employees = (employeesResult.data ?? []) as Pick<
    EmployeeRow,
    "id" | "name" | "role" | "hourly_rate" | "state" | "in_tip_pool"
  >[];
  const periods = (periodsResult.data ?? []) as Pick<
    PayPeriodRow,
    | "id"
    | "employee_id"
    | "period_start"
    | "period_end"
    | "hours_worked"
    | "overtime_hours"
    | "overtime_rate_used"
    | "tips_reported"
    | "cash_wage_paid"
  >[];
  const notices = (noticesResult.data ?? []) as Pick<
    NoticeRow,
    "id" | "employee_id" | "status" | "rule_version"
  >[];

  const noticeByEmployee = new Map(notices.map((notice) => [notice.employee_id, notice]));
  const periodsByEmployee = new Map<string, typeof periods>();
  for (const period of periods) {
    const list = periodsByEmployee.get(period.employee_id) ?? [];
    list.push(period);
    periodsByEmployee.set(period.employee_id, list);
  }

  const findings: PendingFinding[] = [];
  const push = (employeeId: string | null, finding: ViolationFinding | null) => {
    if (finding) findings.push({ ...finding, employeeId });
  };

  for (const employee of employees) {
    const rule = resolveStateRule(employee.state || account.home_state || "");

    // --- Rule 4: missing / unsigned / stale notice (no pay data required) ---
    const notice = noticeByEmployee.get(employee.id);
    push(
      employee.id,
      checkNoticeStatus({
        noticeExists: Boolean(notice),
        noticeStatus: notice?.status,
        noticeRuleVersion: notice?.rule_version,
        currentRuleVersion: RULE_VERSION,
      })
    );

    // The remaining three rule classes need a resolved state rule set. An
    // unsupported state is reported by notice generation, not fabricated here.
    if (rule.eligibility === "unsupported_state") continue;

    // --- Rule 2: ineligible worker in the tip pool ---
    push(
      employee.id,
      checkTipPoolEligibility({
        employeeRole: employee.role,
        isInTipPool: employee.in_tip_pool !== false,
        eligibleRoles: rule.tipPoolEligibleRoles,
      })
    );

    for (const period of periodsByEmployee.get(employee.id) ?? []) {
      // --- Rule 1: overtime computed off the sub-minimum cash wage ---
      const cashWage = Number(period.cash_wage_paid) || Number(employee.hourly_rate) || 0;
      push(
        employee.id,
        checkOvertimeBasis({
          fullMinimumWage: rule.standardMinimumWage,
          overtimeHours: Number(period.overtime_hours) || 0,
          // No recorded premium means it was paid off the cash wage — that is
          // the violation this rule exists to catch, so it is the safe default.
          overtimeRateUsed:
            period.overtime_rate_used === null || period.overtime_rate_used === undefined
              ? cashWage * 1.5
              : Number(period.overtime_rate_used),
        })
      );

      // --- Rule 3: cash wage plus tips below the applicable minimum ---
      push(
        employee.id,
        checkSubminimumShortfall({
          cashWagePaid: cashWage,
          hoursWorked: Number(period.hours_worked) || 0,
          tipsReceived: Number(period.tips_reported) || 0,
          applicableMinimumWage: rule.standardMinimumWage,
        })
      );
    }
  }

  // Replace the open set; resolved findings stay as audit record.
  const { error: clearError } = await db
    .from("violations")
    .delete()
    .eq("account_id", account.id)
    .eq("status", "open");
  if (clearError) {
    console.error("[violations/scan] could not clear stale findings:", clearError);
    return NextResponse.json({ error: "The compliance scan could not run" }, { status: 500 });
  }

  const detectedAt = new Date().toISOString();
  let persisted = 0;

  for (const finding of findings) {
    const { data, error } = await db
      .from("violations")
      .insert({
        account_id: account.id,
        employee_id: finding.employeeId,
        rule_class: finding.ruleClass,
        severity: finding.severity,
        estimated_exposure_usd: finding.estimatedExposureUsd,
        status: "open",
        detail: finding.detail,
        detected_at: detectedAt,
      })
      .select("id")
      .single();

    if (error || !data) {
      console.error("[violations/scan] finding insert failed:", error);
      continue;
    }
    persisted += 1;

    // ACTIVATION EVENT — one per finding (b-08).
    await trackServerEvent("violation_detected", userId, {
      rule_class: finding.ruleClass,
      severity: finding.severity,
      estimated_exposure_usd: finding.estimatedExposureUsd,
      funnel_stage: "activate",
    });
  }

  // Records that a scan HAPPENED. Without this an account whose first scan
  // comes back genuinely clean is indistinguishable from one that never
  // scanned, and /violations shows "run your first scan" forever.
  const { error: stampError } = await db
    .from("accounts")
    .update({ last_scan_at: detectedAt })
    .eq("id", account.id);
  if (stampError) console.error("[violations/scan] last_scan_at stamp failed:", stampError);

  return NextResponse.json({
    open_finding_count: persisted,
    detected: persisted,
    scanned_at: detectedAt,
  } satisfies ScanViolationsResponse);
}
