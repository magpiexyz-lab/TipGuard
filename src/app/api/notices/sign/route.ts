import { NextResponse } from "next/server";
import { z } from "zod";
import { createServiceRoleClient } from "@/lib/supabase-server";
import { rateLimit, clientIpFromHeaders } from "@/lib/rate-limit";
import type { SupabaseClient } from "@supabase/supabase-js";
import type { NoticeRow, SigningTokenRow } from "@/lib/types";
// Same module the send route mints with — see the CROSS-AGENT CONTRACT note at
// the top of signing-token.ts. One hash implementation, two call sites.
import { hashSigningToken, isWellFormedSigningToken } from "@/app/sign/signing-token";

export const dynamic = "force-dynamic";

/**
 * b-07 — record an employee's acknowledgment.
 *
 * THIS IS A PUBLIC ROUTE. The signer is a restaurant employee with no TipGuard
 * account and no session, so:
 *
 *   - Authorization is the single-use token, validated SERVER-SIDE here
 *     against `expires_at` and `used_at`. The render-time check in
 *     `src/app/sign/notice-lookup.ts` is a UX affordance, not the boundary — a
 *     token can expire or be consumed between page render and submit.
 *   - The body carries `signer_name` and nothing else that matters. Timestamp,
 *     IP and user agent are derived from the server clock and request headers.
 *     The frozen notice text is COPIED out of the `notices` row the token
 *     resolves to, so a tampered client cannot alter what is recorded as
 *     legally acknowledged.
 *   - It is rate limited. A public unauthenticated write endpoint without one
 *     is a free token-guessing oracle.
 */

export const signNoticeSchema = z.object({
  token: z.string().min(8).max(128),
  signer_name: z.string().trim().min(2).max(120),
});

export type SignNoticeResponse = { signed_at: string; notice_id: string };

interface TokenLookup extends Pick<SigningTokenRow, "id" | "notice_id" | "expires_at" | "used_at"> {
  account_id: string;
}

export async function POST(request: Request) {
  const ip = clientIpFromHeaders(request.headers);
  const { success } = rateLimit(`notices-sign:${ip}`, { limit: 10, windowMs: 60_000 });
  if (!success) {
    return NextResponse.json({ error: "Too many requests" }, { status: 429 });
  }
  // TODO: Upgrade to Upstash Redis for cross-instance rate limiting

  let input: z.infer<typeof signNoticeSchema>;
  try {
    input = signNoticeSchema.parse(await request.json());
  } catch {
    return NextResponse.json({ error: "Invalid request" }, { status: 400 });
  }

  // Cheap shape check so a malformed value never reaches a database query.
  if (!isWellFormedSigningToken(input.token)) {
    return NextResponse.json({ error: "This signing link is not valid." }, { status: 404 });
  }

  let db: SupabaseClient;
  try {
    // The signer has no session, so RLS (which scopes rows to the owning
    // account) would reject an anon read. Authorization is the token digest.
    db = createServiceRoleClient() as unknown as SupabaseClient;
  } catch (error) {
    console.error("[notices/sign] service-role client unavailable:", error);
    return NextResponse.json({ error: "Service unavailable" }, { status: 503 });
  }

  const tokenResult = await db
    .from("signing_tokens")
    .select("id, account_id, notice_id, expires_at, used_at")
    .eq("token_hash", hashSigningToken(input.token))
    .maybeSingle();

  if (tokenResult.error) {
    console.error("[notices/sign] token lookup failed:", tokenResult.error);
    return NextResponse.json({ error: "Service unavailable" }, { status: 503 });
  }

  const token = tokenResult.data as TokenLookup | null;
  // A miss is indistinguishable from a wrong guess — same response either way.
  if (!token) {
    return NextResponse.json({ error: "This signing link is not valid." }, { status: 404 });
  }

  if (token.used_at) {
    return NextResponse.json(
      { error: "This notice has already been signed." },
      { status: 409 }
    );
  }

  const expiresAt = Date.parse(token.expires_at);
  if (!Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
    return NextResponse.json(
      { error: "This signing link has expired. Ask your employer to send a new one." },
      { status: 410 }
    );
  }

  // STATE-TRANSITION GUARD: `status` is in the SELECT. The only valid
  // pre-state for a signature is 'sent'.
  const noticeResult = await db
    .from("notices")
    .select("id, account_id, status, notice_text")
    .eq("id", token.notice_id)
    .maybeSingle();

  if (noticeResult.error) {
    console.error("[notices/sign] notice lookup failed:", noticeResult.error);
    return NextResponse.json({ error: "Service unavailable" }, { status: 503 });
  }

  const notice = noticeResult.data as Pick<
    NoticeRow,
    "id" | "account_id" | "status" | "notice_text"
  > | null;
  if (!notice) {
    return NextResponse.json({ error: "This signing link is not valid." }, { status: 404 });
  }

  // The token row and the notice row are written together by /notices/send, so
  // these always agree in a healthy database. If they ever disagree the linkage
  // was tampered with or corrupted, and honouring it would file an
  // acknowledgment — and the notice's 'signed' status — under an account the
  // token was never issued for. Refuse with the same opaque message as a miss.
  if (notice.account_id !== token.account_id) {
    console.error(
      "[notices/sign] token/notice account mismatch for notice:",
      notice.id
    );
    return NextResponse.json({ error: "This signing link is not valid." }, { status: 404 });
  }

  if (notice.status !== "sent") {
    return NextResponse.json(
      {
        error:
          notice.status === "signed"
            ? "This notice has already been signed."
            : "This notice is not ready for signature.",
      },
      { status: 409 }
    );
  }

  const signedAt = new Date().toISOString();

  // Consume the token FIRST and only if it is still unused. `used_at IS NULL`
  // in the predicate makes this a compare-and-swap: two concurrent submits
  // race, exactly one updates a row, the loser sees zero rows and stops. This
  // is what makes `notice_signed` fire once per signature.
  const consumed = await db
    .from("signing_tokens")
    .update({ used_at: signedAt })
    .eq("id", token.id)
    .is("used_at", null)
    .select("id");

  if (consumed.error) {
    console.error("[notices/sign] token consume failed:", consumed.error);
    return NextResponse.json({ error: "Could not record your signature" }, { status: 500 });
  }
  // Zero rows means someone else won the race. There is deliberately NO
  // environment-variable escape hatch here: this check is the entire basis for
  // "one signature, one `notice_signed`". (The demo client never reaches this
  // line — its token lookup resolves to null, so a demo request 404s above.)
  const consumedRows = (consumed.data ?? []) as { id: string }[];
  if (consumedRows.length === 0) {
    return NextResponse.json(
      { error: "This notice has already been signed." },
      { status: 409 }
    );
  }

  const { error: signatureError } = await db.from("signatures").insert({
    account_id: notice.account_id,
    notice_id: notice.id,
    signer_name: input.signer_name,
    signed_at: signedAt,
    ip_address: ip,
    user_agent: (request.headers.get("user-agent") ?? "").slice(0, 500),
    // A COPY, not a reference. Later edits to `notices` cannot alter what this
    // signature refers to.
    notice_text_snapshot: notice.notice_text,
  });

  if (signatureError) {
    console.error("[notices/sign] signature insert failed:", signatureError);
    // The token was consumed a moment ago to win the race, but no signature
    // exists. Leaving it consumed would kill the employee's only signing link
    // permanently: every retry would read "already signed" while the vault
    // holds nothing. Put it back so the retry can succeed. Restoring
    // `used_at = NULL` restores the exact pre-request state — it cannot admit a
    // second signature, because there is no first one.
    const { error: releaseError } = await db
      .from("signing_tokens")
      .update({ used_at: null })
      .eq("id", token.id);
    if (releaseError) {
      console.error("[notices/sign] token release failed:", releaseError);
    }
    return NextResponse.json({ error: "Could not record your signature" }, { status: 500 });
  }

  const { error: statusError } = await db
    .from("notices")
    .update({ status: "signed" })
    .eq("id", notice.id);
  if (statusError) {
    // The signature is already durable — the vault is the record of truth.
    // Log and continue rather than telling the employee it failed.
    console.error("[notices/sign] notice status update failed:", statusError);
  }

  return NextResponse.json({
    signed_at: signedAt,
    notice_id: notice.id,
  } satisfies SignNoticeResponse);
}
