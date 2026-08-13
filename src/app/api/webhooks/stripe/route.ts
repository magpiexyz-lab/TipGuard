import { NextResponse } from "next/server";
import type Stripe from "stripe";
import { getStripe } from "@/lib/stripe";
import { createServiceRoleClient } from "@/lib/supabase-server";
import { trackServerEvent } from "@/lib/analytics-server";
import { sendWelcomeEmail } from "@/lib/email";
import type { SupabaseClient } from "@supabase/supabase-js";

export const dynamic = "force-dynamic";

/**
 * b-11 (actor: system) — Stripe `checkout.session.completed`.
 *
 * NOTE: No rate limiting. Stripe retries failed deliveries on a schedule; a
 * limiter would block legitimate retries and silently drop payment events.
 * The security boundary here is `constructEvent()`, which rejects any request
 * without a valid STRIPE_WEBHOOK_SECRET-signed `stripe-signature` header.
 */

const THIRTY_DAYS_MS = 30 * 24 * 60 * 60 * 1000;

/**
 * Stripe has moved `current_period_end` between the subscription and its items
 * across API versions. Read defensively from both, and fall back to a 30-day
 * window rather than writing a null period end onto a paying account.
 */
function readPeriodEnd(subscription: unknown): string {
  const candidate = subscription as
    | {
        current_period_end?: number;
        items?: { data?: { current_period_end?: number }[] };
      }
    | null
    | undefined;

  const seconds =
    candidate?.current_period_end ?? candidate?.items?.data?.[0]?.current_period_end;

  if (typeof seconds === "number" && Number.isFinite(seconds)) {
    return new Date(seconds * 1000).toISOString();
  }
  return new Date(Date.now() + THIRTY_DAYS_MS).toISOString();
}

/**
 * Give the idempotency key back so a Stripe retry can actually re-run.
 *
 * The ledger row is written BEFORE the mutation, which is what makes two
 * concurrent deliveries collapse into one. The cost is that a delivery which
 * fails *after* the insert leaves a key behind: the retry then hits the 23505
 * short-circuit, returns 200, and the paying customer stays on the free plan
 * forever while Stripe reports the webhook as delivered.
 *
 * Only called on paths that return 500 after the insert — i.e. paths where
 * nothing was reported and nothing was emailed. In the rare case where the
 * write actually landed but PostgREST reported an error, the retry redoes an
 * idempotent update and fires `checkout_completed` twice; over-reporting a
 * real upgrade is strictly better than never delivering one.
 */
async function releaseIdempotencyKey(db: SupabaseClient, eventId: string) {
  try {
    await db.from("stripe_events").delete().eq("stripe_event_id", eventId);
  } catch (error) {
    console.error("[webhooks/stripe] idempotency release failed:", error);
  }
}

export async function POST(request: Request) {
  const body = await request.text();
  const signature = request.headers.get("stripe-signature");

  if (!signature) {
    return NextResponse.json({ error: "Bad request" }, { status: 400 });
  }

  const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET;
  if (!webhookSecret && process.env.DEMO_MODE !== "true") {
    console.error("[503] Stripe webhook secret not configured — run /deploy");
    return NextResponse.json({ error: "Service not configured" }, { status: 503 });
  }

  let event: Stripe.Event;
  try {
    event = getStripe().webhooks.constructEvent(body, signature, webhookSecret ?? "");
  } catch {
    // Unsigned or tampered — never process, never explain why.
    return NextResponse.json({ error: "Bad request" }, { status: 400 });
  }

  let db: SupabaseClient;
  try {
    db = createServiceRoleClient() as unknown as SupabaseClient;
  } catch (error) {
    console.error("[webhooks/stripe] service-role client unavailable:", error);
    return NextResponse.json({ error: "Persistence error" }, { status: 500 });
  }

  // Idempotency guard: INSERT + catch PG 23505 (unique_violation). Atomic —
  // two concurrent deliveries of the same event id produce exactly one insert;
  // the loser exits 200 so Stripe stops retrying. This is what makes
  // `checkout_completed` fire exactly once per session id.
  const { error: insertErr } = await db
    .from("stripe_events")
    .insert({ stripe_event_id: event.id });
  if (insertErr) {
    if ((insertErr as { code?: string }).code === "23505") {
      return NextResponse.json({ received: true });
    }
    console.error("[webhooks/stripe] idempotency insert failed:", insertErr);
    return NextResponse.json({ error: "Persistence error" }, { status: 500 });
  }

  if (event.type === "checkout.session.completed") {
    const session = event.data.object as Stripe.Checkout.Session;
    // Identity comes from metadata we set server-side at checkout creation —
    // never from customer_email, which a buyer controls.
    const userId = session.metadata?.user_id ?? "";
    const accountId = session.metadata?.account_id ?? "";
    const amountCents = Number(session.metadata?.amount_cents ?? 0);

    if (!accountId && !userId) {
      console.error("[webhooks/stripe] session missing account metadata:", session.id);
      return NextResponse.json({ received: true });
    }

    const customerId =
      typeof session.customer === "string" ? session.customer : session.customer?.id ?? null;

    let currentPeriodEnd = new Date(Date.now() + THIRTY_DAYS_MS).toISOString();
    const subscriptionId =
      typeof session.subscription === "string"
        ? session.subscription
        : session.subscription?.id ?? null;
    if (subscriptionId) {
      try {
        const subscription = await getStripe().subscriptions.retrieve(subscriptionId);
        currentPeriodEnd = readPeriodEnd(subscription);
      } catch (error) {
        console.error("[webhooks/stripe] subscription retrieve failed:", error);
      }
    }

    // Resolve the account by whichever identifier the session carried.
    const accountQuery = db
      .from("accounts")
      .select("id, user_id, restaurant_name, plan");
    const { data: accountRow, error: accountError } = accountId
      ? await accountQuery.eq("id", accountId).maybeSingle()
      : await accountQuery.eq("user_id", userId).maybeSingle();

    if (accountError) {
      console.error("[webhooks/stripe] account lookup failed:", accountError);
      await releaseIdempotencyKey(db, event.id);
      return NextResponse.json({ error: "Persistence error" }, { status: 500 });
    }

    const account = accountRow as {
      id: string;
      user_id: string;
      restaurant_name: string;
      plan: string;
    } | null;

    if (!account) {
      console.error("[webhooks/stripe] no account for session:", session.id);
      return NextResponse.json({ received: true });
    }

    // Resolves the "// TODO: Update user's payment status in database" from
    // the payment stack template.
    const { error: updateError } = await db
      .from("accounts")
      .update({
        plan: "shield",
        stripe_customer_id: customerId,
        current_period_end: currentPeriodEnd,
      })
      .eq("id", account.id);

    if (updateError) {
      console.error("[webhooks/stripe] plan update failed:", updateError);
      await releaseIdempotencyKey(db, event.id);
      return NextResponse.json({ error: "Persistence error" }, { status: 500 });
    }

    // The upgrade has landed. Everything below is reporting, and no reporting
    // failure may turn a completed checkout into a 500 — Stripe would retry,
    // hit the idempotency guard, and the welcome email would never be sent.
    try {
      await trackServerEvent("checkout_completed", account.user_id || userId || "server", {
        plan: "shield",
        amount_usd: amountCents > 0 ? amountCents / 100 : 79,
        funnel_stage: "monetize",
      });
    } catch (error) {
      console.error("[webhooks/stripe] checkout_completed not recorded:", error);
    }

    // Welcome email. `to` is Stripe's record of the paying customer and the
    // CTA is a static path on our own origin — neither is client-supplied, so
    // this cannot be turned into a phishing relay.
    const to = session.customer_details?.email ?? session.customer_email ?? null;
    if (to) {
      try {
        const siteUrl = (
          process.env.NEXT_PUBLIC_SITE_URL ?? new URL(request.url).origin
        ).replace(/\/$/, "");
        await sendWelcomeEmail(
          to,
          account.restaurant_name || "your restaurant",
          `${siteUrl}/dashboard`
        );
      } catch (error) {
        // The upgrade already landed — a failed email must not make Stripe
        // retry and re-run the whole handler.
        console.error("[webhooks/stripe] welcome email failed:", error);
      }
    }
  }

  // 200 for every event type — never error on events we do not handle.
  return NextResponse.json({ received: true });
}
