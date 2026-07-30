#!/usr/bin/env bash
# source_identity_validator.sh — bash wrapper around the Python validator.
#
# Sourced by .sh trace writers that accept --source-run-id / --source-skill
# overrides (AOC v1.2). Provides a single function:
#
#   validate_source_identity <source_run_id> <source_skill> [<agent>]
#       returns 0 when valid (or both flags empty); non-zero when any of
#       R1-R4 fails. Writes diagnostics to stderr.
#
# The actual validation logic lives in
# .claude/scripts/lib/source_identity_validator.py — this wrapper just
# shells out so the .sh and .py writers share one implementation.

validate_source_identity() {
  local source_run_id="${1:-}"
  local source_skill="${2:-}"
  local agent="${3:-}"

  local project_dir="${CLAUDE_PROJECT_DIR:-.}"
  local validator="$project_dir/.claude/scripts/lib/source_identity_validator.py"

  if [ ! -f "$validator" ]; then
    echo "ERROR: source_identity_validator.py not found at $validator" >&2
    return 1
  fi

  local args=(--source-run-id "$source_run_id" --source-skill "$source_skill" --project-dir "$project_dir")
  if [ -n "$agent" ]; then
    args+=(--agent "$agent")
  fi

  python3 "$validator" "${args[@]}"
}
