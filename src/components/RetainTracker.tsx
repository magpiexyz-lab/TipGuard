"use client";

import { useEffect } from "react";
import { trackRetainReturn } from "@/lib/events";

const FIRST_VISIT_KEY = "tipguard.first_visit_ts";
const LAST_FIRED_KEY = "tipguard.retain_return_days";
const MS_PER_DAY = 86_400_000;

/**
 * `retain_return` (h-07). Mounted once in the root layout so the return window
 * is measured globally rather than per page.
 *
 * The event property EVENTS.yaml requires is `days_since_first`, so the anchor
 * stored here is the FIRST visit, not the last one — a user returning on days
 * 2, 4 and 6 reports 1, 3 and 5, and the retain denominator stays anchored to
 * a single origin.
 *
 * Idempotent within a return window (b-14 test 1): the last reported
 * `days_since_first` is persisted, and the event only fires again once a
 * strictly larger day bucket is reached. Reloading the page ten times on day 3
 * fires once.
 */
export function RetainTracker() {
  useEffect(() => {
    try {
      const now = Date.now();
      const rawFirst = localStorage.getItem(FIRST_VISIT_KEY);
      const first = rawFirst ? Number(rawFirst) : NaN;

      if (!Number.isFinite(first) || first <= 0) {
        localStorage.setItem(FIRST_VISIT_KEY, String(now));
        return;
      }

      const daysSinceFirst = Math.floor((now - first) / MS_PER_DAY);
      if (daysSinceFirst < 1) return;

      const rawLast = localStorage.getItem(LAST_FIRED_KEY);
      const lastFired = rawLast ? Number(rawLast) : -1;
      if (Number.isFinite(lastFired) && daysSinceFirst <= lastFired) return;

      localStorage.setItem(LAST_FIRED_KEY, String(daysSinceFirst));
      trackRetainReturn({ days_since_first: daysSinceFirst });
    } catch {
      // localStorage unavailable (private mode, sandboxed iframe) — skip.
    }
  }, []);

  return null;
}
