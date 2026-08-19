// GENERATED from experiment/EVENTS.yaml by scaffold-libs. When /change or
// /distribute adds a new event to EVENTS.yaml, regenerate the corresponding
// wrapper here. Pages import from this file instead of calling track()
// directly with string event names — this gives compile-time validation of
// event names and property shapes (CLAUDE.md Rule 2).

import { track } from "./analytics";

// --- Event funnel stage map (generated from experiment/EVENTS.yaml) ---

export const EVENT_FUNNEL_MAP: Record<string, string> = {
  landing_view: "reach",
  qualified_paid_visit: "reach",
  cta_click: "demand",
  score_started: "activate",
  score_completed: "activate",
  signup_start: "activate",
  signup_complete: "activate",
  roster_imported: "activate",
  payroll_connect_clicked: "activate",
  notice_generated: "activate",
  notice_sent: "activate",
  notice_signed: "activate",
  violation_detected: "activate",
  violation_resolved: "activate",
  feedback_submitted: "activate",
  checkout_started: "monetize",
  waitlist_joined: "monetize",
  audit_file_exported: "monetize",
  retain_return: "retain",
} as const;

// --- Event wrappers (generated from experiment/EVENTS.yaml events map) ---

export function trackLandingView(props?: {
  variant?: string;
  utm_source?: string;
  utm_medium?: string;
  utm_campaign?: string;
  utm_content?: string;
  gclid?: string;
  click_id?: string;
  referrer?: string;
}) {
  track("landing_view", { ...props, funnel_stage: "reach" });
}

export function trackQualifiedPaidVisit(props: {
  source_channel: string;
  variant?: string;
}) {
  track("qualified_paid_visit", { ...props, funnel_stage: "reach" });
}

export function trackCtaClick(props?: {
  variant?: string;
  cta_position?: string;
}) {
  track("cta_click", { ...props, funnel_stage: "demand" });
}

export function trackScoreStarted(props?: {
  variant?: string;
  state?: string;
}) {
  track("score_started", { ...props, funnel_stage: "activate" });
}

export function trackScoreCompleted(props: {
  readiness_score: number;
  gap_count: number;
  state: string;
  estimated_exposure_usd?: number;
}) {
  track("score_completed", { ...props, funnel_stage: "activate" });
}

export function trackSignupStart(props?: {
  auth_method?: string;
}) {
  track("signup_start", { ...props, funnel_stage: "activate" });
}

export function trackSignupComplete(props: {
  auth_method: string;
  had_score?: boolean;
}) {
  track("signup_complete", { ...props, funnel_stage: "activate" });
}

export function trackRosterImported(props: {
  rows_total: number;
  rows_imported: number;
  rows_failed: number;
}) {
  track("roster_imported", { ...props, funnel_stage: "activate" });
}

export function trackPayrollConnectClicked(props: {
  provider: string;
}) {
  track("payroll_connect_clicked", { ...props, funnel_stage: "activate" });
}

export function trackNoticeGenerated(props: {
  notice_id: string;
  state: string;
  rule_version: string;
  tip_credit_claimed: boolean;
}) {
  track("notice_generated", { ...props, funnel_stage: "activate" });
}

export function trackNoticeSent(props: {
  notice_id: string;
  employee_count: number;
  delivery_channel: string;
}) {
  track("notice_sent", { ...props, funnel_stage: "activate" });
}

export function trackNoticeSigned(props: {
  notice_id: string;
  hours_to_sign?: number;
}) {
  track("notice_signed", { ...props, funnel_stage: "activate" });
}

export function trackViolationDetected(props: {
  rule_class: string;
  severity: string;
  estimated_exposure_usd?: number;
}) {
  track("violation_detected", { ...props, funnel_stage: "activate" });
}

export function trackViolationResolved(props: {
  rule_class: string;
  days_open: number;
}) {
  track("violation_resolved", { ...props, funnel_stage: "activate" });
}

export function trackFeedbackSubmitted(props: {
  activation_action: string;
  source?: string;
  feedback?: string;
}) {
  track("feedback_submitted", { ...props, funnel_stage: "activate" });
}

// --- Monetize events (fake-door waitlist; see experiment/EVENTS.yaml) ---

export function trackCheckoutStarted(props: {
  notices_sent_at_upgrade: number;
  open_violation_count: number;
  variant?: string;
}) {
  track("checkout_started", { ...props, funnel_stage: "monetize" });
}

export function trackWaitlistJoined(props: {
  notices_sent_at_join: number;
  variant?: string;
}) {
  track("waitlist_joined", { ...props, funnel_stage: "monetize" });
}

export function trackAuditFileExported(props: {
  employee_count: number;
  signed_notice_count: number;
  open_violation_count: number;
}) {
  track("audit_file_exported", { ...props, funnel_stage: "monetize" });
}

export function trackRetainReturn(props: {
  days_since_first: number;
  has_sent_notice?: boolean;
}) {
  track("retain_return", { ...props, funnel_stage: "retain" });
}
