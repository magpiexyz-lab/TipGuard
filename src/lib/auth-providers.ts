/**
 * Which third-party sign-in providers are actually wired up.
 *
 * The Google code paths in `login-form.tsx` and `signup-form.tsx` are complete,
 * but the provider must ALSO be enabled on the Supabase project — otherwise
 * `signInWithOAuth({ provider: "google" })` bounces off the auth server with
 * `400 validation_failed: Unsupported provider: provider is not enabled` and
 * the user is left staring at an error on the primary auth path.
 *
 * Rendering the button is therefore gated on configuration, not on the code
 * existing. To turn it on: create the Google Cloud OAuth client with callback
 * `https://<ref>.supabase.co/auth/v1/callback`, enable Google in Supabase
 * (Authentication -> Sign In / Providers), then set this env var to "true"
 * and redeploy. Nothing else changes — the handlers are already there.
 */
export const GOOGLE_SIGN_IN_ENABLED =
  process.env.NEXT_PUBLIC_GOOGLE_SIGN_IN_ENABLED === "true";
