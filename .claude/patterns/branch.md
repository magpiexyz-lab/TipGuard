# Branch Setup Procedure

Run this procedure at the start of every code-writing skill, before making any changes.

The skill that invokes this procedure provides two inputs:
- **branch_prefix**: the prefix for the branch name (e.g., `feat`, `change`, `fix`)
- **branch_name**: the full branch name to create (e.g., `feat/bootstrap`, `change/fix-signup-button`)

## Prerequisites

Verify all of these before proceeding. If any check fails, stop and report the error.

1. **Git repository**: run `git rev-parse --is-inside-work-tree`. If it fails: stop and tell the user: "Not a git repository. Either clone an existing repo (`git clone <url>`) or initialize a new one (`git init && git remote add origin <url>`)."

2. **Not detached HEAD**: run `git symbolic-ref HEAD`. If it fails: stop and tell the user: "HEAD is detached. Run `git checkout main` to switch to a branch."

3. **Origin remote exists**: run `git remote get-url origin`. If it fails: stop and tell the user: "No 'origin' remote found. Run `git remote add origin <repo-url>` to set one up."

4. **GitHub CLI authenticated**: run `gh auth status`. If it fails: stop and tell the user: "GitHub CLI is not authenticated. Run `gh auth login` to authenticate."

## Uncommitted Changes Check

Run `git diff --quiet && git diff --cached --quiet`. If either fails (there are uncommitted changes): stop and tell the user: "You have uncommitted changes. Please commit or stash them first." Show `git status --short` output.

## Worktree Detection

Check if running inside a git worktree (canonical helper — single source of truth):
```bash
IN_WORKTREE=$(bash .claude/scripts/lib/in-worktree.sh)
```

The helper itself uses `git rev-parse --git-common-dir != --git-dir` (the values
differ inside any non-primary worktree). This replaces the previously-inlined
4-line block; callers MUST use the helper rather than re-inlining the comparison.

## Switch to Default Branch and Pull Latest

1. Detect the default branch: `git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@'`. If empty, assume `main` and warn: "Could not detect default branch — assuming 'main'. Run `git remote set-head origin --auto` to fix." Then verify the assumed branch exists: `git show-ref --verify --quiet refs/heads/main`. If it fails, stop and tell the user: "Default branch detection failed and `main` does not exist. Run `git remote set-head origin --auto` to configure the default branch, then retry."

2. If `IN_WORKTREE` is false AND the current branch (from `git branch --show-current`) is not the default branch, run `git checkout <default-branch>`. If `IN_WORKTREE` is true: skip this step — the worktree's HEAD is already at the correct commit (EnterWorktree creates the worktree from the latest HEAD).

3. If `IN_WORKTREE` is false: pull latest: run `git pull --ff-only`. If that fails, try `git pull --rebase`. If rebase also fails, run `git rebase --abort` and stop: "Could not update the default branch. Run `git pull` manually and retry." If `IN_WORKTREE` is true: skip this step.

## Create Feature Branch and Persist to Active Context

This step creates the new branch AND propagates the new branch name to
active `.runs/*-context.json` files in **one atomic Bash invocation**.

**Do NOT split this across multiple Bash tool calls.** The PreToolUse
hook `branch-checkout-propagation-gate.sh` (issue #1328) denies any Bash
chain that contains `git checkout -b` without a sibling
`update-context-branch.sh`. Splitting recreates the race window where
`resolve_active_identity` filters out the active context (its `branch`
field is stale relative to `git branch --show-current`), causing agent
spawns during the gap to land in `degradation_reason:
active_identity_unresolvable`. See issue #1328.

1. Build the branch name from the skill's inputs. The skill provides
   the full `branch_name`.

2. **Slugify** (if the skill passes a description instead of a fixed
   name): convert to lowercase, replace non-alphanumeric characters
   with hyphens, remove leading/trailing hyphens, truncate to 40
   characters.

3. **Handle collisions**: if a branch with that name already exists
   (`git show-ref --verify --quiet refs/heads/<branch_name>`), append
   `-2`. If that also exists, try `-3`, and so on.

4. **Atomic create + propagate** — execute as ONE Bash invocation:

   ```bash
   echo "$(date +%s)" > .runs/last-branch-checkout.tsv && \
     OLD_BRANCH="$(git branch --show-current)" && \
     git checkout -b "<branch_name>" && \
     bash .claude/scripts/update-context-branch.sh "$OLD_BRANCH"
   ```

The chain stamps a sentinel timestamp before the checkout; the helper
reads the sentinel after propagation completes and records
`gap_seconds: N` to `branch-update-log.jsonl` if the propagation took
longer than 30 seconds (catches deferred propagation that somehow slips
past the gate). The helper updates the `branch` field of every
non-completed context file whose current `branch` equals `$OLD_BRANCH`
(skips epilogue contexts, completed contexts, and contexts on
unrelated branches). It writes atomically via a `.tmp` + rename and
appends a JSONL audit entry to `.runs/branch-update-log.jsonl`.

**Escape hatch for ad-hoc / test workflows:** set
`BRANCH_CHECKOUT_PROPAGATION_GATE_SKIP=1` before the Bash call to
bypass the pairing requirement. Use sparingly — silent-bypass risk
exceeds the false-positive risk for legitimate manual checkouts.

**Why bundling is required:** `init-context.sh` captures `branch` at
init-time, which is the pre-checkout default branch. Without
same-turn propagation, `resolve_active_identity`
(`.claude/hooks/lib-state.sh`) filters out the active context because
its `branch` field is stale, silently breaking identity grounding for
every downstream trace writer (`write-agent-trace.sh`,
`write-degraded-trace.py`, `check-observation-artifacts.sh`).

After this procedure completes, the skill is on a clean feature branch
based on the latest default branch, with active context files pointing
at the new branch. Proceed with the skill's implementation steps.
