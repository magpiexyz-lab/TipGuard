// PostHog identity decisions for Supabase auth-state transitions.
//
// Pure function, no imports, no DOM, no network — so it runs under vitest's
// `environment: "node"` with no mocks. The effect (calling identify()/reset()
// from src/lib/analytics.ts) lives in <AnalyticsIdentity />; only the DECISION
// lives here, which is the part worth testing.
//
// ── Why this exists ───────────────────────────────────────────────────────
// Client events (landing_view, cta_click, signup_start) carry the browser's
// anonymous distinct_id, which is where the `gclid` and `utm_*` super-properties
// registered by the `loaded` callback in analytics.ts live. `signup_complete`
// fires SERVER-side from src/app/auth/callback/route.ts with
// `distinctId = user.id`. Without an identify() call those are two different
// person records, so an ad click can never be joined to the conversion it
// produced.
//
// The Google OAuth leg is why the join has to happen here and not in the
// callback route: the browser leaves the origin for Google's consent screen and
// returns to a server route handler, which cannot see the browser's anonymous
// distinct_id. Only the client can close the gap, and only after the session
// exists — i.e. on an auth-state event.

export type IdentityAction =
  | { type: "identify"; userId: string }
  | { type: "reset" }
  | { type: "none" };

export interface IdentityInput {
  /** Supabase AuthChangeEvent name (SIGNED_IN, INITIAL_SESSION, SIGNED_OUT, ...). */
  event: string;
  /** `session?.user?.id` for this event — null/undefined when there is no session. */
  userId: string | null | undefined;
  /** The id most recently passed to identify(), or null if none has been. */
  lastIdentifiedId: string | null;
}

/**
 * Decides what the analytics layer should do for one Supabase auth-state event.
 *
 * One rule covers every documented event:
 *   - SIGNED_OUT resets, but ONLY if somebody was actually identified.
 *   - Every other event identifies, but ONLY when it carries a user id that
 *     differs from the last one identified.
 *
 * The two guards matter more than the happy path:
 *
 *   1. A sessionless event (an anonymous visitor landing on `/` fires
 *      INITIAL_SESSION with no session) returns `none`, NEVER `reset`.
 *      Resetting there would wipe the anonymous distinct_id on every landing
 *      page load, destroying the very attribution this module exists to
 *      preserve.
 *   2. SIGNED_OUT with nothing identified returns `none` rather than `reset`,
 *      so a spurious sign-out on an anonymous browser does not churn the
 *      distinct_id for no gain.
 */
export function decideIdentityAction(input: IdentityInput): IdentityAction {
  const { event, userId, lastIdentifiedId } = input;

  if (event === "SIGNED_OUT") {
    // Guard 2 — nothing to detach.
    return lastIdentifiedId === null ? { type: "none" } : { type: "reset" };
  }

  // Guard 1 — anonymous visitor. An empty string is treated as absent so a
  // malformed session can never be identified as the user `""`.
  if (!userId) return { type: "none" };

  // Dedup. Repeat identify() calls for the same person are wasted work, and
  // TOKEN_REFRESHED fires on a timer for the whole session.
  if (userId === lastIdentifiedId) return { type: "none" };

  // The join. Reached by SIGNED_IN (including the OAuth return leg),
  // INITIAL_SESSION on a restored session, and TOKEN_REFRESHED when an earlier
  // identify was missed.
  return { type: "identify", userId };
}
