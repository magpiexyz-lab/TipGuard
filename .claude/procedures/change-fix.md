# /change: Fix Implementation

> Invoked by change.md Step 6 when type is Fix.
> Read the full change skill at `.claude/commands/change.md` for lifecycle context.

## Prerequisites from change.md

- experiment.yaml and experiment/EVENTS.yaml have been read (Step 2)
- Change classified as Fix (Step 3)
- Preconditions checked (Step 4)
- Plan approved (Phase 1)
- Specs updated (Step 5)

## Implementation

1. **ON-TOUCH check** -- follow `patterns/on-touch-check.md` for files affected by the fix. Write unit tests BEFORE the fix.
2. Generate TDD task: regression test demonstrating the bug + minimal fix, per `patterns/tdd.md` § Regression Tests
3. Spawn implementer agent (`agents/implementer.md`, isolation: "worktree") → regression test (RED, fails on current code) → fix root cause (GREEN, minimal change) → commit
4. Write implementer trace based on Output Contract (same procedure as `change-feature.md` step 6)
5. **Merge worktree changes with verification** -- follow `procedures/worktree-merge-verification.md`.
6. Continue to Step 7
- Make the minimal change needed — smaller diffs are easier to review
- Fix only the root cause, no refactoring of surrounding code
- If the fix touches auth or payment code: add or update a test (see `patterns/tdd.md`)
- Check that analytics events on modified pages are still intact
