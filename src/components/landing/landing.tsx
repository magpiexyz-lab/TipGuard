import { MagicEffects } from "@/components/magicui/effects";
import type { Variant } from "@/lib/variants";
import { EvidenceStrip } from "./evidence-strip";
import { EvidenceTape } from "./evidence-tape";
import { ExposureSection } from "./exposure-section";
import { FeaturesSection } from "./features-section";
import { Hero } from "./hero";
import { LandingAnalytics } from "./landing-analytics";
import { PricingSection } from "./pricing-section";
import { SiteFooter } from "./site-footer";
import { SiteHeader } from "./site-header";

/**
 * Shared landing surface rendered by BOTH `/` and `/v/<slug>`.
 *
 * Variant copy (headline, subheadline, cta, painPoints, promise, proof,
 * urgency) is owned by `src/lib/variants.ts` and slots into the hero, the
 * exposure ledger and the price panel. Structure is identical across all three
 * variants (messaging.md Section D).
 *
 * Landmark note: this component deliberately does NOT render <main>.
 * `src/app/layout.tsx` owns the single `<main id="main-content">` landmark for
 * every route; a second one here would trip axe `landmark-no-duplicate-main`.
 *
 * Analytics (CLAUDE.md Rule 2 — typed wrappers only, never raw track()):
 *   - `landing_view` + `qualified_paid_visit` → <LandingAnalytics /> on mount
 *   - `cta_click` → <CtaButton /> at hero, feature_section, pricing, footer and
 *     header positions; every one navigates to `/score`
 *
 * Section rhythm — no two adjacent sections share a surface or a structure:
 *   ink photo (asymmetric 2-col)
 *   → ink plinth (4-cell hairline strip)
 *   → paper + rules (sticky rail + ledger rows)
 *   → paper-raised inset (asymmetric bento)
 *   → ink tape (marquee band)
 *   → ink (two-panel anchor)
 *   → paper (sticky rail + accordion)
 *   → paper-raised (centred close)
 *   → ink footer
 */
export function Landing({ variant }: { variant: Variant }) {
  return (
    <>
      <MagicEffects />
      <LandingAnalytics variantSlug={variant.slug} />

      <SiteHeader variantSlug={variant.slug} ctaLabel="Free score" />

      <Hero variant={variant} />
      <EvidenceStrip />
      <ExposureSection variant={variant} />
      <FeaturesSection variant={variant} />
      <EvidenceTape />
      <PricingSection variant={variant} />

      <SiteFooter />
    </>
  );
}
