// Unit tests for POST /api/webhooks/stripe — behavior b-11.
//
// This handler is the only place in the product where money becomes
// entitlement. One delivery of `checkout.session.completed` does three
// irreversible things:
//
//   1. flips `accounts.plan` to 'shield' (which is what unlocks the audit-file
//      export — see the plan gate in /api/audit-file),
//   2. fires `checkout_completed`, the experiment's revenue event (h-08), and
//   3. mails the customer a welcome email.
//
// Every failure mode here is silent by construction: Stripe is the only
// caller, nobody is watching a browser tab, and a wrong 200 makes Stripe stop
// retrying forever. So the invariants under test are:
//
//   * Identity comes from `session.metadata`, which we wrote server-side at
//     checkout creation — NEVER from `customer_email`, which the buyer types.
//   * `checkout_completed` fires exactly once per session, enforced by the
//     `stripe_events` INSERT + PG 23505 guard.
//   * A 200 means "do not retry": it may only be returned when the event was
//     fully processed, or when retrying could never help.
//   * A 500 means "retry": it must leave the ledger in a state where the
//     retry can actually re-run.
//
// `tests/flows.test.ts` asserts the unsigned-request rejection end-to-end.
// These tests go under it: the raw-body contract, the plan mutation, the
// idempotency path, and the email — none of which that file can reach without
// a live database and a real signing secret.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST } from "./route";

const { getStripe, createServiceRoleClient, trackServerEvent, sendWelcomeEmail } =
  vi.hoisted(() => ({
    getStripe: vi.fn(),
    createServiceRoleClient: vi.fn(),
    trackServerEvent: vi.fn(),
    sendWelcomeEmail: vi.fn(),
  }));

vi.mock("@/lib/stripe", () => ({ getStripe }));
vi.mock("@/lib/supabase-server", () => ({ createServiceRoleClient }));
vi.mock("@/lib/analytics-server", () => ({ trackServerEvent }));
vi.mock("@/lib/email", () => ({ sendWelcomeEmail }));

const constructEvent = vi.fn();
const retrieveSubscription = vi.fn();

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

/** The row the webhook reads back — `user_id` here is authoritative. */
const ACCOUNT = {
  id: "22222222-2222-4222-8222-222222222222",
  user_id: "11111111-1111-4111-8111-111111111111",
  restaurant_name: "The Tipped Spoon",
  plan: "free",
};

const CUSTOMER_ID = "cus_test_000000000001";
const SUBSCRIPTION_ID = "sub_test_000000000001";
const SESSION_ID = "cs_test_000000000001";
const EVENT_ID = "evt_test_000000000001";

const PERIOD_END_ISO = "2026-09-09T00:00:00.000Z";
const PERIOD_END_SECONDS = Date.parse(PERIOD_END_ISO) / 1000;
const THIRTY_DAYS_MS = 30 * 24 * 60 * 60 * 1000;

type Session = Record<string, unknown>;

function makeSession(overrides: Session = {}): Session {
  return {
    id: SESSION_ID,
    object: "checkout.session",
    customer: CUSTOMER_ID,
    customer_email: null,
    customer_details: { email: "owner@restaurant.test" },
    subscription: SUBSCRIPTION_ID,
    // Written by /api/checkout from the verified session — see the `metadata`
    // bag in src/app/api/checkout/route.ts.
    metadata: {
      user_id: ACCOUNT.user_id,
      account_id: ACCOUNT.id,
      plan: "shield",
      amount_cents: "7900",
    },
    ...overrides,
  };
}

function makeEvent(overrides: Record<string, unknown> = {}) {
  return {
    id: EVENT_ID,
    type: "checkout.session.completed",
    data: { object: makeSession() },
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Recording stand-in for the service-role PostgREST client
//
// The `stripe_events` ledger is modelled for real — inserting the same id
// twice returns PG 23505 — because the whole point of these tests is what
// happens on a redelivery.
// ---------------------------------------------------------------------------

type QueryResult = { data: unknown; error: unknown };
type ResultSource = QueryResult | (() => QueryResult);

const OK: QueryResult = { data: null, error: null };
const UNIQUE_VIOLATION: QueryResult = {
  data: null,
  error: {
    code: "23505",
    message: 'duplicate key value violates unique constraint "stripe_events_pkey"',
  },
};

interface DbCall {
  table: string;
  op: "select" | "insert" | "update" | "delete";
  columns: string;
  filters: [string, unknown][];
  payload: unknown;
}

interface DbScenario {
  /** Forces an outcome on the idempotency insert, bypassing the ledger. */
  eventInsert?: ResultSource;
  account?: ResultSource;
  accountUpdate?: ResultSource;
}

function resolveSource(source: ResultSource | undefined, fallback: QueryResult) {
  if (!source) return fallback;
  return typeof source === "function" ? source() : source;
}

function makeDb(scenario: DbScenario = {}) {
  const calls: DbCall[] = [];
  const ledger = new Set<string>();

  const resultFor = (call: DbCall): QueryResult => {
    if (call.table === "stripe_events" && call.op === "insert") {
      if (scenario.eventInsert) return resolveSource(scenario.eventInsert, OK);
      const id = String(
        (call.payload as { stripe_event_id?: unknown }).stripe_event_id
      );
      if (ledger.has(id)) return UNIQUE_VIOLATION;
      ledger.add(id);
      return OK;
    }
    if (call.table === "stripe_events" && call.op === "delete") {
      for (const [column, value] of call.filters) {
        if (column === "stripe_event_id") ledger.delete(String(value));
      }
      return OK;
    }
    if (call.table === "accounts" && call.op === "select") {
      return resolveSource(scenario.account, { data: ACCOUNT, error: null });
    }
    if (call.table === "accounts" && call.op === "update") {
      return resolveSource(scenario.accountUpdate, OK);
    }
    throw new Error(`unexpected query: ${call.op} ${call.table}`);
  };

  /**
   * Supabase query builders are thenables. The route awaits the builder itself
   * for the insert/update chains and calls `.maybeSingle()` on the account
   * lookup, so both terminations resolve through the same recorder.
   */
  const makeBuilder = (table: string) => {
    const call: DbCall = {
      table,
      op: "select",
      columns: "",
      filters: [],
      payload: undefined,
    };
    const run = () => {
      calls.push(call);
      return resultFor(call);
    };
    const builder = {
      select: (columns: string) => {
        call.columns = columns;
        return builder;
      },
      insert: (payload: unknown) => {
        call.op = "insert";
        call.payload = payload;
        return builder;
      },
      update: (payload: unknown) => {
        call.op = "update";
        call.payload = payload;
        return builder;
      },
      delete: () => {
        call.op = "delete";
        return builder;
      },
      eq: (column: string, value: unknown) => {
        call.filters.push([column, value]);
        return builder;
      },
      maybeSingle: async () => run(),
      then: <T>(
        onFulfilled?: (value: QueryResult) => T,
        onRejected?: (reason: unknown) => T
      ) =>
        Promise.resolve()
          .then(run)
          .then(onFulfilled, onRejected),
    };
    return builder;
  };

  const db = { from: (table: string) => makeBuilder(table) };

  return {
    db,
    calls,
    where: (table: string, op: DbCall["op"]) =>
      calls.filter((call) => call.table === table && call.op === op),
  };
}

/** Wires a fresh recording client and returns its handle. */
function givenDb(scenario: DbScenario = {}) {
  const harness = makeDb(scenario);
  createServiceRoleClient.mockReturnValue(harness.db);
  return harness;
}

// ---------------------------------------------------------------------------
// Request helpers
// ---------------------------------------------------------------------------

const SIGNATURE = "t=1700000000,v1=0123456789abcdef";

function makeRequest(rawBody: string, signature: string | null = SIGNATURE) {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (signature !== null) headers["stripe-signature"] = signature;
  return new Request("https://request-host.test/api/webhooks/stripe", {
    method: "POST",
    headers,
    body: rawBody,
  });
}

/** Delivers a signed event: the mocked verifier returns exactly `event`. */
function deliver(
  event: unknown,
  options: { rawBody?: string; signature?: string | null } = {}
) {
  constructEvent.mockReturnValue(event);
  return POST(
    makeRequest(
      options.rawBody ?? JSON.stringify(event),
      options.signature === undefined ? SIGNATURE : options.signature
    )
  );
}

/** Nothing that a paying customer would notice happened. */
function expectNoSideEffects(where: ReturnType<typeof makeDb>["where"]) {
  expect(where("accounts", "update")).toEqual([]);
  expect(trackServerEvent).not.toHaveBeenCalled();
  expect(sendWelcomeEmail).not.toHaveBeenCalled();
}

const ENV_KEYS = [
  "STRIPE_WEBHOOK_SECRET",
  "DEMO_MODE",
  "NEXT_PUBLIC_SITE_URL",
] as const;
const originalEnv: Record<string, string | undefined> = {};

beforeEach(() => {
  vi.resetAllMocks();
  for (const key of ENV_KEYS) originalEnv[key] = process.env[key];
  process.env.STRIPE_WEBHOOK_SECRET = "whsec_test_secret";
  delete process.env.DEMO_MODE;
  delete process.env.NEXT_PUBLIC_SITE_URL;

  getStripe.mockReturnValue({
    webhooks: { constructEvent },
    subscriptions: { retrieve: retrieveSubscription },
  });
  retrieveSubscription.mockResolvedValue({ current_period_end: PERIOD_END_SECONDS });
  trackServerEvent.mockResolvedValue(undefined);
  sendWelcomeEmail.mockResolvedValue(undefined);
  givenDb();

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
// b-11 criterion: "The webhook signature is verified against
// STRIPE_WEBHOOK_SECRET and unsigned requests are rejected"
// ===========================================================================

describe("POST /api/webhooks/stripe — signature verification", () => {
  it("The webhook signature is verified against STRIPE_WEBHOOK_SECRET and unsigned requests are rejected", async () => {
    const { where } = givenDb();

    const unsigned = await deliver(makeEvent(), { signature: null });
    expect(unsigned.status).toBe(400);
    expect(constructEvent).not.toHaveBeenCalled();

    constructEvent.mockImplementation(() => {
      throw new Error("No signatures found matching the expected signature");
    });
    const tampered = await POST(makeRequest(JSON.stringify(makeEvent())));
    expect(tampered.status).toBe(400);

    expectNoSideEffects(where);
  });

  it("verifies the RAW request body, not a re-serialized object", async () => {
    // Stripe signs the exact bytes it sent. `JSON.parse` + `JSON.stringify`
    // round-trips reorder keys and drop insignificant whitespace, which makes
    // every signature fail in production while every mocked test still passes.
    const rawBody =
      '{\n  "type": "checkout.session.completed",\n  "id": "evt_test_000000000001",\n  "data": {"object": {}}\n}';
    await deliver(makeEvent(), { rawBody });

    const [body] = constructEvent.mock.calls[0];
    expect(typeof body).toBe("string");
    expect(body).toBe(rawBody);
  });

  it("passes the stripe-signature header and the configured secret to the verifier", async () => {
    await deliver(makeEvent());

    const [, signature, secret] = constructEvent.mock.calls[0];
    expect(signature).toBe(SIGNATURE);
    expect(secret).toBe("whsec_test_secret");
  });

  it("rejects a request with no stripe-signature header before touching the database", async () => {
    const { calls } = givenDb();
    const response = await deliver(makeEvent(), { signature: null });

    expect(response.status).toBe(400);
    expect(calls).toEqual([]);
  });

  it("does not explain why verification failed", async () => {
    // The rejection reason is a signing oracle; it must never reach the caller.
    constructEvent.mockImplementation(() => {
      throw new Error("Timestamp outside the tolerance zone (whsec_test_secret)");
    });
    const response = await POST(makeRequest(JSON.stringify(makeEvent())));

    expect(response.status).toBe(400);
    expect(await response.text()).not.toContain("whsec_test_secret");
  });

  it("returns 503 without verifying when no webhook secret is configured", async () => {
    // Verifying against "" would accept nothing anyway, but a 400 would tell
    // Stripe the event was malformed. 503 keeps the retries coming until the
    // secret is provisioned.
    delete process.env.STRIPE_WEBHOOK_SECRET;
    const { where } = givenDb();

    const response = await deliver(makeEvent());

    expect(response.status).toBe(503);
    expect(constructEvent).not.toHaveBeenCalled();
    expectNoSideEffects(where);
  });
});

// ===========================================================================
// b-11 criterion: "trackServerEvent('checkout_completed', user.id,
// { plan: 'shield' }) is called exactly once per session id"
// ===========================================================================

describe("POST /api/webhooks/stripe — idempotency", () => {
  it("trackServerEvent('checkout_completed', user.id, { plan: 'shield' }) is called exactly once per session id", async () => {
    const { where } = givenDb();
    const event = makeEvent();

    const first = await deliver(event);
    expect(first.status).toBe(200);

    // Same event id — Stripe redelivering the same session completion.
    const redelivery = await deliver(event);
    expect(redelivery.status).toBe(200);

    expect(trackServerEvent).toHaveBeenCalledTimes(1);
    expect(trackServerEvent.mock.calls[0][0]).toBe("checkout_completed");
    expect(trackServerEvent.mock.calls[0][1]).toBe(ACCOUNT.user_id);
    expect(trackServerEvent.mock.calls[0][2]).toMatchObject({ plan: "shield" });
    expect(where("accounts", "update")).toHaveLength(1);
    expect(sendWelcomeEmail).toHaveBeenCalledTimes(1);
  });

  it("records the event id in stripe_events before any account mutation", async () => {
    const { calls } = givenDb();
    await deliver(makeEvent());

    expect(calls[0]).toMatchObject({ table: "stripe_events", op: "insert" });
    expect(calls[0].payload).toEqual({ stripe_event_id: EVENT_ID });
  });

  it("returns 200 on a unique violation so Stripe stops retrying", async () => {
    const { where } = givenDb({ eventInsert: UNIQUE_VIOLATION });

    const response = await deliver(makeEvent());

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ received: true });
    expectNoSideEffects(where);
  });

  it("does not re-read the account on a redelivery", async () => {
    // The short-circuit has to happen before the lookup, or a concurrent pair
    // of deliveries both read the account and both fire the event.
    const { where } = givenDb({ eventInsert: UNIQUE_VIOLATION });
    await deliver(makeEvent());

    expect(where("accounts", "select")).toEqual([]);
  });

  it("returns 500 — not 200 — when the ledger insert fails for any other reason", async () => {
    // Treating an unreachable ledger as "already processed" would drop the
    // upgrade on the floor and tell Stripe everything was fine.
    const { where } = givenDb({
      eventInsert: { data: null, error: { code: "57014", message: "statement timeout" } },
    });

    const response = await deliver(makeEvent());

    expect(response.status).toBe(500);
    expectNoSideEffects(where);
  });

  it("processes two different events for the same account independently", async () => {
    givenDb();
    await deliver(makeEvent({ id: "evt_first" }));
    await deliver(makeEvent({ id: "evt_second" }));

    expect(trackServerEvent).toHaveBeenCalledTimes(2);
  });

  it("lets a Stripe retry re-run the upgrade after a transient persistence failure", async () => {
    // The ledger row is written BEFORE the mutation. If a failed delivery
    // leaves it behind, the retry hits the 23505 short-circuit, returns 200,
    // and the paying customer stays on the free plan forever — with Stripe
    // reporting the webhook as delivered.
    let attempt = 0;
    const { where } = givenDb({
      accountUpdate: () => {
        attempt += 1;
        return attempt === 1
          ? { data: null, error: { message: "deadlock detected" } }
          : OK;
      },
    });
    const event = makeEvent();

    const failed = await deliver(event);
    expect(failed.status).toBe(500);
    expect(trackServerEvent).not.toHaveBeenCalled();

    const retry = await deliver(event);
    expect(retry.status).toBe(200);
    expect(where("accounts", "update")).toHaveLength(2);
    expect(trackServerEvent).toHaveBeenCalledTimes(1);
  });

  it("releases the ledger row when the account lookup fails", async () => {
    const { where } = givenDb({
      account: { data: null, error: { message: "connection refused" } },
    });

    const response = await deliver(makeEvent());

    expect(response.status).toBe(500);
    expect(where("stripe_events", "delete")[0]?.filters).toEqual([
      ["stripe_event_id", EVENT_ID],
    ]);
  });

  it("keeps the ledger row when the event was fully processed", async () => {
    const { where } = givenDb();
    await deliver(makeEvent());

    expect(where("stripe_events", "delete")).toEqual([]);
  });

  it("keeps the ledger row for an event it deliberately declines to process", async () => {
    // A session with no metadata can never succeed on retry; releasing the key
    // would just invite Stripe to redeliver a permanently unprocessable event.
    const { where } = givenDb();
    await deliver(
      makeEvent({ data: { object: makeSession({ metadata: {} }) } })
    );

    expect(where("stripe_events", "delete")).toEqual([]);
  });
});

// ===========================================================================
// b-11 criterion: "accounts.plan becomes 'shield' and stripe_customer_id plus
// current_period_end are persisted"
// ===========================================================================

describe("POST /api/webhooks/stripe — the plan mutation", () => {
  it("accounts.plan becomes 'shield' and stripe_customer_id plus current_period_end are persisted", async () => {
    const { where } = givenDb();

    const response = await deliver(makeEvent());

    expect(response.status).toBe(200);
    const updates = where("accounts", "update");
    expect(updates).toHaveLength(1);
    expect(updates[0].payload).toEqual({
      plan: "shield",
      stripe_customer_id: CUSTOMER_ID,
      current_period_end: PERIOD_END_ISO,
    });
    expect(updates[0].filters).toEqual([["id", ACCOUNT.id]]);
  });

  it("resolves the account from metadata.account_id", async () => {
    const { where } = givenDb();
    await deliver(makeEvent());

    expect(where("accounts", "select")[0].filters).toEqual([["id", ACCOUNT.id]]);
  });

  it("falls back to metadata.user_id when the session carries no account_id", async () => {
    const { where } = givenDb();
    await deliver(
      makeEvent({
        data: {
          object: makeSession({
            metadata: { user_id: ACCOUNT.user_id, amount_cents: "7900" },
          }),
        },
      })
    );

    expect(where("accounts", "select")[0].filters).toEqual([
      ["user_id", ACCOUNT.user_id],
    ]);
    expect(where("accounts", "update")).toHaveLength(1);
  });

  it("never resolves the account from customer_email, which the buyer controls", async () => {
    // Stripe Checkout lets the payer type any address. If that address chose
    // which row to upgrade, anyone could buy Shield for someone else's
    // account — or, worse, for an account they then take over.
    const { where } = givenDb();
    const hostile = makeSession({
      customer_email: "victim@other-restaurant.test",
      customer_details: { email: "victim@other-restaurant.test" },
    });
    await deliver(makeEvent({ data: { object: hostile } }));

    const lookup = where("accounts", "select")[0];
    expect(lookup.filters).toEqual([["id", ACCOUNT.id]]);
    expect(where("accounts", "update")[0].filters).toEqual([["id", ACCOUNT.id]]);
    for (const [, value] of [...lookup.filters, ...where("accounts", "update")[0].filters]) {
      expect(value).not.toBe("victim@other-restaurant.test");
    }
  });

  it("upgrades nothing when the session carries no account metadata at all", async () => {
    const { where } = givenDb();
    const response = await deliver(
      makeEvent({
        data: {
          object: makeSession({
            metadata: {},
            customer_email: "buyer@anywhere.test",
          }),
        },
      })
    );

    // 200: a session with no metadata is unprocessable on every retry.
    expect(response.status).toBe(200);
    expect(where("accounts", "select")).toEqual([]);
    expectNoSideEffects(where);
  });

  it("returns 200 and mutates nothing when no account matches the session", async () => {
    const { where } = givenDb({ account: { data: null, error: null } });

    const response = await deliver(makeEvent());

    expect(response.status).toBe(200);
    expectNoSideEffects(where);
  });

  it("persists the customer id when Stripe expands `customer` into an object", async () => {
    const { where } = givenDb();
    await deliver(
      makeEvent({
        data: { object: makeSession({ customer: { id: CUSTOMER_ID, object: "customer" } }) },
      })
    );

    expect(where("accounts", "update")[0].payload).toMatchObject({
      stripe_customer_id: CUSTOMER_ID,
    });
  });

  it("persists a null customer id rather than a stringified object", async () => {
    const { where } = givenDb();
    await deliver(makeEvent({ data: { object: makeSession({ customer: null }) } }));

    expect(where("accounts", "update")[0].payload).toMatchObject({
      stripe_customer_id: null,
    });
  });

  it("returns 500 when the account lookup errors, so Stripe retries", async () => {
    const { where } = givenDb({
      account: { data: null, error: { message: "connection refused" } },
    });

    const response = await deliver(makeEvent());

    expect(response.status).toBe(500);
    expectNoSideEffects(where);
  });

  it("returns 500 and fires nothing when the plan update fails", async () => {
    // Reporting the upgrade before it landed would give the customer a
    // revenue event, a welcome email, and no unlocked export.
    givenDb({ accountUpdate: { data: null, error: { message: "deadlock detected" } } });

    const response = await deliver(makeEvent());

    expect(response.status).toBe(500);
    expect(trackServerEvent).not.toHaveBeenCalled();
    expect(sendWelcomeEmail).not.toHaveBeenCalled();
  });

  it("returns 500 when the service-role client cannot be constructed", async () => {
    createServiceRoleClient.mockImplementation(() => {
      throw new Error("SUPABASE_SERVICE_ROLE_KEY is not configured");
    });

    const response = await deliver(makeEvent());

    expect(response.status).toBe(500);
    expect(trackServerEvent).not.toHaveBeenCalled();
  });

  it("returns 200 and mutates nothing for an event type it does not handle", async () => {
    const { where } = givenDb();

    const response = await deliver(
      makeEvent({ id: "evt_invoice", type: "invoice.payment_failed" })
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ received: true });
    expect(where("accounts", "select")).toEqual([]);
    expectNoSideEffects(where);
  });
});

// ===========================================================================
// current_period_end — the value that decides when Shield lapses
// ===========================================================================

describe("POST /api/webhooks/stripe — reading the period end", () => {
  /** Milliseconds between the persisted period end and `now`. */
  async function persistedWindowMs(where: ReturnType<typeof makeDb>["where"]) {
    const { current_period_end: value } = where("accounts", "update")[0]
      .payload as { current_period_end: string };
    expect(Number.isNaN(Date.parse(value))).toBe(false);
    return Date.parse(value) - Date.now();
  }

  it("reads current_period_end from the subscription root", async () => {
    const { where } = givenDb();
    retrieveSubscription.mockResolvedValue({
      id: SUBSCRIPTION_ID,
      current_period_end: PERIOD_END_SECONDS,
    });

    await deliver(makeEvent());

    expect(retrieveSubscription).toHaveBeenCalledWith(SUBSCRIPTION_ID);
    expect(where("accounts", "update")[0].payload).toMatchObject({
      current_period_end: PERIOD_END_ISO,
    });
  });

  it("reads current_period_end from items.data[0] on newer API versions", async () => {
    // Stripe moved the field onto the subscription item. Reading only the root
    // would silently write a 30-day window over every real renewal date.
    const { where } = givenDb();
    retrieveSubscription.mockResolvedValue({
      id: SUBSCRIPTION_ID,
      items: { data: [{ id: "si_1", current_period_end: PERIOD_END_SECONDS }] },
    });

    await deliver(makeEvent());

    expect(where("accounts", "update")[0].payload).toMatchObject({
      current_period_end: PERIOD_END_ISO,
    });
  });

  it("falls back to a 30-day window when neither shape carries the field", async () => {
    const { where } = givenDb();
    retrieveSubscription.mockResolvedValue({ id: SUBSCRIPTION_ID, items: { data: [] } });

    await deliver(makeEvent());

    // Never a null period end on a paying account.
    const windowMs = await persistedWindowMs(where);
    expect(windowMs).toBeGreaterThan(THIRTY_DAYS_MS - 60_000);
    expect(windowMs).toBeLessThanOrEqual(THIRTY_DAYS_MS);
  });

  it("falls back to a 30-day window when the value is not a finite number", async () => {
    // `new Date(NaN * 1000).toISOString()` throws RangeError, which would take
    // the whole handler down and turn a successful payment into a retry loop.
    for (const value of [Number.NaN, Number.POSITIVE_INFINITY, "1789000000", null]) {
      const { where } = givenDb();
      retrieveSubscription.mockResolvedValue({ current_period_end: value });

      const response = await deliver(makeEvent());

      expect(response.status).toBe(200);
      const windowMs = await persistedWindowMs(where);
      expect(windowMs).toBeGreaterThan(THIRTY_DAYS_MS - 60_000);
      expect(windowMs).toBeLessThanOrEqual(THIRTY_DAYS_MS);
    }
  });

  it("still upgrades the plan when the subscription cannot be retrieved", async () => {
    const { where } = givenDb();
    retrieveSubscription.mockRejectedValue(new Error("Stripe API unreachable"));

    const response = await deliver(makeEvent());

    expect(response.status).toBe(200);
    expect(where("accounts", "update")[0].payload).toMatchObject({ plan: "shield" });
    const windowMs = await persistedWindowMs(where);
    expect(windowMs).toBeGreaterThan(THIRTY_DAYS_MS - 60_000);
  });

  it("does not call Stripe when the session has no subscription", async () => {
    const { where } = givenDb();

    await deliver(
      makeEvent({ data: { object: makeSession({ subscription: null }) } })
    );

    expect(retrieveSubscription).not.toHaveBeenCalled();
    const windowMs = await persistedWindowMs(where);
    expect(windowMs).toBeGreaterThan(THIRTY_DAYS_MS - 60_000);
  });

  it("retrieves the subscription when Stripe expands it into an object", async () => {
    givenDb();
    await deliver(
      makeEvent({
        data: {
          object: makeSession({
            subscription: { id: SUBSCRIPTION_ID, object: "subscription" },
          }),
        },
      })
    );

    expect(retrieveSubscription).toHaveBeenCalledWith(SUBSCRIPTION_ID);
  });
});

// ===========================================================================
// checkout_completed — the revenue event (experiment/EVENTS.yaml)
// ===========================================================================

describe("POST /api/webhooks/stripe — the checkout_completed payload", () => {
  it("attributes the event to the account row's user, not the metadata claim", async () => {
    // metadata is signed by Stripe but authored at checkout creation; the row
    // we just upgraded is the authority on whose account this is.
    givenDb();
    await deliver(
      makeEvent({
        data: {
          object: makeSession({
            metadata: {
              user_id: "99999999-9999-4999-8999-999999999999",
              account_id: ACCOUNT.id,
              amount_cents: "7900",
            },
          }),
        },
      })
    );

    expect(trackServerEvent.mock.calls[0][1]).toBe(ACCOUNT.user_id);
  });

  it("reports the plan, the amount in dollars, and the monetize funnel stage", async () => {
    givenDb();
    await deliver(makeEvent());

    expect(trackServerEvent.mock.calls[0][2]).toEqual({
      plan: "shield",
      amount_usd: 79,
      funnel_stage: "monetize",
    });
  });

  it("converts metadata.amount_cents to dollars", async () => {
    givenDb();
    await deliver(
      makeEvent({
        data: {
          object: makeSession({
            metadata: { account_id: ACCOUNT.id, amount_cents: "12900" },
          }),
        },
      })
    );

    expect(trackServerEvent.mock.calls[0][2]).toMatchObject({ amount_usd: 129 });
  });

  it("reports the baseline price rather than NaN when the amount is missing or unparseable", async () => {
    // amount_usd is a required numeric property; a NaN serializes to null and
    // silently zeroes out revenue reporting.
    for (const amount of [undefined, "", "seventy-nine"]) {
      givenDb();
      trackServerEvent.mockClear();
      await deliver(
        makeEvent({
          data: {
            object: makeSession({
              metadata: { account_id: ACCOUNT.id, amount_cents: amount },
            }),
          },
        })
      );

      expect(trackServerEvent.mock.calls[0][2]).toMatchObject({ amount_usd: 79 });
    }
  });

  it("does not fail the request when analytics delivery throws", async () => {
    // The upgrade already landed. A rejected PostHog call must not become a
    // 500, or Stripe retries, hits the 23505 guard, and the welcome email is
    // never sent for a customer who has already paid.
    const { where } = givenDb();
    trackServerEvent.mockRejectedValue(new Error("posthog unreachable"));

    const response = await deliver(makeEvent());

    expect(response.status).toBe(200);
    expect(where("accounts", "update")).toHaveLength(1);
    expect(sendWelcomeEmail).toHaveBeenCalledTimes(1);
  });
});

// ===========================================================================
// b-11 criterion: "A welcome email is sent via Resend"
// ===========================================================================

describe("POST /api/webhooks/stripe — the welcome email", () => {
  it("A welcome email is sent via Resend", async () => {
    givenDb();
    await deliver(makeEvent());

    expect(sendWelcomeEmail).toHaveBeenCalledTimes(1);
    const [to, restaurantName, ctaUrl] = sendWelcomeEmail.mock.calls[0];
    expect(to).toBe("owner@restaurant.test");
    expect(restaurantName).toBe(ACCOUNT.restaurant_name);
    expect(new URL(ctaUrl as string).pathname).toBe("/dashboard");
  });

  it("falls back to customer_email when Stripe collected no customer details", async () => {
    givenDb();
    await deliver(
      makeEvent({
        data: {
          object: makeSession({
            customer_details: null,
            customer_email: "billing@restaurant.test",
          }),
        },
      })
    );

    expect(sendWelcomeEmail.mock.calls[0][0]).toBe("billing@restaurant.test");
  });

  it("builds the CTA on the configured site origin, not the request Host", async () => {
    process.env.NEXT_PUBLIC_SITE_URL = "https://tipguard.app/";
    givenDb();
    await deliver(makeEvent());

    expect(sendWelcomeEmail.mock.calls[0][2]).toBe("https://tipguard.app/dashboard");
  });

  it("does not fail the request when the email cannot be sent", async () => {
    // The upgrade already landed; a non-200 makes Stripe retry and re-run the
    // whole handler for a session that is already fully processed.
    const { where } = givenDb();
    sendWelcomeEmail.mockRejectedValue(new Error("resend 503"));

    const response = await deliver(makeEvent());

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ received: true });
    expect(where("accounts", "update")).toHaveLength(1);
    expect(trackServerEvent).toHaveBeenCalledTimes(1);
  });

  it("upgrades the account even when the session carries no email address", async () => {
    const { where } = givenDb();
    const response = await deliver(
      makeEvent({
        data: {
          object: makeSession({ customer_details: null, customer_email: null }),
        },
      })
    );

    expect(response.status).toBe(200);
    expect(sendWelcomeEmail).not.toHaveBeenCalled();
    expect(where("accounts", "update")[0].payload).toMatchObject({ plan: "shield" });
    expect(trackServerEvent).toHaveBeenCalledTimes(1);
  });

  it("sends no email for an account that was never upgraded", async () => {
    givenDb({ account: { data: null, error: null } });
    await deliver(makeEvent());

    expect(sendWelcomeEmail).not.toHaveBeenCalled();
  });
});
