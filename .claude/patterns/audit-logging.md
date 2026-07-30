# Audit Logging Pattern

> **Scope**: Production quality (always active).

## What to Log

### Authentication Events
- Login attempts (success and failure)
- Password resets
- Token refresh failures
- Account lockouts

### Data Mutations
- Create, update, delete operations on user-owned resources
- Bulk operations
- Admin actions

### Payment Events
- Checkout initiated, completed, failed
- Subscription changes
- Webhook processing results

### API Errors
- 4xx responses with context (not full request bodies)
- 5xx responses with stack traces
- Rate limit hits

## Log Format

Every audit log entry follows this structure:

```json
{
  "timestamp": "ISO 8601",
  "actor_id": "user ID or 'system' or 'anonymous'",
  "action": "auth.login | data.create | payment.checkout | api.error",
  "resource": "resource type and ID (e.g., 'user:123', 'order:456')",
  "result": "success | failure | error",
  "ip": "optional — include for auth events"
}
```

### Field Rules
- `actor_id`: Use authenticated user ID when available. Use `"anonymous"` for unauthenticated requests. Use `"system"` for automated processes (webhooks, cron).
- `action`: Use dot-separated namespace (`category.verb`).
- `resource`: Use `type:id` format. Omit sensitive data (no passwords, tokens, PII in log entries).
- `ip`: Include only for authentication events. Omit for internal operations.

## Where to Log

### Implementation

**Phase 1 — Structured console output:**
```typescript
function auditLog(entry: AuditEntry): void {
  console.log(JSON.stringify(entry))
}
```

This works with Vercel's log drain and most hosting platforms that capture stdout.

**Phase 2 — Dedicated logging service:**
When log volume or retention requirements exceed console output, add a structured logging service (e.g., Axiom, Datadog, Logtail). This is NOT required for initial production launch.

## What NOT to Log
- Request/response bodies (data leak risk)
- Passwords, tokens, or secrets
- PII beyond actor_id (no emails, names, addresses in logs)
- Successful read operations (too noisy, no security value)
