// posthog-js is loaded LAZILY via dynamic import inside init(). Static top-level
// import would pin the SDK (~60 kB gz) to every page's First Load JS via the
// analytics.ts → events.ts → page.tsx import chain. Events fired before the SDK
// finishes loading are queued in `pending[]` and replayed once init() resolves.
// Public API stays synchronous; callers don't await.

const PROJECT_NAME = "tipguard";
const PROJECT_OWNER = "magpiexyz-lab";
const POSTHOG_KEY = process.env.NEXT_PUBLIC_POSTHOG_KEY ?? "phc_TEAM_KEY";
const POSTHOG_HOST = "/ingest";
const POSTHOG_PLACEHOLDER = "phc_TEAM_KEY";

// Positive misconfiguration check — covers BOTH empty key and unreplaced placeholder.
// See ## Production Observability for the full contract and behavior matrix.
const isMisconfigured = !POSTHOG_KEY || POSTHOG_KEY === POSTHOG_PLACEHOLDER;

// Hostname-based deployed-host detection. Works for any hosting platform without
// requiring NEXT_PUBLIC_* env injection. Excludes localhost, IPv6 loopback, and
// `*.local` mDNS hostnames so dev environments stay quiet. Vercel preview deploys
// are excluded via the additional NEXT_PUBLIC_VERCEL_ENV check (see init() below).
const isDeployedHost =
  typeof window !== "undefined" &&
  !["localhost", "127.0.0.1", "0.0.0.0", "[::1]"].includes(window.location.hostname) &&
  !window.location.hostname.endsWith(".local");

let warned = false;
function warnOnce() {
  if (warned) return;
  warned = true;
  console.error(
    "[analytics] PostHog is not configured for this deployment — events will not be sent. " +
    "Set NEXT_PUBLIC_POSTHOG_KEY in your hosting platform, OR replace 'phc_TEAM_KEY' in src/lib/analytics.ts."
  );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let posthog: any = null;
type PendingCall = (client: unknown) => void;
const pending: PendingCall[] = [];
type Status = "idle" | "loading" | "ready" | "failed";
let status: Status = "idle";

function flushPending() {
  if (!posthog) return;
  while (pending.length > 0) {
    const call = pending.shift();
    if (call) {
      try { call(posthog); } catch { /* per-event isolation */ }
    }
  }
}

function init(): void {
  if (status !== "idle") return;
  if (typeof window === "undefined") return;
  if (isMisconfigured) {
    if (isDeployedHost && process.env.NEXT_PUBLIC_VERCEL_ENV !== "preview") warnOnce();
    return;
  }
  status = "loading";
  // SDK is chunk-split by webpack — does NOT pin to First Load JS. The Test Blocking
  // section below shows preview-gated init flags that must live inside this options
  // object (NOT a top-level posthog.init call) since the call site is now lazy.
  const isPreviewOrDev = process.env.NEXT_PUBLIC_VERCEL_ENV !== "production";
  import("posthog-js")
    .then((mod) => {
      posthog = mod.default;
      posthog.init(POSTHOG_KEY, {
        api_host: POSTHOG_HOST,
        capture_pageview: false,
        capture_exceptions: true,
        // The /sign signing link carries the RAW single-use token in its query
        // string, and it is the entire authorization for the only public write
        // endpoint in the app. PostHog stamps $current_url on EVERY event — not
        // just $pageview — so `capture_pageview: false` does not protect it, and
        // <RetainTracker /> fires on mount of /sign, i.e. while the token is
        // still unused. Without this, live tokens land in a PostHog project
        // shared across experiments, where anyone with read access could replay
        // one and file a forged signature. Strip the token before any event
        // leaves the browser.
        sanitize_properties: (properties: Record<string, unknown>) => {
          for (const key of ["$current_url", "$referrer", "$initial_current_url", "$pathname"]) {
            const value = properties[key];
            if (typeof value !== "string" || !value.includes("token")) continue;
            try {
              const url = new URL(value, window.location.origin);
              if (!url.searchParams.has("token")) continue;
              url.searchParams.set("token", "[redacted]");
              properties[key] = value.startsWith("http")
                ? url.toString()
                : `${url.pathname}${url.search}${url.hash}`;
            } catch {
              // Unparseable — drop rather than risk shipping the token.
              properties[key] = "[redacted]";
            }
          }
          return properties;
        },
        ...(isPreviewOrDev && {
          disable_compression: true, // Force XHR transport (Playwright cannot intercept sendBeacon)
          request_batching: false,   // Force immediate per-event XHR (batching delays events past assertion time)
        }),
        // Read paid-attribution params captured by the synchronous inline
        // <Script id="capture-paid-attribution"> in src/app/layout.tsx
        // (see framework/nextjs.md "Paid-attribution capture" section).
        // That script runs BEFORE React hydration so `?gclid=` is read from
        // the URL even if Next.js router later strips it via replaceState.
        // PostHog's own `$session_entry_gclid` capture races URL cleanup and
        // frequently loses. This `properties.gclid` super-property is the
        // reliable fallback.
        // Match the rest of analytics.ts (which holds `posthog: any`) — narrower
        // types here would require importing posthog-js types statically, which
        // defeats the lazy-import goal.
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        loaded: (ph: any) => {
          // Session super-property: stamps project identity on EVERY event this
          // session emits — including SDK auto-events ($pageleave, $web_vitals,
          // $autocapture, $exception, $identify) that bypass track()'s per-event
          // enrichment and would otherwise land in the shared PostHog project
          // with no owner. register_for_session, NOT register: sessionStorage is
          // origin-scoped, so identity can never leak across subdomain deploys
          // through the eTLD+1 cookie fallback, and a project rename never
          // leaves a stale persisted value. Outside the try below — it must not
          // be skipped when sessionStorage is unavailable.
          ph.register_for_session({ project_name: PROJECT_NAME, project_owner: PROJECT_OWNER });
          try {
            const g = sessionStorage.getItem("__ph_gclid");
            if (g) ph.register({ gclid: g });
            ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"].forEach((k) => {
              const v = sessionStorage.getItem("__ph_" + k);
              if (v) ph.register({ [k]: v });
            });
          } catch {
            // sessionStorage unavailable (private mode, sandboxed iframe); skip silently
          }
        },
      });
      status = "ready";
      flushPending();
    })
    .catch((err) => {
      status = "failed";
      pending.length = 0;
      // Loud-fail: a load failure (offline, CDN block, ad-blocker) means the
      // $exception channel that capture_exceptions: true would have used is
      // ALSO unavailable — operators must see the failure here or it stays silent.
      console.error("[analytics] posthog-js failed to load — events will be dropped:", err);
    });
}

// Test marker (sessionStorage) lives inside track() rather than per-wrapper.
// Keeps the deterministic assertion target available even when callers use
// the bare `track(name, props)` API (no typed wrapper).
function writeTestMarker(event: string, properties: Record<string, unknown>) {
  if (typeof window === "undefined") return;
  try {
    sessionStorage.setItem(
      `analytics:${event}`,
      JSON.stringify({ timestamp: Date.now(), properties })
    );
  } catch { /* sessionStorage unavailable (e.g., private mode in some browsers) */ }
}

export function track(event: string, properties?: Record<string, unknown>) {
  init();
  if (isMisconfigured || status === "failed") return;
  const enriched = { ...properties, project_name: PROJECT_NAME, project_owner: PROJECT_OWNER };
  writeTestMarker(event, enriched);
  if (status === "ready" && posthog) {
    posthog.capture(event, enriched);
    return;
  }
  pending.push((client: unknown) => (client as { capture: (e: string, p: unknown) => void }).capture(event, enriched));
}

export function identify(userId: string, traits?: Record<string, unknown>) {
  init();
  if (isMisconfigured || status === "failed") return;
  if (status === "ready" && posthog) {
    posthog.identify(userId, traits);
    return;
  }
  pending.push((client: unknown) => (client as { identify: (id: string, t?: unknown) => void }).identify(userId, traits));
}

export function reset() {
  init();
  if (isMisconfigured || status === "failed") return;
  if (status === "ready" && posthog) {
    posthog.reset();
    return;
  }
  pending.push((client: unknown) => (client as { reset: () => void }).reset());
}
