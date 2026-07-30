#!/usr/bin/env bash
# test_gate_evidence_runner.sh — wrapper that runs the Python unit tests AND
# does a CLI smoke check on .claude/scripts/verify-gate-evidence.py.
#
# Exit 0 = all checks pass; non-zero = some check failed.
set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO_ROOT"

OK=0
FAIL=0

echo "==> Python unit tests"
if python3 .claude/scripts/tests/test_gate_evidence_runner.py; then
  OK=$((OK + 1))
else
  FAIL=$((FAIL + 1))
fi

echo
echo "==> CLI smoke — empty rules"
if python3 .claude/scripts/verify-gate-evidence.py --rule-id all; then
  echo "  PASS  --rule-id all (empty rules)"
  OK=$((OK + 1))
else
  echo "  FAIL  --rule-id all (empty rules)"
  FAIL=$((FAIL + 1))
fi

echo
echo "==> CLI smoke — --audit on real codebase"
AUDIT_OUT="$(python3 .claude/scripts/verify-gate-evidence.py --audit 2>&1)"
if echo "$AUDIT_OUT" | python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
assert 'total_findings' in data, 'missing total_findings'
assert 'audit_commit_sha' in data, 'missing audit_commit_sha'
assert isinstance(data.get('findings'), list), 'findings is not list'
print(f'  audit returned total_findings={data[\"total_findings\"]}')
" 2>&1; then
  echo "  PASS  --audit"
  OK=$((OK + 1))
else
  echo "  FAIL  --audit"
  echo "$AUDIT_OUT" | head -10
  FAIL=$((FAIL + 1))
fi

echo
echo "==> CLI smoke — nonexistent rule (exits 0, message to stderr)"
if python3 .claude/scripts/verify-gate-evidence.py --rule-id _does_not_exist_ 2>/dev/null; then
  echo "  PASS  nonexistent rule exits 0"
  OK=$((OK + 1))
else
  echo "  FAIL  nonexistent rule exited non-zero"
  FAIL=$((FAIL + 1))
fi

echo
echo "=== Summary: $OK passed, $FAIL failed ==="
exit $((FAIL > 0 ? 1 : 0))
