# STATE 1: INTERVIEW

**PRECONDITIONS:**
- Context read and summary presented (STATE 0 POSTCONDITIONS met)

**ACTIONS:**

Ask these questions **one at a time** by ending your response after each question. Wait for the user's reply before asking the next question.

**Resumption:** If interrupted mid-conversation, the user can re-run `/retro`. If the user provides answers to previous questions up front (e.g., pasting prior responses), skip those questions and continue from where they left off. If the user provides all four answers at once, skip the one-at-a-time flow entirely and proceed to STATE 2.

### Q1: Outcome
"What was the outcome of this experiment?"
- Succeeded -- hit or exceeded thesis target
- Partially succeeded -- made progress but didn't hit target
- Failed -- didn't move the metric
- Inconclusive -- not enough data or time

Follow-up: "What was the actual result vs the target in your thesis: [thesis]?"

### Q2: What worked
"What worked well? (workflow, tools, stack, anything)"

### Q3: What was painful
"What was painful, confusing, or slow?"

### Q4: What was missing
"What capability did you wish you had but didn't?"

**POSTCONDITIONS:**
- All four questions answered by the user
- Answers recorded for STATE 2

- **Write interview artifact** (`.runs/retro-interview.json`):
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  interview = {
      'questions_answered': 4,
      'answers': {}
  }
  print(json.dumps(interview))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/retro-interview.json \
    --payload "$PAYLOAD" \
    --skill retro
  ```

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/retro-interview.json')); assert d.get('questions_answered')==4, 'questions_answered=%s, expected 4' % d.get('questions_answered'); assert isinstance(d.get('answers'), dict) and len(d['answers'])>0, 'answers empty'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh retro 1
```

**NEXT:** Read [state-2-generate.md](state-2-generate.md) to continue.
