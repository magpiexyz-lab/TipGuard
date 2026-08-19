import { NextResponse } from "next/server";
import { z } from "zod";
import { resolveAccount, statusForReason } from "@/lib/api-auth";
import { rateLimit, clientIpFromHeaders } from "@/lib/rate-limit";
import { sendWaitlistEmail } from "@/lib/email";

export const dynamic = "force-dynamic";

/**
 * b-11 — join the TipGuard Shield waitlist.
 *
 * This replaced the Stripe checkout session. The fake door measures whether an
 * owner who clicked the upgrade CTA will also leave an address; `h-06` is
 * scored on `checkout_started`, which the client fires on the click itself, so
 * this route is the follow-through signal, not the hypothesis metric.
 *
 * The body carries NOTHING that identifies the account. `account_id` and
 * `notices_sent_at_join` are both derived server-side — a client-supplied
 * account id is a client-supplied claim about whose intent this was, and a
 * client-supplied count is a client-supplied qualification of the lead.
 */

const ERROR_FOR_REASON = {
  unauthenticated: "Unauthorized",
  no_account: "Account not found",
  unavailable: "Service unavailable",
} as const;

/**
 * Email is optional. When absent the session email is used, which is the
 * normal path — the panel pre-fills it and the owner just confirms. An
 * explicit value lets them route Shield news to a different inbox (owner signs
 * up with a personal address, wants billing mail at the restaurant's).
 */
export const joinWaitlistSchema = z.object({
  email: z.string().email().max(254).optional(),
});

export type JoinWaitlistResponse = { joined: true; email: string };

export async function POST(request: Request) {
  const ip = clientIpFromHeaders(request.headers);
  const { success } = rateLimit(`waitlist:${ip}`, { limit: 10, windowMs: 60_000 });
  if (!success) {
    return NextResponse.json({ error: "Too many requests" }, { status: 429 });
  }
  // TODO: Upgrade to Upstash Redis for cross-instance rate limiting

  let input: z.infer<typeof joinWaitlistSchema>;
  try {
    input = joinWaitlistSchema.parse(await request.json());
  } catch {
    return NextResponse.json({ error: "Invalid request" }, { status: 400 });
  }

  const resolved = await resolveAccount({ create: true });
  if (!resolved.ok) {
    return NextResponse.json(
      { error: ERROR_FOR_REASON[resolved.reason] },
      { status: statusForReason(resolved.reason) }
    );
  }
  const { account, email: sessionEmail, db } = resolved.ctx;

  const email = input.email ?? sessionEmail;
  if (!email) {
    // Session carries no address (possible on some OAuth providers) and none
    // was supplied. Ask for one rather than writing a row we can never reach.
    return NextResponse.json({ error: "email_required" }, { status: 400 });
  }

  // Qualification context, counted server-side at the moment of joining.
  const { count: noticesSent } = await db
    .from("notices")
    .select("id", { count: "exact", head: true })
    .eq("account_id", account.id)
    .in("status", ["sent", "signed"]);

  // UNIQUE(account_id) makes a second confirm an update, not a duplicate. The
  // owner changing their mind about which inbox to use is a legitimate repeat.
  const { error } = await db
    .from("waitlist")
    .upsert(
      {
        account_id: account.id,
        email,
        notices_sent_at_join: noticesSent ?? 0,
      },
      { onConflict: "account_id" }
    );

  if (error) {
    console.error("[waitlist] insert failed:", error.message);
    return NextResponse.json({ error: "Could not join the waitlist" }, { status: 500 });
  }

  // Confirmation is best-effort: the row is what the experiment measures, and
  // a mail outage must not turn a recorded signal into a 500 the owner reads
  // as "it did not work" — they would click again and we would count it twice.
  try {
    await sendWaitlistEmail(email, account.restaurant_name || "your restaurant");
  } catch (mailError) {
    console.error("[waitlist] confirmation email failed:", mailError);
  }

  return NextResponse.json({ joined: true, email } satisfies JoinWaitlistResponse);
}
