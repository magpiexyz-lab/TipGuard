#!/usr/bin/env bash
# retrospective-content-gate.sh — PreToolUse Write/Edit matcher hook.
#
# Closes #1152 enforcement layer 2: when a Write/Edit targets a path declared
# in .claude/patterns/lead-only-artifacts.json, require the artifact's declared
# executor field to be present with value "lead" in the content.
#
# Combined with lead-deliverable-gate.sh (layer 1, blocks delegation route via
# Agent tool spawn), this gate catches direct Write attempts that bypass the
# Agent route. The lead can still write the file from its own session, but
# only with the executor field correctly stamped.

set -euo pipefail

MODE="warn"

source "$(dirname "$0")/lib.sh"
parse_payload

FILE_PATH=$(read_payload_field "tool_input.file_path")
if [[ -z "$FILE_PATH" ]]; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || echo .)}"
MANIFEST="$PROJECT_DIR/.claude/patterns/lead-only-artifacts.json"
if [[ ! -f "$MANIFEST" ]]; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

# Find the manifest entry matching FILE_PATH (suffix match — accepts absolute paths).
# Export the env vars first so they're visible to python's child process.
export FILE_PATH_ENV="$FILE_PATH"
export MANIFEST_ENV="$MANIFEST"
EXECUTOR_FIELD=$(python3 -c "
import json, os
file_path = os.environ['FILE_PATH_ENV']
m = json.load(open(os.environ['MANIFEST_ENV']))
for a in m.get('artifacts', []):
    p = a.get('path', '')
    if not p:
        continue
    if file_path == p or file_path.endswith('/' + p) or file_path.endswith(p):
        print(a.get('executor_field', ''))
        break
" 2>/dev/null || true)
unset FILE_PATH_ENV MANIFEST_ENV

if [[ -z "$EXECUTOR_FIELD" ]]; then
  # Not a lead-only artifact → allow.
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

# Threat model differs by tool:
#   - Write creates/replaces the file → require the field to be present in
#     content with value "lead". (Without this, the file lacks lead attestation.)
#   - Edit modifies an existing file → the file ALREADY exists with the field
#     (the original Write enforced it). Threat is field tampering: removing
#     the field or changing its value to non-"lead". Most legitimate Edits
#     don't touch the field at all and must be allowed.
#
# Pattern: '"<field>"\s*:\s*"lead"' matches both compact ("k":"lead") and
# pretty-printed ('  "k": "lead"') JSON.
TOOL_NAME=$(read_payload_field "tool_name")
CHECK_PATTERN="\"$EXECUTOR_FIELD\"[[:space:]]*:[[:space:]]*\"lead\""
FIELD_PRESENT_PATTERN="\"$EXECUTOR_FIELD\"[[:space:]]*:"

if [[ "$TOOL_NAME" == "Write" ]]; then
  CONTENT=$(read_payload_field "tool_input.content")
  if echo "$CONTENT" | grep -qE "$CHECK_PATTERN"; then
    # friction-skip: trivial-fast-path — input absent or non-applicable
    exit 0
  fi
  VIOLATION="Write to $FILE_PATH lacks $EXECUTOR_FIELD=\"lead\""
elif [[ "$TOOL_NAME" == "Edit" ]]; then
  OLD_STRING=$(read_payload_field "tool_input.old_string")
  NEW_STRING=$(read_payload_field "tool_input.new_string")
  # Allow when the edit doesn't touch the field at all
  if ! echo "$OLD_STRING" | grep -qE "$FIELD_PRESENT_PATTERN" && \
     ! echo "$NEW_STRING" | grep -qE "$FIELD_PRESENT_PATTERN"; then
    # friction-skip: trivial-fast-path — input absent or non-applicable
    exit 0
  fi
  # Edit touches the field — check both directions:
  #   (a) old had field=lead AND new still has field=lead → ALLOW
  #   (b) old had field=lead AND new lacks field=lead → DENY (removal/tamper)
  #   (c) old lacked field AND new sets field=lead → ALLOW (adding the field)
  #   (d) old lacked field AND new sets field=non-lead → DENY (tamper)
  OLD_HAS_LEAD=$(echo "$OLD_STRING" | grep -qE "$CHECK_PATTERN" && echo y || echo n)
  NEW_HAS_LEAD=$(echo "$NEW_STRING" | grep -qE "$CHECK_PATTERN" && echo y || echo n)
  NEW_HAS_FIELD=$(echo "$NEW_STRING" | grep -qE "$FIELD_PRESENT_PATTERN" && echo y || echo n)
  if [[ "$NEW_HAS_LEAD" == "y" ]]; then
    # friction-skip: post-validation — exit follows authoritative decision (allow-list match, deny path, or successful validation)
    exit 0  # post-edit content correctly stamps "lead"
  fi
  if [[ "$NEW_HAS_FIELD" == "n" && "$OLD_HAS_LEAD" == "n" ]]; then
    # friction-skip: post-validation — exit follows authoritative decision (allow-list match, deny path, or successful validation)
    exit 0  # edit doesn't introduce a wrong value
  fi
  VIOLATION="Edit on $FILE_PATH would leave $EXECUTOR_FIELD without value \"lead\" (tampering or removal)"
else
  # Other tools (e.g. NotebookEdit) — out of scope for this gate
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

MSG="retrospective-content-gate: $VIOLATION.

This artifact is declared lead-only in .claude/patterns/lead-only-artifacts.json.
The lead must stamp the executor field to attest this was authored in the lead
session, not a delegated/spawned context. The post-write check in
compliance-audit.py also enforces this, but blocking at write time is the
strongest enforcement layer.

Required pattern: \"$EXECUTOR_FIELD\": \"lead\"

See .claude/patterns/observation-phase.md Step 5a 'Write result' for the schema.
Closes #1152."

case "$MODE" in
  warn)
    # Soft signal — friction-log + emit to stderr, allow the write.
    _write_hook_friction "$MSG"
    echo "WARN: $MSG" >&2
    exit 0
    ;;
  deny)
    deny "$MSG"
    ;;
  *)
    echo "ERROR: retrospective-content-gate.sh — unknown MODE=$MODE" >&2
    exit 1
    ;;
esac
