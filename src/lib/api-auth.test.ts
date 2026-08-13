// Unit tests for the shared API-route identity resolver.
//
// `resolveAccount` is the authorization preamble for TEN authenticated route
// handlers (account/score, audit-file, checkout, feedback, notices,
// notices/generate, notices/send, staff, staff/import, violations/resolve,
// violations/scan). A defect here is not a bug in one route — it is an auth
// bypass across the whole API surface. The two invariants these tests exist to
// protect:
//
//   1. Identity is derived ONLY from `supabase.auth.getUser()`, which verifies
//      the session cookie against the Supabase auth server. Never from the
//      request body, a header, or a query parameter.
//   2. The service-role client — which bypasses RLS on every TipGuard table —
//      is never constructed, and never handed out, without a verified session.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ACCOUNT_COLUMNS,
  resolveAccount,
  statusForReason,
} from "./api-auth";
import type { AccountRow } from "./types";

const { createServerSupabaseClient, createServiceRoleClient } = vi.hoisted(
  () => ({
    createServerSupabaseClient: vi.fn(),
    createServiceRoleClient: vi.fn(),
  })
);

vi.mock("@/lib/supabase-server", () => ({
  createServerSupabaseClient,
  createServiceRoleClient,
}));

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

type QueryResult = { data: unknown; error: unknown };
type ResultSource = QueryResult | (() => QueryResult);

interface DbCalls {
  tables: string[];
  selects: string[];
  eqs: [string, unknown][];
  inserts: unknown[];
}

function resolveSource(source: ResultSource | undefined): QueryResult {
  if (!source) return { data: null, error: null };
  return typeof source === "function" ? source() : source;
}

/** Minimal recording stand-in for the service-role PostgREST client. */
function makeDb(options: { lookup?: ResultSource; insert?: ResultSource } = {}) {
  const calls: DbCalls = { tables: [], selects: [], eqs: [], inserts: [] };

  const makeBuilder = () => {
    let mutating = false;
    const builder = {
      select: (columns: string) => {
        calls.selects.push(columns);
        return builder;
      },
      eq: (column: string, value: unknown) => {
        calls.eqs.push([column, value]);
        return builder;
      },
      insert: (payload: unknown) => {
        mutating = true;
        calls.inserts.push(payload);
        return builder;
      },
      maybeSingle: async () => resolveSource(options.lookup),
      single: async () =>
        resolveSource(mutating ? options.insert : options.lookup),
    };
    return builder;
  };

  const db = {
    from: (table: string) => {
      calls.tables.push(table);
      return makeBuilder();
    },
  };

  return { db, calls };
}

/** Wire an authenticated session with the given user (or none). */
function givenSession(user: { id: string; email?: string } | null) {
  createServerSupabaseClient.mockResolvedValue({
    auth: { getUser: vi.fn(async () => ({ data: { user }, error: null })) },
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  // The module logs failures via console.error by design; keep output readable.
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("resolveAccount — identity is derived from the verified session only", () => {
  it("returns unauthenticated when there is no verified session", async () => {
    givenSession(null);
    await expect(resolveAccount()).resolves.toEqual({
      ok: false,
      reason: "unauthenticated",
    });
  });

  it("never constructs the service-role client without a verified session", async () => {
    // The service-role key bypasses RLS on every table. If it were built
    // before the session check, an unauthenticated request would already hold
    // an all-powerful handle by the time the guard ran.
    givenSession(null);
    await resolveAccount();
    expect(createServiceRoleClient).not.toHaveBeenCalled();
  });

  it("never constructs the service-role client without a session even when create is requested", async () => {
    givenSession(null);
    await expect(resolveAccount({ create: true })).resolves.toEqual({
      ok: false,
      reason: "unauthenticated",
    });
    expect(createServiceRoleClient).not.toHaveBeenCalled();
  });

  it("never touches the database without a verified session", async () => {
    const { db, calls } = makeDb({ lookup: { data: ACCOUNT, error: null } });
    createServiceRoleClient.mockReturnValue(db);
    givenSession(null);
    await resolveAccount({ create: true });
    expect(calls.tables).toEqual([]);
    expect(calls.inserts).toEqual([]);
  });

  it("verifies the session against the auth server on every resolution", async () => {
    const getUser = vi.fn(async () => ({
      data: { user: SESSION_USER },
      error: null,
    }));
    createServerSupabaseClient.mockResolvedValue({ auth: { getUser } });
    const { db } = makeDb({ lookup: { data: ACCOUNT, error: null } });
    createServiceRoleClient.mockReturnValue(db);

    await resolveAccount();

    expect(getUser).toHaveBeenCalledTimes(1);
  });

  it("scopes the account lookup by the user id returned from getUser()", async () => {
    givenSession(SESSION_USER);
    const { db, calls } = makeDb({ lookup: { data: ACCOUNT, error: null } });
    createServiceRoleClient.mockReturnValue(db);

    await resolveAccount();

    expect(calls.tables).toEqual(["accounts"]);
    expect(calls.eqs).toEqual([["user_id", SESSION_USER.id]]);
  });

  it("ignores caller-supplied identity fields and still scopes to the session user", async () => {
    // resolveAccount's only option is `create`. This asserts that smuggling an
    // identity through the options object cannot redirect the lookup.
    givenSession(SESSION_USER);
    const { db, calls } = makeDb({ lookup: { data: ACCOUNT, error: null } });
    createServiceRoleClient.mockReturnValue(db);

    const hostileOptions = {
      create: false,
      userId: "99999999-9999-4999-8999-999999999999",
      user_id: "99999999-9999-4999-8999-999999999999",
      account_id: "deadbeef-0000-4000-8000-000000000000",
    };
    const result = await resolveAccount(hostileOptions);

    expect(calls.eqs).toEqual([["user_id", SESSION_USER.id]]);
    expect(result.ok && result.ctx.userId).toBe(SESSION_USER.id);
    expect(result.ok && result.ctx.account.id).toBe(ACCOUNT.id);
  });

  it("provisions the new account against the session user id, not a supplied one", async () => {
    givenSession(SESSION_USER);
    const { db, calls } = makeDb({
      lookup: { data: null, error: null },
      insert: { data: ACCOUNT, error: null },
    });
    createServiceRoleClient.mockReturnValue(db);

    const hostileOptions = {
      create: true,
      user_id: "99999999-9999-4999-8999-999999999999",
    };
    await resolveAccount(hostileOptions);

    expect(calls.inserts).toHaveLength(1);
    expect(calls.inserts[0]).toEqual({
      user_id: SESSION_USER.id,
      restaurant_name: "",
      home_state: "",
    });
  });
});

describe("resolveAccount — successful resolution", () => {
  beforeEach(() => {
    givenSession(SESSION_USER);
  });

  it("returns the session user id, email, account row, and a service-role client", async () => {
    const { db } = makeDb({ lookup: { data: ACCOUNT, error: null } });
    createServiceRoleClient.mockReturnValue(db);

    const result = await resolveAccount();

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.ctx.userId).toBe(SESSION_USER.id);
    expect(result.ctx.email).toBe(SESSION_USER.email);
    expect(result.ctx.account).toEqual(ACCOUNT);
    expect(result.ctx.db).toBe(db);
  });

  it("reports a null email when the session user has none (OAuth without email scope)", async () => {
    givenSession({ id: SESSION_USER.id });
    const { db } = makeDb({ lookup: { data: ACCOUNT, error: null } });
    createServiceRoleClient.mockReturnValue(db);

    const result = await resolveAccount();
    expect(result.ok && result.ctx.email).toBeNull();
  });

  it("selects the full accounts projection the AccountRow type expects", async () => {
    const { db, calls } = makeDb({ lookup: { data: ACCOUNT, error: null } });
    createServiceRoleClient.mockReturnValue(db);

    await resolveAccount();

    expect(calls.selects).toEqual([ACCOUNT_COLUMNS]);
  });
});

describe("resolveAccount — missing account row", () => {
  beforeEach(() => {
    givenSession(SESSION_USER);
  });

  it("returns no_account when the user has no accounts row and create was not requested", async () => {
    const { db } = makeDb({ lookup: { data: null, error: null } });
    createServiceRoleClient.mockReturnValue(db);

    await expect(resolveAccount()).resolves.toEqual({
      ok: false,
      reason: "no_account",
    });
  });

  it("does not write anything when create was not requested", async () => {
    const { db, calls } = makeDb({ lookup: { data: null, error: null } });
    createServiceRoleClient.mockReturnValue(db);

    await resolveAccount();

    expect(calls.inserts).toEqual([]);
  });

  it("provisions an empty account row when create is requested", async () => {
    const created: AccountRow = { ...ACCOUNT, restaurant_name: "", home_state: "" };
    const { db, calls } = makeDb({
      lookup: { data: null, error: null },
      insert: { data: created, error: null },
    });
    createServiceRoleClient.mockReturnValue(db);

    const result = await resolveAccount({ create: true });

    expect(result.ok && result.ctx.account).toEqual(created);
    // restaurant_name and home_state are NOT NULL in the schema, so the
    // provisioning insert must supply them.
    expect(calls.inserts[0]).toMatchObject({
      restaurant_name: "",
      home_state: "",
    });
  });

  it("does not re-provision when an account already exists", async () => {
    const { db, calls } = makeDb({ lookup: { data: ACCOUNT, error: null } });
    createServiceRoleClient.mockReturnValue(db);

    const result = await resolveAccount({ create: true });

    expect(calls.inserts).toEqual([]);
    expect(result.ok && result.ctx.account).toEqual(ACCOUNT);
  });
});

describe("resolveAccount — failure modes are fail-closed", () => {
  it("returns unavailable when the service-role key is not configured", async () => {
    givenSession(SESSION_USER);
    createServiceRoleClient.mockImplementation(() => {
      throw new Error("SUPABASE_SERVICE_ROLE_KEY is not configured");
    });

    await expect(resolveAccount()).resolves.toEqual({
      ok: false,
      reason: "unavailable",
    });
  });

  it("returns unavailable when the account lookup returns a database error", async () => {
    givenSession(SESSION_USER);
    const { db } = makeDb({
      lookup: { data: null, error: { message: "connection refused" } },
    });
    createServiceRoleClient.mockReturnValue(db);

    await expect(resolveAccount()).resolves.toEqual({
      ok: false,
      reason: "unavailable",
    });
  });

  it("returns unavailable — not no_account — when the lookup errors while create is requested", async () => {
    // Misreading a transient lookup error as "no account" would provision a
    // duplicate row and trip the accounts.user_id UNIQUE constraint.
    givenSession(SESSION_USER);
    const { db, calls } = makeDb({
      lookup: { data: null, error: { message: "timeout" } },
    });
    createServiceRoleClient.mockReturnValue(db);

    await expect(resolveAccount({ create: true })).resolves.toEqual({
      ok: false,
      reason: "unavailable",
    });
    expect(calls.inserts).toEqual([]);
  });

  it("returns unavailable when account provisioning fails", async () => {
    givenSession(SESSION_USER);
    const { db } = makeDb({
      lookup: { data: null, error: null },
      insert: { data: null, error: { message: "duplicate key" } },
    });
    createServiceRoleClient.mockReturnValue(db);

    await expect(resolveAccount({ create: true })).resolves.toEqual({
      ok: false,
      reason: "unavailable",
    });
  });

  it("returns unavailable when the query throws unexpectedly", async () => {
    givenSession(SESSION_USER);
    const { db } = makeDb({
      lookup: () => {
        throw new Error("socket hang up");
      },
    });
    createServiceRoleClient.mockReturnValue(db);

    await expect(resolveAccount()).resolves.toEqual({
      ok: false,
      reason: "unavailable",
    });
  });

  it("returns unavailable rather than throwing when the auth server is unreachable", async () => {
    // Ten route handlers do `const resolved = await resolveAccount()` with no
    // try/catch. A rejected promise escapes as an unhandled route exception
    // and a bare 500, bypassing the documented AccountResolution contract.
    createServerSupabaseClient.mockResolvedValue({
      auth: {
        getUser: vi.fn(async () => {
          throw new Error("fetch failed");
        }),
      },
    });

    await expect(resolveAccount()).resolves.toEqual({
      ok: false,
      reason: "unavailable",
    });
  });

  it("returns unavailable rather than throwing when the server client cannot be built", async () => {
    createServerSupabaseClient.mockImplementation(() => {
      throw new Error("DEMO_MODE is not allowed in production");
    });

    await expect(resolveAccount()).resolves.toEqual({
      ok: false,
      reason: "unavailable",
    });
  });

  it("never hands out a service-role client on any failure path", async () => {
    givenSession(SESSION_USER);
    const scenarios: Array<() => void> = [
      () => {
        createServiceRoleClient.mockImplementation(() => {
          throw new Error("no key");
        });
      },
      () => {
        createServiceRoleClient.mockReturnValue(
          makeDb({ lookup: { data: null, error: { message: "boom" } } }).db
        );
      },
      () => {
        createServiceRoleClient.mockReturnValue(
          makeDb({ lookup: { data: null, error: null } }).db
        );
      },
    ];

    for (const scenario of scenarios) {
      createServiceRoleClient.mockReset();
      scenario();
      const result = await resolveAccount();
      expect(result.ok).toBe(false);
      expect(result).not.toHaveProperty("ctx");
    }
  });
});

describe("ACCOUNT_COLUMNS", () => {
  const columns = ACCOUNT_COLUMNS.split(",").map((c) => c.trim());

  it("lists every column of the accounts table exactly once", () => {
    // Source of truth: supabase/migrations/001_initial.sql.
    expect(columns).toEqual([
      "id",
      "user_id",
      "restaurant_name",
      "home_state",
      "plan",
      "stripe_customer_id",
      "current_period_end",
      "readiness_score",
      "gap_list",
      "scored_at",
      "last_scan_at",
      "created_at",
    ]);
    expect(new Set(columns).size).toBe(columns.length);
  });

  it("satisfies every non-optional field of AccountRow", () => {
    // If a column is dropped from the projection, `as AccountRow` would lie and
    // downstream routes would read undefined at runtime.
    const required: Array<keyof AccountRow> = [
      "id",
      "user_id",
      "restaurant_name",
      "home_state",
      "plan",
      "stripe_customer_id",
      "current_period_end",
      "readiness_score",
      "gap_list",
      "scored_at",
      "last_scan_at",
      "created_at",
    ];
    for (const field of required) {
      expect(columns).toContain(field);
    }
  });

  it("does not use a wildcard projection", () => {
    expect(ACCOUNT_COLUMNS).not.toContain("*");
  });
});

describe("statusForReason", () => {
  it("maps an unverified session to 401 Unauthorized", () => {
    expect(statusForReason("unauthenticated")).toBe(401);
  });

  it("maps a missing account row to 404 Not Found", () => {
    expect(statusForReason("no_account")).toBe(404);
  });

  it("maps an infrastructure failure to 503 Service Unavailable", () => {
    expect(statusForReason("unavailable")).toBe(503);
  });

  it("never maps a failure to a 2xx status", () => {
    for (const reason of ["unauthenticated", "no_account", "unavailable"] as const) {
      expect(statusForReason(reason)).toBeGreaterThanOrEqual(400);
    }
  });
});
