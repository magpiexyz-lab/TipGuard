# STATE 2f: LOOP_GATE

**PRECONDITIONS:**
- Fixes applied (STATE 2e POSTCONDITIONS met)

**ACTIONS:**

Emit a compact state summary and discard prior detail:

```
## Iteration N complete
- seen_findings: [list of all finding signatures across all iterations]
- error_count: [current validator error count]
- files_modified: [list of files changed so far]
- fixes_applied: N, reverted: M, skipped: K
- checks_added: [list of new validator checks, or "none"]
- adversarial_validation: confirmed: N, disputed: M, needs-evidence: K
- disputed_findings: [list of disputed finding signatures + one-line rationale]
- finding_fates: [{signature, dimension, adversarial_label, fate}]
- yield_rate: <fixed_count / (confirmed + needs-evidence count)>
- yield_by_dimension: { A: <fixed/actionable>, B: <fixed/actionable>, C: <fixed/actionable> }
- confirmed_findings_this_iteration: <count of confirmed findings in this iteration>
- error_delta: <current error_count - prior iteration error_count>
```

This summary is the only carry-forward state needed. Prior subagent results,
file reads, and validator outputs from this iteration are no longer needed and
can be safely compressed.

**MANDATORY LOOP GATE — evaluate before proceeding:**

Compute this iteration's yield rate:
- `yield` = (findings fixed this iteration) / (confirmed + needs-evidence this iteration)
- Disputed findings are excluded from the denominator — they are adversarial successes, not signal failures
- If denominator is 0, yield = 0
- Append yield to `yield_history`

Termination decision (evaluate in order — first match wins):

1. **Minimum floor**: `iteration` < 2 -> increment `iteration`, go to 2a NOW.
   (A single scan is never sufficient — fixes may introduce new issues.)
   Exception: if `iteration` == 1 AND 0 findings were reported -> proceed to State 3.
   (Template is clean; a second empty scan adds no value.)

2. **Zero yield**: yield = 0 and no findings were fixed -> proceed to State 3.

3. **Regression trend**: `iteration` >= 2 and `error_delta` > 0 for 2 consecutive
   iterations -> proceed to State 3.
   (Error count rising across iterations signals cascading fix regressions.)

4. **Diminishing returns**: `iteration` >= 3 and `confirmed_findings_this_iteration` <= 1
   -> proceed to State 3.
   (Template converging — agents finding at most 1 new confirmed issue per scan.)

5. **Hard cap**: `iteration` >= `max_iterations` -> proceed to State 3.

6. **Continue**: increment `iteration`, **go to 2a NOW**. Fixes from this
   iteration may have introduced new issues.

State which condition triggered your decision before proceeding.

- **Extend loop decision artifact** (`.runs/review-loop-decision.json`):
  STATE 2e wrote the per-batch fields (`fixes_succeeded`, `fixes_reverted`,
  `fixes_skipped`, `exit_reason`). STATE 2f reads that file and extends it
  with iteration/yield/termination fields. **Use `d.update({...})`, not full
  overwrite** — overwriting would silently drop 2e's fields and break the
  state-2e VERIFY contract.
  ```bash
  python3 - <<'PYEOF'
  import json, os
  p = '.runs/review-loop-decision.json'
  d = json.load(open(p)) if os.path.isfile(p) else {}   # tolerate 2e being skipped
  d.update({
      'iteration': 0,                              # <int — current iteration number>
      'yield_rate': 0.0,                           # <float — yield this iteration>
      'termination_condition': '<which rule>',     # <"minimum_floor"|"zero_yield"|"regression_trend"|"diminishing_returns"|"hard_cap"|"continue">
      'continue': False                            # <bool — True if loop continues, False if exiting>
  })
  json.dump(d, open(p, 'w'), indent=2)
  PYEOF
  ```

**POSTCONDITIONS:**
- Compact state summary emitted
- Termination decision made and stated with triggering condition
- `.runs/review-loop-decision.json` exists with both 2e fields preserved AND 2f fields added

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/review-loop-decision.json')); assert 'fixes_succeeded' in d and 'exit_reason' in d, '2e fields lost in 2f overwrite'; assert isinstance(d.get('iteration'), int) and d['iteration']>=1, 'iteration missing or <1'; assert isinstance(d.get('yield_rate'), (int, float)), 'yield_rate missing or not numeric'; assert d.get('termination_condition'), 'termination_condition empty'; assert isinstance(d.get('continue'), bool), 'continue missing or not bool'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh review 2f
```

**NEXT:** If continuing loop, read [state-2a-review-scan.md](state-2a-review-scan.md). If exiting loop, read [state-3-update-inventory.md](state-3-update-inventory.md).
