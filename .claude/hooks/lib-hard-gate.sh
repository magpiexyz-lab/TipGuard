#!/usr/bin/env bash
# lib-hard-gate.sh — Hard gate predicate evaluation.
# Sourced via lib.sh facade. Do NOT source directly.
# Requires: ERRORS array, CONTENT (from caller — verify-report.md body).
# Cross-module: invokes .claude/scripts/evaluate-hard-gate-predicates.py.

# --- check_hard_gate_predicates ---
# v2 (agent-trace lifecycle contract): predicate-based hard gate evaluation.
# Delegates predicate logic to evaluate-hard-gate-predicates.py (extracted
# from lib-verdict.sh in 2026-04 to enable pytest unit testing). The Python
# script reads agent-registry.json's hard_gates[].allow_predicates and
# additional_block_conditions for $1, evaluates them against the trace at
# $2/$1.json, and prints exactly one line:
#   OK | BLOCK:<reason> | READ_ERROR:<msg> | UNKNOWN_PREDICATE:<name>
# Empty stdout means no hard_gate entry registered for the agent (treat as OK).
#
# Uses caller's $CONTENT, $ERRORS (global).
# $1: agent name (e.g., "design-critic")
# $2: trace directory path
# Usage: check_hard_gate_predicates "design-critic" "$TRACE_DIR"
check_hard_gate_predicates() {
  local agent="$1" trace_dir="$2"
  local trace_file="$trace_dir/${agent}.json"
  [[ ! -f "$trace_file" ]] && return 0

  local project_dir="${CLAUDE_PROJECT_DIR:-.}"
  local reg="$project_dir/.claude/patterns/agent-registry.json"
  [[ ! -f "$reg" ]] && return 0

  local script="$project_dir/.claude/scripts/evaluate-hard-gate-predicates.py"
  # Existence guard for the extracted evaluator (boundary check introduced when
  # the Python was moved out of lib-verdict.sh's heredoc): a missing script
  # means the repository is broken — never a normal run state. Without this
  # guard, python3 errors to stderr and stdout is empty, causing the OK|""
  # branch to silently pass every hard gate.
  if [[ ! -f "$script" ]]; then
    ERRORS+=("${agent} hard gate evaluator script missing: $script")
    return 0
  fi

  local eval_result
  eval_result=$(AGENT_ENV="$agent" \
                TRACE_ENV="$trace_file" \
                TRACES_DIR_ENV="$trace_dir" \
                REG_ENV="$reg" \
                python3 "$script")

  case "$eval_result" in
    OK|"")
      return 0
      ;;
    BLOCK:*)
      if ! echo "$CONTENT" | grep -q 'hard_gate_failure: *true'; then
        ERRORS+=("${agent} hard gate: ${eval_result#BLOCK:}")
      fi
      ;;
    READ_ERROR:*|UNKNOWN_PREDICATE:*)
      ERRORS+=("${agent} hard gate evaluation error: ${eval_result}")
      ;;
  esac
}
