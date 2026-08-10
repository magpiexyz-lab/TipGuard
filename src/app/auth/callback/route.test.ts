// Unit tests for GET /auth/callback — behavior b-03.
//
// This route is the only place where a Supabase PKCE code becomes a session
// cookie. Every authenticated surface in the product is downstream of it, and
// it is reached by a link the user clicks from an email or from Google's
// consent screen — i.e. a URL an attacker can compose in full. Three things
// therefore have to hold, and they are what this file exists to protect:
//
//   * IT IS A REDIRECTOR, SO IT IS AN OPEN-REDIRECT CANDIDATE. `?next=` is
//     attacker-composable. A destination that leaves the site origin turns a
//     tipguard.app link into a credential-phishing hop that carries our
//     hostname in the address bar right up to the jump. Protocol-relative
//     (`//evil`), backslash (`/\evil`), percent-encoded (`%2f%2f`) and
//     scheme-bearing (`javascript:`) forms all have to be refused, not just
//     the obvious absolute URL.
//   * THE ORIGIN IT REDIRECTS TO MUST NOT COME FROM A HEADER. In a Next.js
//     route handler `request.url` is reconstructed from Host/X-Forwarded-Host,
//     which is client-supplied. NEXT_PUBLIC_SITE_URL is the trusted source —
//     the same rule /api/checkout, /api/notices/send and the Stripe webhook
//     already follow.
//   * NOTHING AFTER THE EXCHANGE MAY BREAK THE SIGN-IN. Once
//     exchangeCodeForSession() resolves, the session cookie is already being
//     written. If the analytics call or the getUser() lookup that follows it
//     throws, the user gets a 500 page while holding a live session — signed
//     in but told the product is broken, at the exact moment h-03 measures
//     activation.
//
// The b-03 score handoff itself is NOT this route's job and cannot be: the
// anonymous score lives in localStorage (src/app/score/pending-score.ts) and a
// server route handler cannot read it. This route's half of the contract is to
// land the user on /dashboard, where <PendingScoreClaim /> attaches it, and to
// take identity only from the exchanged session.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GET } from "./route";

const { createServerSupabaseClient, trackServerEvent } = vi.hoisted(() => ({
  createServerSupabaseClient: vi.fn(),
  trackServerEvent: vi.fn(),
}));

vi.mock("@/lib/supabase-server", () => ({ createServerSupabaseClient }));
vi.mock("@/lib/analytics-server", () => ({ trackServerEvent }));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

/** Shape of a Supabase PKCE code: a v4 UUID, 36 URL-safe characters. */
const VALID_CODE = "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d";

const SESSION_USER = {
  id: "11111111-1111-4111-8111-111111111111",
  email: "owner@restaurant.test",
  app_metadata: { provider: "google" },
  created_at: new Date().toISOString(),
};

/** The id an attacker would try to smuggle in through the query string. */
const ATTACKER_ID = "99999999-9999-4999-8999-999999999999";

/** What Next.js would reconstruct from the Host header. */
const REQUEST_ORIGIN = "https://request-host.test";
/** The trusted, deploy-time origin. */
const SITE_ORIGIN = "https://tipguard.app";

const exchangeCodeForSession = vi.fn();
const getUser = vi.fn();

interface SupabaseOptions {
  /** Returned (not thrown) exchange failure, as the SDK reports a bad code. */
  exchangeError?: { message: string } | null;
  /** Transport-level failure: the SDK rejects instead of resolving. */
  exchangeThrows?: Error;
  user?: Record<string, unknown> | null;
  getUserThrows?: Error;
  /** The client itself cannot be constructed (misconfigured deployment). */
  clientThrows?: Error;
}

function givenSupabase(options: SupabaseOptions = {}) {
  if (options.clientThrows) {
    const error = options.clientThrows;
    createServerSupabaseClient.mockImplementation(() => {
      throw error;
    });
    return;
  }

  exchangeCodeForSession.mockImplementation(async () => {
    if (options.exchangeThrows) throw options.exchangeThrows;
    return { data: {}, error: options.exchangeError ?? null };
  });

  getUser.mockImplementation(async () => {
    if (options.getUserThrows) throw options.getUserThrows;
    const user = options.user === undefined ? SESSION_USER : options.user;
    return { data: { user }, error: null };
  });

  createServerSupabaseClient.mockResolvedValue({
    auth: { exchangeCodeForSession, getUser },
  });
}

// ---------------------------------------------------------------------------
// Request helpers
// ---------------------------------------------------------------------------

interface CallOptions {
  /** Origin the framework derived from the Host header. */
  origin?: string;
  headers?: Record<string, string>;
}

function makeRequest(
  query: Record<string, string> = {},
  options: CallOptions = {}
) {
  const url = new URL("/auth/callback", options.origin ?? REQUEST_ORIGIN);
  for (const [key, value] of Object.entries(query)) {
    url.searchParams.set(key, value);
  }
  return new Request(url, { headers: options.headers });
}

function callback(query: Record<string, string> = {}, options: CallOptions = {}) {
  return GET(makeRequest(query, options));
}

/**
 * Calls the route with a raw query string, for values that must not survive a
 * URLSearchParams round-trip (pre-encoded `%2f`, a literal backslash).
 */
function callbackRaw(rawQuery: string, options: CallOptions = {}) {
  const target = `${options.origin ?? REQUEST_ORIGIN}/auth/callback?${rawQuery}`;
  return GET(new Request(target, { headers: options.headers }));
}

/** The parsed Location header. Fails loudly when the route did not redirect. */
function destination(response: Response): URL {
  const location = response.headers.get("location");
  expect(location).toBeTruthy();
  return new URL(location as string);
}

/** Runs the route and reports a thrown error instead of propagating it. */
async function attempt(
  query: Record<string, string>,
  options: CallOptions = {}
): Promise<{ response?: Response; thrown?: unknown }> {
  try {
    return { response: await callback(query, options) };
  } catch (thrown) {
    return { thrown };
  }
}

const ENV_KEYS = ["NEXT_PUBLIC_SITE_URL", "DEMO_MODE", "VERCEL"] as const;
const originalEnv: Record<string, string | undefined> = {};

beforeEach(() => {
  vi.resetAllMocks();
  for (const key of ENV_KEYS) originalEnv[key] = process.env[key];
  for (const key of ENV_KEYS) delete process.env[key];

  givenSupabase();
  // The route logs every failure path by design; keep the output readable.
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
  for (const key of ENV_KEYS) {
    if (originalEnv[key] === undefined) delete process.env[key];
    else process.env[key] = originalEnv[key];
  }
});

// ===========================================================================
// b-03 criterion: "Signup ... creates a Supabase session"
// b-03 criterion: "User is redirected to /dashboard after signup"
// ===========================================================================

describe("GET /auth/callback — the code exchange", () => {
  it("exchanges the code for a session and lands the new owner on /dashboard", async () => {
    const response = await callback({ code: VALID_CODE, next: "/dashboard" });

    expect(exchangeCodeForSession).toHaveBeenCalledTimes(1);
    expect(exchangeCodeForSession).toHaveBeenCalledWith(VALID_CODE);
    expect(response.status).toBeGreaterThanOrEqual(300);
    expect(response.status).toBeLessThan(400);
    expect(destination(response).pathname).toBe("/dashboard");
  });

  it("defaults to /dashboard when the link carries no next", async () => {
    // Both signup legs land here without a next in some flows; dropping the
    // user on the callback route itself would be a blank page.
    const response = await callback({ code: VALID_CODE });

    expect(destination(response).pathname).toBe("/dashboard");
  });

  it("sends the user to login with an error when the link carries no code", async () => {
    const response = await callback({ next: "/dashboard" });

    expect(exchangeCodeForSession).not.toHaveBeenCalled();
    const target = destination(response);
    expect(target.pathname).toBe("/login");
    expect(target.searchParams.get("error")).toBeTruthy();
  });

  it("refuses to exchange a code that is not shaped like a Supabase code", async () => {
    // The exchange call is a network round-trip against the auth server. A
    // value that cannot be a code should never reach it.
    const malformed = [
      "",
      "short",
      "a".repeat(513),
      "has spaces in it here",
      "<script>alert(1)</script>",
      "../../../etc/passwd",
      "a1b2c3d4.e5f6.4a7b.8c9d",
    ];

    for (const code of malformed) {
      exchangeCodeForSession.mockClear();
      const response = await callback({ code, next: "/dashboard" });

      expect(exchangeCodeForSession).not.toHaveBeenCalled();
      expect(destination(response).pathname).toBe("/login");
    }
  });

  it("sends the user to login when Supabase rejects the code", async () => {
    // Expired confirmation link, replayed code, wrong PKCE verifier.
    givenSupabase({ exchangeError: { message: "invalid request: code verifier" } });

    const response = await callback({ code: VALID_CODE, next: "/dashboard" });

    expect(destination(response).pathname).toBe("/login");
    expect(trackServerEvent).not.toHaveBeenCalled();
  });

  it("sends the user to login rather than 500ing when the exchange throws", async () => {
    // A rejected promise here escapes as an unhandled route exception. The
    // owner clicked a link in their inbox and gets a framework error page
    // instead of the login form they could retry from.
    givenSupabase({ exchangeThrows: new Error("fetch failed") });

    const outcome = await attempt({ code: VALID_CODE, next: "/dashboard" });

    expect(outcome.thrown).toBeUndefined();
    expect(destination(outcome.response as Response).pathname).toBe("/login");
  });

  it("sends the user to login rather than 500ing when the client cannot be built", async () => {
    givenSupabase({ clientThrows: new Error("supabase is not configured") });

    const outcome = await attempt({ code: VALID_CODE, next: "/dashboard" });

    expect(outcome.thrown).toBeUndefined();
    expect(destination(outcome.response as Response).pathname).toBe("/login");
  });

  it("never returns a 5xx on any exchange failure", async () => {
    const scenarios: SupabaseOptions[] = [
      { exchangeError: { message: "expired" } },
      { exchangeThrows: new Error("socket hang up") },
      { clientThrows: new Error("no url") },
      { getUserThrows: new Error("fetch failed") },
      { user: null },
    ];

    for (const scenario of scenarios) {
      vi.resetAllMocks();
      vi.spyOn(console, "error").mockImplementation(() => {});
      givenSupabase(scenario);

      const outcome = await attempt({ code: VALID_CODE });

      expect(outcome.thrown).toBeUndefined();
      expect((outcome.response as Response).status).toBeLessThan(500);
    }
  });

  it("does not leak the Supabase error text into the redirect", async () => {
    givenSupabase({
      exchangeError: { message: "invalid jwt for user 1111 with key sb_secret_abc" },
    });

    const response = await callback({ code: VALID_CODE });

    expect(destination(response).href).not.toContain("sb_secret");
  });
});

// ===========================================================================
// Open redirect — the `next` parameter is attacker-composable
// ===========================================================================

describe("GET /auth/callback — the destination cannot leave the site", () => {
  /**
   * Every form of "somewhere else" this route has to refuse. The backslash and
   * percent-encoded variants are the ones a naive `startsWith("//")` check
   * misses: browsers normalize `\` to `/` during URL resolution, and
   * `searchParams.get()` decodes `%2f` before the check ever sees it.
   */
  const HOSTILE_NEXT = [
    "https://evil.example/",
    "http://evil.example/dashboard",
    "//evil.example",
    "//evil.example/dashboard",
    "/\\evil.example",
    "/\\/evil.example",
    "\\\\evil.example",
    "javascript:alert(document.cookie)",
    "data:text/html,<script>alert(1)</script>",
    "https:/\\evil.example",
    "https://tipguard.app.evil.example/dashboard",
    "//user:pass@evil.example/",
  ];

  it("refuses every off-origin destination and falls back to /dashboard", async () => {
    for (const next of HOSTILE_NEXT) {
      const response = await callback({ code: VALID_CODE, next });
      const target = destination(response);

      expect(target.origin).toBe(REQUEST_ORIGIN);
      expect(target.pathname).toBe("/dashboard");
      expect(target.href).not.toContain("evil.example");
    }
  });

  it("refuses a percent-encoded protocol-relative destination", async () => {
    // `?next=%2f%2fevil.example` decodes to `//evil.example` before any check
    // runs, so a guard applied to the raw query string would let it through.
    const response = await callbackRaw(`code=${VALID_CODE}&next=%2F%2Fevil.example`);
    const target = destination(response);

    expect(target.origin).toBe(REQUEST_ORIGIN);
    expect(target.pathname).toBe("/dashboard");
  });

  it("refuses a backslash-prefixed destination sent unencoded", async () => {
    const response = await callbackRaw(`code=${VALID_CODE}&next=/\\evil.example`);

    expect(destination(response).origin).toBe(REQUEST_ORIGIN);
    expect(destination(response).href).not.toContain("evil.example");
  });

  it("honours a genuine same-origin path", async () => {
    // /auth/reset-password is a real destination: login-form.tsx sends the
    // password-reset link through this route with that next.
    for (const next of ["/dashboard", "/auth/reset-password", "/violations", "/staff"]) {
      const response = await callback({ code: VALID_CODE, next });
      const target = destination(response);

      expect(target.origin).toBe(REQUEST_ORIGIN);
      expect(target.pathname).toBe(next);
    }
  });

  it("preserves the query string of a same-origin destination", async () => {
    const response = await callback({ code: VALID_CODE, next: "/dashboard?upgraded=1" });
    const target = destination(response);

    expect(target.pathname).toBe("/dashboard");
    expect(target.searchParams.get("upgraded")).toBe("1");
  });

  it("keeps the failure redirect on-origin too", async () => {
    // The error path is reached by exactly the same attacker-composed link.
    givenSupabase({ exchangeError: { message: "expired" } });

    const response = await callback({ code: VALID_CODE, next: "https://evil.example/" });

    expect(destination(response).origin).toBe(REQUEST_ORIGIN);
  });

  it("never emits a Location header pointing at another host", async () => {
    // The catch-all: whatever the branch, the hostname the browser follows is
    // ours. This is the invariant; the cases above are the known bypasses.
    for (const next of [...HOSTILE_NEXT, "/dashboard", ""]) {
      for (const scenario of [{}, { exchangeError: { message: "expired" } }]) {
        vi.resetAllMocks();
        vi.spyOn(console, "error").mockImplementation(() => {});
        givenSupabase(scenario);

        const response = await callback({ code: VALID_CODE, next });

        expect(destination(response).host).toBe(new URL(REQUEST_ORIGIN).host);
      }
    }
  });
});

// ===========================================================================
// The redirect origin is deploy-time configuration, not a request header
// ===========================================================================

describe("GET /auth/callback — the redirect origin", () => {
  it("redirects to the configured site origin, not the request host", async () => {
    // In a Next.js route handler `request.url` is rebuilt from Host /
    // X-Forwarded-Host, both client-supplied. Deriving the post-auth
    // destination from them hands the redirect target to whoever can set a
    // header in front of the app.
    process.env.NEXT_PUBLIC_SITE_URL = SITE_ORIGIN;

    const response = await callback(
      { code: VALID_CODE, next: "/dashboard" },
      {
        origin: "https://attacker.test",
        headers: { host: "attacker.test", "x-forwarded-host": "attacker.test" },
      }
    );
    const target = destination(response);

    expect(target.origin).toBe(SITE_ORIGIN);
    expect(target.href).not.toContain("attacker.test");
  });

  it("keeps the failure redirect on the configured site origin", async () => {
    process.env.NEXT_PUBLIC_SITE_URL = SITE_ORIGIN;
    givenSupabase({ exchangeError: { message: "expired" } });

    const response = await callback({ code: VALID_CODE }, { origin: "https://attacker.test" });

    expect(destination(response).origin).toBe(SITE_ORIGIN);
    expect(destination(response).pathname).toBe("/login");
  });

  it("tolerates a trailing slash on NEXT_PUBLIC_SITE_URL", async () => {
    // Vercel env values are routinely pasted with one. `${site}${next}` would
    // produce "https://tipguard.app//dashboard" — a protocol-relative path in
    // any context that later resolves it relatively.
    process.env.NEXT_PUBLIC_SITE_URL = "https://tipguard.app/";

    const response = await callback({ code: VALID_CODE, next: "/dashboard" });

    expect(destination(response).href).toBe("https://tipguard.app/dashboard");
  });

  it("falls back to the request origin when no site url is configured", async () => {
    // Without the fallback, localhost and preview deployments would redirect
    // to "undefined/dashboard" and every sign-in would dead-end.
    const response = await callback({ code: VALID_CODE }, { origin: "http://localhost:3000" });

    expect(destination(response).origin).toBe("http://localhost:3000");
  });

  it("falls back rather than throwing when NEXT_PUBLIC_SITE_URL is malformed", async () => {
    process.env.NEXT_PUBLIC_SITE_URL = "tipguard.app";

    const outcome = await attempt({ code: VALID_CODE });

    expect(outcome.thrown).toBeUndefined();
    expect(destination(outcome.response as Response).pathname).toBe("/dashboard");
  });
});

// ===========================================================================
// b-03 criterion: "The pre-signup score and gap list persist onto the new
// account row and render on /dashboard"
//
// This route cannot read localStorage, so its half of the contract is (a) land
// on the surface where <PendingScoreClaim /> runs and (b) never take identity
// from anything the visitor controls.
// ===========================================================================

describe("GET /auth/callback — the pending-score handoff", () => {
  it("lands an OAuth signup on /dashboard, where the pending score is claimed", async () => {
    // src/components/pending-score-claim.tsx skips "/", "/sign", "/login",
    // "/score" and "/v/*". Redirecting a signup to any of those would silently
    // lose the score that h-03 is measured on.
    const unclaimable = ["/", "/sign", "/login", "/score"];

    const response = await callback({ code: VALID_CODE });
    const target = destination(response);

    expect(target.pathname).toBe("/dashboard");
    expect(unclaimable).not.toContain(target.pathname);
  });

  it("takes the identity it reports from the exchanged session, never the query", async () => {
    // The score is attached to whoever the session says you are. If a query
    // parameter could name the account, a crafted link would write one
    // visitor's score onto another owner's file.
    const response = await callback({
      code: VALID_CODE,
      user_id: ATTACKER_ID,
      distinct_id: ATTACKER_ID,
      account_id: ATTACKER_ID,
    });

    expect(getUser).toHaveBeenCalledTimes(1);
    expect(trackServerEvent).toHaveBeenCalledTimes(1);
    const [, distinctId] = trackServerEvent.mock.calls[0];
    expect(distinctId).toBe(SESSION_USER.id);
    expect(destination(response).href).not.toContain(ATTACKER_ID);
  });

  it("does not carry score or gap data supplied in the callback url", async () => {
    // The only trusted copy of the score is the one in the browser's
    // localStorage, posted to /api/account/score by the claim component.
    const response = await callback({
      code: VALID_CODE,
      readiness_score: "100",
      gap_list: "[]",
    });

    const forwarded = destination(response);
    expect(forwarded.searchParams.get("readiness_score")).toBeNull();
    expect(forwarded.searchParams.get("gap_list")).toBeNull();
    const [, , properties] = trackServerEvent.mock.calls[0];
    expect(properties).not.toHaveProperty("readiness_score");
  });
});

// ===========================================================================
// signup_complete — the activate-stage event (EVENTS.yaml)
// ===========================================================================

describe("GET /auth/callback — signup_complete", () => {
  it("fires once for a brand-new Google account", async () => {
    await callback({ code: VALID_CODE });

    expect(trackServerEvent).toHaveBeenCalledTimes(1);
    const [event, distinctId, properties] = trackServerEvent.mock.calls[0];
    expect(event).toBe("signup_complete");
    expect(distinctId).toBe(SESSION_USER.id);
    expect(properties).toMatchObject({
      auth_method: "google",
      funnel_stage: "activate",
    });
  });

  it("reports email for a confirmation-link signup", async () => {
    givenSupabase({
      user: { ...SESSION_USER, app_metadata: { provider: "email" } },
    });

    await callback({ code: VALID_CODE });

    expect(trackServerEvent.mock.calls[0][2]).toMatchObject({ auth_method: "email" });
  });

  it("reports one of the two values EVENTS.yaml allows for an unknown provider", async () => {
    // EVENTS.yaml pins auth_method to "email | google". A raw provider string
    // ("azure", "github") would create an off-contract value in the funnel.
    givenSupabase({
      user: { ...SESSION_USER, app_metadata: { provider: "azure" } },
    });

    await callback({ code: VALID_CODE });

    expect(["email", "google"]).toContain(
      (trackServerEvent.mock.calls[0][2] as { auth_method: string }).auth_method
    );
  });

  it("does not fire for a returning user signing in", async () => {
    // Every login and every password reset comes through this route. Firing
    // signup_complete for them would inflate the activate stage of h-03 with
    // people who signed up weeks ago.
    givenSupabase({
      user: { ...SESSION_USER, created_at: "2026-01-01T00:00:00.000Z" },
    });

    await callback({ code: VALID_CODE });

    expect(trackServerEvent).not.toHaveBeenCalled();
  });

  it("does not fire when the exchange produced no user", async () => {
    givenSupabase({ user: null });

    const response = await callback({ code: VALID_CODE });

    expect(trackServerEvent).not.toHaveBeenCalled();
    expect(destination(response).pathname).toBe("/dashboard");
  });

  it("does not fire when the code was never exchanged", async () => {
    await callback({ next: "/dashboard" });

    expect(trackServerEvent).not.toHaveBeenCalled();
  });
});

// ===========================================================================
// A session that exists must not be thrown away by a downstream failure
// ===========================================================================

describe("GET /auth/callback — nothing after the exchange breaks the sign-in", () => {
  it("still redirects to the destination when analytics fails", async () => {
    // The session cookie is written by exchangeCodeForSession(). A PostHog
    // outage after that point would hand a signed-in owner a 500 page.
    trackServerEvent.mockRejectedValue(new Error("posthog unreachable"));

    const outcome = await attempt({ code: VALID_CODE, next: "/dashboard" });

    expect(outcome.thrown).toBeUndefined();
    expect(destination(outcome.response as Response).pathname).toBe("/dashboard");
  });

  it("still redirects to the destination when the user lookup fails", async () => {
    givenSupabase({ getUserThrows: new Error("fetch failed") });

    const outcome = await attempt({ code: VALID_CODE, next: "/dashboard" });

    expect(outcome.thrown).toBeUndefined();
    expect(destination(outcome.response as Response).pathname).toBe("/dashboard");
  });

  it("does not send the user back to login after a successful exchange", async () => {
    // A half-established session — cookie set, but bounced to the login form —
    // is the most confusing possible outcome: the form would then redirect
    // them straight back in, or appear to reject a valid account.
    for (const scenario of [{ getUserThrows: new Error("boom") }, { user: null }]) {
      vi.resetAllMocks();
      vi.spyOn(console, "error").mockImplementation(() => {});
      givenSupabase(scenario);

      const response = await callback({ code: VALID_CODE });

      expect(destination(response).pathname).not.toBe("/login");
    }
  });
});

// ===========================================================================
// Demo mode
// ===========================================================================

describe("GET /auth/callback — demo mode", () => {
  it("lands on the dashboard without contacting Supabase", async () => {
    process.env.DEMO_MODE = "true";

    const response = await callback({ code: VALID_CODE });

    expect(createServerSupabaseClient).not.toHaveBeenCalled();
    expect(destination(response).pathname).toBe("/dashboard");
  });

  it("still refuses an off-origin destination in demo mode", async () => {
    process.env.DEMO_MODE = "true";

    const response = await callback({ code: VALID_CODE, next: "https://evil.example/" });

    expect(destination(response).origin).toBe(REQUEST_ORIGIN);
    expect(destination(response).pathname).toBe("/dashboard");
  });

  it("refuses to serve demo mode on a production deployment", async () => {
    // Demo mode fabricates a signed-in user. Serving it from a real deployment
    // would hand every visitor a session-shaped shell of somebody's file.
    process.env.DEMO_MODE = "true";
    process.env.VERCEL = "1";

    const outcome = await attempt({ code: VALID_CODE });

    expect(outcome.thrown).toBeInstanceOf(Error);
    expect((outcome.thrown as Error).message).toMatch(/DEMO_MODE/);
  });
});
