#!/usr/bin/env bash
# commit.sh — Convention gate for /review commit checks.
# Extracted from change-commit-gate.sh review branch handling.
# Called by: skill-commit-gate.sh after framework checks pass.
set -euo pipefail

source "$(dirname "$0")/../../../hooks/lib.sh"

PROJECT_DIR="${PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-.}}"
CTX="$PROJECT_DIR/.runs/review-context.json"

if [[ -f "$CTX" ]]; then
  STATES=$(normalize_states "$CTX")
  # At state 4 (final), require review-complete.json
  if [[ " $STATES " == *" 4 "* ]] && [[ ! -f "$PROJECT_DIR/.runs/review-complete.json" ]]; then
    deny "Review commit blocked: review-complete.json missing — complete review validation first."
  fi
fi

exit 0
