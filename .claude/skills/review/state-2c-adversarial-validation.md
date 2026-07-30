# STATE 2c: ADVERSARIAL_VALIDATION

**PRECONDITIONS:**
- Filtered findings available (STATE 2b POSTCONDITIONS met, with > 0 remaining findings)

**ACTIONS:**

Spawn the `review-challenger` Named agent (`subagent_type: review-challenger`).

Pass in the agent prompt:
- All filtered findings from state 2b (full Finding Format)
- The `observation_backlog` from State 0 (if non-empty)

The agent definition at `.claude/agents/review-challenger.md` contains the full
counterexample construction protocol (Dimensions A, B, C + auto-confirm rule).

After the agent returns:
1. Read the agent's trace at `.runs/agent-traces/review-challenger.json`
2. For each finding, transcribe the trace's `verdicts[i].label` to `agent_classification`
3. Set `final_classification = agent_classification` by default
4. If overriding (setting a different `final_classification`), record the rationale

When any `agent_classification != final_classification`, display both classifications
and the rationale at the STOP gate.

Partition findings:
- **confirmed**: full priority in fix phase
- **needs-evidence**: lower priority (sorted after confirmed in fix queue)
- **disputed**: removed from fix queue; record finding signature + one-line rationale for the PR body
- If 0 findings remain after removing disputed -> continue to 2d (the existing 2b exit handles the zero-findings case)

- **Write adversarial artifact** (`.runs/review-adversarial.json`):
  ```bash
  python3 -c "
  import json
  adversarial = {
      'confirmed': [
          # Per-item objects with provenance:
          # {'finding': '<title>', 'agent_classification': 'confirmed', 'final_classification': 'confirmed'}
      ],
      'disputed': [
          # {'finding': '<title>', 'agent_classification': 'disputed', 'final_classification': 'disputed', 'rationale': '<text>'}
      ],
      'needs_evidence': [
          # {'finding': '<title>', 'agent_classification': 'needs-evidence', 'final_classification': 'needs-evidence'}
      ]
  }
  json.dump(adversarial, open('.runs/review-adversarial.json', 'w'), indent=2)
  "
  ```

**POSTCONDITIONS:**
- Each finding labeled: confirmed, disputed, or needs-evidence
- Fix queue ordered: confirmed (by severity), then needs-evidence (by severity)
- Disputed findings recorded with rationale
- `.runs/review-adversarial.json` exists

**VERIFY:**
```bash
python3 .claude/scripts/verify-review-adversarial.py  # review-adversarial.json, review-challenger.json
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh review 2c
```

**NEXT:** Read [state-2d-branch-setup.md](state-2d-branch-setup.md) to continue.
