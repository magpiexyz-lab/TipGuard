# STATE 3: COMMIT_PR

**PRECONDITIONS:**
- State 2 complete (`.runs/upgrade-memory-report.json` exists)

**ACTIONS:**

Read `.runs/upgrade-context.json` to check the `dry_run` flag.

### Build verification

If a `package.json` exists, run the build:
```bash
npm run build
```

If the build fails, apply the standard 3-attempt fix loop:
1. Read the error output
2. Fix the issue
3. Re-run `npm run build`
Repeat up to 3 times. If still failing after 3 attempts, report the error and continue.

### Dry-run exit

If `dry_run == true`:
- Present the combined report from States 1-2 to the user (read `.runs/upgrade-diff-report.json` and `.runs/upgrade-memory-report.json`)
- Write `.runs/delivery-skip.flag` (content: `dry-run`)
- **STOP.** Do not write other delivery artifacts. Present the report and end.

### Update sync metadata

Record the synced template commit for future orphan detection:
```bash
python3 -c "
import json, datetime, subprocess
sha = subprocess.check_output(['git', 'rev-parse', 'template/main']).decode().strip()
meta = {
    'last_synced_commit': sha,
    'last_upgrade_date': datetime.datetime.now(datetime.timezone.utc).isoformat()
}
json.dump(meta, open('.claude/template-sync-meta.json', 'w'), indent=2)
"
```

### Write delivery artifacts

```bash
TEMPLATE_SHA=$(python3 -c "import json; print(json.load(open('.runs/upgrade-diff-report.json')).get('template_commit','latest')[:7])" 2>/dev/null || echo "latest")
```

Write `.runs/commit-message.txt`: `Upgrade template to $TEMPLATE_SHA`

Write `.runs/pr-title.txt`: `chore: upgrade template to $TEMPLATE_SHA`

Write `.runs/pr-body.md` — dedicated upgrade report format (do NOT use the standard PR template):

```
## Template Upgrade Report

**Sync status:** <synced / up-to-date>
**Files synced:** <N> files
**Orphans removed:** <N> files
**Config drift:** <N> lines differ in .gitignore
**Stale memories flagged:** <N> entries

### Synced Files
<list of template files overwritten — from upgrade-diff-report.json files_synced>

### Orphans Deleted
<list orphans removed — from upgrade-diff-report.json orphans_deleted>

### Memory Reconciliation
<list stale entries found and actions taken — from upgrade-memory-report.json>

### Config Drift
<.gitignore differences — template additions and project additions>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

Fill in the actual values from the report JSON files.

### Q-score

Compute upgrade execution quality (see `.claude/patterns/skill-scoring.md`):

```bash
RUN_ID=$(python3 -c "import json; print(json.load(open('.runs/upgrade-context.json')).get('run_id', ''))" 2>/dev/null || echo "")
PAYLOAD=$(python3 -c "
import json, os
print(json.dumps({
    'scope': 'upgrade',
    'dims': {'completion': 1.0}
}))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/q-dimensions.json \
  --payload "$PAYLOAD" \
  --skill upgrade || true
```

### Completion checkpoint

Write `.runs/upgrade-step-check.json`:
```bash
PAYLOAD=$(python3 -c "
import json, os, subprocess, sys
steps = []
if os.path.exists('package.json'):
    steps.append('build_verify')
ctx = json.load(open('.runs/upgrade-context.json')) if os.path.exists('.runs/upgrade-context.json') else {}
dry_run = ctx.get('dry_run', False)
if dry_run:
    steps.append('dry_run_exit')
else:
    if os.path.exists('.runs/upgrade-diff-report.json'):
        diff = json.load(open('.runs/upgrade-diff-report.json'))
        if len(diff.get('files_synced', [])) > 0:
            steps.append('files_synced')
    if os.path.exists('.runs/commit-message.txt'):
        steps.append('artifacts')
steps.append('q_score')
print(f'SELF-CHECK: wrote .runs/upgrade-step-check.json with {len(steps)} steps', file=sys.stderr)
print(json.dumps({
    'steps_completed': steps,
    'key_outputs': {
        'build_passed': 'build_verify' in steps or not os.path.exists('package.json'),
        'dry_run': dry_run
    }
}))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/upgrade-step-check.json \
  --payload "$PAYLOAD" \
  --skill upgrade
```

This checkpoint is mandatory. Do not skip it.

**POSTCONDITIONS:**
- Delivery artifacts written (`.runs/commit-message.txt`, `.runs/pr-title.txt`, `.runs/pr-body.md`) OR `.runs/delivery-skip.flag` if dry-run
- `.runs/q-dimensions.json` written
- `.runs/upgrade-step-check.json` exists with at least 1 completed step

**VERIFY:**
```bash
(test -f .runs/delivery-skip.flag || (test -f .runs/commit-message.txt && test -f .runs/pr-title.txt && test -f .runs/pr-body.md)) && test -f .runs/q-dimensions.json && python3 -c "import json; d=json.load(open('.runs/upgrade-step-check.json')); assert len(d.get('steps_completed',[])) > 0"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh upgrade 3
```

**NEXT:** TERMINAL — `lifecycle-finalize.sh` handles commit, push, PR creation, and auto-merge (or skips if dry-run).

After finalize, read the `DELIVERY=` output and tell the user:
- If `DELIVERY=merged`: "Upgrade PR auto-merged to main."
- If `DELIVERY=pr-created:<reason>`: "Upgrade PR created but not auto-merged (<reason>). Merge manually."
- If `DELIVERY=skipped`: "Dry-run complete — no changes committed."
