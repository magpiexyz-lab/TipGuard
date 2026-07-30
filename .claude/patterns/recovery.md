# Error Recovery Pattern

## Principles
1. **Idempotency first**: Skills should be safe to re-run after failure
2. **State checkpoints**: Skills save progress so re-runs skip completed steps
3. **Partial cleanup guidance**: When re-run isn't possible, document manual cleanup

## Frontmatter-Based Resume

When `.runs/current-plan.md` has YAML frontmatter, skills resume at the exact
checkpoint without re-deriving classification or stack.

| Field | Purpose |
|-------|---------|
| `skill` | Which skill (`change` / `bootstrap`) |
| `type` | Change classification — skip re-classification |
| `scope` | Verification scope — skip re-derivation |
| `archetype` | Product archetype — skip experiment.yaml type read |
| `branch` | Git branch — informational |
| `stack` | All category/value pairs — skip stack resolution |
| `checkpoint` | Exact resume position |
| `modules` | Ordered list of modules for unit test generation |
| `context_files` | Files to re-read on resume — full state reconstruction |

**Backward compatible:** No frontmatter → current behavior (skip Phase 1, start at Phase 2 beginning).

## Per-Skill Recovery Matrix

### /bootstrap failure
- **State saved:** `.runs/current-plan.md` with frontmatter (archetype, stack, checkpoint), `package.json` (installed packages)
- **Recovery:** Re-run `/bootstrap` — Step 4 reads frontmatter checkpoint and resumes at exact phase
- **If checkpoint is `awaiting-verify`:** Bootstrap scaffolding complete. Re-run `/bootstrap` — resumes at STATE 19a (verify prep), then 19b runs embedded verify via transparent dispatch.
- **Manual cleanup:** If you want to start fresh: `git checkout main && make clean`

### /deploy failure (most common)
- **State saved:** `.runs/deploy-manifest.json` (resources created so far)
- **Partial state scenarios:**
  | Failed at | Resources exist | Recovery |
  |-----------|----------------|----------|
  | Step 0.6 (hosting auth) | None | Run the `auth_fix` command from the hosting stack file. If interactive login fails (CI/CD): set the hosting provider's auth token as an env var (see hosting stack file's Deploy Interface > Prerequisites for token env var name). Then re-run `/deploy`. |
  | Step 0.7 (database auth) | None | Run the `auth_fix` command from the database stack file. If interactive login fails (CI/CD): set the database provider's auth token as an env var (see database stack file's Deploy Interface > Prerequisites for token env var name). Then re-run `/deploy`. |
  | Step 3 (database) | Database project | Re-run `/deploy` — Step 3 checks for existing project |
  | Step 4 (hosting) | Database + hosting project | Re-run `/deploy` — Step 4 is idempotent (vercel link reuses existing) |
  | Step 4.4 (env vars) | DB + hosting (no env vars) | Re-run `/deploy` — env vars use upsert semantics |
  | Step 5a (deploy cmd) | DB + hosting + env vars | Re-run `/deploy` — redeploy is safe |
  | Step 5b (agents) | DB + hosting + deployed | Re-run `/deploy` — agents check for existing resources |
- **Nuclear option:** Run `/teardown` (reads manifest, deletes everything in reverse)

### /change failure
- **State saved:** `.runs/current-plan.md` with frontmatter (type, scope, archetype, stack, checkpoint) on feature branch
- **Recovery:** Re-run `/change` on the same branch — Step 4 reads frontmatter checkpoint and resumes at exact step
- **Manual cleanup:** `git checkout main && git branch -d <branch-name>`

### /verify failure
- **State saved:** Fix attempts on current branch, `.runs/agent-traces/` (partial trace artifacts)
- **Recovery:** Re-run `/verify` — starts fresh test run. If verify was embedded by bootstrap, re-run `/bootstrap` instead — it resumes at STATE 19a (verify prep).
- **Manual cleanup:** Trace cleanup is now automatic in STATE 0 (`rm -rf .runs/agent-traces && mkdir -p .runs/agent-traces`). No manual cleanup needed. Verify itself does not modify infrastructure.

### /distribute failure
- **State saved:** `experiment/ads.yaml` (campaign config)
- **Recovery:** Re-run `/distribute` — reads existing ads.yaml
- **Manual cleanup:** Delete `experiment/ads.yaml` to regenerate

### Bootstrap unit test generation failure
- **State saved:** `.runs/bootstrap-scan.json`, `.runs/bootstrap-modules-trace.json`, unit tests on feature branch
- **Recovery:** Re-run `/bootstrap` — STATE 15 re-scans modules, STATE 16 skips modules with existing tests.
- **Manual cleanup:** `git checkout main && git branch -d <branch-name>`

## Generic Recovery Steps
1. Check which branch you're on: `git branch --show-current`
2. Check what files changed: `git status`
3. If on a feature branch with uncommitted changes:
   - Save progress: `git add -A && git commit -m "WIP: recovery point"`
   - Start fresh: `git checkout main`
4. Re-run the skill — most skills detect existing state and resume
