---
assumes: [framework/nextjs, database/supabase, auth/supabase]
packages:
  runtime: [resend]
  dev: []
files:  # conditional: requires framework/nextjs, database/supabase, auth/supabase
  - src/lib/email.ts
  - src/app/api/email/welcome/route.ts
  - src/app/api/email/welcome-webhook/route.ts
  - src/app/api/email/nudge/route.ts
  - vercel.json
env:
  server: [RESEND_API_KEY, CRON_SECRET, RESEND_FROM, SUPABASE_WEBHOOK_SECRET, NEXT_PUBLIC_APP_ORIGIN]
  client: []
ci_placeholders:
  RESEND_API_KEY: re_placeholder_key
  CRON_SECRET: placeholder-cron-secret
  RESEND_FROM: noreply@placeholder.example.com
clean:
  files: []
  dirs: []
gitignore: []
---
Transactional email for retention: welcome email after signup + 24h activation nudge via cron.

## Setup

1. Sign up at [resend.com](https://resend.com) and go to **API Keys** → create a new key
2. Add the key to `.env.local`: `RESEND_API_KEY=re_...`
3. **Domain verification** — optional for local testing (uses `onboarding@resend.dev` sandbox). For production: verify your domain in Resend → Domains, add DNS records (DKIM, SPF, Return-Path). `/deploy` sets `RESEND_FROM=noreply@<domain>` automatically.

## Packages

```bash
npm install resend
```

## Files to Create

### `src/lib/email.ts`

```ts
import { Resend } from "resend";

let _resend: Resend | null = null;

function getResend(): Resend {
  if (!_resend) {
    if (!process.env.RESEND_API_KEY) {
      throw new Error("RESEND_API_KEY is not configured");
    }
    _resend = new Resend(process.env.RESEND_API_KEY);
  }
  return _resend;
}

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#x27;");
}

function sanitizeSubject(str: string): string {
  return str.replace(/[\r\n\0]/g, "");
}

function safeUrl(url: string): string {
  if (url === "/" || (url.startsWith("/") && !url.startsWith("//"))) return url;
  if (url.startsWith("https://")) return url;
  throw new Error("Invalid URL: must be https:// or a relative path");
}

const FROM_ADDRESS = process.env.RESEND_FROM || "onboarding@resend.dev";

export async function sendWelcomeEmail(to: string, name: string, ctaUrl: string) {
  if (process.env.DEMO_MODE === "true" && process.env.VERCEL === "1") {
    throw new Error("DEMO_MODE is not allowed in production");
  }
  if (process.env.DEMO_MODE === "true") return;
  const safeName = escapeHtml(name);
  const safeCtaUrl = safeUrl(ctaUrl);
  const { error } = await getResend().emails.send({
    from: FROM_ADDRESS,
    to,
    subject: `Welcome to the app, ${sanitizeSubject(name)}!`,
    html: `
      <h1>Welcome, ${safeName}!</h1>
      <p>Thanks for signing up. We built this to help you get started fast.</p>
      <p><a href="${safeCtaUrl}" style="display:inline-block;padding:12px 24px;background:#2563eb;color:#fff;border-radius:6px;text-decoration:none;">Get Started</a></p>
    `,
  });
  if (error) throw error;
}

export async function sendActivationNudge(to: string, name: string, activationAction: string, ctaUrl: string) {
  if (process.env.DEMO_MODE === "true" && process.env.VERCEL === "1") {
    throw new Error("DEMO_MODE is not allowed in production");
  }
  if (process.env.DEMO_MODE === "true") return;
  const safeName = escapeHtml(name);
  const safeAction = escapeHtml(activationAction);
  const safeCtaUrl = safeUrl(ctaUrl);
  const { error } = await getResend().emails.send({
    from: FROM_ADDRESS,
    to,
    subject: `Quick reminder: ${sanitizeSubject(activationAction)}`,
    html: `
      <h1>Hey ${safeName}, you're almost there</h1>
      <p>You signed up but haven't ${safeAction} yet. It only takes a minute.</p>
      <p><a href="${safeCtaUrl}" style="display:inline-block;padding:12px 24px;background:#2563eb;color:#fff;border-radius:6px;text-decoration:none;">${safeAction}</a></p>
    `,
  });
  if (error) throw error;
}
```

### `src/app/api/email/welcome/route.ts` — Cookie-authed handler

Called from the auth success callback after `signup_complete` for client-driven flows where the user is logged-in (cookie session present). Sends a welcome email with the value prop and a CTA. Bootstrap generates the route **without** `trackServerEvent()` — see "Analytics Integration" below for how to add telemetry via `/change` after bootstrap.

**Security contract:** the route MUST derive `to` from the authenticated session and construct `ctaUrl` server-side. NEVER accept `to` or `ctaUrl` from the request body — that turns the route into an open phishing relay (an attacker forges arbitrary recipients and embeds attacker-controlled URLs in emails sent from your verified Resend domain). See `## Caveats` below.

```ts
import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { createServerSupabaseClient } from "@/lib/supabase-server";
import { sendWelcomeEmail } from "@/lib/email";
import { rateLimit } from "@/lib/rate-limit";

// Body is intentionally narrow: name only. `to` comes from the session,
// `ctaUrl` is constructed server-side from APP_ORIGIN.
const welcomeSchema = z.object({
  name: z.string().max(200),
});

export async function POST(req: NextRequest) {
  const supabase = await createServerSupabaseClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user?.email) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const limited = await rateLimit(`email:welcome:${user.id}`, { max: 3, windowSec: 86400 });
  if (!limited.ok) {
    return NextResponse.json({ error: "Too many welcome requests" }, { status: 429 });
  }

  const body = welcomeSchema.safeParse(await req.json());
  if (!body.success) {
    return NextResponse.json({ error: "Invalid request" }, { status: 400 });
  }

  // ctaUrl is constructed server-side — never accepted from the client body.
  const origin = process.env.NEXT_PUBLIC_APP_ORIGIN!;
  const ctaUrl = `${origin}/dashboard`;

  await sendWelcomeEmail(user.email, body.data.name, ctaUrl);

  return NextResponse.json({ ok: true });
}
```

### `src/app/api/email/welcome-webhook/route.ts` — Webhook-triggered handler

Called by Supabase `auth.user.created` webhook (or any signed server-event source like a Stripe `customer.created` or an admin-action queue). There is no cookie session, so the cookie-authed handler above does not apply. The route MUST verify the webhook signature and use the verified payload as the source of truth for `to`. Constants:

| Concern | Cookie-authed | Webhook-triggered |
|---|---|---|
| Source of `to` | `supabase.auth.getUser().user.email` | verified webhook payload (`payload.record.email`) |
| Source of `ctaUrl` | server-constructed from `NEXT_PUBLIC_APP_ORIGIN` | server-constructed from `NEXT_PUBLIC_APP_ORIGIN` |
| Authentication | Supabase auth cookies | webhook signature (HMAC) |
| Client used | `createServerSupabaseClient()` | `createServiceRoleClient()` (no cookie context) |

```ts
import { NextRequest, NextResponse } from "next/server";
import { createHmac, timingSafeEqual } from "crypto";
import { sendWelcomeEmail } from "@/lib/email";
import { rateLimit } from "@/lib/rate-limit";

export async function POST(req: NextRequest) {
  // 1. Verify the webhook signature — HMAC over the raw request body.
  const signature = req.headers.get("x-webhook-signature") ?? "";
  const secret = process.env.SUPABASE_WEBHOOK_SECRET;
  if (!secret) {
    return NextResponse.json({ error: "webhook not configured" }, { status: 500 });
  }
  const raw = await req.text();
  const expected = createHmac("sha256", secret).update(raw).digest("hex");
  const a = Buffer.from(signature);
  const b = Buffer.from(expected);
  if (a.length !== b.length || !timingSafeEqual(a, b)) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  // 2. Parse the now-verified payload. `to` comes from the verified body — NEVER trust unverified input.
  const payload = JSON.parse(raw) as { type: string; record?: { email?: string; raw_user_meta_data?: { name?: string } } };
  if (payload.type !== "INSERT" || !payload.record?.email) {
    return NextResponse.json({ ok: true, skipped: true });
  }

  // 3. Per-recipient rate-limit (defense in depth — Supabase webhooks are authoritative but throttling at the relay protects against replay attacks).
  const limited = await rateLimit(`email:welcome-webhook:${payload.record.email}`, { max: 3, windowSec: 86400 });
  if (!limited.ok) {
    return NextResponse.json({ error: "rate-limited" }, { status: 429 });
  }

  const origin = process.env.NEXT_PUBLIC_APP_ORIGIN!;
  const ctaUrl = `${origin}/welcome`;
  const name = payload.record.raw_user_meta_data?.name ?? "there";

  await sendWelcomeEmail(payload.record.email, name, ctaUrl);
  return NextResponse.json({ ok: true });
}
```

Configure the webhook in the Supabase Dashboard: Database → Webhooks → New Hook → Source: `auth.users` → Method: POST → URL: `${APP_ORIGIN}/api/email/welcome-webhook` → HTTP Headers: `x-webhook-signature: ${HMAC_SHA256(payload, SUPABASE_WEBHOOK_SECRET)}`. Add `SUPABASE_WEBHOOK_SECRET` to Vercel env vars.

## Caveats

The library API (`sendWelcomeEmail({to, ctaUrl, ...})`) takes user-controllable parameters by design — that's its job at the SDK layer. The DANGER is at the route handler that wraps it: if the route accepts `to` or `ctaUrl` from the request body without authentication or allowlisting, the route becomes an open phishing relay:

```bash
curl -X POST https://<your-app>.vercel.app/api/email/welcome \
  -H 'Content-Type: application/json' \
  -d '{"email":"victim@bank.com","ctaUrl":"https://attacker.com/steal","name":"You"}'
```

The email is sent FROM your verified Resend domain (legitimate SPF/DKIM/DMARC), to a victim of the attacker's choosing, embedding an attacker-controlled URL inside a "Welcome to <project>" template. Mass mail-out is throttled only by Resend's outbound rate limit. The brand of your project becomes a phishing primitive — and the abuse will be reported to Resend, who may suspend the entire domain.

Required mitigations (BOTH route shapes above implement them):
- Derive `to` from the verified caller (session OR webhook signature) — NEVER from request body.
- Construct `ctaUrl` server-side from `NEXT_PUBLIC_APP_ORIGIN` + a static path; do NOT accept it from client input.
- Apply per-recipient rate-limiting.

### `src/app/api/email/nudge/route.ts`

Called by Vercel Cron daily. Queries the database for users who signed up > 24h ago AND have not yet activated. Sends a nudge email. Skips users already nudged.

```ts
import { NextRequest, NextResponse } from "next/server";
import { timingSafeEqual } from "crypto";
import { createServerSupabaseClient } from "@/lib/supabase-server";
import { sendActivationNudge } from "@/lib/email";

export async function GET(req: NextRequest) {
  // Validate cron secret (timing-safe to prevent side-channel attacks)
  const authHeader = req.headers.get("authorization") ?? "";
  const expected = `Bearer ${process.env.CRON_SECRET}`;
  const a = Buffer.from(authHeader);
  const b = Buffer.from(expected);
  if (a.length !== b.length || !timingSafeEqual(a, b)) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const supabase = await createServerSupabaseClient();
  const twentyFourHoursAgo = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();

  // Find users who signed up > 24h ago, not activated, not yet nudged
  const { data: users, error } = await supabase
    .from("user_status")
    .select("user_id, email, name, created_at")
    .lt("created_at", twentyFourHoursAgo)
    .is("activated_at", null)
    .is("nudge_sent_at", null);

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  let sent = 0;
  for (const user of users ?? []) {
    try {
      await sendActivationNudge(user.email, user.name, "complete your first action", "/");
      await supabase
        .from("user_status")
        .update({ nudge_sent_at: new Date().toISOString() })
        .eq("user_id", user.user_id);
      sent++;
    } catch {
      // Skip individual failures, continue with remaining users
    }
  }

  return NextResponse.json({ ok: true, sent });
}
```

## Vercel Cron Config

### `vercel.json`

```json
{
  "crons": [
    {
      "path": "/api/email/nudge",
      "schedule": "0 9 * * *"
    }
  ]
}
```

The cron runs daily at 9am UTC. Add `CRON_SECRET` to your Vercel environment variables — Vercel automatically sends this as an `Authorization: Bearer <CRON_SECRET>` header to cron endpoints.

## Database Requirements

The nudge route needs to identify un-activated users. Add these columns to your user-related table (or create a `user_status` table if no user table exists beyond Supabase auth):

- `activated_at timestamptz` — set when the user completes the activation action
- `nudge_sent_at timestamptz` — set after the nudge email is sent (prevents duplicate nudges)

If using Supabase auth only (no custom users table), create a small `user_status` table:

```sql
create table if not exists user_status (
  user_id uuid primary key references auth.users(id),
  email text not null,
  name text not null default '',
  created_at timestamptz not null default now(),
  activated_at timestamptz,
  nudge_sent_at timestamptz
);

alter table user_status enable row level security;

create policy "Service role only" on user_status
  for all using (auth.role() = 'service_role');
```

## Analytics Integration

Email-send tracking is **optional** and is not added to `experiment/EVENTS.yaml` by bootstrap (CLAUDE.md Rule 0 forbids scaffold-time modifications to spec files). The route templates above therefore omit `trackServerEvent()` by default — the welcome and nudge helpers work without analytics.

If you want email telemetry, run `/change "Add email telemetry"` **after** bootstrap. `/change` will:
1. Add the event definitions (`email_welcome_sent`, `email_nudge_sent` with their `funnel_stage` and `properties`) to `experiment/EVENTS.yaml`
2. Regenerate typed wrappers in `src/lib/events.ts`
3. Wire the `trackServerEvent()` calls into `src/app/api/email/welcome/route.ts` and `src/app/api/email/nudge/route.ts`

This keeps the canonical event dictionary aligned with the experiment's spec'd funnel instead of silently expanding it during scaffolding.

## Environment Variables

| Variable | Where | Description |
|----------|-------|-------------|
| `RESEND_API_KEY` | Server | Resend API key from resend.com → API Keys |
| `CRON_SECRET` | Server | Vercel Cron secret — auto-sent as Bearer token to cron endpoints |
| `RESEND_FROM` | Server | Sender address for transactional emails. Set by `/deploy` to `noreply@<domain>`. Defaults to `onboarding@resend.dev` (sandbox) when absent. |

## Email Sender Domain

Both pipelines use the same sender domain when `stack.email: resend` is enabled:

| Pipeline | Sender | Configured By |
|----------|--------|---------------|
| Auth emails (confirmation, reset, magic link) | `noreply@<domain>` | `/deploy` Agent A — Supabase SMTP config |
| Transactional emails (welcome, nudge) | `noreply@<domain>` | `/deploy` state-3b — `RESEND_FROM` env var |

`<domain>` = `deploy.domain` from experiment.yaml; fallback `draftlabs.org`.

**Prerequisite:** Verify domain in Resend Dashboard → Domains (one-time, team-level setup).

## Security

- Always HTML-escape user-supplied values (`name`, `activationAction`) before interpolating into email HTML bodies using the `escapeHtml()` helper — prevents HTML injection via crafted registration names
- Always strip control characters (`\r`, `\n`, `\0`) from values interpolated into email subject lines using `sanitizeSubject()` — prevents email header injection
- Always validate `ctaUrl` with `safeUrl()` before interpolation into `<a href>` — rejects `javascript:`, `data:`, and protocol-relative (`//`) URLs that could redirect users to malicious sites
- The welcome email route (`/api/email/welcome`) must require authentication and validate input with zod — unauthenticated email-sending endpoints can be abused for spam relay
- Never log raw email addresses in production — they are PII

## Without Auth or Database

Email without auth is not supported — the email stack requires `stack.auth` to know who to send emails to and `stack.database` to track activation status. If either dependency is absent, bootstrap will stop with an error before installing the email stack.
