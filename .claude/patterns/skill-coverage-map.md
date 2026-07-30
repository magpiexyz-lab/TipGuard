# Skill Coverage Map

Static reference mapping defect categories to the upstream skill(s) responsible for
preventing them. Consumed by `/change` STATE 11a for Fix-type skill deficiency attribution.

## Defect Taxonomy Reference

### Behavior Verifier (B1-B6)

| Code | Name | Description |
|------|------|-------------|
| B1 | Dead Transition | Crash, 500 error, blank page, unhandled exception, network timeout >10s |
| B2 | Wrong Mutation | Wrong redirect, wrong data persisted, session not created, wrong HTTP status |
| B3 | Silent Failure | 200 + success UI but no record created, form resets without side effect |
| B4 | Validation Gap | Invalid input accepted or valid input rejected |
| B5 | State Leak | Previous form values bleed, auth session lost, URL params dropped, stale data |
| B6 | Contract Violation | API returns null where [] expected, missing fields, wrong HTTP status semantics |

### Security Defender (D1-D6)

| Code | Name | Description |
|------|------|-------------|
| D1 | Hardcoded Secrets | Secret-like patterns: `sk_live_`, `sk_test_`, API keys in string literals |
| D2 | Input Validation | API route missing zod schema when reading request body or params |
| D3 | Database RLS | CREATE TABLE without ENABLE ROW LEVEL SECURITY and policies |
| D4 | Client/Server Boundary | Server-only env vars imported in "use client" files |
| D5 | Rate Limiting | Auth/payment/webhook routes missing rate limiting |
| D6 | Dependency Vulns | npm audit returns high/critical vulnerabilities |

### Security Attacker (A1-A5)

| Code | Name | Description |
|------|------|-------------|
| A1 | Validation Bypass | Incomplete zod schemas, unvalidated query params, type coercion gaps |
| A2 | Access Control Gaps | Overly permissive RLS, missing ownership checks, service role in user routes |
| A3 | Injection & Encoding | SQL string concatenation, XSS via unsafe HTML, open redirect |
| A4 | Information Leakage | Stack traces in responses, over-fetched sensitive columns, debug console.log |
| A5 | Auth Weaknesses | Tokens in localStorage, missing httpOnly/secure flags, no session rotation |

### Spec Reviewer (S1-S8)

| Code | Name | Description |
|------|------|-------------|
| S1 | Feature Coverage | Behavior in experiment.yaml has no implementation |
| S2 | Page/Endpoint Existence | Archetype-required page/endpoint/command file missing |
| S3 | Analytics Wiring | EVENTS.yaml event has no tracking call, invalid event schema, or golden_path event not in EVENTS.yaml / funnel order violation |
| S4 | Golden Path Reachability | Step unreachable: page missing, CTA missing, or event not firing |
| S5 | System/Cron Behaviors | System/cron behavior not implemented or untested |
| S6 | Plan Completion | Plan item not addressed in source code |
| S7 | TDD Compliance | Critical path missing unit test |
| S8 | Process Compliance | Process checklist missing or TDD order violation (WARN only) |

## Coverage Matrix

Which skill(s) are responsible for preventing each defect category.
A dash (-) means the skill has no prevention responsibility for that defect.

| Defect | bootstrap (STATE 14-16) | verify (per scope) | deploy (STATE 4 health) |
|--------|--------------------------|--------------------|-----------------------|
| B1 | Generate working pages/endpoints | behavior-verifier | Health check (runtime) |
| B2 | Correct routing and data flow | behavior-verifier | Health check (runtime) |
| B3 | - | behavior-verifier | - |
| B4 | Scaffold zod schemas + unit tests for validation | behavior-verifier | - |
| B5 | - | behavior-verifier | - |
| B6 | Unit tests for API contracts | behavior-verifier | - |
| D1 | No secrets in generated code | security-defender | - |
| D2 | Scaffold zod for all API routes | security-defender | - |
| D3 | Generate RLS policies with schema | security-defender | - |
| D4 | Correct client/server imports | security-defender | - |
| D5 | Scaffold rate limiting middleware | security-defender | - |
| D6 | - | security-defender | - |
| A1 | Unit tests for validation edge cases | security-attacker | - |
| A2 | RLS + ownership checks + unit tests | security-attacker | - |
| A3 | Parameterized queries in templates | security-attacker | - |
| A4 | - | security-attacker | - |
| A5 | Secure auth scaffold + unit tests | security-attacker | - |
| S1 | Implement all behaviors | spec-reviewer | - |
| S2 | Create all pages/endpoints/commands | spec-reviewer | - |
| S3 | Wire all analytics events | spec-reviewer | - |
| S4 | Link all golden path steps | spec-reviewer | - |
| S5 | - | spec-reviewer | - |
| S6 | - | spec-reviewer | - |
| S7 | Unit tests for critical paths | spec-reviewer | - |
| S8 | - | spec-reviewer | - |

## Classification Priority

When a Fix involves multiple defect types, classify by the highest priority:

1. **D/A (security)** — D1-D6 and A1-A5 take precedence
2. **B (behavior)** — B1-B6 next
3. **S (spec)** — S1-S8 lowest priority

If no category matches, use **"unclassified"**.

## Attribution Confidence

| Level | Criteria |
|-------|----------|
| high | Defect category clearly identified AND responsible skill ran (per verify-history.jsonl) |
| medium | Defect category clearly identified BUT execution history unavailable |
| low | Defect is "unclassified" or maps to multiple skills with ambiguous responsibility |
