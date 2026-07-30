**⚠️ Post-merge steps:** None
<!-- Skills replace "None" with actual steps (e.g., run migration SQL, add env vars) -->

## Summary
<!-- Plain-English explanation of what this PR does and why. Written for someone who doesn't read code. -->

## How to Test
<!-- Steps to verify this works after merging and deploying: -->
<!-- 1. Go to [page] -->
<!-- 2. Click [button] -->
<!-- 3. You should see [result] -->

## What Changed
<!-- List the files changed and what changed in each. -->
-

## Why
<!-- What problem does this solve? Reference the experiment.yaml feature or problem. -->
<!-- If fixing a bug: include root cause and link to issue (Closes #123) -->

## Checklist

### Scope
- [ ] Only builds/changes what's in `experiment/experiment.yaml`
- [ ] No new features, libraries, or frameworks beyond scope
- [ ] No unrelated changes bundled into this PR

### Analytics
- [ ] All new/changed pages fire correct events from `experiment/EVENTS.yaml`
- [ ] All required event properties are included
- [ ] `project_name` and `project_owner` are attached (via the analytics library)
- [ ] No existing analytics were removed or broken

Events added/modified:
- <!-- e.g., visit_landing on src/app/page.tsx -->

### Build
- [ ] `npm run build` passes with zero errors
- [ ] No hardcoded secrets (all in env vars)
- [ ] `.env.example` updated if new env vars were added

### Verification
- [ ] `verify.md` ran in full (build loop + parallel review)
- [ ] design-critic verdict: <!-- e.g., "all pass" / "all fixed" / "skipped — Playwright not installed" -->
- [ ] ux-journeyer verdict: <!-- e.g., "all pass, 2 clicks to value" / "fixed dead-end on /dashboard" / "skipped — Playwright not installed" -->
- [ ] security verdict: <!-- e.g., "no issues" / "2 issues fixed" / "skipped — no API routes" -->
