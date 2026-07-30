#!/usr/bin/env bash
# skill-write-gate.sh — Universal PreToolUse hook for Write/Edit tools.
# Delegates write protection to convention gates at .claude/skills/<skill>/gates/write.sh.
# Replaces: bootstrap-root-protection.sh (PR 5, v2 migration step 5/8).

set -euo pipefail

source "$(dirname "$0")/lib.sh"
parse_payload

FILE_PATH=$(read_payload_field "tool_input.file_path")
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"

# ── Detect active skill for the CURRENT branch ──
# Use branch-filtered detection to prevent cross-branch interference.
# Without branch filter, a stale context file from a different branch could
# incorrectly trigger write protection (e.g., bootstrap protection on main).
BRANCH=$(get_branch)
ACTIVE_SKILL=$(detect_active_skill_for_branch "$BRANCH")

if [[ -z "$ACTIVE_SKILL" ]]; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

# ── Convention gate: .claude/skills/<skill>/gates/write.sh ──
GATE_SCRIPT="$PROJECT_DIR/.claude/skills/$ACTIVE_SKILL/gates/write.sh"

if [[ ! -f "$GATE_SCRIPT" ]]; then
  # friction-skip: post-validation — exit follows authoritative decision (allow-list match, deny path, or successful validation)
  exit 0  # No write gate for this skill
fi

# Run gate as subprocess with exported env vars
export FILE_PATH PROJECT_DIR PAYLOAD
GATE_OUTPUT=$(bash "$GATE_SCRIPT" 2>&1) || {
  # Gate denied — forward its message
  echo "$GATE_OUTPUT" >&2
  exit 2
}

# friction-skip: trivial-fast-path — input absent or non-applicable
exit 0
