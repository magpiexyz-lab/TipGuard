# Test-Driven Development Procedure

Follow this procedure when implementing features or fixes.

> **Scope:** This pattern is consumed by the implementer agent (`agents/implementer.md`).

## Red-Green-Refactor Cycle

For every task:

1. **RED** — Write a failing unit test that defines what the code SHOULD do.
   Run the test. Confirm it fails with the expected error.
2. **GREEN** — Write the minimal code to make the test pass. No more, no less.
3. **REFACTOR** — Improve the code under green tests. Rename, extract, simplify.
   Run the test after each change to confirm it still passes.
4. **COMMIT** — Stage and commit your changes. This is mandatory for worktree merge.
   ```bash
   git add <specific-files>
   git commit -m "Add <feature-or-fix-description>"
   ```
   Verify: `git log --oneline -1` must show your commit. If nothing was staged, re-check file paths.

Never skip the RED phase. If the test passes immediately, the code already
satisfies the specification — skip to REFACTOR and move on.

## Unit Tests

Unit tests are the primary approach in production mode. They define
what the code SHOULD do, not what it currently DOES.

- Derive test cases from experiment.yaml `behaviors`, `golden_path`, and behaviors with `actor: system/cron`
- **Use `behavior.tests` entries as required assertions**: each entry in a behavior's `tests` array becomes an `it()` assertion in the unit test. These are the acceptance criteria — every entry must have a corresponding test.
- Each test asserts correct behavior for a specific input/scenario
- If code fails a unit test, that is a real bug — fix the code
- Do NOT write characterization tests (tests that merely snapshot current behavior)

Example:

```typescript
// Unit test: defines CORRECT behavior
expect(validateEmail("bad@@email")).toBe(false);
expect(validateEmail("user@example.com")).toBe(true);

// NOT a characterization test like:
// expect(validateEmail("bad@@email")).toBe(getCurrentResult("bad@@email"));
```

## Regression Tests

Use regression tests for bug fixes. They are distinct from unit tests.

1. Write a test that demonstrates the bug (fails on the current code)
2. Fix the code
3. Confirm the test passes

The test documents the specific failure case so it cannot recur. Label regression
tests clearly (e.g., `it("should not crash when input is empty — regression #42")`).

## Task Granularity

Each TDD task must be small and self-contained:

- **Duration:** 2-5 minutes of work
- **Scope:** One concern per task (do not mix auth + payment in one task)
- **Precision:** Exact file paths to create or modify
- **Clarity:** Expected test code, expected failure message, minimal implementation

Bad task: "Add user authentication"
Good task: "Add `validatePassword` in `src/lib/auth.ts` — unit test: rejects
passwords shorter than 8 characters, accepts valid passwords. Expected failure:
`validatePassword is not a function`."

## Task Dependency Ordering

Before spawning implementer agents, analyze the dependency graph:

1. List all tasks and their file inputs/outputs
2. Identify dependencies: Task B imports from Task A's output
3. Group tasks:
   - **Independent tasks** (no shared dependencies) — run in parallel
   - **Dependent tasks** (B requires A's output) — run sequentially (A before B)
4. Document: "N tasks total, M parallel / K sequential"

Example:
```
Task 1: Create src/lib/validators.ts (no deps)        — parallel group A
Task 2: Create src/lib/auth.ts (no deps)               — parallel group A
Task 3: Create src/app/api/signup/route.ts (imports 1+2) — sequential after A
→ 3 tasks total, 2 parallel / 1 sequential
```

### Sequential Execution Protocol

When tasks are dependent (B requires A's output):

1. Spawn Task A (worktree) — A completes RED→GREEN→REFACTOR and commits
2. After A's worktree merges back: verify A's output files exist on the feature branch
   (`git show HEAD:<path>` for each file Task B imports). If missing, the merge failed — investigate before proceeding.
3. Spawn Task B (worktree) — B's worktree forks from the updated feature branch and can read A's committed output
4. Repeat for further dependencies in the chain

Independent tasks in the same parallel group merge simultaneously after all complete.
Do NOT spawn a dependent task until its prerequisites are merged and verified.

## Test Type Selection

| Scenario | Test Type | Workflow |
|----------|-----------|----------|
| New feature | Specification (TDD) | RED — GREEN — REFACTOR |
| Existing module needing tests | Unit | Write unit test — may fail — fix code |
| Bug fix | Regression | Write test demonstrating bug — fix — pass |
| Refactoring | Existing tests | Refactor under green tests only |

- **New feature:** No code exists yet. Write the unit test first, then the code.
- **Existing module:** Code exists but lacks tests. Write unit tests for what it SHOULD do.
  If the test fails, the code has a bug — fix it.
- **Bug fix:** A specific failure is known. Write a regression test, then fix.
- **Refactoring:** Tests already pass. Change structure without changing behavior.

## What NOT to Test

Skip tests for:

- UI rendering and layout (visual review covers this)
- Static content (copy, labels, placeholder text)
- Framework boilerplate (routing config, middleware wiring, provider setup)
- Third-party library behavior (trust the library)

**Classification rule:** When a file falls into BOTH a skip category AND a
must-test category, the must-test category wins. Route handlers that perform
input validation, data mutations, authorization checks, or return domain-specific
error responses are NOT "framework boilerplate" regardless of how thin the handler
appears. Only pure pass-through wiring with zero logic (e.g., re-export, middleware
registration order) qualifies as framework boilerplate.

Test only:

- Business logic (calculations, state machines, multi-step workflows)
- Authentication and authorization
- Payment flows
- Data mutations (create, update, delete)
- API contracts (request/response shapes, status codes, error handling)
