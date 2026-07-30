#!/usr/bin/env bash
# AOC v1.2 PR6 F3 — observation-evidence.json envelope completeness.
#
# Closes design caveat C4: every present canonical evidence family on disk
# MUST be referenced by the envelope schema. NO exclusion mechanism —
# adding a family requires editing
# .claude/scripts/lib/observer_evidence_families.py:CANONICAL_EVIDENCE_FAMILIES
# (visible in PR diff). The F3 test enforces presence.
#
# Strategy:
# 1. Fabricate one file per CANONICAL_EVIDENCE_FAMILIES entry under a tmp
#    .runs/ directory.
# 2. Run write-observation-evidence.py --print-only against that tmp dir.
# 3. Parse the resulting JSON; assert every (pattern, schema_field, kind)
#    from the constant has its schema_field populated (non-null for
#    `single`, non-empty list for `multi`).
# 4. Negative case: remove a family, re-run, assert that family's field
#    is now null/[] (proving the writer correctly omits absent families).

set -euo pipefail
cd "$(dirname "$0")/../../.."

TMPDIR=$(mktemp -d -t aocv12-f3-XXXXXX)
trap "rm -rf $TMPDIR" EXIT

# We need .claude/scripts/lib on sys.path so write-observation-evidence.py
# can import observer_evidence_families. Use the real project's lib.
PROJECT_DIR="$PWD"
RUNS_DIR="$TMPDIR/.runs"
mkdir -p "$RUNS_DIR/agent-traces"

# Fabricate one file per family (covers every glob pattern).
echo "diff content" > "$RUNS_DIR/observer-diffs.txt"
echo "fix log" > "$RUNS_DIR/fix-log.md"
echo '{"fix_id":"x","provenance":"lead"}' > "$RUNS_DIR/fix-ledger.jsonl"
echo '{}' > "$RUNS_DIR/hook-friction.jsonl"
echo '{"hooks":{}}' > "$RUNS_DIR/hook-friction-summary.json"
echo '{"build":"ok"}' > "$RUNS_DIR/build-result.json"
echo '{"e2e":"ok"}' > "$RUNS_DIR/e2e-result.json"
echo '{"agent":"observer"}' > "$RUNS_DIR/agent-traces/observer.json"
echo '{}' > "$RUNS_DIR/x-summary.json"
echo '{}' > "$RUNS_DIR/x-merge.json"
echo '{}' > "$RUNS_DIR/x-evidence.json"
echo '{}' > "$RUNS_DIR/x-result.json"

# Run the envelope writer in --print-only mode against the tmp runs dir.
ENVELOPE=$(python3 "$PROJECT_DIR/.claude/scripts/write-observation-evidence.py" \
  --runs-dir "$RUNS_DIR" \
  --project-dir "$PROJECT_DIR" \
  --print-only 2>/dev/null)

if [[ -z "$ENVELOPE" ]]; then
  echo "FAIL: envelope writer produced empty output" >&2
  exit 1
fi

# Assert every family's schema_field is populated.
RESULT=$(ENVELOPE_TEXT="$ENVELOPE" python3 - <<'PYEOF'
import json, os, sys
sys.path.insert(0, ".claude/scripts/lib")
from observer_evidence_families import CANONICAL_EVIDENCE_FAMILIES

env = json.loads(os.environ["ENVELOPE_TEXT"])
errors = []
ok_count = 0
for pattern, field, kind in CANONICAL_EVIDENCE_FAMILIES:
    if field not in env:
        errors.append(f"schema_field {field!r} missing from envelope (family {pattern})")
        continue
    val = env[field]
    if kind == "single":
        if not val:
            errors.append(f"schema_field {field!r} for family {pattern} is null (file present on disk)")
        else:
            ok_count += 1
    else:
        if not isinstance(val, list) or len(val) == 0:
            errors.append(f"schema_field {field!r} for family {pattern} is empty list (matches present on disk)")
        else:
            ok_count += 1

if errors:
    print("FAIL")
    for e in errors:
        print("  - " + e)
    sys.exit(1)
print(f"OK: {ok_count} families correctly referenced")
PYEOF
)

echo "=== AOC v1.2 F3 — observation evidence envelope ==="
echo "$RESULT"

if [[ "$RESULT" == FAIL* ]]; then
  exit 1
fi

# Negative: remove agent-traces/, re-run; the corresponding multi field
# should now be empty list (proving correct absent-family handling).
rm -rf "$RUNS_DIR/agent-traces"
ENVELOPE2=$(python3 "$PROJECT_DIR/.claude/scripts/write-observation-evidence.py" \
  --runs-dir "$RUNS_DIR" \
  --project-dir "$PROJECT_DIR" \
  --print-only 2>/dev/null)
TRACES_FIELD=$(ENVELOPE_TEXT="$ENVELOPE2" python3 -c "import json, os; print(json.loads(os.environ['ENVELOPE_TEXT']).get('agent_traces_paths'))")
if [[ "$TRACES_FIELD" == "[]" ]]; then
  echo "  OK: agent_traces_paths correctly empty when family absent"
else
  echo "  FAIL: agent_traces_paths=$TRACES_FIELD (expected [] after removing agent-traces/)"
  exit 1
fi

echo ""
echo "Summary: F3 envelope completeness verified."
exit 0
