#!/usr/bin/env bash
# resolve-challenger.sh — Convention gate for resolve-challenger in /resolve.
set -euo pipefail

source "$(dirname "$0")/../../../hooks/lib.sh"

PROJECT_DIR="${PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-.}}"
ERRORS=()

if [[ ! -f "$PROJECT_DIR/.runs/resolve-context.json" ]]; then
  ERRORS+=("resolve-context.json missing — STATE 0 incomplete")
fi

if [[ ! -f "$PROJECT_DIR/.runs/solve-trace.json" ]]; then
  ERRORS+=("solve-trace.json missing — STATE 5 (solve-reasoning) not complete")
fi

if [[ ${#ERRORS[@]} -gt 0 ]]; then
  deny_errors "resolve-challenger gate blocked: " "Complete prerequisites before spawning resolve-challenger."
fi

exit 0
