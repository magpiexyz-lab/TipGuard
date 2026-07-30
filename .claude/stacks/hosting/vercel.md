---
assumes: [framework/nextjs]
packages:
  runtime: []
  dev: []
files:
  - src/app/api/health/route.ts
env:
  server: []
  client: []
ci_placeholders: {}
clean:
  files: []
  dirs: []
gitignore: [.vercel/]
---
# Hosting: Vercel
> Used when experiment.yaml has `stack.hosting: vercel`
> Assumes: `framework/nextjs` (references `NEXT_PUBLIC_` env var prefix convention)

## Deployment
```bash
npx vercel deploy --prod
```

## Production Deploys Are Manual
- Production deploys are triggered by re-running `/deploy` (which runs `vercel --prod --yes`)
- Auto-deploy to production on merge is **disabled** — this avoids unnecessary Vercel builds and keeps costs predictable
- Preview deployments are still created automatically on PRs (used by `preview-smoke` CI job) via the GitHub integration
- `make deploy` remains available for manual CLI deploys

## Health Check

### `src/app/api/health/route.ts` — Deployment health endpoint

Bootstrap creates this endpoint unconditionally. It always returns basic status; service-specific checks are added based on the active stack.

**Base template (always created):**
```ts
import { NextResponse } from "next/server";

export async function GET() {
  const checks: Record<string, "ok" | "degraded" | "error"> = {};
  // Service checks are added by bootstrap based on active stack services.
  // Each sets "ok", "degraded", or "error" — details are logged server-side only.

  const critical = Object.entries(checks).filter(([k]) => ["database", "auth"].includes(k));
  const hasCriticalFailure = critical.some(([, v]) => v === "error");

  return NextResponse.json(
    { status: hasCriticalFailure ? "degraded" : "ok" },
    { status: hasCriticalFailure ? 503 : 200 }
  );
}
```

> **Security:** The response returns ONLY `{ status: "ok" | "degraded" }` — no per-subsystem keys, no error details, no env var presence. This prevents unauthenticated callers from probing infrastructure topology (OWASP A4-InfoLeakage). All diagnostic details are logged server-side via `console.error`.

**When `stack.database` is present:** bootstrap adds a database connectivity check inside the function body — import the server client, run a lightweight query (e.g., `supabase.from('...').select('id').limit(1)`), and set `checks.database = "ok"` or `"error"`. Log the actual error server-side with `console.error("Health check database error:", error.message)` — never expose raw error messages or subsystem names in the response.

**When `stack.auth` is present:** bootstrap adds an auth service check — call `supabase.auth.getUser()` with no session (expects an auth error, not a network error), and set `checks.auth = "ok"` or `"error"`. Log the actual error server-side with `console.error("Health check auth error:", e.message)` — never expose raw error messages or subsystem names in the response.

**When `stack.analytics` is present:** bootstrap adds an analytics reachability check. Import constants from the analytics server library (e.g., `import { POSTHOG_KEY, POSTHOG_HOST } from "@/lib/analytics-server"`). Do NOT hardcode the API key — always use the imported constant. The publishable key is always available (hardcoded fallback in the analytics library), so always attempt the reachability check. For PostHog: `fetch(POSTHOG_HOST + "/decide?v=3", { method: "POST", body: JSON.stringify({ api_key: POSTHOG_KEY, distinct_id: "healthcheck" }) })`. Set `checks.analytics = "ok"` or `"error"` based on reachability. Timeout gracefully (e.g., 3s) — set `checks.analytics = "degraded"` on timeout. Log the actual error server-side — never expose raw error messages or subsystem names in the response. The `/decide` endpoint is lightweight and does not create events. Analytics is a **non-critical** check (see Response below).

**When `stack.payment` is present:** bootstrap adds a payment configuration check — verify the payment provider's secret key env var exists and has the correct format. For Stripe: check `process.env.STRIPE_SECRET_KEY` starts with `sk_`. Set `checks.payment = "ok"` or `"error"`. Log the actual error server-side — never expose raw error messages or subsystem names in the response.

**Response:** Checks are classified as **critical** (database, auth) or **non-critical** (analytics, payment config). Returns 200 with `{ status: "ok" }` if all critical checks pass. Returns 503 with `{ status: "degraded" }` if any critical check fails. Per-subsystem keys are **never** included in the response — the binary status is all an external caller needs; detailed check results are logged server-side only for operator diagnostics.

## Preview Smoke Test

Vercel automatically creates preview deployments on PRs. CI runs smoke tests against the preview URL before merge.

- No auth, no database writes, no Docker required
- PR-only (`github.event_name == 'pull_request'`) — pushes to main don't create preview deployments
- Uses `patrickedqvist/wait-for-vercel-preview` GitHub Action to get the preview URL

**Web-app archetype:** Reuses existing `e2e/smoke.spec.ts` via `E2E_BASE_URL` pointed at the preview URL (browser-based Playwright tests).

**Service archetype:** No browser tests — preview smoke tests hit the `/api/health` endpoint via `curl`. The CI job uses the same Vercel preview URL but checks the health endpoint instead of running Playwright.

**Web-app:** See the testing stack file's "Preview Smoke CI Job Template" section for the CI job template.

**Service preview smoke** (inline — no testing stack template needed):
```yaml
  preview-smoke:
    needs: build
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - uses: patrickedqvist/wait-for-vercel-preview@v1.3.2
        id: preview
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
          max_timeout: 300
      - name: Health check
        run: |
          STATUS=$(curl -s -o /dev/null -w '%{http_code}' "${{ steps.preview.outputs.url }}/api/health")
          if [ "$STATUS" != "200" ]; then
            echo "Health check failed with status $STATUS"
            curl -s "${{ steps.preview.outputs.url }}/api/health"
            exit 1
          fi
          echo "Health check passed"
```

## Environment Variables
- **Supabase env vars:** Use the [Supabase Vercel Integration](https://vercel.com/integrations/supabase) to auto-inject database env vars (see Supabase Vercel Integration section below)
- **Other env vars (Stripe, etc.):** Set manually via Vercel dashboard → Project → Settings → Environment Variables
- Client-side env vars must use `NEXT_PUBLIC_` prefix
- Never commit secrets to code — always use environment variables

## Supabase Vercel Integration
When `stack.database: supabase` is present, the recommended production setup is the [Supabase Vercel Integration](https://vercel.com/integrations/supabase):
- Auto-creates or links a Supabase project to the Vercel project
- Auto-injects environment variables into Vercel, including:
  - `POSTGRES_URL`, `POSTGRES_URL_NON_POOLING` (connection strings)
  - `POSTGRES_PASSWORD`, `POSTGRES_USER`, `POSTGRES_HOST`, `POSTGRES_DATABASE`
  - `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`
  - `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`
- Database migrations are auto-applied during build via the `prebuild` script (see database stack file "Auto-Migration on Vercel Build")
- Eliminates manual env var copying and manual migration for non-technical team members

Bootstrap PR instructions should reference this integration as the primary setup method, with manual env var entry as a fallback.

## CLI Deployment (Non-Interactive)

Used by the `/deploy` skill for automated first-time setup.

### Project Setup
- `vercel link --yes --project <name> [--scope "<team>"]` — creates project if not exists, links locally
- `vercel git connect --yes` — connects GitHub repo for PR preview deployments (production auto-deploy is disabled separately)
  - Prerequisite: Vercel GitHub App installed on the GitHub org/account

### Environment Variables

**Primary method — Vercel REST API (batch, all environments):**
```bash
curl -s -X POST "https://api.vercel.com/v10/projects/<name>/env?upsert=true&slug=<team>" \
  -H "Authorization: Bearer <vercel_token>" \
  -H "Content-Type: application/json" \
  -d '[{"key":"KEY","value":"VAL","type":"encrypted","target":["production","preview","development"]}]'
```
- `upsert=true` overwrites existing values (idempotent)
- Sets all environments (production, preview, development) in one call
- Omit `&slug=<team>` for personal accounts

**Auth token location:**
- macOS: `~/Library/Application Support/com.vercel.cli/auth.json` → parse JSON, extract `token`
- Linux: `~/.local/share/com.vercel.cli/auth.json` → parse JSON, extract `token`

**Fallback — Vercel CLI (production only, per-variable):**
- `echo $VALUE | vercel env add KEY production --force` — set/overwrite an env var
- Used when auth token is unavailable or REST API fails

**Verify:** `vercel env ls` — list env vars after setup

### First Deploy
- `vercel --prod --yes` — deploy to production without prompts

## Rate Limiting

Simple in-memory counters do not persist across serverless invocations on Vercel, so they are not effective for cross-instance rate limiting. However, they still provide burst protection within a single instance.

Bootstrap creates `src/lib/rate-limit.ts` with an in-memory burst-protection limiter. Auth and payment routes import and apply it. This satisfies security review D5.

**`src/lib/rate-limit.ts`:**
```ts
const rateLimitMap = new Map<string, { count: number; resetTime: number }>();

export function rateLimit(
  key: string,
  { limit = 10, windowMs = 60_000 }: { limit?: number; windowMs?: number } = {}
): { success: boolean; remaining: number } {
  const now = Date.now();
  const entry = rateLimitMap.get(key);

  if (!entry || now > entry.resetTime) {
    rateLimitMap.set(key, { count: 1, resetTime: now + windowMs });
    return { success: true, remaining: limit - 1 };
  }

  if (entry.count >= limit) {
    return { success: false, remaining: 0 };
  }

  entry.count++;
  return { success: true, remaining: limit - entry.count };
}

// Vercel's proxy appends the verified client IP as the LAST entry in the
// X-Forwarded-For chain. Entries BEFORE the last one are forwarded from the
// client (or upstream proxies) and are NOT trusted — an attacker can supply
// arbitrary `X-Forwarded-For: <random>` to inject a unique-per-request key,
// bypassing per-IP rate caps. Always derive the rate-limit key via this
// helper, never via the raw header value. (Issue #1361 / CVSS-medium.)
export function clientIpFromHeaders(headers: Headers): string {
  const xff = headers.get("x-forwarded-for");
  if (xff) {
    const last = xff.split(",").at(-1)?.trim();
    if (last) return last;
  }
  return headers.get("x-real-ip") ?? "unknown";
}
```

**Usage in route handlers:**
```ts
import { rateLimit, clientIpFromHeaders } from "@/lib/rate-limit";

// At the top of the handler:
const ip = clientIpFromHeaders(request.headers);
const { success } = rateLimit(ip, { limit: 10, windowMs: 60_000 });
if (!success) {
  return NextResponse.json({ error: "Too many requests" }, { status: 429 });
}
```

> **Caveat:** In-memory state does not persist across serverless invocations, so this provides burst protection (limiting rapid requests to a single instance) rather than true distributed rate limiting. Add `// TODO: Upgrade to Upstash Redis for cross-instance rate limiting` after the rate limit check. If experiment.yaml `stack` includes a rate-limiting service (e.g., Upstash), use that instead of the in-memory limiter.

### When upgrading the in-memory rateLimit to Upstash Redis (the documented TODO)

Replacing the in-memory `Map` in `src/lib/rate-limit.ts` with an Upstash Redis sliding-window converts `rateLimit()` from a synchronous function to an async one. **Every call site must be updated** to use `await rateLimit(...)` — leaving any call site synchronous produces a Promise truthy-coerce that always passes the `success` check, silently disabling rate limiting on that route.

The call-site count scales with the number of API routes (auth, payment, AI/LLM routes — see paired entries below). Enumerate sites first:

```bash
grep -rn 'rateLimit(' src/app/api src/lib | grep -v 'rate-limit.ts'
```

Update each site to `await` the call, and propagate `async` up to the route handler signature where it isn't already async.

```ts
// BEFORE (synchronous — works against in-memory Map)
export async function POST(request: Request) {
  const ip = clientIpFromHeaders(request.headers);
  const { success } = rateLimit(ip, { limit: 10, windowMs: 60_000 });
  if (!success) return NextResponse.json({ error: "Too many requests" }, { status: 429 });
  // ...
}

// AFTER (async — required against Upstash Redis sliding-window)
export async function POST(request: Request) {
  const ip = clientIpFromHeaders(request.headers);
  const { success } = await rateLimit(ip, { limit: 10, windowMs: 60_000 });
  if (!success) return NextResponse.json({ error: "Too many requests" }, { status: 429 });
  // ...
}
```

Add the Upstash credentials to `.env.example` so deployments and local dev can resolve them:

```
UPSTASH_REDIS_REST_URL=https://...upstash.io
UPSTASH_REDIS_REST_TOKEN=...
```

For local development without Upstash credentials configured, an in-memory fallback inside `src/lib/rate-limit.ts` is acceptable so `npm run dev` still works — gate it on `process.env.UPSTASH_REDIS_REST_URL` presence and emit a `console.warn("Upstash credentials missing — using in-memory rate limiter (single-instance only)")` once at module load. The fallback must remain the same `await`-friendly async shape so call sites stay correct under both code paths.

After the upgrade, remove the `// TODO: Upgrade to Upstash Redis for cross-instance rate limiting` comments from every call site (they live next to each `rateLimit(...)` call per the caveat above).

### AI/LLM API endpoints

When experiment.yaml behaviors involve an AI/LLM provider (e.g., `external/anthropic`, `external/openai`), apply rate limiting to all API routes that call the provider — not just auth and payment routes. Use a lower limit than standard routes (suggested default: 5 req/min/IP) since each request can generate significant inference costs. Adjust the limit based on the specific integration's cost profile and expected usage patterns.

```ts
import { rateLimit, clientIpFromHeaders } from "@/lib/rate-limit";

const ip = clientIpFromHeaders(request.headers);
const { success } = rateLimit(ip, { limit: 5, windowMs: 60_000 });
if (!success) return NextResponse.json({ error: "Too many requests" }, { status: 429 });
```

#### When an AI route uses a session-keyed rate limit, add an IP floor in front

Session-keyed limits (keyed on a user's session_id cookie or auth subject) give each user their own budget — but they are bypassable via **session_id rotation**: an attacker that rotates the session_id cookie on every request resets the session-keyed counter and can drive unlimited inference costs from a single IP. Always apply an IP-based floor **before** the session-keyed check when both layers are used:

```ts
// 1. IP floor — prevents session rotation abuse. Sized higher than the session
//    limit (e.g., 3x) to allow legitimate multi-session use from shared NAT.
const ip = clientIpFromHeaders(request.headers);
const ipCheck = rateLimit(ip, { limit: 30, windowMs: 60_000 });
if (!ipCheck.success) {
  return NextResponse.json({ error: "Too many requests" }, { status: 429 });
}

// 2. Session-keyed limit — per-user enforcement for shared-IP scenarios.
const sessionId = request.cookies.get("session_id")?.value ?? ip;
const sessionCheck = rateLimit(sessionId, { limit: 10, windowMs: 60_000 });
if (!sessionCheck.success) {
  return NextResponse.json({ error: "Too many requests" }, { status: 429 });
}
// TODO: Upgrade to Upstash Redis for cross-instance rate limiting
```

**Residual risk — cross-instance bypass.** The layered pattern above provides **same-instance burst protection only** — it inherits the in-memory caveat documented for `src/lib/rate-limit.ts` above. An attacker that hits multiple Vercel serverless instances in parallel bypasses both layers because each instance maintains its own counter map. For production workloads with genuine cost exposure (paid AI inference, per-request provider fees), upgrade to a durable store (Upstash Redis or similar) per the TODO already in `src/lib/rate-limit.ts`. The IP-floor + session-keyed pattern is necessary but not sufficient at serverless scale.

## Security Headers

Add a `vercel.json` with baseline security headers. These apply to all responses automatically.

```json
{
  "headers": [
    {
      "source": "/(.*)",
      "headers": [
        { "key": "X-Content-Type-Options", "value": "nosniff" },
        { "key": "X-Frame-Options", "value": "DENY" },
        { "key": "Referrer-Policy", "value": "strict-origin-when-cross-origin" }
      ]
    }
  ]
}
```

- **CSP intentionally omitted** — Content-Security-Policy breaks inline styles from UI libraries (shadcn, Tailwind) and analytics scripts (PostHog). Add CSP when ready for strict content security.
- Bootstrap should create `vercel.json` with these headers if it doesn't already exist. If `vercel.json` exists (e.g., for rewrites), merge the `headers` array.

## Stack Knowledge

### When implementing rate limiting on Vercel, derive the IP key from the LAST X-Forwarded-For entry, never the raw header

```yaml
id: vercel-rate-limit-raw-xff-bypass
maturity: raw
anti_pattern: false
composite_identity:
  root_cause_class: rate-limit-key-bound-to-attacker-controllable-xff
  divergence_pattern: raw-xff-as-rate-limit-key
  stack_scope: hosting/vercel
composite_identity_hash: b989da182fc7
symptom_keywords: [vercel, rate-limit, x-forwarded-for, xff, ip-spoofing, rate-limit-bypass, cvss-medium]
fix_template: |
  Use the `clientIpFromHeaders(headers)` helper exported from
  `src/lib/rate-limit.ts`. The helper splits XFF on commas and returns the
  LAST entry trimmed (Vercel's proxy-verified client IP), falling back to
  `x-real-ip` then `"unknown"`. Never use raw `headers.get("x-forwarded-for")`
  as a rate-limit key — attackers can append arbitrary prefix entries.
prevention_mechanism: consistency-check.sh Check 27 (forbids raw XFF reads in stack-file code blocks outside the helper definition); pytest scripts/test_consistency_check.py::TestCheck27ClientIpHelper (fail-closed against Check 27 deletion)
confidence_score: 0.9
occurrence_count: 1
linked_issues: [1361]
first_seen: 2026-05-10
last_seen: 2026-05-10
graduated_to: null
```

Vercel's proxy appends the verified client IP as the LAST comma-separated entry in `X-Forwarded-For`. Entries before it are forwarded from the client (or upstream proxies) and are NOT trusted. Reading the entire header (or `.split(",")[0]`) and using it as the rate-limit key lets an attacker rotate `X-Forwarded-For: <random>` per request to mint unique keys, bypassing the per-IP cap entirely. The same pattern applies on Railway and other reverse-proxy hosts. The canonical fix is the `clientIpFromHeaders` helper; all rate-limited route handlers (auth, payment, AI/LLM) import and use it.

## Patterns
- Production deploys are manual — re-run `/deploy` or use `npx vercel deploy --prod`
- Auto-deploy to production is disabled to control costs; PR preview deployments remain active
- After manual `make deploy`, the health endpoint is automatically checked
- Use Vercel's preview deployments (automatic on PRs) for testing before production
- Preview deployments are smoke-tested in CI before merge
- Client-side environment variables must use the `NEXT_PUBLIC_` prefix
- Environment variables are configured per-environment (Production, Preview, Development) in the Vercel dashboard

## PR Instructions
- After merging: run `/deploy` in Claude Code to set up Vercel + Supabase automatically. Or manually: import your repo at [vercel.com/new](https://vercel.com/new) and add the Supabase Vercel Integration ([vercel.com/integrations/supabase](https://vercel.com/integrations/supabase)) to auto-inject Supabase env vars. For other env vars (Stripe, etc.), add them manually in Vercel Project → Settings → Environment Variables.
- Production deploys are manual — re-run `/deploy` after code changes to update. PR preview deployments are automatic.

## Deploy Interface

Standardized subsections referenced by deploy.md and teardown.md. Each subsection is a self-contained recipe — deploy.md reads them by name and executes the instructions.

### Prerequisites

- **install_check:** `which vercel`
- **install_fix:** `npm i -g vercel`
- **auth_check:** `vercel whoami`
- **auth_fix:** `vercel login`

### Config Gathering

- **CLI command:** `vercel teams list` — lists available teams (or personal account)
- Prompt user for Vercel team selection during deploy (no experiment.yaml field for this)

### Project Setup

1. Link or create the project (idempotent):
   ```bash
   vercel link --yes --project <name> [--scope "<team>"]
   ```
2. Connect GitHub repo for PR preview deployments:
   ```bash
   vercel git connect --yes
   ```
   Prerequisite: Vercel GitHub App installed on the GitHub org/account.
   - "Login Connection" error → user needs to connect GitHub at https://vercel.com/account/settings/authentication
   - "Failed to connect" → user needs to install Vercel GitHub App on their org
3. Disable auto-deploys (production and preview):
   Extract the Vercel auth token (see "Auth token location" under Environment Variables) and project name, then:
   ```bash
   # Get project ID
   PROJECT_INFO=$(curl -s "https://api.vercel.com/v9/projects/<name>?slug=<team>" \
     -H "Authorization: Bearer <vercel_token>")
   PROJECT_ID=$(echo "$PROJECT_INFO" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
   # Disable production auto-deploy
   curl -s -X PATCH "https://api.vercel.com/v9/projects/$PROJECT_ID" \
     -H "Authorization: Bearer <vercel_token>" \
     -H "Content-Type: application/json" \
     -d '{"autoAssignCustomDomains": true, "gitForkProtection": true}'
   ```
   Then set the production branch to a non-existent branch to prevent auto-deploy on merge:
   ```bash
   curl -s -X PATCH "https://api.vercel.com/v9/projects/$PROJECT_ID" \
     -H "Authorization: Bearer <vercel_token>" \
     -H "Content-Type: application/json" \
     -d '{"productionDeploymentBranch": "__manual_deploy_only__"}'
   ```
   This disables production auto-deploy on merge to main. Preview deployments on PRs remain active via the GitHub integration (used by the `preview-smoke` CI job). Production deploys are triggered manually via `vercel --prod --yes` when running `/deploy`.

### Domain Setup

1. Construct domain: `<name>.<domain>` (default parent domain: `draftlabs.org`; override with `deploy.domain` in experiment.yaml)
2. Add domain:
   ```bash
   vercel domains add <name>.<domain> --scope "<team>"
   ```
3. **On success:** `canonical_url` = `<name>.<domain>`, `domain_added` = true
4. **On failure:** Warn "Could not add custom domain. Verify wildcard DNS (CNAME `*` → `cname.vercel-dns.com`, DNS Only)." Set `canonical_url` = null (finalized after deploy), `domain_added` = false

### Environment Variables

**Primary method — REST API (batch, all environments):**
```bash
curl -s -X POST "https://api.vercel.com/v10/projects/<name>/env?upsert=true&slug=<team>" \
  -H "Authorization: Bearer <vercel_token>" \
  -H "Content-Type: application/json" \
  -d '[{"key":"KEY","value":"VAL","type":"encrypted","target":["production","preview","development"]}]'
```
- `upsert=true` overwrites existing values (idempotent)
- Omit `&slug=<team>` for personal accounts

**Auth token location:**
- macOS: `~/Library/Application Support/com.vercel.cli/auth.json` → parse JSON, extract `token`
- Linux: `~/.local/share/com.vercel.cli/auth.json` → parse JSON, extract `token`
- If missing or parse fails → set `vercel_token = null` (use fallback)

**Fallback — CLI (production only, per-variable):**
```bash
echo $VALUE | vercel env add KEY production --force
```

**Verify:** `vercel env ls`

### Deploy

- **Command:** `vercel --prod --yes`
- **Extract URL:** from command output

### Health Check

```bash
curl -s <canonical_url>/api/health
```
Returns JSON `{ status: "ok", ... }` with per-service checks.

### Auto-Fix

| Check | Diagnosis | Fix |
|-------|-----------|-----|
| Env vars | `vercel env ls` — compare with expected | Re-set via REST API or CLI fallback, then redeploy |
| Redeploy | — | `vercel --prod --yes` |

### Teardown

1. Remove custom domain:
   ```bash
   vercel domains rm <domain> --scope "<team>" --yes
   ```
2. Remove project:
   ```bash
   vercel project rm <project> --scope "<team>" --yes
   ```
3. **Dashboard URL (manual fallback):** `https://vercel.com/<team>/<project>/settings`

### Manifest Keys

```json
{
  "provider": "vercel",
  "project": "<name>",
  "team": "<team>",
  "domain": "<domain or null>"
}
```

### Rollback

- **Command:** `vercel rollback`
- **Dashboard:** Vercel → Deployments → "..." → "Promote to Production"
- **Note:** Instant — no rebuild. Does NOT rollback database migrations.

### Compatibility

- **incompatible_databases:** `[sqlite]`
- **reason:** Serverless functions have no persistent filesystem — SQLite database files are lost between invocations
