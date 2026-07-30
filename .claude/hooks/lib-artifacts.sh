#!/usr/bin/env bash
# lib-artifacts.sh — Artifact checking and postcondition functions.
# Sourced via lib.sh facade. Do NOT source directly.
# Requires: ERRORS, WARNINGS arrays (from caller); PAYLOAD (from parse_payload).
# Cross-module: read_json_field (lib-core.sh), PROJECT_DIR (from caller).

# shellcheck disable=SC2153  # PROJECT_DIR is set by the sourcing script, not a misspelling of project_dir
# --- check_postcondition_artifacts ---
# Verifies that postcondition artifact files exist for a given verify state.
# Appends to global ERRORS for any missing artifacts.
# Usage: check_postcondition_artifacts 0
check_postcondition_artifacts() {
  local PREV_STATE="$1"
  local V_SCOPE V_ARCH
  case "$PREV_STATE" in
    0)
      [[ -f "$PROJECT_DIR/.runs/verify-context.json" ]] || ERRORS+=("verify-context.json missing — STATE 0 incomplete")
      [[ -f "$PROJECT_DIR/.runs/fix-log.md" ]] || ERRORS+=("fix-log.md missing — STATE 0 incomplete")
      # AOC v1 FLS v1: fix-ledger.jsonl is the authoritative per-fix source.
      # Presence is not required at STATE 0 (consolidation runs later via
      # .runs/fix-ledger.jsonl writer); but the consumer must reference the
      # canonical path for the R3 coverage rule.
      [[ -d "$TRACES_DIR" ]] || ERRORS+=("agent-traces/ directory missing — STATE 0 incomplete")
      ;;
    3)
      V_SCOPE=$(read_json_field "$PROJECT_DIR/.runs/verify-context.json" "scope")
      V_ARCH=$(read_json_field "$PROJECT_DIR/.runs/verify-context.json" "archetype")
      if [[ ("$V_SCOPE" == "full" || "$V_SCOPE" == "visual") && "$V_ARCH" == "web-app" ]]; then
        [[ -f "$PROJECT_DIR/.runs/design-ux-merge.json" ]] || ERRORS+=("design-ux-merge.json missing — STATE 3 incomplete")
      fi
      ;;
    3d)
      V_SCOPE=$(read_json_field "$PROJECT_DIR/.runs/verify-context.json" "scope")
      V_ARCH=$(read_json_field "$PROJECT_DIR/.runs/verify-context.json" "archetype")
      if [[ ("$V_SCOPE" == "full" || "$V_SCOPE" == "visual") && "$V_ARCH" == "web-app" ]]; then
        [[ -f "$PROJECT_DIR/.runs/quality-merge.json" ]] || ERRORS+=("quality-merge.json missing — STATE 3d incomplete")
      fi
      ;;
    4)
      V_SCOPE=$(read_json_field "$PROJECT_DIR/.runs/verify-context.json" "scope")
      if [[ "$V_SCOPE" == "full" || "$V_SCOPE" == "security" ]]; then
        [[ -f "$PROJECT_DIR/.runs/security-merge.json" ]] || ERRORS+=("security-merge.json missing — STATE 4 incomplete")
      fi
      ;;
    *)
      # Unknown state — fail open (no artifacts to check)
      ;;
  esac
}

# --- check_tier1_retry_complete ---
# Checks that tier-1 agent traces have completed retry if needed.
# Appends to global ERRORS if an agent exhausted turns without retry.
# Usage: check_tier1_retry_complete "design-critic-*" "$TRACES_DIR"
check_tier1_retry_complete() {
  local AGENT_PATTERN="$1"
  local TDIR="$2"
  for TRACE in "$TDIR"/${AGENT_PATTERN}.json; do
    [ -f "$TRACE" ] || continue
    local STATE
    STATE=$(python3 -c "
import json
d = json.load(open('$TRACE'))
has_verdict = 'verdict' in d
retry = d.get('retry_attempted', False)
status = d.get('status', '')
if has_verdict: print('COMPLETE')
elif status in ('started','exhausted') and not has_verdict and not retry: print('NEEDS_RETRY')
else: print('OK')
" 2>/dev/null || echo "OK")
    if [ "$STATE" = "NEEDS_RETRY" ]; then
      ERRORS+=("$(basename "$TRACE") exhausted without retry — must retry before proceeding")
    fi
  done
}

# --- check_efficiency_directives ---
# Validates that an agent prompt contains required efficiency directives.
# Appends to global ERRORS if directives are missing.
# Requires global PAYLOAD (raw hook payload) and PROJECT_DIR.
# Usage: check_efficiency_directives
check_efficiency_directives() {
  if [ -f "$PROJECT_DIR/.runs/verify-context.json" ]; then
    local PROMPT
    PROMPT=$(extract_prompt)
    if ! echo "$PROMPT" | grep -q "DIRECTIVES:batch_search,pr_changed_first,context_digest,pre_existing"; then
      ERRORS+=("Agent prompt missing efficiency directives — append .claude/agent-prompt-footer.md content")
    fi
  fi
}

# --- check_build_result ---
# Checks that build-result.json exists and has exit_code 0.
# Appends to global ERRORS if missing or non-zero.
# Usage: check_build_result
check_build_result() {
  local BR_FILE="$PROJECT_DIR/.runs/build-result.json"
  if [[ ! -f "$BR_FILE" ]]; then
    ERRORS+=("build-result.json missing — STATE 1 (Build & Lint Loop) did not record its result")
    return
  fi
  local EXIT_CODE
  EXIT_CODE=$(read_json_field "$BR_FILE" "exit_code")
  if [[ "$EXIT_CODE" != "0" ]]; then
    ERRORS+=("build-result.json exit_code=$EXIT_CODE — build did not pass (STATE 1 incomplete)")
  fi
}

# --- check_file_boundary ---
# Validates that a per-page agent prompt contains FILE_BOUNDARY markers
# and does not include shared paths (src/components/, src/lib/).
# Appends to global ERRORS on violations. Requires global PAYLOAD.
# Usage: check_file_boundary "design-critic (per-page)"
check_file_boundary() {
  local AGENT_NAME="$1"
  local PROMPT
  PROMPT=$(extract_prompt)

  local BOUNDARY_RESULT
  BOUNDARY_RESULT=$(python3 -c "
import re, sys
prompt = sys.stdin.read()
m = re.search(r'FILE_BOUNDARY_START\n(.*?)FILE_BOUNDARY_END', prompt, re.DOTALL)
if not m:
    print('NO_MARKER')
else:
    files = m.group(1).strip()
    shared = [f for f in files.split('\n') if f.strip().startswith('src/components/') or f.strip().startswith('src/lib/')]
    if shared:
        print('SHARED:' + ';'.join(shared[:3]))
    else:
        print('OK')
" <<< "$PROMPT" 2>/dev/null || echo "OK")

  if [[ "$BOUNDARY_RESULT" == "NO_MARKER" ]]; then
    ERRORS+=("$AGENT_NAME prompt missing FILE_BOUNDARY marker — per-page agents must declare their file boundary")
  elif [[ "$BOUNDARY_RESULT" == SHARED:* ]]; then
    local SHARED_FILES="${BOUNDARY_RESULT#SHARED:}"
    ERRORS+=("$AGENT_NAME FILE_BOUNDARY contains shared paths ($SHARED_FILES) — per-page agents must NOT include src/components/ or src/lib/")
  fi
}

# --- check_claimed_shared ---
# Validates CLAIMED_SHARED markers against .runs/design-claims.json.
# No-op if no CLAIMED_SHARED markers present (backward compatible).
# Appends to global ERRORS on violations. Requires global PAYLOAD.
# Usage: check_claimed_shared "design-critic (per-page)"
check_claimed_shared() {
  local AGENT_NAME="$1"
  local PROMPT
  PROMPT=$(extract_prompt)

  local CLAIM_RESULT
  CLAIM_RESULT=$(python3 -c "
import re, sys, json, os
prompt = sys.stdin.read()
m = re.search(r'CLAIMED_SHARED_START\n(.*?)CLAIMED_SHARED_END', prompt, re.DOTALL)
if not m:
    print('OK')
    # friction-skip: post-validation — exit follows authoritative decision (allow-list match, deny path, or successful validation)
    sys.exit(0)
files = [f.strip() for f in m.group(1).strip().split('\n') if f.strip()]
claims_path = os.path.join('${PROJECT_DIR}', '.runs', 'design-claims.json')
if not os.path.exists(claims_path):
    print('NO_CLAIMS_FILE')
    # friction-skip: post-validation — exit follows authoritative decision (allow-list match, deny path, or successful validation)
    sys.exit(0)
claims = json.load(open(claims_path)).get('claims', {})
invalid = [f for f in files if f not in claims]
if invalid:
    print('UNCLAIMED:' + ';'.join(invalid[:3]))
else:
    print('OK')
" <<< "$PROMPT" 2>/dev/null || echo "OK")

  if [[ "$CLAIM_RESULT" == "NO_CLAIMS_FILE" ]]; then
    ERRORS+=("$AGENT_NAME has CLAIMED_SHARED markers but .runs/design-claims.json does not exist")
  elif [[ "$CLAIM_RESULT" == UNCLAIMED:* ]]; then
    local UNCLAIMED="${CLAIM_RESULT#UNCLAIMED:}"
    ERRORS+=("$AGENT_NAME CLAIMED_SHARED contains paths not in design-claims.json ($UNCLAIMED)")
  fi
}

# --- _parse_check_result ---
# Parses JSON {"errors":[...],"warnings":[...]} from check functions.
# Appends to global ERRORS and WARNINGS arrays.
# Usage: _parse_check_result "$RESULT"
_parse_check_result() {
  local result="$1"
  [[ "$result" == "OK" || -z "$result" ]] && return
  while IFS= read -r line; do
    [[ -n "$line" ]] && ERRORS+=("$line")
  done < <(echo "$result" | python3 -c "import json,sys; [print(x) for x in json.load(sys.stdin).get('errors',[])]" 2>/dev/null)
  while IFS= read -r line; do
    [[ -n "$line" ]] && WARNINGS+=("$line")
  done < <(echo "$result" | python3 -c "import json,sys; [print(x) for x in json.load(sys.stdin).get('warnings',[])]" 2>/dev/null)
}

# --- check_artifact_presence ---
# Table-driven artifact existence checks for verify-report-gate.
# Covers Checks 1-8, 13b, 15: file existence, field validation, trace checks.
# Returns JSON {"errors":[...],"warnings":[...]} — caller uses _parse_check_result.
# $1: project directory  $2: has_hard_gate (0|1)  $3: report content
# Usage: RESULT=$(check_artifact_presence "$PROJECT_DIR" "$HAS_HARD_GATE" "$CONTENT")
check_artifact_presence() {
  local has_hard_gate="$2"
  echo "$3" | python3 "$(dirname "${BASH_SOURCE[0]}")/../scripts/check-artifact-presence.py" \
    --has-hard-gate "$has_hard_gate" 2>/dev/null || echo "OK"
}

# --- check_cross_artifact_consistency ---
# Cross-artifact consistency checks for verify-report-gate.
# Covers Checks 12, 14, 16-18: verdict matching, fix counts, frontmatter.
# Returns JSON {"errors":[...],"warnings":[...]} — caller uses _parse_check_result.
# $1: project directory  $2: report content
# Usage: RESULT=$(check_cross_artifact_consistency "$PROJECT_DIR" "$CONTENT")
check_cross_artifact_consistency() {
  echo "$2" | python3 "$(dirname "${BASH_SOURCE[0]}")/../scripts/check-cross-artifact-consistency.py" \
    2>/dev/null || echo "OK"
}

# --- rerun_postconditions ---
# Re-runs all postcondition commands from state-registry.json for a given skill.
# Skips states whose command is "true" (no artifact to check).
# Appends failures to global ERRORS array. Does not exit — caller decides.
# Returns 0 if all pass, 1 if any fail.
# Usage: rerun_postconditions "change"
rerun_postconditions() {
  local skill="$1"
  local project_dir="${CLAUDE_PROJECT_DIR:-.}"
  local registry="$project_dir/.claude/patterns/state-registry.json"
  [[ ! -f "$registry" ]] && return 0

  local state_cmds
  state_cmds=$(python3 -c "
import json
reg = json.load(open('$registry'))
skill_data = reg.get('$skill', {})
for state_id, entry in skill_data.items():
    if isinstance(entry, str):
        cmd = entry
    elif isinstance(entry, dict):
        cmd = entry.get('verify', '')
    else:
        continue
    if cmd.strip() and cmd.strip() != 'true':
        print(state_id + '\t' + cmd)
" 2>/dev/null || echo "")

  [[ -z "$state_cmds" ]] && return 0

  local had_failure=0
  while IFS=$'\t' read -r state_id cmd; do
    if ! (cd "$project_dir" && eval "$cmd") >/dev/null 2>&1; then
      ERRORS+=("STATE $state_id postcondition failed: $cmd")
      had_failure=1
    fi
  done <<< "$state_cmds"

  return "$had_failure"
}
