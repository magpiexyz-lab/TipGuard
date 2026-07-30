# STATE 16: UNIT_TEST_GENERATION

**PRECONDITIONS:**
- STATE 15 POSTCONDITIONS met (scan complete, classification done)

**ACTIONS:**

Generate unit tests for CRITICAL modules using implementer agents.

**Module dependency analysis** (per `patterns/tdd.md` Task Dependency Ordering):
- For each CRITICAL module from `.runs/bootstrap-scan.json`, identify imports from other CRITICAL modules
- Order modules so dependencies are tested first (if A imports B, test B first)
- Independent modules can be in any order — place them first

**Isolation policy:** Before spawning implementer agents, determine the isolation mode:
- Check if any test files already exist under `src/` **outside the scaffold-libs domain**:
  ```bash
  find src \( -name '*.test.*' -o -name '*.spec.*' \) -not -path 'src/lib/*' | head -1
  ```
  Rationale (#1450 gap 11): scaffold-libs (state-11a) writes `src/lib/*.test.ts` BEFORE state-16 runs the first time. Without the `-not -path 'src/lib/*'` filter, those scaffold-libs tests would falsely trigger worktree mode on every clean bootstrap. Domain split:
    - **scaffold-libs domain**: `src/lib/*.test.ts` (utility unit tests written at state-11a)
    - **state-16 domain**: `src/app/api/**/*.test.ts`, `src/components/**/*.test.tsx` (route + component tests)
- **If no state-16-domain test files exist** (typical during bootstrap): use **direct mode** — agents commit directly to the feature branch without worktree isolation. This avoids unnecessary worktree overhead when there is no risk of conflicting modifications.
- **If any state-16-domain test file already exists** (atypical, possible if re-running after partial failure): use **worktree mode** — agents run in worktree isolation per the standard procedure.

**Spawn rules** (three orthogonal concerns — separated to prevent doc/execution drift, #1047):

- **Parallelism:** Implementer agents MUST NOT run in parallel. They commit to the same branch and parallel spawns cause conflicts.
- **Dependency ordering:** Respect module imports. If module A's tests import module B, B must be tested in an earlier spawn than A. Independent modules can be ordered arbitrarily.
- **Batching:** A single implementer spawn MAY cover up to 5 CRITICAL modules when ALL of the following hold: (a) the batch is a dependency-connected subset — ordering across batches still respected; (b) modules share enough structural similarity that one TDD session can reason about all of them (e.g., "three spec-builder API routes with identical mocking scaffolding"); (c) no module in the batch is complex. Prefer one-per-module for webhook handlers, payment flows, and auth mutations.

**Per-module trace contract** (non-negotiable — matches `state-11c-page-scaffold.md` precedent):

Even when batched, the implementer MUST write one trace file per module:
`.runs/agent-traces/implementer-<module-name>.json`. The `modules_completed` array in
`.runs/bootstrap-modules-trace.json` still holds one entry per CRITICAL module.
Batching reduces spawn count, not observability — the merge script and post-fan-out
verification depend on per-module traces.

For each CRITICAL module (or batch) **in dependency order, never in parallel**:
  a. Spawn implementer agent (`agents/implementer.md`; include `isolation: "worktree"` for worktree mode, omit for direct mode). When batching, include the full list of module names in the agent prompt.
  b. Pass to implementer: file paths for every module in this spawn, each module's behaviors from experiment.yaml (behavior IDs and `tests` entries), and the classification reason. If direct mode: also pass "You are running without worktree isolation. Commit directly to the current branch. Write one trace per module as `.runs/agent-traces/implementer-<module-name>.json`." ALWAYS pass: **"Generated test files MUST pass `npm run lint` with zero `@typescript-eslint/no-unused-vars` errors. Import only symbols that are referenced in assertions. If you want compile-time coverage of all typed wrappers in a file (common for `src/lib/events.test.ts`), add a single `_coverageCheck()` function that calls each wrapper once with a representative payload — this keeps every import referenced without polluting the test bodies. The lint-clean requirement applies to every file you create, including `events.test.ts` and `rate-limit.test.ts`."**
  c. Implementer writes unit tests per `patterns/tdd.md`:
     - What SHOULD the module do? (from behaviors + code reading)
     - Write tests for correct behavior
     - If test fails AND failure shows incorrect behavior → fix the code (bug discovery)
     - If test passes → specification captured
  d. **Verification (mode-dependent):**

     *Worktree mode:*
     - Verify implementer committed: `git log --oneline main..<worktree-branch>`
     - If no commit: re-spawn agent for commit-only (do NOT commit on behalf of the agent). Budget: 1 retry.
     - Merge: `git merge <worktree-branch> --no-ff -m "Merge unit tests: <module-or-batch-name>"`
     - Verify merge: `git log --oneline -1` must show merge commit

     *Direct mode:*
     - Verify each module in this spawn was committed. For each module, run `git log --oneline -- <module-test-file>` and confirm at least one commit exists covering that test file. A single commit may cover multiple batched modules (squashed commits are acceptable) — do NOT use `git log -1` as a per-module check when batching.
     - If a module's test file has no commit: re-spawn agent for commit-only. Budget: 1 retry per missing module.
     - For every module in this spawn, lead writes `.runs/agent-traces/implementer-<module-name>.json` if the agent did not (one trace file per module, per the contract above).

  e. Run `npm run build` — if broken, fix before next spawn
  e2. Run `npm run lint` — if any `@typescript-eslint/no-unused-vars` errors appear in test files written by this implementer, re-spawn for a cleanup round (budget: 1 retry) with the unused-import error text in the prompt. Generated tests must ship lint-clean so the first `/verify` build-lint retry budget is not spent on mechanical unused-import errors (#962).
  f. Log one line per module (even when batched): "Module [name]: N tests added, all passing, lint clean"

- **Write modules trace artifact** (`.runs/bootstrap-modules-trace.json`):
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  trace = {
      'modules_completed': [
          {'name': '<module>', 'tests_added': 0, 'status': 'pass'}
      ],
      'build_passing': True
  }
  print(json.dumps(trace))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/bootstrap-modules-trace.json \
    --payload "$PAYLOAD" \
    --skill bootstrap
  ```

Check off in `.runs/current-plan.md`: `- [x] Unit test generation (state 16)` (#1118)

**POSTCONDITIONS:**
- All CRITICAL modules have unit tests
- All tests pass
- `npm run build` passes
- `.runs/bootstrap-modules-trace.json` exists

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/bootstrap-modules-trace.json')); s=json.load(open('.runs/bootstrap-scan.json')); c=s.get('critical',[]); m=d.get('modules_completed',[]); assert len(m)==len(c), 'count: %d completed vs %d critical'%(len(m),len(c)); assert set(x['name'] for x in m)==set(x['module'] for x in c), 'module name mismatch'; assert all(x.get('tests_added',0)>=1 for x in m), 'module with 0 tests_added'; assert d.get('build_passing') is True, 'build not passing'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh bootstrap 16
```

**NEXT:** Read [state-17-persist-on-touch.md](state-17-persist-on-touch.md) to continue.
