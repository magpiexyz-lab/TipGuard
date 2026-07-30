# STATE 1: PLAN

**PRECONDITIONS:**
- Context read (STATE 0 POSTCONDITIONS met)
- `hosting.provider`, `canonical_url`, and rollback procedure are known

**ACTIONS:**

Identify the rollback target. Present the rollback plan to the user:

```
## Rollback Plan

**Provider:** <provider>
**Target:** <canonical_url>
**Action:** <rollback command or dashboard steps from hosting stack file>

Warning: This will revert the hosting deployment only.
     Database migrations are NOT rolled back.
     Environment variable changes are NOT rolled back.

Proceed with rollback?
```

**POSTCONDITIONS:**
- Rollback plan has been presented to the user with provider, target URL, and action

- **Write plan artifact** (`.runs/rollback-plan.json`):
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  plan = {
      'provider': '<hosting provider>',
      'target_url': '<canonical url>',
      'action': '<rollback command or manual steps>'
  }
  print(json.dumps(plan))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/rollback-plan.json \
    --payload "$PAYLOAD" \
    --skill rollback
  ```

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/rollback-plan.json')); assert d.get('provider'), 'provider empty'; assert d.get('target_url'), 'target_url empty'; assert d.get('action'), 'action empty'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh rollback 1
```

**NEXT:** Read [state-2-user-approval.md](state-2-user-approval.md) to continue.
