#!/usr/bin/env bash
# lib-merge.sh — Merge gate validation functions.
# Sourced via lib.sh facade. Do NOT source directly.
# Cross-module: uses parse_payload, read_payload_field, extract_write_content,
#   handle_validation, read_agent_registry_field from lib-core.sh
#   (loaded before this module by facade).

# --- exec_merge_gate ---
# Hook-level wrapper: reads checks JSON from agent-registry, guards empty,
# dispatches to run_merge_gate. Caller is responsible for parse_payload
# (so adversarial-merge-gate.sh can branch on file_path before calling this).
# $1: agent-registry dotted field (e.g., "merge_gates.design_ux.checks")
# $2: file_path substring to match (e.g., "design-ux-merge")
# $3: human-readable gate name (e.g., "Design-UX merge gate")
# Usage: exec_merge_gate "merge_gates.design_ux.checks" "design-ux-merge" "Design-UX merge gate"
exec_merge_gate() {
  local registry_field="$1"
  local file_pattern="$2"
  local gate_name="$3"

  local checks
  checks=$(read_agent_registry_field "$registry_field")
  if [[ -z "$checks" ]]; then
    # #1349 fix: empty checks were silently exiting 0 — masking misconfigured
    # registry fields and untracked migrations. Friction-log so unconfigured
    # gates are observable. Fail-open per Constraint 19 (registry absence is
    # structural, not adversarial).
    _write_hook_friction "lib-merge.exec_merge_gate: empty checks for registry_field='$registry_field' gate='$gate_name' — failing open (registry may be uninitialized or field renamed)."
    exit 0
  fi

  run_merge_gate "$file_pattern" "$checks" "$gate_name"
}

# --- run_merge_gate ---
# Parameterized merge gate executor. Encapsulates the full gate flow:
# parse_payload → match file_path → extract content → validate → handle result.
# Each merge gate hook calls this with its 3 parameters, eliminating skeleton duplication.
# $1: file_path substring to match (e.g., "design-ux-merge")
# $2: check definitions JSON string (passed to validate_merge_json)
# $3: human-readable gate name (e.g., "Design-UX merge gate")
# Usage: run_merge_gate "design-ux-merge" "$CHECKS_JSON" "Design-UX merge gate"
run_merge_gate() {
  local file_pattern="$1"
  local check_defs="$2"
  local gate_name="$3"

  local file_path
  file_path=$(read_payload_field "tool_input.file_path")

  # Only fire when file_path matches the pattern
  if [[ "$file_path" != *"$file_pattern"* ]]; then
    # friction-skip: trivial-fast-path — file_path doesn't match this gate's pattern.
    exit 0
  fi

  extract_write_content

  # Skip if content is empty
  if [[ -z "$CONTENT" ]]; then
    # friction-skip: trivial-fast-path — empty Write/Edit content has no JSON to validate.
    exit 0
  fi

  local validation
  validation=$(echo "$CONTENT" | validate_merge_json "$check_defs")

  handle_validation "$validation" "$gate_name" "Merge JSON must match source agent traces."

  # friction-skip: post-validation — handle_validation already exited on FAIL/PARSE_ERROR.
  exit 0
}

# --- validate_merge_json ---
# Parameterized JSON validation for merge gate hooks. Reads merge content from stdin.
# Parses merge content, loads traces, compares fields per check definitions.
# Returns "OK", "PARSE_ERROR", or "FAIL:<details>" — caller passes to handle_validation.
# $1: check definitions JSON string (declarative field comparisons)
# Usage: VALIDATION=$(echo "$CONTENT" | validate_merge_json "$CHECK_DEFS")
#
# DO NOT EXTRACT this Python to a .py file — it uses bash variable interpolation
# ($check_defs at line "checks = json.loads('''$check_defs''')") which requires
# bash to evaluate the variable before Python sees the code.
validate_merge_json() {
  local check_defs="$1"
  python3 -c "
import json, sys, os

content = sys.stdin.read().strip()
errors = []

try:
    merge = json.loads(content)
except json.JSONDecodeError:
    print('PARSE_ERROR')
    # friction-skip: post-validation — PARSE_ERROR is a stdout signal consumed by handle_validation.
    sys.exit(0)

traces_dir = os.environ.get('CLAUDE_PROJECT_DIR', '.') + '/.runs/agent-traces'
checks = json.loads('''$check_defs''')

for trace_def in checks.get('traces', []):
    trace_path = os.path.join(traces_dir, trace_def['trace_file'])
    if not os.path.exists(trace_path):
        errors.append(trace_def.get('missing_error', trace_def['trace_file'] + ' not found'))
        continue
    try:
        trace = json.load(open(trace_path))
    except (json.JSONDecodeError, IOError):
        continue

    merge_key = trace_def.get('merge_key')
    merge_section = merge.get(merge_key, {}) if merge_key else merge

    for fdef in trace_def.get('fields', []):
        t_val = trace.get(fdef['trace_field'])
        m_val = merge_section.get(fdef['merge_field'])
        if fdef.get('null_ok') and (t_val is None or m_val is None):
            continue
        if t_val != m_val:
            prefix = (merge_key + '.') if merge_key else ''
            errors.append(f'{prefix}{fdef[\"merge_field\"]} mismatch: trace={t_val}, merge={m_val}')

    for sub in trace_def.get('sub_traces', []):
        sub_path = os.path.join(traces_dir, sub['trace_file'])
        if sub.get('condition') == 'exists' and not os.path.exists(sub_path):
            continue
        try:
            sub_trace = json.load(open(sub_path))
        except (json.JSONDecodeError, IOError):
            continue
        for fdef in sub.get('fields', []):
            t_val = sub_trace.get(fdef['trace_field'])
            m_val = merge_section.get(fdef['merge_field'])
            if fdef.get('null_ok') and (t_val is None or m_val is None):
                continue
            if t_val != m_val:
                prefix = (merge_key + '.') if merge_key else ''
                errors.append(f'{prefix}{fdef[\"merge_field\"]} mismatch: trace={t_val}, merge={m_val}')

for sc in checks.get('self_checks', []):
    if sc['type'] == 'count_match':
        arr = merge.get(sc['array_field'], [])
        count = merge.get(sc['count_field'], 0)
        if count != len(arr):
            errors.append(f'{sc[\"count_field\"]} ({count}) != len({sc[\"array_field\"]}) ({len(arr)})')

if errors:
    print('FAIL:' + '; '.join(errors))
else:
    print('OK')
" 2>/dev/null || echo "OK"
}
