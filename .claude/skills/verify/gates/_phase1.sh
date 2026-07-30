#!/usr/bin/env bash
# _phase1.sh — Shared convention gate for /verify phase1 agents.
# Checks postcondition artifacts from STATE 0 and build result.
# Sourced by individual phase1 agent gate scripts.
set -euo pipefail

source "$(dirname "$0")/../../../hooks/lib.sh"

if [[ -z "${PAYLOAD:-}" ]]; then parse_payload; fi
PROJECT_DIR="${PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-.}}"
ERRORS=()

check_postcondition_artifacts 0
check_build_result

if [[ ${#ERRORS[@]} -gt 0 ]]; then
  deny_errors "Phase 1 agent gate blocked: " "Complete STATE 0 postconditions and build before spawning phase1 agents."
fi

exit 0
