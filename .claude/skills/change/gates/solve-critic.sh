#!/usr/bin/env bash
# solve-critic.sh — Convention gate for solve-critic in /change.
set -euo pipefail

source "$(dirname "$0")/../../../hooks/lib.sh"

PROJECT_DIR="${PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-.}}"

if [[ ! -f "$PROJECT_DIR/.runs/change-context.json" ]]; then
  deny "solve-critic gate blocked: change-context.json missing — STATE 0 incomplete."
fi

exit 0
