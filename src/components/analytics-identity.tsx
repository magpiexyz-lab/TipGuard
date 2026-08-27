"use client";

import { useEffect, useRef } from "react";
import type { AuthChangeEvent, Session } from "@supabase/supabase-js";
import { createClient } from "@/lib/supabase";
import { identify, reset } from "@/lib/analytics";
import { decideIdentityAction } from "@/lib/analytics-identity";

/**
 * Joins the anonymous pre-signup distinct_id to the signed-in user id.
 *
 * WHY THIS EXISTS AS A GLOBAL COMPONENT:
 * `identify()` has to run on EVERY path that establishes a session, and those
 * paths do not share a page. Google OAuth returns to `/auth/callback` (a server
 * route) and then redirects to `/dashboard`; email/password establishes the
 * session on `/signup`; a returning owner just reloads whatever page they were
 * on. Mounting once in the root layout covers all three from one call site —
 * the same reason `<PendingScoreClaim />` lives here.
 *
 * It cannot be done server-side. `signup_complete` fires from the callback
 * route with `distinctId = user.id`, but that route has no way to learn the
 * browser's anonymous distinct_id — the one carrying the `gclid` and `utm_*`
 * super-properties. Only the client knows both ids, so only the client can ask
 * PostHog to merge them.
 *
 * Cost when there is nothing to do: one `onAuthStateChange` subscription and a
 * pure function call per auth event. Anonymous visitors resolve to `none`, so
 * `identify()`/`reset()` are never called and posthog-js is never initialized
 * by this component — the landing page is untouched.
 *
 * All decision logic lives in `@/lib/analytics-identity` so it can be unit
 * tested under vitest's node environment; this file is the effect only.
 */
export function AnalyticsIdentity() {
  // The last id passed to identify(). Per-mount rather than module-level: a
  // hard reload re-identifies once, which PostHog treats as a no-op when the
  // distinct_id already matches.
  const lastIdentifiedIdRef = useRef<string | null>(null);

  useEffect(() => {
    const supabase = createClient();

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange(
      (event: AuthChangeEvent, session: Session | null) => {
        const action = decideIdentityAction({
          event,
          userId: session?.user?.id,
          lastIdentifiedId: lastIdentifiedIdRef.current,
        });

        if (action.type === "identify") {
          // Opaque Supabase user id ONLY — never email or any other trait.
          // PostHog links events to the person internally; PII in the event
          // stream is retained indefinitely (see the PostHog stack file).
          identify(action.userId);
          lastIdentifiedIdRef.current = action.userId;
        } else if (action.type === "reset") {
          reset();
          lastIdentifiedIdRef.current = null;
        }
      }
    );

    return () => subscription.unsubscribe();
  }, []);

  return null;
}
