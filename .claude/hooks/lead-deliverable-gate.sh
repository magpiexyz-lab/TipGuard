#!/usr/bin/env bash
# lead-deliverable-gate.sh — PreToolUse Agent matcher hook.
#
# Closes #1152 enforcement layer 1: denies Agent invocations whose prompt mentions
# any artifact declared in .claude/patterns/lead-only-artifacts.json by path.
# These artifacts require the lead's in-memory execution context to produce
# correctly (e.g., Step 5a Q1/Q2/Q3 retrospective). Delegating to a spawned
# subagent produces structurally weaker output (#1152 root cause).
#
# Detection: PreToolUse Agent payload contains tool_input.prompt; this hook
# extracts the prompt via extract_prompt() and unconditionally denies if the
# prompt contains any lead-only artifact path by literal substring match.
#
# Round-2 caveat R2-C1+C2: unconditional path-match (no verb regex). Verb
# allowlists are bypassable by paraphrase (write|create|generate|populate|...);
# verb denylists generate false positives on legitimate read prompts. Both fail
# to enforce the lead-only invariant. The simpler policy — "the path may not
# appear in any Agent prompt" — has clearer semantics: the lead must read these
# files in its own session and pass relevant *content* to subagents inline,
# never the path.
#
# MODE toggle (#1152 follow-up will flip):
#   MODE="warn" — emit stderr WARN, exit 0 (does not block); soak window.
#   MODE="deny" — emit stderr DENY, exit 2 (blocks the Agent invocation).
#
# Soak rationale (mirrors agent-trace-write-gate.sh PR4 pattern):
# Pre-flight audit (.claude/scripts/audit-lead-deliverable-references.sh)
# greps every skill state file + agent .md for legitimate Agent prompts that
# legitimately mention these paths. After audit confirms zero false positives,
# flip this single line to MODE="deny" in a follow-up commit.

set -euo pipefail

MODE="warn"

source "$(dirname "$0")/lib.sh"
parse_payload

PROMPT=$(extract_prompt)
if [[ -z "$PROMPT" ]]; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || echo .)}"
MANIFEST="$PROJECT_DIR/.claude/patterns/lead-only-artifacts.json"
if [[ ! -f "$MANIFEST" ]]; then
  # Manifest absent → no policy to enforce → allow.
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

# Extract every artifact path; one path per line.
PATHS=$(python3 -c "
import json, sys
try:
    m = json.load(open('$MANIFEST'))
    for a in m.get('artifacts', []):
        p = a.get('path', '')
        if p:
            print(p)
except Exception as e:
    print('', file=sys.stderr)
" 2>/dev/null || true)

if [[ -z "$PATHS" ]]; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

VIOLATION=""
while IFS= read -r path; do
  [[ -z "$path" ]] && continue
  if [[ "$PROMPT" == *"$path"* ]]; then
    VIOLATION="$path"
    break
  fi
done <<< "$PATHS"

if [[ -z "$VIOLATION" ]]; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

MSG="lead-deliverable-gate: Agent prompt mentions lead-only artifact: $VIOLATION

This artifact is declared lead-only in .claude/patterns/lead-only-artifacts.json
because producing it correctly requires the lead's in-memory execution context
(hook-friction events, deviation reasoning, workarounds absorbed by changing
approach) — context that does not exist in any artifact and cannot be
reconstructed from agent traces alone.

If you intended to:
  - Read the artifact's contents from a prior run: do so in the lead session
    and pass relevant data to the Agent inline (NOT the file path).
  - Write the artifact: use the Write tool directly from the lead session,
    not as a deliverable for a spawned Agent.

See .claude/patterns/observation-phase.md Step 5a for the canonical workflow.
Closes #1152."

case "$MODE" in
  warn)
    echo "WARN: $MSG" >&2
    # friction-skip: trivial-fast-path — input absent or non-applicable
    exit 0
    ;;
  deny)
    deny "$MSG"
    ;;
  *)
    echo "ERROR: lead-deliverable-gate.sh — unknown MODE=$MODE (expected 'warn' or 'deny')" >&2
    exit 1
    ;;
esac
