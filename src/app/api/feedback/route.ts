import { NextResponse } from "next/server";
import { z } from "zod";
import { resolveAccount } from "@/lib/api-auth";
import { trackServerEvent } from "@/lib/analytics-server";
import { rateLimit, clientIpFromHeaders } from "@/lib/rate-limit";

export const dynamic = "force-dynamic";

/**
 * Post-activation feedback (`feedback_submitted`).
 *
 * "Post-activation" is enforced server-side: the account must have dispatched
 * at least one notice, which is this experiment's activation action. Without
 * that check the event's `activation_action` property would be a claim the
 * client made about itself rather than a fact about the account.
 */

export const submitFeedbackSchema = z.object({
  source: z.enum(["google", "social", "friend", "other"]).optional(),
  feedback: z.string().trim().max(2000).optional(),
  activation_action: z.literal("notice_sent"),
});

export type SubmitFeedbackResponse = { received: true };

export async function POST(request: Request) {
  const ip = clientIpFromHeaders(request.headers);
  const { success } = rateLimit(`feedback:${ip}`, { limit: 5, windowMs: 60_000 });
  if (!success) {
    return NextResponse.json({ error: "Too many requests" }, { status: 429 });
  }
  // TODO: Upgrade to Upstash Redis for cross-instance rate limiting

  let input: z.infer<typeof submitFeedbackSchema>;
  try {
    input = submitFeedbackSchema.parse(await request.json());
  } catch {
    return NextResponse.json({ error: "Invalid request" }, { status: 400 });
  }

  const resolved = await resolveAccount();
  if (!resolved.ok) {
    if (resolved.reason === "unauthenticated") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    if (resolved.reason === "no_account") {
      return NextResponse.json({ error: "Not found" }, { status: 404 });
    }
    return NextResponse.json({ error: "Service unavailable" }, { status: 503 });
  }
  const { account, db, userId } = resolved.ctx;

  const { data: activated, error: activationError } = await db
    .from("notices")
    .select("id")
    .eq("account_id", account.id)
    .in("status", ["sent", "signed"])
    .limit(1);

  if (activationError) {
    console.error("[feedback] activation lookup failed:", activationError);
    return NextResponse.json({ error: "Could not save your feedback" }, { status: 500 });
  }

  if ((activated ?? []).length === 0) {
    return NextResponse.json(
      { error: "Send a notice for signature first — this form asks about that step." },
      { status: 409 }
    );
  }

  const { error } = await db.from("feedback").insert({
    account_id: account.id,
    source: input.source ?? null,
    feedback: input.feedback ?? null,
    activation_action: input.activation_action,
  });

  if (error) {
    console.error("[feedback] Supabase error:", error);
    return NextResponse.json({ error: "Could not save your feedback" }, { status: 500 });
  }

  await trackServerEvent("feedback_submitted", userId, {
    source: input.source,
    feedback: input.feedback,
    activation_action: input.activation_action,
    funnel_stage: "activate",
  });

  return NextResponse.json({ received: true } satisfies SubmitFeedbackResponse);
}
