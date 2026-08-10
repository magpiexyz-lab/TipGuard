import { NextResponse } from "next/server";
import { resolveAccount } from "@/lib/api-auth";
import type { EmployeeRow, NoticeRow } from "@/lib/types";
import type { NoticeWithEmployee } from "@/app/notices/notice-types";

export const dynamic = "force-dynamic";

export const NOTICE_COLUMNS =
  "id, account_id, employee_id, state, rule_version, cash_wage_paid, tip_credit_claimed, notice_text, status, sent_at, created_at";

export type ListNoticesResponse = { notices: NoticeWithEmployee[] };

/**
 * Joins notice rows to their employee in JS rather than with a PostgREST
 * embed. Two explicit queries keep the column lists visible (no `select("*")`)
 * and behave identically under the demo client, which does not model
 * relationships.
 */
export async function joinNoticesToEmployees(
  notices: NoticeRow[],
  employees: Pick<EmployeeRow, "id" | "name" | "email" | "role">[]
): Promise<NoticeWithEmployee[]> {
  const byId = new Map(employees.map((employee) => [employee.id, employee]));
  return notices.map((notice) => ({
    ...notice,
    employee: byId.get(notice.employee_id) ?? {
      id: notice.employee_id,
      name: "Unknown employee",
      email: "",
      role: "",
    },
  }));
}

/** b-06 — the notice ledger: every employee with status and rendered text. */
export async function GET() {
  const resolved = await resolveAccount();
  if (!resolved.ok) {
    if (resolved.reason === "unauthenticated") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    if (resolved.reason === "no_account") {
      return NextResponse.json({ notices: [] } satisfies ListNoticesResponse);
    }
    return NextResponse.json({ error: "Service unavailable" }, { status: 503 });
  }

  const { account, db } = resolved.ctx;

  const [noticesResult, employeesResult] = await Promise.all([
    db
      .from("notices")
      .select(NOTICE_COLUMNS)
      .eq("account_id", account.id)
      .order("created_at", { ascending: true }),
    db.from("employees").select("id, name, email, role").eq("account_id", account.id),
  ]);

  if (noticesResult.error || employeesResult.error) {
    console.error(
      "[notices] Supabase error:",
      noticesResult.error ?? employeesResult.error
    );
    return NextResponse.json({ error: "Could not read your notices" }, { status: 500 });
  }

  const notices = await joinNoticesToEmployees(
    (noticesResult.data ?? []) as NoticeRow[],
    (employeesResult.data ?? []) as Pick<EmployeeRow, "id" | "name" | "email" | "role">[]
  );

  return NextResponse.json({ notices } satisfies ListNoticesResponse);
}
