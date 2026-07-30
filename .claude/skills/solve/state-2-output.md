# STATE 2: OUTPUT

**PRECONDITIONS:**
- Solve reasoning execution complete (STATE 1 POSTCONDITIONS met)

**ACTIONS:**

Present the output exactly as specified in solve-reasoning.md Phase 6 (full mode) or Step 5 (light mode).

### Q-score

Compute solve quality (see `.claude/patterns/skill-scoring.md`):

```bash
RUN_ID=$(python3 -c "import json; print(json.load(open('.runs/solve-context.json')).get('run_id', ''))" 2>/dev/null || echo "")
PAYLOAD=$(python3 -c "
import json, os
print(json.dumps({
    'scope': 'solve',
    'dims': {'depth': 1.0, 'output': 1.0}
}))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/q-dimensions.json \
  --payload "$PAYLOAD" \
  --skill solve || true
```

**STOP.** After presenting the output, end your response here. Do not implement anything.

The user decides next steps:
- Implement manually
- Run `/change` with the recommendation
- Ask follow-up questions
- Reject and re-run with different constraints

**POSTCONDITIONS:**
- Solution output presented to user
- No code changes made
- Q-score dimensions written to .runs/q-dimensions.json

**VERIFY:**
```bash
python3 -c "import json; st=json.load(open('.runs/solve-trace.json')); assert st.get('mode') in ('light','full'), 'mode invalid'; assert st.get('output'), 'output empty'; ctx=json.load(open('.runs/solve-context.json')); assert ctx.get('skill')=='solve' or 'solve' in ctx.get('run_id',''), 'context not for solve skill'; assert st.get('run_id')==ctx.get('run_id'), 'run_id mismatch: trace=%s context=%s' % (st.get('run_id'), ctx.get('run_id')); json.load(open('.runs/q-dimensions.json'))"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh solve 2
```

**NEXT:** Skill states complete.
