// Server-side resolution of a signing link (behavior b-07).
//
// This module runs ONLY on the server — it imports `node:crypto` (via
// `signing-token.ts`) and the Supabase service-role client, neither of which
// may ever reach the browser bundle. It is imported by the `/sign` server
// component and nothing else.
//
// Why the service-role client: the signer has no session, so RLS (which scopes
// every row to the owning account) would reject an anon read. Authorization
// here is the token itself — we look up by SHA-256 digest, and a miss is
// indistinguishable from a wrong guess. Nothing about the notice is returned
// unless the digest matches a live row.
//
// The four outcomes below map 1:1 to behavior b-07's first test:
// "A valid unexpired token renders the exact notice text that was sent; an
//  invalid, expired, or already-used token renders an error state and cannot
//  sign."

import type { SupabaseClient } from "@supabase/supabase-js";
import { createServiceRoleClient } from "@/lib/supabase-server";
import { generateEmployeeNotice } from "@/lib/notice-generator";
import type {
  AccountRow,
  EmployeeRow,
  NoticeRow,
  SignatureRow,
  SigningTokenRow,
} from "@/lib/types";
import { buildRecordId } from "./format";
import { hashSigningToken, isWellFormedSigningToken } from "./signing-token";

/** Everything the page needs to render a live, signable notice. */
export interface ReadySigningLink {
  status: "ready";
  /** Raw token, echoed back so the form can re-present it for server re-validation. */
  token: string;
  noticeId: string;
  recordId: string;
  employeeName: string;
  employerName: string;
  state: string;
  ruleVersion: string;
  cashWagePaid: number;
  tipCreditClaimed: boolean;
  /** The EXACT text that was sent. Rendered verbatim, never re-generated. */
  noticeText: string;
  /** When the link was minted — used for the `hours_to_sign` analytics property. */
  sentAt: string;
  expiresAt: string;
  isDemo: boolean;
}

export type SigningLinkState =
  | ReadySigningLink
  | { status: "missing_token" }
  | { status: "not_found" }
  | { status: "expired"; employerName: string; expiresAt: string }
  | {
      status: "already_signed";
      recordId: string;
      employerName: string;
      employeeName: string;
      state: string;
      ruleVersion: string;
      signerName: string | null;
      signedAt: string | null;
      /** Frozen copy taken at signature time — NOT the current notice row. */
      noticeTextSnapshot: string | null;
    }
  | { status: "unavailable" };

function isDemoMode(): boolean {
  return (
    process.env.DEMO_MODE === "true" ||
    process.env.NEXT_PUBLIC_DEMO_MODE === "true"
  );
}

// --- Demo-mode fixtures -----------------------------------------------------
// Reachable only when DEMO_MODE is on (the app refuses DEMO_MODE on Vercel —
// see supabase-server.ts). These exist so the page, its error branches, and the
// smoke tests are all exercisable without a seeded database. Every fixture is
// visibly labelled in the UI as demo data.

const DEMO_EMPLOYER = "The Copper Rail";
const DEMO_EMPLOYEE = "Marisol Vega";
const DEMO_NOTICE_ID = "demo-notice-8f2c";

export const DEMO_SIGNING_TOKENS = {
  ready: "demo-notice-ready",
  expired: "demo-notice-expired",
  signed: "demo-notice-signed",
  invalid: "demo-notice-invalid",
} as const;

function demoNoticeText(): string {
  const generated = generateEmployeeNotice({
    employeeName: DEMO_EMPLOYEE,
    employerName: DEMO_EMPLOYER,
    state: "TX",
    cashWagePaid: 2.13,
  });
  if ("error" in generated) {
    // Unreachable for TX, which is in the rule library — but never fabricate a
    // notice body if the generator ever declines to produce one.
    return "";
  }
  return generated.noticeText;
}

function demoLink(token: string): SigningLinkState {
  const now = Date.now();
  if (token === DEMO_SIGNING_TOKENS.invalid) return { status: "not_found" };

  if (token === DEMO_SIGNING_TOKENS.expired) {
    return {
      status: "expired",
      employerName: DEMO_EMPLOYER,
      expiresAt: new Date(now - 1000 * 60 * 60 * 72).toISOString(),
    };
  }

  if (token === DEMO_SIGNING_TOKENS.signed) {
    const signedAt = new Date(now - 1000 * 60 * 60 * 26).toISOString();
    return {
      status: "already_signed",
      recordId: buildRecordId(DEMO_NOTICE_ID, new Date(now - 1000 * 60 * 60 * 30).toISOString()),
      employerName: DEMO_EMPLOYER,
      employeeName: DEMO_EMPLOYEE,
      state: "TX",
      ruleVersion: "2026.1",
      signerName: DEMO_EMPLOYEE,
      signedAt,
      noticeTextSnapshot: demoNoticeText(),
    };
  }

  const sentAt = new Date(now - 1000 * 60 * 60 * 4).toISOString();
  return {
    status: "ready",
    token,
    noticeId: DEMO_NOTICE_ID,
    recordId: buildRecordId(DEMO_NOTICE_ID, sentAt),
    employeeName: DEMO_EMPLOYEE,
    employerName: DEMO_EMPLOYER,
    state: "TX",
    ruleVersion: "2026.1",
    cashWagePaid: 2.13,
    tipCreditClaimed: true,
    noticeText: demoNoticeText(),
    sentAt,
    expiresAt: new Date(now + 1000 * 60 * 60 * 24 * 10).toISOString(),
    isDemo: true,
  };
}

// --- Live resolution --------------------------------------------------------

type TokenLookup = Pick<
  SigningTokenRow,
  "id" | "notice_id" | "expires_at" | "used_at" | "created_at"
>;
type NoticeLookup = Pick<
  NoticeRow,
  | "id"
  | "account_id"
  | "employee_id"
  | "state"
  | "rule_version"
  | "cash_wage_paid"
  | "tip_credit_claimed"
  | "notice_text"
  | "status"
  | "created_at"
>;

export async function loadSigningLink(
  rawToken: string | undefined
): Promise<SigningLinkState> {
  const token = typeof rawToken === "string" ? rawToken.trim() : "";
  const demo = isDemoMode();

  if (!token) {
    // In demo mode a bare /sign renders the sample notice so the page is
    // reviewable without a seeded database. In production it is an error.
    return demo ? demoLink(DEMO_SIGNING_TOKENS.ready) : { status: "missing_token" };
  }
  if (!isWellFormedSigningToken(token)) return { status: "not_found" };
  if (demo) return demoLink(token);

  let db: SupabaseClient;
  try {
    db = createServiceRoleClient() as unknown as SupabaseClient;
  } catch {
    // SUPABASE_SERVICE_ROLE_KEY absent — a deployment configuration problem,
    // not a bad token. Say so rather than telling the employee their link is
    // invalid (which would send them back to their employer for nothing).
    return { status: "unavailable" };
  }

  try {
    const tokenResult = await db
      .from("signing_tokens")
      .select("id, notice_id, expires_at, used_at, created_at")
      .eq("token_hash", hashSigningToken(token))
      .maybeSingle();
    if (tokenResult.error) return { status: "unavailable" };
    const tokenRow = tokenResult.data as TokenLookup | null;
    if (!tokenRow) return { status: "not_found" };

    const noticeResult = await db
      .from("notices")
      .select(
        "id, account_id, employee_id, state, rule_version, cash_wage_paid, tip_credit_claimed, notice_text, status, created_at"
      )
      .eq("id", tokenRow.notice_id)
      .maybeSingle();
    if (noticeResult.error) return { status: "unavailable" };
    const notice = noticeResult.data as NoticeLookup | null;
    if (!notice) return { status: "not_found" };

    const [employeeResult, accountResult] = await Promise.all([
      db.from("employees").select("name").eq("id", notice.employee_id).maybeSingle(),
      db.from("accounts").select("restaurant_name").eq("id", notice.account_id).maybeSingle(),
    ]);
    const employeeName =
      (employeeResult.data as Pick<EmployeeRow, "name"> | null)?.name ?? "";
    const employerName =
      (accountResult.data as Pick<AccountRow, "restaurant_name"> | null)
        ?.restaurant_name ?? "your employer";
    const recordId = buildRecordId(notice.id, notice.created_at);

    // Already consumed → show the completed record, never a signable form.
    if (tokenRow.used_at || notice.status === "signed") {
      const signatureResult = await db
        .from("signatures")
        .select("signer_name, signed_at, notice_text_snapshot")
        .eq("notice_id", notice.id)
        .order("signed_at", { ascending: false })
        .limit(1)
        .maybeSingle();
      const signature = signatureResult.data as Pick<
        SignatureRow,
        "signer_name" | "signed_at" | "notice_text_snapshot"
      > | null;
      return {
        status: "already_signed",
        recordId,
        employerName,
        employeeName,
        state: notice.state,
        ruleVersion: notice.rule_version,
        signerName: signature?.signer_name ?? null,
        signedAt: signature?.signed_at ?? tokenRow.used_at ?? null,
        noticeTextSnapshot: signature?.notice_text_snapshot ?? null,
      };
    }

    const expiresAt = new Date(tokenRow.expires_at);
    if (Number.isNaN(expiresAt.getTime()) || expiresAt.getTime() <= Date.now()) {
      return { status: "expired", employerName, expiresAt: tokenRow.expires_at };
    }

    return {
      status: "ready",
      token,
      noticeId: notice.id,
      recordId,
      employeeName,
      employerName,
      state: notice.state,
      ruleVersion: notice.rule_version,
      cashWagePaid: Number(notice.cash_wage_paid),
      tipCreditClaimed: Boolean(notice.tip_credit_claimed),
      noticeText: notice.notice_text,
      sentAt: tokenRow.created_at,
      expiresAt: tokenRow.expires_at,
      isDemo: false,
    };
  } catch {
    return { status: "unavailable" };
  }
}
