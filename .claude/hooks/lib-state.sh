#!/usr/bin/env bash
# lib-state.sh — State management and skill detection functions.
# Sourced via lib.sh facade. Do NOT source directly.
# Requires: ERRORS array (from caller). Cross-module: none (self-contained).

# --- normalize_states ---
# Reads completed_states (and skip_states) from a context JSON file.
# Normalizes all entries to strings (int 0 → "0", mixed types handled).
# Outputs space-separated list. skip_states are included so downstream
# checks treat skipped states as satisfied.
# Returns empty string if file missing, field absent, or parse error.
# Usage: STATES=$(normalize_states "/path/to/context.json")
normalize_states() {
  local ctx_file="$1"
  [[ ! -f "$ctx_file" ]] && { echo ""; return; }
  python3 -c "
import json
try:
    d = json.load(open('$ctx_file'))
    cs = [str(s) for s in d.get('completed_states', [])]
    skip = [str(s) for s in d.get('skip_states', [])]
    print(' '.join(cs + skip))
except: print('')
" 2>/dev/null || echo ""
}

# --- get_required_states ---
# Reads states array from skill.yaml for a skill.
# Handles mode-qualified names (iterate-check → iterate dir, check mode).
# Returns space-separated list of state IDs. Empty string if skill.yaml missing.
# Usage: REQUIRED=$(get_required_states "bootstrap")
get_required_states() {
  local skill="$1"
  local project_dir="${CLAUDE_PROJECT_DIR:-.}"
  # Map mode-qualified skill names to directory + mode. The canonical resolver
  # for this mapping is resolve_skill_dir in .claude/scripts/lifecycle-lib.sh
  # (filesystem-derived fallback for future modes); this local case list is kept
  # to avoid a hooks-lib -> scripts-lib dependency edge — extend BOTH when
  # adding a mode. Unknown modes fail open here (empty states -> no-op check).
  local skill_dir="$skill" mode=""
  case "$skill" in
    iterate-check) skill_dir="iterate"; mode="check" ;;
    iterate-cross) skill_dir="iterate"; mode="cross" ;;
    iterate-cross-phase2) skill_dir="iterate"; mode="cross-phase2" ;;
  esac
  local skill_yaml="$project_dir/.claude/skills/$skill_dir/skill.yaml"
  [[ ! -f "$skill_yaml" ]] && { echo ""; return; }
  python3 -c "
import re
text = open('$skill_yaml').read()
mode = '$mode'
if mode:
    # Parse modes.<mode>.states
    mp = re.search(r'%s:\s*\n\s+.*?states:\s*\[([^\]]+)\]' % mode, text, re.DOTALL)
    if mp:
        states = [s.strip().strip('\"').strip(\"'\") for s in mp.group(1).split(',')]
        print(' '.join(states))
    else:
        print('')
else:
    m = re.search(r'^states:\s*\[([^\]]+)\]', text, re.MULTILINE)
    if m:
        states = [s.strip().strip('\"').strip(\"'\") for s in m.group(1).split(',')]
        print(' '.join(states))
    else:
        print('')
" 2>/dev/null || echo ""
}

# --- compute_missing_states ---
# Pure computation: prints comma-separated missing states, or "NONE" if all present.
# Usage: MISSING=$(compute_missing_states "$STATES" "$REQUIRED")
compute_missing_states() {
  local states="$1" required="$2"
  python3 -c "
cs = set('$states'.split())
required = '$required'.split()
missing = [s for s in required if s not in cs]
print(','.join(missing) if missing else 'NONE')
" 2>/dev/null || echo "NONE"
}

# --- check_skill_completion ---
# Checks that all _required_states for a skill are in completed_states.
# Appends missing states to global ERRORS array. Does not exit — caller decides.
# No-op if _required_states is empty or context file missing (fail-open).
# Usage: check_skill_completion "change" "$PROJECT_DIR/.runs/change-context.json"
check_skill_completion() {
  local skill="$1" ctx_file="$2"
  [[ ! -f "$ctx_file" ]] && return 0
  local STATES REQUIRED MISSING
  STATES=$(normalize_states "$ctx_file")
  REQUIRED=$(get_required_states "$skill")
  [[ -z "$REQUIRED" ]] && return 0
  MISSING=$(compute_missing_states "$STATES" "$REQUIRED")
  if [[ "$MISSING" != "NONE" ]]; then
    ERRORS+=("$skill states [$MISSING] not complete — finish all required states before proceeding")
  fi
}

# --- _detect_skill_for_branch_impl ---
# Internal: shared implementation for detect_active/detect_skill.
# Args: <branch> <include_completed>
#   include_completed="true"  → return any matching context (active or completed)
#   include_completed="false" → skip contexts with completed: true
#
# Delegates to runs_reader.discover_current_run_id (issue #1437/#1417 fix).
# The Python helper implements a 3-pass precedence:
#   Pass 1 — active top-level contexts (completed=False, parent=None), 48h staleness cap.
#   Pass 2 — completed top-level (only when include_completed=true), with
#            context.timestamp >= HEAD commit timestamp. Rejects stale
#            completed contexts that predate the PR's HEAD commit — the
#            #1417 bug shape (chronologically old observe-context.json
#            on a re-used branch was previously dispatched as the PR's
#            skill identity).
#   Pass 3 — orphan-child fallback (parent != None, within 48h cap).
#            Preserves #1347 semantics: an embedded child's context is
#            returned only when its top-level parent context is absent
#            on disk; a stale completed top-level context that failed
#            Pass 2's recency check cannot sneak through here.
#
# Active variant (include_completed=false) skips Pass 2; the 3 active-only
# callers (skill-write-gate, skill-commit-gate, observe-commit-gate) still
# only see in-flight contexts (Caveat #1 from /solve Round 2 critic).
_detect_skill_for_branch_impl() {
  local branch="$1"
  local include_completed="$2"
  local project_dir="${CLAUDE_PROJECT_DIR:-.}"
  local include_completed_py="False"
  [[ "$include_completed" == "true" ]] && include_completed_py="True"
  # Resolve runs_reader.py via lib.sh's own location (BASH_SOURCE points at
  # this file's path) so the helper is found even when project_dir is a
  # fixture/tmp without .claude/. Falls back to project_dir-relative path.
  local lib_dir
  lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../scripts/lib" 2>/dev/null && pwd || echo "$project_dir/.claude/scripts/lib")"
  python3 -c "
import sys
sys.path.insert(0, '$lib_dir')
from runs_reader import discover_current_run_id
identity = discover_current_run_id(
    branch='$branch',
    project_dir='$project_dir',
    include_completed=$include_completed_py,
)
print(identity.skill if identity else '')
" 2>/dev/null || echo ""
}

# --- detect_active_skill_for_branch ---
# Scans *-context.json files, matches branch, returns skill name.
# Returns "" if no matching context found.
# Ignores epilogue-context.json and completed contexts.
# Usage: SKILL=$(detect_active_skill_for_branch "$BRANCH")
detect_active_skill_for_branch() {
  _detect_skill_for_branch_impl "$1" "false"
}

# --- detect_skill_for_branch ---
# Like detect_active_skill_for_branch but does NOT filter completed contexts.
# Use for PR gates where the skill has already finished all states and
# advance-state.sh has set completed: true before PR creation.
# When both a parent and an embedded child match the branch (e.g. a
# completed verify embedded inside a completed change), this resolves to
# the top-level parent so the parent's PR-gate config applies (#1347).
# Falls back to most-recent context when no top-level match exists.
# Returns "" if no matching context found.
# Usage: SKILL=$(detect_skill_for_branch "$BRANCH")
detect_skill_for_branch() {
  _detect_skill_for_branch_impl "$1" "true"
}

# --- resolve_active_identity ---
# Resolves the active execution identity for the current branch.
# Returns tab-separated: <skill>\t<run_id>\t<attributed_to>\t<ancestors_json>
# Empty line when no active context is found on this branch.
#
# Algorithm (single source of truth for agent-trace identity):
#   1. Scan .runs/*-context.json on current branch
#   2. Skip completed contexts (completed == true)
#   3. Skip epilogue-context.json
#   4. Skip stale contexts (timestamp older than 48h)
#   5. Return the one with latest timestamp
#
# Used by skill-agent-gate.sh (authoritative) and state-completion-gate.sh
# (cross-check only). Replaces ad-hoc timestamp-walks that diverged across
# hooks and caused embed-verify run_id mismatch (issue #941).
#
# Usage: IFS=$'\t' read -r SKILL RUN_ID ATTR ANCESTORS < <(resolve_active_identity)
resolve_active_identity() {
  local branch project_dir
  branch="$(get_branch)"
  project_dir="${CLAUDE_PROJECT_DIR:-.}"
  python3 -c "
import json, glob, os, datetime
branch = '$branch'
project = '$project_dir'
now = datetime.datetime.now(datetime.timezone.utc)
best = None
best_ts = ''
for f in glob.glob(os.path.join(project, '.runs', '*-context.json')):
    if 'epilogue-context' in f:
        continue
    try:
        d = json.load(open(f))
    except:
        continue
    if d.get('branch') and d.get('branch') != branch:
        continue
    if d.get('completed') is True:
        continue
    ts = d.get('timestamp', '')
    if not ts:
        continue
    # 48h staleness cap — protects against abandoned contexts from crashed runs.
    # Measured against LAST ACTIVITY, not run start: 'timestamp' is pinned at
    # run start (run_id derives from it and cannot be bumped), so keying off it
    # alone made any run outliving the cap age itself out mid-flight — identity
    # then resolved empty and every subagent trace degraded to
    # provenance: lead-orchestrated / partial: true. 'written_at' is refreshed
    # on every artifact write, so max(written_at, timestamp) is real liveness.
    def _parse(v):
        if not v:
            return None
        try:
            dt = datetime.datetime.fromisoformat(str(v).replace('Z', '+00:00'))
            return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)
        except Exception:
            return None
    _seen = [t for t in (_parse(d.get('written_at')), _parse(ts)) if t]
    if _seen and (now - max(_seen)).total_seconds() > 48 * 3600:
        continue
    if ts > best_ts:
        best_ts = ts
        best = d
if best is None:
    print('')
else:
    skill = best.get('skill', '')
    run_id = best.get('run_id', '')
    attr = best.get('attributed_to') or skill
    ancestors = best.get('ancestors') or []
    print('\t'.join([skill, run_id, attr, json.dumps(ancestors)]))
" 2>/dev/null || echo ""
}

# --- get_observation_gate ---
# Derives observation gate metadata from skill.yaml for a skill.
# Fields: gate_mechanism, gate_artifacts, pr_checks, strategy.
# Skills with observation section in skill.yaml use explicit config;
# skills without default to postcondition-only.
# Usage: MECH=$(get_observation_gate "upgrade" "gate_mechanism")
get_observation_gate() {
  local skill="$1"
  local field="$2"
  # Map mode-qualified skill names to directory. Canonical resolver:
  # resolve_skill_dir in .claude/scripts/lifecycle-lib.sh — extend BOTH when
  # adding a mode (see get_required_states above for why this stays local).
  local skill_dir="$skill"
  case "$skill" in
    iterate-check) skill_dir="iterate" ;;
    iterate-cross) skill_dir="iterate" ;;
    iterate-cross-phase2) skill_dir="iterate" ;;
  esac
  local skill_yaml="${CLAUDE_PROJECT_DIR:-.}/.claude/skills/$skill_dir/skill.yaml"
  [[ ! -f "$skill_yaml" ]] && { echo ""; return; }
  python3 -c "
import re
text = open('$skill_yaml').read()
field = '$field'

# Parse observation section from skill.yaml
obs = {}
in_obs = False
for line in text.split('\n'):
    if line.startswith('observation:'):
        in_obs = True
        continue
    if in_obs:
        if line and not line[0].isspace():
            break  # New top-level key
        m = re.match(r'\s+(\w+):\s*(.*)', line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if val.startswith('['):
                items = [s.strip().strip('\"').strip(\"'\") for s in val.strip('[]').split(',') if s.strip()]
                obs[key] = items
            else:
                obs[key] = val

# Map field names to skill.yaml observation keys
if field == 'gate_mechanism':
    print(obs.get('gate', ''))
elif field == 'gate_artifacts':
    arts = obs.get('artifacts', [])
    print(' '.join(arts) if isinstance(arts, list) else arts)
elif field == 'pr_checks':
    checks = obs.get('pr_checks', [])
    print(' '.join(checks) if isinstance(checks, list) else checks)
elif field == 'strategy':
    has_branch = bool(re.search(r'^branch:', text, re.MULTILINE))
    has_embed = bool(re.search(r'skill:\s*verify', text))
    if has_embed: print('verify-embedded')
    elif has_branch: print('A')
    else: print('B')
else:
    print('')
" 2>/dev/null || echo ""
}

# --- parse_advance_state_args ---
# Parse advance-state.sh arguments from a command string.
# Sets SKILL and STATE_ID globals. Expects $COMMAND to be set.
#
# Delegates to .claude/scripts/lib/check-advance-state-invocation.py when the
# helper exists (#1223) — its shlex-based parsing correctly skips strings
# inside heredoc bodies, --body arguments, and quoted regions. Falls back to
# the legacy substring grep when the helper is missing (e.g., during a partial
# template upgrade) so callers do not break.
parse_advance_state_args() {
  local _PASA_HELPER
  _PASA_HELPER="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || echo .)}/.claude/scripts/lib/check-advance-state-invocation.py"
  # Intentionally global — callers read SKILL and STATE_ID after invoking this function
  # shellcheck disable=SC2034
  if [[ -f "$_PASA_HELPER" ]]; then
    SKILL=$(printf '%s' "$COMMAND" | python3 "$_PASA_HELPER" --print-skill 2>/dev/null || echo "")
    # shellcheck disable=SC2034
    STATE_ID=$(printf '%s' "$COMMAND" | python3 "$_PASA_HELPER" --print-state-id 2>/dev/null || echo "")
  else
    SKILL=$(echo "$COMMAND" | grep -oE 'advance-state\.sh[[:space:]]+([a-z-]+)' | awk '{print $NF}' || echo "")
    # shellcheck disable=SC2034
    STATE_ID=$(echo "$COMMAND" | grep -oE 'advance-state\.sh[[:space:]]+[a-z-]+[[:space:]]+([0-9a-z_]+)' | awk '{print $NF}' || echo "")
  fi
}

# --- get_archetype ---
# Reads archetype from context JSON (matching hook patterns) or experiment.yaml.
# Returns "web-app" if absent or on error.
# Usage: ARCH=$(get_archetype)
get_archetype() {
  local project_dir="${CLAUDE_PROJECT_DIR:-.}"
  # 1. Try context JSON files
  for f in "$project_dir"/.runs/*-context.json; do
    [[ -f "$f" ]] || continue
    local arch
    arch=$(read_json_field "$f" "archetype")
    [[ -n "$arch" ]] && { echo "$arch"; return; }
  done
  # 2. Fallback to experiment.yaml
  python3 -c "
import yaml
try:
    d = yaml.safe_load(open('$project_dir/experiment/experiment.yaml'))
    print(d.get('type', 'web-app'))
except: print('web-app')
" 2>/dev/null || echo "web-app"
}

# --- is_web_app_only ---
# Returns 0 (true) if archetype is web-app, 1 (false) otherwise.
# Usage: if is_web_app_only; then ... fi
is_web_app_only() {
  [[ "$(get_archetype)" == "web-app" ]]
}
