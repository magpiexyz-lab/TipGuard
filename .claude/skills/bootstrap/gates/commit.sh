#!/usr/bin/env bash
# commit.sh — Convention gate for /bootstrap commit checks.
# Extracted from bootstrap-commit-gate.sh (bootstrap-specific logic only).
# Called by: skill-commit-gate.sh after framework checks pass.
set -euo pipefail

source "$(dirname "$0")/../../../hooks/lib.sh"

if [[ -z "${PAYLOAD:-}" ]]; then parse_payload; fi
SKILL="${SKILL:-bootstrap}"
PROJECT_DIR="${PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-.}}"
BRANCH="${BRANCH:-$(get_branch)}"
COMMAND="${COMMAND:-$(read_payload_field "tool_input.command")}"

# WIP commits allowed — only enforce on final "Bootstrap" commit
if [[ "$COMMAND" != *"Bootstrap"* ]]; then
  exit 0
fi

# --- Final bootstrap commit — run gate checks ---

PLAN="$PROJECT_DIR/.runs/current-plan.md"
ERRORS=()

# Check 1: current-plan.md exists
if [[ ! -f "$PLAN" ]]; then
  ERRORS+=("current-plan.md not found — Process Checklist missing")
fi

if [[ -f "$PLAN" ]]; then
  # Primary: verdict files
  VERDICTS_DIR="$PROJECT_DIR/.runs/gate-verdicts"
  check_verdict_gates "bg1 bg2 bg2.5 bg2-wire bg4" "$VERDICTS_DIR"

  # Freshness: BG1 timestamp > branch creation
  BRANCH_CREATED=$(git log --format=%aI "$(git merge-base main HEAD)" -1 2>/dev/null || echo "")
  if [[ -n "$BRANCH_CREATED" && -f "$VERDICTS_DIR/bg1.json" ]]; then
    VERDICT_TS=$(read_json_field "$VERDICTS_DIR/bg1.json" "timestamp")
    if [[ -n "$VERDICT_TS" ]]; then
      IS_FRESH=$(python3 -c "from datetime import datetime; bt=datetime.fromisoformat('$BRANCH_CREATED'.rstrip('Z')); vt=datetime.fromisoformat('$VERDICT_TS'.rstrip('Z')); print('yes' if vt>=bt else 'no')" 2>/dev/null || echo "yes")
      [[ "$IS_FRESH" == "no" ]] && ERRORS+=("BG1 verdict older than branch creation")
    fi
  fi

  # Secondary: checklist checks
  if ! grep -q '\- \[x\].*BG1' "$PLAN"; then
    ERRORS+=("BG1 Validation Gate not checked off in Process Checklist")
  fi
  if ! grep -q '\- \[x\].*BG2 Orchestration' "$PLAN"; then
    ERRORS+=("BG2 Orchestration Gate not checked off in Process Checklist")
  fi
  if ! grep -q '\- \[x\].*BG2\.5' "$PLAN"; then
    ERRORS+=("BG2.5 Externals Gate not checked off in Process Checklist")
  fi
  if ! grep -q '\- \[x\].*BG2-WIRE' "$PLAN"; then
    ERRORS+=("BG2-WIRE Post-Wire Gate not checked off in Process Checklist")
  fi
fi

if [[ ${#ERRORS[@]} -gt 0 ]]; then
  deny_errors "Bootstrap commit blocked: " "Complete all gate checks before committing."
fi

exit 0
