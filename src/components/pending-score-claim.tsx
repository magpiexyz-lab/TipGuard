"use client";

import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";
import { clearPendingScore, readPendingScore } from "@/app/score/pending-score";

/**
 * b-03 — claims the anonymous /score result onto the signed-in account.
 *
 * WHY THIS EXISTS AS A GLOBAL COMPONENT:
 * `/signup` can attach the score itself on the email/password path, because a
 * session exists on that page the moment `signUp()` resolves. The Google OAuth
 * path cannot: the browser leaves the origin for Google's consent screen and
 * comes back to `/auth/callback` — a SERVER route handler with no access to
 * localStorage, where the pending record lives (localStorage, not
 * sessionStorage, precisely because OAuth may return in a different tab).
 *
 * So nothing on the page side and nothing in the callback can attach it. This
 * component runs on the first authenticated render after the redirect and
 * closes that hole. Without it every Google signup silently loses the score
 * that hypothesis h-03 is measured on.
 *
 * Cost when there is nothing to claim: one synchronous localStorage read that
 * returns null. No fetch, no state, no render output.
 *
 * `clearPendingScore()` is called ONLY on a confirmed 200. A 401 (session not
 * established yet), a network failure, or a 5xx leaves the record in place so
 * the next authenticated page load retries it. The route is idempotent and
 * ignores a record older than the score already on the account.
 */

/** Surfaces where no session can exist — never even read storage there. */
const UNAUTHENTICATED_PATHS = ["/", "/sign", "/login", "/score"];

export function PendingScoreClaim() {
  const pathname = usePathname();
  const attemptedRef = useRef(false);

  useEffect(() => {
    if (attemptedRef.current) return;
    const path = pathname ?? "";
    if (UNAUTHENTICATED_PATHS.includes(path) || path.startsWith("/v/")) return;

    const pending = readPendingScore();
    if (!pending) return;

    attemptedRef.current = true;
    const controller = new AbortController();

    void (async () => {
      try {
        const response = await fetch("/api/account/score", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          signal: controller.signal,
          body: JSON.stringify({
            state: pending.state,
            claims_tip_credit: pending.claimsTipCredit,
            staff_count: pending.staffCount,
            readiness_score: pending.readinessScore,
            gap_list: pending.gaps,
            estimated_exposure_usd: pending.estimatedExposureUsd,
            saved_at: pending.savedAt,
          }),
        });
        // Only a confirmed write discards the local record.
        if (response.ok) clearPendingScore();
        else attemptedRef.current = false;
      } catch {
        // Offline or aborted — keep the record and retry on the next load.
        attemptedRef.current = false;
      }
    })();

    return () => controller.abort();
  }, [pathname]);

  return null;
}
