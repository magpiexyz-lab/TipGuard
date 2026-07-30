#!/usr/bin/env bash
# quality-fixer.sh — Convention gate for quality-fixer agent in /verify.
# Called by: skill-agent-gate.sh after declarative checks pass.
# Declarative checks (requires_traces for build-info-collector,
# check_efficiency_directives) are handled by the universal hook.
# This gate checks EXTRA requirements: postconditions, Phase 2 traces,
# tier1 retry, hard gate, quality-merge presence.
set -euo pipefail

source "$(dirname "$0")/../../../hooks/lib.sh"

if [[ -z "${PAYLOAD:-}" ]]; then parse_payload; fi
PROJECT_DIR="${PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-.}}"
TRACES_DIR="${TRACES_DIR:-$PROJECT_DIR/.runs/agent-traces}"
ERRORS=()

# Check STATE 3 postconditions (design-ux-merge.json) AND STATE 3d postconditions (quality-merge.json)
check_postcondition_artifacts 3
check_postcondition_artifacts "3d"

# Phase 2 traces (scope-conditional)
QF_SCOPE=$(read_json_field "$PROJECT_DIR/.runs/verify-context.json" "scope")
QF_ARCH=$(read_json_field "$PROJECT_DIR/.runs/verify-context.json" "archetype")
if [[ "$QF_ARCH" == "web-app" && ( "$QF_SCOPE" == "full" || "$QF_SCOPE" == "visual" ) ]]; then
  for AGENT in design-critic ux-journeyer accessibility-scanner design-consistency-checker; do
    if [[ ! -f "$TRACES_DIR/$AGENT.json" ]]; then
      ERRORS+=("$AGENT.json trace missing — prerequisite agent incomplete (scope=$QF_SCOPE, archetype=$QF_ARCH)")
    else
      require_trace_verdict "$TRACES_DIR/$AGENT.json" "agent may still be running or exhausted turns"
      check_trace_run_id "$TRACES_DIR/$AGENT.json"
    fi
  done
fi

# Tier 1 retry: ux-journeyer must complete
check_tier1_retry_complete "ux-journeyer" "$TRACES_DIR"

# HARD GATE: design-ux-merge.json verdict must not be "fail"
if [[ "$QF_ARCH" == "web-app" && ( "$QF_SCOPE" == "full" || "$QF_SCOPE" == "visual" ) ]]; then
  if [[ -f "$PROJECT_DIR/.runs/design-ux-merge.json" ]]; then
    MERGE_VERDICT=$(read_json_field "$PROJECT_DIR/.runs/design-ux-merge.json" "verdict")
    if [[ "$MERGE_VERDICT" == "fail" ]]; then
      ERRORS+=("design-ux-merge.json verdict=fail — hard gate failure, skip to STATE 7")
    fi
  fi
fi

# quality-merge.json must exist (written by STATE 3d before spawn)
if [[ ! -f "$PROJECT_DIR/.runs/quality-merge.json" ]]; then
  ERRORS+=("quality-merge.json missing — STATE 3d merge step incomplete")
fi

if [[ ${#ERRORS[@]} -gt 0 ]]; then
  deny_errors "quality-fixer gate blocked: " "Complete prerequisites before spawning quality-fixer."
fi

exit 0
