#!/usr/bin/env bash
# observer.sh — Convention gate for observer agent in /verify.
# Extracted from agent-state-gate.sh _verify_observer_checks().
# Handles two paths: epilogue (relaxed) and verify (full prerequisites).
set -euo pipefail

source "$(dirname "$0")/../../../hooks/lib.sh"

if [[ -z "${PAYLOAD:-}" ]]; then parse_payload; fi
PROJECT_DIR="${PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-.}}"
TRACES_DIR="${TRACES_DIR:-$PROJECT_DIR/.runs/agent-traces}"
ERRORS=()

# Epilogue path: relaxed requirements for skill-epilogue.md observers
if [[ -f "$PROJECT_DIR/.runs/epilogue-context.json" ]] && \
   [[ ! -f "$PROJECT_DIR/.runs/verify-context.json" ]]; then
  FIX_COUNT=$(grep -cE '^\*\*Fix|^Fix \(' "$PROJECT_DIR/.runs/fix-log.md" 2>/dev/null || echo "0")
  if [ "$FIX_COUNT" -gt 0 ] && [ ! -s "$PROJECT_DIR/.runs/observer-diffs.txt" ]; then
    ERRORS+=("observer-diffs.txt missing or empty — collect diffs before spawning observer (epilogue path)")
  fi
else
  # Verify path: full prerequisites
  check_postcondition_artifacts 4

  if [[ ! -f "$PROJECT_DIR/.runs/e2e-result.json" ]]; then
    ERRORS+=("e2e-result.json not found — E2E tests (STATE 5) must complete before observer")
  fi

  if [[ -f "$PROJECT_DIR/.runs/e2e-result.json" ]]; then
    HAS_TESTING=$(grep -c "testing:" "$PROJECT_DIR/experiment/experiment.yaml" 2>/dev/null || echo "0")
    if [[ "$HAS_TESTING" -gt 0 ]]; then
      E2E_REASON=$(read_json_field "$PROJECT_DIR/.runs/e2e-result.json" "reason")
      if [[ "$E2E_REASON" == "no testing stack" ]]; then
        ERRORS+=("e2e-result.json says 'no testing stack' but experiment.yaml has stack.testing — STATE 5 was not executed correctly")
      elif [[ "$E2E_REASON" == "unrecognized test runner" ]]; then
        ERRORS+=("e2e-result.json says 'unrecognized test runner' — check stack.services[].testing value is one of {playwright, vitest}")
      fi
    fi
  fi

  FIX_COUNT=$(grep -cE '^\*\*Fix|^Fix \(' "$PROJECT_DIR/.runs/fix-log.md" 2>/dev/null || echo "0")
  if [ "$FIX_COUNT" -gt 0 ] && [ ! -s "$PROJECT_DIR/.runs/observer-diffs.txt" ]; then
    ERRORS+=("observer-diffs.txt missing or empty — run diff collection script before spawning observer")
  fi
fi

if [[ ${#ERRORS[@]} -gt 0 ]]; then
  deny_errors "observer gate blocked: " "Complete prerequisites before spawning observer."
fi

exit 0
