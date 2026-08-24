/**
 * Shared landing content — the parts of the page that do NOT change per
 * variant. Variant copy (headline, subheadline, cta, painPoints, promise,
 * proof, urgency) comes from `src/lib/variants.ts`; everything here is derived
 * from experiment.yaml `behaviors` and from the statute itself.
 *
 * Proof policy (visual brief § Social Proof): TipGuard is pre-launch, so there
 * are no testimonials, no logo wall and no "trusted by N restaurants". Every
 * figure on this page carries its statutory citation — a figure without a
 * source may not ship.
 */

export interface EvidenceCell {
  value: number;
  from: number;
  decimals: number;
  prefix?: string;
  suffix?: string;
  caption: string;
  citation: string;
}

/** Full-bleed ink plinth under the hero. Figures are federal law, not claims. */
export const EVIDENCE: EvidenceCell[] = [
  {
    value: 2.13,
    from: 7.25,
    decimals: 2,
    prefix: "$",
    caption:
      "The cash wage a tipped employee may be paid per hour — but only while the tip credit is validly claimed.",
    citation: "29 U.S.C. §203(m)",
  },
  {
    value: 5,
    from: 0,
    decimals: 0,
    caption:
      "Elements every tipped employee must be informed of before a single hour is paid at the tip-credit rate.",
    citation: "29 CFR §531.59(b)",
  },
  {
    value: 2,
    from: 0,
    decimals: 0,
    suffix: "×",
    caption:
      "Back wages owed, plus an equal additional amount as liquidated damages, when the credit is disallowed.",
    citation: "29 U.S.C. §216(b)",
  },
  {
    value: 3,
    from: 0,
    decimals: 0,
    suffix: " yr",
    caption:
      "Lookback window on a willful violation — every tipped hour inside it is recomputed at full minimum wage.",
    citation: "29 U.S.C. §255(a)",
  },
];

export interface Feature {
  index: string;
  eyebrow: string;
  title: string;
  body: string;
  image: string;
  alt: string;
  width: number;
  height: number;
  bullets: string[];
}

/** Derived from behaviors b-04/b-05, b-08/b-09, b-07/b-12. */
export const FEATURES: Feature[] = [
  {
    index: "01",
    eyebrow: "Notices",
    title: "Your roster in. State-correct notices out.",
    body:
      "Upload the staff CSV your payroll already exports. TipGuard resolves your state's cash wage floor, maximum tip credit and required notice elements, then drafts a per-employee notice stamped with the rule version it was written against — and emails it for signature.",
    image: "/images/feature-1.webp",
    alt:
      "Engraved illustration of a squared stack of tip-credit notices, the top sheet stamped in brass above an empty ruled signature line",
    width: 800,
    height: 608,
    bullets: [
      "Per-state rule library, not a generic template",
      "States that eliminated the credit get a no-tip-credit notice instead",
      "Signed acknowledgment stores signer, UTC timestamp, IP and the exact text agreed to",
    ],
  },
  {
    index: "02",
    eyebrow: "Violations",
    title: "Four ways the credit breaks. All four, watched.",
    body:
      "Every scan runs the same four rule classes an investigator runs: overtime premiums computed off the sub-minimum cash wage, ineligible managers or back-of-house in the tip pool, workweeks where wage plus tips fell under the minimum, and notices that are missing or stale.",
    image: "/images/feature-2.webp",
    alt:
      "Engraved illustration of an open ruled ledger with three rows marked by brass flag ticks",
    width: 800,
    height: 608,
    bullets: [
      "Each finding names the employees and pay periods affected",
      "Ranked by estimated exposure, in plain English, with the fix",
    ],
  },
  {
    index: "03",
    eyebrow: "Audit file",
    title: "One dated export. Assembled on demand.",
    body:
      "Signed notices with their signature metadata, the notice-status roster, the violation log with resolutions, and the state rule versions applied — indexed into a single file the day someone asks for it, not the week after.",
    image: "/images/feature-3.webp",
    alt:
      "Engraved illustration of a sealed archival dossier box with a blank dated label plate, closed with a brass seal",
    width: 800,
    height: 608,
    bullets: [
      "Frozen copy of every notice as it was acknowledged",
      "Cover index: employee, status, rule version",
    ],
  },
];

/** Evidence tape — the shape of a vault record, not a customer claim. */
export const VAULT_TAPE: { id: string; status: "SIGNED" | "SENT" | "DRAFT"; meta: string }[] = [
  { id: "REC-2026-0416-04", status: "SIGNED", meta: "TX · rule v2026.2 · 21:04 UTC" },
  { id: "REC-2026-0416-05", status: "SENT", meta: "TX · rule v2026.2 · 21:09 UTC" },
  { id: "REC-2026-0417-01", status: "SIGNED", meta: "AZ · rule v2026.1 · 14:22 UTC" },
  { id: "REC-2026-0417-02", status: "DRAFT", meta: "AZ · rule v2026.1 · pending review" },
  { id: "REC-2026-0418-03", status: "SIGNED", meta: "FL · rule v2026.2 · 03:40 UTC" },
  { id: "REC-2026-0419-01", status: "SIGNED", meta: "NC · rule v2026.1 · 19:58 UTC" },
];

/** Seal-green proof moment ahead of the price. */
export const FILE_CONTENTS: string[] = [
  "Every signed acknowledgment, with signer name, UTC timestamp, IP and user agent",
  "A frozen copy of the exact notice text each employee agreed to",
  "The notice-status roster: who is signed, sent, draft or expired",
  "The violation log, including findings you already resolved",
  "The state rule version applied to every notice in the file",
];

/**
 * Illustrative federal-floor arithmetic — labelled as illustrative on the page.
 * $7.25 federal minimum − $2.13 cash wage = $5.12 of credit per hour at risk.
 */
export const EXPOSURE_MATH = {
  staff: 20,
  hoursPerWeek: 30,
  creditPerHour: 5.12,
  weeks: 104,
  backWages: 319488,
  liquidated: 638976,
};

export const FAQ: { q: string; a: string }[] = [
  {
    q: "Is TipGuard legal advice?",
    a: "No, and it never claims to be. TipGuard generates notices from a per-state rule library and stamps each one with the rule version it was written against. Every generated notice carries an explicit line asking you to have your counsel review it before distribution. We do not claim an attorney certification that we do not have.",
  },
  {
    q: "We already run Gusto, ADP or Toast. Why add this?",
    a: "Payroll platforms calculate wages. Tip apps distribute payouts. Neither one generates the legally required tip-credit notice, collects a signed acknowledgment, or keeps the dated per-employee trail an investigator asks for first. TipGuard sits next to them and owns the paperwork.",
  },
  {
    q: "Do I need an account to see my score?",
    a: "Yes — a free account, no card. It takes a moment and it is what your score, your ranked gap list and your exposure range are saved to, so the file is still there when you come back to close the gaps.",
  },
  {
    q: "My state eliminated the tip credit. Does this still apply?",
    a: "Yes — and that is exactly the case operators get wrong. The rule library resolves your state and generates a no-tip-credit notice instead, so your file reflects the wage basis you are actually on rather than a federal template that no longer applies.",
  },
  {
    q: "What happens when a state changes its rules?",
    a: "Notices are stamped with a rule version. When the rule library moves, notices signed against the old version surface as a missing-or-stale finding with the employees affected, so the file closes the gap instead of silently aging.",
  },
  {
    q: "How long does the first file take?",
    a: "One session. Import the roster, generate the notices, send them for signature. New hires fold in from the dashboard afterward without re-importing anything.",
  },
];

export const COUNSEL_DISCLAIMER =
  "TipGuard is compliance software, not a law firm. Generated notices carry a review-by-your-counsel line and are not a substitute for legal advice.";

export const LOGO = {
  src: "/images/logo.svg",
  alt: "TipGuard logo: a solid ink shield whose lower point turns up as a brass folded document corner",
};

export const HERO_IMAGE = {
  src: "/images/hero.webp",
  alt: "Guests seated along the rail of a warmly lit neighbourhood bar during evening service",
  width: 1920,
  height: 1088,
};

/** Anchor targets used by the header nav and by /distribute sitelinks. */
export const SECTION_IDS = {
  exposure: "exposure",
  how: "how-it-works",
  pricing: "pricing",
  faq: "faq",
} as const;
