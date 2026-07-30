#!/usr/bin/env bash
# _scaffold-common.sh — Shared convention gate for bootstrap scaffold agents.
# Checks BG1 verdict PASS + branch match.
# Sourced by individual scaffold agent gate scripts.
set -euo pipefail

source "$(dirname "$0")/../../../hooks/lib.sh"

if [[ -z "${PAYLOAD:-}" ]]; then parse_payload; fi
PROJECT_DIR="${PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-.}}"
BRANCH="${BRANCH:-$(get_branch)}"
VERDICTS_DIR="$PROJECT_DIR/.runs/gate-verdicts"
ERRORS=()

check_verdict_gates "bg1" "$VERDICTS_DIR" "$BRANCH"

# Don't exit here — caller may add more checks
# If sourced by a wrapper gate, the wrapper handles deny_errors
