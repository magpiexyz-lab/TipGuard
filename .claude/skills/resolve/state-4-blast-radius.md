# STATE 4: BLAST_RADIUS

**PRECONDITIONS:**
- Reproduction complete (STATE 3 POSTCONDITIONS met)

**ACTIONS:**

The bug pattern found in Step 3 may exist in other template files:

1. Identify the pattern that caused the issue (e.g., missing archetype check,
   hardcoded path, missing conditional)
2. Grep all template files for the same pattern:
   ```bash
   # Search commands, stacks, patterns, procedures, agents
   rg "<pattern>" .claude/ scripts/ Makefile CLAUDE.md
   ```
3. For each match: evaluate whether it has the same bug. Record matches as
   `blast_radius` string entries in `file:line:classification` format
   (classification is `confirmed` or `potential`)

- **Record blast radius** in `resolve-context.json`:
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  ctx = json.load(open('.runs/resolve-context.json'))
  ctx['blast_radius'] = [
      '<file>:<line>:confirmed',
      '<file>:<line>:potential'
  ]
  print(json.dumps(ctx))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/resolve-context.json \
    --payload "$PAYLOAD" \
    --skill resolve
  ```

**POSTCONDITIONS:**
- `blast_radius` list exists in resolve-context.json
- Each entry is a string in `file:line:classification` format
- `blast_radius` field persisted to `resolve-context.json`

**VERIFY:**
```bash
python3 -c "import json; ctx=json.load(open('.runs/resolve-context.json')); assert isinstance(ctx.get('blast_radius'), list), 'blast_radius missing'; assert all(isinstance(f, str) for f in ctx['blast_radius']), 'blast_radius items must be strings'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh resolve 4
```

**NEXT:** If 2+ actionable issues remain, read [state-4b-root-cause-clustering.md](state-4b-root-cause-clustering.md). Otherwise, read [state-5-fix-design.md](state-5-fix-design.md) to continue.
