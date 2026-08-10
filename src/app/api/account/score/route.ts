import { NextResponse } from "next/server";
import { z } from "zod";
import { resolveAccount, statusForReason } from "@/lib/api-auth";
import { rateLimit, clientIpFromHeaders } from "@/lib/rate-limit";

// Session-scoped; never prerender.
export const dynamic = "force-dynamic";

/**
 * b-03 — attach the anonymous /score questionnaire result to the new account.
 *
 * SECURITY: the account is resolved from `supabase.auth.getUser()`. The body
 * carries ONLY the score payload — there is no account id, no user id and no
 * email in it, so there is nothing for a caller to point at somebody else's
 * row. This is an auth-adjacent route (it runs in the same breath as signup),
 * so it carries the same rate limit as the other auth surfaces.
 *
 * Called twice by design: `/signup` posts it immediately after an
 * email/password session exists, and `<PendingScoreClaim />` posts it on the
 * first authenticated page load after a Google OAuth round trip (the OAuth leg
 * leaves the origin, so nothing on /signup can attach it). The handler is
 * idempotent: a second attach with an older `saved_at` is a no-op.
 */

/**
 * Statuses come from the shared `statusForReason` map so this route cannot
 * drift from the other nine. A missing account is permanent (404), not the
 * transient "come back later" a 503 promises — and <PendingScoreClaim /> keeps
 * retrying on every authenticated page load for as long as it sees a 503.
 */
const ERROR_FOR_REASON = {
  unauthenticated: "Unauthorized",
  no_account: "Account not found",
  unavailable: "Service unavailable",
} as const;

/** Two-letter USPS code. `/score` also emits the sentinel "OTHER". */
const STATE_CODE = /^[A-Za-z]{2}$/;

const gapSchema = z.object({
  id: z.string().max(64),
  label: z.string().max(500),
  severity: z.enum(["critical", "high", "medium"]),
  pointsDeducted: z.number().min(0).max(100),
});

export const attachScoreSchema = z.object({
  state: z.string().min(2).max(20),
  claims_tip_credit: z.boolean(),
  staff_count: z.number().int().min(0).max(10_000),
  readiness_score: z.number().int().min(0).max(100),
  gap_list: z.array(gapSchema).max(20),
  estimated_exposure_usd: z.object({
    low: z.number().min(0).max(1_000_000_000),
    high: z.number().min(0).max(1_000_000_000),
  }),
  // `saved_at` is the ONLY guard against a stale localStorage record
  // clobbering a newer score. An unparseable value slips past the staleness
  // comparison below (NaN is never <=), so it has to be rejected at the
  // boundary. Both clients send `new Date().toISOString()`.
  saved_at: z
    .string()
    .max(40)
    .refine((value) => Number.isFinite(Date.parse(value))),
});

export type AttachScoreResponse = {
  attached: boolean;
  readiness_score: number;
  gap_count: number;
};

export async function POST(request: Request) {
  const ip = clientIpFromHeaders(request.headers);
  const { success } = rateLimit(`account-score:${ip}`, { limit: 10, windowMs: 60_000 });
  if (!success) {
    return NextResponse.json({ error: "Too many requests" }, { status: 429 });
  }
  // TODO: Upgrade to Upstash Redis for cross-instance rate limiting

  let input: z.infer<typeof attachScoreSchema>;
  try {
    input = attachScoreSchema.parse(await request.json());
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

  // A pending score lives in localStorage for up to 7 days. If the account
  // already carries a NEWER score, the stale record must not clobber it.
  // Parseable by construction — the schema rejects anything else.
  const incomingSavedAt = Date.parse(input.saved_at);
  const existingScoredAt = account.scored_at ? Date.parse(account.scored_at) : NaN;
  const stale =
    Number.isFinite(existingScoredAt) && incomingSavedAt <= existingScoredAt;

  if (stale) {
    return NextResponse.json({
      attached: false,
      readiness_score: account.readiness_score ?? input.readiness_score,
      gap_count: Array.isArray(account.gap_list) ? account.gap_list.length : 0,
    } satisfies AttachScoreResponse);
  }

  const savedAtIso = new Date(incomingSavedAt).toISOString();

  const { error } = await db
    .from("accounts")
    .update({
      readiness_score: input.readiness_score,
      gap_list: input.gap_list,
      scored_at: savedAtIso,
      // Only seed the home state — never overwrite one the owner already set,
      // and never seed a code that is not one. `/score` sends "OTHER" for a
      // state outside the rule library; truncating that to "OT" writes a state
      // that does not exist into a column /dashboard and the audit file both
      // render verbatim. Leave it empty for /staff import to seed instead.
      ...(account.home_state || !STATE_CODE.test(input.state)
        ? {}
        : { home_state: input.state.toUpperCase() }),
    })
    .eq("id", account.id);

  if (error) {
    console.error("[account/score] Supabase error:", error);
    return NextResponse.json({ error: "Could not save your score" }, { status: 500 });
  }

  return NextResponse.json({
    attached: true,
    readiness_score: input.readiness_score,
    gap_count: input.gap_list.length,
  } satisfies AttachScoreResponse);
}
