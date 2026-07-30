---
assumes: [framework/nextjs]
packages:
  runtime: []
  dev: []
files: []
env:
  server: []
  client: []
ci_placeholders: {}
clean:
  files: []
  dirs: []
gitignore: []
---
# Notifications: Slack
> Used when experiment.yaml behaviors require Slack notifications via incoming webhooks
> Assumes: `framework/nextjs` for API route handlers

## Packages

No additional packages needed — uses the built-in `fetch` API for webhook delivery.

## Webhook URL Validation

Slack incoming webhook URLs must be validated before saving to the database or sending HTTP requests. Without validation, an attacker (or misconfigured user) can supply an arbitrary URL, causing the server to make outbound requests to any host — a Server-Side Request Forgery (SSRF) vulnerability.

### URL domain allowlist pattern
```ts
const ALLOWED_SLACK_DOMAINS = ["hooks.slack.com"];

function isValidSlackWebhookUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return (
      parsed.protocol === "https:" &&
      ALLOWED_SLACK_DOMAINS.includes(parsed.hostname)
    );
  } catch {
    return false;
  }
}
```

### Usage in API routes
```ts
import { NextResponse } from "next/server";
import { z } from "zod";

const settingsSchema = z.object({
  slack_webhook_url: z.string().url().max(500),
});

export async function POST(request: Request) {
  const body = await request.json();
  const parsed = settingsSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: "Invalid input" }, { status: 400 });
  }

  if (!isValidSlackWebhookUrl(parsed.data.slack_webhook_url)) {
    return NextResponse.json(
      { error: "Invalid Slack webhook URL — must be an https://hooks.slack.com URL" },
      { status: 400 }
    );
  }

  // Save to database or use the validated URL
}
```

### Sending notifications
```ts
async function sendSlackNotification(webhookUrl: string, message: string): Promise<boolean> {
  if (!isValidSlackWebhookUrl(webhookUrl)) {
    console.error("[SSRF] Attempted to send to non-Slack URL:", webhookUrl);
    return false;
  }

  const res = await fetch(webhookUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: message }),
  });
  return res.ok;
}
```

Notes:
- Always validate BOTH when saving the URL (write path) and when sending to it (read path) — defense in depth
- The domain allowlist approach is preferred over regex matching, which is easy to bypass
- Only `https:` protocol is accepted — never allow `http:` for webhook URLs
- Log SSRF attempts server-side for security monitoring

## Stack Knowledge

### Slack webhook URL format changes
Slack may change their webhook URL format in the future. If `hooks.slack.com` is deprecated, update the `ALLOWED_SLACK_DOMAINS` list. The current format is `https://hooks.slack.com/services/T.../B.../...`.
