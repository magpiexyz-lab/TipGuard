// Qualified restaurant-operator source classification (b-13).
//
// Pure function, no network. Classifies a landing visit's UTM parameters and
// referrer against the qualified restaurant-operator allowlist: restaurant-
// owner ad campaigns, reddit.com/r/restaurateur, and state restaurant
// association domains. Drives the `qualified_paid_visit` event (h-08).

export type SourceChannel =
  | "meta_restaurant"
  | "google_intent"
  | "reddit_restaurateur"
  | "association"
  | "other_paid";

export interface AttributionInput {
  utmSource?: string;
  utmMedium?: string;
  utmCampaign?: string;
  referrer?: string;
}

export interface AttributionResult {
  qualified: boolean;
  sourceChannel: SourceChannel | null;
}

// State restaurant association domains that qualify as a trusted channel.
// Extend as partnerships form — see distribution Phase 3 in experiment.yaml.
const ASSOCIATION_DOMAINS = [
  "restaurant.org", // National Restaurant Association
  "calrest.org", // California Restaurant Association
  "nyrestaurant.org", // NY State Restaurant Association
  "txrestaurant.org", // Texas Restaurant Association
];

const RESTAURANT_INTENT_TERMS = ["tip-credit", "tip_credit", "tip-pooling", "tip_pooling", "dol-audit", "dol_audit", "restaurant"];

export function classifyVisit(input: AttributionInput): AttributionResult {
  const source = normalize(input.utmSource);
  const medium = normalize(input.utmMedium);
  const campaign = normalize(input.utmCampaign);
  const referrer = normalize(input.referrer);

  if (referrer.includes("reddit.com/r/restaurateur")) {
    return { qualified: true, sourceChannel: "reddit_restaurateur" };
  }

  if (ASSOCIATION_DOMAINS.some((domain) => referrer.includes(domain))) {
    return { qualified: true, sourceChannel: "association" };
  }

  if (source === "meta" && RESTAURANT_INTENT_TERMS.some((term) => campaign.includes(term))) {
    return { qualified: true, sourceChannel: "meta_restaurant" };
  }

  if (source === "google" && medium === "cpc" && RESTAURANT_INTENT_TERMS.some((term) => campaign.includes(term))) {
    return { qualified: true, sourceChannel: "google_intent" };
  }

  if (medium === "cpc" || medium === "paid") {
    // Paid traffic that didn't match a restaurant-operator campaign signature.
    return { qualified: false, sourceChannel: "other_paid" };
  }

  // Direct visits, generic organic search, and unrecognized referrers.
  return { qualified: false, sourceChannel: null };
}

function normalize(value: string | undefined): string {
  return (value ?? "").trim().toLowerCase();
}
