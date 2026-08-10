// Unit tests for POST /api/staff/import — behavior b-04.
//
// b-04: "the owner uploads a roster CSV of tipped staff; each valid row is
// created as an employee record; invalid rows are reported inline WITHOUT
// ABORTING THE IMPORT; roster_imported fires with row counts."
//
// The load-bearing property of this handler is partial failure. A restaurant
// roster is exported from Gusto or Toast and hand-edited; some rows are always
// broken. If one broken row can take the other thirty-nine down with it, the
// owner is told "nothing was written" and the funnel stops at the first step
// h-05 measures. So every test here asks the same question from a different
// angle: does row N surviving depend on row M?
//
// Parsing is NOT retested here — src/lib/roster-csv.test.ts owns the CSV
// contract. This file tests what the ROUTE does with rows that reached it:
// per-row validation, per-row insertion, the counts it reports, and the fact
// that `account_id` is stamped from the session and can never come off the
// wire.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST } from "./route";
import { trackRosterImported } from "@/lib/events";
import type { AccountRow, EmployeeRow } from "@/lib/types";

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
  last_scan_at: null,
  created_at: "2026-01-01T00:00:00.000Z",
};

const OTHER_ACCOUNT_ID = "99999999-9999-4999-8999-999999999999";

/** The documented batch ceiling. Exceeding it must not import a silent prefix. */
const MAX_ROWS = 500;

/** One well-formed roster row, in the camelCase shape parseRosterCsv emits. */
function row(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    name: "Marisol Vega",
    email: "marisol.vega@northbay.test",
    role: "Server",
    hireDate: "2024-03-11",
    hourlyRate: 2.13,
    state: "TX",
    ...overrides,
  };
}

/** `count` distinct well-formed rows. */
function rows(count: number): Record<string, unknown>[] {
  return Array.from({ length: count }, (_, index) =>
    row({ name: `Employee ${index + 1}`, email: `staff${index + 1}@northbay.test` })
  );
}

// ---------------------------------------------------------------------------
// Recording stand-in for the service-role PostgREST client
//
// It models the one database guarantee this route leans on: employees are
// unique per (account_id, email), so an upsert of an email already on file
// returns the SAME row id rather than creating a second employee.
// ---------------------------------------------------------------------------

interface DbCall {
  table: string;
  op: "select" | "insert" | "upsert" | "update" | "delete";
  columns: string;
  filters: [string, unknown][];
  payload: Record<string, unknown>;
  options: unknown;
}

interface DbScenario {
  /** Emails whose write comes back as a Postgres error. */
  failEmails?: string[];
  /** Emails whose write REJECTS outright — a dropped connection mid-batch. */
  rejectEmails?: string[];
  /** Result of the `accounts.home_state` seed. */
  accountsUpdate?: { data: unknown; error: unknown };
  /** When true the home_state seed rejects instead of returning an error. */
  rejectAccountsUpdate?: boolean;
}

const DB_ERROR = {
  message:
    'duplicate key value violates unique constraint "employees_account_id_email_key" at host db.internal',
};

function makeDb(scenario: DbScenario = {}) {
  const calls: DbCall[] = [];
  /** email -> employee id. Persisted across requests, like the real table. */
  const idByEmail = new Map<string, string>();

  const employeeFor = (payload: Record<string, unknown>): EmployeeRow => {
    const email = String(payload.email);
    if (!idByEmail.has(email)) {
      idByEmail.set(email, `emp-${idByEmail.size + 1}`);
    }
    return {
      id: idByEmail.get(email) as string,
      account_id: String(payload.account_id),
      name: String(payload.name),
      email,
      role: String(payload.role),
      hire_date: String(payload.hire_date),
      hourly_rate: Number(payload.hourly_rate),
      state: String(payload.state),
      in_tip_pool: true,
      created_at: "2026-02-01T00:00:00.000Z",
    };
  };

  const makeBuilder = (table: string) => {
    const call: DbCall = {
      table,
      op: "select",
      columns: "",
      filters: [],
      payload: {},
      options: undefined,
    };

    const settle = () =>
      Promise.resolve().then(() => {
        calls.push(call);
        if (table === "accounts") {
          if (scenario.rejectAccountsUpdate) {
            throw new Error("fetch failed: ECONNRESET");
          }
          return scenario.accountsUpdate ?? { data: null, error: null };
        }
        const email = String(call.payload.email);
        if (scenario.rejectEmails?.includes(email)) {
          throw new Error("fetch failed: ECONNRESET");
        }
        if (scenario.failEmails?.includes(email)) {
          return { data: null, error: DB_ERROR };
        }
        return { data: employeeFor(call.payload), error: null };
      });

    const builder = {
      select: (columns?: string) => {
        call.columns = columns ?? call.columns;
        return builder;
      },
      upsert: (payload: Record<string, unknown>, options?: unknown) => {
        call.op = "upsert";
        call.payload = payload;
        call.options = options;
        return builder;
      },
      insert: (payload: Record<string, unknown>) => {
        call.op = "insert";
        call.payload = payload;
        return builder;
      },
      update: (payload: Record<string, unknown>) => {
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
      single: () => settle(),
      maybeSingle: () => settle(),
      then: <T>(
        onFulfilled?: (value: { data: unknown; error: unknown }) => T,
        onRejected?: (reason: unknown) => T
      ) => settle().then(onFulfilled, onRejected),
    };
    return builder;
  };

  return {
    db: { from: (table: string) => makeBuilder(table) },
    calls,
    writes: () => calls.filter((call) => call.table === "employees"),
    where: (table: string, op: DbCall["op"]) =>
      calls.filter((call) => call.table === table && call.op === op),
  };
}

function givenAccount(db: unknown, overrides: Partial<AccountRow> = {}) {
  const account = { ...ACCOUNT, ...overrides };
  resolveAccount.mockResolvedValue({
    ok: true,
    ctx: { userId: account.user_id, email: "owner@restaurant.test", account, db },
  });
  return account;
}

/** The common arrangement: a signed-in owner and a healthy database. */
function givenOwner(scenario: DbScenario = {}, overrides: Partial<AccountRow> = {}) {
  const harness = makeDb(scenario);
  const account = givenAccount(harness.db, overrides);
  return { ...harness, account };
}

// ---------------------------------------------------------------------------
// Request helpers
// ---------------------------------------------------------------------------

function post(body: unknown) {
  return POST(
    new Request("https://request-host.test/api/staff/import", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: typeof body === "string" ? body : JSON.stringify(body),
    })
  );
}

type ImportBody = {
  employees?: EmployeeRow[];
  imported?: number;
  failed?: number;
  errors?: { row: number; reason: string }[];
  error?: string;
};

async function importRows(value: unknown[]): Promise<ImportBody> {
  return (await (await post({ rows: value })).json()) as ImportBody;
}

beforeEach(() => {
  vi.clearAllMocks();
  // The route logs per-row database failures by design; keep output readable.
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ===========================================================================
// b-04 criterion: "A valid CSV creates one employee row per record, scoped to
// the owner's restaurant by RLS"
// ===========================================================================

describe("POST /api/staff/import — one employee row per valid record", () => {
  it("A valid CSV creates one employee row per record, scoped to the owner's restaurant by RLS", async () => {
    const { writes } = givenOwner();

    const body = await importRows(rows(3));

    expect(body.imported).toBe(3);
    expect(body.employees).toHaveLength(3);
    expect(writes()).toHaveLength(3);
    // The service-role client bypasses RLS, so the stamped account_id is the
    // only thing that files these employees under the right restaurant.
    for (const call of writes()) {
      expect(call.payload.account_id).toBe(ACCOUNT.id);
    }
    expect(new Set(body.employees?.map((employee) => employee.id)).size).toBe(3);
  });

  it("stamps account_id from the session, never from the row", async () => {
    // The rows are assembled in the browser. If a body-supplied account_id
    // could steer the write, any signed-in visitor could plant an employee in
    // another restaurant's roster.
    const { writes } = givenOwner();

    const body = await importRows([
      row({ account_id: OTHER_ACCOUNT_ID }),
      row({ email: "second@northbay.test", account_id: OTHER_ACCOUNT_ID, id: "forged" }),
    ]);

    for (const call of writes()) {
      expect(call.payload.account_id).toBe(ACCOUNT.id);
    }
    expect(JSON.stringify(writes())).not.toContain(OTHER_ACCOUNT_ID);
    expect(JSON.stringify(body)).not.toContain(OTHER_ACCOUNT_ID);
  });

  it("writes only the roster columns, dropping anything else the row carried", async () => {
    // `in_tip_pool` drives the ineligible-tip-pool rule class (b-08) and
    // `created_at` is evidence ordering. Neither may come off the wire.
    const { writes } = givenOwner();

    await importRows([row({ in_tip_pool: false, created_at: "2000-01-01", plan: "shield" })]);

    expect(Object.keys(writes()[0].payload).sort()).toEqual([
      "account_id",
      "email",
      "hire_date",
      "hourly_rate",
      "name",
      "role",
      "state",
    ]);
  });

  it("normalises the email to lower case and the state code to upper case", async () => {
    // The email is the natural key for the (account_id, email) constraint, and
    // the state code selects the rule library the notice is generated from.
    const { writes } = givenOwner();

    await importRows([row({ email: "Marisol.VEGA@NorthBay.test", state: "tx" })]);

    expect(writes()[0].payload.email).toBe("marisol.vega@northbay.test");
    expect(writes()[0].payload.state).toBe("TX");
  });

  it("upserts on (account_id, email) so a corrected re-import updates in place", async () => {
    const harness = givenOwner();

    const first = await importRows([row()]);
    const second = await importRows([row({ role: "Bartender" })]);

    expect(harness.writes().every((call) => call.op === "upsert")).toBe(true);
    expect(harness.writes()[0].options).toMatchObject({ onConflict: "account_id,email" });
    // Same employee, corrected — not a second row for the same person.
    expect(second.employees?.[0].id).toBe(first.employees?.[0].id);
    expect(second.imported).toBe(1);
  });

  it("never deletes and never blind-inserts", async () => {
    // A delete-then-insert would break every notice, signature and violation
    // that references the employee id.
    const { where } = givenOwner();

    await importRows(rows(2));

    expect(where("employees", "delete")).toEqual([]);
    expect(where("employees", "insert")).toEqual([]);
  });
});

// ===========================================================================
// b-04 criterion: "Rows with a missing required field or malformed rate are
// listed as errors and skipped, and valid rows still import"
//
// This is the contract the whole route exists to keep.
// ===========================================================================

describe("POST /api/staff/import — a bad row never aborts the batch", () => {
  it("Rows with a missing required field or malformed rate are listed as errors and skipped, and valid rows still import", async () => {
    const { writes } = givenOwner();

    const body = await importRows([
      row({ name: "Marisol Vega", email: "marisol.vega@northbay.test" }),
      row({ email: "" }), // missing required field
      row({ email: "devon@northbay.test" }),
      row({ email: "alex@northbay.test", hourlyRate: "two dollars" }), // malformed rate
      row({ email: "priya@northbay.test" }),
    ]);

    expect(body.imported).toBe(3);
    expect(body.failed).toBe(2);
    expect(writes()).toHaveLength(3);
    expect(body.employees?.map((employee) => employee.email)).toEqual([
      "marisol.vega@northbay.test",
      "devon@northbay.test",
      "priya@northbay.test",
    ]);
  });

  it("names the row number and the field for every rejected row", async () => {
    // "2 rows failed" is unactionable. The owner has to know which line of
    // their spreadsheet to fix.
    givenOwner();

    const body = await importRows([
      row(),
      row({ email: "devon@northbay.test", hourlyRate: "two dollars" }),
      row({ email: "not-an-email" }),
      row({ email: "priya@northbay.test", state: "Texas" }),
    ]);

    expect(body.errors?.map((failure) => failure.row)).toEqual([2, 3, 4]);
    expect(body.errors?.[0].reason).toMatch(/rate/i);
    expect(body.errors?.[1].reason).toMatch(/email/i);
    expect(body.errors?.[2].reason).toMatch(/state/i);
  });

  it("rejects one row for a bad hire date without touching its neighbours", async () => {
    const { writes } = givenOwner();

    const body = await importRows([
      row({ email: "devon@northbay.test", hireDate: "11/03/2024" }),
      row(),
    ]);

    expect(body.imported).toBe(1);
    expect(body.errors).toEqual([{ row: 1, reason: expect.stringMatching(/hire date/i) }]);
    expect(writes()).toHaveLength(1);
  });

  it("keeps importing after the database rejects one row", async () => {
    const { writes } = givenOwner({ failEmails: ["devon@northbay.test"] });

    const body = await importRows([
      row(),
      row({ email: "devon@northbay.test" }),
      row({ email: "priya@northbay.test" }),
    ]);

    expect(body.imported).toBe(2);
    expect(body.errors?.map((failure) => failure.row)).toEqual([2]);
    // The row after the failure was still attempted.
    expect(writes()).toHaveLength(3);
  });

  it("keeps importing when the connection drops on one row", async () => {
    // A PostgREST call that REJECTS rather than resolving with `.error` is the
    // same failure to the owner — one row is unwritable. Letting it escape the
    // loop turns 39 successful writes into a 500 and a client that reports
    // "nothing was written" over rows that are already on file.
    const { writes } = givenOwner({ rejectEmails: ["devon@northbay.test"] });

    const response = await post({
      rows: [row(), row({ email: "devon@northbay.test" }), row({ email: "priya@northbay.test" })],
    });
    const body = (await response.json()) as ImportBody;

    expect(response.status).toBe(200);
    expect(body.imported).toBe(2);
    expect(body.failed).toBe(1);
    expect(writes()).toHaveLength(3);
  });

  it("imports the surviving rows even when every other row is broken", async () => {
    const { writes } = givenOwner();

    const body = await importRows([
      row({ email: "" }),
      row(),
      row({ hourlyRate: -4 }),
      row({ email: "devon@northbay.test" }),
      row({ role: "" }),
    ]);

    expect(body.imported).toBe(2);
    expect(body.failed).toBe(3);
    expect(writes()).toHaveLength(2);
  });

  it("does not leak the Postgres error text into the row report", async () => {
    // A raw message names the table, the column and the constraint.
    givenOwner({ failEmails: ["marisol.vega@northbay.test"] });

    const text = await (await post({ rows: [row()] })).text();

    expect(text).not.toContain("db.internal");
    expect(text).not.toContain("employees_account_id_email_key");
    expect(text).not.toContain("constraint");
  });

  it("reports a duplicated email inside one upload instead of counting it twice", async () => {
    // Both rows upsert onto the SAME (account_id, email) row, so the second is
    // not a second employee — counting it as imported inflates the h-05
    // denominator and hands the roster table two entries with one id.
    const { writes } = givenOwner();

    const body = await importRows([
      row({ name: "Marisol Vega" }),
      row({ name: "Marisol Vega (day shift)" }),
      row({ email: "devon@northbay.test" }),
    ]);

    expect(body.imported).toBe(2);
    expect(body.failed).toBe(1);
    expect(body.errors?.[0].row).toBe(2);
    expect(body.errors?.[0].reason).toMatch(/duplicate/i);
    expect(writes()).toHaveLength(2);
    expect(new Set(body.employees?.map((employee) => employee.id)).size).toBe(2);
  });

  it("treats a case-different duplicate as the same person", async () => {
    const { writes } = givenOwner();

    const body = await importRows([row(), row({ email: "Marisol.Vega@NorthBay.test" })]);

    expect(body.imported).toBe(1);
    expect(writes()).toHaveLength(1);
  });
});

// ===========================================================================
// b-04 criterion: "roster_imported fires with rows_total, rows_imported, and
// rows_failed"
//
// The event fires client-side from this response (roster-import-card.tsx):
// rows_imported comes straight from `imported`, and rows_failed is `failed`
// plus the rows the parser rejected before the POST. The arithmetic only holds
// if the route accounts for every row it was handed.
// ===========================================================================

describe("roster_imported — the h-05 denominator", () => {
  it("roster_imported fires with rows_total, rows_imported, and rows_failed", async () => {
    const scenarios: { submitted: unknown[]; skippedByParser: number }[] = [
      // Mixed: two rows the parser dropped, one the route rejects.
      { submitted: [row(), row({ email: "devon@northbay.test", hourlyRate: "x" })], skippedByParser: 2 },
      // All valid.
      { submitted: rows(4), skippedByParser: 0 },
      // All invalid.
      { submitted: [row({ email: "" }), row({ state: "Texas" })], skippedByParser: 1 },
    ];

    for (const { submitted, skippedByParser } of scenarios) {
      track.mockClear();
      givenOwner();

      const body = await importRows(submitted);

      // Exactly the computation roster-import-card.tsx performs.
      trackRosterImported({
        rows_total: submitted.length + skippedByParser,
        rows_imported: body.imported as number,
        rows_failed: (body.failed as number) + skippedByParser,
      });

      expect(track).toHaveBeenCalledTimes(1);
      const [event, properties] = track.mock.calls[0] as [string, Record<string, number>];
      expect(event).toBe("roster_imported");
      expect(properties).toMatchObject({
        rows_total: submitted.length + skippedByParser,
        rows_imported: body.imported,
        rows_failed: (body.failed as number) + skippedByParser,
      });
      // The h-05 arithmetic: every row is imported or failed, never neither
      // and never both.
      expect(properties.rows_imported + properties.rows_failed).toBe(properties.rows_total);
    }
  });

  it("accounts for every submitted row exactly once", async () => {
    for (const submitted of [
      rows(5),
      [row({ email: "" }), row(), row({ hourlyRate: 0 })],
      [row(), row()],
      [row({ email: "" })],
    ]) {
      givenOwner({ failEmails: ["staff2@northbay.test"] });

      const body = await importRows(submitted);

      expect((body.imported as number) + (body.failed as number)).toBe(submitted.length);
      expect(body.errors).toHaveLength(body.failed as number);
      expect(body.employees).toHaveLength(body.imported as number);
    }
  });

  it("reports zero imported rather than a partial count when every row fails", async () => {
    givenOwner({ failEmails: ["marisol.vega@northbay.test", "devon@northbay.test"] });

    const body = await importRows([row(), row({ email: "devon@northbay.test" })]);

    expect(body.imported).toBe(0);
    expect(body.failed).toBe(2);
    expect(body.employees).toEqual([]);
  });
});

// ===========================================================================
// Batch bounds — an empty file, a header-only file, and an oversized one
// ===========================================================================

describe("POST /api/staff/import — batch bounds", () => {
  it("rejects an empty batch without touching the database", async () => {
    // An empty CSV and a header-only CSV both parse to zero data rows.
    const { calls } = givenOwner();

    const response = await post({ rows: [] });

    expect(response.status).toBe(400);
    expect(calls).toEqual([]);
  });

  it("rejects a body that is not valid JSON, and rows that are not an array", async () => {
    const { calls } = givenOwner();

    expect((await post("{not json")).status).toBe(400);
    for (const body of [{}, { rows: null }, { rows: "name,email" }, { rows: {} }]) {
      expect((await post(body)).status).toBe(400);
    }
    expect(calls).toEqual([]);
  });

  it("imports a roster at the documented maximum", async () => {
    const { writes } = givenOwner();

    const body = await importRows(rows(MAX_ROWS));

    expect(body.imported).toBe(MAX_ROWS);
    expect(writes()).toHaveLength(MAX_ROWS);
  });

  it("refuses an oversized batch outright rather than importing a silent prefix", async () => {
    // A partial import of the first 500 of 600 rows would leave the owner
    // believing the roster is complete — worse than a refusal they can act on.
    const { calls } = givenOwner();

    const response = await post({ rows: rows(MAX_ROWS + 1) });

    expect(response.status).toBe(400);
    expect(calls).toEqual([]);
  });

  it("does not describe the schema back to the caller", async () => {
    givenOwner();

    const text = await (await post({ rows: rows(MAX_ROWS + 1) })).text();

    expect(JSON.parse(text)).toEqual({ error: "Invalid request" });
    expect(text).not.toContain("too_big");
    expect(text).not.toContain("hourlyRate");
  });
});

// ===========================================================================
// The auth boundary
// ===========================================================================

describe("POST /api/staff/import — the auth boundary", () => {
  it("maps every failed resolution through the shared status map", async () => {
    for (const [reason, status] of [
      ["unauthenticated", 401],
      ["no_account", 404],
      ["unavailable", 503],
    ] as const) {
      resolveAccount.mockResolvedValue({ ok: false, reason });

      expect((await post({ rows: rows(1) })).status).toBe(status);
    }
  });

  it("writes nothing and reports no employees on a failed resolution", async () => {
    for (const reason of ["unauthenticated", "no_account", "unavailable"] as const) {
      const harness = makeDb();
      resolveAccount.mockResolvedValue({ ok: false, reason });

      const response = await post({ rows: rows(2) });
      const body = (await response.json()) as ImportBody;

      expect(response.ok).toBe(false);
      expect(harness.calls).toEqual([]);
      expect(body.employees).toBeUndefined();
      expect(body.imported).toBeUndefined();
    }
  });

  it("provisions the account row so the first import is never blocked", async () => {
    // The roster import is often the first authenticated write after an OAuth
    // signup, when the accounts row does not exist yet.
    givenOwner();

    await importRows(rows(1));

    expect(resolveAccount).toHaveBeenCalledWith({ create: true });
  });
});

// ===========================================================================
// Seeding the account's home state
// ===========================================================================

describe("POST /api/staff/import — seeding home_state", () => {
  it("seeds the home state from the roster when the account has none", async () => {
    // Notice generation resolves its rule library from `home_state`; without a
    // seed the owner's next step has no state to work from.
    const { where } = givenOwner({}, { home_state: "" });

    await importRows([row({ state: "ny" })]);

    expect(where("accounts", "update")).toHaveLength(1);
    expect(where("accounts", "update")[0].payload).toEqual({ home_state: "NY" });
    expect(where("accounts", "update")[0].filters).toContainEqual(["id", ACCOUNT.id]);
  });

  it("never overwrites a home state the owner already set", async () => {
    const { where } = givenOwner({}, { home_state: "CA" });

    await importRows([row({ state: "TX" })]);

    expect(where("accounts", "update")).toEqual([]);
  });

  it("seeds nothing when no row imported", async () => {
    const { where } = givenOwner({}, { home_state: "" });

    await importRows([row({ email: "" })]);

    expect(where("accounts", "update")).toEqual([]);
  });

  it("still reports the imported employees when the seed fails", async () => {
    // The employees are already written. Failing the response over a
    // best-effort column update would tell the owner to re-import rows that
    // are on file.
    const { db } = makeDb({ accountsUpdate: { data: null, error: { message: "deadlock" } } });
    givenAccount(db, { home_state: "" });

    const response = await post({ rows: [row()] });
    const body = (await response.json()) as ImportBody;

    expect(response.status).toBe(200);
    expect(body.imported).toBe(1);
  });

  it("still reports the imported employees when the seed connection drops", async () => {
    const { db } = makeDb({ rejectAccountsUpdate: true });
    givenAccount(db, { home_state: "" });

    const response = await post({ rows: [row()] });
    const body = (await response.json()) as ImportBody;

    expect(response.status).toBe(200);
    expect(body.imported).toBe(1);
  });
});
