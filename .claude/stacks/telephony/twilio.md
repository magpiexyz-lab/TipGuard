---
assumes: [framework/nextjs]
packages:
  runtime: [twilio]
  dev: []
files:
  - src/lib/twilio.ts
  - src/app/api/webhooks/twilio/route.ts
env:
  server: [TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER]
  client: []
ci_placeholders: {}
clean:
  files: []
  dirs: []
gitignore: []
---
# Telephony: Twilio
> Used when experiment.yaml behaviors require SMS, voice, or Twilio webhooks
> Assumes: `framework/nextjs` for API route handlers

## Packages
```bash
npm install twilio
```

## Files to Create

### `src/lib/twilio.ts` — Twilio client and helpers
```ts
import twilio from "twilio";

const accountSid = process.env.TWILIO_ACCOUNT_SID;
const authToken = process.env.TWILIO_AUTH_TOKEN;

if (!accountSid || !authToken) {
  console.error("[503] Twilio not configured — run /deploy to provision");
}

export const twilioClient = accountSid && authToken
  ? twilio(accountSid, authToken)
  : null;

/**
 * XML-escape a string for safe TwiML interpolation.
 * Prevents TwiML injection via user-supplied or database-stored values.
 */
export function escapeXml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}
```

### `src/app/api/webhooks/twilio/route.ts` — Webhook handler template
```ts
import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { validateRequest } from "twilio";

export async function POST(req: NextRequest) {
  const authToken = process.env.TWILIO_AUTH_TOKEN;
  if (!authToken) {
    return NextResponse.json({ error: "Service unavailable" }, { status: 503 });
  }

  // HMAC-SHA1 signature verification
  const signature = req.headers.get("x-twilio-signature") ?? "";
  const url = req.url;
  const body = await req.text();
  const params = Object.fromEntries(new URLSearchParams(body));

  if (!validateRequest(authToken, signature, url, params)) {
    return NextResponse.json({ error: "Bad request" }, { status: 401 });
  }

  // Validate webhook fields with strict Zod schema
  const twilioWebhookSchema = z.object({
    MessageSid: z.string().max(200).optional(),
    AccountSid: z.string().max(200).optional(),
    From: z.string().max(50).optional(),
    To: z.string().max(50).optional(),
    Body: z.string().max(1600).optional(),
    NumMedia: z.string().max(5).optional(),
    CallSid: z.string().max(200).optional(),
    CallStatus: z.string().max(50).optional(),
    Digits: z.string().max(100).optional(),
  }).passthrough();

  const parsed = twilioWebhookSchema.safeParse(params);
  if (!parsed.success) {
    console.error("Twilio webhook validation failed: %d issues", parsed.error.issues.length);
    return NextResponse.json({ error: "Bad request" }, { status: 400 });
  }

  // Process validated webhook payload...
  return new NextResponse("<Response></Response>", {
    headers: { "Content-Type": "text/xml" },
  });
}
```

## Environment Variables
```
TWILIO_ACCOUNT_SID=your-account-sid       # Twilio Account SID
TWILIO_AUTH_TOKEN=your-auth-token         # Twilio Auth Token (used for HMAC-SHA1 verification)
TWILIO_PHONE_NUMBER=+1234567890           # Twilio phone number for outbound SMS/calls
```

## Patterns
- Always verify HMAC-SHA1 signatures on incoming webhooks using the Twilio SDK's `validateRequest()` function
- Always XML-escape dynamic values before embedding in TwiML responses using the `escapeXml()` helper
- Validate all FormData fields with zod before building TwiML responses
- Use the `escapeXml()` helper for every interpolated value in TwiML — practice names, phone numbers, URLs, and service lists

## Security
- HMAC-SHA1 signature verification is mandatory on all webhook routes — without it, any caller can spoof Twilio callbacks
- XML-escape all dynamic strings in TwiML to prevent TwiML injection (characters like `<`, `>`, `&`, `"` can inject arbitrary TwiML verbs)
- Validate that dynamic URL values belong to an expected domain before inserting them into TwiML `<Stream>` or `<Redirect>` elements
- Do NOT rate-limit signed webhook routes — Twilio signs every request with HMAC-SHA1 over the body + URL and retries failed deliveries on a schedule. A rate limiter would block legitimate retries and silently drop SMS/voice callback events. The signature check IS the security boundary (issue #1378). See `.claude/stacks/payment/stripe.md` → "Do not rate-limit signed webhook endpoints" for the universal pattern.
- Never log raw request bodies — they may contain PII (phone numbers, caller names)

## CLI Provisioning
No CLI available — credentials must be obtained via the Twilio Console at https://console.twilio.com.

## PR Instructions
- Sign up at https://www.twilio.com and create a project
- Copy Account SID and Auth Token from the dashboard
- Purchase or configure a phone number
- Add env vars to `.env.local`
- Configure the webhook URL in Twilio Console → Phone Numbers → Active Numbers → select number → Messaging/Voice webhook
