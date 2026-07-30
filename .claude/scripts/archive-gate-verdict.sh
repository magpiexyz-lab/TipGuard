#!/usr/bin/env bash
# archive-gate-verdict.sh — Archive existing gate verdict before overwrite.
# Usage: bash .claude/scripts/archive-gate-verdict.sh <gate-id>
set -euo pipefail

GATE_ID="${1:-}"
if [[ -z "$GATE_ID" ]]; then
  echo "ERROR: archive-gate-verdict.sh — gate-id required" >&2
  exit 1
fi

PROJECT_DIR="$(git rev-parse --show-toplevel 2>/dev/null || echo "${CLAUDE_PROJECT_DIR:-.}")"
VERDICTS_DIR="$PROJECT_DIR/.runs/gate-verdicts"
VERDICT_FILE="$VERDICTS_DIR/$GATE_ID.json"

# Nothing to archive if no existing verdict
[[ -f "$VERDICT_FILE" ]] || exit 0

HISTORY_DIR="$VERDICTS_DIR/history"
mkdir -p "$HISTORY_DIR"

# Count existing attempts with strict pattern
ATTEMPT_COUNT=$(find "$HISTORY_DIR" -maxdepth 1 -name "${GATE_ID}-attempt-*.json" 2>/dev/null | wc -l | tr -d ' ')
NEXT_N=$((ATTEMPT_COUNT + 1))

# cp (not mv) — canonical file remains until cat > overwrites it
cp "$VERDICT_FILE" "$HISTORY_DIR/${GATE_ID}-attempt-${NEXT_N}.json"
