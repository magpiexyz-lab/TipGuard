import { generateEmployeeNotice } from "@/lib/notice-generator";
import type { SupabaseClient } from "@supabase/supabase-js";

import { buildSampleFindings } from "@/app/violations/findings";

import type {
  AccountRow,
  EmployeeRow,
  NoticeRow,
  SignatureRow,
} from "@/lib/types";

/**
 * One demo restaurant, shared by every surface that has a demo fallback.
 *
 * /dashboard and /violations already told a specific story -- Ember & Rail, TX,
 * 14 tipped staff, 14 notices of which 9 are sent and 6 signed. /staff,
 * /notices and /audit-file had no demo path at all, so they queried the generic
 * demo client, matched nothing, and rendered zeros and empty states. Clicking
 * between header links therefore moved between a populated product and what
 * looked like a broken one.
 *
 * These fixtures reproduce the dashboard counts exactly so the whole app reads
 * as one account. Change a count here and the dashboard disagrees.
 */

export const DEMO_ACCOUNT_ID = "demo-account-id";
export const DEMO_RESTAURANT = "Ember & Rail";
export const DEMO_STATE = "TX";
/** Matches demoDashboard(): notices.total 14, sent 9, signed 6. */
export const DEMO_EMPLOYEE_COUNT = 14;
export const DEMO_SENT_COUNT = 9;
export const DEMO_SIGNED_COUNT = 6;

const STAFF: ReadonlyArray<{ name: string; role: string; rate: number; pool: boolean }> = [
  { name: "Marisol Vega", role: "server", rate: 2.13, pool: true },
  { name: "Dashawn Pierce", role: "bartender", rate: 2.13, pool: true },
  { name: "Priya Raman", role: "server", rate: 2.13, pool: true },
  { name: "Tomas Okafor", role: "busser", rate: 2.13, pool: true },
  { name: "Hannah Lindqvist", role: "server", rate: 2.13, pool: true },
  { name: "Ibrahim Salah", role: "bartender", rate: 2.13, pool: true },
  { name: "Rosa Delgado", role: "host", rate: 7.25, pool: false },
  { name: "Kenji Nakamura", role: "runner", rate: 2.13, pool: true },
  { name: "Adaeze Nwosu", role: "server", rate: 2.13, pool: true },
  { name: "Luca Bianchi", role: "barback", rate: 2.13, pool: true },
  { name: "Fatima Haddad", role: "server", rate: 2.13, pool: true },
  { name: "Grady Whitlock", role: "line cook", rate: 15.0, pool: true },
  { name: "Noor Abbasi", role: "server", rate: 2.13, pool: true },
  { name: "Emiliano Cruz", role: "busser", rate: 2.13, pool: true },
];

function slug(name: string): string {
  return name.toLowerCase().replace(/[^a-z]+/g, ".");
}

function daysAgo(now: number, days: number): string {
  return new Date(now - days * 86400000).toISOString();
}

export function demoEmployees(now: number): EmployeeRow[] {
  return STAFF.map((person, i) => ({
    id: "demo-emp-" + String(i + 1).padStart(2, "0"),
    account_id: DEMO_ACCOUNT_ID,
    name: person.name,
    email: slug(person.name) + "@emberandrail.test",
    role: person.role,
    hire_date: daysAgo(now, 40 + i * 23).slice(0, 10),
    hourly_rate: person.rate,
    state: DEMO_STATE,
    in_tip_pool: person.pool,
    created_at: daysAgo(now, 40 + i * 23),
  }));
}

/**
 * One notice per employee. The first DEMO_SIGNED_COUNT are signed, the next run
 * up to DEMO_SENT_COUNT are sent and awaiting signature, the remainder are
 * drafts -- which is the dashboard "6 of 14 generated, 8 still outstanding".
 */
export function demoNotices(now: number): NoticeRow[] {
  return demoEmployees(now).map((employee, i) => {
    const generated = generateEmployeeNotice({
      employeeName: employee.name,
      employerName: DEMO_RESTAURANT,
      state: employee.state,
      cashWagePaid: employee.hourly_rate,
    });
    const text =
      "error" in generated
        ? "Tip-credit notice for " + employee.name + "."
        : generated.noticeText;
    const status =
      i < DEMO_SIGNED_COUNT ? "signed" : i < DEMO_SENT_COUNT ? "sent" : "draft";
    return {
      id: "demo-notice-" + String(i + 1).padStart(2, "0"),
      account_id: DEMO_ACCOUNT_ID,
      employee_id: employee.id,
      state: employee.state,
      rule_version: "error" in generated ? "2026.1" : generated.ruleVersion,
      cash_wage_paid: employee.hourly_rate,
      tip_credit_claimed: employee.hourly_rate < 7.25,
      notice_text: text,
      status,
      sent_at: status === "draft" ? null : daysAgo(now, 12 - i),
      created_at: daysAgo(now, 14 - i),
    } as NoticeRow;
  });
}

export function demoSignatures(now: number): SignatureRow[] {
  const employees = demoEmployees(now);
  return demoNotices(now)
    .filter((notice) => notice.status === "signed")
    .map((notice, i) => ({
      id: "demo-sig-" + String(i + 1).padStart(2, "0"),
      account_id: DEMO_ACCOUNT_ID,
      notice_id: notice.id,
      signer_name: employees[i].name,
      signed_at: daysAgo(now, 10 - i),
      ip_address: "203.0.113." + (20 + i),
      user_agent: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_2 like Mac OS X)",
      notice_text_snapshot: notice.notice_text,
      created_at: daysAgo(now, 10 - i),
    }));
}

export function demoAccount(): AccountRow {
  return {
    id: DEMO_ACCOUNT_ID,
    user_id: "demo-user-id",
    restaurant_name: DEMO_RESTAURANT,
    home_state: DEMO_STATE,
    plan: "free",
    stripe_customer_id: null,
    current_period_end: null,
    readiness_score: 47,
    gap_list: null,
    scored_at: null,
    created_at: new Date(0).toISOString(),
  } as AccountRow;
}

/**
 * Minimal per-table stand-in for the service-role client, used only by the demo
 * context in resolveAccount(). Routes run their real queries against it, so the
 * demo surface exercises the real shaping, ranking and counting code -- if that
 * logic breaks, the demo breaks too and the bug is visible rather than masked.
 */
export function demoDb(now: number): SupabaseClient {
  const byTable: Record<string, unknown[]> = {
    accounts: [demoAccount()],
    employees: demoEmployees(now),
    notices: demoNotices(now),
    signatures: demoSignatures(now),
    pay_periods: [],
    violations: [],
  };
  const chain = (rows: unknown[]) => {
    const thenable: Record<string, unknown> = {
      select: () => thenable,
      eq: () => thenable,
      in: () => thenable,
      is: () => thenable,
      order: () => thenable,
      limit: () => thenable,
      maybeSingle: () => Promise.resolve({ data: rows[0] ?? null, error: null }),
      single: () => Promise.resolve({ data: rows[0] ?? null, error: null }),
      insert: () => Promise.resolve({ data: null, error: null }),
      update: () => Promise.resolve({ data: null, error: null }),
      delete: () => Promise.resolve({ data: null, error: null }),
      then: (resolve: (v: { data: unknown[]; error: null }) => unknown) =>
        resolve({ data: rows, error: null }),
    };
    return thenable;
  };
  return {
    from: (table: string) => chain(byTable[table] ?? []),
  } as unknown as SupabaseClient;
}

/**
 * Open findings, as row stubs. /audit-file counts these and /dashboard renders
 * them from the same buildSampleFindings source, so both surfaces report the
 * same number instead of disagreeing (0 against 4).
 */
export function demoOpenViolations(now: number): { id: string }[] {
  return buildSampleFindings(now)
    .filter((finding) => finding.status === "open")
    .map((finding) => ({ id: finding.id }));
}
