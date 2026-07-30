# CP1 Checkpoint Report: Foundation + Data Layer

**Date**: 2026-03-15
**Scope**: Sessions 1-4 output verification

---

## 1. Automated Checks

| Check | Result | Details |
|-------|--------|---------|
| `npm run build` | PASS | Zero errors, all pages/routes compile |
| `npx tsc --noEmit` | PASS | Zero type errors |
| `npm test` | PASS | 19 files, 212 tests, 0 failures |

---

## 2. Data Layer Verification

| Check | Result | Details |
|-------|--------|---------|
| 17 tables in migration | PASS | `002_session3_complete_schema.sql` contains exactly 17 CREATE TABLE statements |
| All tables have RLS | PASS | 17 `ENABLE ROW LEVEL SECURITY` statements (all tables) |
| All tables have policies | PASS | 16 tables have explicit user-isolation policies; `anonymous_specs` has RLS enabled with no anon policies by design (admin client access only) |
| `docs/CONVENTIONS.md` exists | PASS | Contains 12 sections (## 1 through ## 12) |
| `experiment/experiment.yaml` valid | PASS | YAML parses without error |
| `experiment/EVENTS.yaml` valid | PASS | YAML parses without error |

### Migration Files
- `001_initial.sql` — Bootstrap schema (10 tables, superseded by 002)
- `002_session3_complete_schema.sql` — Complete production schema (17 tables)

### Tables in 002 (authoritative)
1. `anonymous_specs` 2. `experiments` 3. `experiment_rounds` 4. `hypotheses`
5. `hypothesis_dependencies` 6. `research_results` 7. `variants`
8. `experiment_metric_snapshots` 9. `experiment_decisions` 10. `experiment_alerts`
11. `notifications` 12. `ai_usage` 13. `user_billing` 14. `skill_executions`
15. `operation_ledger` 16. `oauth_tokens` 17. `distribution_campaigns`

---

## 3. behavior.tests Coverage (b-16 to b-29)

### Summary: 30/30 test entries have assertions (100%)

Pre-existing coverage: 11/30 (37%)
Added in this checkpoint: 19 tests + 2 code implementations

| Behavior | Test Entry | Status | File |
|----------|-----------|--------|------|
| **b-16** | Endpoint returns SSE content-type | PRE-EXISTING | `src/app/api/spec/stream/route.test.ts` |
| **b-16** | Spec data streams progressively | ADDED | `src/app/api/spec/stream/route.test.ts` |
| **b-17** | Spec ownership transfers to authenticated user | PRE-EXISTING | `src/app/api/spec/claim/route.test.ts` |
| **b-17** | Unauthenticated requests are rejected | PRE-EXISTING | `src/app/api/spec/claim/route.test.ts` |
| **b-18** | Users can only access their own experiments | ADDED | `src/app/api/experiments/[id]/route.test.ts` |
| **b-18** | CRUD operations return correct status codes | PRE-EXISTING | `src/app/api/experiments/route.test.ts`, `[id]/route.test.ts` |
| **b-19** | Sub-resources are scoped to parent experiment | PRE-EXISTING | `variants/`, `hypotheses/`, `rounds/` route.test.ts |
| **b-19** | Missing experiments return 404 | PRE-EXISTING | Multiple sub-resource test files |
| **b-20** | Skill execution starts and returns a job ID | ADDED | `src/app/api/skills/route.test.ts` |
| **b-20** | Unauthorized skills are rejected | ADDED | `src/app/api/skills/route.test.ts` |
| **b-21** | Approval-gated skills pause and wait | ADDED | `src/app/api/skills/route.test.ts` |
| **b-21** | User can approve or reject pending skills | ADDED | `src/app/api/skills/route.test.ts` |
| **b-22** | Free-tier users are blocked from Pro-only operations | ADDED | `src/app/api/skills/route.test.ts` |
| **b-22** | Pro users can access all operations | ADDED | `src/app/api/skills/route.test.ts` |
| **b-23** | Subscribe creates a valid Stripe subscription checkout | ADDED | `src/app/api/billing/billing.test.ts` |
| **b-23** | Topup creates a valid PAYG top-up checkout ($10-$500) | ADDED | `src/app/api/billing/billing.test.ts` |
| **b-23** | Portal redirects to Stripe billing management | ADDED | `src/app/api/billing/billing.test.ts` |
| **b-24** | Campaign CRUD operations work correctly | ADDED | `src/app/api/experiments/[id]/distribution/route.test.ts` |
| **b-24** | Sync status is tracked per channel | ADDED | `src/app/api/experiments/[id]/distribution/route.test.ts` |
| **b-25** | Webhook signature is verified | PRE-EXISTING | `tests/flows.test.ts` |
| **b-25** | Subscription state reflects webhook events | ADDED | `tests/flows.test.ts` |
| **b-26** | Metrics table is updated with fresh data | PRE-EXISTING | `tests/flows.test.ts` |
| **b-26** | Stale data is detected and flagged | ADDED | `tests/flows.test.ts` |
| **b-27** | Budget exhaustion triggers alert | ADDED | `tests/flows.test.ts` |
| **b-27** | Dropping dimension triggers alert | ADDED | `tests/flows.test.ts` |
| **b-28** | Specs older than 24h without an owner are removed | ADDED | `tests/flows.test.ts` |
| **b-28** | Claimed specs are not affected | ADDED | `tests/flows.test.ts` |
| **b-29** | Milestone notifications are sent | ADDED | `tests/flows.test.ts` |
| **b-29** | Verdict notifications are sent | ADDED | `tests/flows.test.ts` |

---

## 4. Issues Found and Fixed

### Fix 1: Billing enforcement missing (b-22)
**Problem**: Skills route (`/api/skills`) accepted deploy/distribute requests without checking user billing status.
**Fix**: Added billing check in `src/app/api/skills/route.ts` — queries `user_billing` table for plan/balance before allowing Pro-only skills (deploy, distribute). Returns 403 for free-tier users with zero PAYG balance.

### Fix 2: Dimension dropping detection missing (b-27)
**Problem**: Alert detection cron only checked budget exhaustion and stale metrics, not dropping dimensions.
**Fix**: Added dimension dropping detection in `src/app/api/cron/alert-detection/route.ts` — compares latest two `experiment_metric_snapshots` entries. Creates `dimension_dropping` alert when any funnel dimension ratio drops by >30%.

### Note: Zod v4 UUID validation
Test UUIDs must use valid v4 format (3rd group starts with 4, 4th group starts with 8/9/a/b). Generic placeholder UUIDs like `11111111-1111-1111-1111-111111111111` fail Zod v4 strict validation.

---

## 5. Final Verification

```
npm run build     → PASS (zero errors)
npx tsc --noEmit  → PASS (zero errors)
npm test          → PASS (19 files, 212 tests, 0 failures)
```

**Verdict**: All CP1 checks pass. Ready for Phase 3.
