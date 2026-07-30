# Auto-Merge Procedure

Auto-merge is executed centrally by `lifecycle-finalize.sh` after delivery gate
checks pass. Individual skills no longer call auto-merge directly — they write
delivery artifacts (`.runs/commit-message.txt`, `.runs/pr-title.txt`,
`.runs/pr-body.md`) and finalize handles commit, push, PR creation, and merge.

This document defines the procedure that `lifecycle-finalize.sh` implements.
The PR exists for audit trail (Rule 1) and is merged immediately after creation.

## Default-Branch Guard (before any commit)

Delivery must never commit on the repository's default branch (issue #1990:
an analysis-mode skill whose init created no feature branch had its run
record committed and pushed directly to main). Before `git add`, finalize
invokes `.claude/scripts/lib/delivery-branch-guard.sh`, which:

- derives the default branch once via `resolve_default_branch` in
  `lifecycle-lib.sh` (origin/HEAD symbolic ref, then origin/main, then
  origin/master, then the literal `main`) — the same derived value replaces
  every previously hardcoded `main` in finalize;
- is a no-op on any non-default branch (code-writing skills already sit on
  their init-created branch);
- on the default branch with a clean tree in sync with origin, reports
  skip-no-changes so no empty chore branch or guaranteed-empty PR is created;
- otherwise creates and checks out `chore/<skill>-delivery-<UTC stamp>`
  (collisions append `-2`..`-5`; exhaustion is a hard failure), using the
  bundled checkout chain from `branch.md` so `update-context-branch.sh`
  propagates the context's `branch` field in the same command chain;
- exits non-zero when safety cannot be guaranteed — finalize then records
  `branch-guard-failed` and does NOT commit.

**Analysis-only record deliveries.** An analysis-only skill (per the command
file's `type:` frontmatter, resolved through the BASE skill name so
mode-qualified keys like `iterate-cross` work) skips delivery only when it
produced no delivery artifacts. Artifacts present at finalize were
necessarily written during this run — lifecycle-init deletes them at every
non-embed skill start — so they are treated as a deliberate record delivery
(e.g. iterate-cross committing its config + decision-ledger mutations), with
the guard enforcing PR-first.

**Degrade, never abort.** Every delivery stage after the gates (`git commit`,
`git push`, `gh pr create`, the post-merge checkout/pull) converts failure
into a recorded delivery status instead of aborting the script, so the
verify-recheck artifact and transient-service teardown always run. The #1990
incident aborted mid-delivery after the push had landed, skipping both.

## Safety Gates

Run all three gates in order. If ANY gate fails, leave the PR open and report
the gate failure to the user. Do not proceed to merge.

### Gate 1: Migration guard

```bash
if gh pr diff --name-only | grep -q '^supabase/migrations/'; then
  echo "PR contains database migrations — skipping auto-merge."
  echo "Review migrations and merge manually."
  # SKIP — do not merge
fi
```

Why: CI runs `supabase db push` on push to main. Destructive migrations
(drop table/column) should be reviewed before hitting production.

### Gate 2: Secret scan (graceful)

```bash
if command -v gitleaks >/dev/null 2>&1; then
  if ! gitleaks detect --source . --no-banner --exit-code 1 2>/dev/null; then
    echo "gitleaks detected potential secrets — skipping auto-merge."
    echo "Review findings and merge manually."
    # SKIP — do not merge
  fi
fi
# If gitleaks is not installed: PASS (proceed). This gate is advisory.
```

Why: CI runs gitleaks on PRs. Local verification uses LLM-based security
review which may miss secrets that deterministic scanning catches.

### Gate 3: Template-lint parity (diff-dispatched)

```bash
if command -v make >/dev/null 2>&1; then
  MERGE_BASE=$(git merge-base "origin/$DEFAULT_BRANCH" HEAD 2>/dev/null || git merge-base "$DEFAULT_BRANCH" HEAD 2>/dev/null || echo "")
  if [[ -z "$MERGE_BASE" ]]; then
    LINT_TARGET="lint-template-full"   # unknown state → fail-closed
  else
    DIFF_FILES=$(git diff --name-only "$MERGE_BASE..HEAD" 2>/dev/null || echo "")
    if [[ -z "$DIFF_FILES" ]]; then
      LINT_TARGET="lint-template-full"  # unknown state → fail-closed
    elif echo "$DIFF_FILES" | grep -qE '^scripts/'; then
      LINT_TARGET="lint-template-full"  # validator code changed → include pytest
    elif echo "$DIFF_FILES" | grep -qE '^\.claude/|^\.github/workflows/|^Makefile$'; then
      LINT_TARGET="lint-template"       # template content / CI config only → fast
    fi
    # else: pure src/ → LINT_TARGET empty → skip gate
  fi
  if [[ -n "$LINT_TARGET" ]]; then
    if ! make "$LINT_TARGET"; then
      echo "make $LINT_TARGET failed — skipping auto-merge."
      # SKIP — do not merge
    fi
  fi
fi
```

Why: local `/verify` only covers app-level checks (build, design-critic,
ux-journeyer, security agents). The template-semantic validators that CI
runs (`validate-semantics.py`, `validate-convergence-config.py`,
`consistency-check.sh`, `ci-check-stack-knowledge.py`,
`validate-stack-knowledge.py`, `verify-linter.sh` drift, `pytest scripts/`)
are disjoint from `/verify`. A PR that passes `/verify` can still fail CI
on those validators, landing a broken `main` (issue #1003).

The diff dispatch keeps the common case cheap. Most skill PRs touch only
`.claude/` files; those get the fast `lint-template` path (~1–3s). PRs
that touch the validator code under `scripts/` get the full path including
pytest (~50s) because validator-code regressions are exactly what pytest
catches. Unknown diff state (empty output, unresolvable merge-base) falls
through to `lint-template-full` — fail-closed, because unknown state is
how the original bug slipped through.

`git diff` is used instead of `gh pr diff` to avoid the same silent-failure
class the original bug had: if `gh` auth expires mid-session or GitHub
blips, `gh pr diff` returns empty stdout + exit 0, which looks
indistinguishable from "no diff." `git diff` against the local merge-base
is deterministic and network-free.

### Why not wait for remote CI instead? (considered and rejected)

<!-- DO_NOT example discussion: the `--auto` flag is mentioned below as something
     we must NOT use on this repo. Check 21 excludes DO_NOT-marked lines. -->
An alternative design polls `gh pr checks --watch --fail-fast` between PR
creation and merge. Advantages: CI is the single source of truth, zero drift
risk. Disadvantages: +30s–2m per merge (CI median on this repo is ~77s), and
this private repo has `allow_auto_merge=false` + no GitHub Pro (branch
protection unavailable, 403), so the usual `gh pr merge` + `--auto` path is <!-- DO_NOT -->
booby-trapped — it silently falls back to immediate non-gated merge.

For this single-maintainer template repo, the local-mirror approach's only
real hazard — drift between `Makefile` and `.github/workflows/*.yml` — is
closed by the parity assertion in `scripts/consistency-check.sh` (Check 20),
which CI runs on every PR. Net result: ~79s/merge saved with equivalent
safety. See plan `distributed-wibbling-pebble.md` for the first-principles
analysis.

## Merge

```bash
FEATURE_BRANCH=$(git branch --show-current)

# All skills use --squash for clean single-commit history.
# /upgrade tracks sync state via .claude/template-sync-meta.json instead of merge ancestry.
# DO_NOT add --auto: repo allow_auto_merge=false — --auto silently becomes
# an immediate non-gated merge (see issue #1003, feedback_gh_pr_merge_auto_fallback).
if [[ "$(bash .claude/scripts/lib/in-worktree.sh)" == "true" ]]; then
  # In worktree: --delete-branch triggers local checkout of main which fails
  # (main is checked out in primary worktree). Branch is cleaned up by ExitWorktree.
  gh pr merge --squash
else
  gh pr merge --squash --delete-branch
fi
```

If `gh pr merge` fails:
- Report the error to the user
- Common causes: branch protection requires reviews, merge conflicts
- Leave the PR open — do not retry
- The skill still reaches TERMINAL with the skip reason reported

## Post-Merge

```bash
if [[ "$(bash .claude/scripts/lib/in-worktree.sh)" == "false" ]]; then
  { git checkout "$DEFAULT_BRANCH" && git pull; } || \
    echo "WARN: post-merge checkout/pull failed — resolve manually" >&2
  git branch -d "$FEATURE_BRANCH" 2>/dev/null || true
fi
# In worktree: skip local checkout — ExitWorktree handles cleanup.
# A checkout/pull failure warns and continues — the recheck artifact and
# transient teardown must still run.
```

After merge completes:
1. Report: "PR #N auto-merged to main."
2. Surface the skill's next-step guidance (deploy, publish, etc.)

## Skip Conditions

Skills skip auto-merge entirely when:
- **Upgrade dry-run**: No PR was created (`dry_run == true`)
- **Review no-findings**: No branch exists (no findings across iterations)
- **Any safety gate fails**: PR left open with reason reported. Reason codes:
  - `migrations` — Gate 1 detected a `supabase/migrations/` change
  - `gitleaks` — Gate 2 detected a potential secret
  - `template-lint` — Gate 3 `make lint-template` failed on a `.claude/` diff
  - `merge-failed` — `gh pr merge` itself returned non-zero

In every `pr-created:*` outcome the session stays on the (possibly
guard-created) feature branch and the local branch is not deleted — the
operator reviews and merges manually, which is the standing practice while
Gate 3 trips on pre-existing template-lint debt.

Delivery-stage statuses (degrade-not-abort; recorded in
`verify-recheck.json.delivery_status` and echoed as `DELIVERY=<status>`):
  - `skipped-no-changes` — guard found a clean default branch in sync with
    origin; nothing to deliver
  - `branch-guard-failed` — the guard could not guarantee a safe branch;
    nothing was committed
  - `commit-failed` / `push-failed` — the corresponding git stage failed;
    later stages skipped
  - `pr-create-failed` — the branch is pushed but `gh pr create` failed;
    open the PR manually

## Regression Guards

Three invariants protect this procedure from future regressions. All three
live in `scripts/consistency-check.sh` and run on every PR via the
`Consistency check` step in `.github/workflows/ci.yml`:

- **Check 20 — Makefile ↔ CI parity.** Every template validator invoked by
  any `.github/workflows/*.yml` must also appear in the `lint-template:`
  target in `Makefile`, unless it is deliberately declared in a `# CI-ONLY:`
  comment directly above the target (for validators that require PR context,
  are scheduled nightly, etc.). Prevents silent drift between the local
  mirror and CI.

- **Check 21 — No `--auto` flag.** No file under `.claude/scripts/`,
  `.claude/patterns/`, or `.claude/hooks/` may add the `--auto` flag to a
  merge command. Lines containing a `DO_NOT` marker (comments, HTML
  comments, or inline doc prose) are skipped so this document can discuss
  the forbidden pattern without tripping the check.

- **Check 22 — Merge-caller allowlist.** All `gh pr merge` invocations under
  `.claude/` must live in either `.claude/scripts/lifecycle-finalize.sh` or
  `.claude/patterns/auto-merge.md`. Prevents a future skill/hook from
  sneaking in a second merge caller that bypasses the Guard chain above.
  Same `DO_NOT` exclusion applies.

## User-Facing Messages

When auto-merge succeeds:
> PR #N auto-merged to main. [skill-specific next steps]

When auto-merge is skipped:
> PR created but not auto-merged: [reason]. Review and merge manually.
