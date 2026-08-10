// Unit tests for POST /api/account/score — behavior b-03.
//
// b-03: "a visitor who saw a failing audit-readiness score signs up; the
// anonymous score and gap list are attached to the new account; the user lands
// on /dashboard showing their score and open gaps." This route is the PERSIST
// half of that criterion — everything /dashboard renders for a brand new owner
// comes from the row this handler writes.
//
// Three properties make it dangerous:
//
//   * IDENTITY IS SESSION-DERIVED. The payload is assembled in the browser from
//     localStorage (src/app/score/pending-score.ts) and posted by two different
//     clients (src/app/signup/signup-form.tsx on the password path,
//     src/components/pending-score-claim.tsx after the OAuth round trip). A
//     `user_id` or `account_id` in that body must be inert: the write is scoped
//     to `resolveAccount()`'s row and nothing else.
//   * THE BODY IS FULLY ATTACKER-CONTROLLED. It is unauthenticated data that
//     ends up in a jsonb column which /dashboard renders. An unvalidated blob
//     here is stored junk at best.
//   * IT IS CALLED TWICE BY DESIGN. Both clients may fire for the same account,
//     and a pending record survives in localStorage for 7 days. A re-claim must
//     never let an older questionnaire clobber a newer score.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST } from "./route";
import type { AccountRow } from "@/lib/types";

const { resolveAccount } = vi.hoisted(() => ({ resolveAccount: vi.fn() }));

// Partial mock: the reason -> status mapping is real, only the resolution is
// stubbed. A test that also stubbed `statusForReason` could not detect the
// route mapping a reason to the wrong status.
vi.mock("@/lib/api-auth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-auth")>()),
  resolveAccount,
}));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const SESSION_USER_ID = "11111111-1111-4111-8111-111111111111";
const OTHER_ACCOUNT_ID = "99999999-9999-4999-8999-999999999999";

/** A freshly provisioned account: no score, no home state yet. */
const NEW_ACCOUNT: AccountRow = {
  id: "22222222-2222-4222-8222-222222222222",
  user_id: SESSION_USER_ID,
  restaurant_name: "",
  home_state: "",
  plan: "free",
  stripe_customer_id: null,
  current_period_end: null,
  readiness_score: null,
  gap_list: null,
  scored_at: null,
  last_scan_at: null,
  created_at: "2026-01-01T00:00:00.000Z",
};

/** Exactly the shape scoreAuditReadiness() produces (src/lib/scoring.ts). */
const GAPS = [
  {
    id: "notice_missing",
    label: "No signed tip-credit notice on file for any tipped employee",
    severity: "critical",
    pointsDeducted: 25,
  },
  {
    id: "overtime_base",
    label: "Overtime computed on the cash wage instead of the full minimum",
    severity: "high",
    pointsDeducted: 15,
  },
];

const SAVED_AT = "2026-02-01T10:00:00.000Z";
const NEWER_SAVED_AT = "2026-02-08T10:00:00.000Z";
const OLDER_SAVED_AT = "2026-01-20T10:00:00.000Z";

function scoreBody(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    state: "TX",
    claims_tip_credit: true,
    staff_count: 12,
    readiness_score: 62,
    gap_list: GAPS,
    estimated_exposure_usd: { low: 4200, high: 11800 },
    saved_at: SAVED_AT,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Recording stand-in for the service-role PostgREST client
// ---------------------------------------------------------------------------

type QueryResult = { data: unknown; error: unknown };

interface DbCall {
  table: string;
  op: "select" | "insert" | "update" | "delete";
  filters: [string, unknown][];
  payload: unknown;
}

/**
 * Supabase query builders are thenables, not promises — the route awaits the
 * builder itself after the last filter. The stub mirrors that so
 * `.update().eq()` resolves without special-casing a terminal method.
 */
function makeDb(result: QueryResult = { data: null, error: null }) {
  const calls: DbCall[] = [];

  const makeBuilder = (table: string) => {
    const call: DbCall = { table, op: "select", filters: [], payload: undefined };
    const builder = {
      select: () => builder,
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
      then: <T>(
        onFulfilled?: (value: QueryResult) => T,
        onRejected?: (reason: unknown) => T
      ) =>
        Promise.resolve()
          .then(() => {
            calls.push(call);
            return result;
          })
          .then(onFulfilled, onRejected),
    };
    return builder;
  };

  return {
    db: { from: (table: string) => makeBuilder(table) },
    calls,
    where: (table: string, op: DbCall["op"]) =>
      calls.filter((call) => call.table === table && call.op === op),
  };
}

function givenAccount(
  db: unknown,
  overrides: Partial<AccountRow> = {}
): AccountRow {
  const account = { ...NEW_ACCOUNT, ...overrides };
  resolveAccount.mockResolvedValue({
    ok: true,
    ctx: { userId: account.user_id, email: "owner@restaurant.test", account, db },
  });
  return account;
}

/** The common arrangement: a fresh account and a healthy database. */
function givenFreshAccount(overrides: Partial<AccountRow> = {}) {
  const harness = makeDb();
  const account = givenAccount(harness.db, overrides);
  return { ...harness, account };
}

// ---------------------------------------------------------------------------
// Request helpers
// ---------------------------------------------------------------------------

// The limiter is real, module-scoped, and shared across this file. A distinct
// source IP per request keeps tests independent of one another.
let ipCounter = 0;
function nextIp(): string {
  ipCounter += 1;
  return `203.0.113.${ipCounter % 255}.${Math.floor(ipCounter / 255)}`;
}

function makeRequest(body: unknown, ip: string = nextIp()): Request {
  return new Request("https://request-host.test/api/account/score", {
    method: "POST",
    headers: { "content-type": "application/json", "x-forwarded-for": ip },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

function post(body: unknown, ip?: string) {
  return POST(makeRequest(body, ip));
}

type AttachBody = {
  attached?: boolean;
  readiness_score?: number;
  gap_count?: number;
  error?: string;
};

/** The single `accounts` UPDATE the happy path is supposed to issue. */
function updatePayload(where: ReturnType<typeof makeDb>["where"]) {
  const updates = where("accounts", "update");
  expect(updates).toHaveLength(1);
  return updates[0].payload as Record<string, unknown>;
}

beforeEach(() => {
  vi.clearAllMocks();
  // The route logs infrastructure failures by design; keep output readable.
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ===========================================================================
// b-03 criterion: "The pre-signup score and gap list persist onto the new
// account row and render on /dashboard" — the persist half.
// ===========================================================================

describe("POST /api/account/score — the pre-signup score persists onto the account row", () => {
  it("writes the readiness score, the gap list, and when it was scored", async () => {
    const { where } = givenFreshAccount();

    const response = await post(scoreBody());

    expect(response.status).toBe(200);
    expect(updatePayload(where)).toMatchObject({
      readiness_score: 62,
      gap_list: GAPS,
      scored_at: SAVED_AT,
    });
  });

  it("preserves the gap list verbatim, in severity order, for /dashboard to render", async () => {
    // /dashboard lists open gaps straight out of this jsonb column. Reordering
    // or trimming here changes what the owner is told to fix first.
    const { where } = givenFreshAccount();

    await post(scoreBody());

    expect(updatePayload(where).gap_list).toEqual(GAPS);
  });

  it("returns the score and gap count the dashboard confirms the attach with", async () => {
    givenFreshAccount();

    const body = (await (await post(scoreBody())).json()) as AttachBody;

    expect(body).toEqual({ attached: true, readiness_score: 62, gap_count: 2 });
  });

  it("updates the existing row rather than inserting or deleting one", async () => {
    // The account row already exists (resolveAccount provisions it). An INSERT
    // here would orphan the row every other route reads.
    const { where } = givenFreshAccount();

    await post(scoreBody());

    expect(where("accounts", "insert")).toEqual([]);
    expect(where("accounts", "delete")).toEqual([]);
    expect(where("accounts", "update")).toHaveLength(1);
  });

  it("attaches a perfect score without treating 100 as nothing to save", async () => {
    // A clean questionnaire is still a scored account: `scored_at` is what
    // /dashboard uses to tell "scored, all clear" from "never scored".
    const { where } = givenFreshAccount();

    const body = (await (
      await post(scoreBody({ readiness_score: 100, gap_list: [] }))
    ).json()) as AttachBody;

    expect(body).toEqual({ attached: true, readiness_score: 100, gap_count: 0 });
    expect(updatePayload(where)).toMatchObject({ readiness_score: 100, gap_list: [] });
  });

  it("attaches a zero score rather than dropping a falsy value", async () => {
    const { where } = givenFreshAccount();

    await post(scoreBody({ readiness_score: 0 }));

    expect(updatePayload(where).readiness_score).toBe(0);
  });

  it("normalizes the scored_at stamp to ISO-8601 UTC", async () => {
    const { where } = givenFreshAccount();

    await post(scoreBody({ saved_at: "2026-02-01T12:00:00+02:00" }));

    expect(updatePayload(where).scored_at).toBe("2026-02-01T10:00:00.000Z");
  });
});

// ===========================================================================
// Identity comes from the verified session, never from the body
// ===========================================================================

describe("POST /api/account/score — identity is session-derived", () => {
  it("scopes the write to the caller's own account row", async () => {
    const { where, account } = givenFreshAccount();

    await post(scoreBody());

    expect(where("accounts", "update")[0].filters).toEqual([["id", account.id]]);
  });

  it("ignores an account_id or user_id supplied in the request body", async () => {
    // The body is assembled in the browser. If either key could steer the
    // write, any signed-in visitor could overwrite another restaurant's score.
    const { where, account } = givenFreshAccount();

    await post(
      scoreBody({
        account_id: OTHER_ACCOUNT_ID,
        user_id: OTHER_ACCOUNT_ID,
        id: OTHER_ACCOUNT_ID,
      })
    );

    const update = where("accounts", "update")[0];
    expect(update.filters).toEqual([["id", account.id]]);
    expect(JSON.stringify(update.payload)).not.toContain(OTHER_ACCOUNT_ID);
  });

  it("does not forward unknown body fields into the update", async () => {
    // `plan` and `stripe_customer_id` are the entitlement columns. A body that
    // could reach them would be a free upgrade to Shield.
    const { where } = givenFreshAccount();

    await post(
      scoreBody({ plan: "shield", stripe_customer_id: "cus_attacker", last_scan_at: "2030-01-01" })
    );

    const payload = updatePayload(where);
    expect(payload).not.toHaveProperty("plan");
    expect(payload).not.toHaveProperty("stripe_customer_id");
    expect(payload).not.toHaveProperty("last_scan_at");
  });

  it("writes only the score columns it is responsible for", async () => {
    const { where } = givenFreshAccount();

    await post(scoreBody());

    expect(Object.keys(updatePayload(where)).sort()).toEqual([
      "gap_list",
      "home_state",
      "readiness_score",
      "scored_at",
    ]);
  });

  it("provisions the account row so the OAuth claim is not blocked", async () => {
    // After a Google round trip the auth user exists but the accounts row may
    // not; without `create` the first claim would 404 and the score would be
    // lost — exactly the conversion h-03 measures.
    givenFreshAccount();

    await post(scoreBody());

    expect(resolveAccount).toHaveBeenCalledWith({ create: true });
  });
});

// ===========================================================================
// The auth boundary
// ===========================================================================

describe("POST /api/account/score — the auth boundary", () => {
  it("returns 401 when there is no verified session", async () => {
    resolveAccount.mockResolvedValue({ ok: false, reason: "unauthenticated" });

    expect((await post(scoreBody())).status).toBe(401);
  });

  it("returns 404 when the caller has no account row", async () => {
    // A missing account is permanent, not transient: 503 would tell the client
    // (and PendingScoreClaim's retry-on-next-load) to keep trying forever.
    resolveAccount.mockResolvedValue({ ok: false, reason: "no_account" });

    expect((await post(scoreBody())).status).toBe(404);
  });

  it("returns 503 when the database or service-role key is unavailable", async () => {
    resolveAccount.mockResolvedValue({ ok: false, reason: "unavailable" });

    expect((await post(scoreBody())).status).toBe(503);
  });

  it("never reports a score as attached on a failed resolution", async () => {
    // PendingScoreClaim clears localStorage on `response.ok`. A 2xx here would
    // discard the only copy of the score without writing it anywhere.
    for (const reason of ["unauthenticated", "no_account", "unavailable"] as const) {
      resolveAccount.mockResolvedValue({ ok: false, reason });

      const response = await post(scoreBody());
      const body = (await response.json()) as AttachBody;

      expect(response.ok).toBe(false);
      expect(body.attached).toBeUndefined();
    }
  });
});

// ===========================================================================
// Input validation — a hostile payload cannot write junk
// ===========================================================================

describe("POST /api/account/score — the payload is validated before it is stored", () => {
  it("rejects a body that is not valid JSON without touching the database", async () => {
    const { calls } = givenFreshAccount();

    expect((await post("{not json")).status).toBe(400);
    expect(calls).toEqual([]);
  });

  it("rejects a body missing the score fields", async () => {
    givenFreshAccount();

    expect((await post({})).status).toBe(400);
  });

  it("rejects a readiness score outside 0-100", async () => {
    givenFreshAccount();

    for (const readiness_score of [101, -1, 1000]) {
      const { calls } = givenFreshAccount();
      const response = await post(scoreBody({ readiness_score }));

      expect(response.status).toBe(400);
      expect(calls).toEqual([]);
    }
  });

  it("rejects a readiness score that is not a whole number", async () => {
    givenFreshAccount();

    for (const readiness_score of [62.5, "62", null, Number.NaN]) {
      expect((await post(scoreBody({ readiness_score }))).status).toBe(400);
    }
  });

  it("rejects a gap list that is not an array of gap findings", async () => {
    givenFreshAccount();

    for (const gap_list of ["<script>alert(1)</script>", { id: "x" }, [null], [{ id: "x" }]]) {
      expect((await post(scoreBody({ gap_list }))).status).toBe(400);
    }
  });

  it("rejects a gap severity outside the known set", async () => {
    givenFreshAccount();

    const gap_list = [{ ...GAPS[0], severity: "apocalyptic" }];
    expect((await post(scoreBody({ gap_list }))).status).toBe(400);
  });

  it("caps the gap list so the column cannot be used as a blob store", async () => {
    givenFreshAccount();

    const gap_list = Array.from({ length: 21 }, (_, index) => ({
      ...GAPS[0],
      id: `gap_${index}`,
    }));
    expect((await post(scoreBody({ gap_list }))).status).toBe(400);
  });

  it("caps the length of a single gap label", async () => {
    givenFreshAccount();

    const gap_list = [{ ...GAPS[0], label: "x".repeat(501) }];
    expect((await post(scoreBody({ gap_list }))).status).toBe(400);
  });

  it("rejects an implausible staff count and an implausible exposure", async () => {
    givenFreshAccount();

    expect((await post(scoreBody({ staff_count: 10_001 }))).status).toBe(400);
    expect((await post(scoreBody({ staff_count: -1 }))).status).toBe(400);
    expect(
      (await post(scoreBody({ estimated_exposure_usd: { low: -1, high: 5 } }))).status
    ).toBe(400);
  });

  it("rejects a saved_at that is not a real timestamp", async () => {
    // `saved_at` is the ONLY guard against a stale record clobbering a newer
    // score. An unparseable value that reached the handler would slip past the
    // staleness comparison (NaN is never <=) and overwrite whatever is there.
    const { calls } = givenFreshAccount({
      readiness_score: 88,
      scored_at: NEWER_SAVED_AT,
    });

    const response = await post(scoreBody({ saved_at: "whenever" }));

    expect(response.status).toBe(400);
    expect(calls).toEqual([]);
  });

  it("does not describe the schema back to the caller", async () => {
    // Forwarding ZodError.issues hands an attacker the exact field names,
    // types, and bounds to aim at.
    givenFreshAccount();

    const response = await post(scoreBody({ readiness_score: 9999 }));
    const text = await response.text();

    expect(JSON.parse(text)).toEqual({ error: "Invalid request" });
    expect(text).not.toContain("readiness_score");
    expect(text).not.toContain("too_big");
  });
});

// ===========================================================================
// Re-claiming — the route is called twice by design
// ===========================================================================

describe("POST /api/account/score — re-claiming an already-scored account", () => {
  it("ignores a stale record rather than clobbering a newer score", async () => {
    // The pending record lives in localStorage for 7 days. Somebody who
    // re-takes the questionnaire, then opens an old tab, must not lose the
    // newer result.
    const { where } = givenFreshAccount({
      readiness_score: 88,
      gap_list: [GAPS[0]],
      scored_at: NEWER_SAVED_AT,
    });

    const response = await post(scoreBody({ saved_at: OLDER_SAVED_AT }));
    const body = (await response.json()) as AttachBody;

    expect(response.status).toBe(200);
    expect(body.attached).toBe(false);
    expect(where("accounts", "update")).toEqual([]);
  });

  it("reports the score already on the account when it declines a stale attach", async () => {
    // The client renders this number; echoing the stale one would show the
    // owner a score their dashboard does not have.
    givenFreshAccount({
      readiness_score: 88,
      gap_list: [GAPS[0]],
      scored_at: NEWER_SAVED_AT,
    });

    const body = (await (
      await post(scoreBody({ readiness_score: 62, saved_at: OLDER_SAVED_AT }))
    ).json()) as AttachBody;

    expect(body).toEqual({ attached: false, readiness_score: 88, gap_count: 1 });
  });

  it("treats an exact replay as a no-op", async () => {
    // Both clients can fire for the same account: signup-form on the password
    // path and PendingScoreClaim on the next authenticated render.
    const { where } = givenFreshAccount({ readiness_score: 62, scored_at: SAVED_AT });

    const body = (await (await post(scoreBody())).json()) as AttachBody;

    expect(body.attached).toBe(false);
    expect(where("accounts", "update")).toEqual([]);
  });

  it("accepts a newer questionnaire result over an older one", async () => {
    const { where } = givenFreshAccount({ readiness_score: 41, scored_at: OLDER_SAVED_AT });

    const response = await post(scoreBody({ readiness_score: 77, saved_at: NEWER_SAVED_AT }));

    expect(response.status).toBe(200);
    expect(updatePayload(where)).toMatchObject({
      readiness_score: 77,
      scored_at: NEWER_SAVED_AT,
    });
  });

  it("attaches when the account carries a gap list but no scored_at stamp", async () => {
    // Rows written before `scored_at` existed have no stamp; the guard must
    // not read "no stamp" as "newer than anything".
    const { where } = givenFreshAccount({ readiness_score: 41, scored_at: null });

    const response = await post(scoreBody());

    expect(response.status).toBe(200);
    expect(where("accounts", "update")).toHaveLength(1);
  });
});

// ===========================================================================
// Seeding the home state
// ===========================================================================

describe("POST /api/account/score — seeding home_state", () => {
  it("seeds the home state from the questionnaire when the account has none", async () => {
    const { where } = givenFreshAccount({ home_state: "" });

    await post(scoreBody({ state: "ny" }));

    expect(updatePayload(where).home_state).toBe("NY");
  });

  it("never overwrites a home state the owner already set", async () => {
    // /staff import seeds it from the roster, which is the better source.
    const { where } = givenFreshAccount({ home_state: "CA" });

    await post(scoreBody({ state: "TX" }));

    expect(updatePayload(where)).not.toHaveProperty("home_state");
  });

  it("stores no home state for the OTHER sentinel instead of a truncated code", async () => {
    // /score offers "Another state" as the value "OTHER" (see
    // src/app/score/questions.ts). Truncating it to two characters writes "OT"
    // — a state that does not exist — and /dashboard and the audit file both
    // render `home_state` verbatim.
    const { where } = givenFreshAccount({ home_state: "" });

    await post(scoreBody({ state: "OTHER" }));

    expect(updatePayload(where)).not.toHaveProperty("home_state");
  });
});

// ===========================================================================
// Infrastructure failures and abuse
// ===========================================================================

describe("POST /api/account/score — failures and abuse", () => {
  it("returns 500 without claiming the score was attached when the write fails", async () => {
    // PendingScoreClaim keeps the local record on a non-2xx and retries.
    const harness = makeDb({ data: null, error: { message: "deadlock detected" } });
    givenAccount(harness.db);

    const response = await post(scoreBody());
    const body = (await response.json()) as AttachBody;

    expect(response.status).toBe(500);
    expect(body.attached).toBeUndefined();
  });

  it("does not leak the database error text to the caller", async () => {
    const harness = makeDb({
      data: null,
      error: { message: 'relation "accounts" does not exist at host db.internal' },
    });
    givenAccount(harness.db);

    const text = await (await post(scoreBody())).text();

    expect(text).not.toContain("db.internal");
    expect(text).not.toContain("relation");
  });

  it("throttles a burst from one IP before it becomes a write amplifier", async () => {
    const ip = "198.51.100.42";
    givenFreshAccount();

    for (let attempt = 0; attempt < 10; attempt += 1) {
      expect((await post(scoreBody(), ip)).status).toBe(200);
    }

    const throttled = await post(scoreBody(), ip);
    expect(throttled.status).toBe(429);
  });

  it("resolves no account and writes nothing once the limit is hit", async () => {
    const ip = "198.51.100.43";
    const { calls } = givenFreshAccount();

    for (let attempt = 0; attempt < 10; attempt += 1) await post(scoreBody(), ip);
    resolveAccount.mockClear();
    calls.length = 0;

    const throttled = await post(scoreBody(), ip);

    expect(throttled.status).toBe(429);
    expect(resolveAccount).not.toHaveBeenCalled();
    expect(calls).toEqual([]);
  });
});
