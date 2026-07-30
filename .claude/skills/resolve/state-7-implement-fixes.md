# STATE 7: IMPLEMENT_FIXES

**PRECONDITIONS:**
- On `fix/resolve-*` branch (STATE 6 POSTCONDITIONS met)

**ACTIONS:**

For each issue in severity order (HIGH first):

0. **Present fix summary and wait for approval:**
   Before implementing, present a brief explanation to the user:
   ```
   **Fix for #<N>: <title>**
   - Root cause: <1 sentence>
   - What changes: <files and what's modified, 1-2 bullets>
   - Risk: <low/medium — blast radius summary>
   ```
   **Learned pattern basis (advisory — only when `pattern_hints` non-empty):**
   If `.runs/resolve-triage.json.pattern_hints` has entries matching this issue,
   append a short block listing each hint's `id`, `maturity`, `confidence_score`,
   and a one-line pointer to `fix_template`. Example:
   ```
   #### Learned pattern basis
   - nextjs-demo-guard (canonical, confidence 1.0) — fix_template: add VERCEL guard before DEMO_MODE check
   ```
   This is purely informational — it does NOT change the approval flow below.
   **STOP. Wait for the user to approve this fix before implementing.**
   If the user rejects a fix, move to the next issue. The `rejected_issues`
   field written at the end of this state preserves the audit trail in
   `resolve-context.json`; do NOT write to `.runs/fix-log.md` directly
   (AOC v1 R2 — `aoc-fix-ledger-ownership` allows only canonical writers).

1. Implement the fix per the approved fix plan from Step 5
1.4. **Post-fix guard execution** (Falsification Gate — only when
    `prevention_analysis.problem_type == "defect"` in `.runs/solve-trace.json`):
    Read `prevention_analysis.recurrence_guard.kind` and `.artifact` for the
    current fix/cluster, then run the appropriate check:

    - `kind ∈ {test, hook, invariant}` → execute the guard at the artifact
      path. Assert it reports green (the fix should have made it pass).
      If it fails red → fix introduced regression beyond stated symptom →
      revert via Step 4's existing `git checkout --` mechanism; log as
      "falsification-failed" in the fix-ledger description.
    - `kind == "lint"` → run the lint rule against the changed files:
      ```bash
      bash .claude/scripts/verify-linter.sh --json \
        --cache .runs/.linter-cache --rules <artifact>
      ```
      Assert exit 0 (zero hits on post-fix state). If hits → revert.
    - `kind == "none"` → no executable step here; the textual falsification
      block was already validated at STATE 5 VERIFY (Falsification Gate)
      and challenged by solve-critic vector 7 in STATE 5d.

    Append per-fix result to `.runs/resolve-falsification.json` via
    `write-gate-artifact.sh`:
    ```json
    {"issue": <N>, "kind": "<...>", "artifact": "<...>",
     "post_fix_green": true, "executed_at": "<iso>"}
    ```

    Backward compat: silently skip this step when `falsification` block is
    absent from solve-trace.json (covers soak-window runs and non-defect
    fixes). Once soak closes, missing falsification is caught upstream by
    STATE 5 VERIFY.

1b. After each fix, log it via the canonical writer (AOC v1 R2):
    ```bash
    python3 .claude/scripts/write-fix-ledger.py --lead-fix --skill resolve \
      --fix-json '{"file":"<path>","symptom":"<one-line symptom>","fix":"<one-line description of what was fixed and why>"}'
    ```
    The renderer (`render-fix-log.py`) regenerates `.runs/fix-log.md` from
    the populated ledger during the skill epilogue's observation detection
    in Step 11, so lead-fix entries survive. Do NOT write to
    `.runs/fix-log.md` directly — `aoc-fix-ledger-ownership` blocks at
    runtime via `fix-ledger-write-guard.sh` and statically via the
    coherence rule.
2. If a validator check was proposed: implement it in the target script
2b. If the bug involves a configuration not covered by existing test
    fixtures (identified in Step 5b or by checking `tests/fixtures/`):
    create a minimal fixture following existing naming conventions.
    Include only the stack/archetype config needed to trigger the bug
    pattern, with assertions that catch it. Skip if triggering config
    is already covered.
3b. **Record fixture evaluation** in `resolve-context.json`:
    Set `fixtures_evaluated` to a list of fixture files checked from `tests/fixtures/`,
    or `["not_needed: <reason>"]` if no fixture is applicable for this fix.
    ```bash
    PAYLOAD=$(python3 -c "
    import json
    ctx = json.load(open('.runs/resolve-context.json'))
    ctx['fixtures_evaluated'] = []  # list of fixture files checked, or ['not_needed: <reason>']
    print(json.dumps(ctx))
    ")
    bash .claude/scripts/lib/write-gate-artifact.sh \
      --path .runs/resolve-context.json \
      --payload "$PAYLOAD" \
      --skill resolve
    ```
3c. Run all 3 validators:
   - `python3 scripts/validate-frontmatter.py`
   - `python3 scripts/validate-semantics.py`
   - `bash scripts/consistency-check.sh`
4. If error count increased vs pre-fix count -> revert with
   `git checkout -- <modified files>`, log as "reverted", move to next issue
5. If error count same or decreased -> keep the fix

If new validator checks were added:
- Update `scripts/check-inventory.md` (add to appropriate table, update counts)

**After all fixes have been processed:**
- Record rejected issue numbers in `resolve-context.json`:
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  ctx = json.load(open('.runs/resolve-context.json'))
  ctx['rejected_issues'] = []  # list of issue numbers rejected by user (empty if none)
  print(json.dumps(ctx))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/resolve-context.json \
    --payload "$PAYLOAD" \
    --skill resolve
  ```
- If ALL fixes were rejected (no changes in git working tree):
  1. Report: "All fixes were rejected — no changes to commit. Issues remain open."
  2. Write the no-fixes marker to resolve-context.json so VERIFY recognises the
     legitimate early-exit path (registry declares
     `allows_early_exit_when: "all_fixes_rejected"`):
     ```bash
     PAYLOAD=$(python3 -c "
     import json
     ctx = json.load(open('.runs/resolve-context.json'))
     ctx['all_fixes_rejected'] = True
     if ctx.get('fixtures_evaluated') is None:
         ctx['fixtures_evaluated'] = ['not_needed: all_fixes_rejected']
     print(json.dumps(ctx))
     ")
     bash .claude/scripts/lib/write-gate-artifact.sh \
       --path .runs/resolve-context.json \
       --payload "$PAYLOAD" \
       --skill resolve
     ```
  3. Advance state and **TERMINAL** — skill ends, no PR created.

**POSTCONDITIONS:**
- All approved fixes implemented (or reverted with logged reason)
- Validator error count has not increased vs `pre_fix_baseline`
- `check-inventory.md` updated if new checks were added
- `rejected_issues` recorded in `resolve-context.json`
- Git working tree has changes (fixes applied) — unless all-rejected TERMINAL

**VERIFY:**
```bash
python3 -c "import json,subprocess; ctx=json.load(open('.runs/resolve-context.json')); has_diff=bool(subprocess.run(['git','diff','--name-only','HEAD'],capture_output=True,text=True).stdout.strip() or subprocess.run(['git','diff','--cached','--name-only'],capture_output=True,text=True).stdout.strip()); all_rejected=ctx.get('all_fixes_rejected') is True; assert has_diff or all_rejected, 'no diff and no all_fixes_rejected marker in resolve-context.json'; fe=ctx.get('fixtures_evaluated'); assert fe is not None, 'fixtures_evaluated missing from resolve-context.json'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh resolve 7
```

**NEXT:** Read [state-8-final-validation.md](state-8-final-validation.md) to continue.
