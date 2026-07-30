#!/usr/bin/env bash
# check-init-context-callers.sh — Static lint for init-context.sh callers.
#
# Scans .claude/{skills,procedures,agents}/**/*.md for invocations of
#   bash .claude/scripts/init-context.sh <skill> '<json>'
# and flags any caller that passes protected fields (skill, branch, timestamp,
# run_id) inside the JSON payload. Those fields are silently dropped by
# init-context.sh per the #941 protected-fields policy — passing them is dead
# code and is the symptom that produced issue #1160 (verify state-0 spec drift).
#
# Output:
#   - findings written to .runs/init-context-caller-findings.jsonl (one JSON
#     per finding) for downstream coherence consumers.
#   - human-readable summary printed to stderr.
#   - exit 0 always (warn-only) — discoverability tool, not a hard gate.
#
# Wired into .claude/scripts/lifecycle-finalize.sh Step 4.5 alongside
# verify-linter.sh. Findings fold into .runs/template-coherence-cache.json.
#
# Use cases:
#   - Catch future spec drift like #1160 (caller passes `skill: <parent>` to
#     attribute Q-scores; should use `attributed_to: <parent>` instead).
#   - Catch new callers that copy a stale pattern.

set -euo pipefail

PROJECT_DIR="$(git rev-parse --show-toplevel 2>/dev/null || echo "${CLAUDE_PROJECT_DIR:-.}")"
cd "$PROJECT_DIR"

OUT=".runs/init-context-caller-findings.jsonl"
mkdir -p "$(dirname "$OUT")"
: > "$OUT"

# Protected fields (must match init-context.sh:78,136 protected set).
PROTECTED='skill|branch|timestamp|run_id'

# Search scope: skills, procedures, agents (where init-context.sh is invoked).
# Use grep -rn for file:line and surface the matched line.
FOUND_COUNT=0
TOTAL_CALLER_COUNT=0

# Find every line that calls init-context.sh in the search scope.
while IFS= read -r match; do
  file="${match%%:*}"
  rest="${match#*:}"
  line_no="${rest%%:*}"
  content="${rest#*:}"
  TOTAL_CALLER_COUNT=$((TOTAL_CALLER_COUNT + 1))

  # Check the matched line for protected fields embedded in JSON keys.
  # Pattern: \"<protected>\":  (escape-quoted JSON key inside bash string)
  if echo "$content" | grep -qE "\\\\\"($PROTECTED)\\\\\":"; then
    # Extract which protected fields were found (deduped).
    # Pattern \"<field>\": → strip leading/trailing escape-quotes and trailing colon,
    # keeping just the bare field name.
    fields_found=$(echo "$content" | grep -oE "\\\\\"($PROTECTED)\\\\\":" | sed -E 's|^\\"||; s|\\":$||' | sort -u | tr '\n' ',' | sed 's/,$//')
    FOUND_COUNT=$((FOUND_COUNT + 1))
    # JSONL row.
    python3 -c "
import json, sys
print(json.dumps({
    'file': sys.argv[1],
    'line': int(sys.argv[2]),
    'protected_fields_passed': sys.argv[3].split(','),
    'matched_line': sys.argv[4][:300],
}))
" "$file" "$line_no" "$fields_found" "$content" >> "$OUT"
    echo "WARN: $file:$line_no — init-context.sh caller passes protected fields: $fields_found" >&2
    echo "      $content" >&2
  fi
done < <(grep -rn "init-context\.sh" .claude/skills/ .claude/procedures/ .claude/agents/ 2>/dev/null || true)

if [[ $FOUND_COUNT -gt 0 ]]; then
  echo "" >&2
  echo "check-init-context-callers.sh: $FOUND_COUNT/$TOTAL_CALLER_COUNT caller(s) pass protected fields." >&2
  echo "  These fields ({skill, branch, timestamp, run_id}) are silently dropped by init-context.sh." >&2
  echo "  Use 'attributed_to' instead for Q-score attribution; the other 3 are immutable identity." >&2
  echo "  See .claude/scripts/init-context.sh:72-73 for design rationale." >&2
  echo "  Findings written to: $OUT" >&2
else
  echo "check-init-context-callers.sh: clean — $TOTAL_CALLER_COUNT caller(s) scanned, no protected-field drops." >&2
fi

# Always exit 0 — this is a warn-only linter, never blocks.
exit 0
