// Database row types for TipGuard — mirrors the schema in
// `supabase/migrations/001_initial.sql`, which is the source of truth. Naming
// convention: <Table>Row. These are the canonical project types; pages and API
// routes import from here rather than redeclaring shapes inline.
//
// API contract types (XxxRequest / XxxResponse) are collected at the bottom of
// this file from the zod schemas and response types each route exports.
//
// Dependency direction: route.ts <- types.ts <- page.tsx. Routes export schemas
// but never import from types.ts; pages import types from here, never from a
// route file. That keeps the graph acyclic.

export type PlanTier = "free" | "shield";

export interface AccountRow {
  id: string;
  user_id: string;
  restaurant_name: string;
  home_state: string;
  plan: PlanTier;
  stripe_customer_id: string | null;
  current_period_end: string | null;
  readiness_score: number | null;
  gap_list: unknown | null; // JSON snapshot of the questionnaire gap findings
  /** When the carried questionnaire result was produced. Guards a stale
   *  localStorage record from clobbering a newer score (b-03). */
  scored_at: string | null;
  /** Last compliance scan. NULL means NEVER scanned — which is a different
   *  state from "scanned and came back clean". /violations reads this rather
   *  than inferring from `violations.length > 0`, so an account whose first
   *  scan is genuinely clean sees the clean-ledger state instead of being told
   *  to run its first scan. */
  last_scan_at: string | null;
  created_at: string;
}

export interface EmployeeRow {
  id: string;
  account_id: string;
  name: string;
  email: string;
  role: string;
  hire_date: string;
  hourly_rate: number;
  state: string;
  /** Input to the ineligible-tip-pool rule class (b-08). */
  in_tip_pool: boolean;
  created_at: string;
}

export interface PayPeriodRow {
  id: string;
  employee_id: string;
  account_id: string;
  period_start: string;
  period_end: string;
  hours_worked: number;
  overtime_hours: number;
  overtime_rate_used: number | null;
  tips_reported: number;
  cash_wage_paid: number;
  created_at: string;
}

export type NoticeStatus = "draft" | "sent" | "signed";

export interface NoticeRow {
  id: string;
  account_id: string;
  employee_id: string;
  state: string;
  rule_version: string;
  cash_wage_paid: number;
  tip_credit_claimed: boolean;
  notice_text: string;
  status: NoticeStatus;
  /** Set when the notice leaves for signature. NULL while still a draft. */
  sent_at: string | null;
  created_at: string;
}

export interface SigningTokenRow {
  id: string;
  account_id: string;
  notice_id: string;
  /** SHA-256 hex digest. The raw token is NEVER stored — see
   *  `src/app/sign/signing-token.ts`. */
  token_hash: string;
  expires_at: string;
  used_at: string | null;
  created_at: string;
}

export interface SignatureRow {
  id: string;
  account_id: string;
  notice_id: string;
  signer_name: string;
  signed_at: string;
  ip_address: string;
  user_agent: string;
  notice_text_snapshot: string;
  created_at: string;
}

export type ViolationRuleClass =
  | "overtime_base"
  | "ineligible_tip_pool"
  | "subminimum_shortfall"
  | "missing_notice";

export type ViolationSeverity = "critical" | "high" | "medium";

export type ViolationStatus = "open" | "resolved";

export interface ViolationRow {
  id: string;
  account_id: string;
  employee_id: string | null;
  rule_class: ViolationRuleClass;
  severity: ViolationSeverity;
  estimated_exposure_usd: number;
  status: ViolationStatus;
  detail: string;
  detected_at: string;
  resolved_at: string | null;
  created_at: string;
}

export interface FakeDoorClickRow {
  id: string;
  /** NULL when the click happened before an account existed. */
  account_id: string | null;
  provider: string;
  created_at: string;
}

export interface FeedbackRow {
  id: string;
  account_id: string | null;
  source: string | null;
  feedback: string | null;
  activation_action: string;
  created_at: string;
}

/** Stripe webhook replay guard. Service role only — never read by a page. */
export interface StripeEventRow {
  stripe_event_id: string;
  received_at: string;
}

// ---------------------------------------------------------------------------
// API contract types (wire.md Step 6)
//
// Request types are inferred from each route's exported zod schema — the
// schema is authoritative, so a page can never drift from what the route
// actually accepts. Response types are plain TS re-exports: they are
// server-authored and not validated at the boundary.
// ---------------------------------------------------------------------------

import type { z } from "zod";
import type { attachScoreSchema } from "@/app/api/account/score/route";
import type { importStaffSchema } from "@/app/api/staff/import/route";
import type { generateNoticesSchema } from "@/app/api/notices/generate/route";
import type { sendNoticesSchema } from "@/app/api/notices/send/route";
import type { signNoticeSchema } from "@/app/api/notices/sign/route";
import type { resolveViolationSchema } from "@/app/api/violations/resolve/route";
import type { createCheckoutSchema } from "@/app/api/checkout/route";
import type { submitFeedbackSchema } from "@/app/api/feedback/route";

export type AttachScoreRequest = z.infer<typeof attachScoreSchema>;
export type ImportStaffRequest = z.infer<typeof importStaffSchema>;
export type GenerateNoticesRequest = z.infer<typeof generateNoticesSchema>;
export type SendNoticesRequest = z.infer<typeof sendNoticesSchema>;
export type SignNoticeRequest = z.infer<typeof signNoticeSchema>;
export type ResolveViolationRequest = z.infer<typeof resolveViolationSchema>;
export type CreateCheckoutRequest = z.infer<typeof createCheckoutSchema>;
export type SubmitFeedbackRequest = z.infer<typeof submitFeedbackSchema>;

export type { AttachScoreResponse } from "@/app/api/account/score/route";
export type { ListStaffResponse } from "@/app/api/staff/route";
export type { ImportStaffResponse, ImportStaffFailure } from "@/app/api/staff/import/route";
export type { ListNoticesResponse } from "@/app/api/notices/route";
export type {
  GenerateNoticesResponse,
  NoticeGenerationSkip,
} from "@/app/api/notices/generate/route";
export type { SendNoticesResponse } from "@/app/api/notices/send/route";
export type { SignNoticeResponse } from "@/app/api/notices/sign/route";
export type { ScanViolationsResponse } from "@/app/api/violations/scan/route";
export type { ResolveViolationResponse } from "@/app/api/violations/resolve/route";
export type { CreateCheckoutResponse } from "@/app/api/checkout/route";
export type { SubmitFeedbackResponse } from "@/app/api/feedback/route";
export type {
  AuditFilePreview,
  AuditFileExport,
  AuditFileCounts,
  CoverIndexEntry,
  SignedNoticeEntry,
} from "@/app/audit-file/audit-file-contract";
