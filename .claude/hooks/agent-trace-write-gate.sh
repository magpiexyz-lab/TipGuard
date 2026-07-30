#!/usr/bin/env bash
# agent-trace-write-gate.sh — Claude Code PreToolUse hook for Write/Edit on agent-traces.
#
# Companion to agent-trace-write-guard.sh (which gates Bash). This hook closes
# the symmetric gap: direct Write/Edit tool calls targeting .runs/agent-traces/*.json
# are blocked because they bypass write-agent-trace.sh and lose AOC v1.1
# canonical metadata (agent, timestamp, run_id, provenance, partial,
# recovery_validated, spawn_sha, spawn_index).
#
# Allowed Bash callers (via agent-trace-write-guard.sh, not this hook):
#   - .claude/scripts/write-agent-trace.sh   (AOC v1.1 centralized writer)
#   - .claude/scripts/write-recovery-trace.sh
#   - .claude/scripts/write-degraded-trace.py
#   - .claude/scripts/validate-recovery.sh   (stamps recovery_validated only)
#   - .claude/scripts/migrate-legacy-traces.py
#   - .claude/scripts/merge-design-critic-traces.py
#   - .claude/scripts/merge-scaffold-pages-traces.py
#   - .claude/scripts/augment-trace.py
#   - scripts/init-trace.py
#
# This hook denies ALL Write/Edit tool calls targeting agent-traces/*.json
# because there is no legitimate Write/Edit caller for these paths — every
# canonical writer is a Bash/Python script that uses POSIX file APIs.
#
# Mode toggle (PR4 will flip):
#   MODE="warn" — emit stderr WARN, exit 0 (does not block).
#   MODE="deny" — emit stderr DENY, exit 2 (blocks the Write/Edit call).
#
# Soak window for WARN mode: telemetry from `_write_hook_friction` surfaces
# any unexpected legitimate caller before flipping to deny.

set -euo pipefail

# PR4: flipped to deny after pre-flight audit confirmed zero legitimate
# Write/Edit callers for .runs/agent-traces/*.json (all references are reads:
# json.load, test -f, glob.glob). 9 known direct-Write callers were migrated
# in PR2 (#1173). To revert to WARN if an unexpected regression surfaces,
# change this single line back to MODE="warn".
MODE="deny"

source "$(dirname "$0")/lib.sh"
parse_payload

FILE_PATH=$(read_payload_field "tool_input.file_path")

# Fast-path: not targeting an agent-traces JSON → allow.
case "$FILE_PATH" in
  *agent-traces/*.json) ;;
  *) exit 0 ;;
esac

MSG="Agent trace write gate: direct Write/Edit to .runs/agent-traces/*.json is not allowed (AOC v1.1). Use one of the canonical writers via Bash:
  bash .claude/scripts/write-agent-trace.sh <agent> --json '<...>'
  python3 .claude/scripts/write-degraded-trace.py <agent> --reason '<...>'
  bash .claude/scripts/write-recovery-trace.sh <agent> --reason '<...>'
See .claude/patterns/agent-output-contract.md § Canonical Writer Policy.
Path attempted: $FILE_PATH"

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
    echo "ERROR: agent-trace-write-gate.sh — unknown MODE=$MODE (expected 'warn' or 'deny')" >&2
    exit 1
    ;;
esac
