#!/usr/bin/env bash
# phase-boundary-gate.sh — Claude Code PreToolUse hook for Write, Edit, Bash.
# Enforces phase boundaries during multi-phase skill orchestration.
# Reads .runs/pipeline-phase.json (written by run-skill.sh) and prevents
# the LLM from performing operations outside the current phase's scope.
# When pipeline-phase.json is absent (direct /skill usage), exits 0 — zero impact.
set -euo pipefail

source "$(dirname "$0")/lib.sh"
parse_payload

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
SIGNAL="$PROJECT_DIR/.runs/pipeline-phase.json"

# --- CRITICAL: no signal file → no enforcement ---
if [[ ! -f "$SIGNAL" ]]; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

# --- Extract signal fields (phase, state_range, skill) ---
# read_json_field can't read arrays, so use a single python3 call.
eval "$(python3 -c "
import json
try:
    d = json.load(open('$SIGNAL'))
    print('PHASE=%s' % d.get('phase', ''))
    sr = d.get('state_range', [])
    print('RANGE_MIN=%s' % (sr[0] if len(sr) > 0 else ''))
    print('RANGE_MAX=%s' % (sr[1] if len(sr) > 1 else ''))
    print('SIGNAL_SKILL=%s' % d.get('skill', ''))
except Exception:
    print('PHASE=')
    print('RANGE_MIN=')
    print('RANGE_MAX=')
    print('SIGNAL_SKILL=')
" 2>/dev/null)"

# Fail-open if signal file is malformed.
# #1349 follow-up: empty PHASE means signal-file parse failed silently.
# Friction-log so the parse-failure is observable in retrospectives.
if [[ -z "$PHASE" ]]; then
  _write_hook_friction "phase-boundary-gate: empty PHASE after parse — signal file $SIGNAL malformed or absent; failing open."
  exit 0
fi

# --- Detect tool type ---
TOOL_NAME=$(read_payload_field "tool_name")

# ============================================================
# Write / Edit checks
# ============================================================
if [[ "$TOOL_NAME" == "Write" || "$TOOL_NAME" == "Edit" ]]; then
  FILE_PATH=$(read_payload_field "tool_input.file_path")

  # -- Plan-phase src/ protection --
  PHASE_LOWER=$(echo "$PHASE" | tr '[:upper:]' '[:lower:]')
  if [[ "$PHASE_LOWER" == "plan" ]]; then
    if [[ "$FILE_PATH" == */src/* || "$FILE_PATH" == src/* ]]; then
      deny "Plan phase: cannot write to src/ — implementation happens in next phase"
    fi
  fi

  # -- Context JSON completed_states protection --
  if [[ "$FILE_PATH" == *-context.json ]]; then
    extract_write_content
    if [[ "$CONTENT" == *"completed_states"* ]]; then
      deny "Cannot directly modify context JSON completed_states — use advance-state.sh"
    fi
  fi

  exit 0
fi

# ============================================================
# Bash checks
# ============================================================
if [[ "$TOOL_NAME" == "Bash" ]]; then
  COMMAND=$(read_payload_field "tool_input.command")

  # Only fire on actual advance-state.sh invocations at command-head position
  # (#1223). See state-completion-gate.sh for the full rationale.
  _PROJECT_DIR_GATE="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || echo .)}"
  _INVOCATION_HELPER="$_PROJECT_DIR_GATE/.claude/scripts/lib/check-advance-state-invocation.py"
  if [[ ! -f "$_INVOCATION_HELPER" ]]; then
    # Helper missing — fall back to legacy grep so we do not over-block.
    if ! printf '%s' "$COMMAND" | grep -qE 'bash\s+\S*advance-state\.sh\s'; then
      # friction-skip: trivial-fast-path — input absent or non-applicable
      exit 0
    fi
    parse_advance_state_args
  else
    if ! printf '%s' "$COMMAND" | python3 "$_INVOCATION_HELPER"; then
      # friction-skip: trivial-fast-path — input absent or non-applicable
      exit 0
    fi
    SKILL=$(printf '%s' "$COMMAND" | python3 "$_INVOCATION_HELPER" --print-skill)
    STATE_ID=$(printf '%s' "$COMMAND" | python3 "$_INVOCATION_HELPER" --print-state-id)
  fi

  if [[ -z "$SKILL" || -z "$STATE_ID" ]]; then
    # friction-skip: trivial-fast-path — input absent or non-applicable
    exit 0
  fi

  # Need state_range values for range check
  if [[ -z "$RANGE_MIN" || -z "$RANGE_MAX" ]]; then
    # friction-skip: trivial-fast-path — input absent or non-applicable
    exit 0
  fi

  # Registry-based range check — state IDs can be strings ("1_5", "2a"),
  # so we use the registry key order as canonical sequence.
  REGISTRY="$PROJECT_DIR/.claude/patterns/state-registry.json"
  if [[ ! -f "$REGISTRY" ]]; then
    # friction-skip: trivial-fast-path — input absent or non-applicable
    exit 0
  fi

  RANGE_RESULT=$(python3 -c "
import json, sys
try:
    registry = json.load(open('$REGISTRY'))
    skill_states = list(registry.get('$SKILL', {}).keys())
    state = '$STATE_ID'
    rmin = str($RANGE_MIN) if '$RANGE_MIN'.isdigit() else '$RANGE_MIN'
    rmax = str($RANGE_MAX) if '$RANGE_MAX'.isdigit() else '$RANGE_MAX'
    if state not in skill_states or rmin not in skill_states or rmax not in skill_states:
        print('OK')
        # friction-skip: post-validation — exit follows authoritative decision (allow-list match, deny path, or successful validation)
        sys.exit(0)
    si = skill_states.index(state)
    lo = skill_states.index(rmin)
    hi = skill_states.index(rmax)
    if si < lo:
        print('BELOW')
    elif si > hi:
        print('ABOVE')
    else:
        print('OK')
except Exception:
    print('OK')
" 2>/dev/null || echo "OK")

  if [[ "$RANGE_RESULT" == "BELOW" ]]; then
    deny "Phase boundary: cannot re-run state $STATE_ID — below current phase range [$RANGE_MIN, $RANGE_MAX]"
  elif [[ "$RANGE_RESULT" == "ABOVE" ]]; then
    deny "Phase boundary: state $STATE_ID is above current phase range [$RANGE_MIN, $RANGE_MAX] — belongs to a later phase"
  fi

  exit 0
fi

# --- Not a relevant tool ---
exit 0
