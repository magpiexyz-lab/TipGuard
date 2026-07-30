# STATE 1: BASELINE_VALIDATORS

**PRECONDITIONS:**
- Context loaded (STATE 0 POSTCONDITIONS met)

**ACTIONS:**

- Run all 4 validators, capture total error count as `baseline_errors`:
  - `python3 scripts/validate-frontmatter.py`
  - `python3 scripts/validate-semantics.py`
  - `bash scripts/consistency-check.sh`
  - `shellcheck --exclude=SC2154,SC2086,SC2059,SC1091 .claude/hooks/*.sh`
- If a script fails to run (missing python3/pyyaml/shellcheck): stop and tell the user

- **Compute `health_clean`** (boolean):
  - `baseline_errors == 0` (all validators pass)
  - AND no rows under `## Pending` in `scripts/check-inventory.md` (grep for non-empty rows after that heading)
  - AND no `TODO` strings in `.claude/commands/*.md` or `.claude/stacks/**/*.md`

  If `health_clean == true`:
  - Set `max_iterations = 3`, `max_findings_per_dimension = 3`
  - Log: "Template health: clean — using light review parameters (3 iterations, 3 findings/dimension)"

  If `health_clean == false`:
  - Set `max_iterations = 5`, `max_findings_per_dimension = 5`
  - Log: "Template health: needs attention — using full review parameters"

- **Cross-run convergence check** (only when `health_clean == true` AND `prior_precision` is available from STATE 0):
  Extract `findings_fixed` and `disputed_rate` from `prior_precision`.
  If `findings_fixed <= 3 AND disputed_rate >= 40%`:
  - STOP and present to user:
    > "Template appears converged — prior review fixed only N findings with M% dispute rate. Run /review again? (y/n)"
  - If user says **no** -> set `max_iterations = 0` (skip loop entirely, proceed through states 3-6 to exit cleanly). Log: "Template health: converged — skipping review loop per user decision"
  - If user says **yes** -> set `max_iterations = 2`, `max_findings_per_dimension = 2`. Log: "Template health: converged — using minimal review parameters (2 iterations, 2 findings/dimension)"

**POSTCONDITIONS:**
- `baseline_errors` captured
- `health_clean` computed
- `max_iterations` and `max_findings_per_dimension` set
- All 4 validators ran successfully (or user notified of missing tools)

- **Write baseline artifact** (`.runs/review-baseline.json`):
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  baseline = {
      'baseline_errors': 0,
      'health_clean': True,
      'converged': False,
      'max_iterations': 3,
      'max_findings_per_dimension': 3
  }
  print(json.dumps(baseline))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/review-baseline.json \
    --payload "$PAYLOAD" \
    --skill review
  ```

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/review-baseline.json')); assert isinstance(d.get('baseline_errors'), int) and d['baseline_errors']>=0, 'baseline_errors not valid'; assert isinstance(d.get('health_clean'), bool), 'health_clean not bool'; mi=d.get('max_iterations'); assert isinstance(mi, int) and mi>=0, 'max_iterations invalid'; mf=d.get('max_findings_per_dimension'); assert isinstance(mf, int) and mf>=0, 'max_findings_per_dimension invalid'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh review 1
```

**NEXT:** Read [state-2a-review-scan.md](state-2a-review-scan.md) to begin the Review-Fix Loop.

Initialize before the first iteration:
- `seen_findings` = empty set
- `iteration` = 1
- `yield_history` = empty list

The Review-Fix Loop runs **2 to `max_iterations`** iterations, terminating based on
convergence (see Loop Gate in state-2f). Within-iteration early exits:
- State 2b produces 0 remaining findings -> exit loop
- State 2e: no fixes succeeded this iteration -> exit loop

Completing fixes does NOT justify exiting early — fixes may introduce
new issues that only a fresh scan can detect.
