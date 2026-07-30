# STATE 5: E2E_TESTS

**PRECONDITIONS:** STATE 4 complete (or skipped for visual/build scope).

**ACTIONS:**

- If `stack.testing` is NOT present in experiment.yaml → write `.runs/e2e-result.json`:
  ```bash
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/e2e-result.json \
    --payload '{"skipped":true,"reason":"no testing stack"}' \
    --skill verify
  ```
  Skip to STATE 7a.

- If `stack.testing` is present but no test configuration file exists → write `.runs/e2e-result.json`:
  ```bash
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/e2e-result.json \
    --payload '{"skipped":true,"reason":"no test configuration"}' \
    --skill verify
  ```
  Skip to STATE 7a.

- Otherwise: run tests with precondition separation.

  **Determine test runner** from `stack.testing` in experiment.yaml:
  - `playwright` → list command: `npx playwright test --list`, run command: `npx playwright test`
  - `vitest` → list command: `npx vitest list`, run command: `npx vitest run`
  - If the value is absent or not one of {playwright, vitest} → write `.runs/e2e-result.json`:
    ```bash
    bash .claude/scripts/lib/write-gate-artifact.sh \
      --path .runs/e2e-result.json \
      --payload '{"skipped":true,"reason":"unrecognized test runner"}' \
      --skill verify
    ```
    Skip to STATE 7a.

  **Phase A: Config validation (max 2 attempts, NOT counted against test budget)**

  1. Run: `timeout 30 <list command> 2>&1`
  2. If list succeeds (exit 0, lists test names): proceed to Phase B.
  3. If config error (output contains `Cannot find module`, `config`, `Error`, or runner-specific errors like `browserType`/`chromium` for playwright):
     - These are infrastructure issues, not test failures.
     - Fix the config error (e.g., install missing browser for playwright, fix config path).
     - Record the fix via the AOC v1.1 lead-fix path:
       ```bash
       python3 .claude/scripts/write-fix-ledger.py --lead-fix --skill verify \
         --fix-json '{"file":"<config-file>","symptom":"e2e-config error: <reason>","fix":"<what changed>"}'
       ```
     - Re-run list command (max 2 config-fix attempts total).
  4. If test file error (syntax errors in test files, missing imports in tests): proceed to Phase B — these count against the test budget.
  5. If config errors persist after 2 attempts, write `.runs/e2e-result.json` and record a WARN-severity ledger entry:
     ```bash
     bash .claude/scripts/lib/write-gate-artifact.sh \
       --path .runs/e2e-result.json \
       --payload '{"passed":false,"attempts":0,"config_error":true,"reason":"test config broken after 2 fix attempts"}' \
       --skill verify
     python3 .claude/scripts/write-fix-ledger.py --lead-fix --skill verify --severity warn \
       --fix-json '{"file":"<config-file>","symptom":"e2e infrastructure broken after 2 fix attempts","fix":"flagged in verify report; tests NOT executed"}'
     ```
     **Important:** STATE 7 (WRITE_REPORT) must check for `config_error` in `e2e-result.json` and set `hard_gate_failure: true` when present — a passing report with untested code violates Rule 5 (Deploy-Ready).
     Skip to STATE 7a.

  **Phase B: Test execution (3-attempt budget, starts ONLY after list succeeds)**

  For each failed attempt:
  1. Read test output, identify failures
  2. Fix issues (test code or app code)
  3. Record each fix via the AOC v1.1 lead-fix path:
     ```bash
     python3 .claude/scripts/write-fix-ledger.py --lead-fix --skill verify \
       --fix-json '{"file":"<file>","symptom":"e2e test failure: <reason>","fix":"<what changed>"}'
     ```
  4. Re-run tests using the run command determined above

  After tests pass (or 3-attempt budget exhausted), write `.runs/e2e-result.json`:
  ```bash
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/e2e-result.json \
    --payload '{"passed":<true|false>,"attempts":<N>,"fixes":<N>,"config_attempts":<CA>}' \
    --skill verify
  ```

  **Phase C: Unit tests (co-installed vitest)**

  If the primary test runner is NOT vitest (e.g., `playwright`) AND a `vitest.config.ts` file exists on disk:

  1. Run: `npx vitest run`
  2. If vitest passes: update `.runs/e2e-result.json` to include `"spec_passed": true`
  3. If vitest fails: apply the same 3-attempt fix budget as Phase B (independent budget). After each fix, record via the AOC v1.1 lead-fix path:
     ```bash
     python3 .claude/scripts/write-fix-ledger.py --lead-fix --skill verify \
       --fix-json '{"file":"<file>","symptom":"spec test failure: <reason>","fix":"<what changed>"}'
     ```
     Update `.runs/e2e-result.json` to include `"spec_passed": <true|false>, "spec_attempts": <N>`.
  4. If no `vitest.config.ts` exists, skip Phase C (vitest was not co-installed)

**POSTCONDITIONS:** `e2e-result.json` exists.

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/e2e-result.json')); assert d.get('skipped') is True or d.get('passed') is not None, 'neither skipped nor passed field present'; assert d.get('skipped') or isinstance(d.get('attempts'), int), 'not skipped but attempts missing'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh verify 5
```

**NEXT:** Read [state-7a-write-report.md](state-7a-write-report.md) to continue.
