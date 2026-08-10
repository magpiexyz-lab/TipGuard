import { loadStripe } from "@stripe/stripe-js";

const STRIPE_PUBLISHABLE_PLACEHOLDER = "placeholder-stripe-publishable";
const stripeKey = process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY || STRIPE_PUBLISHABLE_PLACEHOLDER;

// Warn loudly when the placeholder fallback is hit on a deployed host.
// Stripe's `loadStripe()` does not surface a configuration error for an
// invalid publishable key — checkout silently fails when a user clicks
// "Pay" — so the warning has to come from this module at load time.
const isStripeMisconfigured = stripeKey === STRIPE_PUBLISHABLE_PLACEHOLDER;
const isDeployedHost =
  typeof window !== "undefined" &&
  !["localhost", "127.0.0.1", "0.0.0.0", "[::1]"].includes(window.location.hostname) &&
  !window.location.hostname.endsWith(".local");

if (isStripeMisconfigured && isDeployedHost && process.env.NEXT_PUBLIC_VERCEL_ENV !== "preview") {
  console.error(
    "[stripe-client] Stripe is not configured for this deployment — checkout will silently fail. " +
    "Set NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY in your hosting platform (Vercel → Settings → " +
    "Environment Variables) to a real `pk_test_*` or `pk_live_*` publishable key."
  );
}

// Use `||` (falsy check) rather than `??` so empty-string env values (common on
// CI/Vercel when a var is declared but unset) fall back to the placeholder
// instead of initializing Stripe.js with "" and crashing at load time.
export const stripePromise = isStripeMisconfigured ? null : loadStripe(stripeKey);
