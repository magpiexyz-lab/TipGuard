#!/usr/bin/env bash
# scan-template-edits.sh — Phase 1 implementation of issue #1128 Mechanism A.
#
# Scans the run's git diff for changes under template-owned paths
# (.claude/, scripts/, .github/, docs/, plus root files like Makefile,
# CLAUDE.md, .gitleaks.toml, LICENSE, README.md, run-skill.sh).
#
# For each changed template file NOT already covered by an existing
# fix-ledger row, append a --template-edit row attributing the change to
# "lead-template-edit". Files with an existing ledger row are skipped
# (the agent's trace already recorded the fix).
#
# Idempotent: re-running detects existing rows and skips them.
# Fail-open: any error → no rows written, no failure surfaced.

set -uo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
cd "$PROJECT_DIR" || exit 0

SKILL="${1:-}"
if [[ -z "$SKILL" ]]; then
  # Derive from the most-recent non-epilogue, non-completed context file.
  SKILL=$(python3 -c "
import json, glob
best = None
best_ts = ''
for f in glob.glob('.runs/*-context.json'):
    if 'epilogue' in f:
        continue
    try:
        d = json.load(open(f))
    except Exception:
        continue
    if d.get('completed') is True:
        continue
    ts = d.get('timestamp', '') or ''
    if ts >= best_ts:
        best = d
        best_ts = ts
print((best or {}).get('skill', ''))
" 2>/dev/null || echo "")
fi
[[ -n "$SKILL" ]] || exit 0

# Resolve diff scope: prefer merge-base...HEAD; fall back to HEAD~1...HEAD.
MERGE_BASE=$(git merge-base main HEAD 2>/dev/null || echo "")
HEAD_SHA=$(git rev-parse HEAD 2>/dev/null || echo "")
if [[ -n "$MERGE_BASE" ]] && [[ "$MERGE_BASE" != "$HEAD_SHA" ]]; then
  RANGE="${MERGE_BASE}...HEAD"
  BASE_REF="$MERGE_BASE"
else
  RANGE="HEAD~1...HEAD"
  BASE_REF="HEAD~1"
fi

# Get changed files; filter to template-owned paths.
CHANGED=$(git diff --name-only "$RANGE" 2>/dev/null | python3 -c "
import sys
prefixes = ('.claude/', 'scripts/', '.github/', 'docs/')
files = ('Makefile', 'CLAUDE.md', '.gitleaks.toml', 'LICENSE', 'README.md', 'run-skill.sh')
for line in sys.stdin:
    p = line.strip()
    if not p:
        continue
    if p.startswith(prefixes) or p in files:
        print(p)
" || echo "")

[[ -n "$CHANGED" ]] || exit 0

# Resolve the current run_id from .runs/<skill>-context.json so dedupe
# is scoped to THIS run only. Without this, a prior run's row for the same
# file would silently mask the current run's edit (cross-run dedupe leak).
CURRENT_RUN_ID=$(python3 -c "
import json, os
ctx = f'.runs/$SKILL-context.json'
if os.path.isfile(ctx):
    try: print(json.load(open(ctx)).get('run_id', '') or '')
    except Exception: print('')
" 2>/dev/null || echo "")

# Load existing ledger; collect file paths already covered IN THIS RUN.
# Cross-run rows (different run_id) are intentionally ignored — they reflect
# prior skill executions and must not mask the current edit set.
COVERED=$(CURRENT_RUN_ID="$CURRENT_RUN_ID" python3 -c "
import json, os
ledger = '.runs/fix-ledger.jsonl'
if not os.path.isfile(ledger):
    raise SystemExit(0)
rid = os.environ.get('CURRENT_RUN_ID', '')
seen = set()
with open(ledger) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if rid and r.get('run_id') != rid:
            continue
        f_ = r.get('file')
        if f_:
            seen.add(f_)
for f in sorted(seen):
    print(f)
" 2>/dev/null || echo "")

# For each changed template file not already covered, write a row.
echo "$CHANGED" | while IFS= read -r file; do
  [[ -n "$file" ]] || continue
  if [[ -n "$COVERED" ]] && echo "$COVERED" | grep -qxF "$file"; then
    continue  # Agent trace already recorded a fix for this file
  fi
  BEFORE=$(git rev-parse "${BASE_REF}:$file" 2>/dev/null | head -c 8)
  AFTER=$(git rev-parse "HEAD:$file" 2>/dev/null | head -c 8)
  python3 .claude/scripts/write-fix-ledger.py --template-edit \
    --skill "$SKILL" \
    --file "$file" \
    --before-hash "${BEFORE:-none}" \
    --after-hash "${AFTER:-none}" \
    --agent "lead-template-edit" >/dev/null 2>&1 || true
done

# Re-render fix-log (idempotent).
python3 .claude/scripts/render-fix-log.py >/dev/null 2>&1 || true
exit 0
