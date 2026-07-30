#!/usr/bin/env bash
# run-skill.sh — Generic skill orchestration for MVP template.
# Splits skills into multiple claude CLI conversations based on declarative configs.
# Usage: ./run-skill.sh <skill> [args...]
# Env:   RESUME_FROM=<phase_number> to skip earlier phases
set -euo pipefail

SKILL="${1:-}"
shift || true
ARGS="$*"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG="$PROJECT_DIR/.claude/orchestration/$SKILL.json"
RESUME_FROM="${RESUME_FROM:-0}"

# --- Validation ---
if [[ -z "$SKILL" ]]; then
  echo "Usage: ./run-skill.sh <skill> [args...]"
  echo "Env:   RESUME_FROM=<N> to resume from phase N"
  exit 1
fi

# --- Path A: No orchestration config → direct exec ---
if [[ ! -f "$CONFIG" ]]; then
  echo "[orchestrator] No config for '$SKILL' — running directly"
  exec claude --effort max -- "/$SKILL $ARGS"
fi

# --- Read config metadata ---
eval "$(python3 -c "
import json, sys
config = json.load(open(sys.argv[1]))
phases = config['phases']
print('PHASE_COUNT=' + str(len(phases)))
single = 1 if (len(phases) == 1 and phases[0].get('interactive', False)) else 0
print('SINGLE_INTERACTIVE=' + str(single))
" "$CONFIG")"

# --- Path B: Single interactive phase → degenerate, direct exec ---
if [[ "$SINGLE_INTERACTIVE" == "1" ]]; then
  echo "[orchestrator] Single interactive phase for '$SKILL' — running directly"
  exec claude --effort max -- "/$SKILL $ARGS"
fi

# --- Path C: Full orchestration loop ---
echo "[orchestrator] Running '$SKILL' with $PHASE_COUNT phases (RESUME_FROM=$RESUME_FROM)"

FIRST_NON_SKIPPED=-1
LAST_COMPLETED=-1

for (( i=0; i<PHASE_COUNT; i++ )); do
  # Skip phases before RESUME_FROM
  if [[ $i -lt $RESUME_FROM ]]; then
    echo "[orchestrator] Skipping phase $i (RESUME_FROM=$RESUME_FROM)"
    continue
  fi

  # Track first non-skipped phase
  [[ $FIRST_NON_SKIPPED -lt 0 ]] && FIRST_NON_SKIPPED=$i

  # Extract phase config
  eval "$(python3 -c "
import json, sys
config = json.load(open(sys.argv[1]))
phase = config['phases'][int(sys.argv[2])]
print('PHASE_NAME=' + str(phase['name']))
print('PHASE_INTERACTIVE=' + str(1 if phase.get('interactive', False) else 0))
print('PHASE_BUDGET=' + str(phase.get('max_budget', 50)))
sr = phase['state_range']
print('STATE_START=' + str(sr[0]))
print('STATE_END=' + str(sr[1]))
" "$CONFIG" "$i")"

  echo ""
  echo "================================================================"
  echo "[orchestrator] Phase $((i+1))/$PHASE_COUNT: $PHASE_NAME (states $STATE_START-$STATE_END)"
  echo "================================================================"

  # Write pipeline-phase.json signal file
  python3 -c "
import json, sys, datetime
config = json.load(open(sys.argv[1]))
phase = config['phases'][int(sys.argv[2])]
signal = {
    'skill': sys.argv[3],
    'phase': phase['name'],
    'phase_index': int(sys.argv[2]),
    'total_phases': int(sys.argv[4]),
    'state_range': phase['state_range'],
    'started': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
}
json.dump(signal, open('.claude/pipeline-phase.json', 'w'), indent=2)
" "$CONFIG" "$i" "$SKILL" "$PHASE_COUNT"

  # Launch claude
  CLAUDE_EXIT=0
  if [[ "$PHASE_INTERACTIVE" == "1" && $i -eq $FIRST_NON_SKIPPED ]]; then
    # Interactive mode: user gets terminal control
    echo "[orchestrator] Interactive phase — launching terminal session"
    claude --effort max --permission-mode bypassPermissions -- "/$SKILL $ARGS" || CLAUDE_EXIT=$?
  else
    # Headless mode: automated execution with budget cap
    SYSTEM_PROMPT="[ORCHESTRATOR] Phase $((i+1))/$PHASE_COUNT ($PHASE_NAME). Read .claude/patterns/checkpoint-resumption.md first. Resume from checkpoint. Execute states $STATE_START-$STATE_END ONLY. Do NOT start from STATE 0. Do NOT re-create context JSON."
    echo "[orchestrator] Headless phase — budget \$$PHASE_BUDGET"
    claude -p \
      --effort max \
      --permission-mode acceptEdits \
      --max-budget-usd "$PHASE_BUDGET" \
      --append-system-prompt "$SYSTEM_PROMPT" \
      -- "Resume /$SKILL from checkpoint" || CLAUDE_EXIT=$?
  fi

  # Check claude exit code
  if [[ $CLAUDE_EXIT -ne 0 ]]; then
    echo "[orchestrator] ERROR: claude exited with code $CLAUDE_EXIT in phase $PHASE_NAME"
    python3 -c "
import json, sys, datetime
state = {
    'skill': sys.argv[1],
    'total_phases': int(sys.argv[2]),
    'last_completed_phase': int(sys.argv[3]),
    'status': 'failed',
    'failed_phase': int(sys.argv[4]),
    'failure_reason': 'claude_exit_' + sys.argv[5],
    'finished': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
}
json.dump(state, open('.claude/pipeline-state.json', 'w'), indent=2)
" "$SKILL" "$PHASE_COUNT" "$LAST_COMPLETED" "$i" "$CLAUDE_EXIT"
    exit $CLAUDE_EXIT
  fi

  # Run phase gate (skip if last phase with null gate — phase-gate.py handles null)
  echo "[orchestrator] Running gate check for phase $PHASE_NAME..."
  if ! python3 "$PROJECT_DIR/.claude/scripts/phase-gate.py" "$CONFIG" "$i"; then
    echo "[orchestrator] ERROR: Gate check failed for phase $PHASE_NAME"
    python3 -c "
import json, sys, datetime
state = {
    'skill': sys.argv[1],
    'total_phases': int(sys.argv[2]),
    'last_completed_phase': int(sys.argv[3]),
    'status': 'failed',
    'failed_phase': int(sys.argv[4]),
    'failure_reason': 'gate',
    'finished': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
}
json.dump(state, open('.claude/pipeline-state.json', 'w'), indent=2)
" "$SKILL" "$PHASE_COUNT" "$LAST_COMPLETED" "$i"
    exit 1
  fi

  echo "[orchestrator] Phase $PHASE_NAME — gate passed ✓"
  LAST_COMPLETED=$i
done

# Write final completion state
python3 -c "
import json, sys, datetime
state = {
    'skill': sys.argv[1],
    'total_phases': int(sys.argv[2]),
    'last_completed_phase': int(sys.argv[3]),
    'status': 'complete',
    'finished': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
}
json.dump(state, open('.claude/pipeline-state.json', 'w'), indent=2)
" "$SKILL" "$PHASE_COUNT" "$LAST_COMPLETED"

echo ""
echo "[orchestrator] $SKILL completed successfully ($PHASE_COUNT phases)"
