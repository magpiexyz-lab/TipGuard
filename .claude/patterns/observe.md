# Template Observation Procedure

Follow this procedure to evaluate and file template-rooted issues as GitHub
issues on the template repo.

## Entry Point

> **Implementation:** `.claude/patterns/observation-phase.md` is the unified
> entry point for all observation. It calls this procedure's decision framework
> (3-condition test), redaction, dedup, and issue filing sections.

This procedure defines the canonical decision framework. It is invoked:
1. By `observation-phase.md` Steps 4-6 — the unified observation procedure for all skills
2. By `/observe` skill's state-1 — manual observation via `--file` and `--symptom`
3. By verify STATE 7b — Q-score-triggered observation (Path 3)

When called, you should already know which fix(es) to evaluate. Proceed
directly to Trigger Evaluation below.

## Prerequisites

1. Resolve the template repo (where observations should be filed):
   ```bash
   TEMPLATE_REPO="magpiexyz-lab/mvp-template"
   if ! git remote get-url template &>/dev/null; then
     git remote add template https://github.com/magpiexyz-lab/mvp-template.git
   fi
   ```
   The template remote is auto-added if missing.
2. `gh auth status` — if fails → skip filing only (evaluation still runs).
3. `gh repo view $TEMPLATE_REPO --json name` — if fails → skip filing only (evaluation still runs).

Observation evaluation is mandatory. Filing to GitHub is gracefully degraded
(if `gh` auth or repo access fails, log locally and report to user). Never
silently skip the evaluation step itself.

## Trigger Evaluation

Evaluate whether fixes qualify as template observations. Use **Path 1** or
**Path 2** depending on how you were invoked.

**Decision rule:** If you were spawned as an Observer Agent with a diff, fix
summaries, and template file list provided to you, use **Path 1**. Otherwise
(deploy.md, ad-hoc fix, or any other direct invocation), use **Path 2**.

---

### Path 1 — Observer Agent (used by verify.md Auto-Observe)

You are a fresh agent with no project context. You received:
- A `git diff` of fixes made during verification (build, lint, visual, and/or security)
- One-line summaries of each error fixed
- A template file list

For each fix, evaluate whether **all three** conditions are true:

**A. Template file is the root cause.** The fix required changing — or would ideally
change — a file that appears in the template file list you were given.

  OR: project code was fixed, but the root cause is incorrect guidance in a template
  file (e.g., a code template produces a build error, a skill's instructions lead to
  a missing import).

**B. Not an environment issue.** NOT caused by: missing CLI tools, network failures,
Node version mismatches, missing env vars (.env not populated), or auth failures.

**C. Not a user code issue.** NOT caused by: business logic bugs, project-specific
dependency conflicts, or code that simply doesn't follow template guidance.

**Heuristic:** "Would another developer using this template with a different project
hit this same problem?" If yes → file it.

If no fixes qualify → return "No template observations" and stop.

If any qualify → proceed to Prerequisites below.

---

### Path 2 — Direct evaluation (deploy.md, ad-hoc)

For each code change or error fix made during the current session, evaluate
whether it qualifies as a template observation. A change qualifies when **all
three** conditions are true:

**A. Template file is the root cause.** The fix required changing — or would ideally
change — a file listed in `.claude/template-owned-dirs.txt` (the canonical list of
all template-owned directories and files).

  OR: you fixed project code, but the root cause is incorrect guidance in a template
  file (e.g., a code template produces a build error, a skill's instructions lead to
  a missing import).

**B. Not an environment issue.** NOT caused by: missing CLI tools, network failures,
Node version mismatches, missing env vars (.env not populated), or auth failures.

**C. Not a user code issue.** NOT caused by: business logic bugs specific to this
experiment.yaml, unclear experiment.yaml content, user code not following template guidance, or
project-specific dependency conflicts.

**Heuristic:** "Would another developer using this template with a different experiment.yaml
hit this same problem?" If yes → file it.

If no fixes qualify → stop here.

## Path 3 — Q-score trigger (used by verify.md STATE 7)

You are triggered because a skill's Q-score fell below 0.5. You received:
- The skill name and Q-score breakdown (Gate, R_system, R_human, dimension_scores)
- The timestamp and run_id

### Evaluation

For Q-score-triggered observations, the evaluation is simpler than Path 1/2:

**A. Is this a template issue?** Does the low Q indicate a systematic problem that would affect other users with different experiment.yaml files?
- Gate = 0 (hard failure) with `hard_gate_failure: true` → likely template issue if the gate agent (design-critic, ux-journeyer, security-fixer, quality-fixer) consistently fails
- R_system > 0.5 (high auto-remediation) → template prompt may need tightening (agents doing too much cleanup)
- R_human > 0 (exhaustions/interventions) → template agent budgets or instructions may be insufficient

**B. Is this reproducible?** A single low-Q run could be LLM stochasticity. Only file if:
- This is the second consecutive low-Q run for the same skill (check verify-history.jsonl), OR
- Gate = 0 (hard failures are always worth reporting)

If neither condition is met → stop here. The Q-score is logged for trend analysis but no observation is filed.

### Issue Format

Title: `[observe] Low Q-score: <skill> Q=<q_skill>`

Body:
```
**Skill:** <skill>
**Q-score:** <q_skill> (Gate=<gate>, R_system=<r_system>, R_human=<r_human>)
**Weakest dimension:** <dimension with lowest Q_d> (<value>)
**Scope:** <scope>
**Archetype:** <archetype>

This is an automated quality observation. The skill's Q-score fell below 0.5,
indicating significant remediation was needed after the skill ran.
```

Then follow the standard **Redaction**, **Dedup**, and **Issue Creation** procedures below.

## Redaction

Before composing the issue, strip all project-specific information:
- Replace the project name (from experiment.yaml `name`) with `<project>`
- Replace experiment.yaml content (problem, solution, features) with `<redacted>`
- Replace full error stack traces with the relevant error message only
- Replace paths containing project-specific page names with generic paths
  (e.g., `src/app/invoice-create/page.tsx` → `src/app/<page>/page.tsx`)
- Keep: template file name, generic symptom description, fix diff (template-relevant
  lines only)

## Dedup

Search for existing open observations about the same template file:

```bash
gh issue list --repo $TEMPLATE_REPO --label observation \
  --search "[observe] <template-file-basename>:" --state open --limit 20
```

Read the titles of matching results. If any existing issue describes the same
underlying problem (same template file, same root cause — even if worded
differently), add a comment instead of creating a new issue:

```bash
gh issue comment <issue-number> --repo $TEMPLATE_REPO --body "<comment>"
```

Comment body:
```
## Additional occurrence

**Context:** /<skill-name> or ad-hoc fix
**Date:** <today>
**Symptom:** <one-line generic description>
**Fix applied in project:** <generic description of the workaround>
```

After commenting → stop. Do not create a new issue.

## Issue Creation

If no duplicate found, create a new issue.

**Title format:** `[observe] <template-file-basename>: <symptom-in-imperative-form>`

Examples:
- `[observe] nextjs.md: Landing page template missing React import for Suspense`
- `[observe] bootstrap.md: Step 7b runs playwright install before npm install -D`
- `[observe] deploy.md: Auto-fix loop does not re-check auth config after PATCH`

**Body format:**
```
## Observation

**Template file:** `<full path>`
**Context:** /<skill-name> | ad-hoc fix
**Trigger:** verify.md auto-observe | deploy.md auto-fix | auto-generated stack file | ad-hoc fix

## Symptom

<1-3 sentences, generic — no project names>

## Root cause

<1-3 sentences explaining why the template guidance/code is incorrect>

## Fix

<Minimal diff or description. Only template-relevant lines. Redacted.>

## Suggested template change

<What the template file should change to prevent this in future projects.
If you already updated the stack file during "Save Notable Patterns", describe
that change. If you only fixed project code as a workaround, describe the
template-level fix.>

---
*Auto-filed by the observation pattern.*
```

**Filing command:**

Before filing, compute the file version for the template file being observed:
```bash
FILE_VERSION=$(git hash-object "$TEMPLATE_FILE" 2>/dev/null || echo "unknown")
```

Append version metadata to the body (after the `*Auto-filed by the observation pattern.*` line):
```
---
template_file: <full path to the template file>
file_version: <FILE_VERSION value>
```

Then file the issue:
```bash
gh issue create --repo $TEMPLATE_REPO \
  --title "<title>" \
  --label "observation" \
  --body "<body>"
```

**Error handling:**
- If label "observation" doesn't exist → retry without `--label "observation"`.
  Prefix body with: `**Label:** observation (create this label for filtering)`.
- If filing fails for any other reason → log the error and continue.
- If successful → report the URL to the user: "Filed template observation: <url>"

## Constraints

- **Mandatory evaluation, graceful filing.** Evaluation must always run.
  GitHub filing degrades gracefully on API failures (log locally, report to user).
  Never silently skip evaluation.
- **Max 1 issue per session.** Multiple fixes → combine into one issue with
  multiple Symptom/Fix sections.
- **Skip simple typos** unlikely to recur (consistent with verify.md's skip rule).
