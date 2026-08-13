// Unit tests for POST /api/notices/send — behavior b-06.
//
// This is the most consequential mutation in the product. One request does
// four irreversible things per notice:
//
//   1. mints a signing token (the ONLY authorization material for the public
//      /sign route — see src/app/sign/signing-token.ts),
//   2. persists ONLY its SHA-256 digest,
//   3. flips `notices.status` to 'sent',
//   4. emails the raw token to an employee address.
//
// And it is the measurement source for `notice_sent`, the experiment's
// activation event (h-04 numerator, h-06/h-07 denominator). /notices fires
// `notice_sent` once per entry in this route's `sent[]` — so the shape of that
// array IS the metric. A duplicated entry inflates activation; a missing one
// under-reports it.
//
// The tests are grouped by the b-06 acceptance criteria, preceded by the
// authorization boundary every authenticated route shares.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST } from "./route";
import {
  hashSigningToken,
  isWellFormedSigningToken,
} from "@/app/sign/signing-token";
import type { AccountRow, EmployeeRow, NoticeRow } from "@/lib/types";

const { resolveAccount, sendNoticeSigningEmail } = vi.hoisted(() => ({
  resolveAccount: vi.fn(),
  sendNoticeSigningEmail: vi.fn(),
}));

vi.mock("@/lib/api-auth", () => ({ resolveAccount }));
vi.mock("@/lib/email", () => ({ sendNoticeSigningEmail }));

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

const EMPLOYEE_A: EmployeeRow = {
  id: "aaaaaaaa-0000-4000-8000-000000000001",
  account_id: ACCOUNT.id,
  name: "Dana Server",
  email: "dana@restaurant.test",
  role: "server",
  hire_date: "2025-06-01",
  hourly_rate: 2.13,
  state: "TX",
  in_tip_pool: true,
  created_at: "2026-01-01T00:00:00.000Z",
};

const EMPLOYEE_B: EmployeeRow = {
  ...EMPLOYEE_A,
  id: "aaaaaaaa-0000-4000-8000-000000000002",
  name: "Sam Barback",
  email: "sam@restaurant.test",
};

/** On the roster but with no address on file — cannot be emailed. */
const EMPLOYEE_NO_EMAIL: EmployeeRow = {
  ...EMPLOYEE_A,
  id: "aaaaaaaa-0000-4000-8000-000000000003",
  name: "Pat Newhire",
  email: "",
};

function makeNotice(
  id: string,
  employee: EmployeeRow,
  status: NoticeRow["status"] = "draft"
): NoticeRow {
  return {
    id,
    account_id: ACCOUNT.id,
    employee_id: employee.id,
    state: "TX",
    rule_version: "2026.1",
    cash_wage_paid: 2.13,
    tip_credit_claimed: true,
    notice_text: "Tip credit notice text",
    status,
    sent_at: null,
    created_at: "2026-01-01T00:00:00.000Z",
  };
}

const NOTICE_A_ID = "bbbbbbbb-0000-4000-8000-000000000001";
const NOTICE_B_ID = "bbbbbbbb-0000-4000-8000-000000000002";
const NOTICE_NO_EMAIL_ID = "bbbbbbbb-0000-4000-8000-000000000003";
const FOREIGN_NOTICE_ID = "cccccccc-0000-4000-8000-000000000001";

// ---------------------------------------------------------------------------
// Recording stand-in for the service-role PostgREST client
// ---------------------------------------------------------------------------

type QueryResult = { data: unknown; error: unknown };

interface DbCall {
  table: string;
  op: "select" | "insert" | "update";
  columns: string;
  filters: [string, unknown][];
  payload: unknown;
}

interface DbScenario {
  notices?: QueryResult;
  employees?: QueryResult;
  tokenInsert?: QueryResult;
  noticeUpdate?: QueryResult;
}

const OK: QueryResult = { data: null, error: null };

/**
 * Supabase query builders are thenables, not promises — the route awaits the
 * builder itself after the last filter. The stub mirrors that so every chain
 * shape in the route (`.select().eq().in()`, `.insert()`,
 * `.update().eq().eq()`) resolves without special-casing a terminal method.
 */
function makeDb(scenario: DbScenario = {}) {
  const calls: DbCall[] = [];

  const resultFor = (call: DbCall): QueryResult => {
    if (call.table === "notices" && call.op === "select") {
      return scenario.notices ?? { data: [], error: null };
    }
    if (call.table === "employees") {
      return scenario.employees ?? { data: [], error: null };
    }
    if (call.table === "signing_tokens") return scenario.tokenInsert ?? OK;
    if (call.table === "notices" && call.op === "update") {
      return scenario.noticeUpdate ?? OK;
    }
    throw new Error(`unexpected query: ${call.op} ${call.table}`);
  };

  const makeBuilder = (table: string) => {
    const call: DbCall = {
      table,
      op: "select",
      columns: "",
      filters: [],
      payload: undefined,
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
      eq: (column: string, value: unknown) => {
        call.filters.push([column, value]);
        return builder;
      },
      in: (column: string, value: unknown) => {
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
            return resultFor(call);
          })
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

// ---------------------------------------------------------------------------
// Request helpers
// ---------------------------------------------------------------------------

// The limiter is real, module-scoped, and shared across this file. A distinct
// source IP per request keeps tests independent of one another.
let ipCounter = 0;
function nextIp(): string {
  ipCounter += 1;
  return `203.0.113.${ipCounter}`;
}

function makeRequest(body: unknown, ip: string = nextIp()): Request {
  return new Request("https://request-host.test/api/notices/send", {
    method: "POST",
    headers: { "content-type": "application/json", "x-forwarded-for": ip },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
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

/** The tokenized link this route emailed, per call. */
function emailedTokens(): string[] {
  return sendNoticeSigningEmail.mock.calls.map((call) => {
    const url = new URL(call[3] as string);
    const token = url.searchParams.get("token");
    if (!token) throw new Error(`no token in signing url: ${call[3]}`);
    return token;
  });
}

type SendBody = {
  sent?: { notice_id: string; expires_at?: string }[];
  blocked?: { notice_id: string; reason: string }[];
  delivery_channel?: string;
  error?: string;
};

const originalSiteUrl = process.env.NEXT_PUBLIC_SITE_URL;

beforeEach(() => {
  vi.clearAllMocks();
  sendNoticeSigningEmail.mockResolvedValue(undefined);
  delete process.env.NEXT_PUBLIC_SITE_URL;
  // The route logs infrastructure failures by design; keep output readable.
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
  if (originalSiteUrl === undefined) delete process.env.NEXT_PUBLIC_SITE_URL;
  else process.env.NEXT_PUBLIC_SITE_URL = originalSiteUrl;
});

// ---------------------------------------------------------------------------
// Authorization boundary
// ---------------------------------------------------------------------------

describe("POST /api/notices/send — authorization boundary", () => {
  it("returns 401 when there is no verified session", async () => {
    resolveAccount.mockResolvedValue({ ok: false, reason: "unauthenticated" });
    const response = await POST(makeRequest({ notice_ids: [NOTICE_A_ID] }));
    expect(response.status).toBe(401);
  });

  it("returns 404 when the session has no account row", async () => {
    resolveAccount.mockResolvedValue({ ok: false, reason: "no_account" });
    const response = await POST(makeRequest({ notice_ids: [NOTICE_A_ID] }));
    expect(response.status).toBe(404);
  });

  it("returns 503 when the database or service-role key is unavailable", async () => {
    resolveAccount.mockResolvedValue({ ok: false, reason: "unavailable" });
    const response = await POST(makeRequest({ notice_ids: [NOTICE_A_ID] }));
    expect(response.status).toBe(503);
  });

  it("mints no token and sends no email on any failed resolution", async () => {
    for (const reason of ["unauthenticated", "no_account", "unavailable"] as const) {
      resolveAccount.mockResolvedValue({ ok: false, reason });
      const response = await POST(makeRequest({ notice_ids: [NOTICE_A_ID] }));
      expect(response.status).toBeGreaterThanOrEqual(400);
    }
    expect(sendNoticeSigningEmail).not.toHaveBeenCalled();
  });

  it("never leaks the failure reason as a 2xx", async () => {
    for (const reason of ["unauthenticated", "no_account", "unavailable"] as const) {
      resolveAccount.mockResolvedValue({ ok: false, reason });
      const response = await POST(makeRequest({ notice_ids: [NOTICE_A_ID] }));
      expect(response.ok).toBe(false);
    }
  });
});

describe("POST /api/notices/send — input validation", () => {
  beforeEach(() => {
    const { db } = makeDb();
    givenAccount(db);
  });

  it("rejects a body that is not valid JSON", async () => {
    const response = await POST(makeRequest("{not json"));
    expect(response.status).toBe(400);
  });

  it("rejects a missing notice_ids field", async () => {
    const response = await POST(makeRequest({}));
    expect(response.status).toBe(400);
  });

  it("rejects an empty notice_ids array — a send must name a notice", async () => {
    const response = await POST(makeRequest({ notice_ids: [] }));
    expect(response.status).toBe(400);
  });

  it("rejects ids that are not uuids before any query runs", async () => {
    const { db, calls } = makeDb();
    givenAccount(db);
    const response = await POST(makeRequest({ notice_ids: ["../../etc/passwd"] }));
    expect(response.status).toBe(400);
    expect(calls).toEqual([]);
  });

  it("caps the batch so one request cannot fan out unbounded email", async () => {
    const ids = Array.from(
      { length: 201 },
      (_, index) => `bbbbbbbb-0000-4000-8000-${String(index).padStart(12, "0")}`
    );
    const response = await POST(makeRequest({ notice_ids: ids }));
    expect(response.status).toBe(400);
  });

  it("throttles a burst from one IP before it becomes an outbound-mail relay", async () => {
    const ip = "198.51.100.7";
    const notice = makeNotice(NOTICE_A_ID, EMPLOYEE_A);
    const { db } = makeDb({
      notices: { data: [notice], error: null },
      employees: { data: [EMPLOYEE_A], error: null },
    });
    givenAccount(db);

    for (let attempt = 0; attempt < 20; attempt += 1) {
      const allowed = await POST(makeRequest({ notice_ids: [NOTICE_A_ID] }, ip));
      expect(allowed.status).toBe(200);
    }
    sendNoticeSigningEmail.mockClear();

    const throttled = await POST(makeRequest({ notice_ids: [NOTICE_A_ID] }, ip));
    expect(throttled.status).toBe(429);
    expect(sendNoticeSigningEmail).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Tenant scoping — an owner may only send their own notices
// ---------------------------------------------------------------------------

describe("POST /api/notices/send — notices are scoped to the caller's account", () => {
  it("scopes the notice lookup by account_id and the requested ids", async () => {
    const notice = makeNotice(NOTICE_A_ID, EMPLOYEE_A);
    const { db, where } = makeDb({
      notices: { data: [notice], error: null },
      employees: { data: [EMPLOYEE_A], error: null },
    });
    givenAccount(db);

    await POST(makeRequest({ notice_ids: [NOTICE_A_ID] }));

    const lookup = where("notices", "select")[0];
    expect(lookup.filters).toContainEqual(["account_id", ACCOUNT.id]);
    expect(lookup.filters).toContainEqual(["id", [NOTICE_A_ID]]);
  });

  it("scopes the employee lookup by account_id", async () => {
    const notice = makeNotice(NOTICE_A_ID, EMPLOYEE_A);
    const { db, where } = makeDb({
      notices: { data: [notice], error: null },
      employees: { data: [EMPLOYEE_A], error: null },
    });
    givenAccount(db);

    await POST(makeRequest({ notice_ids: [NOTICE_A_ID] }));

    expect(where("employees", "select")[0].filters).toContainEqual([
      "account_id",
      ACCOUNT.id,
    ]);
  });

  it("refuses another restaurant's notice without minting a token or sending mail", async () => {
    // The row exists in the table but not in this account's scope, so the
    // scoped SELECT returns nothing.
    const { db, where } = makeDb({ notices: { data: [], error: null } });
    givenAccount(db);

    const response = await POST(makeRequest({ notice_ids: [FOREIGN_NOTICE_ID] }));
    const body = (await response.json()) as SendBody;

    expect(response.status).toBe(409);
    expect(body.sent).toEqual([]);
    expect(where("signing_tokens", "insert")).toEqual([]);
    expect(where("notices", "update")).toEqual([]);
    expect(sendNoticeSigningEmail).not.toHaveBeenCalled();
  });

  it("does not confirm whether an out-of-scope notice exists", async () => {
    // Same message for "not yours" and "never existed" — otherwise the blocked
    // reason becomes an existence oracle for other restaurants' notice ids.
    const { db } = makeDb({ notices: { data: [], error: null } });
    givenAccount(db);

    const foreign = (await (
      await POST(makeRequest({ notice_ids: [FOREIGN_NOTICE_ID] }))
    ).json()) as SendBody;
    const missing = (await (
      await POST(makeRequest({ notice_ids: [NOTICE_A_ID] }))
    ).json()) as SendBody;

    expect(foreign.blocked?.[0].reason).toBe(missing.blocked?.[0].reason);
  });
});

// ---------------------------------------------------------------------------
// b-06 criterion: "Sending creates a single-use signing token with an expiry
// and dispatches an email to the employee address"
// ---------------------------------------------------------------------------

describe("POST /api/notices/send — mints a token with an expiry and emails it", () => {
  function givenOneDraft() {
    const notice = makeNotice(NOTICE_A_ID, EMPLOYEE_A);
    const harness = makeDb({
      notices: { data: [notice], error: null },
      employees: { data: [EMPLOYEE_A], error: null },
    });
    givenAccount(harness.db);
    return harness;
  }

  it("creates exactly one signing token per notice, bound to the account and notice", async () => {
    const { where } = givenOneDraft();

    const response = await POST(makeRequest({ notice_ids: [NOTICE_A_ID] }));
    expect(response.status).toBe(200);

    const inserts = where("signing_tokens", "insert");
    expect(inserts).toHaveLength(1);
    expect(inserts[0].payload).toMatchObject({
      account_id: ACCOUNT.id,
      notice_id: NOTICE_A_ID,
    });
  });

  it("gives the token an expiry in the future and reports it to the caller", async () => {
    const { where } = givenOneDraft();

    const before = Date.now();
    const response = await POST(makeRequest({ notice_ids: [NOTICE_A_ID] }));
    const body = (await response.json()) as SendBody;

    const payload = where("signing_tokens", "insert")[0].payload as {
      expires_at: string;
    };
    const expiresAt = Date.parse(payload.expires_at);
    expect(Number.isNaN(expiresAt)).toBe(false);
    expect(expiresAt).toBeGreaterThan(before);
    // The employee may not work again for days; the link has to outlive a
    // couple of shifts but must not be effectively permanent.
    expect(expiresAt).toBeLessThanOrEqual(before + 31 * 24 * 60 * 60 * 1000);
    expect(body.sent?.[0]).toEqual({
      notice_id: NOTICE_A_ID,
      expires_at: payload.expires_at,
    });
  });

  it("persists only the SHA-256 digest — never the raw token", async () => {
    // A database leak must not hand an attacker a set of working signing links.
    const { where } = givenOneDraft();
    await POST(makeRequest({ notice_ids: [NOTICE_A_ID] }));

    const [rawToken] = emailedTokens();
    const payload = where("signing_tokens", "insert")[0].payload as Record<
      string,
      unknown
    >;

    expect(payload.token_hash).toBe(hashSigningToken(rawToken));
    expect(JSON.stringify(payload)).not.toContain(rawToken);
    expect(payload).not.toHaveProperty("token");
  });

  it("mints a token /sign will accept as well-formed", async () => {
    givenOneDraft();
    await POST(makeRequest({ notice_ids: [NOTICE_A_ID] }));

    const [rawToken] = emailedTokens();
    expect(isWellFormedSigningToken(rawToken)).toBe(true);
    // randomBytes(32).toString("base64url")
    expect(rawToken).toHaveLength(43);
  });

  it("mints a distinct token per notice so one link cannot sign another notice", async () => {
    const { db } = makeDb({
      notices: {
        data: [
          makeNotice(NOTICE_A_ID, EMPLOYEE_A),
          makeNotice(NOTICE_B_ID, EMPLOYEE_B),
        ],
        error: null,
      },
      employees: { data: [EMPLOYEE_A, EMPLOYEE_B], error: null },
    });
    givenAccount(db);

    await POST(makeRequest({ notice_ids: [NOTICE_A_ID, NOTICE_B_ID] }));

    const tokens = emailedTokens();
    expect(tokens).toHaveLength(2);
    expect(new Set(tokens).size).toBe(2);
  });

  it("dispatches the email to the employee's address on file with the employer name", async () => {
    givenOneDraft();
    await POST(makeRequest({ notice_ids: [NOTICE_A_ID] }));

    expect(sendNoticeSigningEmail).toHaveBeenCalledTimes(1);
    const [to, employeeName, employerName, signingUrl] =
      sendNoticeSigningEmail.mock.calls[0];
    expect(to).toBe(EMPLOYEE_A.email);
    expect(employeeName).toBe(EMPLOYEE_A.name);
    expect(employerName).toBe(ACCOUNT.restaurant_name);
    expect(new URL(signingUrl as string).pathname).toBe("/sign");
  });

  it("builds the signing link on the configured site origin, not the request Host", async () => {
    // The email carries the raw token. If the link origin came from a
    // caller-controlled Host header, a spoofed request would mail a working
    // token to a link that points at the attacker.
    process.env.NEXT_PUBLIC_SITE_URL = "https://tipguard.app/";
    givenOneDraft();

    await POST(makeRequest({ notice_ids: [NOTICE_A_ID] }));

    const signingUrl = new URL(sendNoticeSigningEmail.mock.calls[0][3] as string);
    expect(signingUrl.origin).toBe("https://tipguard.app");
  });

  it("marks the notice sent, scoped by id AND account_id", async () => {
    const { where } = givenOneDraft();
    await POST(makeRequest({ notice_ids: [NOTICE_A_ID] }));

    const updates = where("notices", "update");
    expect(updates).toHaveLength(1);
    expect(updates[0].payload).toMatchObject({ status: "sent" });
    expect((updates[0].payload as { sent_at: string }).sent_at).toEqual(
      expect.any(String)
    );
    expect(updates[0].filters).toContainEqual(["id", NOTICE_A_ID]);
    expect(updates[0].filters).toContainEqual(["account_id", ACCOUNT.id]);
  });

  it("blocks an employee with no address on file instead of minting a dead token", async () => {
    const { db, where } = makeDb({
      notices: {
        data: [makeNotice(NOTICE_NO_EMAIL_ID, EMPLOYEE_NO_EMAIL)],
        error: null,
      },
      employees: { data: [EMPLOYEE_NO_EMAIL], error: null },
    });
    givenAccount(db);

    const response = await POST(makeRequest({ notice_ids: [NOTICE_NO_EMAIL_ID] }));
    const body = (await response.json()) as SendBody;

    expect(response.status).toBe(409);
    expect(body.blocked?.[0].reason).toMatch(/no email address/i);
    expect(where("signing_tokens", "insert")).toEqual([]);
    expect(where("notices", "update")).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// b-06 criterion: "notice_sent fires once per notice with employee_count and
// delivery channel"
//
// /notices fires the event once per `sent[]` entry, with
// employee_count = sent.length and delivery_channel = the response field. These
// tests pin the payload this route hands the page.
// ---------------------------------------------------------------------------

describe("POST /api/notices/send — the notice_sent measurement payload", () => {
  it("returns exactly one sent entry per dispatched notice", async () => {
    const { db } = makeDb({
      notices: {
        data: [
          makeNotice(NOTICE_A_ID, EMPLOYEE_A),
          makeNotice(NOTICE_B_ID, EMPLOYEE_B),
        ],
        error: null,
      },
      employees: { data: [EMPLOYEE_A, EMPLOYEE_B], error: null },
    });
    givenAccount(db);

    const response = await POST(
      makeRequest({ notice_ids: [NOTICE_A_ID, NOTICE_B_ID] })
    );
    const body = (await response.json()) as SendBody;

    expect(body.sent?.map((entry) => entry.notice_id)).toEqual([
      NOTICE_A_ID,
      NOTICE_B_ID,
    ]);
  });

  it("counts a repeated notice id once — a double-submit must not double-count activation", async () => {
    // The page fires `notice_sent` once per `sent[]` entry with
    // employee_count = sent.length. Two entries for one notice inflate the
    // h-04 numerator AND mail the employee twice.
    const { db, where } = makeDb({
      notices: { data: [makeNotice(NOTICE_A_ID, EMPLOYEE_A)], error: null },
      employees: { data: [EMPLOYEE_A], error: null },
    });
    givenAccount(db);

    const response = await POST(
      makeRequest({ notice_ids: [NOTICE_A_ID, NOTICE_A_ID, NOTICE_A_ID] })
    );
    const body = (await response.json()) as SendBody;

    expect(body.sent).toHaveLength(1);
    expect(where("signing_tokens", "insert")).toHaveLength(1);
    expect(sendNoticeSigningEmail).toHaveBeenCalledTimes(1);
  });

  it("does not repeat a blocked notice id either", async () => {
    const { db } = makeDb({ notices: { data: [], error: null } });
    givenAccount(db);

    const response = await POST(
      makeRequest({ notice_ids: [FOREIGN_NOTICE_ID, FOREIGN_NOTICE_ID] })
    );
    const body = (await response.json()) as SendBody;

    expect(body.blocked).toHaveLength(1);
  });

  it("reports the email channel when delivery succeeded", async () => {
    const { db } = makeDb({
      notices: { data: [makeNotice(NOTICE_A_ID, EMPLOYEE_A)], error: null },
      employees: { data: [EMPLOYEE_A], error: null },
    });
    givenAccount(db);

    const body = (await (
      await POST(makeRequest({ notice_ids: [NOTICE_A_ID] }))
    ).json()) as SendBody;

    expect(body.delivery_channel).toBe("email");
  });

  it("reports link_copy — not email — when every dispatch failed", async () => {
    // The token exists and the notice is 'sent', so the link is real. Claiming
    // "email" would make delivery_channel a lie in the activation event and
    // hide a Resend outage behind a green metric.
    const { db, where } = makeDb({
      notices: { data: [makeNotice(NOTICE_A_ID, EMPLOYEE_A)], error: null },
      employees: { data: [EMPLOYEE_A], error: null },
    });
    givenAccount(db);
    sendNoticeSigningEmail.mockRejectedValue(new Error("resend 503"));

    const response = await POST(makeRequest({ notice_ids: [NOTICE_A_ID] }));
    const body = (await response.json()) as SendBody;

    expect(response.status).toBe(200);
    expect(body.delivery_channel).toBe("link_copy");
    expect(body.sent).toHaveLength(1);
    expect(where("signing_tokens", "insert")).toHaveLength(1);
  });

  it("never lists a blocked notice as sent", async () => {
    const { db } = makeDb({
      notices: {
        data: [
          makeNotice(NOTICE_A_ID, EMPLOYEE_A),
          makeNotice(NOTICE_B_ID, EMPLOYEE_B, "signed"),
        ],
        error: null,
      },
      employees: { data: [EMPLOYEE_A, EMPLOYEE_B], error: null },
    });
    givenAccount(db);

    const body = (await (
      await POST(makeRequest({ notice_ids: [NOTICE_A_ID, NOTICE_B_ID] }))
    ).json()) as SendBody;

    const sentIds = new Set(body.sent?.map((entry) => entry.notice_id));
    for (const block of body.blocked ?? []) {
      expect(sentIds.has(block.notice_id)).toBe(false);
    }
  });
});

// ---------------------------------------------------------------------------
// b-06 criterion: "Re-sending an already-signed notice is blocked and surfaces
// a clear message"
// ---------------------------------------------------------------------------

describe("POST /api/notices/send — a signed notice is immutable", () => {
  function givenSigned() {
    const harness = makeDb({
      notices: {
        data: [makeNotice(NOTICE_A_ID, EMPLOYEE_A, "signed")],
        error: null,
      },
      employees: { data: [EMPLOYEE_A], error: null },
    });
    givenAccount(harness.db);
    return harness;
  }

  it("blocks the re-send with a message that explains why", async () => {
    givenSigned();
    const response = await POST(makeRequest({ notice_ids: [NOTICE_A_ID] }));
    const body = (await response.json()) as SendBody;

    expect(response.status).toBe(409);
    expect(body.sent).toEqual([]);
    expect(body.blocked?.[0].notice_id).toBe(NOTICE_A_ID);
    expect(body.blocked?.[0].reason).toMatch(/already been signed/i);
  });

  it("mints no token, sends no email, and leaves the row untouched", async () => {
    // A signature is bound to a specific notice text. Re-sending would issue a
    // link to a document the employee already acknowledged.
    const { where } = givenSigned();
    await POST(makeRequest({ notice_ids: [NOTICE_A_ID] }));

    expect(where("signing_tokens", "insert")).toEqual([]);
    expect(where("notices", "update")).toEqual([]);
    expect(sendNoticeSigningEmail).not.toHaveBeenCalled();
  });

  it("still sends the sendable notices in a mixed batch", async () => {
    const { db } = makeDb({
      notices: {
        data: [
          makeNotice(NOTICE_A_ID, EMPLOYEE_A),
          makeNotice(NOTICE_B_ID, EMPLOYEE_B, "signed"),
        ],
        error: null,
      },
      employees: { data: [EMPLOYEE_A, EMPLOYEE_B], error: null },
    });
    givenAccount(db);

    const response = await POST(
      makeRequest({ notice_ids: [NOTICE_A_ID, NOTICE_B_ID] })
    );
    const body = (await response.json()) as SendBody;

    expect(response.status).toBe(200);
    expect(body.sent?.map((entry) => entry.notice_id)).toEqual([NOTICE_A_ID]);
    expect(body.blocked?.map((block) => block.notice_id)).toEqual([NOTICE_B_ID]);
    expect(sendNoticeSigningEmail).toHaveBeenCalledTimes(1);
  });

  it("allows re-sending a notice that was sent but not yet signed", async () => {
    // Only a signature is immutable. A nagging re-send is the whole point of
    // the /notices follow-up flow.
    const { db, where } = makeDb({
      notices: {
        data: [makeNotice(NOTICE_A_ID, EMPLOYEE_A, "sent")],
        error: null,
      },
      employees: { data: [EMPLOYEE_A], error: null },
    });
    givenAccount(db);

    const response = await POST(makeRequest({ notice_ids: [NOTICE_A_ID] }));

    expect(response.status).toBe(200);
    expect(where("signing_tokens", "insert")).toHaveLength(1);
    expect(sendNoticeSigningEmail).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// Infrastructure failures
// ---------------------------------------------------------------------------

describe("POST /api/notices/send — infrastructure failures fail closed", () => {
  it("returns 500 when the notice lookup errors", async () => {
    const { db, where } = makeDb({
      notices: { data: null, error: { message: "connection refused" } },
    });
    givenAccount(db);

    const response = await POST(makeRequest({ notice_ids: [NOTICE_A_ID] }));

    expect(response.status).toBe(500);
    expect(where("signing_tokens", "insert")).toEqual([]);
    expect(sendNoticeSigningEmail).not.toHaveBeenCalled();
  });

  it("returns 500 when the employee lookup errors, instead of blaming the roster", async () => {
    // An unread error here yields an empty employee map, and every notice is
    // then refused with "this employee has no email address on file" — sending
    // the owner to fix data that is not broken while a database fault goes
    // unreported.
    const { db, where } = makeDb({
      notices: { data: [makeNotice(NOTICE_A_ID, EMPLOYEE_A)], error: null },
      employees: { data: null, error: { message: "timeout" } },
    });
    givenAccount(db);

    const response = await POST(makeRequest({ notice_ids: [NOTICE_A_ID] }));
    const body = (await response.json()) as SendBody;

    expect(response.status).toBe(500);
    expect(body.blocked ?? []).toEqual([]);
    expect(where("signing_tokens", "insert")).toEqual([]);
    expect(sendNoticeSigningEmail).not.toHaveBeenCalled();
  });

  it("does not mark a notice sent when its token could not be created", async () => {
    const { db, where } = makeDb({
      notices: { data: [makeNotice(NOTICE_A_ID, EMPLOYEE_A)], error: null },
      employees: { data: [EMPLOYEE_A], error: null },
      tokenInsert: { data: null, error: { message: "unique violation" } },
    });
    givenAccount(db);

    const response = await POST(makeRequest({ notice_ids: [NOTICE_A_ID] }));
    const body = (await response.json()) as SendBody;

    expect(response.status).toBe(409);
    expect(body.sent).toEqual([]);
    expect(body.blocked?.[0].reason).toMatch(/nothing was sent/i);
    expect(where("notices", "update")).toEqual([]);
    expect(sendNoticeSigningEmail).not.toHaveBeenCalled();
  });

  it("does not email a signing link when the status transition failed", async () => {
    // Reporting a notice as sent while the row still reads 'draft' would put
    // the ledger and the employee's inbox permanently out of sync.
    const { db } = makeDb({
      notices: { data: [makeNotice(NOTICE_A_ID, EMPLOYEE_A)], error: null },
      employees: { data: [EMPLOYEE_A], error: null },
      noticeUpdate: { data: null, error: { message: "deadlock detected" } },
    });
    givenAccount(db);

    const response = await POST(makeRequest({ notice_ids: [NOTICE_A_ID] }));
    const body = (await response.json()) as SendBody;

    expect(response.status).toBe(409);
    expect(body.sent).toEqual([]);
    expect(body.blocked?.[0].reason).toMatch(/status could not be updated/i);
    expect(sendNoticeSigningEmail).not.toHaveBeenCalled();
  });

  it("does not read the foreign account id from anywhere in the response", async () => {
    // Defence in depth: nothing about another tenant should appear in output.
    const { db } = makeDb({ notices: { data: [], error: null } });
    givenAccount(db);

    const response = await POST(makeRequest({ notice_ids: [FOREIGN_NOTICE_ID] }));
    const text = await response.text();

    expect(text).not.toContain(OTHER_ACCOUNT_ID);
  });
});
