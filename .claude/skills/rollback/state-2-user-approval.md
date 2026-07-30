# STATE 2: USER_APPROVAL

**PRECONDITIONS:**
- Plan presented (STATE 1 POSTCONDITIONS met)

**ACTIONS:**

**STOP.** End your response here. Wait for user approval before continuing.

DO NOT proceed to STATE 3 until the user explicitly replies with approval.
If the user requests changes or asks questions, address their concerns and present the plan again (return to STATE 1). Repeat until approved.

- **Record approval** in `rollback-context.json`:
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  ctx = json.load(open('.runs/rollback-context.json'))
  ctx['approved'] = True
  print(json.dumps(ctx))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/rollback-context.json \
    --payload "$PAYLOAD" \
    --skill rollback
  ```

**POSTCONDITIONS:**
- User has explicitly approved the rollback
- `approved` field set to `true` in `rollback-context.json`

**VERIFY:**
```bash
python3 -c "import json; assert json.load(open('.runs/rollback-context.json')).get('approved') == True, 'approved not set'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh rollback 2
```

**NEXT:** Read [state-3-execute.md](state-3-execute.md) to continue.
