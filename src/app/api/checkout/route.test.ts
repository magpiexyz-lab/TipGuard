// Unit tests for POST /api/checkout — behavior b-10.
//
// This route is the money path. It is where the product decides what the
// customer will be charged and who gets upgraded when Stripe calls back, and
// both of those decisions have to survive a hostile request body:
//
//   * PRICE IS SERVER-CONTROLLED. The body carries a plan key and nothing
//     else that matters. A client-supplied amount, unit_amount, or price id is
//     a client-supplied invoice — if any of them reached `sessions.create`,
//     anyone could buy Shield for a cent.
//   * IDENTITY IS SESSION-DERIVED. `metadata.user_id` / `metadata.account_id`
//     come from `resolveAccount()`, never from the body. Stripe signs whatever
//     we put there and hands it straight back to the webhook, which uses it to
//     decide whose `accounts.plan` flips to 'shield'.
//   * THE METADATA BAG IS A CONTRACT with src/app/api/webhooks/stripe/route.ts.
//     That handler reads `user_id`, `account_id`, and `amount_cents` back out
//     of the session. A rename on this side means paying customers silently
//     never get upgraded, and nothing fails loudly enough to notice. The
//     contract is pinned from both ends: see the `makeSession()` fixture in
//     src/app/api/webhooks/stripe/route.test.ts.
//   * NO FAILURE MAY THROW. An unhandled rejection here is a 500 with no
//     `checkout_started` follow-through and an owner who thinks the product is
//     broken at the exact moment they tried to pay (h-06).
//
// `checkout_started` itself fires client-side, before the redirect, so that
// abandoning on Stripe's page still counts as intent to pay — see
// src/app/pricing/upgrade-button.tsx. Its payload contract is asserted at the
// bottom of this file.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST } from "./route";
import { trackCheckoutStarted } from "@/lib/events";
import type { AccountRow } from "@/lib/types";

const { getStripe, resolveAccount, rateLimit, clientIpFromHeaders, track } =
  vi.hoisted(() => ({
    getStripe: vi.fn(),
    resolveAccount: vi.fn(),
    rateLimit: vi.fn(),
    clientIpFromHeaders: vi.fn(),
    track: vi.fn(),
  }));

vi.mock("@/lib/stripe", () => ({ getStripe }));
vi.mock("@/lib/rate-limit", () => ({ rateLimit, clientIpFromHeaders }));
vi.mock("@/lib/analytics", () => ({ track }));
// Partial mock: the reason -> status mapping is real, only the resolution is
// stubbed. A test that also stubbed `statusForReason` could not detect the
// route mapping a reason to the wrong status.
vi.mock("@/lib/api-auth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-auth")>()),
  resolveAccount,
}));

const createSession = vi.fn();

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const SESSION_USER = {
  id: "11111111-1111-4111-8111-111111111111",
  email: "owner@restaurant.test",
};

const ACCOUNT: AccountRow = {
  id: "22222222-2222-4222-8222-222222222222",
  user_id: SESSION_USER.id,
  restaurant_name: "The Tipped Spoon",
  home_state: "TX",
  plan: "free",
  stripe_customer_id: null,
  current_period_end: null,
  readiness_score: 62,
  gap_list: null,
  scored_at: null,
  last_scan_at: null,
  created_at: "2026-01-01T00:00:00.000Z",
};

/** What Shield costs. Single source of truth lives in the route. */
const SHIELD_CENTS = 7900;
const SESSION_URL = "https://checkout.stripe.com/c/pay/cs_test_000000000001";
const CLIENT_IP = "203.0.113.7";
/** The attacker-controlled prefix of the X-Forwarded-For chain. */
const SPOOFED_IP = "10.0.0.1";

/**
 * The metadata keys src/app/api/webhooks/stripe/route.ts reads back out of the
 * completed session. Dropping or renaming one here upgrades nobody.
 */
const WEBHOOK_METADATA_KEYS = ["user_id", "account_id", "amount_cents"] as const;

function givenAccount(overrides: Partial<AccountRow> = {}) {
  const account = { ...ACCOUNT, ...overrides };
  resolveAccount.mockResolvedValue({
    ok: true,
    ctx: {
      userId: SESSION_USER.id,
      email: SESSION_USER.email,
      account,
      db: {},
    },
  });
  return account;
}

function givenNoResolution(reason: "unauthenticated" | "no_account" | "unavailable") {
  resolveAccount.mockResolvedValue({ ok: false, reason });
}

// ---------------------------------------------------------------------------
// Request helpers
// ---------------------------------------------------------------------------

interface RequestInitOptions {
  url?: string;
  headers?: Record<string, string>;
  /** Bypasses JSON serialization, for malformed-body cases. */
  raw?: string;
}

function makeRequest(body: unknown, options: RequestInitOptions = {}) {
  return new Request(options.url ?? "https://request-host.test/api/checkout", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-forwarded-for": `${SPOOFED_IP}, ${CLIENT_IP}`,
      ...options.headers,
    },
    body: options.raw ?? JSON.stringify(body),
  });
}

function post(body: unknown, options: RequestInitOptions = {}) {
  return POST(makeRequest(body, options));
}

// --- Readers over the params handed to Stripe ------------------------------

function sessionParams(): Record<string, unknown> {
  expect(createSession).toHaveBeenCalledTimes(1);
  return createSession.mock.calls[0][0] as Record<string, unknown>;
}

function lineItem(): Record<string, unknown> {
  return (sessionParams().line_items as Record<string, unknown>[])[0];
}

function priceData(): Record<string, unknown> {
  return lineItem().price_data as Record<string, unknown>;
}

function sessionMetadata(): Record<string, string> {
  return sessionParams().metadata as Record<string, string>;
}

const ENV_KEYS = ["STRIPE_SECRET_KEY", "DEMO_MODE", "NEXT_PUBLIC_SITE_URL"] as const;
const originalEnv: Record<string, string | undefined> = {};

beforeEach(() => {
  vi.resetAllMocks();
  for (const key of ENV_KEYS) originalEnv[key] = process.env[key];
  process.env.STRIPE_SECRET_KEY = "sk_test_000000000001";
  delete process.env.DEMO_MODE;
  delete process.env.NEXT_PUBLIC_SITE_URL;

  rateLimit.mockReturnValue({ success: true, remaining: 9 });
  clientIpFromHeaders.mockReturnValue(CLIENT_IP);
  getStripe.mockReturnValue({ checkout: { sessions: { create: createSession } } });
  createSession.mockResolvedValue({ id: "cs_test_000000000001", url: SESSION_URL });
  givenAccount();

  // The route logs every failure path by design; keep the output readable.
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
  for (const key of ENV_KEYS) {
    if (originalEnv[key] === undefined) delete process.env[key];
    else process.env[key] = originalEnv[key];
  }
});

// ===========================================================================
// b-10 criterion: "Clicking upgrade calls /api/checkout, receives a Stripe
// session URL, and redirects"
// ===========================================================================

describe("POST /api/checkout — the happy path", () => {
  it("Clicking upgrade calls /api/checkout, receives a Stripe session URL, and redirects", async () => {
    // The body is exactly what src/app/pricing/upgrade-button.tsx posts.
    const response = await post({ plan: "shield" });

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ url: SESSION_URL });
    expect(createSession).toHaveBeenCalledTimes(1);
  });

  it("returns only the url, so the client has nothing else to branch on", async () => {
    // upgrade-button.tsx redirects on `result.url` and shows an error
    // otherwise. An extra `error` key in a 200 would flip it to the failure
    // copy after a session was already created and billed.
    const response = await post({ plan: "shield" });

    expect(Object.keys(await response.json())).toEqual(["url"]);
  });

  it("creates a monthly subscription session, not a one-off payment", async () => {
    await post({ plan: "shield" });

    expect(sessionParams().mode).toBe("subscription");
    expect(priceData().recurring).toEqual({ interval: "month" });
    expect(lineItem().quantity).toBe(1);
  });

  it("names the product so the Stripe receipt is recognizable", async () => {
    await post({ plan: "shield" });

    expect(priceData().product_data).toEqual({ name: "TipGuard Shield" });
  });
});

// ===========================================================================
// Price and plan are server-controlled
// ===========================================================================

describe("POST /api/checkout — the price is not negotiable", () => {
  it("charges $79.00 in USD for Shield", async () => {
    await post({ plan: "shield" });

    expect(priceData().unit_amount).toBe(SHIELD_CENTS);
    expect(priceData().currency).toBe("usd");
  });

  it("ignores an amount supplied in the request body", async () => {
    // The whole reason the body carries a plan key instead of a price.
    await post({
      plan: "shield",
      amount_cents: 1,
      unit_amount: 1,
      amount: 1,
      currency: "xxx",
    });

    expect(priceData().unit_amount).toBe(SHIELD_CENTS);
    expect(priceData().currency).toBe("usd");
  });

  it("ignores a price id supplied in the request body", async () => {
    // `price` and `price_data` are mutually exclusive in the Stripe API: a
    // leaked-through `price` would silently take precedence over our amount.
    await post({ plan: "shield", price: "price_attacker_controlled" });

    expect(lineItem().price).toBeUndefined();
    expect(priceData().unit_amount).toBe(SHIELD_CENTS);
  });

  it("does not forward unknown body fields into the Stripe session", async () => {
    await post({
      plan: "shield",
      discounts: [{ coupon: "FREE_FOREVER" }],
      metadata: { user_id: "99999999-9999-4999-8999-999999999999" },
      trial_period_days: 3650,
    });

    expect(sessionParams().discounts).toBeUndefined();
    expect(sessionParams().trial_period_days).toBeUndefined();
    expect(sessionMetadata().user_id).toBe(SESSION_USER.id);
  });

  it("rejects any plan that is not on the server price list", async () => {
    for (const plan of ["free", "enterprise", "", "SHIELD", null, 7900]) {
      createSession.mockClear();
      const response = await post({ plan });

      expect(response.status).toBe(400);
      expect(createSession).not.toHaveBeenCalled();
    }
  });

  it("rejects a request with no plan and a malformed body", async () => {
    for (const options of [{}, { raw: "not json" }, { raw: "" }]) {
      createSession.mockClear();
      const response = await post({}, options as RequestInitOptions);

      expect(response.status).toBe(400);
      expect(createSession).not.toHaveBeenCalled();
    }
  });
});

// ===========================================================================
// The auth boundary — resolveAccount
// ===========================================================================

describe("POST /api/checkout — the auth boundary", () => {
  it("returns 401 for a request with no verified session", async () => {
    givenNoResolution("unauthenticated");

    const response = await post({ plan: "shield" });

    expect(response.status).toBe(401);
  });

  it("returns 404 when the caller has no account row", async () => {
    // A missing account is permanent, not transient: 503 would tell the client
    // (and any retry logic in front of it) to try again forever.
    givenNoResolution("no_account");

    const response = await post({ plan: "shield" });

    expect(response.status).toBe(404);
  });

  it("returns 503 when account resolution is unavailable", async () => {
    givenNoResolution("unavailable");

    const response = await post({ plan: "shield" });

    expect(response.status).toBe(503);
  });

  it("creates no Stripe session on any failed resolution", async () => {
    // Billing an identity we could not verify is the worst outcome available
    // to this route.
    for (const reason of ["unauthenticated", "no_account", "unavailable"] as const) {
      createSession.mockClear();
      getStripe.mockClear();
      givenNoResolution(reason);

      const response = await post({ plan: "shield" });

      expect(response.ok).toBe(false);
      expect(getStripe).not.toHaveBeenCalled();
      expect(createSession).not.toHaveBeenCalled();
    }
  });

  it("provisions an account row so a first-time buyer is not blocked", async () => {
    // OAuth signup creates the auth user but no accounts row; without
    // `create` the first thing a new owner ever tries to buy would 404.
    await post({ plan: "shield" });

    expect(resolveAccount).toHaveBeenCalledWith({ create: true });
  });
});

// ===========================================================================
// The metadata contract with src/app/api/webhooks/stripe/route.ts
// ===========================================================================

describe("POST /api/checkout — the webhook metadata contract", () => {
  it("writes the exact keys the checkout.session.completed handler reads back", async () => {
    await post({ plan: "shield" });

    const metadata = sessionMetadata();
    for (const key of WEBHOOK_METADATA_KEYS) {
      expect(metadata[key]).toBeTruthy();
      // Stripe stores metadata as strings; the webhook does Number(amount).
      expect(typeof metadata[key]).toBe("string");
    }
    expect(metadata.user_id).toBe(SESSION_USER.id);
    expect(metadata.account_id).toBe(ACCOUNT.id);
    expect(Number(metadata.amount_cents)).toBe(SHIELD_CENTS);
  });

  it("mirrors the same metadata onto the subscription", async () => {
    // Session metadata does not propagate to the subscription. Without this
    // bag, later invoice/subscription events cannot resolve the account.
    await post({ plan: "shield" });

    const subscriptionData = sessionParams().subscription_data as {
      metadata: Record<string, string>;
    };
    expect(subscriptionData.metadata).toEqual(sessionMetadata());
  });

  it("derives user_id and account_id from the session, never from the body", async () => {
    // Stripe signs whatever we put in metadata and the webhook trusts it
    // completely. If the body could set it, anyone could upgrade any account
    // — or take over one by upgrading it with their own card.
    await post({
      plan: "shield",
      user_id: "99999999-9999-4999-8999-999999999999",
      account_id: "deadbeef-0000-4000-8000-000000000000",
      amount_cents: "1",
    });

    expect(sessionMetadata()).toMatchObject({
      user_id: SESSION_USER.id,
      account_id: ACCOUNT.id,
      amount_cents: String(SHIELD_CENTS),
    });
  });

  it("reports the amount the webhook will bill as revenue", async () => {
    // The webhook turns metadata.amount_cents into `amount_usd` on
    // checkout_completed. A mismatch here misreports revenue for h-08.
    await post({ plan: "shield" });

    expect(Number(sessionMetadata().amount_cents) / 100).toBe(79);
  });
});

// ===========================================================================
// Linking the Stripe customer
// ===========================================================================

describe("POST /api/checkout — customer linkage", () => {
  it("reuses the existing Stripe customer when the account has one", async () => {
    givenAccount({ stripe_customer_id: "cus_test_000000000001" });

    await post({ plan: "shield" });

    expect(sessionParams().customer).toBe("cus_test_000000000001");
    // Stripe rejects a session that carries both.
    expect(sessionParams().customer_email).toBeUndefined();
  });

  it("prefills the session with the session email for a first purchase", async () => {
    await post({ plan: "shield" });

    expect(sessionParams().customer_email).toBe(SESSION_USER.email);
    expect(sessionParams().customer).toBeUndefined();
  });

  it("still creates a session when the session user has no email", async () => {
    resolveAccount.mockResolvedValue({
      ok: true,
      ctx: { userId: SESSION_USER.id, email: null, account: ACCOUNT, db: {} },
    });

    const response = await post({ plan: "shield" });

    expect(response.status).toBe(200);
    expect(sessionParams().customer_email).toBeUndefined();
  });
});

// ===========================================================================
// An account that already pays
// ===========================================================================

describe("POST /api/checkout — an account already on Shield", () => {
  it("refuses to open a second subscription for an existing subscriber", async () => {
    // Nothing downgrades `plan` back to 'free', and entitlement is read from
    // `plan` alone (see the gate in /api/audit-file). A second session would
    // bill $79/mo twice for the same unlocked account.
    givenAccount({ plan: "shield" });

    const response = await post({ plan: "shield" });

    expect(response.status).toBe(409);
    expect(createSession).not.toHaveBeenCalled();
  });

  it("explains the refusal in words the pricing page can show", async () => {
    givenAccount({ plan: "shield" });

    const body = (await (await post({ plan: "shield" })).json()) as { error: string };
    expect(body.error).toMatch(/already/i);
  });
});

// ===========================================================================
// Stripe failures never escape as unhandled rejections
// ===========================================================================

describe("POST /api/checkout — Stripe failures", () => {
  it("returns 503 without calling Stripe when no secret key is configured", async () => {
    // 503, not 500: the deployment is unprovisioned, not broken.
    delete process.env.STRIPE_SECRET_KEY;

    const response = await post({ plan: "shield" });

    expect(response.status).toBe(503);
    expect(getStripe).not.toHaveBeenCalled();
  });

  it("still creates a session in demo mode without a secret key", async () => {
    delete process.env.STRIPE_SECRET_KEY;
    process.env.DEMO_MODE = "true";

    const response = await post({ plan: "shield" });

    expect(response.status).toBe(200);
    expect(createSession).toHaveBeenCalledTimes(1);
  });

  it("returns 500 rather than rejecting when the Stripe client cannot be built", async () => {
    getStripe.mockImplementation(() => {
      throw new Error("STRIPE_SECRET_KEY is not configured");
    });

    const response = await post({ plan: "shield" });

    expect(response.status).toBe(500);
  });

  it("returns 500 when the session cannot be created", async () => {
    createSession.mockRejectedValue(new Error("Stripe API unreachable"));

    const response = await post({ plan: "shield" });

    expect(response.status).toBe(500);
    expect(await response.json()).toEqual({ error: "Checkout failed" });
  });

  it("does not leak the Stripe error text to the caller", async () => {
    createSession.mockRejectedValue(
      new Error("Invalid API Key provided: sk_live_51H******")
    );

    const response = await post({ plan: "shield" });

    expect(await response.text()).not.toContain("sk_live");
  });

  it("returns 500 when Stripe returns a session with no url", async () => {
    // Responding 200 with `{ url: undefined }` would leave the button spinning
    // on a checkout the customer can never reach.
    createSession.mockResolvedValue({ id: "cs_test_000000000001", url: null });

    const response = await post({ plan: "shield" });

    expect(response.status).toBe(500);
  });
});

// ===========================================================================
// Redirect URLs
// ===========================================================================

describe("POST /api/checkout — redirect urls", () => {
  it("returns the buyer to the dashboard on success and to pricing on cancel", async () => {
    process.env.NEXT_PUBLIC_SITE_URL = "https://tipguard.app/";

    await post({ plan: "shield" });

    expect(sessionParams().success_url).toBe("https://tipguard.app/dashboard?upgraded=1");
    expect(sessionParams().cancel_url).toBe("https://tipguard.app/pricing");
  });

  it("falls back to the request origin, not a forwarded host header", async () => {
    // Without the fallback an unset NEXT_PUBLIC_SITE_URL sends Stripe
    // "undefined/dashboard" and the post-payment redirect dead-ends.
    await post(
      { plan: "shield" },
      { headers: { "x-forwarded-host": "attacker.test", host: "attacker.test" } }
    );

    expect(sessionParams().success_url).toBe(
      "https://request-host.test/dashboard?upgraded=1"
    );
    expect(String(sessionParams().cancel_url)).not.toContain("attacker.test");
  });
});

// ===========================================================================
// Rate limiting (Rule 6)
// ===========================================================================

describe("POST /api/checkout — rate limiting", () => {
  it("returns 429 without touching auth or Stripe once the limit is hit", async () => {
    rateLimit.mockReturnValue({ success: false, remaining: 0 });

    const response = await post({ plan: "shield" });

    expect(response.status).toBe(429);
    expect(resolveAccount).not.toHaveBeenCalled();
    expect(getStripe).not.toHaveBeenCalled();
  });

  it("keys the limiter on the trusted client ip, not the forwarded chain", async () => {
    // A caller who can vary the key has no rate limit at all.
    await post({ plan: "shield" });

    expect(clientIpFromHeaders).toHaveBeenCalledTimes(1);
    const [key] = rateLimit.mock.calls[0];
    expect(key).toBe(`checkout:${CLIENT_IP}`);
    expect(String(key)).not.toContain(SPOOFED_IP);
  });

  it("uses its own bucket rather than sharing one with other routes", async () => {
    await post({ plan: "shield" });

    expect(String(rateLimit.mock.calls[0][0])).toMatch(/^checkout:/);
  });
});

// ===========================================================================
// b-10 criterion: "checkout_started fires with notices_sent_at_upgrade and
// open_violation_count"
//
// The event fires client-side on the click, before the redirect (see
// src/app/pricing/upgrade-button.tsx), so that abandoning on Stripe's hosted
// page still counts as intent to pay — h-06's numerator. What is pinned here
// is the payload contract: EVENTS.yaml marks both properties required.
// ===========================================================================

describe("checkout_started — the h-06 numerator", () => {
  it("checkout_started fires with notices_sent_at_upgrade and open_violation_count", () => {
    trackCheckoutStarted({
      notices_sent_at_upgrade: 3,
      open_violation_count: 2,
    });

    expect(track).toHaveBeenCalledTimes(1);
    const [event, properties] = track.mock.calls[0];
    expect(event).toBe("checkout_started");
    expect(properties).toMatchObject({
      notices_sent_at_upgrade: 3,
      open_violation_count: 2,
      funnel_stage: "monetize",
    });
  });

  it("keeps a zero count as a number rather than dropping the property", () => {
    // An owner who upgrades with no notices sent is the case h-06 most needs
    // to see; a falsy-filtered property would make that cohort invisible.
    trackCheckoutStarted({ notices_sent_at_upgrade: 0, open_violation_count: 0 });

    expect(track.mock.calls[0][1]).toMatchObject({
      notices_sent_at_upgrade: 0,
      open_violation_count: 0,
    });
  });
});
