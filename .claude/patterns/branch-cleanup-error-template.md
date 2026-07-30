# Branch Cleanup Error Template

Canonical boilerplate for branch-cleanup guidance in skill state files. When a
state stops while the user is on a feature branch, the user-facing message must
include cleanup instructions. State files reference this file once and supply
the variable parts (branch, recovery); the template defines the wrapping prose
so any improvement is made in one place.

Used by: `/change` (state-5, state-7) and `/distribute` (state-0, state-1).

## Variants

### Variant A — Stop message with recovery path (most common)

Append to user-facing stop messages when there's a way to fix the problem and re-run the skill:

> To abort: `git checkout main && git branch -D <branch-name>`. To fix and retry: <recovery-action>.

### Variant B — Abort-only

Append when no recovery path is possible (the change as configured cannot proceed on this branch). Often paired with an inline recovery instruction in the error description itself:

> To abort: `git checkout main && git branch -D <branch-name>`.

### Variant C — Manual cleanup fallback message

Used when a state runs the cleanup commands itself (currently only `/change` state-7 when the user selects "skip") and either command fails (e.g., uncommitted changes blocking checkout, branch deletion refused). The state should report this manual-fallback message:

> Could not clean up automatically. Run `git stash && git checkout main && git branch -D <branch-name>` manually, then run `/<skill>` again.

The "happy path" — running the cleanup commands and the success message — is the calling state's responsibility (kept inline so the operational steps are visible without chasing this reference).

## Placeholders

- `<branch-name>` — current feature branch name. For `/change`, leave as the literal `<branch-name>` (the user mentally substitutes their actual branch when running the command — this matches the existing convention). For `/distribute`, substitute the fixed value `chore/distribute`.
- `<recovery-action>` — short imperative describing the fix (e.g., `address the missing dependencies, then re-run \`/change\``).
- `<skill>` — the skill name (`change`, `distribute`).

## How state files reference this template

Add one blockquote near the top of the state's ACTIONS block:

> **Branch cleanup on failure:** Any "stop" below leaves you on a feature branch. Append cleanup boilerplate per `.claude/patterns/branch-cleanup-error-template.md` to every stop message — Variant A by default, Variant B if no recovery path applies. Supply `recovery` (and `branch`, for `/distribute`) per call.

Each stop call then writes only the variable parts inline, for example:

> ... if X, stop: "Testing setup assumes [unmet dependencies]. Tests will break. Run `/change fix test configuration` first, or remove `testing` from experiment.yaml `stack`. (Append Variant A, recovery=`address the missing dependencies, then re-run \`/change\``.)"

The recovery wording stays visible inline; only the wrapping prose lives here.
