# STATE 0: INPUT_BRANCH_SETUP

**PRECONDITIONS:**
- Git repository exists in working directory
- GitHub CLI (`gh`) is authenticated

**ACTIONS:**

Parse `$ARGUMENTS` for the `--dry-run` flag. If present, set `dry_run = true` in the context file.

Create the upgrade branch (atomic checkout + context propagation per
issue #1328):
```bash
echo "$(date +%s)" > .runs/last-branch-checkout.tsv && \
  OLD_BRANCH="$(git branch --show-current)" && \
  git checkout -b chore/upgrade-template && \
  bash .claude/scripts/update-context-branch.sh "$OLD_BRANCH"
```

Auto-add `template` remote if missing:
```bash
if ! git remote get-url template &>/dev/null; then
  git remote add template https://github.com/magpiexyz-lab/mvp-template.git
fi
```

Fetch template:
```bash
git fetch template
```

### Resolve sync base

Determine the last-synced template commit for orphan detection:
```bash
if [ -f .claude/template-sync-meta.json ]; then
  SYNC_BASE=$(python3 -c "import json; print(json.load(open('.claude/template-sync-meta.json'))['last_synced_commit'])")
else
  # First overwrite-based upgrade: fall back to merge-base (works because prior upgrades used --merge)
  SYNC_BASE=$(git merge-base HEAD template/main 2>/dev/null || echo "")
fi
```

Clean stale skill artifacts and merge upgrade-specific fields into context:
```bash
rm -f .runs/upgrade-*.json
bash .claude/scripts/init-context.sh upgrade '{"dry_run":false}'
```

Store sync_base and dry_run in the context file:
```bash
PAYLOAD=$(SYNC_BASE_ENV="$SYNC_BASE" python3 -c "
import json, os
d = json.load(open('.runs/upgrade-context.json'))
d['sync_base'] = os.environ['SYNC_BASE_ENV']
d['dry_run'] = False
print(json.dumps(d))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/upgrade-context.json \
  --payload "$PAYLOAD" \
  --skill upgrade
```

If `--dry-run` was specified, update the context file:
```bash
PAYLOAD=$(python3 -c "
import json
d = json.load(open('.runs/upgrade-context.json'))
d['dry_run'] = True
print(json.dumps(d))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/upgrade-context.json \
  --payload "$PAYLOAD" \
  --skill upgrade
```

**POSTCONDITIONS:**
- `.runs/upgrade-context.json` exists
- On `chore/upgrade-template` branch
- `template` remote is configured and fetched

**VERIFY:**
```bash
test -f .runs/upgrade-context.json && git branch --show-current | grep -q 'chore/upgrade-template' && python3 -c "import json,glob; d=json.load(open('.runs/upgrade-context.json')); ctx=None
for f in glob.glob('.runs/*-context.json'):
    if 'epilogue' in f: continue
    try: c=json.load(open(f))
    except: continue
    if c.get('completed') is True: continue
    if ctx is None or (c.get('timestamp','') > (ctx.get('timestamp','') or '')): ctx=c
active_skill=ctx.get('skill','') if ctx else ''
active_run_id=ctx.get('run_id','') if ctx else ''
assert d.get('skill') == active_skill, 'upgrade-context.json skill=%r does not match active_skill=%r (stale prior-skill artifact)' % (d.get('skill'), active_skill)
assert d.get('run_id') == active_run_id, 'upgrade-context.json run_id=%r does not match active_run_id=%r (stale artifact)' % (d.get('run_id'), active_run_id)"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh upgrade 0
```

**NEXT:** Read [state-1-merge-validate.md](state-1-merge-validate.md) to continue.
