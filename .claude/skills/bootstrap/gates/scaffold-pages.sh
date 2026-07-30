#!/usr/bin/env bash
# scaffold-pages.sh — Convention gate: BG1 + root files + scaffold-libs completion.
set -euo pipefail

source "$(dirname "$0")/_scaffold-common.sh"

# Root files must exist (created by lead in Phase A)
for REQUIRED_FILE in "src/app/layout.tsx" "src/app/not-found.tsx" "src/app/error.tsx"; do
  if [[ ! -f "$PROJECT_DIR/$REQUIRED_FILE" ]]; then
    ERRORS+=("Phase A file '$REQUIRED_FILE' missing — lead must create root files before spawning page agents")
  fi
done

# scaffold-libs must have completed
LIBS_MANIFEST="$PROJECT_DIR/.runs/agent-traces/scaffold-libs.json"
if [[ ! -f "$LIBS_MANIFEST" ]]; then
  ERRORS+=("scaffold-libs manifest missing — scaffold-libs must complete before page agents")
else
  LIBS_STATUS=$(read_json_field "$LIBS_MANIFEST" "status")
  if [[ "$LIBS_STATUS" != "completed" ]]; then
    ERRORS+=("scaffold-libs status is '$LIBS_STATUS', not 'completed' — wait for scaffold-libs to finish")
  fi
fi

if [[ ${#ERRORS[@]} -gt 0 ]]; then
  deny_errors "scaffold-pages gate blocked: " "Complete prerequisites before spawning scaffold-pages."
fi

exit 0
