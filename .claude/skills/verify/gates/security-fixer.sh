#!/usr/bin/env bash
# security-fixer.sh — Convention gate for security-fixer agent in /verify.
# Called by: skill-agent-gate.sh after declarative checks pass.
# Declarative checks (requires_traces for build-info-collector,
# check_efficiency_directives) are handled by the universal hook.
# This gate checks EXTRA requirements: postconditions, Phase 2 traces,
# tier1 retry, hard gate, scope=security behavior-verifier.
set -euo pipefail

source "$(dirname "$0")/../../../hooks/lib.sh"

if [[ -z "${PAYLOAD:-}" ]]; then parse_payload; fi
PROJECT_DIR="${PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-.}}"
TRACES_DIR="${TRACES_DIR:-$PROJECT_DIR/.runs/agent-traces}"
ERRORS=()

check_postcondition_artifacts 3
check_postcondition_artifacts "3d"

# Phase 2 traces (scope-conditional — not in manifest declarative)
SF_SCOPE=$(read_json_field "$PROJECT_DIR/.runs/verify-context.json" "scope")
SF_ARCH=$(read_json_field "$PROJECT_DIR/.runs/verify-context.json" "archetype")
if [[ "$SF_ARCH" == "web-app" && ( "$SF_SCOPE" == "full" || "$SF_SCOPE" == "visual" ) ]]; then
  for AGENT in design-critic ux-journeyer; do
    if [[ ! -f "$TRACES_DIR/$AGENT.json" ]]; then
      ERRORS+=("$AGENT.json trace missing — Phase 2 agent incomplete (scope=$SF_SCOPE, archetype=$SF_ARCH)")
    else
      require_trace_verdict "$TRACES_DIR/$AGENT.json" "agent may still be running or exhausted turns"
      check_trace_run_id "$TRACES_DIR/$AGENT.json"
    fi
  done
fi

# Tier 1 retry: ux-journeyer must complete
check_tier1_retry_complete "ux-journeyer" "$TRACES_DIR"

# HARD GATE: design-ux-merge.json verdict must not be "fail"
if [[ "$SF_ARCH" == "web-app" && ( "$SF_SCOPE" == "full" || "$SF_SCOPE" == "visual" ) ]]; then
  if [[ -f "$PROJECT_DIR/.runs/design-ux-merge.json" ]]; then
    MERGE_VERDICT=$(read_json_field "$PROJECT_DIR/.runs/design-ux-merge.json" "verdict")
    if [[ "$MERGE_VERDICT" == "fail" ]]; then
      ERRORS+=("design-ux-merge.json verdict=fail — hard gate failure, skip to STATE 7")
    fi
  fi
fi

# scope=security requires behavior-verifier (not in manifest declarative)
if [[ "$SF_SCOPE" == "security" ]]; then
  if [[ ! -f "$TRACES_DIR/behavior-verifier.json" ]]; then
    ERRORS+=("behavior-verifier.json trace missing — Phase 1 agent incomplete (scope=$SF_SCOPE)")
  fi
  require_trace_verdict "$TRACES_DIR/behavior-verifier.json" "agent may still be running or exhausted turns"
  check_trace_run_id "$TRACES_DIR/behavior-verifier.json"
fi

if [[ ${#ERRORS[@]} -gt 0 ]]; then
  deny_errors "security-fixer gate blocked: " "Complete prerequisites before spawning security-fixer."
fi

exit 0
