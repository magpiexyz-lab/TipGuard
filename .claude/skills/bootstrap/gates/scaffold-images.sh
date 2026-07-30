#!/usr/bin/env bash
# scaffold-images.sh — Convention gate: BG1 verdict check for scaffold agent.
set -euo pipefail
source "$(dirname "$0")/_scaffold-common.sh"
if [[ ${#ERRORS[@]} -gt 0 ]]; then
  deny_errors "scaffold-images gate blocked: " "Complete BG1 gate before spawning scaffold agents."
fi
exit 0
