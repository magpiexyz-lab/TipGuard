#!/usr/bin/env bash
# audit-lead-deliverable-references.sh — pre-flight audit for lead-deliverable-gate.sh.
#
# Greps every skill state-*.md, agent .md, pattern .md for legitimate references
# to lead-only artifact paths declared in lead-only-artifacts.json. Output
# tells you whether it's safe to flip lead-deliverable-gate.sh from MODE="warn"
# to MODE="deny" without breaking existing flows.
#
# Each "hit" needs human review:
#   - Is this a legitimate read of the file (e.g., compliance-audit reading
#     after the lead writes it)? → not a problem, but the AGENT is the one
#     spawning that read; check if the path appears IN AGENT PROMPTS.
#   - Is this prose documenting the lead-only constraint? → fine.
#   - Is this an Agent prompt asking the agent to PRODUCE the file? → that's
#     the bug we want to block; the prompt source must be updated.
#
# Run: bash .claude/scripts/audit-lead-deliverable-references.sh
# Exit 0 always; this is informational. Returns counts and file:line:context.

set -euo pipefail

PROJECT_DIR="$(git rev-parse --show-toplevel 2>/dev/null || echo "${CLAUDE_PROJECT_DIR:-.}")"
MANIFEST="$PROJECT_DIR/.claude/patterns/lead-only-artifacts.json"

if [[ ! -f "$MANIFEST" ]]; then
  echo "ERROR: $MANIFEST not found." >&2
  exit 1
fi

# Extract every artifact path
PATHS=$(python3 -c "
import json
m = json.load(open('$MANIFEST'))
for a in m.get('artifacts', []):
    p = a.get('path', '')
    if p:
        print(p)
")

echo "Pre-flight audit: lead-deliverable-gate.sh"
echo "Manifest: $MANIFEST"
echo ""

TOTAL_HITS=0
for path in $PATHS; do
  echo "============================================================"
  echo "Artifact: $path"
  echo "============================================================"

  # Skill state files (where Agent invocations live)
  echo ""
  echo "[skill state files] — Agent prompt content lives in these files."
  echo "Each hit means the lead might pass this path to a spawned Agent."
  echo "Review needed: if the prompt asks the agent to PRODUCE the file → bug."
  HITS=$(grep -rn "$path" "$PROJECT_DIR/.claude/skills/" 2>/dev/null || true)
  if [[ -n "$HITS" ]]; then
    echo "$HITS"
    HIT_COUNT=$(echo "$HITS" | wc -l | tr -d ' ')
    TOTAL_HITS=$((TOTAL_HITS + HIT_COUNT))
  else
    echo "  (no hits)"
  fi

  echo ""
  echo "[agent definition files] — Agent .md files."
  echo "Each hit is a negative-deliverable violation unless the agent"
  echo "explicitly documents 'Evidence collection only' or 'lead writes'."
  HITS=$(grep -rn "$path" "$PROJECT_DIR/.claude/agents/" 2>/dev/null || true)
  if [[ -n "$HITS" ]]; then
    echo "$HITS"
    HIT_COUNT=$(echo "$HITS" | wc -l | tr -d ' ')
    TOTAL_HITS=$((TOTAL_HITS + HIT_COUNT))
  else
    echo "  (no hits)"
  fi

  echo ""
  echo "[shared patterns] — pattern .md files."
  echo "Hits are usually prose; review if any flow asks an agent to write the file."
  HITS=$(grep -rn "$path" "$PROJECT_DIR/.claude/patterns/" 2>/dev/null | grep -v "lead-only-artifacts.json" || true)
  if [[ -n "$HITS" ]]; then
    echo "$HITS"
    HIT_COUNT=$(echo "$HITS" | wc -l | tr -d ' ')
    TOTAL_HITS=$((TOTAL_HITS + HIT_COUNT))
  else
    echo "  (no hits)"
  fi
  echo ""
done

echo "============================================================"
echo "TOTAL hits across skills + agents + patterns: $TOTAL_HITS"
echo ""
echo "If all hits are read-only (compliance/cross-checks), prose docs, or"
echo "this script itself, safely flip MODE=warn → MODE=deny in:"
echo "  .claude/hooks/lead-deliverable-gate.sh"
echo ""
echo "Otherwise, update each violating Agent prompt to NOT include the path,"
echo "then re-run this audit. Repeat until zero violation."
