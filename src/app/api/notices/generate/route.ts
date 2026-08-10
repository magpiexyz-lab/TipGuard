import { NextResponse } from "next/server";
import { z } from "zod";
import { resolveAccount } from "@/lib/api-auth";
import { NOTICE_COLUMNS, joinNoticesToEmployees } from "@/app/api/notices/route";
import { generateEmployeeNotice } from "@/lib/notice-generator";
import { RULE_VERSION } from "@/lib/state-rules";
import { trackServerEvent } from "@/lib/analytics-server";
import type { EmployeeRow, NoticeRow } from "@/lib/types";
import type { NoticeWithEmployee } from "@/app/notices/notice-types";

export const dynamic = "force-dynamic";

/**
 * b-05 (actor: system) — generate one state-specific notice per employee.
 *
 * Rule resolution and rendering are the pure functions in
 * `src/lib/state-rules.ts` and `src/lib/notice-generator.ts`. This route only
 * persists their output. It never calls the AI module: a notice is a legal
 * document generated from a versioned rule table, and every one of them
 * carries the counsel-review disclaimer that `notice-generator.ts` appends.
 *
 * An employee in a state the rule library does not cover is SKIPPED and
 * reported — never given a notice fabricated from federal defaults, which
 * would manufacture the exact compliance gap this product exists to close.
 */

export const generateNoticesSchema = z.object({
  /** Optional subset; omitted means "every employee missing a current notice". */
  employee_ids: z.array(z.uuid()).max(500).optional(),
});

export interface NoticeGenerationSkip {
  employee_id: string;
  employee_name: string;
  reason: string;
}

export type GenerateNoticesResponse = {
  notices: NoticeWithEmployee[];
  generated: number;
  skipped: NoticeGenerationSkip[];
};

export async function POST(request: Request) {
  let input: z.infer<typeof generateNoticesSchema>;
  try {
    const raw = await request.json().catch(() => ({}));
    input = generateNoticesSchema.parse(raw ?? {});
  } catch {
    return NextResponse.json({ error: "Invalid request" }, { status: 400 });
  }

  const resolved = await resolveAccount({ create: true });
  if (!resolved.ok) {
    if (resolved.reason === "unauthenticated") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json({ error: "Service unavailable" }, { status: 503 });
  }
  const { account, db, userId } = resolved.ctx;

  const employeesQuery = db
    .from("employees")
    .select("id, name, email, role, hourly_rate, state")
    .eq("account_id", account.id);
  if (input.employee_ids && input.employee_ids.length > 0) {
    employeesQuery.in("id", input.employee_ids);
  }

  const [employeesResult, existingResult] = await Promise.all([
    employeesQuery,
    db
      .from("notices")
      .select(NOTICE_COLUMNS)
      .eq("account_id", account.id),
  ]);

  if (employeesResult.error || existingResult.error) {
    console.error(
      "[notices/generate] Supabase error:",
      employeesResult.error ?? existingResult.error
    );
    return NextResponse.json({ error: "Could not generate notices" }, { status: 500 });
  }

  const employees = (employeesResult.data ?? []) as Pick<
    EmployeeRow,
    "id" | "name" | "email" | "role" | "hourly_rate" | "state"
  >[];
  const existing = (existingResult.data ?? []) as NoticeRow[];
  const currentByEmployee = new Set(
    existing
      .filter((notice) => notice.rule_version === RULE_VERSION)
      .map((notice) => notice.employee_id)
  );

  const employerName = account.restaurant_name || "Your restaurant";
  const created: NoticeRow[] = [];
  const skipped: NoticeGenerationSkip[] = [];

  for (const employee of employees) {
    if (currentByEmployee.has(employee.id)) continue;

    const state = (employee.state || account.home_state || "").trim();
    const generated = generateEmployeeNotice({
      employeeName: employee.name,
      employerName,
      state,
      cashWagePaid: Number(employee.hourly_rate) || 0,
    });

    if ("error" in generated) {
      skipped.push({
        employee_id: employee.id,
        employee_name: employee.name,
        reason: `TipGuard does not yet carry a verified tip-credit rule set for ${
          generated.state || "this state"
        }. No notice was generated rather than one built from unverified defaults.`,
      });
      continue;
    }

    const { data, error } = await db
      .from("notices")
      .insert({
        account_id: account.id,
        employee_id: employee.id,
        state: generated.state,
        rule_version: generated.ruleVersion,
        cash_wage_paid: generated.cashWagePaid,
        tip_credit_claimed: generated.tipCreditClaimed,
        notice_text: generated.noticeText,
        status: "draft",
      })
      .select(NOTICE_COLUMNS)
      .single();

    if (error || !data) {
      console.error("[notices/generate] Supabase error:", error);
      skipped.push({
        employee_id: employee.id,
        employee_name: employee.name,
        reason: "The notice could not be saved. Try again in a moment.",
      });
      continue;
    }

    const row = data as NoticeRow;
    created.push(row);

    // ACTIVATION EVENT — one per generated notice (b-05, h-05 numerator).
    await trackServerEvent("notice_generated", userId, {
      notice_id: row.id,
      state: row.state,
      rule_version: row.rule_version,
      tip_credit_claimed: row.tip_credit_claimed,
      funnel_stage: "activate",
    });
  }

  // Return the full ledger so the page can replace its list in one hop.
  const [allNoticesResult, allEmployeesResult] = await Promise.all([
    db
      .from("notices")
      .select(NOTICE_COLUMNS)
      .eq("account_id", account.id)
      .order("created_at", { ascending: true }),
    db.from("employees").select("id, name, email, role").eq("account_id", account.id),
  ]);

  const notices = await joinNoticesToEmployees(
    (allNoticesResult.data ?? []) as NoticeRow[],
    (allEmployeesResult.data ?? []) as Pick<
      EmployeeRow,
      "id" | "name" | "email" | "role"
    >[]
  );

  return NextResponse.json({
    notices,
    generated: created.length,
    skipped,
  } satisfies GenerateNoticesResponse);
}
