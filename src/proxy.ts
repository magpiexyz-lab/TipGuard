import { NextResponse, type NextRequest } from "next/server";
import { createServerClient } from "@supabase/ssr";

// Canonical set from `python3 .claude/scripts/lib/derive_pages.py public_paths
// < experiment/experiment.yaml` — union of auth landing pages, /api/health,
// and behavior pages where every owning behavior declares anonymous_allowed: true.
const publicPaths = [
  "/",
  "/api/health",
  "/auth/callback",
  "/auth/reset-password",
  "/landing",
  "/login",
  // Reachable signed-out by necessity: Google's OAuth consent screen fetches
  // these URLs to publish the app, and a visitor deciding whether to hand over
  // a payroll roster must be able to read them before creating an account.
  "/privacy",
  // /score is deliberately NOT public. b-01/b-02 originally ran the
  // questionnaire anonymously; the owner moved the account ahead of the score
  // on 2026-08-24 so every interested operator is captured as a real contact.
  // derive_pages.py public_paths will keep emitting /score until b-02 loses its
  // anonymous_allowed flag in experiment.yaml, which this change also does.
  "/sign",
  "/signup",
  "/terms",
];

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Skip public paths, static files, API routes, analytics proxy, and variant routes
  if (
    publicPaths.some((p) => pathname === p) ||
    pathname.startsWith("/_next") ||
    pathname.startsWith("/api/") ||
    pathname.startsWith("/ingest/") ||
    pathname.startsWith("/v/") ||
    pathname.includes(".")
  ) {
    return NextResponse.next();
  }

  // Bypass auth in demo mode (no Supabase credentials available)
  if (process.env.NEXT_PUBLIC_DEMO_MODE === "true") {
    return NextResponse.next();
  }

  const response = NextResponse.next();
  // Use `||` (falsy check) not `!` (non-null assertion) — non-null assertions
  // pass through empty-string env values ("" is set but empty), causing the SDK
  // to initialize with "" and crash on the first cookie refresh.
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL || "https://placeholder.supabase.co",
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "placeholder-anon-key",
    {
      cookies: {
        getAll() { return request.cookies.getAll(); },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value, options }) => {
            response.cookies.set(name, value, options);
          });
        },
      },
    }
  );

  const { data: { user } } = await supabase.auth.getUser();
  if (!user) {
    // /score arrives from the landing CTA, so the visitor is almost always new.
    // Sending them to /login would ask them to sign in to an account they have
    // not created yet; every other gated page is somewhere you return to.
    const target = pathname === "/score" ? "/signup" : "/login";
    const redirectUrl = new URL(target, request.url);
    redirectUrl.searchParams.set("next", pathname);
    return NextResponse.redirect(redirectUrl);
  }

  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\..*).*)"],
};
