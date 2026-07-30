#!/usr/bin/env bash
# bound-by-coverage-provider-gate.sh — PreToolUse:Bash hook.
#
# Fires when the lead invokes `write-agent-trace.sh --provenance lead-synthesized`.
# Delegates to .claude/scripts/lib/bound-by-coverage-provider.py to validate
# that numerical claims in the lead-synthesized trace payload are bounded by
# the coverage_provider artifact.
#
# Closes prose-gate `lead-synthesized-numerical-bounds`
# (.claude/patterns/prose-gates.json). Phase A: warn-mode (logs to
# .runs/lead-deviation-log.jsonl, exits 0). Phase C: deny-mode (exits 2).
#
# Test-mode bypass: CLAUDE_HOOK_TEST_MODE=1 → fast-path exit 0.
# Emergency escape:  PROSE_GATES_TOLERANT=1 → warn + exit 0 (mirrors RMG_V2_TOLERANT).

set -euo pipefail

source "$(dirname "$0")/lib.sh"
parse_payload

TOOL_NAME=$(read_payload_field "tool_name")
if [[ "$TOOL_NAME" != "Bash" ]]; then
  # friction-skip: trivial-fast-path — only fires on Bash tool
  exit 0
fi

COMMAND=$(read_payload_field "tool_input.command")

# Fast-path: not a write-agent-trace call → allow.
case "$COMMAND" in
  *write-agent-trace.sh*) ;;
  *)
    # friction-skip: trivial-fast-path — input non-applicable
    exit 0
    ;;
esac

# Normalize multi-line continuation backslashes; collapse whitespace.
NORM=$(printf '%s' "$COMMAND" | tr '\n' ' ' | sed -E 's/\\$//g; s/[[:space:]]+/ /g')

# Match either `--provenance lead-synthesized` or `--provenance=lead-synthesized`.
if [[ ! "$NORM" =~ --provenance[[:space:]]+lead-synthesized ]] && \
   [[ ! "$NORM" =~ --provenance=lead-synthesized ]]; then
  # friction-skip: trivial-fast-path — different provenance
  exit 0
fi

# Test-mode bypass for E2E tests.
if [[ "${CLAUDE_HOOK_TEST_MODE:-}" == "1" ]]; then
  # friction-skip: test-mode bypass
  exit 0
fi

# Emergency escape (mirrors RMG_V2_TOLERANT — see .claude/patterns/state-completion-gate.md).
if [[ "${PROSE_GATES_TOLERANT:-0}" == "1" ]]; then
  _write_hook_friction "bound-by-coverage-provider-gate" "tolerant-mode-bypass: PROSE_GATES_TOLERANT=1" || true
  echo "WARN: bound-by-coverage-provider-gate: PROSE_GATES_TOLERANT=1 — bypassing." >&2
  # friction-skip: paired with _write_hook_friction above
  exit 0
fi

# Resolve mode via shared prose_gate_mode helper (#1449/#1431/#1433).
# Gate 1 (lead-synthesized-numerical-bounds) prior_default="warn" preserves
# Phase A behavior. Helper checks: PROSE_GATES_TOLERANT > per-gate env >
# snapshot > registry (when v2+) > prior_default.
# Per-gate override env: PROSE_GATE_LEAD_SYNTHESIZED_NUMERICAL_BOUNDS_MODE.
MODE=$(bash "$(dirname "$0")/../scripts/lib/prose_gate_mode.sh" lead-synthesized-numerical-bounds warn)

# Invoke the validator with the normalized command. Validator extracts the
# --json payload and --coverage-provider arg itself.
VALIDATOR="$CLAUDE_PROJECT_DIR/.claude/scripts/lib/bound-by-coverage-provider.py"
if [[ ! -f "$VALIDATOR" ]]; then
  # Validator missing — fail-open with friction log.
  _write_hook_friction "bound-by-coverage-provider-gate" "validator-missing: $VALIDATOR" || true
  echo "WARN: bound-by-coverage-provider-gate: validator missing at $VALIDATOR" >&2
  # friction-skip: paired with _write_hook_friction above
  exit 0
fi

if RESULT=$(python3 "$VALIDATOR" --command "$NORM" 2>&1); then
  # friction-skip: validator passed (no violation)
  exit 0
fi

case "$MODE" in
  warn)
    _write_hook_friction "bound-by-coverage-provider-gate" "warn-mode-violation: $RESULT" || true
    echo "WARN: bound-by-coverage-provider-gate: $RESULT" >&2
    # friction-skip: paired with _write_hook_friction above
    exit 0
    ;;
  deny)
    deny "lead-synthesized numerical claims unbounded: $RESULT"
    ;;
esac
