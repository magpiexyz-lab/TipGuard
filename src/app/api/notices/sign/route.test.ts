// Unit tests for POST /api/notices/sign — behavior b-07.
//
// This is the app's ONLY public, unauthenticated write endpoint. There is no
// session, no cookie and no account: the signer is a restaurant employee who
// received a link by email. The single piece of authorization material is the
// opaque token in that link, so every guarantee b-07 makes rests on this file:
//
//   - the token is looked up by its SHA-256 digest (`signing_tokens.token_hash`),
//     never by the raw value — the raw token is never stored anywhere;
//   - the token is SINGLE USE, enforced by a compare-and-swap on `used_at`, so a
//     replayed link cannot produce a second signature (and therefore cannot
//     produce a second `notice_signed` event);
//   - expiry is re-checked at submit time, because a token can lapse between
//     page render and Submit — the render-time check in `notice-lookup.ts` is a
//     UX affordance, not the boundary;
//   - NOTHING in the request body may identify the notice or the account. Only
//     the token may. The signer name is the sole caller-supplied value that is
//     persisted, and the timestamp, IP, user agent and frozen notice text are
//     all derived server-side.
//
// The db stand-in below models `used_at` as real state so replay, concurrency
// and rollback are exercised as sequences of requests rather than as mocked
// return values.

import { randomBytes } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST } from "./route";
import { hashSigningToken } from "@/app/sign/signing-token";
import type {
  NoticeRow,
  NoticeStatus,
  SignNoticeResponse,
  SignatureRow,
  SigningTokenRow,
} from "@/lib/types";

const { createServiceRoleClient } = vi.hoisted(() => ({
  createServiceRoleClient: vi.fn(),
}));

vi.mock("@/lib/supabase-server", () => ({ createServiceRoleClient }));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const ACCOUNT_ID = "22222222-2222-4222-8222-222222222222";
const OTHER_ACCOUNT_ID = "99999999-9999-4999-8999-999999999999";
const NOTICE_ID = "bbbbbbbb-0000-4000-8000-000000000001";
const TOKEN_ID = "dddddddd-0000-4000-8000-000000000001";

/** The exact text that was emailed. A signature freezes a copy of this. */
const NOTICE_TEXT = [
  "TIP CREDIT NOTICE",
  "",
  "Employer: The Tipped Spoon (TX)",
  "Cash wage paid: $2.13/hour. Tip credit claimed: $5.12/hour.",
  "This document requires review by your counsel before distribution.",
].join("\n");

/** Minted exactly the way POST /api/notices/send mints: 32 random bytes, base64url. */
function mintToken(): string {
  return randomBytes(32).toString("base64url");
}

const HOUR = 60 * 60 * 1000;

function makeToken(overrides: Partial<SigningTokenRow> = {}): SigningTokenRow {
  return {
    id: TOKEN_ID,
    account_id: ACCOUNT_ID,
    notice_id: NOTICE_ID,
    token_hash: "unused-by-the-stub",
    expires_at: new Date(Date.now() + 14 * 24 * HOUR).toISOString(),
    used_at: null,
    created_at: new Date(Date.now() - 4 * HOUR).toISOString(),
    ...overrides,
  };
}

type NoticeLookup = Pick<NoticeRow, "id" | "account_id" | "status" | "notice_text">;

function makeNotice(status: NoticeStatus = "sent", overrides: Partial<NoticeLookup> = {}): NoticeLookup {
  return {
    id: NOTICE_ID,
    account_id: ACCOUNT_ID,
    status,
    notice_text: NOTICE_TEXT,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Stateful stand-in for the service-role PostgREST client
// ---------------------------------------------------------------------------

type QueryResult = { data: unknown; error: unknown };
type DbError = { message: string };

interface DbCall {
  table: string;
  op: "select" | "insert" | "update" | "delete";
  columns: string;
  filters: [string, unknown][];
  /** `.is(col, value)` predicates, kept apart so the CAS guard is assertable. */
  isFilters: [string, unknown][];
  payload: unknown;
}

interface DbScenario {
  token?: SigningTokenRow | null;
  notice?: NoticeLookup | null;
  errors?: {
    tokenLookup?: DbError;
    noticeLookup?: DbError;
    consume?: DbError;
    signature?: DbError;
    noticeUpdate?: DbError;
  };
}

/**
 * Supabase query builders are thenables: the route awaits the builder itself
 * after the last filter for mutations, and awaits `.maybeSingle()` for reads.
 * The stub mirrors both, and models `signing_tokens.used_at` as live state so
 * `update(...).is("used_at", null)` behaves like the real compare-and-swap.
 */
function makeDb(scenario: DbScenario = {}) {
  const calls: DbCall[] = [];
  const signatures: Partial<SignatureRow>[] = [];
  const tokenRow = scenario.token === undefined ? makeToken() : scenario.token;
  const noticeRow = scenario.notice === undefined ? makeNotice() : scenario.notice;
  const errors = scenario.errors ?? {};

  const resultFor = (call: DbCall): QueryResult => {
    if (call.table === "signing_tokens" && call.op === "select") {
      if (errors.tokenLookup) return { data: null, error: errors.tokenLookup };
      return { data: tokenRow, error: null };
    }
    if (call.table === "notices" && call.op === "select") {
      if (errors.noticeLookup) return { data: null, error: errors.noticeLookup };
      return { data: noticeRow, error: null };
    }
    if (call.table === "signing_tokens" && call.op === "update") {
      const payload = call.payload as { used_at: string | null };
      if (payload.used_at === null) {
        // Releasing a consumed token (rollback after a failed insert).
        if (tokenRow) tokenRow.used_at = null;
        return { data: [{ id: tokenRow?.id }], error: null };
      }
      if (errors.consume) return { data: null, error: errors.consume };
      // Compare-and-swap: only an unused token may be consumed.
      if (tokenRow && tokenRow.used_at === null) {
        tokenRow.used_at = payload.used_at;
        return { data: [{ id: tokenRow.id }], error: null };
      }
      return { data: [], error: null };
    }
    if (call.table === "signatures" && call.op === "insert") {
      if (errors.signature) return { data: null, error: errors.signature };
      signatures.push(call.payload as Partial<SignatureRow>);
      return { data: null, error: null };
    }
    if (call.table === "notices" && call.op === "update") {
      if (errors.noticeUpdate) return { data: null, error: errors.noticeUpdate };
      const payload = call.payload as { status?: NoticeStatus };
      if (noticeRow && payload.status) noticeRow.status = payload.status;
      return { data: null, error: null };
    }
    throw new Error(`unexpected query: ${call.op} ${call.table}`);
  };

  const makeBuilder = (table: string) => {
    const call: DbCall = {
      table,
      op: "select",
      columns: "",
      filters: [],
      isFilters: [],
      payload: undefined,
    };
    const record = () => {
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
      is: (column: string, value: unknown) => {
        call.isFilters.push([column, value]);
        return builder;
      },
      maybeSingle: async () => record(),
      single: async () => record(),
      then: <T>(
        onFulfilled?: (value: QueryResult) => T,
        onRejected?: (reason: unknown) => T
      ) =>
        Promise.resolve()
          .then(record)
          .then(onFulfilled, onRejected),
    };
    return builder;
  };

  return {
    db: { from: (table: string) => makeBuilder(table) },
    calls,
    signatures,
    tokenRow,
    noticeRow,
    where: (table: string, op: DbCall["op"]) =>
      calls.filter((call) => call.table === table && call.op === op),
  };
}

type Harness = ReturnType<typeof makeDb>;

function given(scenario: DbScenario = {}): Harness {
  const harness = makeDb(scenario);
  createServiceRoleClient.mockReturnValue(harness.db);
  return harness;
}

// ---------------------------------------------------------------------------
// Request helpers
// ---------------------------------------------------------------------------

// The limiter is real and module-scoped for the whole file, so every request
// gets its own source IP unless a test is deliberately exercising throttling.
let ipCounter = 0;
function nextIp(): string {
  ipCounter += 1;
  return `203.0.113.${ipCounter % 250}`;
}

const USER_AGENT =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1";

function makeRequest(
  body: unknown,
  options: { ip?: string; xff?: string; userAgent?: string } = {}
): Request {
  const headers: Record<string, string> = {
    "content-type": "application/json",
    "x-forwarded-for": options.xff ?? options.ip ?? nextIp(),
  };
  if (options.userAgent !== undefined) headers["user-agent"] = options.userAgent;
  return new Request("https://tipguard.app/api/notices/sign", {
    method: "POST",
    headers,
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

/** A complete, well-formed submission for the fixture token. */
function sign(token: string, signerName = "Marisol Vega") {
  return POST(makeRequest({ token, signer_name: signerName }, { userAgent: USER_AGENT }));
}

type ErrorBody = { error?: string };

const originalDemoMode = process.env.DEMO_MODE;

beforeEach(() => {
  vi.clearAllMocks();
  delete process.env.DEMO_MODE;
  // The route logs infrastructure failures by design; keep output readable.
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
  if (originalDemoMode === undefined) delete process.env.DEMO_MODE;
  else process.env.DEMO_MODE = originalDemoMode;
});

// ---------------------------------------------------------------------------
// The token is the only authorization material
// ---------------------------------------------------------------------------

describe("POST /api/notices/sign — the token is the only authorization material", () => {
  it("resolves the token by its SHA-256 digest, never by the raw value", async () => {
    // `signing_tokens.token_hash` stores the digest only. Querying by the raw
    // token would mean the raw token had to be stored, and a database leak
    // would hand an attacker a set of working signing links.
    const rawToken = mintToken();
    const { where } = given();

    await sign(rawToken);

    const lookup = where("signing_tokens", "select")[0];
    expect(lookup.filters).toEqual([["token_hash", hashSigningToken(rawToken)]]);
    expect(JSON.stringify(lookup.filters)).not.toContain(rawToken);
  });

  it("accepts the digest of a token minted the way /api/notices/send mints them", async () => {
    // Cross-route contract: send writes hashSigningToken(randomBytes(32)) and
    // this route must resolve that same digest. A fork in the hashing would
    // break every signing link in production, silently.
    const rawToken = mintToken();
    const { signatures } = given();

    const response = await sign(rawToken);

    expect(response.status).toBe(200);
    expect(signatures).toHaveLength(1);
  });

  it("never persists the raw token anywhere in the signature record", async () => {
    const rawToken = mintToken();
    const { signatures } = given();

    await sign(rawToken);

    expect(JSON.stringify(signatures[0])).not.toContain(rawToken);
  });

  it("identifies the notice from the token row, not from the request body", async () => {
    // A body field naming another notice must have no effect whatsoever.
    const rawToken = mintToken();
    const { where, signatures } = given();

    const response = await POST(
      makeRequest(
        {
          token: rawToken,
          signer_name: "Marisol Vega",
          notice_id: "ffffffff-0000-4000-8000-000000000009",
          account_id: OTHER_ACCOUNT_ID,
        },
        { userAgent: USER_AGENT }
      )
    );

    expect(response.status).toBe(200);
    expect(where("notices", "select")[0].filters).toEqual([["id", NOTICE_ID]]);
    expect(signatures[0]).toMatchObject({
      notice_id: NOTICE_ID,
      account_id: ACCOUNT_ID,
    });
  });

  it("ignores caller-supplied timestamp, IP, user agent and notice text", async () => {
    // Every one of these is legally load-bearing, and a browser is not a
    // trustworthy source for any of them.
    const rawToken = mintToken();
    const { signatures } = given();

    const response = await POST(
      makeRequest(
        {
          token: rawToken,
          signer_name: "Marisol Vega",
          signed_at: "1999-01-01T00:00:00.000Z",
          ip_address: "127.0.0.1",
          user_agent: "definitely-not-my-browser",
          notice_text_snapshot: "I agree to work for free.",
        },
        { ip: "198.51.100.5", userAgent: USER_AGENT }
      )
    );

    expect(response.status).toBe(200);
    const record = signatures[0];
    expect(record.signed_at).not.toBe("1999-01-01T00:00:00.000Z");
    expect(record.ip_address).toBe("198.51.100.5");
    expect(record.user_agent).toBe(USER_AGENT);
    expect(record.notice_text_snapshot).toBe(NOTICE_TEXT);
  });

  it("refuses when the token names a notice belonging to a different account", async () => {
    // The token row and the notice row are written together by /notices/send,
    // so a mismatch means the linkage was tampered with or corrupted. Signing
    // it would file an acknowledgment under someone else's account.
    const rawToken = mintToken();
    const { signatures, where } = given({
      token: makeToken({ account_id: ACCOUNT_ID }),
      notice: makeNotice("sent", { account_id: OTHER_ACCOUNT_ID }),
    });

    const response = await sign(rawToken);

    expect(response.status).toBeGreaterThanOrEqual(400);
    expect(signatures).toEqual([]);
    expect(where("signing_tokens", "update")).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// b-07 criterion 1: "an invalid, expired, or already-used token ... cannot sign"
// ---------------------------------------------------------------------------

describe("POST /api/notices/sign — invalid, expired and used tokens cannot sign", () => {
  it("signs with a valid, unexpired, unused token", async () => {
    const rawToken = mintToken();
    const { signatures } = given();

    const response = await sign(rawToken);
    const body = (await response.json()) as SignNoticeResponse;

    expect(response.status).toBe(200);
    expect(body.notice_id).toBe(NOTICE_ID);
    expect(Number.isNaN(Date.parse(body.signed_at))).toBe(false);
    expect(signatures).toHaveLength(1);
  });

  it("refuses an unknown token with 404 and writes nothing", async () => {
    const { signatures, where } = given({ token: null });

    const response = await sign(mintToken());

    expect(response.status).toBe(404);
    expect(signatures).toEqual([]);
    expect(where("signing_tokens", "update")).toEqual([]);
    expect(where("notices", "update")).toEqual([]);
  });

  it("refuses a malformed token before any database query runs", async () => {
    // A value outside the mintable alphabet cannot match a stored digest, so
    // it must never reach a query.
    const { calls } = given();

    const response = await POST(
      makeRequest({ token: "../../../etc/passwd", signer_name: "Marisol Vega" })
    );

    expect(response.status).toBe(404);
    expect(calls).toEqual([]);
  });

  it("refuses a token with SQL-ish or wildcard characters without querying", async () => {
    const { calls } = given();

    for (const hostile of ["' OR 1=1 --", "%", "aaaaaaaa%", "aaaa aaaa"]) {
      const response = await POST(
        makeRequest({ token: hostile, signer_name: "Marisol Vega" })
      );
      expect(response.status).toBeGreaterThanOrEqual(400);
    }
    expect(calls).toEqual([]);
  });

  it("refuses an expired token with 410 and writes nothing", async () => {
    const { signatures, where } = given({
      token: makeToken({ expires_at: new Date(Date.now() - HOUR).toISOString() }),
    });

    const response = await sign(mintToken());
    const body = (await response.json()) as ErrorBody;

    expect(response.status).toBe(410);
    expect(body.error).toMatch(/expired/i);
    expect(signatures).toEqual([]);
    expect(where("signing_tokens", "update")).toEqual([]);
  });

  it("treats a token expiring exactly now as expired", async () => {
    const now = Date.now();
    vi.spyOn(Date, "now").mockReturnValue(now);
    const { signatures } = given({
      token: makeToken({ expires_at: new Date(now).toISOString() }),
    });

    const response = await sign(mintToken());

    expect(response.status).toBe(410);
    expect(signatures).toEqual([]);
  });

  it("refuses a token whose expiry is unparseable rather than assuming it is live", async () => {
    const { signatures } = given({ token: makeToken({ expires_at: "not-a-date" }) });

    const response = await sign(mintToken());

    expect(response.status).toBe(410);
    expect(signatures).toEqual([]);
  });

  it("refuses an already-used token with 409 and writes nothing", async () => {
    const { signatures, where } = given({
      token: makeToken({ used_at: new Date(Date.now() - HOUR).toISOString() }),
    });

    const response = await sign(mintToken());
    const body = (await response.json()) as ErrorBody;

    expect(response.status).toBe(409);
    expect(body.error).toMatch(/already been signed/i);
    expect(signatures).toEqual([]);
    expect(where("signatures", "insert")).toEqual([]);
  });

  it("refuses an already-used token even when it has not expired", async () => {
    // Single use is not a function of expiry — a fresh-but-consumed link is
    // just as dead as a lapsed one.
    const { signatures } = given({
      token: makeToken({
        used_at: new Date().toISOString(),
        expires_at: new Date(Date.now() + 14 * 24 * HOUR).toISOString(),
      }),
    });

    const response = await sign(mintToken());

    expect(response.status).toBe(409);
    expect(signatures).toEqual([]);
  });

  it("refuses when the notice the token points at no longer exists", async () => {
    const { signatures, where } = given({ notice: null });

    const response = await sign(mintToken());

    expect(response.status).toBe(404);
    expect(signatures).toEqual([]);
    expect(where("signing_tokens", "update")).toEqual([]);
  });

  it("refuses a notice that is already signed even if the token looks unused", async () => {
    const { signatures } = given({ notice: makeNotice("signed") });

    const response = await sign(mintToken());
    const body = (await response.json()) as ErrorBody;

    expect(response.status).toBe(409);
    expect(body.error).toMatch(/already been signed/i);
    expect(signatures).toEqual([]);
  });

  it("refuses a notice that is still a draft — only a sent notice is signable", async () => {
    const { signatures } = given({ notice: makeNotice("draft") });

    const response = await sign(mintToken());
    const body = (await response.json()) as ErrorBody;

    expect(response.status).toBe(409);
    expect(body.error).toMatch(/not ready/i);
    expect(signatures).toEqual([]);
  });

  it("does not reveal whether a guessed token exists", async () => {
    // "Never minted" and "minted but the notice vanished" must read the same,
    // otherwise the error body is an enumeration oracle.
    given({ token: null });
    const missingToken = await sign(mintToken());
    given({ notice: null });
    const missingNotice = await sign(mintToken());

    expect(missingToken.status).toBe(404);
    expect(missingNotice.status).toBe(404);
    expect(((await missingToken.json()) as ErrorBody).error).toBe(
      ((await missingNotice.json()) as ErrorBody).error
    );
  });
});

// ---------------------------------------------------------------------------
// b-07 criterion 4 (route half): "notice_signed fires once per signature"
//
// The client fires `notice_signed` on a 2xx response. Exactly one 2xx per
// token is therefore exactly one event per signature.
// ---------------------------------------------------------------------------

describe("POST /api/notices/sign — a token signs exactly once", () => {
  it("produces one signature row and one 2xx for a valid token", async () => {
    const rawToken = mintToken();
    const { signatures, where } = given();

    const response = await sign(rawToken);

    expect(response.status).toBe(200);
    expect(signatures).toHaveLength(1);
    expect(where("signatures", "insert")).toHaveLength(1);
  });

  it("refuses a replay of the same token and writes no second signature", async () => {
    // The db stand-in models `used_at`, so the second request sees exactly what
    // the second request would see in production.
    const rawToken = mintToken();
    const { signatures } = given();

    const first = await sign(rawToken);
    const replay = await sign(rawToken);

    expect(first.status).toBe(200);
    expect(replay.status).toBe(409);
    expect(signatures).toHaveLength(1);
  });

  it("refuses a replay carrying a different signer name", async () => {
    // Otherwise a leaked link would let anyone append their own name.
    const rawToken = mintToken();
    const { signatures } = given();

    await sign(rawToken, "Marisol Vega");
    const replay = await sign(rawToken, "Someone Else");

    expect(replay.status).toBe(409);
    expect(signatures).toHaveLength(1);
    expect(signatures[0].signer_name).toBe("Marisol Vega");
  });

  it("consumes the token with a compare-and-swap on used_at, scoped to that token", async () => {
    // `used_at IS NULL` in the predicate is what makes two concurrent submits
    // resolve to one winner at the database, not in application code.
    const { where } = given();

    await sign(mintToken());

    const consume = where("signing_tokens", "update")[0];
    expect(consume.payload).toMatchObject({ used_at: expect.any(String) });
    expect(consume.filters).toContainEqual(["id", TOKEN_ID]);
    expect(consume.isFilters).toContainEqual(["used_at", null]);
  });

  it("consumes the token before writing the signature", async () => {
    const { calls } = given();

    await sign(mintToken());

    const consumeIndex = calls.findIndex(
      (call) => call.table === "signing_tokens" && call.op === "update"
    );
    const insertIndex = calls.findIndex(
      (call) => call.table === "signatures" && call.op === "insert"
    );
    expect(consumeIndex).toBeGreaterThanOrEqual(0);
    expect(insertIndex).toBeGreaterThan(consumeIndex);
  });

  it("writes nothing when it loses the compare-and-swap race", async () => {
    // Two submits from a double-tap: the loser's UPDATE matches zero rows. It
    // must stop there rather than insert a second signature.
    const harness = given();
    const originalFrom = harness.db.from;
    let tokenQueries = 0;
    harness.db.from = (table: string) => {
      if (table === "signing_tokens") {
        tokenQueries += 1;
        // The lookup (1st) still sees an unused token; by the time we consume
        // (2nd), the concurrent winner has already taken it.
        if (tokenQueries === 2 && harness.tokenRow) {
          harness.tokenRow.used_at = new Date().toISOString();
        }
      }
      return originalFrom(table);
    };

    const response = await sign(mintToken());

    expect(response.status).toBe(409);
    expect(harness.signatures).toEqual([]);
  });

  it("still refuses the compare-and-swap loser when DEMO_MODE is set", async () => {
    // An env-var escape hatch around the CAS is an escape hatch around the one
    // guarantee that keeps `notice_signed` at one event per signature. The demo
    // client never reaches this line anyway — its token lookup resolves to
    // null, so the request 404s long before the update.
    process.env.DEMO_MODE = "true";
    const harness = given();
    const originalFrom = harness.db.from;
    let tokenQueries = 0;
    harness.db.from = (table: string) => {
      if (table === "signing_tokens") {
        tokenQueries += 1;
        if (tokenQueries === 2 && harness.tokenRow) {
          harness.tokenRow.used_at = new Date().toISOString();
        }
      }
      return originalFrom(table);
    };

    const response = await sign(mintToken());

    expect(response.status).toBe(409);
    expect(harness.signatures).toEqual([]);
  });

  it("enforces single use regardless of environment configuration", async () => {
    // Single use is the guarantee behind "notice_signed fires once per
    // signature". No environment variable may switch it off.
    process.env.DEMO_MODE = "true";
    const { signatures } = given({ token: makeToken({ used_at: null }) });
    const rawToken = mintToken();

    await sign(rawToken);
    const replay = await sign(rawToken);

    expect(replay.status).toBe(409);
    expect(signatures).toHaveLength(1);
  });

  it("marks the notice signed so the owner's dashboard count moves once", async () => {
    const { where, noticeRow } = given();

    await sign(mintToken());

    const update = where("notices", "update")[0];
    expect(update.payload).toEqual({ status: "signed" });
    expect(update.filters).toContainEqual(["id", NOTICE_ID]);
    expect(noticeRow?.status).toBe("signed");
  });
});

// ---------------------------------------------------------------------------
// b-07 criterion 2: "Signing persists signer name, timestamp, IP, user agent,
// and a frozen copy of the notice text"
// ---------------------------------------------------------------------------

describe("POST /api/notices/sign — what the vault record contains", () => {
  it("persists every field the acknowledgment vault requires", async () => {
    const { signatures } = given();

    const before = Date.now();
    await POST(
      makeRequest(
        { token: mintToken(), signer_name: "Marisol Vega" },
        { ip: "198.51.100.23", userAgent: USER_AGENT }
      )
    );

    const record = signatures[0];
    expect(record).toMatchObject({
      account_id: ACCOUNT_ID,
      notice_id: NOTICE_ID,
      signer_name: "Marisol Vega",
      ip_address: "198.51.100.23",
      user_agent: USER_AGENT,
      notice_text_snapshot: NOTICE_TEXT,
    });
    expect(Date.parse(record.signed_at as string)).toBeGreaterThanOrEqual(before);
  });

  it("records the timestamp in UTC ISO-8601 from the server clock", async () => {
    const { signatures } = given();

    await sign(mintToken());

    expect(signatures[0].signed_at).toMatch(
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/
    );
  });

  it("reports the same timestamp to the signer that it wrote to the vault", async () => {
    const { signatures } = given();

    const response = await sign(mintToken());
    const body = (await response.json()) as SignNoticeResponse;

    expect(body.signed_at).toBe(signatures[0].signed_at);
  });

  it("stamps the consumed token with the same instant as the signature", async () => {
    const { signatures, where } = given();

    await sign(mintToken());

    const consume = where("signing_tokens", "update")[0].payload as { used_at: string };
    expect(consume.used_at).toBe(signatures[0].signed_at);
  });

  it("takes the IP from the trusted last X-Forwarded-For entry", async () => {
    // Entries before the last are client-supplied. Recording one would put a
    // forged address in a legal record.
    const { signatures } = given();

    await POST(
      makeRequest(
        { token: mintToken(), signer_name: "Marisol Vega" },
        { xff: "1.2.3.4, 5.6.7.8, 198.51.100.99", userAgent: USER_AGENT }
      )
    );

    expect(signatures[0].ip_address).toBe("198.51.100.99");
  });

  it("records an empty user agent rather than failing when the header is absent", async () => {
    // `signatures.user_agent` is NOT NULL. A headless submit must still record.
    const { signatures } = given();

    const response = await POST(
      makeRequest({ token: mintToken(), signer_name: "Marisol Vega" })
    );

    expect(response.status).toBe(200);
    expect(signatures[0].user_agent).toBe("");
  });

  it("bounds the stored user agent so a padded header cannot bloat the vault", async () => {
    const { signatures } = given();

    await POST(
      makeRequest(
        { token: mintToken(), signer_name: "Marisol Vega" },
        { userAgent: "U".repeat(4000) }
      )
    );

    expect((signatures[0].user_agent as string).length).toBeLessThanOrEqual(500);
  });

  it("stores a copy of the notice text, not a reference to the notice row", async () => {
    // The snapshot is what the employee actually acknowledged. A later edit to
    // `notices.notice_text` must not be able to change it.
    const harness = given();

    await sign(mintToken());
    const snapshot = harness.signatures[0].notice_text_snapshot;
    harness.noticeRow!.notice_text = "Rewritten after the fact.";

    expect(snapshot).toBe(NOTICE_TEXT);
    expect(harness.signatures[0].notice_text_snapshot).toBe(NOTICE_TEXT);
  });

  it("reads the frozen text out of the notice row the token resolved to", async () => {
    const customText = "TIP CREDIT NOTICE — Colorado edition";
    const { signatures } = given({ notice: makeNotice("sent", { notice_text: customText }) });

    await sign(mintToken());

    expect(signatures[0].notice_text_snapshot).toBe(customText);
  });

  it("stores the signer name trimmed of surrounding whitespace", async () => {
    const { signatures } = given();

    await sign(mintToken(), "  Marisol Vega  ");

    expect(signatures[0].signer_name).toBe("Marisol Vega");
  });
});

// ---------------------------------------------------------------------------
// b-07 criterion 3: "The signed record is immutable — no API path allows
// editing notice text after signature"
// ---------------------------------------------------------------------------

describe("POST /api/notices/sign — the signed record is immutable", () => {
  it("only ever inserts into signatures — never updates or deletes one", async () => {
    const { where } = given();

    await sign(mintToken());

    expect(where("signatures", "insert")).toHaveLength(1);
    expect(where("signatures", "update")).toEqual([]);
    expect(where("signatures", "delete")).toEqual([]);
  });

  it("touches only the notice status — never the notice text", async () => {
    // This route is the only writer on the signing path. If it could carry a
    // notice_text into the update, the text behind a signature would be
    // editable through the public endpoint.
    const { where } = given();

    await sign(mintToken());

    for (const update of where("notices", "update")) {
      expect(Object.keys(update.payload as object)).toEqual(["status"]);
    }
  });

  it("does not accept a notice_text field from the body on any path", async () => {
    const { where, signatures } = given();

    await POST(
      makeRequest(
        {
          token: mintToken(),
          signer_name: "Marisol Vega",
          notice_text: "Employee agrees to forfeit overtime.",
        },
        { userAgent: USER_AGENT }
      )
    );

    expect(signatures[0].notice_text_snapshot).toBe(NOTICE_TEXT);
    for (const update of where("notices", "update")) {
      expect(JSON.stringify(update.payload)).not.toContain("forfeit overtime");
    }
  });

  it("cannot rewrite an existing record by re-submitting the same token", async () => {
    const rawToken = mintToken();
    const { signatures, where } = given();

    await sign(rawToken, "Marisol Vega");
    const replay = await POST(
      makeRequest(
        { token: rawToken, signer_name: "Marisol Vega", notice_text_snapshot: "Different." },
        { userAgent: USER_AGENT }
      )
    );

    expect(replay.status).toBe(409);
    expect(where("signatures", "insert")).toHaveLength(1);
    expect(signatures[0].notice_text_snapshot).toBe(NOTICE_TEXT);
  });
});

// ---------------------------------------------------------------------------
// Input validation — the body is untrusted input
// ---------------------------------------------------------------------------

describe("POST /api/notices/sign — input validation", () => {
  it("rejects a body that is not valid JSON without querying", async () => {
    const { calls } = given();

    const response = await POST(makeRequest("{not json"));

    expect(response.status).toBe(400);
    expect(calls).toEqual([]);
  });

  it("rejects a missing token", async () => {
    given();
    const response = await POST(makeRequest({ signer_name: "Marisol Vega" }));
    expect(response.status).toBe(400);
  });

  it("rejects a missing signer name", async () => {
    given();
    const response = await POST(makeRequest({ token: mintToken() }));
    expect(response.status).toBe(400);
  });

  it("rejects a token shorter than any mintable token", async () => {
    const { calls } = given();
    const response = await POST(makeRequest({ token: "abc", signer_name: "Marisol Vega" }));
    expect(response.status).toBe(400);
    expect(calls).toEqual([]);
  });

  it("rejects an over-long token before hashing or querying", async () => {
    const { calls } = given();
    const response = await POST(
      makeRequest({ token: "a".repeat(5000), signer_name: "Marisol Vega" })
    );
    expect(response.status).toBe(400);
    expect(calls).toEqual([]);
  });

  it("rejects a token that is not a string", async () => {
    const { calls } = given();
    const response = await POST(makeRequest({ token: { toString: 1 }, signer_name: "Marisol Vega" }));
    expect(response.status).toBe(400);
    expect(calls).toEqual([]);
  });

  it("rejects a one-character signer name", async () => {
    const { signatures } = given();
    const response = await POST(makeRequest({ token: mintToken(), signer_name: "M" }));
    expect(response.status).toBe(400);
    expect(signatures).toEqual([]);
  });

  it("rejects a whitespace-only signer name — a blank line is not a signature", async () => {
    const { signatures } = given();
    const response = await POST(
      makeRequest({ token: mintToken(), signer_name: "      " })
    );
    expect(response.status).toBe(400);
    expect(signatures).toEqual([]);
  });

  it("rejects a signer name longer than the column allows", async () => {
    const { signatures } = given();
    const response = await POST(
      makeRequest({ token: mintToken(), signer_name: "M".repeat(121) })
    );
    expect(response.status).toBe(400);
    expect(signatures).toEqual([]);
  });

  it("rejects a signer name that is not a string", async () => {
    const { signatures } = given();
    const response = await POST(
      makeRequest({ token: mintToken(), signer_name: ["Marisol", "Vega"] })
    );
    expect(response.status).toBe(400);
    expect(signatures).toEqual([]);
  });

  it("never consumes a token when validation fails", async () => {
    const { where, tokenRow } = given();

    await POST(makeRequest({ token: mintToken(), signer_name: "M" }));

    expect(where("signing_tokens", "update")).toEqual([]);
    expect(tokenRow?.used_at).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Rate limiting — this endpoint is a public token-guessing surface
// ---------------------------------------------------------------------------

describe("POST /api/notices/sign — rate limiting", () => {
  it("throttles a burst from one IP so the endpoint is not a guessing oracle", async () => {
    const ip = "198.51.100.201";
    given({ token: null });

    for (let attempt = 0; attempt < 10; attempt += 1) {
      const allowed = await POST(
        makeRequest({ token: mintToken(), signer_name: "Marisol Vega" }, { ip })
      );
      expect(allowed.status).toBe(404);
    }

    const throttled = await POST(
      makeRequest({ token: mintToken(), signer_name: "Marisol Vega" }, { ip })
    );
    expect(throttled.status).toBe(429);
  });

  it("throttles before touching the database", async () => {
    const ip = "198.51.100.202";
    const { calls } = given({ token: null });

    for (let attempt = 0; attempt < 10; attempt += 1) {
      await POST(makeRequest({ token: mintToken(), signer_name: "Marisol Vega" }, { ip }));
    }
    const queriesBefore = calls.length;

    const throttled = await POST(
      makeRequest({ token: mintToken(), signer_name: "Marisol Vega" }, { ip })
    );

    expect(throttled.status).toBe(429);
    expect(calls.length).toBe(queriesBefore);
  });

  it("cannot be evaded by prepending forged X-Forwarded-For entries", async () => {
    // Only the LAST entry is appended by the proxy. Keying on the whole header
    // would let an attacker mint a fresh bucket per request.
    given({ token: null });

    for (let attempt = 0; attempt < 10; attempt += 1) {
      await POST(
        makeRequest(
          { token: mintToken(), signer_name: "Marisol Vega" },
          { xff: `10.0.0.${attempt}, 198.51.100.203` }
        )
      );
    }

    const throttled = await POST(
      makeRequest(
        { token: mintToken(), signer_name: "Marisol Vega" },
        { xff: "10.0.0.250, 198.51.100.203" }
      )
    );
    expect(throttled.status).toBe(429);
  });
});

// ---------------------------------------------------------------------------
// Infrastructure failures fail closed
// ---------------------------------------------------------------------------

describe("POST /api/notices/sign — infrastructure failures fail closed", () => {
  it("returns 503 when the service-role client cannot be built", async () => {
    createServiceRoleClient.mockImplementation(() => {
      throw new Error("SUPABASE_SERVICE_ROLE_KEY is not configured");
    });

    const response = await sign(mintToken());

    expect(response.status).toBe(503);
  });

  it("returns 503 — not 404 — when the token lookup errors", async () => {
    // Reporting "your link is invalid" during an outage sends the employee
    // back to their employer for a link that is perfectly good.
    const { signatures } = given({ errors: { tokenLookup: { message: "connection refused" } } });

    const response = await sign(mintToken());

    expect(response.status).toBe(503);
    expect(signatures).toEqual([]);
  });

  it("returns 503 when the notice lookup errors and consumes nothing", async () => {
    const { where, tokenRow } = given({ errors: { noticeLookup: { message: "timeout" } } });

    const response = await sign(mintToken());

    expect(response.status).toBe(503);
    expect(where("signing_tokens", "update")).toEqual([]);
    expect(tokenRow?.used_at).toBeNull();
  });

  it("does not write a signature when the token could not be consumed", async () => {
    const { signatures } = given({ errors: { consume: { message: "deadlock detected" } } });

    const response = await sign(mintToken());

    expect(response.status).toBeGreaterThanOrEqual(500);
    expect(signatures).toEqual([]);
  });

  it("returns 500 when the signature insert fails", async () => {
    const { where } = given({ errors: { signature: { message: "insert failed" } } });

    const response = await sign(mintToken());

    expect(response.status).toBe(500);
    expect(where("notices", "update")).toEqual([]);
  });

  it("releases the token when the signature insert fails, so the link is not dead", async () => {
    // The token is consumed BEFORE the insert. If the insert then fails and the
    // token stays consumed, the employee's only signing link is permanently
    // dead: every retry returns "already signed" while the vault holds nothing.
    const { tokenRow } = given({ errors: { signature: { message: "insert failed" } } });

    const response = await sign(mintToken());

    expect(response.status).toBe(500);
    expect(tokenRow?.used_at).toBeNull();
  });

  it("lets the employee retry successfully after a failed signature insert", async () => {
    const rawToken = mintToken();
    const harness = makeDb({ errors: { signature: { message: "insert failed" } } });
    createServiceRoleClient.mockReturnValue(harness.db);

    const failed = await sign(rawToken);
    expect(failed.status).toBe(500);

    // Same token, same notice, healthy database on the second attempt.
    const retryHarness = makeDb({ token: harness.tokenRow, notice: harness.noticeRow });
    createServiceRoleClient.mockReturnValue(retryHarness.db);

    const retry = await sign(rawToken);

    expect(retry.status).toBe(200);
    expect(retryHarness.signatures).toHaveLength(1);
  });

  it("still confirms the signature when only the notice status update fails", async () => {
    // The vault row is already durable and is the record of truth. Telling the
    // employee it failed would invite a second submit that can never succeed.
    const { signatures } = given({ errors: { noticeUpdate: { message: "deadlock" } } });

    const response = await sign(mintToken());

    expect(response.status).toBe(200);
    expect(signatures).toHaveLength(1);
  });

  it("never returns a 2xx without a signature row", async () => {
    const scenarios: DbScenario[] = [
      { token: null },
      { notice: null },
      { token: makeToken({ used_at: new Date().toISOString() }) },
      { token: makeToken({ expires_at: new Date(Date.now() - HOUR).toISOString() }) },
      { notice: makeNotice("draft") },
      { notice: makeNotice("signed") },
      { errors: { tokenLookup: { message: "boom" } } },
      { errors: { noticeLookup: { message: "boom" } } },
      { errors: { consume: { message: "boom" } } },
      { errors: { signature: { message: "boom" } } },
    ];

    for (const scenario of scenarios) {
      const { signatures } = given(scenario);
      const response = await sign(mintToken());
      expect(response.ok).toBe(false);
      expect(signatures).toEqual([]);
    }
  });
});
