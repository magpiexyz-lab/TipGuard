#!/usr/bin/env bash
# solve-critic.sh — Convention gate for solve-critic in /solve.
set -euo pipefail

source "$(dirname "$0")/../../../hooks/lib.sh"

PROJECT_DIR="${PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-.}}"

if [[ ! -f "$PROJECT_DIR/.runs/solve-context.json" ]]; then
  deny "solve-critic gate blocked: solve-context.json missing — STATE 0 incomplete."
fi

exit 0
