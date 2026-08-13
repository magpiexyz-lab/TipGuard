import { NextResponse } from "next/server";
import { createServerSupabaseClient } from "@/lib/supabase-server";
import { POSTHOG_HOST, POSTHOG_KEY } from "@/lib/analytics-server";

// Reads cookies via the Supabase server client — must never be prerendered.
export const dynamic = "force-dynamic";

const ANALYTICS_TIMEOUT_MS = 3_000;

/**
 * Deployment health endpoint (hosting/vercel.md § Health Check).
 *
 * The response body is ONLY `{ status }`. Per-subsystem keys, env-var presence
 * and raw error strings are deliberately withheld — an unauthenticated caller
 * must not be able to map our infrastructure (OWASP A4). Diagnostics go to the
 * server log.
 */
export async function GET() {
  const checks: Record<string, "ok" | "degraded" | "error"> = {};

  // --- database + auth (critical) ---
  try {
    const supabase = await createServerSupabaseClient();
    const { error } = await supabase.from("accounts").select("id").limit(1);
    if (error) {
      console.error("Health check database error:", error.message);
      checks.database = "error";
    } else {
      checks.database = "ok";
    }
  } catch (error) {
    console.error(
      "Health check database error:",
      error instanceof Error ? error.message : String(error)
    );
    checks.database = "error";
  }

  try {
    const supabase = await createServerSupabaseClient();
    // With no session this returns an auth error, not a network error. Either
    // outcome proves the auth service answered.
    await supabase.auth.getUser();
    checks.auth = "ok";
  } catch (error) {
    console.error(
      "Health check auth error:",
      error instanceof Error ? error.message : String(error)
    );
    checks.auth = "error";
  }

  // --- analytics (non-critical) ---
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), ANALYTICS_TIMEOUT_MS);
    try {
      const response = await fetch(`${POSTHOG_HOST}/decide?v=3`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: POSTHOG_KEY, distinct_id: "healthcheck" }),
        signal: controller.signal,
      });
      checks.analytics = response.ok ? "ok" : "error";
    } finally {
      clearTimeout(timer);
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error("Health check analytics error:", message);
    checks.analytics = message.includes("abort") ? "degraded" : "error";
  }

  // --- payment config (non-critical) ---
  const stripeKey = process.env.STRIPE_SECRET_KEY ?? "";
  if (stripeKey.startsWith("sk_")) {
    checks.payment = "ok";
  } else {
    console.error("Health check payment error: STRIPE_SECRET_KEY missing or malformed");
    checks.payment = "error";
  }

  const critical = Object.entries(checks).filter(([key]) =>
    ["database", "auth"].includes(key)
  );
  const hasCriticalFailure = critical.some(([, value]) => value === "error");

  return NextResponse.json(
    { status: hasCriticalFailure ? "degraded" : "ok" },
    { status: hasCriticalFailure ? 503 : 200 }
  );
}
