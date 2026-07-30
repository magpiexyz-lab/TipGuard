# STATE 2: MEMORY_RECONCILE

**PRECONDITIONS:**
- State 1 complete (`.runs/upgrade-diff-report.json` exists)

**ACTIONS:**

### Locate memory directories

Find the auto-memory directory for the current project:
```bash
# The project memory path uses a mangled version of the project directory
# Glob to find it
ls -d ~/.claude/projects/*/memory/ 2>/dev/null
```

Match the correct one by checking if the mangled path corresponds to the current working directory. The mangling replaces `/` with `-` and prepends `-`, so `/Users/foo/myproject` becomes `-Users-foo-myproject`.

Also check `.claude/agent-memory/` in the project root if it exists.

### Scan for stale references

If no memory directory exists or it is empty → write an empty report and skip to output.

For each `.md` file in the memory directory:
1. Read the file content
2. Extract file paths using patterns:
   - Paths starting with `src/`, `.claude/`, `experiment/`, `scripts/`, `.github/`
   - Paths matching common code file patterns (e.g., `*.ts`, `*.tsx`, `*.js`, `*.md`, `*.json`, `*.yaml`, `*.sh`)
3. For each extracted path, check if it exists on disk relative to the project root
4. If a referenced file does not exist → flag the memory entry as stale with the missing references

Apply the same logic to files in `.claude/agent-memory/` if that directory exists.

### Present results

Print a summary of stale entries to the user:
```
Stale memory entries found:
  - memory-name.md: references src/old/path.ts (missing), .claude/old/pattern.md (missing)
  - another-memory.md: references src/removed/file.tsx (missing)
```

Read `.runs/upgrade-context.json` to check the `dry_run` flag:
- If `dry_run == true`: report only, do not prompt for deletion
- If `dry_run == false` and stale entries exist: present the list and ask the user which entries to delete. Only delete entries the user explicitly confirms.

### Output

Write `.runs/upgrade-memory-report.json`:
```json
{
  "memories_checked": 4,
  "stale_entries": [
    {"file": "memory-name.md", "missing_refs": ["src/old/path.ts", ".claude/old/pattern.md"]},
    {"file": "another-memory.md", "missing_refs": ["src/removed/file.tsx"]}
  ],
  "action_taken": "reported"
}
```

Set `action_taken` to:
- `"reported"` if dry-run or no stale entries found
- `"user-confirmed-deletions"` if user confirmed deletions in normal mode

**POSTCONDITIONS:**
- `.runs/upgrade-memory-report.json` exists with valid JSON

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/upgrade-memory-report.json')); assert isinstance(d.get('memories_checked'), int) and d['memories_checked']>=0, 'memories_checked invalid'; assert isinstance(d.get('stale_entries'), list), 'stale_entries not list'; assert all(isinstance(e, (str,dict)) for e in d['stale_entries']), 'stale_entries items invalid'; assert d.get('action_taken') in ('reported','user-confirmed-deletions'), 'action_taken invalid: %s' % d.get('action_taken')"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh upgrade 2
```

**NEXT:** Read [state-3-commit-pr.md](state-3-commit-pr.md) to continue.
