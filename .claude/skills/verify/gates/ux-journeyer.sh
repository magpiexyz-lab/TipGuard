#!/usr/bin/env bash
# ux-journeyer.sh — Convention gate for ux-journeyer agent in /verify.
# Called by: skill-agent-gate.sh after declarative checks pass.
# Declarative checks (requires_archetype=web-app, requires_traces for
# design-critic + design-consistency-checker, check_efficiency_directives)
# are handled by the universal hook.
# This gate checks EXTRA requirements: postconditions, tier1 retry,
# scope-conditional consistency checker.
set -euo pipefail

source "$(dirname "$0")/../../../hooks/lib.sh"

if [[ -z "${PAYLOAD:-}" ]]; then parse_payload; fi
PROJECT_DIR="${PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-.}}"
TRACES_DIR="${TRACES_DIR:-$PROJECT_DIR/.runs/agent-traces}"
ERRORS=()

check_postcondition_artifacts 0
check_build_result

# design-critic: check retry completion
check_tier1_retry_complete "design-critic-*" "$TRACES_DIR"
check_tier1_retry_complete "design-critic" "$TRACES_DIR"

# design-consistency-checker prerequisite (scope-conditional, beyond declarative)
UX_SCOPE=$(read_json_field "$PROJECT_DIR/.runs/verify-context.json" "scope")
UX_ARCH=$(read_json_field "$PROJECT_DIR/.runs/verify-context.json" "archetype")
if [[ "$UX_SCOPE" =~ ^(full|visual)$ ]] && [[ "$UX_ARCH" == "web-app" ]]; then
  if [[ ! -f "$TRACES_DIR/design-consistency-checker.json" ]]; then
    ERRORS+=("design-consistency-checker.json trace missing — spawn consistency checker before ux-journeyer")
  else
    require_trace_verdict "$TRACES_DIR/design-consistency-checker.json" "consistency checker may still be running or exhausted turns"
  fi
fi

if [[ ${#ERRORS[@]} -gt 0 ]]; then
  deny_errors "ux-journeyer gate blocked: " "Complete prerequisites before spawning ux-journeyer."
fi

exit 0
