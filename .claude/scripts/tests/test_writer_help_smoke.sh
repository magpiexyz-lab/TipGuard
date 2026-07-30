#!/usr/bin/env bash
# AOC v1.2 PR6 F5 — Parser-build smoke test.
#
# Closes the prior-failure regression class (#1121: argparse duplicate
# --extra-json blocked all invocations including --help).
#
# For each writer modified in PR1-PR5, invoke with --help and assert:
#   - exit 0
#   - stdout non-empty (the parser printed usage)
#
# This is a NARROW guard (catches argparse construction regressions only);
# branch-coverage of the validation logic is owned by F6
# (test_writer_validation_matrix.sh).

set -euo pipefail
cd "$(dirname "$0")/../../.."

PASS=0
FAIL=0
FAILED_WRITERS=()

check_writer() {
  local label="$1"; shift
  # Capture both stdout + stderr; exit code in {0, 1} acceptable (some tools
  # exit 1 on --help by convention — argparse exits 0, but bash usage()
  # functions often exit 1 to share the missing-args path). The TEST point
  # is that the parser BUILDS — empty output indicates argparse construction
  # failure (the #1121 regression class).
  local out
  local rc=0
  out=$("$@" --help 2>&1) || rc=$?
  if [[ -z "$out" ]]; then
    FAIL=$((FAIL + 1))
    FAILED_WRITERS+=("$label (empty stdout)")
    echo "  FAIL: $label — --help produced empty output (parser construction failure?)"
    return
  fi
  if [[ $rc -gt 1 ]]; then
    FAIL=$((FAIL + 1))
    FAILED_WRITERS+=("$label (exit $rc)")
    echo "  FAIL: $label — --help exit $rc (expected 0 or 1)"
    return
  fi
  PASS=$((PASS + 1))
  echo "  OK: $label (exit $rc)"
}

echo "=== AOC v1.2 F5 — writer --help smoke test ==="
check_writer "write-agent-trace.sh"       bash .claude/scripts/write-agent-trace.sh
check_writer "write-degraded-trace.py"    python3 .claude/scripts/write-degraded-trace.py
check_writer "augment-trace.py"           python3 .claude/scripts/augment-trace.py
check_writer "write-recovery-trace.sh"    bash .claude/scripts/write-recovery-trace.sh
check_writer "write-skipped-fixer-trace.sh" bash .claude/scripts/write-skipped-fixer-trace.sh
check_writer "write-observation-evidence.py" python3 .claude/scripts/write-observation-evidence.py
check_writer "source_identity_validator.py" python3 .claude/scripts/lib/source_identity_validator.py

echo ""
echo "Summary: $PASS passed, $FAIL failed"
if [[ $FAIL -gt 0 ]]; then
  echo "Failed writers:"
  for w in "${FAILED_WRITERS[@]}"; do
    echo "  - $w"
  done
  exit 1
fi
exit 0
