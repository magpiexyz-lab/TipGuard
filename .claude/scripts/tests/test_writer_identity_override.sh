#!/usr/bin/env bash
# AOC v1.2 PR6 F1 — Writer identity-override happy path.
#
# For each writer that accepts --source-run-id + --source-skill (PR2 B1-B6
# + PR3 + PR5), verify the happy path: a fabricated post-completion
# scenario (all *-context.json have completed:true) where the lead supplies
# explicit identity flags + spawn-log entry exists.
#
# Negative cases (forgery, missing flags, R1-R4 violations) live in F6
# (test_writer_validation_matrix.sh) — this test only verifies that the
# canonical source-flag plumbing works end-to-end.

set -euo pipefail
cd "$(dirname "$0")/../../.."

# Run inside an isolated tmp project so we do not pollute the live .runs/.
TMPDIR=$(mktemp -d -t aocv12-f1-XXXXXX)
trap "rm -rf $TMPDIR" EXIT

mkdir -p "$TMPDIR/.runs/agent-traces" "$TMPDIR/.claude/scripts/lib" "$TMPDIR/.claude/hooks" "$TMPDIR/.claude/patterns" "$TMPDIR/.claude/scripts"

# Mirror the writers + their dependencies into the tmp project.
cp .claude/scripts/write-agent-trace.sh "$TMPDIR/.claude/scripts/"
cp .claude/scripts/write-degraded-trace.py "$TMPDIR/.claude/scripts/"
cp .claude/scripts/lib/source_identity_validator.py "$TMPDIR/.claude/scripts/lib/"
cp .claude/scripts/lib/source_identity_validator.sh "$TMPDIR/.claude/scripts/lib/"
cp .claude/hooks/lib*.sh "$TMPDIR/.claude/hooks/"
cp .claude/patterns/agent-registry.json "$TMPDIR/.claude/patterns/"

# Initialize as git repo (some writers shell out to git).
( cd "$TMPDIR" && git init -q && git checkout -q -b f1-test 2>&1 ) >/dev/null

# Fabricate post-completion: a context with completed:true (so
# resolve_active_identity returns empty) — but the run_id+skill exist.
python3 -c "
import json
json.dump({'skill':'verify','run_id':'verify-f1-r1','completed':True,'timestamp':'2026-05-04T12:00:00Z'},
          open('$TMPDIR/.runs/verify-context.json','w'))
"

# Spawn-log entry proving the agent was invoked under that run.
python3 -c "
import json
with open('$TMPDIR/.runs/agent-spawn-log.jsonl','w') as f:
    json.dump({'agent':'design-critic','run_id':'verify-f1-r1','hook':'skill-agent-gate','head_sha':'abc123','spawn_index':1}, f)
    f.write('\n')
"

PASS=0; FAIL=0; FAILS=()

assert_ok() {
  local label="$1"; shift
  if "$@" >/dev/null 2>&1; then
    PASS=$((PASS+1))
    echo "  OK: $label"
  else
    local rc=$?
    FAIL=$((FAIL+1))
    FAILS+=("$label (exit $rc)")
    echo "  FAIL: $label — exit $rc"
    "$@" 2>&1 | head -5 | sed 's/^/    /'
  fi
}

assert_trace_field() {
  local label="$1" trace_path="$2" field="$3" expected="$4"
  local actual
  actual=$(python3 -c "import json; print(json.load(open('$trace_path')).get('$field'))" 2>/dev/null)
  if [[ "$actual" == "$expected" ]]; then
    PASS=$((PASS+1))
    echo "  OK: $label ($field=$actual)"
  else
    FAIL=$((FAIL+1))
    FAILS+=("$label ($field=$actual, expected $expected)")
    echo "  FAIL: $label — $field=$actual (expected $expected)"
  fi
}

echo "=== AOC v1.2 F1 — writer identity-override happy path ==="

# B1: write-agent-trace.sh with --source-run-id + --source-skill.
# Simulate cross-skill (active=none, source=verify) so HC13 passes trivially.
( cd "$TMPDIR" && \
    bash .claude/scripts/write-agent-trace.sh design-critic \
      --json '{"verdict":"pass","result":"clean","checks_performed":["x"]}' \
      --source-run-id verify-f1-r1 \
      --source-skill verify \
  ) >/dev/null 2>&1
TRACE="$TMPDIR/.runs/agent-traces/design-critic.json"
if [[ -f "$TRACE" ]]; then
  assert_trace_field "B1 provenance" "$TRACE" "provenance" "lead-orchestrated"
  assert_trace_field "B1 lead_attestation" "$TRACE" "lead_attestation" "True"
  assert_trace_field "B1 source_run_id" "$TRACE" "source_run_id" "verify-f1-r1"
  assert_trace_field "B1 source_skill" "$TRACE" "source_skill" "verify"
else
  FAIL=$((FAIL+1)); FAILS+=("B1 trace missing")
  echo "  FAIL: B1 trace missing at $TRACE"
fi

# B2: write-degraded-trace.py with source flags.
rm -f "$TRACE"
( cd "$TMPDIR" && \
    python3 .claude/scripts/write-degraded-trace.py design-critic \
      --reason "test-degraded" \
      --checks-performed "smoke-check" \
      --source-run-id verify-f1-r1 \
      --source-skill verify \
  ) >/dev/null 2>&1
if [[ -f "$TRACE" ]]; then
  assert_trace_field "B2 provenance" "$TRACE" "provenance" "lead-orchestrated"
  assert_trace_field "B2 source_run_id" "$TRACE" "source_run_id" "verify-f1-r1"
  assert_trace_field "B2 source_skill" "$TRACE" "source_skill" "verify"
else
  FAIL=$((FAIL+1)); FAILS+=("B2 trace missing")
  echo "  FAIL: B2 trace missing at $TRACE"
fi

echo ""
echo "Summary: $PASS passed, $FAIL failed"
if [[ $FAIL -gt 0 ]]; then
  echo "Failures:"
  for f in "${FAILS[@]}"; do echo "  - $f"; done
  exit 1
fi
exit 0
