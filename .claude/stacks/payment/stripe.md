---
assumes: [framework/nextjs]
packages:
  runtime: [stripe, "@stripe/stripe-js"]
  dev: []
files:
  - src/lib/stripe.ts
  - src/lib/stripe-client.ts
  - src/app/api/checkout/route.ts
  - src/app/api/webhooks/stripe/route.ts
env:
  server: [STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, NEXT_PUBLIC_SITE_URL]
  client: [NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY]
ci_placeholders:
  STRIPE_SECRET_KEY: placeholder-stripe-secret
  NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY: placeholder-stripe-publishable
  STRIPE_WEBHOOK_SECRET: placeholder-stripe-webhook-secret
  NEXT_PUBLIC_SITE_URL: http://localhost:3000
clean:
  files: []
  dirs: []
gitignore: []
---
# Payment: Stripe
> Used when experiment.yaml has `stack.payment: stripe`

## Packages
```bash
npm install stripe @stripe/stripe-js
```

## Files to Create

### `src/lib/stripe.ts` — Server-side Stripe client
```ts
import Stripe from "stripe";

let _stripe: Stripe | null = null;

function createDemoStripe() {
  return {
    checkout: {
      sessions: {
        create: (params: Record<string, unknown>) =>
          Promise.resolve({ url: (params?.success_url as string) ?? "/" }),
      },
    },
    webhooks: {
      constructEvent: () => ({ type: "demo", data: { object: {} } }),
    },
  } as unknown as Stripe;
}

export function getStripe(): Stripe {
  if (process.env.DEMO_MODE === "true" && process.env.VERCEL === "1") {
    throw new Error("DEMO_MODE is not allowed in production");
  }
  if (process.env.DEMO_MODE === "true") return createDemoStripe();
  if (!_stripe) {
    if (!process.env.STRIPE_SECRET_KEY) {
      throw new Error("STRIPE_SECRET_KEY is not configured");
    }
    _stripe = new Stripe(process.env.STRIPE_SECRET_KEY);
  }
  return _stripe;
}
```
- The Stripe SDK automatically uses the API version bundled with the installed package. To pin a specific version, add `apiVersion` — see https://stripe.com/docs/upgrades.
- Import `getStripe` in API route handlers only — call it inside the handler function, not at module scope

### `src/lib/stripe-client.ts` — Client-side Stripe loader
```ts
import { loadStripe } from "@stripe/stripe-js";

const STRIPE_PUBLISHABLE_PLACEHOLDER = "placeholder-stripe-publishable";
const stripeKey = process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY || STRIPE_PUBLISHABLE_PLACEHOLDER;

// Issue #1170 follow-up: warn loudly when the placeholder fallback is hit on a
// deployed host. Stripe's `loadStripe()` does not surface a configuration error
// for an invalid publishable key — checkout silently fails when a user clicks
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
```
- Use this in client components to redirect to Stripe Checkout. When `stripePromise` is `null`, callers should disable the checkout button (or short-circuit the redirect) — never call Stripe APIs with the placeholder.

## Environment Variables
```
STRIPE_SECRET_KEY=sk_test_...
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
NEXT_PUBLIC_SITE_URL=https://your-domain.com
```

## API Routes

### `src/app/api/checkout/route.ts` — Create Checkout Session
```ts
import { NextResponse } from "next/server";
import { z } from "zod";
import { getStripe } from "@/lib/stripe";
import { rateLimit, clientIpFromHeaders } from "@/lib/rate-limit";

const checkoutSchema = z.object({
  // TODO: Replace z.string() with z.enum([...]) listing valid plan values for this project
  plan: z.string().max(200),
});

export async function POST(request: Request) {
  const ip = clientIpFromHeaders(request.headers);
  const { success } = rateLimit(ip, { limit: 10, windowMs: 60_000 });
  if (!success) {
    return NextResponse.json({ error: "Too many requests" }, { status: 429 });
  }
  // TODO: Upgrade to Upstash Redis for cross-instance rate limiting
  try {
    const body = await request.json();
    const { plan } = checkoutSchema.parse(body);

    // TODO: Add auth check here — see auth stack file "Server-Side Auth Check" for the correct import
    // This defines `user`, whose `user.id` is referenced in metadata below

    // TODO: Look up price server-side — never trust client-provided prices
    // Define a PLAN_PRICES map or query the database for the plan's price
    // Example: const PLAN_PRICES: Record<string, number> = { basic: 999, pro: 2999 };
    const amount_cents = PLAN_PRICES[plan]; // Intentional — fails build until PLAN_PRICES is defined (see TODO above)

    const siteUrl = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

    const session = await getStripe().checkout.sessions.create({
      mode: "payment",
      line_items: [
        {
          price_data: {
            currency: "usd",
            product_data: { name: plan },
            unit_amount: amount_cents,
          },
          quantity: 1,
        },
      ],
      metadata: {
        user_id: user.id, // Intentional — fails build until auth is wired (see TODO above)
        plan,
        amount_cents: String(amount_cents),
      },
      success_url: `${siteUrl}/`,
      cancel_url: `${siteUrl}/`,
    });

    return NextResponse.json({ url: session.url });
  } catch (error) {
    if (error instanceof z.ZodError) {
      return NextResponse.json({ error: "Invalid request" }, { status: 400 });
    }
    return NextResponse.json({ error: "Checkout failed" }, { status: 500 });
  }
}
```

Notes:
- Rate limiting: the template includes an in-memory burst limiter (`rateLimit` from `@/lib/rate-limit`). See the hosting stack file for the rate limiter implementation.
- Validates request body with zod (plan name)
- Creates a Stripe Checkout Session in `payment` mode (change to `subscription` for recurring)
- Sets `success_url` and `cancel_url` using `NEXT_PUBLIC_SITE_URL` environment variable with a `localhost:3000` fallback when the var is absent — never use client-controlled headers for redirect URLs
- Returns the session URL to the client
- If `stack.analytics` is present: fire `pay_start` analytics event before redirecting — use the typed `trackPayStart()` wrapper from `events.ts` (client-side, before calling this route). Skip if analytics is absent.
- The `user.id` reference is intentionally undefined in the template — it causes a build error until auth is integrated. See the auth stack file's "Server-Side Auth Check" section for the correct import and guard pattern. The `metadata` object is critical — the webhook handler reads `session.metadata.user_id` to update the database.
- The `PLAN_PRICES[plan]` reference is intentionally undefined — it causes a build error until server-side pricing is implemented. Define a price map or query the database. Never accept prices from the client (see Security section). The `amount_cents` value flows into session metadata and is read by the webhook handler.

### `src/app/api/webhooks/stripe/route.ts` — Stripe Webhook Handler

When `stack.analytics` is absent: remove the `@/lib/analytics-server` import and the `await trackServerEvent()` call from the template below. The webhook will still process payments correctly without analytics.

The template uses **INSERT + catch PG `23505`** for idempotency (see `supabase/migrations/xxx_stripe_events.sql` below). Stripe delivers at-least-once; a SELECT-then-INSERT check is a TOCTOU race that can double-process the same event under concurrent delivery. The UNIQUE constraint on `stripe_event_id` + the catch of the `23505` unique-violation error code is atomic and safe by default.

```ts
import { NextResponse } from "next/server";
import { getStripe } from "@/lib/stripe";
import { createServiceRoleClient } from "@/lib/supabase-server";
import { trackServerEvent } from "@/lib/analytics-server";

// NOTE: No rate limiting on the webhook endpoint.
// Stripe retries failed events (network errors, 500s, timeouts) on a schedule —
// a rate limiter would block legitimate retries and silently drop payment events.
// The actual security defense is stripe.webhooks.constructEvent(), which rejects
// any request without a valid STRIPE_WEBHOOK_SECRET-signed stripe-signature header.
// See the "Do not rate-limit signed webhooks" Stack Knowledge entry below.
export async function POST(request: Request) {
  const body = await request.text();
  const signature = request.headers.get("stripe-signature");

  if (!signature) {
    return NextResponse.json({ error: "Bad request" }, { status: 400 });
  }

  let event;
  try {
    event = getStripe().webhooks.constructEvent(
      body,
      signature,
      process.env.STRIPE_WEBHOOK_SECRET!
    );
  } catch {
    return NextResponse.json({ error: "Bad request" }, { status: 400 });
  }

  // Idempotency guard: INSERT + catch PG 23505 (unique_violation).
  // This is atomic — two concurrent deliveries of the same event_id will
  // produce exactly one successful insert; the other receives 23505 and
  // exits early with 200 so Stripe does not retry.
  const supabase = createServiceRoleClient();
  const { error: insertErr } = await supabase
    .from("stripe_events")
    .insert({ stripe_event_id: event.id });
  if (insertErr) {
    if ((insertErr as { code?: string }).code === "23505") {
      return NextResponse.json({ received: true });
    }
    return NextResponse.json({ error: "Persistence error" }, { status: 500 });
  }

  if (event.type === "checkout.session.completed") {
    const session = event.data.object;
    const userId = session.metadata?.user_id ?? "unknown";
    // TODO: Update user's payment status in database using userId

    await trackServerEvent("pay_success", userId, {
      plan: session.metadata?.plan ?? "",
      amount_cents: Number(session.metadata?.amount_cents ?? 0),
      provider: "stripe",
    });
  }

  return NextResponse.json({ received: true });
}
```

#### Idempotency migration (`supabase/migrations/<N>_stripe_events.sql`)

```sql
create table if not exists stripe_events (
  stripe_event_id text primary key,
  received_at timestamptz not null default now()
);

-- Only the service role writes to this table (webhook handler uses createServiceRoleClient).
-- No RLS-exposed access from clients.
alter table stripe_events enable row level security;

drop policy if exists "service role writes stripe events" on stripe_events;
create policy "service role writes stripe events"
  on stripe_events
  for all
  using (auth.role() = 'service_role')
  with check (auth.role() = 'service_role');
```

The primary key on `stripe_event_id` is what makes the INSERT+catch-23505 pattern atomic — PostgreSQL rejects the second insert with `23505` (`unique_violation`) inside the same transaction window as the first.

Notes:
- No rate limiting: the webhook endpoint deliberately omits the in-memory burst limiter that the checkout route uses (10/min). Stripe delivers webhook events at-least-once and retries failed deliveries (network errors, 500s, timeouts) on a schedule — a rate limiter would block legitimate retries and silently drop payment events (`pay_success` would never fire for affected sessions). The cryptographic security boundary is `stripe.webhooks.constructEvent()` with `STRIPE_WEBHOOK_SECRET`; volume-based abuse protection belongs at the CDN/WAF layer if needed at all. See the "Do not rate-limit signed webhook endpoints — signature verification is the defense" Stack Knowledge entry below.
- Reads the raw request body (do NOT parse JSON before verification)
- Verifies the webhook signature using `STRIPE_WEBHOOK_SECRET`
- Handles `checkout.session.completed` event: should update payment status (see TODO in template) and fires `pay_success` server-side via `trackServerEvent()` with all required experiment/EVENTS.yaml properties (`plan`, `amount_cents`, `provider`)
- The `// TODO: Update user's payment status in database` compiles silently — unlike the checkout route's `user.id` reference which fails the build. You must implement the database update using the `userId` extracted from session metadata before the payment flow is complete. Without this, successful payments are not recorded.
- Extracts `user_id`, `plan`, and `amount_cents` from session metadata (set during checkout creation)
- Returns `200` for all event types (don't error on unknown events)

## Production Observability

When `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` is missing or empty, `src/lib/stripe-client.ts` falls back to the literal placeholder `placeholder-stripe-publishable`. Stripe's `loadStripe()` does NOT surface a configuration error for an invalid publishable key — checkout silently fails when the user clicks "Pay" — so the misconfiguration is invisible until a real conversion attempt fails.

**Fail-loud mechanism (issue #1170 follow-up):** `stripe-client.ts` performs a module-load `console.error` when the placeholder is in use AND the page is running on a deployed host (hostname not in `["localhost", "127.0.0.1", "0.0.0.0", "[::1]"]`, not `*.local`, and not a Vercel preview build). When misconfigured, `stripePromise` is exported as `null`; client components MUST treat a `null` promise as "checkout disabled" — never call Stripe APIs through it.

This warning surfaces at first page load, before any user clicks "Pay", giving operators time to set the correct `pk_test_*` / `pk_live_*` value in the hosting platform.

The server-side `getStripe()` factory in `src/lib/stripe.ts` already throws when `STRIPE_SECRET_KEY` is missing (line 60-62) — that path is loud by design. Only the client-side publishable key needed the additional surfacing.

## Patterns
- Use **Stripe Checkout** (hosted payment page) — never handle raw card data
- Fire `pay_start` when redirecting the user to Checkout
- Fire `pay_success` in the webhook handler (server-side confirmation)
- Always verify webhook signatures — reject requests with invalid signatures
- Use `metadata` on the Checkout Session to pass `user_id` for database updates in the webhook

## Security
- Never expose `STRIPE_SECRET_KEY` or `STRIPE_WEBHOOK_SECRET` to the client
- Always verify webhook signatures before processing events
- Use the server-side Stripe client (`stripe.ts`) only in API routes
- Validate all amounts and plan names server-side — never trust client-provided prices

## Analytics Integration
- `pay_start`: fire client-side when the client receives the Checkout URL and redirects — use the typed `trackPayStart()` wrapper from `events.ts` (per CLAUDE.md Rule 2)
- `pay_success`: fired server-side in the webhook handler via `trackServerEvent()` from `analytics-server.ts` after confirming `checkout.session.completed` — includes all required properties (`plan`, `amount_cents`, `provider`)
- See experiment/EVENTS.yaml for the full property spec for both events

## Stack Knowledge

### Do not rate-limit signed webhook endpoints — signature verification is the defense

Stripe (and every other signed-webhook provider — Twilio, Retell, GitHub Apps, etc.) delivers events at-least-once and retries failed deliveries (network errors, 500s, timeouts) on a schedule. A rate limiter on the webhook route blocks legitimate provider retries: the route returns 429 to a retry, Stripe marks the delivery as failed, eventually gives up, and the corresponding payment event silently never fires (`pay_success` is lost, downstream provisioning runs forever-pending).

The cryptographic security boundary is `stripe.webhooks.constructEvent(body, signature, STRIPE_WEBHOOK_SECRET)`. An attacker without the secret cannot forge a valid signature — the route already rejects unsigned/invalid requests at the signature check with 400. Adding a rate limiter on top adds zero security and actively harms reliability.

```typescript
// WRONG — rate-limit on signed webhook silently drops Stripe retries:
import { rateLimit, clientIpFromHeaders } from "@/lib/rate-limit";

export async function POST(request: Request) {
  const ip = clientIpFromHeaders(request.headers);
  const { success } = rateLimit(ip, { limit: 30, windowMs: 60_000 });
  if (!success) return NextResponse.json({ error: "Too many requests" }, { status: 429 });
  // ... signature verification ...
}

// CORRECT — no rate limit; signature verification IS the auth layer:
export async function POST(request: Request) {
  const body = await request.text();
  const signature = request.headers.get("stripe-signature");
  if (!signature) return NextResponse.json({ error: "Bad request" }, { status: 400 });
  const event = getStripe().webhooks.constructEvent(body, signature, process.env.STRIPE_WEBHOOK_SECRET!);
  // ... process event ...
}
```

Applies universally to every signed-webhook stack: `stripe.webhooks.constructEvent()`, Twilio's `X-Twilio-Signature` HMAC-SHA1 verification, Retell's API-key-signed webhooks, GitHub App webhook signatures, etc. Volume-based abuse protection at the CDN/WAF layer is a separate question — Cloudflare/Vercel WAF can drop egregious traffic before it hits the route. Application-level rate limiting on the signed-webhook handler is the anti-pattern.

The atomicity defense (preventing duplicate side-effects from at-least-once delivery) is the `INSERT + catch PG 23505` idempotency guard documented in the next entry — that's the right shape for handling replays, not rate limiting.

### When deduplicating Stripe webhook replays, use INSERT + catch PG `23505` (already baked into the template)
Stripe delivers at-least-once, so webhook replays are expected. The route template above uses the correct pattern: `INSERT INTO stripe_events(stripe_event_id)` and catch PostgreSQL error code `23505` (unique_violation) as a successful no-op. **Do NOT rewrite this as a SELECT-then-INSERT check** — that is a Time-of-Check-Time-of-Use (TOCTOU) race: two concurrent deliveries of the same event ID can both pass the SELECT and both INSERT, causing duplicate side-effects (double payment processing, double `trackServerEvent("pay_success")`). The INSERT + catch-`23505` pattern is atomic at the database level via the `PRIMARY KEY` on `stripe_event_id`; keep it.

### When the Stripe webhook provisions a user account, never resolve identity via customer_email
The `checkout.session.completed` event carries `customer_email` but this field is attacker-controlled — a Stripe customer object can be created with any email address. Resolving a Supabase user via `listUsers({ filter: 'email=...' })` (or any database lookup keyed on the Stripe-supplied email) and then upserting a subscribers row creates a cross-account billing IDOR: an attacker who creates a Stripe customer with a victim's email hijacks the provisioning flow.

```typescript
// WRONG — listUsers({email}) treats Stripe-controlled customer_email as identity
const { data: list } = await sb.auth.admin.listUsers({ filter: `email=${session.customer_email}` });
const user = list.users[0];  // attacker controls this lookup

// CORRECT — only session.metadata.user_id (set at checkout creation by an authenticated server route)
const userId = session.metadata?.user_id;
if (!userId) return NextResponse.json({ error: "Missing user_id" }, { status: 400 });
```

For unauthenticated checkout flows where no `user_id` exists at checkout creation time (guest gift purchases, lead-magnet checkouts), use a server-side lookup-token table — not Stripe metadata — to bind the Checkout Session to the recipient. This is the same pattern as gift-purchase PII storage (see "When implementing gift purchases, store PII in a server-side table" below).

A second class applies to new-account creation in webhooks: creating a Supabase user with `email_confirm: true` lets an attacker pre-claim `victim@example.com` before the real user signs up. Always set `email_confirm: false` (or equivalent) when creating accounts from webhook context — the user confirms via the normal magic-link / OTP flow.

### When a Stripe key appears as a literal in a test fixture, avoid the sk_test_ / pk_test_ prefix
Hardcoded values like `sk_test_demo`, `sk_test_abc123`, or any string beginning with `sk_test_` / `pk_test_` trigger secret-scanning false positives in CI, in `gitleaks`-style audits, and in GitHub's push-protection secret-scanning. The scanners match the Stripe key prefix pattern regardless of whether the value is a real key. Use a descriptive placeholder that does NOT match the Stripe key format — prefer the `placeholder-stripe-*` family already declared in this stack's frontmatter `ci_placeholders` slot for self-consistency.

```ts
// WRONG — `sk_test_` prefix triggers secret-scanning FPs
process.env.STRIPE_SECRET_KEY = "sk_test_demo";
process.env.STRIPE_SECRET_KEY = "sk_test_abc123";

// CORRECT — re-use the placeholder name declared in the stack frontmatter
process.env.STRIPE_SECRET_KEY = "placeholder-stripe-secret";
process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY = "placeholder-stripe-publishable";
process.env.STRIPE_WEBHOOK_SECRET = "placeholder-stripe-webhook-secret";
```

This applies to ALL test files (Vitest, Jest, Playwright global setup) that hardcode a mock Stripe key, and to any inline docs/README code samples. The stack file's own `loadStripe` fallback near the top of this file already uses the safe `placeholder-stripe-publishable` — do the same for fixtures.

### Never use client-submitted bounds for amount validation — re-read authoritative values from the database
API routes that accept client-submitted numeric bounds (price ranges, discount bounds, quantity limits, quote-tier floors/ceilings) and use those bounds to validate or clamp a final value are vulnerable to fraud: the client controls both the submitted value AND the bounds it is validated against. A client can submit `{range_low: 0, range_high: 1e9, final: 1}` and bypass the intended tier constraints entirely. The authoritative bounds must be sourced from the database (server-computed values tied to a user/tier/product), not from the request body.

```typescript
// WRONG — client-submitted bounds used for CLAMP validation
const { range_low, range_high, final } = await req.json();
if (final < range_low || final > range_high) return error();  // client controls both sides

// CORRECT — re-read authoritative bounds from DB keyed on a server-known entity
const { quoteId, final } = await req.json();
const { range_low, range_high } = await db.quotes.findOne({ id: quoteId, userId });
if (final < range_low || final > range_high) return error();  // bounds come from DB
```

This applies to checkout confirm routes, quote confirm/finalize routes, admin amount-adjust routes, discount-apply routes, and any route where a client posts a numeric value alongside its own "intended range." The pattern also applies to non-Stripe payment flows — it is the general principle for server-authoritative numeric constraints. The Zod schema can still validate shape (`range_low: z.number().nonnegative()`) but must not validate the relationship between client fields; the relationship check must use server-sourced bounds.

### When NEXT_PUBLIC_SITE_URL is missing, Stripe checkout redirect URLs become "undefined/path"
The checkout route template uses a `localhost:3000` fallback when building Stripe redirect URLs. Without it, the env var evaluates to `undefined` and produces `undefined/dashboard/setup` — a URL Stripe accepts silently, causing post-payment redirects to fail. The fallback is a defensive measure for local development before `NEXT_PUBLIC_SITE_URL` is configured. In production, the env var should always be set.

```typescript
const siteUrl = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";
success_url: `${siteUrl}/`,
cancel_url: `${siteUrl}/`,
```

### When checkout is gated by a capability token, validate the token in `/api/checkout` with the same TTL + constant-time compare used by the resource route

Any checkout route that accepts a `session_id` (or similar pending-record key) to identify what the user is purchasing MUST also require and validate the capability token associated with that session — using the same 3-step check applied by the resource endpoint: (1) well-formed token (e.g., 43-char base64url), (2) TTL not expired (`token_expires_at > now()`), (3) constant-time comparison via `crypto.timingSafeEqual`. Without this, a leaked resource URL becomes a purchase oracle: a caller who obtains the `session_id` can trigger a $X checkout even after the token has expired or been used.

The complementary client-side gap: the page component that reads the token from the URL (`?t=<base64url>`) MUST also include the token in the checkout POST body — otherwise the server has no token to validate even if it tried.

```typescript
// In /api/checkout — after parsing the request body:
const { session_id, preview_token } = checkoutRequestSchema.parse(body);
const { data: session } = await supabase
  .from("pending_sessions")
  .select("preview_token, preview_token_expires_at")
  .eq("id", session_id)
  .single();
if (
  !session ||
  !preview_token ||
  preview_token.length !== 43 ||
  new Date(session.preview_token_expires_at) < new Date() ||
  !crypto.timingSafeEqual(
    Buffer.from(preview_token),
    Buffer.from(session.preview_token),
  )
) {
  return NextResponse.json({ error: "Forbidden" }, { status: 403 });
}
```

Client-side requirements:
- Read the token from the URL query param (e.g., `?t=`).
- Route to an empty / error state when the token parameter is absent.
- Include the token in the JSON body sent to `/api/checkout`.

Forward the validated token in `cancel_url` so returning buyers do not hit the empty state:

```typescript
cancel_url: `${siteUrl}/preview?session=${session_id}&t=${preview_token}`,
```

**Applies to:** any Next.js + Stripe project where a resource page (preview, report, PDF, etc.) is gated by a short-lived URL token AND a paid checkout unlocks the full content. The token-validation rule is independent of the broader `customer_email IDOR` rule above — both apply when both conditions are present.

### When implementing gift purchases, store PII in a server-side table — not in Stripe metadata
Stripe Checkout Session `metadata` is readable by anyone with Stripe dashboard access or webhook-consumer access. Placing buyer/recipient PII (name, email, personal note) in metadata creates unnecessary exposure. Stripe metadata values are also capped at 500 characters per value — real names + heartfelt notes can exceed this and the Checkout Session creation call fails silently or truncates.

Safe pattern (3 steps):

1. In the gift checkout API route, INSERT a `pending_gifts` row keyed on the soon-to-be-created `session.id` (or a server-generated `gift_token` you also pass to Stripe). Store buyer/recipient PII here, not in Stripe.
2. In Stripe metadata, store ONLY non-PII identifiers: `is_gift: "true"`, `plan_id`, `amount_cents`, `recipient_email_hash` (SHA-256 of lowercase+trimmed email — for dedup checks without revealing the address).
3. In the webhook `checkout.session.completed` handler, SELECT the `pending_gifts` row by the same key, provision the gift, then DELETE the row (point-in-time PII — do not retain after use).

```sql
-- Schema sketch (database-stack-aware access control — see your database stack file)
create table pending_gifts (
  session_id text primary key,
  buyer_email text not null,
  buyer_name text not null,
  recipient_email text not null,
  recipient_name text not null,
  personal_note text,
  created_at timestamptz not null default now()
);
```

**Access control is database-stack-specific:**
- When `stack.database` is `supabase`: enable RLS with a service-role-only policy (same pattern as the `stripe_events` table above — see `.claude/stacks/database/supabase.md`).
- When `stack.database` is `sqlite` (no RLS): route the table behind service-role API calls only — never expose the table to client code. Enforce access in route handlers (see `.claude/stacks/database/sqlite.md`).

This pattern is exactly the lookup-token-in-server-table referenced by the customer_email IDOR entry above — gift purchases ARE the canonical anonymous-checkout flow that needs it.

### When checkout session mode is `subscription`, also set `subscription_data.metadata`

Stripe does NOT propagate Session-level `metadata` to the Subscription object created at the end of checkout. If the webhook handler reads `subscription.metadata.user_id` (the canonical pattern for recurring billing) but `subscription_data.metadata` was never set at checkout creation, `user_id` is `undefined` and downstream provisioning fails. On Supabase this surfaces as a UUID column violation when the webhook tries to insert into `subscribers(user_id, ...)`; the fallback path that uses the Stripe customer ID (e.g., `cus_XXX`) orphans the paying customer because no Supabase user matches that string.

The existing template at the top of this file uses `mode: "payment"` (one-time purchases), so this bug is not exercised by the shipped scaffold. It only surfaces when a project switches to `mode: "subscription"`. Always set BOTH `metadata` (Session-level — for ad-platform attribution, which reads from the Session) AND `subscription_data.metadata` (Subscription-level — for the webhook handler, which reads from the Subscription).

```typescript
const session = await getStripe().checkout.sessions.create({
  mode: "subscription",
  // Session-level metadata — ad pixels read THIS (Stripe Session), not the Subscription
  metadata: {
    user_id: user.id,
    plan,
    amount_cents: String(amount_cents),
  },
  // REQUIRED when the webhook reads subscription.metadata.user_id
  subscription_data: {
    metadata: {
      user_id: user.id,
      plan,
      amount_cents: String(amount_cents),
    },
  },
  line_items: [{ price: STRIPE_PRICE_ID, quantity: 1 }],
  success_url: `${siteUrl}/`,
  cancel_url: `${siteUrl}/`,
});
```

Keep BOTH blocks — they serve different consumers:

- **Session metadata** — ad-platform attribution (Meta Conversions API, Google Ads, etc.) reads the Stripe Session object, not the Subscription. Drop this and ad-attribution breaks.
- **Subscription metadata** — the webhook handler's canonical source for `user_id` when provisioning recurring access. Drop this and the webhook misroutes (orphaned subscriber rows on Supabase, UUID column violation).

When migrating an existing `mode: "payment"` template to `mode: "subscription"`, audit the webhook handler for `subscription.metadata.*` reads BEFORE flipping the mode — if the handler is still reading `session.metadata.*` only, propagation works without `subscription_data.metadata`. The bug surfaces only when consumer (webhook) and producer (checkout) diverge on which object they trust.

## PR Instructions
- After merging, set these environment variables in your hosting provider:
  - `STRIPE_SECRET_KEY` — from Stripe Dashboard > Developers > API keys
  - `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` — from Stripe Dashboard > Developers > API keys
  - `STRIPE_WEBHOOK_SECRET` — from Stripe Dashboard > Developers > Webhooks (create a webhook endpoint pointing to `https://your-domain/api/webhooks/stripe`)
- Configure the Stripe webhook to listen for `checkout.session.completed` events
