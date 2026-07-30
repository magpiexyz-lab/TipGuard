#!/usr/bin/env bash
# design-critic.sh — Convention gate for design-critic agent in /verify.
# Called by: skill-agent-gate.sh after declarative checks pass.
# Declarative checks (requires_archetype, requires_traces, scope_condition,
# check_efficiency_directives) are handled by the universal hook.
# This gate only checks EXTRA requirements beyond declarative.
set -euo pipefail

source "$(dirname "$0")/../../../hooks/lib.sh"

if [[ -z "${PAYLOAD:-}" ]]; then parse_payload; fi
PROJECT_DIR="${PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-.}}"
ERRORS=()

check_postcondition_artifacts 0
check_build_result

# Per-page file boundary enforcement
PROMPT=$(extract_prompt)
IS_PER_PAGE=$(python3 -c "
import re, sys
if re.search(r'design-critic-(?!shared)\w+\.json', sys.stdin.read()):
    print('yes')
else:
    print('no')
" <<< "$PROMPT" 2>/dev/null || echo "no")
if [[ "$IS_PER_PAGE" == "yes" ]]; then
  check_file_boundary "design-critic (per-page)"
  check_claimed_shared "design-critic (per-page)"
fi

if [[ ${#ERRORS[@]} -gt 0 ]]; then
  deny_errors "design-critic gate blocked: " "Complete prerequisites before spawning design-critic."
fi

exit 0
