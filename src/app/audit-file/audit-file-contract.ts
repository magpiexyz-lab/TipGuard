import type { NoticeStatus, PlanTier } from "@/lib/types";

/**
 * Contract with `src/app/api/audit-file/route.ts` — behavior b-12.
 *
 * ⚠️ The route is owned by scaffold-wire (STATE 14) and does not exist yet.
 * This page is written against the contract below; scaffold-wire should
 * implement it verbatim.
 *
 * ── GET /api/audit-file ───────────────────────────────────────────────────
 * Owner-scoped by session + RLS. Assembles the *preview* of the file.
 *   200 AuditFilePreview
 *   401 { error: "unauthenticated" }        — no session
 *   5xx { error: string }
 *
 * On `plan === "free"` the route MUST still return the full cover index and
 * the signed-notice index, with `noticeText: null` on every signed notice —
 * the preview is locked, not withheld. b-12's third test requires a locked
 * preview with an upgrade prompt, never a broken download.
 *
 * ── POST /api/audit-file ──────────────────────────────────────────────────
 * Builds the assembled, dated export. Body: `{}`.
 *   200 AuditFileExport                      — `plan === "shield"` only
 *   402 { error: "upgrade_required" }        — free tier
 *   401 { error: "unauthenticated" }
 *
 * `content` is the complete export body: a cover index listing every employee
 * with notice status and the state rule version applied, followed by every
 * signed notice with its signer name, UTC timestamp, and the frozen notice
 * text captured at signature time (never re-rendered from the current
 * template — see `signatures.notice_text_snapshot`).
 */

export interface AuditFileCounts {
  employee_count: number;
  signed_notice_count: number;
  open_violation_count: number;
}

/** A row of the export's cover index. */
export interface CoverIndexEntry {
  employeeId: string;
  employeeName: string;
  role: string;
  state: string;
  /** `"none"` when no notice has been generated for the employee yet. */
  noticeStatus: NoticeStatus | "none";
  ruleVersion: string | null;
  sentAt: string | null;
  signedAt: string | null;
}

/** One signed acknowledgment as it appears in the vault. */
export interface SignedNoticeEntry {
  noticeId: string;
  employeeName: string;
  signerName: string;
  /** ISO 8601 UTC. */
  signedAt: string;
  state: string;
  ruleVersion: string;
  /** `null` on the free tier — the frozen text is part of the locked export. */
  noticeText: string | null;
}

export interface AuditFilePreview {
  plan: PlanTier;
  generatedAt: string;
  ruleVersions: string[];
  counts: AuditFileCounts;
  coverIndex: CoverIndexEntry[];
  signedNotices: SignedNoticeEntry[];
}

export interface AuditFileExport {
  filename: string;
  contentType: string;
  content: string;
  counts: AuditFileCounts;
}

export type AuditFileLoadResult =
  | { status: "ready"; preview: AuditFilePreview }
  | { status: "unauthenticated" }
  | { status: "unavailable"; detail: string };

const EMPTY_COUNTS: AuditFileCounts = {
  employee_count: 0,
  signed_notice_count: 0,
  open_violation_count: 0,
};

function toCounts(value: unknown): AuditFileCounts {
  const raw = (value ?? {}) as Partial<Record<keyof AuditFileCounts, unknown>>;
  const num = (candidate: unknown) =>
    typeof candidate === "number" && Number.isFinite(candidate) ? candidate : 0;
  return {
    employee_count: num(raw.employee_count),
    signed_notice_count: num(raw.signed_notice_count),
    open_violation_count: num(raw.open_violation_count),
  };
}

/**
 * Normalises the route response defensively. A compliance export is the last
 * place to let an undefined field render as "undefined" next to a signer name.
 */
export function normalisePreview(value: unknown): AuditFilePreview {
  const raw = (value ?? {}) as Partial<AuditFilePreview>;
  return {
    plan: raw.plan === "shield" ? "shield" : "free",
    generatedAt: typeof raw.generatedAt === "string" ? raw.generatedAt : "",
    ruleVersions: Array.isArray(raw.ruleVersions) ? raw.ruleVersions : [],
    counts: toCounts(raw.counts),
    coverIndex: Array.isArray(raw.coverIndex) ? raw.coverIndex : [],
    signedNotices: Array.isArray(raw.signedNotices) ? raw.signedNotices : [],
  };
}

export async function loadAuditFilePreview(): Promise<AuditFileLoadResult> {
  try {
    const response = await fetch("/api/audit-file", {
      method: "GET",
      headers: { Accept: "application/json" },
    });

    if (response.status === 401) return { status: "unauthenticated" };

    if (!response.ok) {
      return {
        status: "unavailable",
        detail:
          "The audit file service did not respond. Your records are untouched — try again in a moment.",
      };
    }

    const body: unknown = await response.json();
    return { status: "ready", preview: normalisePreview(body) };
  } catch {
    return {
      status: "unavailable",
      detail:
        "Could not reach the audit file service. Check your connection and try again.",
    };
  }
}

export { EMPTY_COUNTS };

/** `YYYY-MM-DD HH:MM UTC` — deterministic, tabular, and never locale-shifted. */
export function formatUtc(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const pad = (value: number) => String(value).padStart(2, "0");
  return (
    `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}` +
    ` ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())} UTC`
  );
}
