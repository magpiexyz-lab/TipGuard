import { NextResponse } from "next/server";
import { z } from "zod";
import { resolveAccount, statusForReason } from "@/lib/api-auth";
import { EMPLOYEE_COLUMNS } from "@/app/api/staff/route";
import type { EmployeeRow } from "@/lib/types";
import type { SupabaseClient } from "@supabase/supabase-js";

export const dynamic = "force-dynamic";

/**
 * b-04 — roster import.
 *
 * The load-bearing contract: **a malformed sibling row never aborts the
 * import**. `src/lib/roster-csv.ts` already rejected the rows it could see as
 * broken client-side; this route re-validates every surviving row server-side
 * (the client is not a validator, it is a convenience) and then inserts them
 * ONE AT A TIME. A single batch insert would mean one constraint violation
 * discards the other 39 valid employees — the exact failure mode b-04's second
 * test forbids.
 *
 * That contract governs VALIDATION too: only the envelope (`rows` is a
 * non-empty array within the batch ceiling) is parsed all-or-nothing. Each row
 * is validated on its own and a row that fails joins `errors` with its 1-based
 * position and the field to fix. Parsing the whole array against the row schema
 * would 400 the entire upload over one cell the client's looser regex let
 * through — the abort this route exists to prevent, delivered by the validator
 * instead of the database.
 */

/** Batch ceiling. Above this the upload is refused whole — never truncated. */
const MAX_ROWS = 500;

const rosterRowSchema = z.object({
  name: z.string().min(1).max(200),
  email: z.email().max(200),
  role: z.string().min(1).max(100),
  /** ISO date (YYYY-MM-DD) — normalised by src/lib/roster-csv.ts. */
  hireDate: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  hourlyRate: z.number().positive().max(10_000),
  state: z.string().regex(/^[A-Za-z]{2}$/),
});

/**
 * The request contract, and the source of `ImportStaffRequest` in
 * `src/lib/types.ts`. The handler parses the envelope below and then each row
 * separately, which accepts exactly this shape and additionally accepts (and
 * reports) batches where only SOME rows match.
 */
export const importStaffSchema = z.object({
  rows: z.array(rosterRowSchema).min(1).max(MAX_ROWS),
});

/** All-or-nothing part: the shape of the batch, not the quality of its rows. */
const importEnvelopeSchema = z.object({
  rows: z.array(z.unknown()).min(1).max(MAX_ROWS),
});

/** Field names the owner sees in their spreadsheet, not our property names. */
const FIELD_LABELS: Record<string, string> = {
  name: "name",
  email: "email",
  role: "role",
  hireDate: "hire date",
  hourlyRate: "hourly rate",
  state: "state",
};

/** Names the columns to fix. Never echoes the value — it is re-rendered text. */
function reasonForIssues(issues: readonly { path: PropertyKey[] }[]): string {
  const fields = Array.from(
    new Set(issues.map((issue) => FIELD_LABELS[String(issue.path[0])] ?? "value"))
  );
  return `Check the ${fields.join(", ")} on this row — it was skipped.`;
}

export interface ImportStaffFailure {
  /** 1-based index within the submitted `rows` array. */
  row: number;
  reason: string;
}

export type ImportStaffResponse = {
  employees: EmployeeRow[];
  imported: number;
  failed: number;
  errors: ImportStaffFailure[];
};

/**
 * One employee, written on its own so a failure stays contained to its row.
 *
 * The try/catch is the batch contract, not defensive noise: a PostgREST call
 * that REJECTS (dropped connection, DNS blip) rather than resolving with
 * `.error` would otherwise escape the import loop, discard the rows already
 * written above it, and hand the client a 500 that it reports to the owner as
 * "nothing was written" over employees that are already on file.
 */
async function upsertEmployee(
  db: SupabaseClient,
  payload: Record<string, unknown>
): Promise<{ data: unknown; error: unknown }> {
  try {
    // Upsert on (account_id, email): re-importing a corrected CSV updates the
    // existing employee instead of failing on the unique constraint.
    return await db
      .from("employees")
      .upsert(payload, { onConflict: "account_id,email" })
      .select(EMPLOYEE_COLUMNS)
      .single();
  } catch (thrown) {
    return { data: null, error: thrown };
  }
}

/**
 * Statuses come from the shared `statusForReason` map so this route cannot
 * drift from the other nine. A missing account is permanent (404), not the
 * transient "come back later" a 503 promises.
 */
const ERROR_FOR_REASON = {
  unauthenticated: "Unauthorized",
  no_account: "Account not found",
  unavailable: "Service unavailable",
} as const;

export async function POST(request: Request) {
  let rawRows: unknown[];
  try {
    rawRows = importEnvelopeSchema.parse(await request.json()).rows;
  } catch {
    // Never forward ZodError.issues — it describes our schema to an attacker.
    return NextResponse.json({ error: "Invalid request" }, { status: 400 });
  }

  const resolved = await resolveAccount({ create: true });
  if (!resolved.ok) {
    return NextResponse.json(
      { error: ERROR_FOR_REASON[resolved.reason] },
      { status: statusForReason(resolved.reason) }
    );
  }
  const { account, db } = resolved.ctx;

  const employees: EmployeeRow[] = [];
  const errors: ImportStaffFailure[] = [];
  /** Emails already written by THIS batch. See the duplicate check below. */
  const seenEmails = new Set<string>();

  for (const [index, raw] of rawRows.entries()) {
    const rowNumber = index + 1;

    const parsed = rosterRowSchema.safeParse(raw);
    if (!parsed.success) {
      errors.push({ row: rowNumber, reason: reasonForIssues(parsed.error.issues) });
      continue;
    }
    const row = parsed.data;
    const email = row.email.toLowerCase();

    // Two rows for the same email upsert onto the SAME (account_id, email)
    // row, so the second is not a second employee: counting it as imported
    // inflates the h-05 denominator and hands the roster table two entries
    // sharing one id. Report it where the owner can fix the spreadsheet.
    if (seenEmails.has(email)) {
      errors.push({
        row: rowNumber,
        reason: `Duplicate email in this file — the first row for ${email} was imported instead.`,
      });
      continue;
    }
    seenEmails.add(email);

    const payload = {
      account_id: account.id,
      name: row.name,
      email,
      role: row.role,
      hire_date: row.hireDate,
      hourly_rate: row.hourlyRate,
      state: row.state.toUpperCase(),
    };

    // One statement per row — see upsertEmployee above for why it cannot throw.
    const { data, error } = await upsertEmployee(db, payload);

    if (error || !data) {
      console.error("[staff/import] Supabase error on row", rowNumber, error);
      errors.push({
        row: rowNumber,
        // Generic — a Postgres message leaks table, column and policy names.
        reason: "This row could not be saved. Check the values and re-import it.",
      });
      continue;
    }
    employees.push(data as EmployeeRow);
  }

  // Seed the account's home state from the roster when it is still blank, so
  // notice generation has a state to resolve rules against. Best-effort: the
  // employees are already written, and failing the response over one optional
  // column would tell the owner to re-import rows that are on file.
  if (!account.home_state && employees.length > 0) {
    try {
      const { error } = await db
        .from("accounts")
        .update({ home_state: employees[0].state })
        .eq("id", account.id);
      if (error) console.error("[staff/import] home_state seed failed:", error);
    } catch (thrown) {
      console.error("[staff/import] home_state seed failed:", thrown);
    }
  }

  return NextResponse.json({
    employees,
    imported: employees.length,
    failed: errors.length,
    errors,
  } satisfies ImportStaffResponse);
}
