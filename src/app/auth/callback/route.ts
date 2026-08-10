import { NextResponse } from "next/server";
import { z } from "zod";
import { createServerSupabaseClient } from "@/lib/supabase-server";
import { trackServerEvent } from "@/lib/analytics-server";

export const dynamic = "force-dynamic";

// PKCE codes are URL-safe base64, typically 40-200 chars. Cap generously.
const codeSchema = z.string().min(20).max(512).regex(/^[A-Za-z0-9_-]+$/);

// New-user recency window (ms) for activate-stage event firing. Covers OAuth
// and magic-link signups (user.created_at is set during the handshake) and
// prompt-email-confirm signups; skips password-reset and returning users.
const SIGNUP_RECENCY_MS = 60_000;

/** First authenticated surface; renders the carried score (b-03). */
const DEFAULT_DESTINATION = "/dashboard";
/** Where an unusable link lands. src/app/login/login-form.tsx reads `error`. */
const FAILURE_DESTINATION = "/login?error=auth";

/**
 * The origin every redirect out of this route is built on.
 *
 * `request.url` is reconstructed by the framework from the Host /
 * X-Forwarded-Host headers, which are client-supplied — deriving the post-auth
 * destination from them hands the redirect target to anything that can set a
 * header in front of the app. NEXT_PUBLIC_SITE_URL is deploy-time config and
 * therefore trusted; the request origin is only a fallback so that localhost
 * and preview deployments (where it is unset) still work. Same rule as
 * /api/checkout, /api/notices/send and the Stripe webhook.
 */
function siteOrigin(request: Request): string {
  const configured = process.env.NEXT_PUBLIC_SITE_URL;
  if (configured) {
    try {
      // `.origin` also drops the trailing slash env values are often pasted with.
      return new URL(configured).origin;
    } catch {
      // Malformed config must not take sign-in down with it.
    }
  }
  return new URL(request.url).origin;
}

/**
 * Resolves `?next=` to a destination that cannot leave this site.
 *
 * The parameter is part of a link the user clicks from an email or from
 * Google's consent screen, so it is fully attacker-composable, and a redirector
 * that honours it turns a tipguard.app URL into a phishing hop. The three
 * bypasses a naive check misses:
 *   - `//evil.example` is protocol-relative — a host, not a path.
 *   - `/\evil.example` is the same thing: browsers normalize `\` to `/` while
 *     resolving, so the guard has to reject the backslash form outright.
 *   - `%2f%2fevil.example` is already decoded by `searchParams.get()`, so the
 *     check must run on the decoded value (it does — this takes `raw` from
 *     searchParams, never from the raw query string).
 * Resolution against the site origin plus an origin comparison is the backstop
 * that covers anything not enumerated above.
 */
function safeDestination(raw: string | null, origin: string): URL {
  const fallback = new URL(DEFAULT_DESTINATION, origin);
  if (!raw || !raw.startsWith("/") || raw.startsWith("//") || raw.includes("\\")) {
    return fallback;
  }
  try {
    const resolved = new URL(raw, origin);
    return resolved.origin === fallback.origin ? resolved : fallback;
  } catch {
    return fallback;
  }
}

/**
 * Exchanges PKCE authorization codes for sessions: email confirmation
 * auto-login, Google OAuth, and password reset all land here.
 *
 * ── b-03 / the anonymous score handoff ────────────────────────────────────
 * The free /score result is parked in **localStorage** under
 * `tipguard.pending_score.v1` (see `src/app/score/pending-score.ts`). This is
 * a server route handler: it has no access to localStorage, so it CANNOT
 * attach the score itself.
 *
 * The claim therefore happens on the first authenticated page render, in
 * `<PendingScoreClaim />` (mounted once in `src/app/layout.tsx`), which reads
 * the pending record, POSTs it to `/api/account/score`, and calls
 * `clearPendingScore()` only after a confirmed 200. That covers BOTH legs:
 *   - email/password: `/signup` posts it directly once the session exists,
 *     and the claim component is a harmless no-op afterwards.
 *   - Google OAuth: the browser has left `/signup` entirely by the time the
 *     session is created here, so the component landing on `/dashboard` is
 *     the ONLY thing that can attach it. Without it every OAuth signup
 *     silently loses the score that h-03 measures.
 * Both paths are idempotent — `/api/account/score` ignores a stale record.
 */
export async function GET(request: Request) {
  if (process.env.DEMO_MODE === "true" && process.env.VERCEL === "1") {
    throw new Error("DEMO_MODE is not allowed in production");
  }

  const { searchParams } = new URL(request.url);
  const origin = siteOrigin(request);
  const destination = safeDestination(searchParams.get("next"), origin);
  const failure = new URL(FAILURE_DESTINATION, origin);

  if (process.env.DEMO_MODE === "true") {
    return NextResponse.redirect(destination);
  }

  const rawCode = searchParams.get("code");
  const parsedCode = rawCode ? codeSchema.safeParse(rawCode) : null;
  if (!parsedCode?.success) {
    // No code, or a value that cannot be one — never worth a round-trip to the
    // auth server.
    return NextResponse.redirect(failure);
  }

  // Everything below runs under one guard because a thrown error would
  // otherwise escape as an unhandled route exception: the owner clicked a link
  // in their inbox and would get a framework error page with nothing to retry.
  let sessionEstablished = false;
  try {
    const supabase = await createServerSupabaseClient();
    const { error } = await supabase.auth.exchangeCodeForSession(parsedCode.data);
    if (error) {
      console.error("[auth/callback] code exchange failed:", error.message);
      return NextResponse.redirect(failure);
    }

    // The session cookie is written from here on. Nothing below may divert the
    // user to /login: they ARE signed in, and the login form would either
    // bounce them straight back or look like it rejected a valid account.
    sessionEstablished = true;

    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (user && Date.now() - new Date(user.created_at).getTime() < SIGNUP_RECENCY_MS) {
      const provider = (user.app_metadata?.provider as string | undefined) ?? "email";
      await trackServerEvent("signup_complete", user.id, {
        auth_method: provider === "google" ? "google" : "email",
        funnel_stage: "activate",
      });
    }
  } catch (thrown) {
    console.error("[auth/callback] callback failed:", thrown);
    if (!sessionEstablished) return NextResponse.redirect(failure);
    // A signed-in owner losing their activation event is a reporting gap; a
    // signed-in owner losing the redirect is a broken product.
  }

  return NextResponse.redirect(destination);
}
