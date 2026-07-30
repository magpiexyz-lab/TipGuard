#!/usr/bin/env bash
# AOC v1.2 PR6 F2 — write-skipped-fixer-trace.sh test surface.
#
# Covers happy path + key forgery rejections. Critical safety property:
# the trace's verdict MUST NOT match any pass_* predicate (audit-only
# contract). Verified end-to-end via evaluate-hard-gate-predicates.py.

set -euo pipefail
cd "$(dirname "$0")/../../.."

TMPDIR=$(mktemp -d -t aocv12-f2-XXXXXX)
trap "rm -rf $TMPDIR" EXIT

mkdir -p "$TMPDIR/.runs/agent-traces" "$TMPDIR/.claude/scripts/lib" "$TMPDIR/.claude/hooks" "$TMPDIR/.claude/patterns" "$TMPDIR/.claude/scripts"
cp .claude/scripts/write-skipped-fixer-trace.sh "$TMPDIR/.claude/scripts/"
cp .claude/scripts/lib/source_identity_validator.py "$TMPDIR/.claude/scripts/lib/"
cp .claude/scripts/lib/source_identity_validator.sh "$TMPDIR/.claude/scripts/lib/"
cp .claude/hooks/lib*.sh "$TMPDIR/.claude/hooks/"
cp .claude/patterns/agent-registry.json "$TMPDIR/.claude/patterns/"
( cd "$TMPDIR" && git init -q && git checkout -q -b f2-test 2>&1 ) >/dev/null

python3 -c "
import json
json.dump({'skill':'verify','run_id':'verify-f2-r1','completed':False,'timestamp':'2026-05-04T12:00:00Z'},
          open('$TMPDIR/.runs/verify-context.json','w'))
"

# Fabricate security-merge.json with fixer_skipped:true + 3 critical findings.
python3 -c "
import json
json.dump({'fixer_skipped':True,'reason':'hard_gate_failure','issues':[
    {'severity':'critical'},{'severity':'high'},{'severity':'serious'},{'severity':'low'}
],'merged_issues':4,'run_id':'verify-f2-r1'},
          open('$TMPDIR/.runs/security-merge.json','w'))
"

PASS=0; FAIL=0; FAILS=()

expect_pass() {
  local label="$1"; shift
  if "$@" >/dev/null 2>&1; then
    PASS=$((PASS+1)); echo "  OK: $label"
  else
    FAIL=$((FAIL+1)); FAILS+=("$label"); echo "  FAIL: $label"
  fi
}
expect_fail() {
  local label="$1"; shift
  if "$@" >/dev/null 2>&1; then
    FAIL=$((FAIL+1)); FAILS+=("$label (should have failed)"); echo "  FAIL: $label — should have rejected"
  else
    PASS=$((PASS+1)); echo "  OK: $label rejected"
  fi
}

echo "=== AOC v1.2 F2 — write-skipped-fixer-trace.sh ==="

# Happy path
( cd "$TMPDIR" && \
    bash .claude/scripts/write-skipped-fixer-trace.sh security-fixer \
      --reason hard_gate_failure \
      --upstream-merge-path .runs/security-merge.json \
  ) >/dev/null 2>&1
TRACE="$TMPDIR/.runs/agent-traces/security-fixer.json"
if [[ -f "$TRACE" ]]; then
  PASS=$((PASS+1)); echo "  OK: happy-path trace written"
  # Verify shape
  for fld in provenance verdict result lead_attestation upstream_evidence_path reason unresolved_critical; do
    val=$(python3 -c "import json; print(json.load(open('$TRACE')).get('$fld'))" 2>/dev/null)
    if [[ -n "$val" && "$val" != "None" ]]; then
      PASS=$((PASS+1)); echo "  OK: $fld=$val"
    else
      FAIL=$((FAIL+1)); FAILS+=("missing $fld"); echo "  FAIL: $fld missing"
    fi
  done
  # CRITICAL: unresolved_critical must equal 3 (critical + high + serious; not low)
  uc=$(python3 -c "import json; print(json.load(open('$TRACE')).get('unresolved_critical'))" 2>/dev/null)
  if [[ "$uc" == "3" ]]; then
    PASS=$((PASS+1)); echo "  OK: unresolved_critical=3 (correct count)"
  else
    FAIL=$((FAIL+1)); FAILS+=("uc=$uc"); echo "  FAIL: unresolved_critical=$uc, expected 3"
  fi
else
  FAIL=$((FAIL+1)); FAILS+=("happy path no trace"); echo "  FAIL: happy path produced no trace"
fi

# Forgery: non-fixer agent
expect_fail "non-fixer agent rejected" \
  bash -c "cd $TMPDIR && bash .claude/scripts/write-skipped-fixer-trace.sh observer --reason hard_gate_failure --upstream-merge-path .runs/security-merge.json"

# Forgery: missing --upstream-merge-path
expect_fail "missing upstream-merge-path rejected" \
  bash -c "cd $TMPDIR && bash .claude/scripts/write-skipped-fixer-trace.sh security-fixer --reason hard_gate_failure"

# Forgery: upstream merge with fixer_skipped:false
python3 -c "
import json
json.dump({'fixer_skipped':False,'reason':'hard_gate_failure','issues':[]}, open('$TMPDIR/.runs/bad-merge.json','w'))
"
expect_fail "upstream fixer_skipped:false rejected" \
  bash -c "cd $TMPDIR && bash .claude/scripts/write-skipped-fixer-trace.sh security-fixer --reason hard_gate_failure --upstream-merge-path .runs/bad-merge.json"

# Forgery: caller --unresolved-critical flag
expect_fail "caller --unresolved-critical rejected" \
  bash -c "cd $TMPDIR && bash .claude/scripts/write-skipped-fixer-trace.sh security-fixer --reason hard_gate_failure --upstream-merge-path .runs/security-merge.json --unresolved-critical 0"

# Forgery: invalid --reason
expect_fail "invalid --reason rejected" \
  bash -c "cd $TMPDIR && bash .claude/scripts/write-skipped-fixer-trace.sh security-fixer --reason made_up --upstream-merge-path .runs/security-merge.json"

# STUB-PROTECTION contract: writer must REFUSE to overwrite non-stub trace.
# Without this guard, a buggy state-file or duplicate invocation could
# silently downgrade a real verdict=pass to audit-only blocked.
echo ""
echo "  Verifying stub-protection (refuse to overwrite non-stub trace)..."
# Synthesize a non-stub fixer trace (verdict=pass).
python3 -c "
import json
json.dump({'agent':'quality-fixer','status':'completed','verdict':'pass','provenance':'self','result':'fixed'},
          open('$TMPDIR/.runs/agent-traces/quality-fixer.json','w'))
json.dump({'fixer_skipped':True,'reason':'hard_gate_failure','issues':[{'severity':'critical'}]},
          open('$TMPDIR/.runs/quality-merge.json','w'))
"
set +e
( cd "$TMPDIR" && bash .claude/scripts/write-skipped-fixer-trace.sh quality-fixer --reason hard_gate_failure --upstream-merge-path .runs/quality-merge.json ) >/dev/null 2>&1
RC=$?
set -e
if [[ $RC -ne 0 ]]; then
  ACTUAL=$(python3 -c "import json; t=json.load(open('$TMPDIR/.runs/agent-traces/quality-fixer.json')); print(t.get('verdict')+'/'+t.get('provenance'))")
  if [[ "$ACTUAL" == "pass/self" ]]; then
    PASS=$((PASS+1))
    echo "  OK: stub-protection refused overwrite; original verdict=pass/self preserved"
  else
    FAIL=$((FAIL+1))
    FAILS+=("stub-protection passed but trace was modified to $ACTUAL")
    echo "  FAIL: writer rejected but trace was modified: $ACTUAL"
  fi
else
  FAIL=$((FAIL+1))
  FAILS+=("stub-protection FAILED — writer overwrote non-stub trace")
  echo "  FAIL: writer overwrote non-stub trace (stub-protection broken)"
fi

# AUDIT-ONLY contract: trace must fail all pass_* predicates.
echo ""
echo "  Verifying audit-only contract (verdict must fail every pass_* predicate)..."
HARD_GATE_OUTPUT=$(AGENT_ENV=security-fixer \
  TRACE_ENV="$TRACE" \
  TRACES_DIR_ENV="$TMPDIR/.runs/agent-traces" \
  REG_ENV=".claude/patterns/agent-registry.json" \
  python3 .claude/scripts/evaluate-hard-gate-predicates.py 2>&1)
if [[ "$HARD_GATE_OUTPUT" == BLOCK:* ]]; then
  PASS=$((PASS+1))
  echo "  OK: hard-gate blocks (verdict=blocked + no pass_* predicate matches): ${HARD_GATE_OUTPUT:0:80}..."
else
  FAIL=$((FAIL+1))
  FAILS+=("audit-only contract violated: $HARD_GATE_OUTPUT")
  echo "  FAIL: hard-gate did NOT block — output: $HARD_GATE_OUTPUT"
fi

echo ""
echo "Summary: $PASS passed, $FAIL failed"
if [[ $FAIL -gt 0 ]]; then
  for f in "${FAILS[@]}"; do echo "  - $f"; done
  exit 1
fi
exit 0
