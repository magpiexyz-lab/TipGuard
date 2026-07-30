#!/usr/bin/env bash
# scaffold-wire.sh — Convention gate: BG1 + BG2 verdict for wire agent.
set -euo pipefail

source "$(dirname "$0")/_scaffold-common.sh"

# BG2 verdict must also exist
check_verdict_gates "bg2" "$VERDICTS_DIR"

if [[ ${#ERRORS[@]} -gt 0 ]]; then
  deny_errors "scaffold-wire gate blocked: " "Complete BG1 and BG2 gates before spawning scaffold-wire."
fi

exit 0
