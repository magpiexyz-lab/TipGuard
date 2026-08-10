// Unit tests for GET/POST /api/audit-file — behavior b-12.
//
// b-12: "a paid owner clicks 'Build my audit file'; a single dated export is
// assembled containing every signed notice with its signature metadata, the
// notice-status roster, the violation log with resolutions, and the applicable
// state rule versions; audit_file_exported fires."
//
// Two properties make this handler the one to get right:
//
//   1. IT IS THE PAYWALL. The assembled export is the paid artifact (h-06).
//      The free tier gets the same index — locked, not withheld — with the
//      frozen notice text removed. A gating defect does not throw; it quietly
//      ships the paid content, and no page test would notice. So the free-tier
//      assertions here are POSITIVE: the frozen text must appear nowhere in the
//      payload, at any depth, under any key.
//   2. IT IS EVIDENCE. Every signed notice is rendered from
//      `signatures.notice_text_snapshot` — the copy frozen at signature time —
//      never re-rendered from the current template. And the cover index and the
//      signed-notice index are read side by side by whoever is auditing the
//      restaurant: if they disagree about whether an employee signed, the file
//      is worse than useless.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GET, POST } from "./route";
import { trackAuditFileExported } from "@/lib/events";
import type {
  AuditFileCounts,
  AuditFileExport,
  AuditFilePreview,
} from "@/app/audit-file/audit-file-contract";
import type { AccountRow, EmployeeRow, NoticeRow, SignatureRow } from "@/lib/types";

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

/**
 * The paid content. Every free-tier assertion in this file hunts for this
 * string and the fragment below it, so it has to be unmistakable.
 */
const FROZEN_TEXT = [
  "TIP CREDIT NOTICE (frozen at signature time)",
  "Cash wage: $2.13/hour. Tip credit claimed: $5.12/hour.",
  "Texas rule version tx-2026.01 applied.",
].join("\n");

/** A fragment that survives any reformatting of the text above. */
const FROZEN_FRAGMENT = "frozen at signature time";

/** What the CURRENT template would render. Never belongs in the export. */
const REGENERATED_TEXT = "TIP CREDIT NOTICE (re-rendered from today's template)";

type EmployeeSlice = Pick<EmployeeRow, "id" | "name" | "email" | "role" | "state">;
type NoticeSlice = Pick<
  NoticeRow,
  | "id"
  | "employee_id"
  | "state"
  | "rule_version"
  | "status"
  | "sent_at"
  | "created_at"
  | "notice_text"
>;
type SignatureSlice = Pick<
  SignatureRow,
  "id" | "notice_id" | "signer_name" | "signed_at" | "notice_text_snapshot"
>;

const EMPLOYEES: EmployeeSlice[] = [
  {
    id: "emp-1",
    name: "Marisol Vega",
    email: "marisol.vega@northbay.test",
    role: "Server",
    state: "TX",
  },
  {
    id: "emp-2",
    name: "Devon Achebe",
    email: "devon.achebe@northbay.test",
    role: "Bartender",
    state: "TX",
  },
  {
    id: "emp-3",
    name: "Priya Raman",
    email: "priya.raman@northbay.test",
    role: "Server",
    state: "TX",
  },
];

const NOTICES: NoticeSlice[] = [
  {
    id: "notice-1",
    employee_id: "emp-1",
    state: "TX",
    rule_version: "tx-2026.01",
    status: "signed",
    sent_at: "2026-02-02T09:00:00.000Z",
    created_at: "2026-02-01T09:00:00.000Z",
    notice_text: REGENERATED_TEXT,
  },
  {
    id: "notice-2",
    employee_id: "emp-2",
    state: "TX",
    rule_version: "tx-2026.01",
    status: "sent",
    sent_at: "2026-02-02T09:00:00.000Z",
    created_at: "2026-02-01T09:05:00.000Z",
    notice_text: REGENERATED_TEXT,
  },
];

const SIGNATURES: SignatureSlice[] = [
  {
    id: "sig-1",
    notice_id: "notice-1",
    signer_name: "Marisol Vega",
    signed_at: "2026-02-03T14:22:00.000Z",
    notice_text_snapshot: FROZEN_TEXT,
  },
];

const VIOLATIONS = [{ id: "violation-1" }, { id: "violation-2" }];

interface Dataset {
  employees: EmployeeSlice[];
  notices: NoticeSlice[];
  signatures: SignatureSlice[];
  violations: { id: string }[];
}

function dataset(overrides: Partial<Dataset> = {}): Dataset {
  return {
    employees: EMPLOYEES,
    notices: NOTICES,
    signatures: SIGNATURES,
    violations: VIOLATIONS,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Recording stand-in for the service-role PostgREST client
//
// It PROJECTS to the requested column list, like PostgREST does. That is what
// makes "the export prints the frozen snapshot, not the live notice text" a
// real assertion: a route that selected `notice_text` would have to ask for it.
// ---------------------------------------------------------------------------

interface DbCall {
  table: string;
  columns: string;
  filters: [string, unknown][];
  order: string | null;
}

interface DbScenario {
  data?: Partial<Dataset>;
  /** Table whose read comes back as a Postgres error. */
  errorOn?: keyof Dataset;
}

const DB_ERROR = {
  message: 'relation "signatures" does not exist at host db.internal',
};

function project(row: Record<string, unknown>, columns: string): Record<string, unknown> {
  const wanted = columns.split(",").map((column) => column.trim());
  const out: Record<string, unknown> = {};
  for (const column of wanted) {
    if (column in row) out[column] = row[column];
  }
  return out;
}

function makeDb(scenario: DbScenario = {}) {
  const rowsByTable = dataset(scenario.data) as unknown as Record<
    string,
    Record<string, unknown>[]
  >;
  const calls: DbCall[] = [];

  const makeBuilder = (table: string) => {
    const call: DbCall = { table, columns: "", filters: [], order: null };

    const settle = () =>
      Promise.resolve().then(() => {
        calls.push(call);
        if (scenario.errorOn === table) return { data: null, error: DB_ERROR };
        const rows = rowsByTable[table] ?? [];
        return { data: rows.map((row) => project(row, call.columns)), error: null };
      });

    const builder = {
      select: (columns: string) => {
        call.columns = columns;
        return builder;
      },
      eq: (column: string, value: unknown) => {
        call.filters.push([column, value]);
        return builder;
      },
      order: (column: string) => {
        call.order = column;
        return builder;
      },
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
    forTable: (table: string) => calls.filter((call) => call.table === table),
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

/** A paid owner with the default records on file. */
function givenShieldOwner(scenario: DbScenario = {}) {
  const harness = makeDb(scenario);
  givenAccount(harness.db, { plan: "shield" });
  return harness;
}

/** A free owner with the SAME records — only the entitlement differs. */
function givenFreeOwner(scenario: DbScenario = {}) {
  const harness = makeDb(scenario);
  givenAccount(harness.db, { plan: "free" });
  return harness;
}

// ---------------------------------------------------------------------------
// Response helpers
// ---------------------------------------------------------------------------

/** The handler takes no request — this cast proves the body cannot reach it. */
const postWithBody = POST as unknown as (request: Request) => Promise<Response>;

function requestWith(body: unknown): Request {
  return new Request("https://request-host.test/api/audit-file", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function preview(): Promise<AuditFilePreview> {
  return (await (await GET()).json()) as AuditFilePreview;
}

async function exported(): Promise<Partial<AuditFileExport> & { error?: string }> {
  return (await (await POST()).json()) as Partial<AuditFileExport> & { error?: string };
}

/** Every string anywhere in the payload — the free-tier leak hunt. */
function allStrings(value: unknown, found: string[] = []): string[] {
  if (typeof value === "string") found.push(value);
  else if (Array.isArray(value)) value.forEach((item) => allStrings(item, found));
  else if (value && typeof value === "object") {
    Object.values(value).forEach((item) => allStrings(item, found));
  }
  return found;
}

/** The data rows of the export's cover-index table. */
function coverIndexRows(content: string): string[] {
  const section = content.split("## Cover index")[1]?.split("## Signed acknowledgments")[0] ?? "";
  return section
    .split("\n")
    .filter((line) => line.startsWith("|"))
    .slice(2); // drop the header row and the `| --- |` separator
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
// b-12 criterion: "The export includes every signed notice with signer name,
// timestamp, and the frozen notice text"
// ===========================================================================

describe("POST /api/audit-file — the signed acknowledgments", () => {
  it("The export includes every signed notice with signer name, timestamp, and the frozen notice text", async () => {
    givenShieldOwner({
      data: {
        signatures: [
          ...SIGNATURES,
          {
            id: "sig-2",
            notice_id: "notice-2",
            signer_name: "Devon Achebe",
            signed_at: "2026-02-04T18:05:00.000Z",
            notice_text_snapshot: `${FROZEN_TEXT}\nSigned by Devon.`,
          },
        ],
      },
    });

    const body = await exported();

    expect(typeof body.content).toBe("string");
    const content = body.content as string;
    for (const signature of ["Marisol Vega", "Devon Achebe"]) {
      expect(content).toContain(signature);
    }
    expect(content).toContain("2026-02-03T14:22:00.000Z");
    expect(content).toContain("2026-02-04T18:05:00.000Z");
    // The whole frozen copy, not a summary of it.
    expect(content).toContain(FROZEN_TEXT);
    expect(content).toContain("Signed by Devon.");
  });

  it("prints the frozen snapshot rather than the notice text as it reads today", async () => {
    // `notices.notice_text` can be regenerated when a state rule changes. The
    // export is evidence of what was ACKNOWLEDGED, so it may only ever come
    // from `signatures.notice_text_snapshot`.
    const { forTable } = givenShieldOwner();

    const body = await exported();

    expect(body.content).toContain(FROZEN_TEXT);
    expect(body.content).not.toContain(REGENERATED_TEXT);
    expect(forTable("notices")[0].columns).not.toContain("notice_text");
    expect(forTable("signatures")[0].columns).toContain("notice_text_snapshot");
  });

  it("returns a dated filename and a markdown content type", async () => {
    givenShieldOwner();

    const body = await exported();

    expect(body.filename).toMatch(/^tipguard-audit-file-\d{4}-\d{2}-\d{2}\.md$/);
    expect(body.contentType).toContain("text/markdown");
  });

  it("assembles a file for an owner with no signed notices yet", async () => {
    // A restaurant that has sent notices but collected no signatures still
    // needs the roster half of the file — an empty export would read as "no
    // records exist" when the records are simply unsigned.
    givenShieldOwner({ data: { signatures: [] } });

    const response = await POST();
    const body = (await response.json()) as Partial<AuditFileExport>;

    expect(response.status).toBe(200);
    expect(body.counts).toMatchObject({ signed_notice_count: 0, employee_count: 3 });
    expect(body.content).toContain("Marisol Vega");
    expect(body.content).toMatch(/no signed acknowledgments/i);
  });
});

// ===========================================================================
// b-12 criterion: "The export includes a cover index listing employees, notice
// status, and the state rule version applied"
// ===========================================================================

describe("POST /api/audit-file — the cover index", () => {
  it("The export includes a cover index listing employees, notice status, and the state rule version applied", async () => {
    givenShieldOwner();

    const content = (await exported()).content as string;
    const rows = coverIndexRows(content);

    expect(rows).toHaveLength(EMPLOYEES.length);
    expect(rows[0]).toContain("Marisol Vega");
    expect(rows[0]).toContain("signed");
    expect(rows[0]).toContain("tx-2026.01");
    expect(rows[1]).toContain("Devon Achebe");
    expect(rows[1]).toContain("sent");
    expect(content).toContain("Rule versions applied: tx-2026.01");
  });

  it("keeps an employee with no notice on the index instead of dropping them", async () => {
    // The gap is the finding. An employee who is missing from the roster looks
    // like an employee who does not exist.
    givenShieldOwner();

    const rows = coverIndexRows((await exported()).content as string);

    expect(rows[2]).toContain("Priya Raman");
    expect(rows[2]).toContain("none");
  });

  it("does not contradict the signed-notice index when an employee has two rule versions", async () => {
    // `notices` is unique on (employee_id, rule_version), so a state rule
    // update leaves an employee with a signed notice AND a fresh draft. A cover
    // index that reports the draft says the employee never signed, two
    // paragraphs above their signature — the one thing an evidence file may
    // never do.
    givenShieldOwner({
      data: {
        notices: [
          ...NOTICES,
          {
            id: "notice-3",
            employee_id: "emp-1",
            state: "TX",
            rule_version: "tx-2026.07",
            status: "draft",
            sent_at: null,
            created_at: "2026-07-01T09:00:00.000Z",
            notice_text: REGENERATED_TEXT,
          },
        ],
      },
    });

    const body = (await (await GET()).json()) as AuditFilePreview;

    const signedEmployees = new Set(body.signedNotices.map((entry) => entry.employeeName));
    for (const entry of body.coverIndex) {
      if (signedEmployees.has(entry.employeeName)) {
        expect(entry.noticeStatus).toBe("signed");
        expect(entry.signedAt).toBe("2026-02-03T14:22:00.000Z");
        expect(entry.ruleVersion).toBe("tx-2026.01");
      }
    }
  });

  it("keeps one table row per employee when a name carries the column delimiter", async () => {
    // Names come out of a hand-edited roster CSV. A raw `|` in a markdown table
    // cell silently splits the row into different columns, so an auditor reads
    // one employee's rule version against another employee's name.
    givenShieldOwner({
      data: {
        employees: [{ ...EMPLOYEES[0], name: "Vega | Marisol" }, EMPLOYEES[1], EMPLOYEES[2]],
      },
    });

    const rows = coverIndexRows((await exported()).content as string);

    expect(rows).toHaveLength(EMPLOYEES.length);
    for (const row of rows) {
      // Seven columns => eight unescaped delimiters => nine split parts.
      expect(row.split(/(?<!\\)\|/)).toHaveLength(9);
    }
    expect(rows[0]).toContain("Marisol");
  });
});

// ===========================================================================
// b-12 criterion: "Free-tier accounts see a locked preview with an upgrade
// prompt instead of a download"
//
// The gating boundary. Everything below asserts the paid content is ABSENT,
// not merely that one field is null.
// ===========================================================================

describe("/api/audit-file — the paywall", () => {
  it("Free-tier accounts see a locked preview with an upgrade prompt instead of a download", async () => {
    givenFreeOwner();

    const locked = await preview();
    const response = await POST();
    const body = (await response.json()) as Partial<AuditFileExport> & { error?: string };

    // The preview is LOCKED, not withheld: the owner can see their file is
    // real and complete before being asked to pay for it.
    expect(locked.plan).toBe("free");
    expect(locked.coverIndex).toHaveLength(EMPLOYEES.length);
    expect(locked.signedNotices).toHaveLength(SIGNATURES.length);
    expect(locked.signedNotices.every((entry) => entry.noticeText === null)).toBe(true);
    expect(locked.signedNotices[0].signerName).toBe("Marisol Vega");
    // …and the download itself is the paid part.
    expect(response.status).toBe(402);
    expect(body.error).toBe("upgrade_required");
    expect(body.content).toBeUndefined();
    expect(body.filename).toBeUndefined();
  });

  it("never leaks the frozen notice text anywhere in a free-tier payload", async () => {
    // Not "noticeText is null" — the paid text must not survive under any key,
    // at any depth, in either response.
    givenFreeOwner();

    const previewResponse = await GET();
    const previewText = await previewResponse.text();
    const exportResponse = await POST();
    const exportText = await exportResponse.text();

    for (const raw of [previewText, exportText]) {
      expect(raw).not.toContain(FROZEN_FRAGMENT);
      expect(raw).not.toContain("2.13");
      for (const value of allStrings(JSON.parse(raw))) {
        expect(value).not.toContain(FROZEN_FRAGMENT);
      }
    }
  });

  it("assembles nothing at all for a free-tier export request", async () => {
    // The gate has to close before the work, not after: a route that assembled
    // first and filtered later is one early return away from shipping the file.
    const { calls } = givenFreeOwner();

    await POST();

    expect(calls).toEqual([]);
  });

  it("reads the entitlement from the account row, never from the request", async () => {
    givenFreeOwner();

    const response = await postWithBody(requestWith({ plan: "shield", account_id: OTHER_ACCOUNT_ID }));

    expect(response.status).toBe(402);
  });

  it("does not treat a lapsed subscriber's leftover Stripe id as an entitlement", async () => {
    // `plan` is what the webhook writes on payment; a stripe_customer_id only
    // says this owner once had a checkout session.
    const harness = makeDb();
    givenAccount(harness.db, { plan: "free", stripe_customer_id: "cus_expired" });

    expect((await POST()).status).toBe(402);
  });

  it("unlocks the frozen text in the preview for a paid owner", async () => {
    // The same preview endpoint, the same records — only the entitlement moved.
    givenShieldOwner();

    const unlocked = await preview();

    expect(unlocked.plan).toBe("shield");
    expect(unlocked.signedNotices[0].noticeText).toBe(FROZEN_TEXT);
  });

  it("shows a free owner the real counts so the locked file is visibly theirs", async () => {
    givenFreeOwner();

    const locked = await preview();

    expect(locked.counts).toEqual({
      employee_count: 3,
      signed_notice_count: 1,
      open_violation_count: 2,
    });
    expect(locked.ruleVersions).toEqual(["tx-2026.01"]);
  });
});

// ===========================================================================
// b-12 criterion: "audit_file_exported fires with employee_count,
// signed_notice_count, and open_violation_count"
//
// The event fires client-side from this response (audit-file/export-panel.tsx),
// so the counts the route returns ARE the h-06 signal.
// ===========================================================================

describe("audit_file_exported — the h-06 signal", () => {
  it("audit_file_exported fires with employee_count, signed_notice_count, and open_violation_count", async () => {
    givenShieldOwner();

    const counts = (await exported()).counts as AuditFileCounts;

    // Exactly the computation export-panel.tsx performs on a successful build.
    trackAuditFileExported({
      employee_count: counts.employee_count,
      signed_notice_count: counts.signed_notice_count,
      open_violation_count: counts.open_violation_count,
    });

    expect(track).toHaveBeenCalledTimes(1);
    const [event, properties] = track.mock.calls[0] as [string, Record<string, unknown>];
    expect(event).toBe("audit_file_exported");
    expect(properties).toMatchObject({
      employee_count: 3,
      signed_notice_count: 1,
      open_violation_count: 2,
      funnel_stage: "monetize",
    });
  });

  it("counts what the file actually contains", async () => {
    givenShieldOwner({ data: { violations: [], signatures: [] } });

    const body = await exported();

    expect(body.counts).toEqual({
      employee_count: 3,
      signed_notice_count: 0,
      open_violation_count: 0,
    });
    expect(coverIndexRows(body.content as string)).toHaveLength(3);
  });

  it("counts only open findings, not resolved ones", async () => {
    // The resolved log belongs in the file; the OPEN count is what the owner
    // is being told still needs work.
    const { forTable } = givenShieldOwner();

    await POST();

    expect(forTable("violations")[0].filters).toContainEqual(["status", "open"]);
  });
});

// ===========================================================================
// Tenant scoping — an audit file assembled from another restaurant's records
// would be a catastrophic disclosure
// ===========================================================================

describe("/api/audit-file — tenant scoping", () => {
  it("scopes every read to the caller's own account", async () => {
    const { calls } = givenShieldOwner();

    await POST();

    expect(calls.map((call) => call.table).sort()).toEqual([
      "employees",
      "notices",
      "signatures",
      "violations",
    ]);
    for (const call of calls) {
      expect(call.filters).toContainEqual(["account_id", ACCOUNT.id]);
    }
  });

  it("scopes the preview the same way as the export", async () => {
    const { calls } = givenFreeOwner();

    await GET();

    expect(calls).toHaveLength(4);
    for (const call of calls) {
      expect(call.filters).toContainEqual(["account_id", ACCOUNT.id]);
    }
  });

  it("never reads by an identifier that came from the caller", async () => {
    const { calls } = givenShieldOwner();

    await postWithBody(requestWith({ account_id: OTHER_ACCOUNT_ID }));

    expect(JSON.stringify(calls)).not.toContain(OTHER_ACCOUNT_ID);
  });
});

// ===========================================================================
// The auth boundary
// ===========================================================================

describe("/api/audit-file — the auth boundary", () => {
  it("returns 401 to a caller with no verified session on both verbs", async () => {
    resolveAccount.mockResolvedValue({ ok: false, reason: "unauthenticated" });

    expect((await GET()).status).toBe(401);
    expect((await POST()).status).toBe(401);
  });

  it("returns an empty preview, not an error, for an owner with nothing on file", async () => {
    // A brand new account has no `accounts` row until its first write. The
    // audit file page must render the empty state, not a failure.
    resolveAccount.mockResolvedValue({ ok: false, reason: "no_account" });

    const response = await GET();
    const body = (await response.json()) as AuditFilePreview;

    expect(response.status).toBe(200);
    expect(body).toMatchObject({
      plan: "free",
      coverIndex: [],
      signedNotices: [],
      counts: { employee_count: 0, signed_notice_count: 0, open_violation_count: 0 },
    });
  });

  it("refuses the export with upgrade_required when there is no account row", async () => {
    // No account row means no subscription, so this is the paywall, not a 404.
    resolveAccount.mockResolvedValue({ ok: false, reason: "no_account" });

    const response = await POST();
    const body = (await response.json()) as { error?: string; content?: string };

    expect(response.status).toBe(402);
    expect(body.error).toBe("upgrade_required");
    expect(body.content).toBeUndefined();
  });

  it("returns 503 on both verbs when the database or service-role key is unavailable", async () => {
    resolveAccount.mockResolvedValue({ ok: false, reason: "unavailable" });

    expect((await GET()).status).toBe(503);
    expect((await POST()).status).toBe(503);
  });

  it("never returns file content on a failed resolution", async () => {
    for (const reason of ["unauthenticated", "no_account", "unavailable"] as const) {
      resolveAccount.mockResolvedValue({ ok: false, reason });

      const text = await (await POST()).text();

      expect(text).not.toContain(FROZEN_FRAGMENT);
      expect(JSON.parse(text).content).toBeUndefined();
    }
  });

  it("does not provision an account row to build a file", async () => {
    givenShieldOwner();

    await POST();

    expect(resolveAccount).toHaveBeenCalledWith();
  });
});

// ===========================================================================
// Infrastructure failures fail closed — a partial audit file is a false record
// ===========================================================================

describe("/api/audit-file — a partial file is never returned", () => {
  it("returns 500 without content when any single table read fails", async () => {
    for (const table of ["employees", "notices", "signatures", "violations"] as const) {
      givenShieldOwner({ errorOn: table });

      const response = await POST();
      const body = (await response.json()) as { content?: string; counts?: AuditFileCounts };

      expect(response.status).toBe(500);
      expect(body.content).toBeUndefined();
      expect(body.counts).toBeUndefined();
    }
  });

  it("fails the preview rather than showing an incomplete roster", async () => {
    // A cover index missing the employees whose read failed reads as "these
    // people are not on staff".
    givenFreeOwner({ errorOn: "employees" });

    expect((await GET()).status).toBe(500);
  });

  it("does not leak the database error text to the caller", async () => {
    givenShieldOwner({ errorOn: "signatures" });

    const text = await (await POST()).text();

    expect(text).not.toContain("db.internal");
    expect(text).not.toContain("relation");
  });
});
