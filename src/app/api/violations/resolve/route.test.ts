// Unit tests for POST /api/violations/resolve — behavior b-09.
//
// b-09: "the owner works an open violation finding and completes the fix; the
// finding is marked resolved and `violation_resolved` fires." Two acceptance
// criteria hang off this handler:
//
//   1. "Resolving a finding updates its status and removes it from the open
//      list without deleting the audit record." The whole product promise is
//      that an investigator can be shown what was found and when it was fixed.
//      A DELETE here destroys the most valuable evidence TipGuard produces, and
//      it would do it silently — the open list looks identical either way.
//   2. "violation_resolved fires with rule_class and days_open." The event is
//      fired client-side by src/app/violations/violations-client.tsx from THIS
//      response, so the response shape is the h-05 metric. A finding that can
//      be resolved twice fires the event twice and inflates it.
//
// The id is supplied in the request body, which makes tenant scoping the other
// half of the job: `.eq("account_id", ...)` on both the read and the write, and
// a refusal that cannot be used to probe whether another restaurant's id
// exists.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST } from "./route";
import { trackViolationResolved } from "@/lib/events";
import type { AccountRow, ViolationRow } from "@/lib/types";

const { resolveAccount, track } = vi.hoisted(() => ({
  resolveAccount: vi.fn(),
  track: vi.fn(),
}));

vi.mock("@/lib/analytics", () => ({ track }));
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

const ACCOUNT: AccountRow = {
  id: "22222222-2222-4222-8222-222222222222",
  user_id: "11111111-1111-4111-8111-111111111111",
  restaurant_name: "The Tipped Spoon",
  home_state: "TX",
  plan: "free",
  stripe_customer_id: null,
  current_period_end: null,
  readiness_score: 62,
  gap_list: null,
  scored_at: null,
  last_scan_at: "2026-02-01T00:00:00.000Z",
  created_at: "2026-01-01T00:00:00.000Z",
};

const OTHER_ACCOUNT_ID = "99999999-9999-4999-8999-999999999999";
const VIOLATION_ID = "dddddddd-0000-4000-8000-000000000001";
/** Belongs to another restaurant. Real row, out of this caller's scope. */
const FOREIGN_VIOLATION_ID = "eeeeeeee-0000-4000-8000-000000000001";
const MISSING_VIOLATION_ID = "ffffffff-0000-4000-8000-000000000001";

const MS_PER_DAY = 86_400_000;

/** Only the columns the route SELECTs. */
type ViolationSlice = Pick<ViolationRow, "id" | "status" | "rule_class" | "detected_at">;

function makeViolation(overrides: Partial<ViolationSlice> = {}): ViolationSlice {
  return {
    id: VIOLATION_ID,
    status: "open",
    rule_class: "overtime_base",
    detected_at: new Date(Date.now() - 9.5 * MS_PER_DAY).toISOString(),
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
  columns: string;
  filters: [string, unknown][];
  payload: unknown;
}

interface DbScenario {
  /** The scoped lookup. `undefined` data means "no row in your scope". */
  lookup?: QueryResult;
  /** The compare-and-swap write. Zero rows means somebody else got there. */
  update?: QueryResult;
}

/**
 * Supabase query builders are thenables, not promises — the route awaits the
 * builder itself after the last filter or terminal method. The stub mirrors
 * that so `.select().eq().eq().maybeSingle()` and `.update().eq().select()`
 * both resolve.
 */
function makeDb(scenario: DbScenario = {}) {
  const calls: DbCall[] = [];

  const resultFor = (call: DbCall): QueryResult => {
    if (call.op === "update") {
      return scenario.update ?? { data: [{ id: VIOLATION_ID }], error: null };
    }
    return scenario.lookup ?? { data: makeViolation(), error: null };
  };

  const makeBuilder = (table: string) => {
    const call: DbCall = {
      table,
      op: "select",
      columns: "",
      filters: [],
      payload: undefined,
    };
    const settle = () =>
      Promise.resolve().then(() => {
        calls.push(call);
        return resultFor(call);
      });

    const builder = {
      select: (columns?: string) => {
        call.columns = columns ?? call.columns;
        return builder;
      },
      update: (payload: unknown) => {
        call.op = "update";
        call.payload = payload;
        return builder;
      },
      insert: (payload: unknown) => {
        call.op = "insert";
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
      maybeSingle: () =>
        settle().then((result) => ({
          data: Array.isArray(result.data) ? (result.data[0] ?? null) : result.data,
          error: result.error,
        })),
      single: () =>
        settle().then((result) => ({
          data: Array.isArray(result.data) ? (result.data[0] ?? null) : result.data,
          error: result.error,
        })),
      then: <T>(
        onFulfilled?: (value: QueryResult) => T,
        onRejected?: (reason: unknown) => T
      ) => settle().then(onFulfilled, onRejected),
    };
    return builder;
  };

  return {
    db: { from: (table: string) => makeBuilder(table) },
    calls,
    where: (op: DbCall["op"]) => calls.filter((call) => call.op === op),
  };
}

function givenAccount(db: unknown) {
  resolveAccount.mockResolvedValue({
    ok: true,
    ctx: {
      userId: ACCOUNT.user_id,
      email: "owner@restaurant.test",
      account: ACCOUNT,
      db,
    },
  });
}

/** The common arrangement: one open finding owned by the caller. */
function givenOpenFinding(overrides: Partial<ViolationSlice> = {}) {
  const harness = makeDb({ lookup: { data: makeViolation(overrides), error: null } });
  givenAccount(harness.db);
  return harness;
}

// ---------------------------------------------------------------------------
// Request helpers
// ---------------------------------------------------------------------------

function makeRequest(body: unknown): Request {
  return new Request("https://request-host.test/api/violations/resolve", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

function post(body: unknown) {
  return POST(makeRequest(body));
}

type ResolveBody = {
  violation_id?: string;
  rule_class?: string;
  days_open?: number;
  resolved_at?: string;
  error?: string;
};

beforeEach(() => {
  vi.clearAllMocks();
  // The route logs infrastructure failures by design; keep output readable.
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ===========================================================================
// b-09 criterion: "Resolving a finding updates its status and removes it from
// the open list without deleting the audit record"
// ===========================================================================

describe("POST /api/violations/resolve — the finding is marked, never deleted", () => {
  it("Resolving a finding updates its status and removes it from the open list without deleting the audit record", async () => {
    const { where } = givenOpenFinding();

    const response = await post({ violation_id: VIOLATION_ID });

    expect(response.status).toBe(200);
    // Marked resolved — which is what drops it out of the open tab, since
    // /violations partitions on `status`.
    expect(where("update")[0].payload).toMatchObject({ status: "resolved" });
    // And the row itself is untouched.
    expect(where("delete")).toEqual([]);
  });

  it("issues no DELETE on any path through the handler", async () => {
    for (const scenario of [
      givenOpenFinding(),
      givenOpenFinding({ status: "resolved" }),
      (() => {
        const harness = makeDb({ lookup: { data: null, error: null } });
        givenAccount(harness.db);
        return harness;
      })(),
    ]) {
      await post({ violation_id: VIOLATION_ID });
      expect(scenario.where("delete")).toEqual([]);
    }
  });

  it("writes only status and resolved_at, leaving the evidence columns intact", async () => {
    // `detail`, `detected_at`, `estimated_exposure_usd`, `severity` are what
    // the audit file prints. Blanking any of them turns a resolved finding into
    // an empty row.
    const { where } = givenOpenFinding();

    await post({ violation_id: VIOLATION_ID });

    expect(Object.keys(where("update")[0].payload as object).sort()).toEqual([
      "resolved_at",
      "status",
    ]);
  });

  it("stamps resolved_at with the moment of the fix", async () => {
    const { where } = givenOpenFinding();
    const before = Date.now();

    const body = (await (await post({ violation_id: VIOLATION_ID })).json()) as ResolveBody;

    const stamped = (where("update")[0].payload as { resolved_at: string }).resolved_at;
    expect(Date.parse(stamped)).toBeGreaterThanOrEqual(before);
    expect(Date.parse(stamped)).toBeLessThanOrEqual(Date.now());
    // The client and the row must agree on when it was closed.
    expect(body.resolved_at).toBe(stamped);
  });

  it("reads the status before writing so the transition can be checked", async () => {
    const { where } = givenOpenFinding();

    await post({ violation_id: VIOLATION_ID });

    expect(where("select")[0].columns).toContain("status");
    expect(where("select")[0].columns).toContain("detected_at");
  });
});

// ===========================================================================
// b-09 criterion: "violation_resolved fires with rule_class and days_open"
//
// The event fires client-side from this response (violations-client.tsx), so
// the route is authoritative for both properties.
// ===========================================================================

describe("violation_resolved — the h-05 signal", () => {
  it("violation_resolved fires with rule_class and days_open", () => {
    trackViolationResolved({ rule_class: "overtime_base", days_open: 9 });

    expect(track).toHaveBeenCalledTimes(1);
    const [event, properties] = track.mock.calls[0];
    expect(event).toBe("violation_resolved");
    expect(properties).toMatchObject({
      rule_class: "overtime_base",
      days_open: 9,
      funnel_stage: "activate",
    });
  });

  it("returns the rule_class and days_open the event needs", async () => {
    const { db } = makeDb({
      lookup: {
        data: makeViolation({
          rule_class: "ineligible_tip_pool",
          detected_at: new Date(Date.now() - 9.5 * MS_PER_DAY).toISOString(),
        }),
        error: null,
      },
    });
    givenAccount(db);

    const body = (await (await post({ violation_id: VIOLATION_ID })).json()) as ResolveBody;

    expect(body.rule_class).toBe("ineligible_tip_pool");
    expect(body.days_open).toBe(9);
  });

  it("reports the rule_class stored on the row, not one supplied in the body", async () => {
    givenOpenFinding({ rule_class: "missing_notice" });

    const body = (await (
      await post({ violation_id: VIOLATION_ID, rule_class: "subminimum_shortfall" })
    ).json()) as ResolveBody;

    expect(body.rule_class).toBe("missing_notice");
  });

  it("reports zero days for a finding fixed the same day", async () => {
    // A same-day fix is the best outcome the product can produce; rounding it
    // up to 1 would understate how fast the loop closes.
    givenOpenFinding({ detected_at: new Date(Date.now() - 3 * 3_600_000).toISOString() });

    const body = (await (await post({ violation_id: VIOLATION_ID })).json()) as ResolveBody;

    expect(body.days_open).toBe(0);
  });

  it("never reports a negative days_open for a clock-skewed detected_at", async () => {
    givenOpenFinding({ detected_at: new Date(Date.now() + 2 * MS_PER_DAY).toISOString() });

    const body = (await (await post({ violation_id: VIOLATION_ID })).json()) as ResolveBody;

    expect(body.days_open).toBe(0);
  });

  it("always returns days_open as a finite number", async () => {
    // NaN serializes to null, and a null on a required event property drops the
    // whole row from the h-05 aggregate.
    givenOpenFinding({ detected_at: "not-a-timestamp" });

    const body = (await (await post({ violation_id: VIOLATION_ID })).json()) as ResolveBody;

    expect(Number.isFinite(body.days_open)).toBe(true);
  });
});

// ===========================================================================
// Tenant scoping — the id comes from the request body
// ===========================================================================

describe("POST /api/violations/resolve — tenant scoping", () => {
  it("scopes the lookup by both the requested id and the caller's account", async () => {
    const { where } = givenOpenFinding();

    await post({ violation_id: VIOLATION_ID });

    expect(where("select")[0].filters).toContainEqual(["id", VIOLATION_ID]);
    expect(where("select")[0].filters).toContainEqual(["account_id", ACCOUNT.id]);
  });

  it("scopes the write by account_id as well, not by id alone", async () => {
    // RLS is bypassed by the service-role client, so this filter is the only
    // thing standing between a body-supplied id and another tenant's row.
    const { where } = givenOpenFinding();

    await post({ violation_id: VIOLATION_ID });

    expect(where("update")[0].filters).toContainEqual(["account_id", ACCOUNT.id]);
    expect(where("update")[0].filters).toContainEqual(["id", VIOLATION_ID]);
  });

  it("refuses another restaurant's finding without writing anything", async () => {
    // The row exists, but not in this caller's scope, so the scoped lookup
    // returns nothing.
    const harness = makeDb({ lookup: { data: null, error: null } });
    givenAccount(harness.db);

    const response = await post({ violation_id: FOREIGN_VIOLATION_ID });

    expect(response.status).toBe(404);
    expect(harness.where("update")).toEqual([]);
    expect(harness.where("delete")).toEqual([]);
  });

  it("does not confirm whether an out-of-scope finding exists", async () => {
    // Identical status AND identical body for "not yours" and "never existed",
    // otherwise the endpoint is an existence oracle for other restaurants' ids.
    const foreignHarness = makeDb({ lookup: { data: null, error: null } });
    givenAccount(foreignHarness.db);
    const foreign = await post({ violation_id: FOREIGN_VIOLATION_ID });
    const foreignText = await foreign.text();

    const missingHarness = makeDb({ lookup: { data: null, error: null } });
    givenAccount(missingHarness.db);
    const missing = await post({ violation_id: MISSING_VIOLATION_ID });
    const missingText = await missing.text();

    expect(foreign.status).toBe(missing.status);
    expect(foreignText).toBe(missingText);
  });

  it("never echoes another tenant's identifiers", async () => {
    const harness = makeDb({ lookup: { data: null, error: null } });
    givenAccount(harness.db);

    const text = await (
      await post({ violation_id: FOREIGN_VIOLATION_ID, account_id: OTHER_ACCOUNT_ID })
    ).text();

    expect(text).not.toContain(OTHER_ACCOUNT_ID);
    expect(text).not.toContain(FOREIGN_VIOLATION_ID);
  });

  it("ignores an account_id supplied in the request body", async () => {
    const { where } = givenOpenFinding();

    await post({ violation_id: VIOLATION_ID, account_id: OTHER_ACCOUNT_ID });

    for (const call of where("select").concat(where("update"))) {
      expect(call.filters).toContainEqual(["account_id", ACCOUNT.id]);
      expect(call.filters).not.toContainEqual(["account_id", OTHER_ACCOUNT_ID]);
    }
  });
});

// ===========================================================================
// The open -> resolved transition happens at most once
// ===========================================================================

describe("POST /api/violations/resolve — resolving twice", () => {
  it("refuses an already-resolved finding", async () => {
    givenOpenFinding({ status: "resolved" });

    const response = await post({ violation_id: VIOLATION_ID });

    expect(response.status).toBe(409);
  });

  it("writes nothing when the finding is already resolved", async () => {
    // A second write would move `resolved_at` forward and rewrite history.
    const { where } = givenOpenFinding({ status: "resolved" });

    await post({ violation_id: VIOLATION_ID });

    expect(where("update")).toEqual([]);
  });

  it("returns a non-ok response so the client cannot fire violation_resolved twice", async () => {
    // violations-client.tsx throws on `!response.ok` BEFORE tracking. A 200
    // here would double-count the h-05 numerator for one real fix.
    givenOpenFinding({ status: "resolved" });

    const response = await post({ violation_id: VIOLATION_ID });
    const body = (await response.json()) as ResolveBody;

    expect(response.ok).toBe(false);
    expect(body.days_open).toBeUndefined();
    expect(body.error).toBeTruthy();
  });

  it("guards the write on the row still being open", async () => {
    // The status check is a read, and the write is a separate statement. Two
    // clicks in flight at once both read 'open' and both write unless the
    // UPDATE itself carries the precondition.
    const { where } = givenOpenFinding();

    await post({ violation_id: VIOLATION_ID });

    expect(where("update")[0].filters).toContainEqual(["status", "open"]);
  });

  it("refuses the loser of a concurrent double-submit instead of reporting success", async () => {
    // The guarded UPDATE matches no row because the other request already
    // flipped it. Returning 200 would fire violation_resolved a second time.
    const harness = makeDb({
      lookup: { data: makeViolation(), error: null },
      update: { data: [], error: null },
    });
    givenAccount(harness.db);

    const response = await post({ violation_id: VIOLATION_ID });

    expect(response.status).toBe(409);
    expect(response.ok).toBe(false);
  });
});

// ===========================================================================
// Input validation
// ===========================================================================

describe("POST /api/violations/resolve — input validation", () => {
  it("rejects an id that is not a uuid before any query runs", async () => {
    const harness = makeDb();
    givenAccount(harness.db);

    for (const violation_id of ["../../etc/passwd", "1", "' OR 1=1 --", ""]) {
      const response = await post({ violation_id });

      expect(response.status).toBe(400);
      expect(harness.calls).toEqual([]);
    }
  });

  it("rejects a missing, null, or non-string violation_id", async () => {
    const harness = makeDb();
    givenAccount(harness.db);

    for (const body of [{}, { violation_id: null }, { violation_id: 7 }, { violation_id: [VIOLATION_ID] }]) {
      expect((await post(body)).status).toBe(400);
    }
    expect(harness.calls).toEqual([]);
  });

  it("rejects a body that is not valid JSON", async () => {
    const harness = makeDb();
    givenAccount(harness.db);

    expect((await post("{not json")).status).toBe(400);
    expect(harness.calls).toEqual([]);
  });
});

// ===========================================================================
// The auth boundary
// ===========================================================================

describe("POST /api/violations/resolve — the auth boundary", () => {
  it("returns 401 when there is no verified session", async () => {
    resolveAccount.mockResolvedValue({ ok: false, reason: "unauthenticated" });

    expect((await post({ violation_id: VIOLATION_ID })).status).toBe(401);
  });

  it("returns 404 when the caller has no account row", async () => {
    resolveAccount.mockResolvedValue({ ok: false, reason: "no_account" });

    expect((await post({ violation_id: VIOLATION_ID })).status).toBe(404);
  });

  it("returns 503 when the database or service-role key is unavailable", async () => {
    resolveAccount.mockResolvedValue({ ok: false, reason: "unavailable" });

    expect((await post({ violation_id: VIOLATION_ID })).status).toBe(503);
  });

  it("never returns a resolution payload on a failed resolution", async () => {
    for (const reason of ["unauthenticated", "no_account", "unavailable"] as const) {
      resolveAccount.mockResolvedValue({ ok: false, reason });

      const response = await post({ violation_id: VIOLATION_ID });
      const body = (await response.json()) as ResolveBody;

      expect(response.ok).toBe(false);
      expect(body.resolved_at).toBeUndefined();
    }
  });

  it("does not provision an account row for a resolve", async () => {
    // Nothing to resolve without an existing account; creating one here would
    // turn a 404 into an empty-tenant 404 one query later.
    givenOpenFinding();

    await post({ violation_id: VIOLATION_ID });

    expect(resolveAccount).toHaveBeenCalledWith();
  });
});

// ===========================================================================
// Infrastructure failures
// ===========================================================================

describe("POST /api/violations/resolve — infrastructure failures fail closed", () => {
  it("returns 500 without writing when the lookup errors", async () => {
    const harness = makeDb({
      lookup: { data: null, error: { message: "connection refused" } },
    });
    givenAccount(harness.db);

    const response = await post({ violation_id: VIOLATION_ID });

    expect(response.status).toBe(500);
    expect(harness.where("update")).toEqual([]);
  });

  it("does not mistake a lookup error for a missing finding", async () => {
    // A 404 would tell the owner the finding is gone and stop the retry; the
    // finding is fine and the database is not.
    const harness = makeDb({
      lookup: { data: null, error: { message: "connection refused" } },
    });
    givenAccount(harness.db);

    expect((await post({ violation_id: VIOLATION_ID })).status).not.toBe(404);
  });

  it("returns 500 when the write fails", async () => {
    const harness = makeDb({
      lookup: { data: makeViolation(), error: null },
      update: { data: null, error: { message: "deadlock detected" } },
    });
    givenAccount(harness.db);

    const response = await post({ violation_id: VIOLATION_ID });
    const body = (await response.json()) as ResolveBody;

    expect(response.status).toBe(500);
    expect(body.days_open).toBeUndefined();
  });

  it("does not leak the database error text to the caller", async () => {
    const harness = makeDb({
      lookup: { data: null, error: { message: 'relation "violations" missing at db.internal' } },
    });
    givenAccount(harness.db);

    const text = await (await post({ violation_id: VIOLATION_ID })).text();

    expect(text).not.toContain("db.internal");
    expect(text).not.toContain("relation");
  });
});
