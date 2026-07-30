#!/usr/bin/env bash
# observe-commit-gate.sh — Claude Code PreToolUse hook for Bash commands.
# Blocks final skill commits unless observation epilogue has been performed.
# Data-driven: uses *-context.json + skill.yaml observation config
# to determine which skills need observation enforcement.
# Skills that embed /verify (bootstrap, change, distribute) are exempt —
# verify-report.md proves verify ran — observation handled in epilogue.

set -euo pipefail

source "$(dirname "$0")/lib.sh"
parse_payload

COMMAND=$(read_payload_field "tool_input.command")

# Match `git commit` only as an actual command head — anchored at start
# of $COMMAND or after a shell separator (;, &, |), with whitespace-
# tolerant token boundaries. See #1366 for the bare-substring false-
# positive class this regex closes.
if [[ ! "$COMMAND" =~ (^|[;\&\|])[[:space:]]*git[[:space:]]+commit([[:space:]]|$) ]]; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

# --- Data-driven skill detection ---
# Scan *-context.json for branch match → get active skill
BRANCH=$(get_branch)
SKILL=$(detect_active_skill_for_branch "$BRANCH")

# No skill context for this branch → non-skill branch, allow
if [[ -z "$SKILL" ]]; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

# Check if this skill uses commit-gate enforcement
GATE_MECH=$(get_observation_gate "$SKILL" "gate_mechanism")
if [[ "$GATE_MECH" != "commit-pr-gate" ]]; then
  # friction-skip: post-validation — exit follows authoritative decision (allow-list match, deny path, or successful validation)
  exit 0  # postcondition-only skills don't need commit gate
fi

# Allow WIP commits (only enforce on final commits)
if [[ "$COMMAND" != *"Fix #"* ]] && [[ "$COMMAND" != *"Fix \#"* ]] && [[ "$COMMAND" != *"Automated review-fix"* ]]; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"

# If verify-report.md exists, verify ran — observation handled in epilogue
if [[ -f "$PROJECT_DIR/.runs/verify-report.md" ]]; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

# If observe-result.json exists, check verdict integrity then allow
if [[ -f "$PROJECT_DIR/.runs/observe-result.json" ]]; then
  ERRORS=()
  check_verdict_error
  check_verdict_consistency "$SKILL"
  check_fixlog_verdict_consistency
  if [[ ${#ERRORS[@]} -gt 0 ]]; then
    deny_errors "Observation integrity check failed: " "Re-run the skill epilogue to retry observation."
  fi
  exit 0
fi

# No observation evidence — check state completion for specific feedback
ERRORS=()
check_skill_completion "$SKILL" "$PROJECT_DIR/.runs/${SKILL}-context.json"
if [[ ${#ERRORS[@]} -gt 0 ]]; then
  deny_errors "Commit blocked: " "Complete all required states before final commit."
fi

# No observation evidence found — deny
deny "Observation not performed for /$SKILL. Run the skill epilogue (.claude/patterns/skill-epilogue.md) before the final commit. This ensures template-level issues are detected and filed."
