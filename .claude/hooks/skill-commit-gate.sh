#!/usr/bin/env bash
# skill-commit-gate.sh — Universal PreToolUse hook for Bash (git commit).
# Framework defaults (postconditions, BLOCK verdicts, completion) +
# convention gates at .claude/skills/<skill>/gates/commit.sh.
# Replaces: change-commit-gate.sh + bootstrap-commit-gate.sh (PR 5, v2 migration step 5/8).

set -euo pipefail

# Source lifecycle-lib.sh for resolve_framework_manifest (issue #1006).
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../scripts" && pwd)"
source "$_SCRIPT_DIR/lifecycle-lib.sh"

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

BRANCH=$(get_branch)
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"

# ── Detect active skill for this branch ──
ACTIVE_SKILL=$(detect_active_skill_for_branch "$BRANCH")

if [[ -z "$ACTIVE_SKILL" ]]; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

# ── Load manifest ──
# ACTIVE_SKILL is the context.json `skill` field, which is MODE-QUALIFIED for
# mode-qualified runs (iterate-cross), while the framework manifest file is
# named after the BASE skill only (iterate). Resolving with the qualified name
# pointed at a nonexistent path and fail-opened the whole hook for those runs
# (flagged in #1990's closure; same fix pattern as lifecycle-finalize.sh's
# resolution preamble). Registry keys and ctx paths still want the QUALIFIED
# name — only the manifest resolution uses the base skill.
read -r BASE_SKILL _SKILL_MODE <<< "$(resolve_skill_dir "$ACTIVE_SKILL")"
MANIFEST=$(resolve_framework_manifest "$BASE_SKILL")

if [[ ! -f "$MANIFEST" ]]; then
  # No manifest = no active skill lifecycle — allow
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

# ── Skills with commit enforcement handled elsewhere ──
# /upgrade commits are allowed here — observation enforced by observe-commit-gate.sh
# (matches old change-commit-gate.sh behavior)
if [[ "$ACTIVE_SKILL" == "upgrade" ]]; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

# ── MANIFEST PATH: Framework defaults ──
CTX="$PROJECT_DIR/.runs/${ACTIVE_SKILL}-context.json"
# Use verify-context.json for verify skill
if [[ "$ACTIVE_SKILL" == "verify" ]]; then
  CTX="$PROJECT_DIR/.runs/verify-context.json"
fi

ERRORS=()

# Framework default 1: Re-run postconditions
rerun_postconditions "$ACTIVE_SKILL"

# Framework default 2: BLOCK verdict check
check_block_verdicts

# Framework default 3: State completion check
check_skill_completion "$ACTIVE_SKILL" "$CTX"

# ── Convention gate: .claude/skills/<skill>/gates/commit.sh ──
# Skill DIRECTORIES are base-named (.claude/skills/iterate/, no iterate-cross/),
# so the gate path uses BASE_SKILL; the exported SKILL env stays qualified.
GATE_SCRIPT="$PROJECT_DIR/.claude/skills/$BASE_SKILL/gates/commit.sh"

if [[ -f "$GATE_SCRIPT" ]]; then
  export PAYLOAD SKILL="$ACTIVE_SKILL" PROJECT_DIR BRANCH COMMAND
  GATE_OUTPUT=$(bash "$GATE_SCRIPT" 2>&1) || {
    [[ -n "$GATE_OUTPUT" ]] && ERRORS+=("$GATE_OUTPUT")
  }
fi

# ── Deny or allow ──
if [[ ${#ERRORS[@]} -gt 0 ]]; then
  deny_errors "Commit blocked ($ACTIVE_SKILL): " "Complete prerequisite checks before committing."
fi

exit 0
