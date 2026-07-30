---
assumes: [framework/nextjs]
packages:
  runtime: [retell-sdk]
  dev: []
files:
  - src/lib/retell.ts
  - src/app/api/webhooks/retell/route.ts
env:
  server: [RETELL_API_KEY]
  client: []
ci_placeholders: {}
clean:
  files: []
  dirs: []
gitignore: []
---
# External: Retell AI
> Used when experiment.yaml behaviors require AI voice agents or Retell AI webhooks
> Assumes: `framework/nextjs` for API route handlers

## Packages
```bash
npm install retell-sdk
```

## Files to Create

### `src/lib/retell.ts` — Retell AI client and helpers
```ts
import Retell, { verify } from "retell-sdk";

const apiKey = process.env.RETELL_API_KEY;

if (!apiKey) {
  console.error("[503] Retell AI not configured — run /deploy to provision");
}

export const retellClient = apiKey ? new Retell({ apiKey }) : null;

/**
 * Verify Retell AI webhook signature using the SDK helper. Retell signs
 * webhooks with the API key itself (not a separate webhook secret); the
 * `x-retell-signature` header has format `v=<timestamp_ms>,d=<hex_digest>`
 * and the SDK enforces the 5-minute timestamp window via constant-time
 * comparison. See https://docs.retellai.com/features/secure-webhook.
 */
export async function verifyRetellSignature(
  body: string,
  signature: string | null,
): Promise<boolean> {
  if (!apiKey || !signature) return false;
  try {
    return await verify(body, apiKey, signature);
  } catch {
    return false;
  }
}
```

### `src/app/api/webhooks/retell/route.ts` — Webhook handler template
```ts
import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { verifyRetellSignature } from "@/lib/retell";

export async function POST(req: NextRequest) {
  if (!process.env.RETELL_API_KEY) {
    return NextResponse.json({ error: "Service unavailable" }, { status: 503 });
  }

  // Read raw body before parsing
  const rawBody = await req.text();
  const signature = req.headers.get("x-retell-signature");

  if (!(await verifyRetellSignature(rawBody, signature))) {
    return NextResponse.json({ error: "Bad request" }, { status: 401 });
  }

  const payload = JSON.parse(rawBody);

  // Validate payload with strict Zod schema
  const retellWebhookSchema = z.object({
    event: z.string().max(100),
    call: z.object({
      call_id: z.string().max(200),
      agent_id: z.string().max(200),
      call_status: z.string().max(50).optional(),
      start_timestamp: z.number().optional(),
      end_timestamp: z.number().optional(),
      transcript: z.string().max(50000).optional(),
      recording_url: z.string().url().max(2000).optional(),
    }).passthrough(),
  }).passthrough();

  const parsed = retellWebhookSchema.safeParse(payload);
  if (!parsed.success) {
    console.error("Retell webhook validation failed: %d issues", parsed.error.issues.length);
    return NextResponse.json({ error: "Bad request" }, { status: 400 });
  }

  // Cross-validate agent_id against stored record before processing
  // const agentId = parsed.data.call.agent_id;
  // const agent = await supabase.from("agents").select("id").eq("retell_agent_id", agentId).single();
  // if (!agent.data) return NextResponse.json({ error: "Bad request" }, { status: 400 });

  // If payload contains user_id: validate against profiles table before inserting
  // const userId = parsed.data.call.metadata?.user_id;
  // if (userId) {
  //   const profile = await supabase.from("profiles").select("id").eq("id", userId).single();
  //   if (!profile.data) return NextResponse.json({ error: "Bad request" }, { status: 400 });
  // }

  return NextResponse.json({ received: true });
}
```

## Environment Variables
```
RETELL_API_KEY=your-api-key                # Retell AI API key (also signs webhooks — no separate secret)
```

Retell does NOT issue a separate webhook-signing secret. Webhooks are signed
with the API key itself. Do not introduce a separate webhook-signing env var —
see https://docs.retellai.com/features/secure-webhook.

## Patterns
- Verify webhook signatures with the SDK's `verify(body, apiKey, signature)` helper — it parses the `v=<timestamp_ms>,d=<hex_digest>` header format, enforces a 5-minute timestamp window, and does constant-time comparison. Do NOT hand-roll HMAC-SHA256 over the body only — Retell signs `body + timestamp`, not just body.
- Read the raw body before JSON parsing so the bytes passed to `verify()` match what Retell signed
- After signature verification, validate the payload with a strict Zod schema including `.max()` bounds on all string and array fields — a valid signature does not guarantee safe field lengths or types
- After schema validation, cross-validate `agent_id` in the payload against the stored record in the database — a valid signature alone does not prevent a legitimate agent from posting to the wrong endpoint
- If the payload contains user-supplied fields like `user_id`, validate them against the profiles table before inserting webhook data — a valid signature proves Retell sent the payload, not that the user_id belongs to a real user
- Avoid logging raw Zod validation errors — log only the error count to prevent leaking request structure

## Security
- SDK `verify()` signature verification is mandatory on all webhook routes — without it, any caller can send arbitrary payloads
- Redact phone numbers and PII from all log output
- Remove internal service names from error responses returned to callers
- Do NOT rate-limit signed webhook routes — Retell signs webhooks with the API key + retries on failures. A rate limiter would block legitimate retries and silently drop call-completion / agent-end events. The SDK `verify()` check IS the security boundary (issue #1378). See `.claude/stacks/payment/stripe.md` → "Do not rate-limit signed webhook endpoints" for the universal pattern.

## CLI Provisioning
No CLI available — credentials must be obtained via the Retell AI dashboard at https://www.retellai.com.

## PR Instructions
- Sign up at https://www.retellai.com and create a project
- Copy the API key from the dashboard (also used for webhook signature verification — no separate secret)
- Add `RETELL_API_KEY` to `.env.local`
- Set the webhook URL in Retell AI → Agents → select agent → Webhook URL
