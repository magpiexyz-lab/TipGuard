# TDD Cycle

> Invoked by `agents/implementer.md` and `agents/visual-implementer.md`.
> See `patterns/tdd.md` for the full TDD workflow and task granularity rules.

## 1. Read existing code

Read the target files and any files they import. Understand the current state before changing anything.

Also glob for existing test files (`**/*.test.*`, `**/*.spec.*`). If test files exist, read 1-2 to understand the project's testing patterns (assertion style, helper naming, file organization). Note the conventions already established in the codebase: function naming pattern (camelCase verbs: validate*, get*, create*), error handling pattern (throw vs return), import style (@/ alias vs relative). Match these conventions in your new code and tests.

If NO test files exist (first TDD run), use these defaults: vitest `describe`/`it`/`expect` blocks, camelCase verb prefixes for functions (validate*, get*, create*), `@/` alias imports, colocate test files next to source (`foo.ts` -> `foo.test.ts`). Read the testing stack file at `.claude/stacks/testing/<value>.md` (value from `experiment/experiment.yaml` `stack.testing`) for any framework-specific patterns (setup files, custom matchers, coverage config).

## 2. Write unit test

Write a test that defines what the code SHOULD do — per `patterns/tdd.md` section Unit Tests. Derive test cases from the task specification, not from current behavior. If behavior `tests` entries were provided in the task, generate an `it()` assertion for each entry — these are non-negotiable acceptance criteria.

## 3. RED — verify test fails

Run the test. Confirm it fails with an expected error (missing function, wrong return value, etc.).

If the test passes unexpectedly, the code already satisfies the specification. Skip to step 5.

## 4. GREEN — write minimal code

Write the minimal code to make the test pass. No more, no less.

## 5. REFACTOR — improve under green tests

Improve the code: rename, extract, simplify. Run tests after each change to confirm they still pass.

## 6. Self-review and commit

Read your own diff. Check for unintended changes, leftover debug code, or files outside task scope. Run `npm run build` to confirm zero errors.

Commit your changes — this step is **mandatory** for worktree isolation to work. The lead agent merges your worktree branch via `git merge`; if you do not commit, there is nothing to merge.

```bash
# Stage only the files you created or modified (never use git add -A)
git add <specific-file-1> <specific-file-2> ...

# Commit with imperative mood referencing the task
git commit -m "Add <short task description>"
```

Verify the commit exists: run `git log --oneline -1` and confirm your commit message appears. If `git commit` fails (e.g., nothing staged), re-check your file paths and retry.

## Bug Discovery Protocol

If a unit test reveals that existing code has a bug (test fails AND the failure shows incorrect behavior, not just missing code): fix the code to match the specification. The unit test defines correct behavior, and the code must conform.

## Key Constraints

- One task per invocation, one concern per task
- Do NOT modify files outside task scope
- Do NOT skip the RED phase (verify test fails before writing code)
- Do NOT write characterization tests (unit tests only — see `patterns/tdd.md`)
- `npm run build` MUST pass before completing
