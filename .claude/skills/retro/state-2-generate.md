# STATE 2: GENERATE

**PRECONDITIONS:**
- All four questions answered (STATE 1 POSTCONDITIONS met)

**ACTIONS:**

Compile all data into a structured document with these sections:

1. **Experiment Summary** -- name, description, target user, thesis, outcome, metric results
2. **Timeline & Activity** -- commits, PRs, pages built, scope delivered vs planned
3. **Stack Used** -- from experiment.yaml `stack`
4. **Team Assessment** -- answers to Q2-Q4
5. **Template Improvement Suggestions** -- specific, actionable changes mapped to template components (e.g., "Add X to the bootstrap skill", "Change Y in CLAUDE.md Rule Z")
6. **Skill Quality Summary** -- per-skill Q-score table from `.runs/verify-history.jsonl` (if available):

   | Skill | Runs | Avg Q | Min Q | Top Rework Source |
   |-------|------|-------|-------|-------------------|

   If no Q-score data exists, note: "No Q-score data available -- Q tracking requires running /verify after /bootstrap or /change."

Show the full retro to the user before filing.

**POSTCONDITIONS:**
- Structured retro document generated with all six sections
- Retro content shown to user for review

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/retro-interview.json')); assert isinstance(d.get('answers'), dict) and len(d['answers'])>0, 'answers missing or empty'" && test -f .runs/retro-context.json
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh retro 2
```

**NEXT:** Read [state-3-file-issue.md](state-3-file-issue.md) to continue.
