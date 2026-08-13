// Shared API-route identity resolution.
//
// EVERY authenticated route in this app needs the same three things: the
// session user, the tenant `accounts` row that user owns, and a service-role
// client to perform the write (all TipGuard tables are read-only to clients —
// see supabase/migrations/001_initial.sql). Ten routes needed the identical
// preamble, so it lives here once.
//
// SECURITY: identity is ALWAYS derived from `supabase.auth.getUser()`, which
// verifies the session cookie against the Supabase auth server. It is never
// derived from the request body, a header, or a query parameter. Routes that
// accept an `id` in the body must additionally scope their query by
// `account_id = ctx.account.id` (defence in depth on top of RLS).

import type { SupabaseClient } from "@supabase/supabase-js";
import {
  createServerSupabaseClient,
  createServiceRoleClient,
} from "@/lib/supabase-server";
import type { AccountRow } from "@/lib/types";

export const ACCOUNT_COLUMNS =
  "id, user_id, restaurant_name, home_state, plan, stripe_customer_id, current_period_end, readiness_score, gap_list, scored_at, last_scan_at, created_at";

export interface AccountContext {
  userId: string;
  email: string | null;
  account: AccountRow;
  /** Service-role client. Bypasses RLS — always scope queries by account.id. */
  db: SupabaseClient;
}

export type AccountResolution =
  | { ok: true; ctx: AccountContext }
  /** No verified session cookie. */
  | { ok: false; reason: "unauthenticated" }
  /** Session exists but no `accounts` row (and `create` was not requested). */
  | { ok: false; reason: "no_account" }
  /** SUPABASE_SERVICE_ROLE_KEY absent, or the database is unreachable. */
  | { ok: false; reason: "unavailable" };

/**
 * Resolve the caller's account.
 *
 * @param options.create - provision an empty `accounts` row when the user has
 *   none. Signup creates the auth user; the account row is created lazily on
 *   the first authenticated write so the OAuth path does not need a second
 *   round trip before the user can do anything.
 */
export async function resolveAccount(
  options: { create?: boolean } = {}
): Promise<AccountResolution> {
  // Session verification is a network call to the Supabase auth server. When
  // that server is unreachable it rejects, and none of the ten call sites wrap
  // `await resolveAccount()` in a try/catch — an escaping rejection becomes a
  // bare 500 that bypasses the documented AccountResolution contract entirely.
  // Degrade to `unavailable` (503), which is fail-closed: no user, no
  // service-role client, no data.
  let user: { id: string; email?: string | null } | null;
  try {
    const supabase = await createServerSupabaseClient();
    const result = await supabase.auth.getUser();
    user = result.data.user;
  } catch (error) {
    console.error("[api-auth] session verification failed:", error);
    return { ok: false, reason: "unavailable" };
  }
  if (!user) return { ok: false, reason: "unauthenticated" };

  let db: SupabaseClient;
  try {
    db = createServiceRoleClient() as unknown as SupabaseClient;
  } catch (error) {
    console.error("[api-auth] service-role client unavailable:", error);
    return { ok: false, reason: "unavailable" };
  }

  try {
    const existing = await db
      .from("accounts")
      .select(ACCOUNT_COLUMNS)
      .eq("user_id", user.id)
      .maybeSingle();

    if (existing.error) {
      console.error("[api-auth] account lookup failed:", existing.error);
      return { ok: false, reason: "unavailable" };
    }

    let account = existing.data as AccountRow | null;

    if (!account && options.create) {
      const created = await db
        .from("accounts")
        .insert({ user_id: user.id, restaurant_name: "", home_state: "" })
        .select(ACCOUNT_COLUMNS)
        .single();
      if (created.error) {
        console.error("[api-auth] account provisioning failed:", created.error);
        return { ok: false, reason: "unavailable" };
      }
      account = created.data as AccountRow;
    }

    if (!account) return { ok: false, reason: "no_account" };

    return {
      ok: true,
      ctx: { userId: user.id, email: user.email ?? null, account, db },
    };
  } catch (error) {
    console.error("[api-auth] unexpected account resolution error:", error);
    return { ok: false, reason: "unavailable" };
  }
}

/** Maps a failed resolution to the HTTP status the route should return. */
export function statusForReason(
  reason: "unauthenticated" | "no_account" | "unavailable"
): number {
  if (reason === "unauthenticated") return 401;
  if (reason === "no_account") return 404;
  return 503;
}
