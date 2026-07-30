#!/usr/bin/env bash
# commit.sh — Convention gate for /resolve commit checks.
# Handles epilogue bypass: fix/ branches with observe-result.json
# skip G4/verify checks (resolve does not produce them).
# Called by: skill-commit-gate.sh after framework checks pass.
set -euo pipefail

source "$(dirname "$0")/../../../hooks/lib.sh"

PROJECT_DIR="${PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-.}}"

# Epilogue bypass: observation complete → check verdict integrity then allow
if [[ -f "$PROJECT_DIR/.runs/observe-result.json" ]]; then
  ERRORS=()
  check_verdict_error
  if [[ ${#ERRORS[@]} -gt 0 ]]; then
    deny_errors "Observation integrity check failed: " "Re-run /resolve to retry observation."
  fi
  exit 0
fi

# No other resolve-specific commit checks
exit 0
