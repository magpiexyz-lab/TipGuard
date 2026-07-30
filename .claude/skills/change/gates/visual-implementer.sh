#!/usr/bin/env bash
# visual-implementer.sh — Convention gate: G3 verdict check for visual-implementer agents.
set -euo pipefail

source "$(dirname "$0")/../../../hooks/lib.sh"

if [[ -z "${PAYLOAD:-}" ]]; then parse_payload; fi
PROJECT_DIR="${PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-.}}"
BRANCH="${BRANCH:-$(get_branch)}"
VERDICTS_DIR="$PROJECT_DIR/.runs/gate-verdicts"
ERRORS=()

check_verdict_gates "g3" "$VERDICTS_DIR" "$BRANCH"

if [[ ${#ERRORS[@]} -gt 0 ]]; then
  deny_errors "visual-implementer gate blocked: " "Complete G3 gate (plan approval) before spawning visual-implementer."
fi

exit 0
