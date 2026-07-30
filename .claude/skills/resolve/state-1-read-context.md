# STATE 1: READ_CONTEXT

**PRECONDITIONS:**
- `issue_list` is populated (STATE 0 POSTCONDITIONS met)

**ACTIONS:**

- Read `CLAUDE.md`
- Read `scripts/check-inventory.md`
- For each issue in `issue_list`: read every template file mentioned in the issue body

- **Record files read** in `resolve-context.json`:
  ```bash
  PAYLOAD=$(python3 -c "
  import json, os
  ctx = json.load(open('.runs/resolve-context.json'))
  ctx['files_read'] = ['CLAUDE.md']  # always include CLAUDE.md; add all template files read
  if os.path.exists('scripts/check-inventory.md'):
      ctx['files_read'].append('scripts/check-inventory.md')
  else:
      ctx['check_inventory_absent'] = True
  print(json.dumps(ctx))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/resolve-context.json \
    --payload "$PAYLOAD" \
    --skill resolve
  ```

**POSTCONDITIONS:**
- `CLAUDE.md` and `scripts/check-inventory.md` have been read
- All template files cited in issue bodies have been read
- Their contents are in context for subsequent states
- `files_read` field persisted to `resolve-context.json`

**VERIFY:**
```bash
python3 -c "import json,os; ctx=json.load(open('.runs/resolve-context.json')); fr=ctx.get('files_read',[]); assert isinstance(fr,list) and len(fr)>0, 'files_read empty'; assert 'CLAUDE.md' in fr, 'CLAUDE.md not in files_read'; assert 'scripts/check-inventory.md' in fr or ctx.get('check_inventory_absent'), 'scripts/check-inventory.md not read and not marked absent'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh resolve 1
```

**NEXT:** Read [state-2-triage.md](state-2-triage.md) to continue.
