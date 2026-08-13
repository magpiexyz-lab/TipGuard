/**
 * Landing variant definitions — mirrors experiment.yaml `variants`.
 *
 * Each variant gets its own URL (`/v/<slug>`) and its own ad group. The root
 * route `/` renders DEFAULT_VARIANT so paid traffic can be split without a
 * redirect hop.
 *
 * Keep this in sync with experiment.yaml — it is the source of truth.
 */

export type VariantSlug = "audit-risk" | "cost-shield" | "one-click-file";

export interface Variant {
  slug: VariantSlug;
  headline: string;
  subheadline: string;
  cta: string;
  painPoints: [string, string, string];
  promise: string;
  proof: string;
  urgency: string;
  pricingAmount: number;
  pricingModel: "subscription";
  /** Meta title — must stay <= 60 chars (messaging.md Section E). */
  metaTitle: string;
  /** Meta description — must stay <= 160 chars (messaging.md Section E). */
  metaDescription: string;
}

export const DEFAULT_VARIANT: VariantSlug = "audit-risk";

export const VARIANTS: Record<VariantSlug, Variant> = {
  "audit-risk": {
    slug: "audit-risk",
    headline: "One Missing Signature Voids Every Tip Credit You Ever Took",
    subheadline:
      "TipGuard generates state-specific tip-credit notices, collects signed acknowledgments, and keeps the dated file a DOL investigator asks for first.",
    cta: "Get My Free Audit-Readiness Score",
    painPoints: [
      "The tip credit is conditional — no signed notice means the $2.13 rate was never valid, retroactively, for every tipped hour",
      "Food service is the most-audited industry and the missing per-employee notice is the most-cited paperwork failure",
      "You will not find out the file is incomplete until an investigator is already asking for it",
    ],
    promise:
      "Know your exposure in two minutes, then close the gaps the same afternoon.",
    proof:
      "Score your restaurant against the same items an investigator opens with — notices, tip-pool composition, overtime basis, and sub-minimum shortfalls.",
    urgency:
      "Back-pay liability accrues on every shift you run without the signed file.",
    pricingAmount: 79,
    pricingModel: "subscription",
    metaTitle: "One Missing Signature Voids Your Tip Credit | TipGuard",
    metaDescription:
      "Generate state-specific tip-credit notices, collect signed acknowledgments, and keep the dated file a DOL investigator asks for first.",
  },
  "cost-shield": {
    slug: "cost-shield",
    headline: "$79 a Month Against a Six-Figure Wage Claim",
    subheadline:
      "A single wage-and-hour class action runs past $500K in defense costs before trial. TipGuard keeps the paperwork that makes the claim a non-starter.",
    cta: "Protect My Tip Credit",
    painPoints: [
      "One wage-and-hour class action costs more in defense fees than a decade of compliance software",
      "Payroll calculates and tip apps distribute — neither generates the notices or keeps the audit trail",
      "A bookkeeper cannot track shifting state tip-credit rules across every new hire by hand",
    ],
    promise: "Convert an unbounded legal exposure into a fixed $79 line item.",
    proof:
      "$79/mo is roughly one hour of wage-and-hour defense counsel. The paperwork it maintains is the first thing that defense would ask you for.",
    urgency: "Every pay period without signed notices widens the back-pay window.",
    pricingAmount: 79,
    pricingModel: "subscription",
    metaTitle: "$79/mo Against a Six-Figure Wage Claim | TipGuard",
    metaDescription:
      "A wage-and-hour class action runs past $500K before trial. Keep the tip-credit paperwork that makes the claim a non-starter — for $79 a month.",
  },
  "one-click-file": {
    slug: "one-click-file",
    headline: "Hand the DOL a Complete File, Not a Panic",
    subheadline:
      "Every signed notice, every acknowledgment date, every tip-pool and overtime check — assembled into one export, updated as staff and state rules change.",
    cta: "See My Audit File",
    painPoints: [
      "When the notice arrives you have days to assemble records scattered across payroll, POS, and a filing cabinet",
      "Staff turnover means the notice file is stale within a month of the last time anyone checked it",
      "Several states are changing or phasing out the tip credit and nobody tells the operator when the rules move",
    ],
    promise:
      "The audit file stays complete on its own — new hires and rule changes fold in automatically.",
    proof:
      "Signed notices are stored with signer, timestamp, and the exact text acknowledged, so the export is evidence rather than a summary.",
    urgency:
      "Rebuilding two years of tip-credit records under deadline is not a weekend project.",
    pricingAmount: 79,
    pricingModel: "subscription",
    metaTitle: "Hand the DOL a Complete File, Not a Panic | TipGuard",
    metaDescription:
      "Every signed notice, acknowledgment date, and tip-pool check assembled into one dated export — updated as your staff and state rules change.",
  },
};

export const VARIANT_SLUGS = Object.keys(VARIANTS) as VariantSlug[];

export function isVariantSlug(value: string): value is VariantSlug {
  return value in VARIANTS;
}

export function getVariant(slug: string): Variant | null {
  return isVariantSlug(slug) ? VARIANTS[slug] : null;
}
