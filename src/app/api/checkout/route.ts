import { NextResponse } from "next/server";
import { z } from "zod";
import { getStripe } from "@/lib/stripe";
import { resolveAccount, statusForReason } from "@/lib/api-auth";
import { rateLimit, clientIpFromHeaders } from "@/lib/rate-limit";

export const dynamic = "force-dynamic";

/**
 * b-10 — start the $79/mo TipGuard Shield subscription.
 *
 * The price is resolved SERVER-SIDE from the map below. The body carries a
 * plan key, never an amount: a client-supplied price is a client-supplied
 * invoice. `user.id` comes from the verified session, and it is what the
 * webhook reads back out of `metadata` to decide whose account to upgrade.
 */

/** Cents. Single source of truth for what Shield costs. */
const PLAN_PRICES: Record<string, number> = { shield: 7900 };
const PLAN_LABELS: Record<string, string> = { shield: "TipGuard Shield" };

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

export const createCheckoutSchema = z.object({
  plan: z.enum(["shield"]),
});

export type CreateCheckoutResponse = { url: string };

export async function POST(request: Request) {
  const ip = clientIpFromHeaders(request.headers);
  const { success } = rateLimit(`checkout:${ip}`, { limit: 10, windowMs: 60_000 });
  if (!success) {
    return NextResponse.json({ error: "Too many requests" }, { status: 429 });
  }
  // TODO: Upgrade to Upstash Redis for cross-instance rate limiting

  let input: z.infer<typeof createCheckoutSchema>;
  try {
    input = createCheckoutSchema.parse(await request.json());
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
  const { account, userId, email } = resolved.ctx;

  if (account.plan === "shield") {
    return NextResponse.json(
      { error: "This account is already on TipGuard Shield." },
      { status: 409 }
    );
  }

  if (!process.env.STRIPE_SECRET_KEY && process.env.DEMO_MODE !== "true") {
    console.error("[503] Stripe is not configured — run /deploy to provision credentials");
    return NextResponse.json({ error: "Service not configured" }, { status: 503 });
  }

  const amountCents = PLAN_PRICES[input.plan];
  // Never derive redirect URLs from client-controlled headers. Falling back to
  // the request origin keeps localhost and preview deploys working when
  // NEXT_PUBLIC_SITE_URL has not been set yet (otherwise Stripe receives
  // "undefined/dashboard" and the redirect dead-ends).
  const siteUrl = (
    process.env.NEXT_PUBLIC_SITE_URL ?? new URL(request.url).origin
  ).replace(/\/$/, "");

  const metadata = {
    user_id: userId,
    account_id: account.id,
    plan: input.plan,
    amount_cents: String(amountCents),
  };

  try {
    const session = await getStripe().checkout.sessions.create({
      mode: "subscription",
      line_items: [
        {
          price_data: {
            currency: "usd",
            product_data: { name: PLAN_LABELS[input.plan] },
            unit_amount: amountCents,
            recurring: { interval: "month" },
          },
          quantity: 1,
        },
      ],
      // Both metadata bags: `metadata` rides the checkout session (read by the
      // checkout.session.completed handler); `subscription_data.metadata`
      // rides the subscription itself, so later invoice/subscription events
      // can still resolve the account.
      metadata,
      subscription_data: { metadata },
      ...(account.stripe_customer_id
        ? { customer: account.stripe_customer_id }
        : email
          ? { customer_email: email }
          : {}),
      success_url: `${siteUrl}/dashboard?upgraded=1`,
      cancel_url: `${siteUrl}/pricing`,
    });

    if (!session.url) {
      console.error("[checkout] Stripe returned a session with no URL");
      return NextResponse.json({ error: "Checkout failed" }, { status: 500 });
    }

    return NextResponse.json({ url: session.url } satisfies CreateCheckoutResponse);
  } catch (error) {
    console.error("[checkout] Stripe error:", error);
    return NextResponse.json({ error: "Checkout failed" }, { status: 500 });
  }
}
