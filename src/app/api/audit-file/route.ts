import { NextResponse } from "next/server";
import { resolveAccount } from "@/lib/api-auth";
import { COUNSEL_REVIEW_DISCLAIMER } from "@/lib/notice-generator";
import type {
  AuditFileCounts,
  AuditFileExport,
  AuditFilePreview,
  CoverIndexEntry,
  SignedNoticeEntry,
} from "@/app/audit-file/audit-file-contract";
import type { EmployeeRow, NoticeRow, SignatureRow } from "@/lib/types";
import type { SupabaseClient } from "@supabase/supabase-js";

export const dynamic = "force-dynamic";

/**
 * b-12 — the audit file.
 *
 * Free tier gets the FULL cover index and the FULL signed-notice index with
 * `noticeText: null` on every entry. The preview is locked, not withheld: an
 * owner must be able to see that their file is real and complete before being
 * asked to pay for the export of it. The frozen notice text and the assembled
 * download are the paid part.
 *
 * Every signed notice is rendered from `signatures.notice_text_snapshot` — the
 * copy frozen at signature time — never re-rendered from the current template.
 * An export that re-generated the text would be a summary; this one is
 * evidence.
 */

interface AuditFileData {
  plan: "free" | "shield";
  generatedAt: string;
  ruleVersions: string[];
  counts: AuditFileCounts;
  coverIndex: CoverIndexEntry[];
  signedNotices: SignedNoticeEntry[];
}

async function assemble(
  db: SupabaseClient,
  accountId: string,
  plan: "free" | "shield",
  includeNoticeText: boolean
): Promise<AuditFileData | null> {
  const [employeesResult, noticesResult, signaturesResult, violationsResult] =
    await Promise.all([
      db
        .from("employees")
        .select("id, name, email, role, state")
        .eq("account_id", accountId)
        .order("name", { ascending: true }),
      db
        .from("notices")
        .select("id, employee_id, state, rule_version, status, sent_at, created_at")
        .eq("account_id", accountId),
      db
        .from("signatures")
        .select("id, notice_id, signer_name, signed_at, notice_text_snapshot")
        .eq("account_id", accountId)
        .order("signed_at", { ascending: true }),
      db
        .from("violations")
        .select("id")
        .eq("account_id", accountId)
        .eq("status", "open"),
    ]);

  if (
    employeesResult.error ||
    noticesResult.error ||
    signaturesResult.error ||
    violationsResult.error
  ) {
    console.error(
      "[audit-file] Supabase error:",
      employeesResult.error ??
        noticesResult.error ??
        signaturesResult.error ??
        violationsResult.error
    );
    return null;
  }

  const employees = (employeesResult.data ?? []) as Pick<
    EmployeeRow,
    "id" | "name" | "email" | "role" | "state"
  >[];
  const notices = (noticesResult.data ?? []) as Pick<
    NoticeRow,
    "id" | "employee_id" | "state" | "rule_version" | "status" | "sent_at" | "created_at"
  >[];
  const signatures = (signaturesResult.data ?? []) as Pick<
    SignatureRow,
    "id" | "notice_id" | "signer_name" | "signed_at" | "notice_text_snapshot"
  >[];

  const employeeById = new Map(employees.map((employee) => [employee.id, employee]));
  const noticeById = new Map(notices.map((notice) => [notice.id, notice]));
  const signatureByNotice = new Map(
    signatures.map((signature) => [signature.notice_id, signature])
  );

  // `notices` is UNIQUE on (employee_id, rule_version), so a state rule update
  // leaves an employee holding a SIGNED notice for the old version and a fresh
  // draft for the new one. Keeping whichever row arrived last would print
  // "draft, never signed" on the cover index two paragraphs above that
  // employee's signature — the one thing an evidence file may never do. Rank
  // the notice that carries the most acknowledgment, newest first on a tie.
  const STATUS_RANK: Record<string, number> = { signed: 3, sent: 2, draft: 1 };
  const noticeByEmployee = new Map<string, (typeof notices)[number]>();
  for (const notice of notices) {
    const held = noticeByEmployee.get(notice.employee_id);
    if (!held || outranks(notice, held)) noticeByEmployee.set(notice.employee_id, notice);
  }

  function outranks(
    candidate: (typeof notices)[number],
    held: (typeof notices)[number]
  ): boolean {
    const byStatus =
      (STATUS_RANK[candidate.status] ?? 0) - (STATUS_RANK[held.status] ?? 0);
    if (byStatus !== 0) return byStatus > 0;
    return (
      Date.parse(candidate.created_at ?? "") > Date.parse(held.created_at ?? "")
    );
  }

  const coverIndex: CoverIndexEntry[] = employees.map((employee) => {
    const notice = noticeByEmployee.get(employee.id);
    const signature = notice ? signatureByNotice.get(notice.id) : undefined;
    return {
      employeeId: employee.id,
      employeeName: employee.name,
      role: employee.role,
      state: employee.state,
      noticeStatus: notice ? notice.status : "none",
      ruleVersion: notice?.rule_version ?? null,
      sentAt: notice?.sent_at ?? null,
      signedAt: signature?.signed_at ?? null,
    };
  });

  const signedNotices: SignedNoticeEntry[] = signatures.map((signature) => {
    const notice = noticeById.get(signature.notice_id);
    const employee = notice ? employeeById.get(notice.employee_id) : undefined;
    return {
      noticeId: signature.notice_id,
      employeeName: employee?.name ?? "Unknown employee",
      signerName: signature.signer_name,
      signedAt: signature.signed_at,
      state: notice?.state ?? "",
      ruleVersion: notice?.rule_version ?? "",
      // Free tier: the index is complete, the frozen text is locked.
      noticeText: includeNoticeText ? signature.notice_text_snapshot : null,
    };
  });

  const ruleVersions = Array.from(
    new Set(notices.map((notice) => notice.rule_version).filter(Boolean))
  ).sort();

  return {
    plan,
    generatedAt: new Date().toISOString(),
    ruleVersions,
    counts: {
      employee_count: employees.length,
      signed_notice_count: signatures.length,
      open_violation_count: (violationsResult.data ?? []).length,
    },
    coverIndex,
    signedNotices,
  };
}

/** GET — the locked-or-unlocked preview. */
export async function GET() {
  const resolved = await resolveAccount();
  if (!resolved.ok) {
    if (resolved.reason === "unauthenticated") {
      return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
    }
    if (resolved.reason === "no_account") {
      // Signed in, nothing filed yet: an empty file, not an error.
      return NextResponse.json({
        plan: "free",
        generatedAt: new Date().toISOString(),
        ruleVersions: [],
        counts: { employee_count: 0, signed_notice_count: 0, open_violation_count: 0 },
        coverIndex: [],
        signedNotices: [],
      } satisfies AuditFilePreview);
    }
    return NextResponse.json({ error: "Service unavailable" }, { status: 503 });
  }

  const { account, db } = resolved.ctx;
  const data = await assemble(db, account.id, account.plan, account.plan === "shield");
  if (!data) {
    return NextResponse.json({ error: "Could not assemble your file" }, { status: 500 });
  }

  return NextResponse.json(data satisfies AuditFilePreview);
}

/** POST — build the dated export. Shield only. */
export async function POST() {
  const resolved = await resolveAccount();
  if (!resolved.ok) {
    if (resolved.reason === "unauthenticated") {
      return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
    }
    if (resolved.reason === "no_account") {
      return NextResponse.json({ error: "upgrade_required" }, { status: 402 });
    }
    return NextResponse.json({ error: "Service unavailable" }, { status: 503 });
  }

  const { account, db } = resolved.ctx;

  // The paywall is enforced HERE, on the server, from the account row the
  // Stripe webhook writes — not from anything the client sent.
  if (account.plan !== "shield") {
    return NextResponse.json({ error: "upgrade_required" }, { status: 402 });
  }

  const data = await assemble(db, account.id, "shield", true);
  if (!data) {
    return NextResponse.json({ error: "Could not assemble your file" }, { status: 500 });
  }

  const stamp = data.generatedAt.slice(0, 10);
  const content = renderExport(
    account.restaurant_name || "Your restaurant",
    account.home_state || "—",
    data
  );

  return NextResponse.json({
    filename: `tipguard-audit-file-${stamp}.md`,
    contentType: "text/markdown;charset=utf-8",
    content,
    counts: data.counts,
  } satisfies AuditFileExport);
}

/**
 * One cover-index cell. Employee names and roles come out of a hand-edited
 * roster CSV, and a raw `|` splits a markdown row into different columns — an
 * auditor would read one employee's rule version against another's name.
 */
function cell(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return value.replace(/\r?\n|\r/g, " ").replace(/\|/g, "\\|");
}

/**
 * One interpolated value outside the cover-index table.
 *
 * `signerName` is the only field in this document typed by someone other than
 * the account owner — the employee enters it at /sign. A raw newline lets that
 * employee close the current section and open a fabricated
 * `### Name — signed <date>` block, and a raw backtick unbalances the fenced
 * notice body so genuine acknowledgments render as prose. Either one forges
 * the evidence this export exists to be trusted as, so every interpolation in
 * the acknowledgment section is flattened to a single line with fences
 * neutralised.
 */
function inline(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return value.replace(/\r?\n|\r/g, " ").replace(/`/g, "'");
}

/**
 * The frozen notice snapshot, rendered inside a fenced block. The text is
 * server-generated, but it is concatenated with a fence we control, so a
 * defensive strip of any embedded fence keeps the block balanced no matter
 * what a future generator emits.
 */
function fencedBody(value: string | null | undefined): string {
  return (value ?? "").replace(/^```/gm, "'''");
}

function renderExport(
  restaurantName: string,
  homeState: string,
  data: AuditFileData
): string {
  const lines: string[] = [];

  lines.push(`# TipGuard audit file — ${restaurantName}`);
  lines.push("");
  lines.push(`Generated: ${data.generatedAt}`);
  lines.push(`Home state: ${homeState}`);
  lines.push(
    `Rule versions applied: ${data.ruleVersions.length ? data.ruleVersions.join(", ") : "—"}`
  );
  lines.push(
    `Employees: ${data.counts.employee_count} · Signed notices: ${data.counts.signed_notice_count} · Open findings: ${data.counts.open_violation_count}`
  );
  lines.push("");
  lines.push(`> ${COUNSEL_REVIEW_DISCLAIMER}`);
  lines.push("");

  lines.push("## Cover index");
  lines.push("");
  lines.push("| Employee | Role | State | Notice status | Rule version | Sent | Signed |");
  lines.push("| --- | --- | --- | --- | --- | --- | --- |");
  for (const entry of data.coverIndex) {
    lines.push(
      `| ${cell(entry.employeeName)} | ${cell(entry.role)} | ${cell(entry.state)} | ${cell(
        entry.noticeStatus
      )} | ${cell(entry.ruleVersion)} | ${cell(entry.sentAt)} | ${cell(entry.signedAt)} |`
    );
  }
  if (data.coverIndex.length === 0) lines.push("| — | — | — | — | — | — | — |");
  lines.push("");

  lines.push("## Signed acknowledgments");
  lines.push("");
  if (data.signedNotices.length === 0) {
    lines.push("_No signed acknowledgments on file yet._");
  }
  for (const signed of data.signedNotices) {
    lines.push(`### ${inline(signed.employeeName)} — signed ${inline(signed.signedAt)}`);
    lines.push("");
    lines.push(`- Signer name (typed): ${inline(signed.signerName)}`);
    lines.push(`- Timestamp (UTC): ${inline(signed.signedAt)}`);
    lines.push(`- State / rule version: ${inline(signed.state)} / ${inline(signed.ruleVersion)}`);
    lines.push("");
    lines.push("```text");
    // The frozen copy taken at signature time. NOT re-rendered.
    lines.push(fencedBody(signed.noticeText));
    lines.push("```");
    lines.push("");
  }

  return lines.join("\n");
}
