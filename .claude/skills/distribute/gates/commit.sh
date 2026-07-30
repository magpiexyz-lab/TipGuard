#!/usr/bin/env bash
# commit.sh — Convention gate for /distribute commit checks.
# Extracted from change-commit-gate.sh distribute branch handling.
# Called by: skill-commit-gate.sh after framework checks pass.
set -euo pipefail

source "$(dirname "$0")/../../../hooks/lib.sh"

PROJECT_DIR="${PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-.}}"
REPORT="$PROJECT_DIR/.runs/verify-report.md"

# If verify-report exists, allow
if [[ -f "$REPORT" ]]; then
  exit 0
fi

# Only block at final state (state 7+ completed = ready for verify+commit)
CTX="$PROJECT_DIR/.runs/distribute-context.json"
if [[ -f "$CTX" ]]; then
  STATES=$(normalize_states "$CTX")
  if [[ " $STATES " == *" 7 "* ]]; then
    deny "Distribute commit blocked: verify-report.md missing — run verify before final commit."
  fi
fi

exit 0
