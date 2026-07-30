#!/usr/bin/env bash
# lib-core.sh — Core utility functions used by all hooks.
# Sourced via lib.sh facade. Do NOT source directly.
# Globals provided: PAYLOAD (after parse_payload), CURRENT_BRANCH, TOOL_NAME, CONTENT.

# --- parse_payload ---
# Reads stdin into global PAYLOAD. Must be called before any read_payload_field.
parse_payload() {
  PAYLOAD=$(cat)
}

# --- get_branch ---
# Returns current git branch. Caches in CURRENT_BRANCH on first call.
get_branch() {
  if [[ -z "${CURRENT_BRANCH+x}" ]]; then
    CURRENT_BRANCH=$(git branch --show-current 2>/dev/null || echo "")
  fi
  echo "$CURRENT_BRANCH"
}

# --- get_project_dir ---
# Returns the git working tree root. In a worktree, this is the worktree path,
# not the main repo root. Falls back to CLAUDE_PROJECT_DIR or "." if git fails.
# Caches in _PROJECT_DIR_CACHE on first call (same pattern as get_branch).
get_project_dir() {
  if [[ -z "${_PROJECT_DIR_CACHE+x}" ]]; then
    local toplevel
    toplevel=$(git rev-parse --show-toplevel 2>/dev/null)
    _PROJECT_DIR_CACHE="${toplevel:-${CLAUDE_PROJECT_DIR:-.}}"
  fi
  echo "$_PROJECT_DIR_CACHE"
}

# Override CLAUDE_PROJECT_DIR so all downstream code (hooks, lib modules,
# Python subprocesses) uses the worktree-aware path. No-op when not in a worktree.
CLAUDE_PROJECT_DIR="$(get_project_dir)"
export CLAUDE_PROJECT_DIR

# --- _write_hook_friction ---
# Appends one row to .runs/hook-friction.jsonl (#1128 Layer 2).
# Subshell-isolated and fail-open: any error inside is swallowed so the
# caller's deny() / deny_errors() contract (stderr + exit 2) is unchanged.
# Uses env vars (not heredoc args) to avoid shell-quoting issues.
# Usage: _write_hook_friction "deny message"
_write_hook_friction() {
  ( # subshell isolates errexit and any side-effect failures
    set +e
    local msg="$1"
    # #1393 + #1379 r3 — optional action_type classifier (defaults to "block"
    # in append-hook-friction.py when env var unset). Callers in warn-mode
    # paths pass "warn-mode-bypass"; future post-emit lead-write observers
    # pass "manual-write-sanctioned" or "manual-write-deviation".
    local action_type="${2:-}"
    local hook_basename
    # `$0` is the hook script path Claude Code spawned (e.g.,
    # /.../.claude/hooks/fix-ledger-write-guard.sh). It is set at process
    # start and stable regardless of how lib-core.sh is sourced — far more
    # reliable than BASH_SOURCE[N] which depends on the source chain.
    hook_basename=$(basename "${0:-unknown}" 2>/dev/null || echo "unknown")
    local tool_name=""
    local blocked_cmd=""
    if [[ -n "${PAYLOAD:-}" ]]; then
      tool_name=$(read_payload_field "tool_name" 2>/dev/null || echo "")
      blocked_cmd=$(read_payload_field "tool_input.command" 2>/dev/null || echo "")
      if [[ -z "$blocked_cmd" ]]; then
        blocked_cmd=$(read_payload_field "tool_input.file_path" 2>/dev/null || echo "")
      fi
    fi
    HOOK_FRICTION_HOOK="$hook_basename" \
    HOOK_FRICTION_REASON="$msg" \
    HOOK_FRICTION_TOOL_NAME="$tool_name" \
    HOOK_FRICTION_BLOCKED_CMD="$blocked_cmd" \
    HOOK_FRICTION_ACTION_TYPE="$action_type" \
    python3 "${CLAUDE_PROJECT_DIR:-.}/.claude/scripts/append-hook-friction.py" 2>/dev/null
  ) 2>/dev/null || true
}

# --- deny ---
# Outputs reason to stderr and exits 2 to block the tool call.
# Claude Code hook protocol: exit 0 = allow, exit non-zero = block.
# Never call deny() inside a subshell like $(deny "msg").
# Tees a row to .runs/hook-friction.jsonl before exiting (#1128 Layer 2).
# Usage: deny "Your message here"
deny() {
  local msg="$1"
  _write_hook_friction "$msg"
  echo "$msg" >&2
  exit 2
}

# --- deny_errors ---
# Joins global ERRORS array with "; ", outputs reason to stderr, exits 2.
# Tees a row to .runs/hook-friction.jsonl before exiting (#1128 Layer 2).
# Usage: deny_errors "Prefix: " "Suffix."
deny_errors() {
  local prefix="$1"
  local suffix="$2"
  local joined
  joined=$(printf '%s; ' "${ERRORS[@]}")
  _write_hook_friction "${prefix}${joined}${suffix}"
  echo "${prefix}${joined}${suffix}" >&2
  exit 2
}

# --- read_payload_field ---
# Extracts a field from PAYLOAD by dotted path. Returns "" on missing/error.
# Handles root-level (tool_name) and nested (tool_input.command) paths.
# Usage: VAL=$(read_payload_field "tool_input.command")
read_payload_field() {
  local field_path="$1"
  echo "$PAYLOAD" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for p in '$field_path'.split('.'):
    if isinstance(d, dict):
        d = d.get(p, '')
    else:
        d = ''
        break
print('' if isinstance(d, (dict, list)) else d)
" 2>/dev/null || echo ""
}

# --- read_json_field ---
# Reads a single field from a JSON file. Returns "" if file missing or error.
# Stringifies scalars (int 0 → "0", bool → "True"/"False").
# Usage: VAL=$(read_json_field "/path/to/file.json" "verdict")
read_json_field() {
  local file="$1"
  local field="$2"
  if [[ ! -f "$file" ]]; then
    echo ""
    return
  fi
  python3 -c "
import json
try:
    val = json.load(open('$file')).get('$field', '')
    print('' if isinstance(val, (dict, list)) else val)
except:
    print('')
" 2>/dev/null || echo ""
}

# --- extract_write_content ---
# Sets globals TOOL_NAME and CONTENT from Write or Edit payload.
# Must be called after parse_payload.
# shellcheck disable=SC2034
extract_write_content() {
  TOOL_NAME=$(read_payload_field "tool_name")
  CONTENT=""
  if [[ "$TOOL_NAME" == "Write" ]]; then
    CONTENT=$(read_payload_field "tool_input.content")
  elif [[ "$TOOL_NAME" == "Edit" ]]; then
    CONTENT=$(read_payload_field "tool_input.new_string")
  fi
}

# --- extract_prompt ---
# Extracts tool_input.prompt from PAYLOAD. Returns "" if missing.
# Must be called after parse_payload.
# Usage: PROMPT=$(extract_prompt)
extract_prompt() {
  read_payload_field "tool_input.prompt"
}

# --- handle_validation ---
# Processes VALIDATION result from python3 content checks.
# OK → return, PARSE_ERROR → exit 0 (fail open), FAIL:... → deny with detail.
# Usage: handle_validation "$VALIDATION" "Gate name" "Suffix message."
handle_validation() {
  local result="$1"
  local gate_name="$2"
  local suffix="${3:-}"
  if [[ "$result" == "PARSE_ERROR" ]]; then
    exit 0
  fi
  if [[ "$result" == FAIL:* ]]; then
    local detail="${result#FAIL:}"
    deny "${gate_name} blocked: ${detail}. ${suffix}"
  fi
}

# --- Agent registry lookup ---
# Reads a field from agent-registry.json using dot notation (e.g., "merge_gates.design_ux.checks").
# Returns: lists as space-separated strings, dicts as JSON, scalars as strings.
# Usage: VAL=$(read_agent_registry_field "verdict_agents")
_AGENT_REGISTRY="${CLAUDE_PROJECT_DIR:-.}/.claude/patterns/agent-registry.json"

read_agent_registry_field() {
  local field="$1"
  [[ ! -f "$_AGENT_REGISTRY" ]] && { echo ""; return; }
  python3 -c "
import json
reg = json.load(open('$_AGENT_REGISTRY'))
keys = '$field'.split('.')
val = reg
for k in keys:
    val = val[k] if isinstance(val, dict) and k in val else None
    if val is None: break
if isinstance(val, list):
    print(' '.join(str(v) for v in val))
elif isinstance(val, dict):
    print(json.dumps(val))
elif val is not None:
    print(val)
" 2>/dev/null || echo ""
}
