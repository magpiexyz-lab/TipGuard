import { NextResponse } from "next/server";
import { resolveAccount } from "@/lib/api-auth";
import type { EmployeeRow } from "@/lib/types";

export const dynamic = "force-dynamic";

/** Explicit column list — RLS gates rows, not columns (database/supabase.md § Security). */
export const EMPLOYEE_COLUMNS =
  "id, account_id, name, email, role, hire_date, hourly_rate, state, in_tip_pool, created_at";

export type ListStaffResponse = { employees: EmployeeRow[] };

/** b-04 — the owner's roster. Scoped to their account by RLS and by `.eq()`. */
export async function GET() {
  const resolved = await resolveAccount();
  if (!resolved.ok) {
    if (resolved.reason === "unauthenticated") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    if (resolved.reason === "no_account") {
      // Signed in but nothing provisioned yet — an empty roster, not an error.
      return NextResponse.json({ employees: [] } satisfies ListStaffResponse);
    }
    return NextResponse.json({ error: "Service unavailable" }, { status: 503 });
  }

  const { account, db } = resolved.ctx;
  const { data, error } = await db
    .from("employees")
    .select(EMPLOYEE_COLUMNS)
    .eq("account_id", account.id)
    .order("created_at", { ascending: true });

  if (error) {
    console.error("[staff] Supabase error:", error);
    return NextResponse.json({ error: "Could not read your roster" }, { status: 500 });
  }

  return NextResponse.json({
    employees: (data ?? []) as EmployeeRow[],
  } satisfies ListStaffResponse);
}
