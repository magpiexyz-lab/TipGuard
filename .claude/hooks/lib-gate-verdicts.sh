#!/usr/bin/env bash
# lib-gate-verdicts.sh — Gate verdict file + trace verdict queries.
# Sourced via lib.sh facade. Do NOT source directly.
# Requires: ERRORS array (from caller), PROJECT_DIR (from caller, used by check_trace_run_id).
# Cross-module: read_json_field, get_branch (lib-core.sh).

# --- check_verdict_gates ---
# Loops over gate verdict files, checks existence + PASS verdict + optional branch match.
# Appends errors to the global ERRORS array. Does not exit — caller decides.
# $1: space-separated list of gate names (e.g., "bg1 bg2 bg2.5 bg4")
# $2: verdicts directory path
# $3: (optional) branch name — when set, also validates verdict.branch matches
# Usage: check_verdict_gates "bg1 bg2 bg2.5 bg4" "$VERDICTS_DIR"
#        check_verdict_gates "g4 g5 g6" "$VERDICTS_DIR" "$BRANCH"
check_verdict_gates() {
  local gates_list="$1" verdicts_dir="$2" branch="${3:-}"
  for gate in $gates_list; do
    local gate_upper
    gate_upper=$(printf '%s' "$gate" | tr '[:lower:]' '[:upper:]')
    local gf="$verdicts_dir/$gate.json"
    if [[ ! -f "$gf" ]]; then
      ERRORS+=("${gate_upper} verdict missing")
      continue
    fi
    local v; v=$(read_json_field "$gf" "verdict")
    [[ "$v" != "PASS" ]] && ERRORS+=("${gate_upper} verdict is ${v:-?}, not PASS")
    if [[ -n "$branch" ]]; then
      local vb; vb=$(read_json_field "$gf" "branch")
      [[ -n "$vb" && "$vb" != "$branch" ]] && ERRORS+=("${gate_upper} verdict is for branch $vb, not $branch")
    fi
  done
}

# --- check_trace_verdict ---
# Checks a single field in a trace JSON file against an expected value.
# Returns "yes" (match), "no" (mismatch), or "missing" (file/field absent).
# Usage: RESULT=$(check_trace_verdict "/path/to/trace.json" "verdict" "PASS")
check_trace_verdict() {
  local trace_file="$1" field="$2" expected="$3"
  [[ ! -f "$trace_file" ]] && { echo "missing"; return; }
  python3 -c "
import json
try:
    d = json.load(open('$trace_file'))
    val = d.get('$field')
    if val is None: print('missing')
    elif str(val) == '$expected': print('yes')
    else: print('no')
except: print('missing')
" 2>/dev/null || echo "missing"
}

# --- require_trace_verdict ---
# Checks that a trace file has a verdict field (any value).
# Appends to global ERRORS if file exists but verdict is absent.
# No-op if trace file doesn't exist (caller checks existence separately).
# Usage: require_trace_verdict "$TRACES_DIR/agent.json" "context message"
require_trace_verdict() {
  local trace_file="$1" context="$2"
  if [[ -f "$trace_file" ]]; then
    local result
    result=$(check_trace_verdict "$trace_file" "verdict" "__ANY__")
    if [[ "$result" == "missing" ]]; then
      ERRORS+=("$(basename "$trace_file") trace incomplete (no verdict) — $context")
    fi
  fi
}

# --- check_trace_run_id ---
# Validates that a trace file's run_id matches the verify-context.json run_id.
# Appends to global ERRORS if run_id is stale (from a prior /verify run).
# No-op if trace or context file is missing.
# Usage: check_trace_run_id "$TRACES_DIR/agent.json"
check_trace_run_id() {
  local TRACE_FILE="$1"
  # shellcheck disable=SC2153
  if [[ ! -f "$TRACE_FILE" ]] || [[ ! -f "$PROJECT_DIR/.runs/verify-context.json" ]]; then
    return 0
  fi
  local RESULT
  RESULT=$(python3 -c "
import json
ctx = json.load(open('$PROJECT_DIR/.runs/verify-context.json'))
trace = json.load(open('$TRACE_FILE'))
ctx_run_id = ctx.get('run_id', '')
trace_run_id = trace.get('run_id', '')
if not trace_run_id:
    print('WARN')
elif not ctx_run_id:
    print('OK')
elif trace_run_id != ctx_run_id:
    print('STALE')
else:
    print('OK')
" 2>/dev/null || echo "OK")
  if [[ "$RESULT" == "STALE" ]]; then
    local BASENAME
    BASENAME=$(basename "$TRACE_FILE")
    ERRORS+=("$BASENAME has stale run_id — trace is from a prior /verify run, not the current one")
  fi
}

# --- check_block_verdicts ---
# Checks gate-verdicts/ for any BLOCK verdicts on the current branch.
# Appends blocking gate IDs to global ERRORS array. Does not exit — caller decides.
# Usage: check_block_verdicts
check_block_verdicts() {
  local project_dir="${CLAUDE_PROJECT_DIR:-.}"
  local verdicts_dir="$project_dir/.runs/gate-verdicts"
  [[ ! -d "$verdicts_dir" ]] && return 0

  local branch
  branch=$(get_branch)

  for gf in "$verdicts_dir"/*.json; do
    [[ -f "$gf" ]] || continue
    local v; v=$(read_json_field "$gf" "verdict")
    [[ "$v" != "BLOCK" ]] && continue
    local vb; vb=$(read_json_field "$gf" "branch")
    if [[ "$vb" == "$branch" ]]; then
      local gate_id gate_id_upper
      gate_id=$(basename "$gf" .json)
      gate_id_upper=$(printf '%s' "$gate_id" | tr '[:lower:]' '[:upper:]')
      ERRORS+=("Gate ${gate_id_upper} has BLOCK verdict on branch $branch")
    fi
  done
}
