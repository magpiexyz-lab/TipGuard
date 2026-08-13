import { NextResponse } from "next/server";
import { z } from "zod";
import { resolveAccount, statusForReason } from "@/lib/api-auth";
import type { ViolationRow } from "@/lib/types";

export const dynamic = "force-dynamic";

/**
 * b-09 — mark a finding resolved.
 *
 * The row is UPDATED, never deleted: "Resolving a finding updates its status
 * and removes it from the open list without deleting the audit record." An
 * investigator asking what you found and when you fixed it is answered by the
 * resolved rows, so deleting them would destroy the most useful evidence the
 * product produces.
 */

/** Statuses come from the shared map so this route cannot drift from the rest. */
const ERROR_FOR_REASON = {
  unauthenticated: "Unauthorized",
  no_account: "Not found",
  unavailable: "Service unavailable",
} as const;

export const resolveViolationSchema = z.object({
  violation_id: z.uuid(),
});

export type ResolveViolationResponse = {
  violation_id: string;
  rule_class: ViolationRow["rule_class"];
  days_open: number;
  resolved_at: string;
};

const MS_PER_DAY = 86_400_000;

export async function POST(request: Request) {
  let input: z.infer<typeof resolveViolationSchema>;
  try {
    input = resolveViolationSchema.parse(await request.json());
  } catch {
    return NextResponse.json({ error: "Invalid request" }, { status: 400 });
  }

  const resolved = await resolveAccount();
  if (!resolved.ok) {
    return NextResponse.json(
      { error: ERROR_FOR_REASON[resolved.reason] },
      { status: statusForReason(resolved.reason) }
    );
  }
  const { account, db } = resolved.ctx;

  // STATE-TRANSITION GUARD (wire.md Step 5): `status` is in the SELECT.
  // `violations.status` is an open -> resolved DAG; resolving an already
  // resolved finding is a forbidden transition, not a silent no-op.
  // `.eq("account_id", ...)` is defence in depth on top of RLS — the id comes
  // from the request body and must never address another tenant's row.
  const { data, error } = await db
    .from("violations")
    .select("id, status, rule_class, detected_at")
    .eq("id", input.violation_id)
    .eq("account_id", account.id)
    .maybeSingle();

  if (error) {
    console.error("[violations/resolve] Supabase error:", error);
    return NextResponse.json({ error: "The finding could not be resolved" }, { status: 500 });
  }

  const violation = data as Pick<
    ViolationRow,
    "id" | "status" | "rule_class" | "detected_at"
  > | null;
  if (!violation) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  if (violation.status !== "open") {
    return NextResponse.json({ error: "Invalid state transition" }, { status: 409 });
  }

  const resolvedAt = new Date().toISOString();
  const detectedMs = Date.parse(violation.detected_at);
  const daysOpen = Number.isFinite(detectedMs)
    ? Math.max(0, Math.floor((Date.parse(resolvedAt) - detectedMs) / MS_PER_DAY))
    : 0;

  // COMPARE-AND-SWAP. The status check above is a separate statement from this
  // write, so two clicks in flight at once both read 'open' and both write —
  // and /violations fires `violation_resolved` off each 200, double-counting
  // one real fix in h-05 and moving `resolved_at` forward. Carrying the
  // precondition into the UPDATE makes the transition atomic: exactly one
  // request matches a row, and the loser is told so.
  const { data: updated, error: updateError } = await db
    .from("violations")
    .update({ status: "resolved", resolved_at: resolvedAt })
    .eq("id", violation.id)
    .eq("account_id", account.id)
    .eq("status", "open")
    .select("id");

  if (updateError) {
    console.error("[violations/resolve] Supabase error:", updateError);
    return NextResponse.json({ error: "The finding could not be resolved" }, { status: 500 });
  }

  if (!Array.isArray(updated) || updated.length === 0) {
    return NextResponse.json({ error: "Invalid state transition" }, { status: 409 });
  }

  // `violation_resolved` is fired client-side by /violations with these exact
  // values — the server is authoritative for days_open.
  return NextResponse.json({
    violation_id: violation.id,
    rule_class: violation.rule_class,
    days_open: daysOpen,
    resolved_at: resolvedAt,
  } satisfies ResolveViolationResponse);
}
