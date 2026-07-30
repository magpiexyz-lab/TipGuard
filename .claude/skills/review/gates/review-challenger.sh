#!/usr/bin/env bash
# review-challenger.sh — Convention gate for review-challenger in /review.
set -euo pipefail

source "$(dirname "$0")/../../../hooks/lib.sh"

PROJECT_DIR="${PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-.}}"

if [[ ! -f "$PROJECT_DIR/.runs/review-context.json" ]]; then
  deny "review-challenger gate blocked: review-context.json missing — STATE 0 incomplete."
fi

exit 0
