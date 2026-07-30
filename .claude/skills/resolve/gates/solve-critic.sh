#!/usr/bin/env bash
# solve-critic.sh — Convention gate for solve-critic in /resolve.
set -euo pipefail

source "$(dirname "$0")/../../../hooks/lib.sh"

PROJECT_DIR="${PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-.}}"

if [[ ! -f "$PROJECT_DIR/.runs/solve-trace.json" ]]; then
  deny "solve-critic gate blocked: solve-trace.json missing — solve-reasoning not complete."
fi

exit 0
