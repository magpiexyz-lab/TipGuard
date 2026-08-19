import { createClient } from "@/lib/supabase";
import type { PlanTier } from "@/lib/types";

/**
 * What `/pricing` needs to know about the visitor to render the right CTA and
 * to populate `checkout_started`'s required properties.
 *
 * Read through the RLS-scoped browser client rather than a stats endpoint:
 * `/pricing` must stay readable logged-out, and the two counts are exactly the
 * two properties EVENTS.yaml marks required on `checkout_started`.
 */
export interface AccountSnapshot {
  signedIn: boolean;
  plan: PlanTier;
  /** `notices_sent_at_upgrade` — notices dispatched for signature so far. */
  noticesSent: number;
  /** `open_violation_count` — findings still open at the moment of the click. */
  openViolations: number;
  /** Pre-fills the waitlist panel so joining is one click (b-11). */
  email: string | null;
}

export const ANONYMOUS_SNAPSHOT: AccountSnapshot = {
  signedIn: false,
  plan: "free",
  noticesSent: 0,
  openViolations: 0,
  email: null,
};

function rowCount(value: unknown): number {
  return Array.isArray(value) ? value.length : 0;
}

export async function loadAccountSnapshot(): Promise<AccountSnapshot> {
  const supabase = createClient();

  try {
    const { data: userData } = await supabase.auth.getUser();
    const user = userData?.user;
    if (!user) return ANONYMOUS_SNAPSHOT;

    const [accountResult, noticeResult, violationResult] = await Promise.all([
      supabase.from("accounts").select("plan").eq("user_id", user.id).maybeSingle(),
      supabase.from("notices").select("id").in("status", ["sent", "signed"]),
      supabase.from("violations").select("id").eq("status", "open"),
    ]);

    const plan = (accountResult?.data as { plan?: PlanTier } | null)?.plan;

    return {
      signedIn: true,
      plan: plan === "shield" ? "shield" : "free",
      noticesSent: rowCount(noticeResult?.data),
      openViolations: rowCount(violationResult?.data),
      email: user.email ?? null,
    };
  } catch {
    // The pricing argument does not depend on account state — degrade to the
    // logged-out reading rather than blocking the page on a schema that may
    // not exist yet.
    return ANONYMOUS_SNAPSHOT;
  }
}
