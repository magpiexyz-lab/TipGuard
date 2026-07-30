# World-Champion Quality Elevation Plan

> Generated 2026-03-08 by 5-agent first-principles review.
> Each task is self-contained — open a separate Claude Code session per task.
> Tasks within the same PR are sequential; different PRs can run in parallel sessions.

---

## Overview

| PR | Theme | Tasks | Est. Complexity | Dependencies |
|----|-------|-------|-----------------|--------------|
| PR-A | Rollback & Incident Response | A1–A3 | Medium | None |
| PR-B | Error Recovery State Machine | B1–B3 | Medium | None |
| PR-C | Operational Monitoring | C1–C3 | Light | None |
| PR-D | Skill Handoff & Coherence | D1–D4 | Medium | None |
| PR-E | Security Hardening | E1–E4 | Medium | None |
| PR-F | Performance & A11y Agents | F1–F3 | Medium | None |
| PR-G | /change Decomposition | G1–G3 | Heavy | None |

All PRs can be developed in parallel on separate branches.

---

## PR-A: Rollback & Incident Response

**Branch:** `feat/rollback-incident-response`

**Why:** Currently the template has /teardown (nuclear option) but no way to revert a bad deploy or respond to production incidents. This is the #1 gap blocking world-champion status.

### Task A1: Create `patterns/incident-response.md`

**File to create:** `.claude/patterns/incident-response.md`

**Context:** No incident response pattern exists. When a deployed app has a critical bug (broken payments, auth failure, data corruption), users have zero documented recovery path. The only option is /teardown which destroys everything.

**Content requirements:**

```markdown
# Incident Response Procedure

## Severity Classification
- **P0 Critical**: Payment failures, data corruption, auth bypass — user data at risk
- **P1 High**: Core feature broken, but data is safe
- **P2 Medium**: Non-core feature broken, degraded experience

## Immediate Actions (First 5 minutes)

### For Vercel-hosted apps:
1. **Instant rollback**: Vercel Dashboard → Deployments → find last working deployment → click "..." → "Promote to Production"
   - This is instant (no rebuild, no redeploy)
   - Alternative CLI: `vercel rollback` (rolls back to previous production deployment)
2. **If rollback doesn't fix it** (e.g., database migration already applied):
   - Check Supabase Dashboard → SQL Editor → verify data state
   - If data is corrupted: Supabase Dashboard → Backups → restore from latest backup (7-day retention on free tier)

### For Railway-hosted apps:
1. **Instant rollback**: Railway Dashboard → Deployments → click previous deployment → "Redeploy"
2. **If SQLite data is corrupted**: Restore from backup (if backup cron exists) or accept data loss

### Universal steps:
3. **Rotate compromised secrets**: If the incident involves exposed credentials:
   - Generate new keys in the provider dashboard (Stripe, Supabase, etc.)
   - Update env vars: use hosting stack file's `## Deploy Interface > Environment Variables` method
   - Redeploy after env var update

## Root Cause Analysis (After stabilization)
1. What code change caused the bug?
2. Why didn't /verify catch it? (Missing test? Missing security check?)
3. File a `/change fix <root cause>` to prevent recurrence
4. If the root cause is in a template file: follow `.claude/patterns/observe.md`

## Secret Rotation Schedule
- API keys and webhook secrets: every 90 days
- Database passwords: every 90 days
- Auth tokens: auto-managed by Supabase (1h access / 7d refresh)
```

**Acceptance criteria:**
- File exists at `.claude/patterns/incident-response.md`
- Covers P0/P1/P2 severity classification
- Has Vercel-specific and Railway-specific rollback instructions
- Includes secret rotation schedule
- References observe.md for template-level issues

### Task A2: Create `/rollback` skill

**File to create:** `.claude/commands/rollback.md`

**Context:** This is a new skill that fills the gap between "everything is fine" and /teardown (destroy everything). It reads the deploy manifest and the hosting stack file to execute a provider-specific rollback.

**Key design decisions:**
- Read-only for database (no automatic DB rollback — too dangerous)
- Hosting rollback only (revert to previous deployment)
- Reads `.runs/deploy-manifest.json` for hosting provider
- Reads hosting stack file's `## Deploy Interface` for rollback command
- No branch/PR needed — this is an emergency operation

**Content requirements:**

```yaml
---
description: "Roll back to the previous production deployment. Emergency use — no branch or PR."
type: analysis-only
reads:
  - .runs/deploy-manifest.json
  - experiment/experiment.yaml
stack_categories: [hosting]
requires_approval: true
references:
  - .claude/patterns/incident-response.md
branch_prefix: ""
modifies_specs: false
---
```

**Skill steps:**
1. Read deploy-manifest.json → extract hosting provider
2. Read hosting stack file → check for rollback instructions
3. Present rollback plan (which deployment to revert to) → STOP for approval
4. Execute rollback command (provider-specific)
5. Health check post-rollback
6. Report result + next steps (file /change fix, check database state)

**Files to modify:**
- Add Rollback section to `.claude/stacks/hosting/vercel.md` Deploy Interface:
  ```
  ### Rollback
  - **Command:** `vercel rollback`
  - **Dashboard:** Vercel → Deployments → "..." → "Promote to Production"
  - **Note:** Instant — no rebuild required. Does NOT rollback database migrations.
  ```
- Add Rollback section to `.claude/stacks/hosting/railway.md` Deploy Interface:
  ```
  ### Rollback
  - **Command:** `railway service rollback` (or redeploy previous deployment via dashboard)
  - **Dashboard:** Railway → Deployments → select previous → "Redeploy"
  - **Note:** Does NOT rollback database or volume changes.
  ```

**Acceptance criteria:**
- Skill file exists at `.claude/commands/rollback.md`
- Both hosting stack files have Rollback sections
- Skill reads deploy manifest and hosting stack file dynamically
- Has approval gate before executing
- Health check after rollback
- Clear warning that DB is NOT rolled back

### Task A3: Wire incident response into existing skills

**Files to modify:**
1. **`CLAUDE.md`** — Add to Rule 6 (Security Baseline):
   ```
   - Follow `.claude/patterns/incident-response.md` for production incidents and secret rotation
   ```

2. **`.claude/commands/deploy.md`** — Add to Step 6 Summary, after "Next steps":
   ```
   **If something goes wrong after deploy:**
   - Run `/rollback` to revert to the previous deployment (hosting only — does not affect database)
   - For data issues: see `.claude/patterns/incident-response.md`
   ```

3. **`.claude/commands/iterate.md`** — Add to Step 5 recommendations table:
   ```
   | Production incident | `/rollback` to revert deploy, then `/change fix <root cause>` |
   ```

**Acceptance criteria:**
- CLAUDE.md Rule 6 references incident-response.md
- deploy.md Step 6 mentions /rollback
- iterate.md recommendations include /rollback for incidents
- Build passes (`npm run build`)

---

## PR-B: Error Recovery State Machine

**Branch:** `feat/error-recovery`

**Why:** When a skill fails mid-execution (e.g., /deploy provisions database but hosting fails), users are left with partial state and no recovery path. Skills need idempotency documentation and recovery guidance.

### Task B1: Create `patterns/recovery.md`

**File to create:** `.claude/patterns/recovery.md`

**Context:** Currently when skills fail mid-execution, users must manually clean up partial state. This pattern provides a systematic recovery framework.

**Content requirements:**

```markdown
# Error Recovery Pattern

## Principles
1. **Idempotency first**: Skills should be safe to re-run after failure
2. **State checkpoints**: Skills save progress so re-runs skip completed steps
3. **Partial cleanup guidance**: When re-run isn't possible, document manual cleanup

## Per-Skill Recovery Matrix

### /bootstrap failure
- **State saved:** `.claude/current-plan.md` (plan), `package.json` (installed packages)
- **Recovery:** Re-run `/bootstrap` — Step 4 precondition detects partial bootstrap and continues
- **Manual cleanup:** If you want to start fresh: `git checkout main && make clean`

### /deploy failure (most common)
- **State saved:** `.runs/deploy-manifest.json` (resources created so far)
- **Partial state scenarios:**
  | Failed at | Resources exist | Recovery |
  |-----------|----------------|----------|
  | Step 3 (database) | Database project | Re-run `/deploy` — Step 3 checks for existing project |
  | Step 4 (hosting) | Database + hosting project | Re-run `/deploy` — Step 4 is idempotent (vercel link reuses existing) |
  | Step 4.4 (env vars) | DB + hosting (no env vars) | Re-run `/deploy` — env vars use upsert semantics |
  | Step 5a (deploy cmd) | DB + hosting + env vars | Re-run `/deploy` — redeploy is safe |
  | Step 5b (agents) | DB + hosting + deployed | Re-run `/deploy` — agents check for existing resources |
- **Nuclear option:** Run `/teardown` (reads manifest, deletes everything in reverse)

### /change failure
- **State saved:** `.claude/current-plan.md` on feature branch
- **Recovery:** Re-run `/change` on the same branch — Step 4 detects existing plan and resumes Phase 2
- **Manual cleanup:** `git checkout main && git branch -d <branch-name>`

### /verify failure
- **State saved:** Fix attempts on current branch
- **Recovery:** Re-run `/verify` — starts fresh test run
- **Manual cleanup:** None needed — verify doesn't modify infrastructure

### /distribute failure
- **State saved:** `experiment/ads.yaml` (campaign config)
- **Recovery:** Re-run `/distribute` — reads existing ads.yaml
- **Manual cleanup:** Delete `experiment/ads.yaml` to regenerate

### /harden failure
- **State saved:** `experiment/on-touch.yaml`, specification tests on feature branch
- **Recovery:** Re-run `/harden` on the same branch — completed modules already have tests
- **Manual cleanup:** `git checkout main && git branch -d <branch-name>`

## Generic Recovery Steps
1. Check which branch you're on: `git branch --show-current`
2. Check what files changed: `git status`
3. If on a feature branch with uncommitted changes:
   - Save progress: `git add -A && git commit -m "WIP: recovery point"`
   - Start fresh: `git checkout main`
4. Re-run the skill — most skills detect existing state and resume
```

**Acceptance criteria:**
- File exists at `.claude/patterns/recovery.md`
- Covers all 6 code-writing/infrastructure skills
- Each skill has a recovery matrix with specific scenarios
- References deploy-manifest.json and current-plan.md appropriately

### Task B2: Add idempotency guarantees to deploy.md

**File to modify:** `.claude/commands/deploy.md`

**Context:** deploy.md already has an Idempotency section (lines 457-469) but it's at the bottom and not referenced during execution. Need to:

1. Add to **Step 0** (after line 26, build check):
   ```
   11. **Recovery check:** If `.runs/deploy-manifest.json` exists, read it and report:
       "Previous deploy detected (deployed_at: <timestamp>). Resources may already exist.
       `/deploy` is idempotent — re-running will reuse existing resources and update configuration.
       Reply **continue** to proceed, or run `/teardown` first to start fresh."
       Wait for user confirmation.
   ```

2. Add to **Step 5b preamble** (after line 173), a timeout policy:
   ```
   **Timeout policy:** Each agent has a 5-minute timeout. If an agent doesn't complete within 5 minutes:
   - Log: "Agent [name] timed out after 5 minutes"
   - Record: `{status: "timeout", message: "Agent timed out"}`
   - Continue with other agents — do not block

   **Partial failure policy:** After all agents complete (or timeout):
   - If ALL succeeded: proceed normally
   - If ANY failed/timed out: list failures in Step 6 summary with manual setup instructions
   - Do NOT retry automatically — the user can re-run `/deploy` to retry failed agents
   ```

3. Add to **Step 6** (Summary section, after line 397), distinguish failed vs skipped:
   ```
   [If any agent returned status: "failed"] **Failed (needs manual setup):**
   - [service]: ❌ failed — [error message]. Set up manually: [instructions from stack file]

   [If any agent returned status: "timeout"] **Timed out (retry by re-running /deploy):**
   - [service]: ⏱️ timed out — re-run `/deploy` to retry, or set up manually
   ```

**Acceptance criteria:**
- Step 0 has recovery check reading deploy-manifest.json
- Step 5b has explicit timeout (5 min) and partial failure policies
- Step 6 distinguishes ✅ success / ⏭️ skipped / ❌ failed / ⏱️ timed out
- Existing Idempotency section is preserved

### Task B3: Add recovery references to all skills

**Files to modify:**
1. **`.claude/commands/bootstrap.md`** — Add after Step 0 branch setup:
   ```
   > **If resuming from a failed bootstrap:** see `.claude/patterns/recovery.md` for recovery options.
   ```

2. **`.claude/commands/change.md`** — Add to Step 4 (preconditions), after line 55:
   ```
   > **If resuming from a failed /change:** see `.claude/patterns/recovery.md`. The plan in `.claude/current-plan.md` persists across sessions.
   ```

3. **`.claude/commands/harden.md`** — Add to Step 0 (preconditions):
   ```
   - If on a `chore/harden-*` branch with existing specification tests: a previous `/harden` may have partially completed. Tell the user: "Found existing hardening work on this branch. Scanning for modules that still need tests..." Then scan for CRITICAL modules without test files and proceed from Step 3.4.
   ```

4. **`.claude/commands/distribute.md`** — Add a recovery note at the top after the description:
   ```
   > If `experiment/ads.yaml` already exists from a previous run, this skill reads it and presents it for approval. Delete `experiment/ads.yaml` to regenerate from scratch.
   ```

**Acceptance criteria:**
- All 4 skills reference recovery.md or have inline recovery guidance
- No existing behavior is changed
- Build passes

---

## PR-C: Operational Monitoring & Cost Guidance

**Branch:** `feat/operational-monitoring`

**Why:** After /deploy, users have zero guidance on monitoring health, staying within free tier quotas, or estimating costs. This is a documentation and deploy.md enhancement — no new skills needed.

### Task C1: Add monitoring guidance to deploy.md Step 6

**File to modify:** `.claude/commands/deploy.md`

**Context:** deploy.md Step 6 (Summary, lines 368-423) currently lists URLs and next steps but doesn't mention monitoring. Add a new section after the "Next steps" block.

**Add to Step 6 Summary (after line 423):**

```markdown
**Monitoring setup (recommended):**
1. **Health check alert**: Set up uptime monitoring for `https://<canonical_url>/api/health`
   [If hosting is vercel] - Vercel: Dashboard → Monitoring → Create monitor (built-in, free)
   [If hosting is railway] - Use a free service like UptimeRobot (uptimerobot.com) — add HTTP monitor for /api/health
2. **Analytics digest**: PostHog → Dashboards → "<idea.name> Experiment" → Subscribe (bell icon) → every 3 days → add email
3. **Free tier quotas to watch:**
   [If analytics is posthog] - PostHog: 1M events/month (check: PostHog → Settings → Billing)
   [If database is supabase] - Supabase: 500MB storage, 2GB bandwidth/month (check: Supabase Dashboard → Usage)
   [If hosting is vercel] - Vercel: 100GB bandwidth/month (check: Vercel → Usage)
   [If hosting is railway] - Railway: $5 credit/month on free tier (check: Railway → Usage)
   At 100 active users × 10 actions/day, typical monthly usage:
   - Analytics: ~30K events (well within 1M)
   - Database: ~10MB storage (well within 500MB)
   - Hosting: ~5GB bandwidth (well within limits)
```

**Acceptance criteria:**
- deploy.md Step 6 has Monitoring setup section
- Provider-specific guidance based on stack values
- Free tier quota estimates included
- Build passes

### Task C2: Add `npm audit` enforcement to bootstrap and deploy

**Files to modify:**

1. **`.claude/commands/bootstrap.md`** — In Phase 2, after the Setup Phase scaffold-setup agent returns (line 243), add:
   ```
   After setup completes, run `npm audit --audit-level=high`. If any high or critical
   vulnerabilities are found:
   - Run `npm audit fix` to auto-fix what's possible
   - If unfixable vulnerabilities remain, warn the user: "Dependencies have known high/critical
     vulnerabilities: [list]. These may be false positives for dev-only packages. Review and
     proceed, or pin specific versions in package.json to resolve."
   - Do NOT block bootstrap for audit findings — warn and continue
   ```

2. **`.claude/commands/deploy.md`** — In Step 0 (after line 26, build check), add:
   ```
   3b. Run `npm audit --audit-level=high`. If critical vulnerabilities are found, warn:
       "npm audit found critical vulnerabilities. Run `npm audit fix` before deploying.
       Reply **continue** to deploy anyway, or fix first."
       Wait for user confirmation before proceeding.
   ```

3. **`CLAUDE.md`** — Add to Rule 6 (Security Baseline), after the rate limiting line:
   ```
   - Run `npm audit` before deploying. Fix critical/high vulnerabilities before production use.
   ```

**Acceptance criteria:**
- bootstrap.md runs npm audit after package installation
- deploy.md runs npm audit as a pre-deploy check (with user override)
- CLAUDE.md Rule 6 mentions npm audit
- Neither blocks on audit findings — warns and lets user decide

### Task C3: Add CSP headers and CORS guidance to stack files

**Files to modify:**

1. **`.claude/stacks/hosting/vercel.md`** — Add new section after "Rate Limiting Limitation" (line 132):
   ```markdown
   ## Security Headers

   Bootstrap should create `vercel.json` with security headers:
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

   > Note: CSP (Content-Security-Policy) is intentionally omitted for MVPs — it requires
   > per-project tuning (inline scripts, analytics domains, payment iframes) and breaks
   > builds when misconfigured. Add CSP via `/change add CSP headers` when graduating
   > to production.
   ```

2. **`.claude/stacks/framework/nextjs.md`** — Add to "API Route Conventions" section (after line 81):
   ```markdown
   ## CORS Policy
   - API routes serve same-origin by default (Next.js behavior) — no CORS headers needed
   - If the API needs cross-origin access (e.g., separate frontend):
     ```ts
     // Add to route handler
     const corsHeaders = {
       "Access-Control-Allow-Origin": process.env.ALLOWED_ORIGIN || "",
       "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE",
       "Access-Control-Allow-Headers": "Content-Type, Authorization",
     };
     ```
   - Never use `Access-Control-Allow-Origin: "*"` for authenticated endpoints
   ```

**Acceptance criteria:**
- vercel.md has Security Headers section with vercel.json template
- nextjs.md has CORS Policy section
- No CSP for MVPs (documented reason)
- Build passes

---

## PR-D: Skill Handoff & Coherence

**Branch:** `feat/skill-coherence`

**Why:** Skills operate in isolation — /iterate analysis doesn't flow to /change, preconditions are checked at inconsistent points, retry budgets vary without reason.

### Task D1: Bridge /iterate to /change via manifest

**Files to modify:**

1. **`.claude/commands/iterate.md`** — At the end of Step 5 (after recommendations), add:
   ```markdown
   ### Save analysis for /change context

   Write `.runs/iterate-manifest.json`:
   ```json
   {
     "verdict": "<GO|NO-GO|PIVOT|MONITOR|TOO_EARLY>",
     "bottleneck": {
       "stage": "<funnel stage name>",
       "conversion": "<percentage>",
       "diagnosis": "<one-line diagnosis>"
     },
     "recommendations": [
       {
         "action": "<what to do>",
         "skill": "</change ...>",
         "expected_impact": "<which metric improves>"
       }
     ],
     "variant_winner": "<slug or null>",
     "analyzed_at": "<ISO 8601>"
   }
   ```

   This file is read by `/change` to provide context for the next iteration.
   ```

2. **`.claude/commands/change.md`** — In Step 2 (Read context, after line 36), add:
   ```markdown
   - If `.runs/iterate-manifest.json` exists, read it for context:
     - Include the verdict, bottleneck, and recommendations in the plan (Phase 1)
     - Reference: "This change addresses the [bottleneck.stage] bottleneck identified by /iterate ([bottleneck.diagnosis])"
     - This provides continuity between analysis and implementation
   ```

**Acceptance criteria:**
- iterate.md writes iterate-manifest.json at the end of Step 5
- change.md reads iterate-manifest.json in Step 2 if it exists
- The manifest schema is minimal (verdict + bottleneck + recommendations)
- Build passes

### Task D2: Normalize retry budgets and precondition order

**Files to modify:**

1. **`.claude/commands/change.md`** — Move precondition checks BEFORE branch creation:
   - Current order: Step 0 (branch) → Step 1 (validate input) → Step 2 (read context) → Step 3 (classify) → Step 4 (preconditions)
   - New order: Step 0 (validate input + critical preconditions) → Step 1 (branch) → Step 2 (read context) → Step 3 (classify) → Step 4 (remaining preconditions)

   Specifically, move these checks from Step 4 to a new Step 0 (before branch.md):
   ```
   ## Step 0: Pre-flight checks (before branch creation)

   - If `$ARGUMENTS` is empty or unclear: stop and ask the user to describe what they want to change
   - If `$ARGUMENTS` contains `#<number>`: read the GitHub issue via `gh issue view <number>`
   - Verify `package.json` exists. If not → stop
   - Verify `experiment/EVENTS.yaml` exists. If not → stop
   - Run `npm run build` to confirm the project compiles (unless Fix type)
   ```

   Then renumber: current Step 0 becomes Step 1 (branch), current Step 2 becomes Step 2, etc.

   **Important:** Keep the remaining type-specific preconditions (payment/email dependency checks, quality:production check) in their current location (now Step 5, was Step 4), because they depend on classification (Step 4, was Step 3).

2. **`.claude/commands/deploy.md`** — In Step 5d (Auto-fix, line 329), change "max 1 round" to "max 2 rounds" for consistency:
   ```
   ### 5d: Auto-fix (max 2 rounds)
   ```
   Rationale: All other skills use 2-3 retry budget. Deploy using 1 is inconsistent.

3. **`.claude/patterns/verify.md`** — Add a note at line 7 explaining the budget:
   ```
   > Budget rationale: 3 attempts allows iterative refinement with error feedback.
   > Attempt 1 catches the obvious error. Attempt 2 catches cascading effects.
   > Attempt 3 is the safety net. All skills use this budget for consistency.
   ```

**Acceptance criteria:**
- change.md validates input and critical preconditions BEFORE branch creation
- deploy.md auto-fix uses 2 rounds (was 1)
- verify.md documents retry budget rationale
- Step numbering is consistent after reorder
- Build passes

### Task D3: Add archetype-feature matrix to CLAUDE.md

**File to modify:** `CLAUDE.md`

**Context:** Skills have inconsistent archetype conditionalization. Adding a matrix makes it clear which features apply to which archetype.

**Add after Rule 3 (Use Stack from experiment.yaml), as a sub-section:**

```markdown
### Archetype-Feature Matrix

| Feature | web-app | service | cli |
|---------|---------|---------|-----|
| Pages (src/app/<page>/page.tsx) | ✅ | ❌ | ❌ |
| API routes (src/app/api/) | ✅ | ✅ | ❌ |
| Commands (src/commands/) | ❌ | ❌ | ✅ |
| Landing page | ✅ | surface | surface |
| Variants (A/B messaging) | ✅ | ❌ | ❌ |
| Fake Door components | ✅ | stub routes | stub commands |
| Browser tests (Playwright) | ✅ | ❌ | ❌ |
| API/unit tests (Vitest) | optional | ✅ | ✅ |
| /distribute (ad campaigns) | ✅ | ✅ (if surface) | ✅ (if surface) |
| /deploy | ✅ | ✅ | surface only |
| Analytics (client-side) | ✅ | ❌ | ❌ |
| Analytics (server-side) | ✅ | ✅ | ✅ |
```

**Acceptance criteria:**
- Matrix is added to CLAUDE.md after Rule 3
- All 3 archetypes are covered
- Build passes

### Task D4: Unify "read context" across skills

**File to create:** `.claude/patterns/read-context.md`

**Context:** Each skill reads a different subset of context files at startup. This creates inconsistency. Create a shared pattern that skills reference.

**Content:**

```markdown
# Read Context Pattern

Every skill reads this baseline context before executing its specific logic.

## Required Context (always read)
1. `experiment/experiment.yaml` — single source of truth (scope, features, stack, metrics)
2. `experiment/EVENTS.yaml` — canonical analytics event list
3. Archetype file at `.claude/archetypes/<type>.md` (type from experiment.yaml, default `web-app`)

## Stack Context (read when `stack_categories` in skill frontmatter includes the category)
For each category in experiment.yaml `stack`:
- Read `.claude/stacks/<category>/<value>.md`

## Optional Context (read if file exists)
- `.claude/current-plan.md` — persisted plan from previous session
- `.runs/iterate-manifest.json` — analysis from last /iterate run
- `.runs/deploy-manifest.json` — resources from last /deploy run
- `experiment/on-touch.yaml` — modules deferred for hardening

## How to Reference
Skills should say: "Read context per `.claude/patterns/read-context.md`" instead of
listing individual files. Type-specific context (e.g., deploy reads .env.example,
change reads src/app/) is documented in the skill itself.
```

**Files to modify:** Do NOT modify existing skills in this task. The pattern is created as a reference — skills can be updated to reference it incrementally.

**Acceptance criteria:**
- File exists at `.claude/patterns/read-context.md`
- Lists all context files with when to read them
- Explains the reference pattern
- Build passes

---

## PR-E: Security Hardening

**Branch:** `feat/security-hardening`

**Why:** Security review scored 9.2/10. These targeted improvements close the remaining gaps: CSP prep, audit logging pattern, CSRF documentation, and secret rotation.

### Task E1: Add audit logging pattern

**File to create:** `.claude/patterns/audit-logging.md`

**Context:** No audit logging guidance exists. When `quality: production` is set, security events should be logged for forensic analysis.

**Content requirements:**
- Define what to log: auth attempts (success/failure), data mutations (create/update/delete), payment events, API errors (4xx/5xx)
- Define log format: `{ timestamp, actor_id, action, resource, result, ip? }`
- Define where to log: console.log for MVP (Vercel captures stdout), structured logging library for production
- NOT a mandatory pattern for MVP — only triggered when `quality: production`
- Reference from security-review.md as an optional check

**Acceptance criteria:**
- File exists at `.claude/patterns/audit-logging.md`
- Scoped to `quality: production` only
- Practical (console.log is sufficient for most MVPs)
- Build passes

### Task E2: Strengthen security-defender D5 with Vercel guidance

**File to modify:** `.claude/agents/security-defender.md`

**Context:** D5 (Rate Limiting) currently says "See hosting stack file" but Vercel's serverless can't do in-memory rate limiting. The defender should know this and suggest alternatives.

**Add to D5 section:**
```markdown
**Vercel-specific:** In-memory rate limiting does not work on serverless (counters reset per invocation).
Acceptable alternatives:
- `// TODO: Add production rate limiting (e.g., Upstash Redis)` comment at top of route (MVP)
- Upstash `@upstash/ratelimit` package (production)
- Vercel Edge Config rate limiting

A TODO comment counts as "present" for MVP mode. For `quality: production`, a real
implementation is required — TODO comments are a FAIL.
```

**Acceptance criteria:**
- D5 has Vercel-specific guidance
- TODO comment is acceptable for MVP, not for production
- Build passes

### Task E3: Document CSRF and session handling

**File to modify:** `.claude/agents/security-attacker.md`

**Context:** Neither CLAUDE.md nor security agents mention CSRF. It's auto-handled by Next.js but should be documented to prevent confusion.

**Add to A5 (Authentication Weaknesses):**
```markdown
**CSRF:** Next.js API routes using `request.json()` are inherently CSRF-resistant
(browsers don't send JSON Content-Type in cross-origin form submissions). For
non-JSON endpoints (form-encoded), verify SameSite cookie attribute is set.
Framework-handled: do NOT flag as a vulnerability unless the app uses custom
form-action endpoints that bypass Next.js routing.
```

**Acceptance criteria:**
- security-attacker.md A5 documents CSRF handling
- Explains why it's not a vulnerability in Next.js context
- Build passes

### Task E4: Add secret expiry documentation to auth stack

**File to modify:** `.claude/stacks/auth/supabase.md`

**Context:** Session token expiry is not documented. Developers might assume tokens are permanent.

**Add a new section "Session Token Lifecycle":**
```markdown
## Session Token Lifecycle
- **Access token:** expires after 1 hour (configurable in Supabase Dashboard → Auth → Settings)
- **Refresh token:** expires after 7 days (configurable)
- **Auto-refresh:** The `supabase-server.ts` client auto-refreshes tokens via cookies
- **Edge case:** If a user is inactive for >7 days, they must re-authenticate
- **Monitor:** Watch for `AuthApiError: Invalid Refresh Token` in server logs — indicates expired sessions
```

**Acceptance criteria:**
- supabase.md (auth stack) has Session Token Lifecycle section
- Documents access/refresh token expiry
- Mentions auto-refresh behavior
- Build passes

---

## PR-F: Performance & Accessibility Agents

**Branch:** `feat/perf-a11y-agents`

**Why:** Pattern & Agent review scored missing performance and accessibility reviews at 6-7/10. These are the most impactful agent additions.

### Task F1: Create performance-reporter agent

**File to create:** `.claude/agents/performance-reporter.md`

**Context:** No agent checks Core Web Vitals, bundle size, or Lighthouse scores. This agent runs during /verify parallel review.

**Content requirements:**

```yaml
# Agent description for SETTINGS.json / subagent_type registry
name: performance-reporter
description: "Measures Core Web Vitals and bundle size. Reports metrics without fixing code."
model: claude-sonnet-4-6
maxTurns: 15
tools: [Bash, Read, Glob, Grep]
```

**Agent procedure:**
1. Read experiment.yaml to determine archetype
2. If web-app:
   - Run `npm run build` and capture output (Next.js reports bundle sizes)
   - Parse route sizes from build output
   - Flag any page bundle > 200KB (first-load JS)
   - If Playwright is installed: run a Lighthouse audit via `npx playwright test` with performance config
3. If service/cli: skip (no browser metrics applicable)
4. Report:
   ```
   | Page | First Load JS | Status |
   |------|---------------|--------|
   | / | 150KB | ✅ (<200KB) |
   | /dashboard | 250KB | ⚠️ (>200KB — consider code splitting) |

   Bundle size total: 400KB
   Largest dependency: [name] (estimated from node_modules)
   ```

**Wire into verify.md:** Add as optional 6th agent (or 7th if spec-reviewer is also present):
```markdown
### performance-reporter (if archetype is `web-app`)

Spawn the `performance-reporter` agent (`subagent_type: performance-reporter`). No additional context needed.
```

**Acceptance criteria:**
- Agent file exists at `.claude/agents/performance-reporter.md`
- verify.md spawns it for web-app archetype
- Reports bundle sizes from Next.js build output
- Does NOT fix code — report only
- Build passes

### Task F2: Create accessibility-scanner agent

**File to create:** `.claude/agents/accessibility-scanner.md`

**Context:** No WCAG compliance checking exists. This agent scans generated HTML for common accessibility violations.

**Content requirements:**

```yaml
name: accessibility-scanner
description: "Scans pages for WCAG accessibility violations. Reports issues without fixing code."
model: claude-sonnet-4-6
maxTurns: 15
tools: [Bash, Read, Glob, Grep]
```

**Agent procedure:**
1. Read experiment.yaml to determine archetype and pages
2. If web-app:
   - Scan all page.tsx files for common violations:
     - Images without alt text (`<img` without `alt=`)
     - Buttons without accessible labels (`<button` without text content or `aria-label`)
     - Form inputs without labels (`<input` without associated `<label` or `aria-label`)
     - Color contrast (check CSS for light text on light backgrounds — heuristic only)
     - Missing heading hierarchy (h1 → h3 without h2)
     - Missing lang attribute on `<html>` tag in layout.tsx
   - Check for touch target sizes in CSS (min 44px for interactive elements)
3. If service/cli: skip (no HTML output)
4. Report:
   ```
   | Issue | File | Line | WCAG | Severity |
   |-------|------|------|------|----------|
   | Image missing alt text | src/app/page.tsx | 45 | 1.1.1 | High |
   | Button without label | src/components/cta.tsx | 12 | 4.1.2 | High |

   Total: N issues (M high, K medium)
   ```

**Wire into verify.md:** Add as optional agent for web-app:
```markdown
### accessibility-scanner (if archetype is `web-app`)

Spawn the `accessibility-scanner` agent (`subagent_type: accessibility-scanner`). No additional context needed.
```

**Acceptance criteria:**
- Agent file exists at `.claude/agents/accessibility-scanner.md`
- verify.md spawns it for web-app archetype
- Checks for top 6 WCAG violations (images, buttons, inputs, contrast, headings, lang)
- Does NOT fix code — report only
- Build passes

### Task F3: Register new agents in subagent descriptions

**File to modify:** Check if there's a central agent registry. If agents are registered via `settings.json` or agent descriptions in the Claude Code config, update accordingly.

**Context:** The new agents need to be available as `subagent_type` values. Check how existing agents (design-critic, security-defender, etc.) are registered and follow the same pattern.

**Steps:**
1. Grep for where `subagent_type: design-critic` or similar is defined
2. Add `performance-reporter` and `accessibility-scanner` to the same registry
3. Update `.claude/settings.json` if that's where agent types are registered

**Acceptance criteria:**
- Both new agents are registered in the same way as existing agents
- Can be spawned via `subagent_type: performance-reporter` and `subagent_type: accessibility-scanner`
- Build passes

---

## PR-G: /change Decomposition

**Branch:** `feat/change-decomposition`

**Why:** change.md is 357 lines with 6 change types, each having MVP and production paths. It's the most complex skill and the hardest to maintain. Decomposing it improves clarity and reduces cognitive load.

### Task G1: Extract type-specific constraints to procedure files

**Context:** change.md Step 6 has 6 type-specific constraint blocks (Feature, Upgrade, Fix, Polish, Analytics, Test) totaling ~150 lines. Extract each to a procedure file that change.md references.

**Current structure (change.md lines 207-301):**
```
Step 6: Make changes (type-specific)
  ├── Feature constraints (lines 209-228) — ~20 lines + production path
  ├── Upgrade constraints (lines 239-255) — ~17 lines + production path
  ├── Fix constraints (lines 257-267) — ~11 lines + production path
  ├── Polish constraints (lines 269-278) — ~10 lines
  ├── Analytics constraints (lines 280-284) — ~5 lines
  └── Test constraints (lines 286-301) — ~16 lines
```

**Files to create:**

1. **`.claude/procedures/change-feature.md`** — Extract Feature constraints block
2. **`.claude/procedures/change-upgrade.md`** — Extract Upgrade constraints block
3. **`.claude/procedures/change-fix.md`** — Extract Fix constraints block
4. **`.claude/procedures/change-test.md`** — Extract Test constraints block

**Do NOT extract** Polish and Analytics — they're short enough to stay inline (<10 lines each).

**Each procedure file structure:**
```markdown
# /change: [Type] Implementation

> This procedure is invoked by change.md Step 6 when the change type is [Type].
> Read the full change skill at `.claude/commands/change.md` for lifecycle context.

## Prerequisites from change.md
- experiment.yaml and experiment/EVENTS.yaml have been read (Step 2)
- Change has been classified as [Type] (Step 3)
- Preconditions have been checked (Step 4/5)
- Plan has been approved (Phase 1)
- Specs have been updated (Step 5)

## Implementation

[Paste the exact constraint block from change.md, preserving all content]

## Production Quality Path (if `quality: production` in experiment.yaml)

[Paste the production-specific sub-block]
```

**File to modify:** `.claude/commands/change.md`

Replace each extracted block with a reference:
```markdown
#### Feature constraints
Follow the procedure in `.claude/procedures/change-feature.md`.
```

Keep the **CHECKPOINT — VERIFICATION GATE** block (lines 302-307) in change.md — it's a cross-cutting concern.

**Expected result:**
- change.md drops from ~357 lines to ~250 lines
- Each type's implementation is self-contained in its own file
- change.md remains the orchestrator (lifecycle, steps, gating)
- Procedure files are independently readable

**Acceptance criteria:**
- 4 procedure files created in `.claude/procedures/`
- change.md references them instead of inlining
- All content is preserved — no logic changes
- Polish and Analytics remain inline in change.md
- Verification gate stays in change.md
- Build passes

### Task G2: Extract plan templates to a shared location

**Context:** change.md Phase 1 has 6 plan templates (Feature, Upgrade, Fix, Polish, Analytics, Test) totaling ~90 lines. These are presentation templates, not implementation logic.

**File to create:** `.claude/procedures/change-plans.md`

**Content:** Move all 6 plan templates from change.md lines 77-185 to this file:
```markdown
# /change Plan Templates

> These templates are used by change.md Phase 1 to present the plan to the user.
> Each template corresponds to a change type classified in Step 3.

## Feature Plan Template
[paste from change.md lines 78-107]

## Upgrade Plan Template
[paste from change.md lines 109-124]

## Fix Plan Template
[paste from change.md lines 126-138]

## Polish Plan Template
[paste from change.md lines 140-146]

## Analytics Plan Template
[paste from change.md lines 148-164]

## Test Plan Template
[paste from change.md lines 166-185]
```

**File to modify:** `.claude/commands/change.md`

Replace the 6 template blocks with:
```markdown
Present the plan using the template for the classified type from `.claude/procedures/change-plans.md`.
```

**Expected result:**
- change.md drops by another ~90 lines (from ~250 to ~160)
- Plan templates are independently readable and editable
- change.md focuses on orchestration flow

**Acceptance criteria:**
- Procedure file created at `.claude/procedures/change-plans.md`
- All 6 templates preserved exactly
- change.md references the file instead of inlining
- Build passes

### Task G3: Final cleanup and cross-reference verification

**Context:** After G1 and G2, change.md should be ~160 lines. Verify all cross-references work and the overall flow is coherent.

**Steps:**
1. Read the final change.md and verify:
   - Step numbering is sequential and correct
   - All references to procedures resolve to existing files
   - Phase 1 → Phase 2 transition is clear
   - Verification gate (Step 7) still references verify.md
   - Step 8 (commit/push/PR) is unchanged

2. Read each procedure file and verify:
   - It references the correct change.md steps
   - All internal references (to other files like tdd.md, design.md) are correct
   - No duplicate content between procedures

3. Verify no other files reference change.md line numbers that have shifted:
   - Grep for "change.md" across all files
   - Update any line-number references if found

**Acceptance criteria:**
- change.md is < 200 lines
- All cross-references between change.md and procedure files are correct
- No broken references in other files
- Build passes
- The skill behavior is IDENTICAL to before decomposition

---

## Execution Guide

### Parallel sessions (maximum 7 concurrent):
```
Session 1: PR-A (rollback + incident response)
Session 2: PR-B (error recovery)
Session 3: PR-C (operational monitoring)
Session 4: PR-D (skill coherence)
Session 5: PR-E (security hardening)
Session 6: PR-F (performance + a11y agents)
Session 7: PR-G (/change decomposition)
```

### Per-session instructions:
```
Read docs/world-champion-plan.md, then execute PR-[X] tasks sequentially.
Follow CLAUDE.md rules (especially Rule 1: PR-First Workflow).
Create branch, implement all tasks, run verification (patterns/verify.md), open PR.
```

### Verification after all PRs merge:
Run `/review` to confirm the full template is consistent after all changes.
