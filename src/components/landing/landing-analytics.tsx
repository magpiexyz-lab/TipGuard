"use client";

import { useEffect, useRef } from "react";
import { classifyVisit } from "@/lib/analytics-attribution";
import { trackLandingView, trackQualifiedPaidVisit } from "@/lib/events";
import type { VariantSlug } from "@/lib/variants";

/**
 * Landing attribution + view tracking (b-01 test 2, b-13).
 *
 * Fires exactly once per mount:
 *   - `landing_view` with UTM params, click ids, referrer and variant slug
 *   - `qualified_paid_visit` when the source matches the restaurant-operator
 *     allowlist. Classification is delegated to
 *     `src/lib/analytics-attribution.ts` (unit-tested) — never reimplemented here.
 *
 * Renders nothing. Kept as a leaf client component so the rest of the landing
 * surface stays server-rendered and fully present in the static HTML.
 */
export function LandingAnalytics({ variantSlug }: { variantSlug: VariantSlug }) {
  const fired = useRef(false);

  useEffect(() => {
    // React StrictMode double-invokes effects in dev; the event must fire once.
    if (fired.current) return;
    fired.current = true;

    const params = new URLSearchParams(window.location.search);
    const param = (key: string) => params.get(key)?.trim() || undefined;

    const utmSource = param("utm_source");
    const utmMedium = param("utm_medium");
    const utmCampaign = param("utm_campaign");
    const utmContent = param("utm_content");
    const gclid = param("gclid");
    const clickId =
      param("click_id") ?? param("fbclid") ?? param("msclkid") ?? param("ttclid");
    // Always present so downstream funnels can distinguish "direct" from "unset".
    const referrer = document.referrer || "direct";

    trackLandingView({
      variant: variantSlug,
      utm_source: utmSource,
      utm_medium: utmMedium,
      utm_campaign: utmCampaign,
      utm_content: utmContent,
      gclid,
      click_id: clickId,
      referrer,
    });

    const { qualified, sourceChannel } = classifyVisit({
      utmSource,
      utmMedium,
      utmCampaign,
      referrer: document.referrer,
    });

    if (qualified && sourceChannel) {
      trackQualifiedPaidVisit({ source_channel: sourceChannel, variant: variantSlug });
    }
  }, [variantSlug]);

  return null;
}
