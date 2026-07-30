---
assumes: [framework/nextjs]  # @next/env loadEnvConfig used in scripts/check-analytics-env.mjs prebuild script
packages:
  runtime: [posthog-js, posthog-node]  # posthog-js conditional: only when framework is nextjs
  dev: []
files:
  - src/lib/analytics.ts  # conditional: only when framework is nextjs
  - src/lib/analytics-server.ts
  - src/lib/events.ts  # conditional: only when framework is nextjs
  - scripts/check-analytics-env.mjs  # prebuild guard, see ## Production Observability Layer 1
env:
  server: [POSTHOG_SERVER_KEY]
  client: [NEXT_PUBLIC_POSTHOG_KEY]
ci_placeholders: {}
clean:
  files: []
  dirs: []
gitignore: []
---
# Analytics: PostHog
> Used when experiment.yaml has `stack.analytics: posthog`

## Packages
```bash
npm install posthog-node
```
> When framework is nextjs, also install the client-side library:
```bash
npm install posthog-js
```

## Files to Create

### `src/lib/analytics.ts`
```ts
// posthog-js is loaded LAZILY via dynamic import inside init(). Static top-level
// import would pin the SDK (~60 kB gz) to every page's First Load JS via the
// analytics.ts → events.ts → page.tsx import chain. Events fired before the SDK
// finishes loading are queued in `pending[]` and replayed once init() resolves.
// Public API stays synchronous; callers don't await.

const PROJECT_NAME = "TODO"; // Replaced by bootstrap with kebab-case experiment.yaml `name` (^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$, enforced by /bootstrap state-3 — see .claude/scripts/lib/validate_experiment_yaml.py). Must NEVER be edited at runtime; identity stability across deploys depends on this constant being immutable for an MVP's lifetime.
const PROJECT_OWNER = "TODO"; // Replaced by bootstrap with experiment.yaml `owner`
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
        // frequently loses (foundrygraph 0.5%, pingback 14%, report-pilot 24%
        // in prod). This `properties.gclid` super-property is the reliable
        // fallback; /iterate --cross uses coalesce(both) so either path works.
        // Match the rest of analytics.ts (which holds `posthog: any`) — narrower
        // types here would require importing posthog-js types statically, which
        // defeats the lazy-import goal.
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        loaded: (ph: any) => {
          // Session super-property: stamps project identity on EVERY event this
          // session emits — including SDK auto-events ($pageleave, $web_vitals,
          // $autocapture, $exception, $identify) that bypass track()'s per-event
          // enrichment and would otherwise land in the shared PostHog project
          // with no owner (the __orphan_<host>__ rows in /iterate --cross).
          // register_for_session, NOT register: sessionStorage is origin-scoped,
          // so identity can never leak across subdomain deploys through the
          // eTLD+1 cookie fallback, and a project rename never leaves a stale
          // persisted value. Outside the try below — it must not be skipped
          // when sessionStorage is unavailable.
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
// the bare `track(name, props)` API (no typed wrapper). See `## Stack Knowledge
// > Testing analytics events deterministically (Playwright)` for usage.
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
```

Notes:
- `init()` is lazy — safe to import server-side, PostHog only initializes on first client-side call
- The SDK itself is also lazily LOADED (not just lazily INITIALIZED) — `import("posthog-js")` produces a separate webpack chunk and does NOT pin posthog-js to every page's First Load JS. Events fired during the load window queue in `pending[]` and replay on resolve.
- Load-failure semantics: when `import("posthog-js")` rejects (offline, CDN block, ad-blocker), `status` becomes `"failed"`, the queue is dropped, and all subsequent `track()`/`identify()`/`reset()` calls short-circuit — operators see the load failure via the `console.error` in the `.catch()` handler. Note that this also kills the `$exception` channel that `capture_exceptions: true` would otherwise use for runtime exception reporting.
- `capture_pageview: false` because pages fire explicit events via `events.ts`
- `capture_exceptions: true` sends unhandled JS errors and promise rejections to PostHog as `$exception` events — provides post-deploy error visibility without additional error tracking setup, but only when the SDK successfully loaded (see load-failure semantics above)
- The `writeTestMarker()` call inside `track()` records a deterministic sessionStorage entry per event — Playwright tests assert on these markers (see `## Stack Knowledge > Testing analytics events deterministically (Playwright)`) without racing the network. This works whether callers use the bare `track()` or a typed wrapper from `events.ts`.
- Bootstrap replaces `PROJECT_NAME` and `PROJECT_OWNER` with actual experiment.yaml values
- `POSTHOG_HOST` is `/ingest` on the client (proxied via Next.js rewrites to avoid ad blockers) and `https://us.i.posthog.com` on the server (direct, not affected by ad blockers). `POSTHOG_KEY` defaults to the **placeholder** `phc_TEAM_KEY`, which **must be replaced** before deploy — either by editing the constant directly (fork-once workflow) or by setting `NEXT_PUBLIC_POSTHOG_KEY` in your hosting platform's environment variables (per-project override). The placeholder being still present at deploy time is a misconfiguration; see `## Production Observability` for the three-layer fail-loud mechanism that catches it. PostHog `phc_` keys are publishable (write-only, safe for client-side embedding — same class as Stripe `pk_test_`).
- Global properties are placed after the spread so they can't be overridden by callers

### `src/lib/analytics-server.ts` — Server-side tracking (for webhooks and API routes)
```ts
import { PostHog } from "posthog-node";

const PROJECT_NAME = "TODO"; // Replaced by bootstrap with kebab-case experiment.yaml `name` (^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$, enforced by /bootstrap state-3 — see .claude/scripts/lib/validate_experiment_yaml.py). Must NEVER be edited at runtime; identity stability across deploys depends on this constant being immutable for an MVP's lifetime.
const PROJECT_OWNER = "TODO"; // Replaced by bootstrap with experiment.yaml `owner`
export const POSTHOG_KEY = process.env.POSTHOG_SERVER_KEY ?? process.env.NEXT_PUBLIC_POSTHOG_KEY ?? "phc_TEAM_KEY";
export const POSTHOG_HOST = "https://us.i.posthog.com";
const POSTHOG_PLACEHOLDER = "phc_TEAM_KEY";

const isMisconfigured = !POSTHOG_KEY || POSTHOG_KEY === POSTHOG_PLACEHOLDER;
// Server-side has full env access — gate on hosting-platform indicators.
// `VERCEL === "1"` is the canonical Vercel deploy indicator (see TEMPLATE.md).
// `RAILWAY_ENVIRONMENT_NAME` is the Railway equivalent. Add other host indicators here
// when introducing new hosting stack files.
const isHostingPlatform = process.env.VERCEL === "1" || !!process.env.RAILWAY_ENVIRONMENT_NAME;

if (isMisconfigured && isHostingPlatform) {
  console.error(
    "[analytics-server] PostHog is not configured for this deployment — server events will not be sent. " +
    "Set NEXT_PUBLIC_POSTHOG_KEY (or POSTHOG_SERVER_KEY) in your hosting platform, " +
    "or replace 'phc_TEAM_KEY' in src/lib/analytics-server.ts."
  );
}

export async function trackServerEvent(
  event: string,
  distinctId: string,
  properties?: Record<string, unknown>
) {
  if (isMisconfigured) return;
  const client = new PostHog(POSTHOG_KEY, {
    host: POSTHOG_HOST,
  });

  client.capture({
    distinctId,
    event,
    properties: {
      ...properties,
      project_name: PROJECT_NAME,
      project_owner: PROJECT_OWNER,
    },
  });

  await client.shutdown();
}
```

Notes:
- Creates a PostHog client per call and calls `shutdown()` to flush — required for serverless (Vercel)
- `POSTHOG_KEY` defaults to the placeholder `phc_TEAM_KEY` (must be replaced before deploy — see client-side notes above and `## Production Observability`). Optional override via `POSTHOG_SERVER_KEY` (server-only, takes precedence) or `NEXT_PUBLIC_POSTHOG_KEY` (shared with client). `POSTHOG_HOST` uses the direct PostHog URL since server-side requests are not affected by ad blockers. Both `POSTHOG_KEY` and `POSTHOG_HOST` are exported for use by the health check route.
- Auto-attaches `project_name` and `project_owner` like client-side `track()`
- Bootstrap replaces `PROJECT_NAME` and `PROJECT_OWNER` with actual experiment.yaml values
- Use this in webhook handlers and API routes for server-side events (e.g., `pay_success`)

### `src/lib/events.ts` — Typed event wrappers (generated by bootstrap from experiment/EVENTS.yaml)

Bootstrap dynamically generates this file from the `events` map in `experiment/EVENTS.yaml`.
For each event, it creates a typed wrapper function and an `EVENT_FUNNEL_MAP` constant.

**Generation rules:**
1. Read all events from `experiment/EVENTS.yaml` `events` map
2. Filter by `requires` (include only if the required stack key is present in experiment.yaml `stack`) and `archetypes` (include only if the archetype matches experiment.yaml `type`)
3. For each surviving event, generate a wrapper function:
   - Function name: `track` + PascalCase(event_name) (e.g., `invoice_created` → `trackInvoiceCreated`)
   - Props type: built from the event's `properties` map — `required: true` → mandatory, `required: false` → optional (`?`)
   - If ALL properties are optional (or no properties), the entire props parameter is optional (`props?: { ... }`)
   - Body: calls `track(event_name, { ...props, funnel_stage: "<funnel_stage>" })`
4. Generate `EVENT_FUNNEL_MAP` constant mapping every filtered event name to its `funnel_stage`
5. Group payment events (those with `requires: [payment]`) under a comment separator

**Example output** (for the default EVENTS.yaml — actual output depends on the experiment's EVENTS.yaml):
```ts
import { track } from "./analytics";

// --- Event funnel stage map (generated from experiment/EVENTS.yaml) ---

export const EVENT_FUNNEL_MAP: Record<string, string> = {
  visit_landing: "reach",
  signup_start: "demand",
  signup_complete: "demand",
  activate: "activate",
  retain_return: "retain",
  pay_start: "monetize",
  pay_success: "monetize",
} as const;

// --- Event wrappers (generated from experiment/EVENTS.yaml events map) ---

export function trackVisitLanding(props?: { variant?: string; referrer?: string; utm_source?: string; utm_medium?: string; utm_campaign?: string; gclid?: string; click_id?: string; utm_content?: string }) {
  track("visit_landing", { ...props, funnel_stage: "reach" });
}

export function trackSignupStart(props: { method: string }) {
  track("signup_start", { ...props, funnel_stage: "demand" });
}

// ... one wrapper per event, following the same pattern ...

// --- Payment events (only when requires: [payment] matched) ---

export function trackPayStart(props: { plan: string; amount_cents: number }) {
  track("pay_start", { ...props, funnel_stage: "monetize" });
}

export function trackPaySuccess(props: { plan: string; amount_cents: number; provider: string }) {
  track("pay_success", { ...props, funnel_stage: "monetize" });
}
```

Notes:
- Bootstrap generates this file dynamically from experiment/EVENTS.yaml. The example above illustrates the pattern for the default EVENTS.yaml; actual output depends on the experiment's events.
- Each wrapper auto-injects `funnel_stage` from the event's EVENTS.yaml definition into every `track()` call. Callers never pass `funnel_stage` manually.
- `EVENT_FUNNEL_MAP` exports the event-to-funnel-stage mapping for use by `/iterate` analysis tooling that needs to group events by funnel stage without re-parsing EVENTS.yaml.
- When all properties on an event are `required: false` (or the event has no properties), the wrapper's props parameter is optional (e.g., `trackVisitLanding(props?: { ... })`).
- Payment event functions (those where the EVENTS.yaml entry has `requires: [payment]`) are only included when `stack.payment` is present in experiment.yaml. Omit them otherwise.
- `trackPaySuccess` is exported for completeness but the webhook handler uses `trackServerEvent()` from `analytics-server.ts` instead (server-side). The client-side wrapper is available if a success page needs to track it.
- When events are added to EVENTS.yaml after bootstrap (via `/change` or `/distribute`), regenerate typed wrappers in `events.ts` for the new events.
- Pages import from `@/lib/events` instead of calling `track()` directly — this provides compile-time validation of event names and property types.

## Environment Variables

```
NEXT_PUBLIC_POSTHOG_KEY=phc_...   # client-side publishable key (optional override)
POSTHOG_SERVER_KEY=phc_...        # server-side key (optional override; defaults to client value)
```

Both are **optional overrides** for the source-level publishable key constant declared in the analytics library files. Before any project bootstrapped from this template can deploy to production, one of two workflows must satisfy the publishable key:

1. **Per-project env override (recommended for downstream forks):** set `NEXT_PUBLIC_POSTHOG_KEY` in your hosting platform (Vercel → Project → Settings → Environment Variables, or `vercel env add`) to your team's real publishable key. Optionally set `POSTHOG_SERVER_KEY` to a server-only key.
2. **Fork-once source replacement:** edit the analytics library files' constant directly with your team's real publishable key. All future bootstraps from your fork inherit the replaced value.

If neither is done, the prebuild script (see `## Production Observability` Layer 1) fails the deploy build, and the deployed code's runtime warnings (Layer 2) surface the misconfiguration in DevTools. All experiments share one PostHog project (filtered by `project_name`).

## Production Observability

PostHog failures in production must be **immediately visible** — not silent. This stack prescribes three layers of "fail loud" so misconfigurations surface at the earliest possible point in the deploy lifecycle.

### Layer 1 — Build-time prebuild check

Implemented by `scripts/check-analytics-env.mjs`, emitted by `scaffold-libs.md` Step 6.5 when `stack.analytics: posthog` is present. Wired into `package.json` via the `prebuild` lifecycle hook so it runs automatically before `npm run build`.

Logic:
1. **Skip-gate**: exit 0 when neither `process.env.CI === "1" && process.env.VERCEL === "1"` (Vercel CI build platform — `CI=1` distinguishes it from local `vercel build`) nor `process.env.RAILWAY_ENVIRONMENT_NAME` (Railway) is present. This keeps bootstrap and local builds passing.
2. **Env-override path**: if `NEXT_PUBLIC_POSTHOG_KEY` is set and not equal to `phc_TEAM_KEY` → exit 0 (env wins; source-level placeholder doesn't matter at runtime).
3. **Source-fallback path**: grep these specific paths only:
   - `src/lib/analytics.ts`
   - `src/lib/analytics-server.ts`
   - `src/app/route.ts` (service co-located surface)
   - `site/index.html` (cli detached surface)

   If any contains the literal `"phc_TEAM_KEY"` (single OR double-quoted) → exit 1 with an actionable error listing the files. Otherwise → exit 0 (source has been customized).

#### `scripts/check-analytics-env.mjs` (canonical source)

scaffold-libs emits this file verbatim into the project root when `stack.analytics: posthog`:

```js
#!/usr/bin/env node
// Validates analytics configuration before build, on hosting platforms only.
// Runs as `prebuild` lifecycle hook. Skips on bootstrap/local builds.

import nextEnv from "@next/env";
import fs from "node:fs";

// .mjs (raw Node ESM) requires DEFAULT-import + destructure for @next/env. The
// named-import form (`import { loadEnvConfig } from ...`) fails under Node 22
// raw ESM with `SyntaxError: Named export 'loadEnvConfig' not found` because
// Node's CJS named-export detection does not surface this package's exports.
// .ts files loaded by Playwright/jest/tsx (CJS-transpile via pirates) require
// the OPPOSITE shape — see "CJS-interop with @next/env" Stack Knowledge entry
// below for the per-loader contract.
const { loadEnvConfig } = nextEnv;

// Load .env.local / .env so local `npm run build` invocations see the same
// NEXT_PUBLIC_POSTHOG_KEY override that Next.js itself uses. On Vercel build
// platforms env vars are already populated, so this is a no-op there.
loadEnvConfig(process.cwd());

// Skip-gate: only run on real Vercel/Railway build platforms.
// `process.env.CI === "1"` distinguishes Vercel CI builds from local `vercel build`,
// which also sets VERCEL=1 but not CI=1.
const isVercelBuildPlatform = process.env.CI === "1" && process.env.VERCEL === "1";
const isRailwayBuildPlatform = !!process.env.RAILWAY_ENVIRONMENT_NAME;
if (!isVercelBuildPlatform && !isRailwayBuildPlatform) process.exit(0);

const PLACEHOLDER = "phc_TEAM_KEY";
const envKey = process.env.NEXT_PUBLIC_POSTHOG_KEY ?? "";

// Path 1: env override is valid → pass.
if (envKey && envKey !== PLACEHOLDER) process.exit(0);

// Path 2: env unset/placeholder → check if source has a real fallback.
const SOURCE_PATHS = [
  "src/lib/analytics.ts",
  "src/lib/analytics-server.ts",
  "src/app/route.ts",   // service co-located surface
  "site/index.html",    // cli detached surface
];

const filesWithPlaceholder = SOURCE_PATHS
  .filter(p => fs.existsSync(p))
  .filter(p => {
    const src = fs.readFileSync(p, "utf8");
    return src.includes(`"${PLACEHOLDER}"`) || src.includes(`'${PLACEHOLDER}'`);
  });

if (filesWithPlaceholder.length === 0) process.exit(0);  // source customized → pass

console.error(`\n[analytics] PostHog is not configured for this deployment.`);
console.error(`Files still containing the '${PLACEHOLDER}' placeholder:`);
for (const p of filesWithPlaceholder) console.error(`  - ${p}`);
console.error(`\nFix one of:`);
console.error(`  1. Set NEXT_PUBLIC_POSTHOG_KEY in your hosting platform`);
console.error(`     (Vercel → Project → Settings → Environment Variables).`);
console.error(`  2. Replace '${PLACEHOLDER}' in the listed source files with`);
console.error(`     your team's PostHog publishable key (phc_xxx).\n`);
process.exit(1);
```

### Layer 2 — Runtime module-load validator

The `isMisconfigured` constant in both `analytics.ts` and `analytics-server.ts` (computed at module load) catches BOTH empty key and unreplaced placeholder cases. When `isMisconfigured` is true:
- **Client (`analytics.ts`)**: `console.error`-once via `warnOnce()` on deployed hostnames (excluding `localhost`, `127.0.0.1`, `0.0.0.0`, `[::1]`, `*.local`). Vercel preview deploys are also excluded via `process.env.NEXT_PUBLIC_VERCEL_ENV !== "preview"` to avoid noisy preview-smoke logs.
- **Server (`analytics-server.ts`)**: `console.error`-once at module load when `process.env.VERCEL === "1"` or `process.env.RAILWAY_ENVIRONMENT_NAME` is set.
- **CLI**: `console.error`-once inside `isAnalyticsEnabled()` so it surfaces in published CLI binaries (where `VERCEL` and `RAILWAY_ENVIRONMENT_NAME` are absent).

`init()`, `track()`, `identify()`, `reset()`, and `trackServerEvent()` all short-circuit on `isMisconfigured` so no PostHog SDK calls are attempted with a bogus key.

### Layer 3 — `/distribute` STATE 2 pre-flight static grep

Before launching paid distribution, `/distribute` STATE 2 step "2.0 Static placeholder check" runs an archetype-aware grep over the same path set as Layer 1 and STOPS with an actionable error if `phc_TEAM_KEY` is still present. This catches the misconfiguration before ad spend, complementing Layer 1 (which catches at build) and Layer 2 (which catches at first page-load).

See `.claude/skills/distribute/state-2-validate-analytics.md` for the exact step.

### Behavior matrix

| Source-level constant | `NEXT_PUBLIC_POSTHOG_KEY` env | Resolved `POSTHOG_KEY` | `init()` runs? | Warning fires? |
|---|---|---|---|---|
| `phc_TEAM_KEY` (unconfigured fork) | unset | `phc_TEAM_KEY` | no | yes (deployed hosts) |
| `phc_TEAM_KEY` (unconfigured fork) | `""` (set-but-empty) | `""` | no | yes (deployed hosts) |
| `phc_TEAM_KEY` (unconfigured fork) | real `phc_xxx` key | real key | yes | no |
| `phc_REAL_xxx` (replaced fork) | unset | `phc_REAL_xxx` | yes | no |
| `phc_REAL_xxx` (replaced fork) | real `phc_yyy` key | real key (env wins) | yes | no |
| `phc_REAL_xxx` (replaced fork) | `""` (set-but-empty) | `""` | no | yes (deployed hosts) |

### Prebuild composition with other stacks

`scaffold-libs.md` owns the `prebuild` entry in `package.json` (see `database/supabase.md` Migration Setup). When multiple stacks contribute prebuild work, scaffold-libs composes them via `&&`-chained, defensively-guarded segments:

```json
{
  "scripts": {
    "prebuild": "(test ! -f scripts/auto-migrate.mjs || node scripts/auto-migrate.mjs) && (test ! -f scripts/check-analytics-env.mjs || node scripts/check-analytics-env.mjs)"
  }
}
```

Each segment uses `test ! -f X || node X` to no-op when its script is absent (intermediate bootstrap states stay safe). Any non-zero exit propagates and fails the build. The order matters when one stack's check depends on another's effects (analytics check after migrations, since neither writes to the other's surface but the convention is "infrastructure first, then config").

## Reverse Proxy Setup
Client-side analytics use `/ingest` as the API host to bypass ad blockers that filter `us.i.posthog.com`. Bootstrap adds these rewrites AND a client-side `VERCEL_ENV` injection to `next.config.ts`:

```ts
const nextConfig: NextConfig = {
  env: {
    // Inject Vercel's deploy-environment indicator into the client bundle.
    // Vercel does NOT auto-prefix system env vars with NEXT_PUBLIC_, so without
    // this block client-side `process.env.NEXT_PUBLIC_VERCEL_ENV` is undefined
    // and the disable_compression production gate (## Test Blocking) fails open.
    // `?? ""` keeps this defined-but-empty on non-Vercel builds (local dev,
    // bootstrap) so gates fall through cleanly.
    NEXT_PUBLIC_VERCEL_ENV: process.env.VERCEL_ENV ?? "",
  },
  async rewrites() {
    return [
      { source: "/ingest/decide", destination: "https://us.i.posthog.com/decide" },
      { source: "/ingest/:path*", destination: "https://us.i.posthog.com/:path*" },
    ];
  },
  skipTrailingSlashRedirect: true,
};
```

Notes:
- `skipTrailingSlashRedirect` is required — without it, Next.js redirects `/ingest/e` to `/ingest/e/` before the rewrite applies, breaking the proxy
- Server-side tracking (`analytics-server.ts`) still uses the direct PostHog URL — rewrites only apply to client-side browser requests
- This is PostHog's officially recommended approach for avoiding ad blockers
- The `env` block is the **only way** to make Vercel system env vars visible to client code. Vercel injects `VERCEL_ENV` server-side automatically; this block re-exports it under the `NEXT_PUBLIC_` prefix that Next.js requires for client-bundle inlining. Removing this block breaks the disable_compression gate (## Test Blocking) AND the client-side preview-deploy filter in the warn-once gate (analytics.ts).

### Cross-stack contract: auth middleware must whitelist `/ingest/`

When `stack.auth` is present AND the project uses client-side PostHog (`stack.analytics: posthog` + `type: web-app`), the auth stack's route-protection middleware MUST include `pathname.startsWith("/ingest/")` in its skip list. Otherwise the middleware sees unauthenticated PostHog event POSTs from top-of-funnel pages (landing, demo, signup) and 307-redirects them to `/login?next=/ingest/...` — since `/login` handles GET only, it returns **405 Method Not Allowed**. Every client-side analytics event from unauthenticated visitors fails silently in production, making funnel metrics like `visit_landing → signup_start` impossible to measure.

- `auth/supabase.md` already whitelists `/ingest/` in its route-protection template — look for the `pathname.startsWith("/ingest/")` entry beside the other startsWith checks.
- Any new auth stack file authoring its own route-protection template must replicate this skip-list entry. The PostHog proxy only works end-to-end when `next.config.ts` (rewrite rule) AND the route-protection file (`src/proxy.ts` on Next.js 16+ — today's default per the filename↔export-name invariant documented at `.claude/stacks/framework/nextjs.md` Stack Knowledge; auth skip list) agree on the `/ingest/` prefix.
- This cross-file contract exists because both files are independently authored by their respective stacks; changing the proxy prefix requires coordinated edits in both. (See issue #983 for the failure mode when the contract was silently broken.)

## When framework is NOT nextjs (server-only analytics)

For non-Next.js frameworks (Hono, Commander, Virtuals-ACP, etc.), only server-side
analytics are generated. Client-side tracking (`posthog-js`, `analytics.ts`,
`events.ts`, Reverse Proxy Setup) does not apply — these frameworks have no
browser context.

**Packages:** Install only `posthog-node` (skip `posthog-js`).

**Files:** Generate only `src/lib/analytics-server.ts` (same template as above).
Skip `src/lib/analytics.ts` and `src/lib/events.ts`.

**All tracking uses `trackServerEvent()`** from `analytics-server.ts`. There are
no typed event wrappers — call `trackServerEvent(eventName, distinctId, properties)`
directly for all events defined in experiment/EVENTS.yaml.

### CLI Opt-In Consent

When the archetype is `cli`, analytics must be opt-in per the CLI archetype
contract. Wrap all `trackServerEvent()` calls in a consent check that ALSO
surfaces misconfiguration to end users (CLI binaries don't have a hosting
platform indicator like `VERCEL=1`, so the module-load `console.error` in
`analytics-server.ts` won't fire — the warning has to live here).

```ts
let cliWarned = false;
function isAnalyticsEnabled(): boolean {
  if (process.env.DO_NOT_TRACK === "1") return false;
  if (process.env.<CLI_NAME>_TELEMETRY_OPTOUT === "1") return false;
  if (isMisconfigured) {
    if (!cliWarned) {
      cliWarned = true;
      console.error(
        "[analytics] CLI analytics is enabled but the PostHog key is missing or unreplaced. " +
        "Events will not be sent. Replace 'phc_TEAM_KEY' in src/lib/analytics-server.ts before publishing."
      );
    }
    return false;
  }
  return true;
}
```

Replace `<CLI_NAME>` with the uppercase experiment name (e.g., `QUICKBILL`).
Bootstrap generates this helper in `src/lib/analytics-server.ts` for CLI
projects and wraps `trackServerEvent()` so callers don't need to check
manually:

```ts
export async function trackServerEvent(
  event: string,
  distinctId: string,
  properties?: Record<string, unknown>
) {
  if (!isAnalyticsEnabled()) return;
  // ... existing PostHog capture logic
}
```

The `cliWarned` flag is module-scoped so the warning fires at most once per CLI
process even when `trackServerEvent()` is called repeatedly. The check happens
inside `isAnalyticsEnabled()` (not at module load) because module-load
`console.error` would also fire when the user opted out — annoying for opted-out
users who don't care about analytics being misconfigured.

The `DO_NOT_TRACK` env var follows the [Console Do Not Track](https://consoledonottrack.com/)
standard. The project-specific `<CLI_NAME>_TELEMETRY_OPTOUT` provides a
per-tool opt-out. Both default to tracking-enabled (absent = opt-in).

**Reverse Proxy Setup:** Skip — no client-side requests to proxy.

**`next.config.ts` rewrites:** Not applicable — no Next.js config file.

## Patterns
- Client-side tracking goes through `src/lib/analytics.ts` — never import posthog-js directly in pages or components
- Server-side tracking (webhooks, API routes) goes through `src/lib/analytics-server.ts` — never import posthog-node directly in route handlers
- `track()` auto-attaches `project_name` and `project_owner` to every event; the `loaded` callback additionally registers both as **session super-properties** (`register_for_session`) so SDK auto-events (`$pageleave`, `$web_vitals`, `$autocapture`, `$exception`, `$identify`) carry them too — without this, auto-events are unattributable orphans in the shared analytics project
- All projects in the company share the same analytics project — these properties distinguish experiments
- If you rename the project in experiment.yaml (`name` field), update the `PROJECT_NAME` and `PROJECT_OWNER` constants in both `src/lib/analytics.ts` and `src/lib/analytics-server.ts`. `/verify` and `/bootstrap` enforce `PROJECT_NAME` equality via `.claude/scripts/lib/check_project_name.py` — drift will fail the pipeline with a clear fix message; `PROJECT_OWNER` is checked only for unreplaced `"TODO"` placeholders.
- Every event in experiment/EVENTS.yaml must have a `funnel_stage`. The analytics library generates typed wrappers for all events in the EVENTS.yaml `events` map. Cross-MVP funnel analysis queries by `funnel_stage` (with `count(DISTINCT distinct_id)` dedup), not by event name — this allows each MVP to define events that fit its domain while remaining comparable at the funnel level.

## Test Blocking
When running E2E tests, block analytics requests to prevent test data from polluting production analytics. The endpoint pattern for PostHog is:
```
**/ingest/**
```
This matches the proxied PostHog ingestion endpoint (`/ingest/*`). Playwright's `page.route()` uses this pattern to intercept and abort analytics requests. See the testing stack file's `blockAnalytics` helper for usage.

**sendBeacon + batching limitations:** PostHog JS uses `navigator.sendBeacon()` by default (which Playwright's `page.route()` cannot intercept) and batches multiple events into a single XHR after a threshold (which delays event emission past a test's assertion window). Both behaviors must be disabled for reliable Playwright interception. The canonical `analytics.ts` template above ALREADY includes the `disable_compression: true` + `request_batching: false` flags inside the lazy `init()` `.then()` callback, gated on `NEXT_PUBLIC_VERCEL_ENV !== "production"` so they fire in preview/dev (where tests run) but NOT in real production deploys.

The relevant block from `analytics.ts` (canonical — do not duplicate; this is the live source):

```ts
// (inside the import("posthog-js").then() callback in analytics.ts above)
const isPreviewOrDev = process.env.NEXT_PUBLIC_VERCEL_ENV !== "production";
posthog.init(POSTHOG_KEY, {
  api_host: POSTHOG_HOST,
  capture_pageview: false,
  capture_exceptions: true,
  ...(isPreviewOrDev && {
    disable_compression: true, // Force XHR transport (Playwright cannot intercept sendBeacon)
    request_batching: false,   // Force immediate per-event XHR (batching delays events past assertion time)
  }),
  // See canonical analytics.ts above for the loaded callback that registers
  // project_name/project_owner as session super-properties, plus gclid + utm_*
  // super-properties read from sessionStorage (populated by the inline
  // <Script> in layout.tsx — see framework/nextjs.md).
  loaded: (ph) => { /* project identity + gclid/utm super-property registration */ },
});
```

The `NEXT_PUBLIC_VERCEL_ENV` value is injected into the client bundle via `next.config.ts`'s `env` block (see `framework/nextjs.md` — Vercel does NOT auto-prefix system env vars with `NEXT_PUBLIC_`). On non-Vercel hosts the value is empty string so `!== "production"` is true and the flags apply (suboptimal-but-safe per-event XHR for non-Vercel production until that host's stack file injects an analogous indicator).

Both flags work together. `disable_compression` forces XHR transport; `request_batching: false` makes each event fire immediately instead of waiting for a batch threshold. The testing helper `captureAnalytics` (see `testing/playwright.md`) does handle batched bodies for slower assertions, but immediate-fire reduces flakiness in tight action → assertion windows. Both options are safe for MVPs — per-event XHRs and uncompressed payloads only matter at scale.

When creating a new analytics stack file, document the equivalent endpoint pattern so the testing stack file can adapt its route blocking.

## Audit Checklist (for /change skill — analytics type)
- Verify `track()` in `analytics.ts` and `trackServerEvent()` in `analytics-server.ts` both exist and auto-attach `project_name` and `project_owner`
- Verify `PROJECT_NAME` matches `experiment.yaml.name` via `python3 .claude/scripts/lib/check_project_name.py` (single source of truth — also runs in `/verify` state-0 and `/bootstrap` state-13a + state-13c gate-keeper). Verify `PROJECT_OWNER` matches `experiment.yaml.owner` manually (script does not cover owner).
- If any values are wrong, fix both analytics files before auditing pages/routes

## Stack Knowledge

### Never include PII in analytics event properties
Do not send personally identifiable information (email, name, phone number, IP address) as event properties. PostHog stores event data indefinitely and may be subject to GDPR/CCPA data subject requests. Use non-PII identifiers instead: `utm_source`, `plan_type`, `user_role` (generic, not the user's name). For user identification, use `identify(userId)` with the opaque user ID — PostHog links events to users internally without exposing PII in the event stream.

### When calling trackServerEvent() for anonymous users, never pass raw email as distinctId
The `distinctId` parameter in `trackServerEvent(event, distinctId, properties)` is stored by PostHog as the user identity axis — indefinitely, and subject to GDPR data subject access requests. Passing a raw email address (e.g. from a lead-capture form, an email-preference webhook, or any unauthenticated API route) leaks PII to PostHog under the identity column itself.

For anonymous / unauthenticated contexts, pass a deterministic opaque hash instead:

```ts
import { createHash } from "crypto";

function leadDistinctId(email: string): string {
  return "lead:" + createHash("sha256").update(email.toLowerCase().trim()).digest("hex").slice(0, 32);
}

// Usage:
await trackServerEvent("sample_requested", leadDistinctId(email), { plan });
```

The `"lead:"` prefix distinguishes anonymous-lead person records from authenticated users in PostHog without ever storing the email itself. The raw email lives only in the project's own `leads` (or equivalent) table where access can be governed by RLS or route-handler service-role gating. For authenticated users, continue to use `user.id` (opaque UUID from Supabase Auth) as `distinctId`.

This entry covers the `distinctId` axis. The entry above ("Never include PII in analytics event properties") covers the `properties` object — both must be non-PII.

### FakeDoor template encoded raw email as track("activate") event property (PII leak)

```yaml
id: no-pii-in-fakedoor-track-call
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: PII (email) leaked as analytics event property
  divergence_pattern: stack-template-encodes-pii-in-track-call
  stack_scope: ui/shadcn
composite_identity_hash: 70955e9dcac3
symptom_keywords: [posthog, pii, email, fake_door, track-activate, lead-capture, gdpr, intent-capture]
fix_template: |
  FakeDoor is demand-validation-only at the template default. The button click is
  the activation signal; do not collect email at the template default. Remove the
  email property from the track() call and the email field from the form. For
  projects that need real lead capture (email + persistence + later outreach),
  add the Feature via /change as a separately scoped behavior — scopes a server-
  side /api/leads/<action> route + leads table + RLS + rate-limiting + email-
  service integration. See scaffold-externals.md § Intent Capture Contract Rule 4
  + Lead-capture extension; CLAUDE.md Rule 0 (Scope Lock).
prevention_mechanism: |
  Bash smoke test at .claude/scripts/tests/no-pii-in-fakedoor-track-call.sh
  scans .claude/{stacks,procedures,skills,agents,templates}/ AND src/{app,
  commands}/ for any activate-event tracking call that includes a PII token
  (email/phone) in the property bag. Wired into lifecycle-finalize.sh Step
  4.5b (between coherence-lint Step 4.5 and RMG-guard Step 4.6); blocks
  delivery on any hit. Catches both template-side recurrence and downstream-
  MVP stale FakeDoor TSX in project-owned src/.
confidence_score: 0.9
occurrence_count: 1
linked_issues: [1326]
first_seen: 2026-05-08
last_seen: 2026-05-08
graduated_to: null
```

The FakeDoor template at `.claude/stacks/ui/shadcn.md` originally collected the user's email via a form input and passed the raw email as an event property on the activate-tracking call. This violated the canonical "Never include PII in analytics event properties" rule (above). The same shape was contractually mandated by `.claude/procedures/scaffold-externals.md` Rule 4 (Intent Capture Contract), so a fix in shadcn.md alone left contract drift. Compounding issue: the success copy promised "We will email when ready", but the template ships zero outreach infrastructure — the email went to PostHog and nowhere else (deceptive UX). Original incident: issue #1326, discovered during /resolve open-issues round-1 critic on a related PR.

### Testing analytics events deterministically (Playwright)

DO NOT assert on PostHog network requests in Playwright tests:

```ts
// FLAKY — race the test machine can lose
await Promise.all([
  page.waitForRequest(/posthog\.com\/e\//, { timeout: 5000 }),
  page.click("text=Sign up"),
]);
```

PostHog's JS client batches events, debounces via `_flushTimer`, falls back to `navigator.sendBeacon()` on page unload (uncatchable by Playwright after navigation), and skips network entirely under DNT / opt-out. The `disable_compression: true` + `request_batching: false` flags in `## Test Blocking` above mitigate batching but cannot eliminate the fundamental race between "the action that triggered the event" and "the network actually being made". CI machines under load lose the race.

The assertion target should be "**the `track()` call for `<event>` was made**" — a synchronous client-code observation that doesn't go through PostHog's network layer at all. The canonical `analytics.ts` (above) writes a sessionStorage marker inside `track()` itself, so EVERY event automatically gets a deterministic marker — whether the call site is the bare `track()` API or a typed wrapper from `events.ts`.

The marker shape (written by `track()` in analytics.ts):

```ts
// Inside track() — already part of the canonical analytics.ts template:
sessionStorage.setItem(
  `analytics:${event}`,
  JSON.stringify({ timestamp: Date.now(), properties: enriched })
);
```

A typed wrapper that calls `track()` inherits the marker:

```ts
// src/lib/events.ts (typed wrapper layer) — no marker code needed; track() handles it.
import { track } from "@/lib/analytics";

export function trackWelcomeEmailSent(props: { variant: string }) {
  track("welcome_email_sent", props);  // marker written automatically
}
```

```ts
// e2e/funnel.spec.ts — deterministic, no network race
test("signup fires welcome_email_sent", async ({ page }) => {
  await page.goto("/signup");
  await page.fill("input[name=email]", "a@b.com");
  await page.click("text=Sign up");
  await page.waitForURL("/welcome");

  const marker = await page.evaluate(() =>
    sessionStorage.getItem("analytics:welcome_email_sent"),
  );
  expect(marker).not.toBeNull();
  const parsed = JSON.parse(marker!);
  expect(parsed.properties).toMatchObject({ variant: expect.any(String) });
});
```

The marker is library-level (inside `track()`) rather than wrapper-level. This means: (a) bare `track(name, props)` calls also get markers (no requirement to use a typed wrapper); (b) the marker survives the lazy-load window — `track()` writes the marker BEFORE queueing the call into `pending[]`, so tests asserting on markers don't depend on `posthog-js` having loaded yet.

### Missing PostHog key produces silent no-op without `## Production Observability` safeguard

```yaml
id: posthog-missing-key-silent-noop
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: missing_env_var_at_production_runtime
  divergence_pattern: silent_noop_without_visibility
  stack_scope: analytics/posthog
composite_identity_hash: 81f48e6bba35
symptom_keywords: [posthog, analytics, silent, noop, missing-key, placeholder, phc_TEAM_KEY]
fix_template: |
  Three-layer fail-loud:
  (1) prebuild script `scripts/check-analytics-env.mjs` with env-first
      source-fallback grep gated on `CI=1 && VERCEL=1` (or `RAILWAY_ENVIRONMENT_NAME`),
      wired via `prebuild` lifecycle hook with `test ! -f X || node X` defensive idiom;
  (2) module-load `isMisconfigured` validator + `console.error`-once in
      `analytics.ts` and `analytics-server.ts`, gated on hostname (client) /
      hosting indicator (server) / `isAnalyticsEnabled()` (CLI);
  (3) `/distribute` STATE 2 step "2.0 Static placeholder check" — archetype-aware
      pre-flight grep for `phc_TEAM_KEY` before existing HogQL Auto Query.
  See `## Production Observability` for the full contract and behavior matrix.
prevention_mechanism: prebuild-env-source-validator + module-load-positive-validator
confidence_score: 0.9
occurrence_count: 1
linked_issues: [1170]
first_seen: 2026-04-30
last_seen: 2026-04-30
graduated_to: null
```

When the generated `analytics.ts` / `analytics-server.ts` is deployed with `NEXT_PUBLIC_POSTHOG_KEY` unset OR set to empty string, the original `?? "phc_TEAM_KEY"` fallback masked the misconfiguration entirely — every `track()` call silently dropped, the entire client-side funnel invisible until someone manually opened DevTools. The fix replaces the silent fallback with a positive `isMisconfigured` check that fires loudly at three layers (build, runtime, post-deploy verification). All layers are designed for both fork workflows: env override (per-project) and source-level placeholder replacement (fork-once). Original incident: issue #1170, discovered during `/distribute` STATE 6 manual ad-launch verification.

### CJS-interop with @next/env: shape depends on loader (.mjs raw ESM vs .ts CJS-transpile)

```yaml
id: nextenv-cjs-interop-loader-conditional
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: esm-cjs-interop-loader-conditional-shape
  divergence_pattern: single-shape-applied-uniformly-across-loaders
  stack_scope: analytics/posthog
composite_identity_hash: e74f81cb2f1d
symptom_keywords: [next-env, loadEnvConfig, esm, cjs, prebuild, mjs, ts, named-import, default-import, node22]
fix_template: |
  @next/env publishes as CommonJS only. The correct CJS-interop shape DEPENDS
  on the host loader — there is no single canonical shape:

  .ts files loaded by Playwright/jest/tsx (CJS-transpile via pirates / @swc-node
  / etc.) → NAMED-import works; default-import + destructure FAILS with
  `TypeError: Cannot destructure property 'loadEnvConfig' of '_env.default' as
  it is undefined` because the TS interop wrapper produces `{default: undefined}`.

      import { loadEnvConfig } from "@next/env";

  .mjs files loaded as raw Node ESM (`node script.mjs`) → DEFAULT-import +
  destructure works; named-import FAILS with `SyntaxError: Named export
  'loadEnvConfig' not found` because Node's CJS named-export detection does not
  surface this package's exports.

      import nextEnv from "@next/env";
      const { loadEnvConfig } = nextEnv;

  Empirical verification (run on your machine to confirm shapes for your
  installed @next/env version):

      cd /tmp && mkdir t && cd t && npm init -y && npm install @next/env
      # named in .mjs (expect SyntaxError):
      printf 'import { loadEnvConfig } from "@next/env";\nconsole.log(loadEnvConfig);\n' > a.mjs && node a.mjs
      # default+destructure in .mjs (expect function):
      printf 'import nextEnv from "@next/env";\nconsole.log(nextEnv.loadEnvConfig);\n' > b.mjs && node b.mjs

  Affects: scripts/check-analytics-env.mjs (DEFAULT+destructure),
  scripts/auto-migrate.mjs (DEFAULT+destructure), playwright.config.ts (NAMED).
prevention_mechanism: stack-file-comment-pinning-loader-conditional-shape + per-file inline reminders cross-referencing this entry
confidence_score: 0.95
occurrence_count: 2
linked_issues: [1325, 1382]
first_seen: 2026-05-07
last_seen: 2026-05-11
graduated_to: null
verification_snippet: |
  # exit 0 = bug present (default+destructure required for .mjs raw Node ESM)
  # exit 1 = bug absent (Node CJS named-export detection now surfaces @next/env exports)
  # exit 2 = preconditions not met (npm/node not available)
  set -e
  command -v npm >/dev/null && command -v node >/dev/null || exit 2
  T=$(mktemp -d)
  cd "$T"
  npm init -y >/dev/null 2>&1
  npm install @next/env >/dev/null 2>&1
  # Test the .mjs raw-ESM path: named import should FAIL (bug present)
  printf 'import { loadEnvConfig } from "@next/env";\nconsole.log(typeof loadEnvConfig);\n' > a.mjs
  if node a.mjs >/dev/null 2>&1; then
    # Named import succeeded → Node has fixed named-export detection → bug ABSENT
    exit 1
  else
    # Named import failed (the documented bug) → bug still PRESENT
    exit 0
  fi
```

The `@next/env` package is published as CommonJS only. Earlier guidance (issue
#1325) prescribed default-import + destructure as the universal canonical shape;
issue #1382 empirically demonstrated this is FALSE for .ts contexts — there the
TS-emitted CJS interop wrapper produces `{default: undefined}` and the
destructure throws TypeError. The shape is loader-conditional: `.mjs` files keep
default-import + destructure (raw Node ESM); `.ts` files (Playwright config) use
named-import (TS-transpiled CJS-interop). Three template files distribute these
shapes: `scripts/check-analytics-env.mjs` (analytics prebuild — .mjs default),
`scripts/auto-migrate.mjs` (database prebuild — .mjs default),
`playwright.config.ts` (testing config — .ts named, both with-auth and no-auth
fallback).

## PR Instructions
- `NEXT_PUBLIC_POSTHOG_KEY` MUST be set in the hosting platform's environment OR the source-level `phc_TEAM_KEY` placeholder must be replaced with the team's real key (see `## Environment Variables` and `## Production Observability`). Otherwise the prebuild script will fail the production build.
- Verify events are flowing: open the app, perform an action, then check PostHog → Activity → Live Events

## Dashboard Navigation (for /iterate skill)
How to pull funnel numbers from PostHog:
1. Go to your PostHog dashboard -> **Insights** -> **New insight** -> **Funnel**
2. Add events from experiment/EVENTS.yaml `events` map in funnel_stage order (reach → demand → activate → monetize → retain). Filter by `requires` (match experiment stack) and `archetypes` (match experiment type). Omit events with `requires: [payment]` if `stack.payment` is absent.
3. Add a filter: `project_name` equals your experiment.yaml `name` value
4. Set the date range to match your experiment's start date
5. Read the count at each funnel stage

## Auto Query (for /iterate skill)
Automated funnel data retrieval via PostHog's HogQL Query API. This eliminates the need for users to manually navigate PostHog dashboards and paste numbers.

### Constants
```
POSTHOG_API_HOST = https://us.i.posthog.com
```

**Project ID discovery** — do NOT hardcode a project ID. Discover it dynamically at runtime:
```bash
POSTHOG_PROJECT_ID=$(curl -s "https://us.i.posthog.com/api/projects/" \
  -H "Authorization: Bearer $POSTHOG_API_KEY" | python3 -c "import sys,json; print(json.load(sys.stdin)['results'][0]['id'])")
```
This returns the first project in the organization. All experiments share one PostHog project.

### Credential
- Path: `~/.posthog/personal-api-key`
- Follows the `~/.supabase/access-token` pattern from `deploy.md`
- Machine-level, one-time setup, shared across all experiments
- Setup instructions: PostHog → Settings → Personal API Keys → Create key (scope: Query Read) → save to file

### Credential Check
```bash
test -f ~/.posthog/personal-api-key
```
Missing → **STOP**. Do not fall back to manual input. Show setup instructions and tell user to create the key before re-running:

> PostHog personal API key not found at `~/.posthog/personal-api-key`.
> Create one: PostHog → click your profile (bottom left) → Personal API keys → Create personal API key → Label: `cli` → Scopes: Query Read → Create key → copy the `phx_` key → save:
> ```
> mkdir -p ~/.posthog && echo 'phx_YOUR_KEY' > ~/.posthog/personal-api-key
> ```

### Query Procedure
1. Read API key from `~/.posthog/personal-api-key`
2. Build event list from experiment/EVENTS.yaml `events` map (filter by `requires` matching experiment stack and `archetypes` matching experiment type)
3. Determine experiment duration from experiment.yaml context (e.g., funnel thresholds, deploy date)
4. Single HogQL query via curl:

```bash
curl -s -X POST "https://us.i.posthog.com/api/projects/$POSTHOG_PROJECT_ID/query/" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $POSTHOG_API_KEY" \
  -d '{
    "query": {
      "kind": "HogQLQuery",
      "query": "SELECT event, count(DISTINCT distinct_id) AS unique_users FROM events WHERE event IN ({events}) AND properties.project_name = {project_name} AND timestamp >= now() - INTERVAL <N> DAY GROUP BY event ORDER BY unique_users DESC",
      "values": {
        "project_name": "<name>",
        "events": ["visit_landing", "signup_start"]
      }
    }
  }'
```

> **Security:** Always use HogQL parameterized `values` for user-supplied inputs (project names, event names). Never use string interpolation — even with regex validation, string interpolation into query languages is an injection anti-pattern.

Key decisions:
- `count(DISTINCT distinct_id)` — unique users, not raw event fires (matches funnel visualization)
- Single HogQL query, not PostHog Funnel query type — simpler, documented API, iterate.md computes conversion rates itself
- Event list built dynamically from experiment/EVENTS.yaml at skill runtime

### Error Handling

| Condition | Action |
|-----------|--------|
| Credential file missing | Fall back to manual. Show setup instructions. |
| curl fails / network error | Fall back to manual. Report "PostHog API unreachable." |
| Response has `"detail"` or `"error"` | Fall back to manual. Report error message. |
| Empty results | Report "No events found." Fall back to manual. |

### Response Format
```json
{
  "results": [["visit_landing", 342], ["signup_start", 58]],
  "columns": ["event", "unique_users"]
}
```

## Cross-MVP Queries (for /iterate --cross)

PostHog-only — no Google Ads dependency. The cross-skill uses three query patterns: discovery, per-MVP event catalog, per-MVP signup count.

**Critical filter rules:**

- Use the shared paid-traffic filter from `.claude/scripts/lib/gclid_filter.py` (`PAID_GCLID_FILTER`): `coalesce(toString(properties.$session_entry_gclid), toString(properties.gclid)) IS NOT NULL AND length(...) > 40 AND (startsWith(..., 'Cj') OR startsWith(..., 'EAI') OR startsWith(..., 'CIa'))`. This is the single source of truth — all 5 query sites (state-x0/x1/x2/c2, this file's examples) MUST read from it. Do NOT use `utm_source = 'google'` (some campaign final URLs only get auto-tagged with `gclid`, no explicit `utm_source`, so the utm_source filter undercounts).
- Use `count(DISTINCT distinct_id)` everywhere — events double-fire and we want unique users.
- Always parameterize values via `{name}` — never interpolate user-supplied strings into the query.

### MVP identity rule

**Every cross-MVP HogQL query MUST key by `properties.project_name` exclusively.** No URL fallback — not `$current_url LIKE`, not `splitByChar(domain($current_url))[1]`. `project_name` is the canonical MVP identifier (substituted verbatim from `experiment.yaml.name` at /bootstrap state-3, enforced as kebab-case by `validate_experiment_yaml.py`). URL-based filtering double-counts events between similarly-named MVPs (e.g. `rubberduck` events bleeding into `rubber-duck-api` because both URLs contain `rubberduck`).

Legacy duplicates (MVPs created before kebab-case enforcement) are merged via `mvp_aliases:` in `experiment/iterate-cross-config.yaml`, applied in state-x0 after discovery — never during query time.

### Discovery query (used by STATE x0)

Returns one row per `project_name` with gclid traffic in the window. Rows with NULL/empty `project_name` are surfaced separately as orphan hosts (operator-actionable: fix tracking in those deploys).

```bash
curl -s -X POST "https://us.i.posthog.com/api/projects/$POSTHOG_PROJECT_ID/query/" \
  -H "Authorization: Bearer $POSTHOG_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "query": {
      "kind": "HogQLQuery",
      "query": "SELECT properties.project_name AS mvp_key, max(properties.utm_campaign) AS sample_utm_campaign, count(DISTINCT distinct_id) AS gclid_visitors, min(timestamp) AS first_seen, max(timestamp) AS last_seen FROM events WHERE coalesce(toString(properties.$session_entry_gclid), toString(properties.gclid)) IS NOT NULL AND length(coalesce(toString(properties.$session_entry_gclid), toString(properties.gclid))) > 40 AND (startsWith(coalesce(toString(properties.$session_entry_gclid), toString(properties.gclid)), 'Cj') OR startsWith(coalesce(toString(properties.$session_entry_gclid), toString(properties.gclid)), 'EAI') OR startsWith(coalesce(toString(properties.$session_entry_gclid), toString(properties.gclid)), 'CIa')) AND properties.project_name IS NOT NULL AND properties.project_name != {empty} AND timestamp >= now() - INTERVAL 90 DAY GROUP BY mvp_key HAVING gclid_visitors > 0 ORDER BY gclid_visitors DESC LIMIT 200",
      "values": {"empty": ""}
    }
  }'
```

### Per-MVP event catalog (used by STATE x1)

For each discovered MVP, list its events with counts and `funnel_stage` hint. Builds the input for the LLM signup classifier in x2.

The skill packs N MVPs into a single UNION ALL query (one round-trip). Per-MVP subquery:

```sql
SELECT {p_name} AS mvp_key,
       event AS event_name,
       max(toString(properties.funnel_stage)) AS sample_stage,
       count(*) AS event_count,
       count(DISTINCT distinct_id) AS unique_users,
       count(DISTINCT IF(coalesce(toString(properties.$session_entry_gclid), toString(properties.gclid)) IS NOT NULL AND length(coalesce(toString(properties.$session_entry_gclid), toString(properties.gclid))) > 40 AND (startsWith(coalesce(toString(properties.$session_entry_gclid), toString(properties.gclid)), 'Cj') OR startsWith(coalesce(toString(properties.$session_entry_gclid), toString(properties.gclid)), 'EAI') OR startsWith(coalesce(toString(properties.$session_entry_gclid), toString(properties.gclid)), 'CIa')), distinct_id, NULL)) AS gclid_users
FROM events
WHERE timestamp >= now() - INTERVAL {window_days} DAY
  AND properties.project_name = {p_name}
  AND event NOT LIKE '$%'
GROUP BY event_name
HAVING gclid_users > 0 OR unique_users >= 5
```

### Per-MVP signup count (used by STATE x2)

After x2's LLM classifies signup_events per MVP, query gclid-filtered distinct user count for each MVP's specific events. Per-MVP subquery (combined into UNION ALL):

```sql
SELECT {p_name} AS mvp_key,
       count(DISTINCT IF(event = {sg1} OR event = {sg2}, distinct_id, NULL)) AS signups
FROM events
WHERE coalesce(toString(properties.$session_entry_gclid), toString(properties.gclid)) IS NOT NULL
  AND length(coalesce(toString(properties.$session_entry_gclid), toString(properties.gclid))) > 40
  AND (startsWith(coalesce(toString(properties.$session_entry_gclid), toString(properties.gclid)), 'Cj')
       OR startsWith(coalesce(toString(properties.$session_entry_gclid), toString(properties.gclid)), 'EAI')
       OR startsWith(coalesce(toString(properties.$session_entry_gclid), toString(properties.gclid)), 'CIa'))
  AND timestamp >= now() - INTERVAL {window_days} DAY
  AND properties.project_name = {p_name}
```

### Notes

- Paid-traffic queries should always use `coalesce(toString(properties.$session_entry_gclid), toString(properties.gclid))` as the attribution expression — `$session_entry_gclid` is auto-populated by `posthog-js@1.130.0+` when SDK init wins the race against URL cleanup, but Next.js router can strip `?gclid=` before SDK loads in lazy-import setups. The template's `analytics.ts` mitigates this by also stamping `properties.gclid` as a super property via a `loaded` callback that reads from `sessionStorage` (populated by a synchronous inline `<Script>` in `layout.tsx` — see `framework/nextjs.md` "Paid-attribution capture" section). The `coalesce` ensures both capture paths work; the length+prefix filter (in `gclid_filter.py`) excludes operator manual-test gclids that slip past loose `length>30` rules.
- HogQL `IN [array]` inside `count(DISTINCT IF(... , distinct_id, NULL))` triggers a `Nested type Array(String) cannot be inside Nullable type` error. Workaround: use `(event = {sg1} OR event = {sg2} OR ...)` instead of `event IN {sg_list}`.
- The `event NOT LIKE '$%'` filter excludes PostHog auto-capture events (`$pageview`, `$autocapture`, etc.) from the catalog — they're never signups and they crowd out the meaningful events.
