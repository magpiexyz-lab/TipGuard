# STATE 4: FINAL_VALIDATION

**PRECONDITIONS:**
- Inventory updated (STATE 3 POSTCONDITIONS met)

**ACTIONS:**

- Run all 3 validators
- Record `final_errors`
- If `final_errors` > `baseline_errors` -> stop and report regression
- Write `.runs/review-complete.json` (required by verify-pr-gate.sh for PR creation):
  ```bash
  PAYLOAD=$(BRANCH="$(git branch --show-current)" TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)" python3 -c "
  import json, os
  print(json.dumps({
      'branch': os.environ['BRANCH'],
      'timestamp': os.environ['TIMESTAMP'],
      'iterations': '<iteration count>',
      'yield': '<overall yield rate>',
      'baseline_errors': '<baseline_errors>',
      'final_errors': '<final_errors>',
      'findings_fixed': '<total fixed across all iterations>',
      'findings_disputed': '<total disputed across all iterations>',
  }))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/review-complete.json \
    --payload "$PAYLOAD" \
    --skill review
  ```

**POSTCONDITIONS:**
- All 3 validators ran
- `final_errors` <= `baseline_errors` (no regression)
- `.runs/review-complete.json` written

**VERIFY:**
```bash
test -f .runs/review-complete.json && python3 -c "import json; d=json.load(open('.runs/review-complete.json')); assert 'final_errors' in d and 'baseline_errors' in d, 'required fields missing'; assert isinstance(d['final_errors'], int) and isinstance(d['baseline_errors'], int), 'final_errors/baseline_errors must be int'; assert d['final_errors'] <= d['baseline_errors'], 'final_errors %d > baseline_errors %d (no regression allowed)' % (d['final_errors'], d['baseline_errors'])"
```

> **VERIFY rationale:** ACTIONS allow `final_errors <= baseline_errors` (some
> validators have non-zero baselines on legacy projects). The previous VERIFY
> re-ran the 3 validators and demanded all exit 0, which contradicted ACTIONS
> on baseline-error projects. The new VERIFY reads the artifact and asserts
> non-regression, matching ACTIONS intent (verify_semantics: no_regression_from_baseline).

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh review 4
```

**NEXT:** Read [state-6-commit-pr.md](state-6-commit-pr.md) to continue.
