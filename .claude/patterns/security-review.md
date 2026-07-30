# Security Review Procedure

Review all changed files for security issues that compile successfully but
create runtime vulnerabilities. This enforces CLAUDE.md Rule 6.

## 1. Plugin Check

**Invoke the `security-guidance` skill** (via the Skill tool) to review all
changed files. The skill has full authority over security analysis — it
catches vulnerabilities that compile successfully but create runtime holes
(hardcoded secrets, missing validation, absent access control).

If the skill is not available (not listed in available skills): stop and
tell the user:

> The `security-guidance` plugin provides automated security analysis of
> your code changes — catching hardcoded secrets, missing input validation,
> absent RLS policies, and client/server boundary violations.
>
> It is enabled in `.claude/settings.json` but did not load in this
> session. Restart Claude Code to reload plugins. If the issue persists,
> verify `"security-guidance@claude-plugins-official": true` is set in
> `.claude/settings.json`.

Then **stop and wait** for the user to confirm it's fixed (or to say
"skip"). If the user says "skip", proceed with the manual fallback
checklist below.

## 2. Manual Fallback Checklist

> Only used when the security-guidance skill is skipped.

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
> web-app: D1–D5 + A1–A5 | service: D1, D2, D3, D5 + A1–A4 | cli: D1, D2 + A1, A4

Read `experiment/experiment.yaml` to determine the archetype (`type` field, default: `web-app`).
Scope applies to both Defender and Attacker agents below:

- **web-app**: Defender D1–D5, Attacker A1–A5
- **service**: Defender D1, D2, D3, D5 (skip D4), Attacker A1–A4 (A5 only if auth endpoints exist)
- **cli**: Defender D1, D2 only, Attacker A1, A4 only

### Parallel Agents

> **When invoked by verify.md:** These checks are executed by the
> `security-defender` and `security-attacker` custom subagents directly.
> The parallel spawn below applies only to direct invocations of this
> procedure (e.g., from deploy.md or ad-hoc).

Spawn **two agents simultaneously** using parallel Agent tool calls. Both scan
all files in `src/` but from different perspectives.

#### Defender Agent

Adopt a **compliance auditor** perspective. Check for the presence of required
security controls. Report a pass/FAIL/skip table.

**D1. Hardcoded Secrets**
Search for secret-like patterns: `sk_live_`, `sk_test_`, `sbp_`, `supabase_service_role`,
`-----BEGIN`, API keys assigned to string literals. Any match is a FAIL.
Exclude `phc_` prefixed values — PostHog publishable project API keys, designed
for client-side embedding (same class as Stripe `pk_test_`). The security-guidance
plugin may independently flag `phc_` strings; expected resolution: dismiss as
publishable key.

**D2. Input Validation**
Every API route handler must validate input with zod (or similar). Check
each `route.ts` / `route.js` file — if the handler reads `request.json()`,
`request.formData()`, or URL params without schema validation, it's a FAIL.

**D3. Database RLS**
> Skip if `stack.database` is absent from experiment.yaml.

Every `CREATE TABLE` statement must have a corresponding
`ALTER TABLE ... ENABLE ROW LEVEL SECURITY` and at least one policy. Check
migration files and schema definitions. Missing RLS is a FAIL.

**D4. Client/Server Boundary**
> Skip for `service` and `cli` archetypes — web-app only.

Server-only environment variables (`SUPABASE_SERVICE_ROLE_KEY`, `*_SECRET_*`,
`*_ADMIN_*`) must not be imported or referenced in files marked `"use client"`.
Any match is a FAIL.

**D5. Rate Limiting**
Auth and payment API routes (`/api/auth/**`, `/api/payment/**`,
`/api/checkout/**`, `/api/webhook/**`) must include rate limiting. Missing
rate limiting is a FAIL. See hosting stack file for deployment-specific
constraints.

**Output format:**

| Check | Status |
|-------|--------|
| D1. Hardcoded secrets | pass/FAIL |
| D2. Input validation | pass/FAIL |
| D3. Database RLS | pass/FAIL/skip |
| D4. Client/server boundary | pass/FAIL/skip |
| D5. Rate limiting | pass/FAIL |

#### Attacker Agent

Adopt a **penetration tester** perspective. Attempt to find logic-level
vulnerabilities that pass Defender checks but are still exploitable. Assign
each finding a severity: **critical**, **high**, or **info**.

**A1. Validation Bypass**
Look for incomplete zod schemas: missing `.max()` on strings, missing
`.email()` on email fields, `z.any()` or `z.unknown()` without narrowing,
unvalidated query parameters, type coercion gaps (e.g., numeric string
accepted where integer expected).

**A2. Access Control Gaps**
Look for overly permissive RLS policies (`USING (true)`), missing ownership
checks (`WHERE id = $1` without `AND user_id = $user`), service role key
used in user-facing routes, endpoints that skip auth middleware.

**A3. Injection & Encoding**
Look for SQL string concatenation (instead of parameterized queries), XSS
via unsafe HTML rendering (e.g., `dangerouslySetInnerHTML` without
DOMPurify sanitization), unvalidated redirect URLs (open redirect).

**A4. Information Leakage**
Look for stack traces in error responses (e.g., `error.stack` returned to
client), over-fetched sensitive columns (e.g., `SELECT *` including
`password_hash`), debug `console.log` statements that leak sensitive data.

**A5. Authentication Weaknesses**
Look for tokens stored in `localStorage` (instead of httpOnly cookies),
missing `httpOnly` or `secure` flags on auth cookies, password reset flows
without expiry, session tokens that don't rotate after privilege changes.

**Output format:** Numbered findings list. If no issues found, report
"Attacker: no adversarial issues found."

For each finding:
```
#N [severity] Category — File:line
Description of the vulnerability.
Suggested fix: ...
```

### Merge

After both agents complete, combine results:

1. Collect all Defender FAILs and all Attacker findings.
2. If both flag the same file and issue, keep the more specific Attacker
   finding and mark the Defender check as **subsumed** (still counts as FAIL
   in the Defender table, but the Attacker finding drives the fix).
3. The merged list is the input to Step 3.

## 3. Fix Cycle (max 2 cycles)

If security issues are found from either Defender or Attacker:

1. Prioritize **critical** and **high** Attacker findings first, then Defender FAILs
2. **Info**-severity Attacker findings skip fix cycles (noted in report only)
3. Fix the code
4. Run `npm run build` (must still pass)
5. Re-run the failed checks
6. Re-review

Repeat up to **2 fix cycles**. If issues remain after 2 cycles, report
them to the user and proceed — do not block the commit.

## 4. Report

Summarize results in two tables:

**Defender Results**

| Check | Status |
|-------|--------|
| D1. Hardcoded secrets | pass/FAIL |
| D2. Input validation | pass/FAIL |
| D3. Database RLS | pass/FAIL/skip |
| D4. Client/server boundary | pass/FAIL/skip |
| D5. Rate limiting | pass/FAIL |

**Attacker Results**

| # | Severity | Category | File | Issue | Status |
|---|----------|----------|------|-------|--------|
| 1 | critical/high/info | A1–A5 | file:line | description | fixed/unfixed/noted |

If no Attacker findings: "Attacker: no adversarial issues found."

Status values:
- **fixed**: resolved during fix cycles
- **unfixed**: critical/high that could not be resolved in 2 cycles
- **noted**: info-severity, reported for awareness only

Any unfixed FAIL or critical/high Attacker items must be noted in the PR
body under a **Security Notes** section so reviewers are aware.
