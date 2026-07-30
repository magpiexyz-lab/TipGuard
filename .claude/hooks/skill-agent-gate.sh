#!/usr/bin/env bash
# skill-agent-gate.sh — Universal PreToolUse hook for Agent tool.
# Manifest-driven declarative checks + convention gates + registry defense-in-depth.
# Replaces: agent-state-gate.sh (PR 5, v2 migration step 5/8).

set -euo pipefail

# Source lifecycle-lib.sh for resolve_framework_manifest (issue #1006).
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../scripts" && pwd)"
source "$_SCRIPT_DIR/lifecycle-lib.sh"

source "$(dirname "$0")/lib.sh"
parse_payload

SUBAGENT_TYPE=$(read_payload_field "tool_input.subagent_type")

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
TRACES_DIR="$PROJECT_DIR/.runs/agent-traces"
ERRORS=()

# ── Fast-path: no context files → no skill active → allow ──
shopt -s nullglob
CTX_FILES=("$PROJECT_DIR"/.runs/*-context.json)
shopt -u nullglob
if [[ ${#CTX_FILES[@]} -eq 0 ]]; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

# ── Detect active skill via single-source identity helper ──
# Replaces a prior timestamp-walk that disagreed with state-completion-gate's
# arg-driven lookup on embed-verify (issue #941). The helper filters by
# current branch + completed flag + 48h staleness cap (R2 C2).
#
# Identity-resolution failure handling (#1224): when resolve_active_identity
# returns empty (no matching context, stale branch field — see #1222), the
# legacy behavior was to exit 0 silently — which let the agent spawn proceed
# but dropped the spawn-log entry. Downstream consumers (compliance-audit,
# Step 5a retrospective Q3, validate-recovery) then could not tell whether
# the agent ran at all. The new behavior writes a degraded spawn-log entry
# so the failure is observable, then exits 0 (we still allow the spawn —
# blocking would silently degrade many test/diagnostic flows).
ACTIVE_IDENTITY="$(resolve_active_identity)"
DEGRADED_REASON=""
if [[ -z "$ACTIVE_IDENTITY" ]]; then
  DEGRADED_REASON="active_identity_unresolvable"
fi
if [[ -z "$DEGRADED_REASON" ]]; then
  IFS=$'\t' read -r ACTIVE_SKILL ACTIVE_RUN_ID ACTIVE_ATTR _ACTIVE_ANCESTORS <<< "$ACTIVE_IDENTITY"
  if [[ -z "$ACTIVE_SKILL" ]]; then
    DEGRADED_REASON="active_skill_empty"
  fi
fi

if [[ -n "$DEGRADED_REASON" ]]; then
  # AOC v1.2 / #1275: lead-orchestrated post-completion honoring path.
  # When the lead orchestrates a true post-completion re-spawn, it exports
  # SOURCE_RUN_ID + SOURCE_SKILL env vars before invoking the Agent tool.
  # The hook independently validates three gates (see
  # `.claude/scripts/lib/source_identity_validator.py`
  # `validate_source_identity_for_hook`):
  #   (i)   SOURCE_RUN_ID + SOURCE_SKILL match a context with completed:true
  #   (ii)  active identity is empty (we're already in this branch — gate
  #         (ii) is structural here; the validator double-checks)
  #   (iii) no prior NON-degraded entry exists for (agent, SOURCE_RUN_ID)
  #         — anti-replay defense.
  # On success: stamp a non-degraded entry stamped with the SOURCE identity.
  # On failure: fall through to the existing degraded path AND emit the
  # validator's errors to stderr so the lead sees why honoring was refused.
  _SAG_HONOR_SOURCE="false"
  if [[ -n "${SOURCE_RUN_ID:-}" && -n "${SOURCE_SKILL:-}" ]]; then
    # Path to the validator script relative to THIS hook (mirrors the
    # `agent-gate-check.py` invocation pattern below at line ~143).
    # Avoids depending on $PROJECT_DIR which may resolve to a fixture
    # or worktree path without our code laid down.
    _SAG_VALIDATOR_PY="$(dirname "$0")/../scripts/lib/source_identity_validator.py"
    # Use `if cmd; then ... else ...` form so `set -e` does NOT trigger
    # on validator non-zero exit. Bash 3.2 (macOS default) triggers -e
    # on `var=$(failing-cmd)` assignment, even though POSIX/modern Bash
    # do not. The if-form is portable across both.
    if _SAG_HOOK_VALIDATOR_OUT=$(python3 "$_SAG_VALIDATOR_PY" \
        --mode hook \
        --source-run-id "$SOURCE_RUN_ID" \
        --source-skill "$SOURCE_SKILL" \
        --agent "$SUBAGENT_TYPE" \
        --project-dir "$PROJECT_DIR" 2>&1); then
      _SAG_HONOR_SOURCE="true"
    else
      echo "WARN: skill-agent-gate: SOURCE_RUN_ID/SOURCE_SKILL honoring REFUSED for $SUBAGENT_TYPE:" >&2
      echo "$_SAG_HOOK_VALIDATOR_OUT" >&2
    fi
  fi

  _SAG_DEGRADED_LOG="$PROJECT_DIR/.runs/agent-spawn-log.jsonl"
  mkdir -p "$PROJECT_DIR/.runs"
  _SAG_DEGRADED_HEAD_SHA=$(git rev-parse HEAD 2>/dev/null || echo "")

  if [[ "$_SAG_HONOR_SOURCE" == "true" ]]; then
    echo "INFO: skill-agent-gate: lead-orchestrated source identity HONORED for $SUBAGENT_TYPE (skill=$SOURCE_SKILL run_id=$SOURCE_RUN_ID)" >&2
    export _SAG_SUBAGENT_TYPE="$SUBAGENT_TYPE"
    export _SAG_SOURCE_SKILL="$SOURCE_SKILL"
    export _SAG_SOURCE_RUN_ID="$SOURCE_RUN_ID"
    export _SAG_DEGRADED_HEAD_SHA _SAG_DEGRADED_LOG
    python3 -c "
import json, datetime, os
entry = {
    'agent': os.environ['_SAG_SUBAGENT_TYPE'],
    'skill': os.environ['_SAG_SOURCE_SKILL'],
    'run_id': os.environ['_SAG_SOURCE_RUN_ID'],
    'attributed_to': os.environ['_SAG_SOURCE_SKILL'],
    'spawn_index': 0,
    'head_sha': os.environ['_SAG_DEGRADED_HEAD_SHA'],
    'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'hook': 'skill-agent-gate',
    'lead_orchestrated': True,
}
with open(os.environ['_SAG_DEGRADED_LOG'], 'a') as f:
    f.write(json.dumps(entry) + '\n')
" 2>/dev/null || true
    unset _SAG_SUBAGENT_TYPE _SAG_SOURCE_SKILL _SAG_SOURCE_RUN_ID
    # friction-skip: trivial-fast-path — input absent or non-applicable
    exit 0
  fi

  # Best-available run_id: scan non-completed contexts (any branch) for the
  # latest run_id rather than write 'unknown', so downstream provenance scans
  # (state-completion-gate.sh:223,289) can still cross-reference the spawn.
  # Falls back to 'unknown' only when no non-completed context exists.
  #
  # coherence-allow: provenance-blind-read — degraded-path attribution
  # spans branches by design (a degraded agent spawn must attribute to ANY
  # in-flight skill, not just one on the current branch). runs_reader's
  # discover_current_run_id is branch-scoped and unsuitable here.
  _SAG_BEST_RUN_ID=$(python3 -c "
import json, glob, os
project = '$PROJECT_DIR'
best_ts = ''
best_run = ''
best_skill = ''
for f in glob.glob(os.path.join(project, '.runs', '*-context.json')):
    if 'epilogue-context' in f:
        continue
    try:
        d = json.load(open(f))
    except Exception:
        continue
    if d.get('completed') is True:
        continue
    ts = d.get('timestamp', '')
    if ts and ts > best_ts:
        best_ts = ts
        best_run = d.get('run_id', '') or ''
        best_skill = d.get('skill', '') or ''
print(best_skill + '\t' + best_run)
" 2>/dev/null || echo $'\t')
  IFS=$'\t' read -r _SAG_FALLBACK_SKILL _SAG_FALLBACK_RUN_ID <<< "$_SAG_BEST_RUN_ID"
  : "${_SAG_FALLBACK_SKILL:=unknown}"
  : "${_SAG_FALLBACK_RUN_ID:=unknown}"

  echo "WARN: skill-agent-gate: $DEGRADED_REASON for $SUBAGENT_TYPE — writing degraded spawn-log entry (skill=$_SAG_FALLBACK_SKILL run_id=$_SAG_FALLBACK_RUN_ID)" >&2

  python3 -c "
import json, datetime
entry = {
    'agent': '$SUBAGENT_TYPE',
    'skill': '$_SAG_FALLBACK_SKILL',
    'run_id': '$_SAG_FALLBACK_RUN_ID',
    'attributed_to': '$_SAG_FALLBACK_SKILL',
    'spawn_index': 0,
    'head_sha': '$_SAG_DEGRADED_HEAD_SHA',
    'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'hook': 'skill-agent-gate',
    'degraded': True,
    'degradation_reason': '$DEGRADED_REASON',
}
with open('$_SAG_DEGRADED_LOG', 'a') as f:
    f.write(json.dumps(entry) + '\n')
" 2>/dev/null || true
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

# ── Load manifest and check if agent is declared ──
# ACTIVE_SKILL can be mode-qualified (iterate-cross) while the framework
# manifest file is named after the BASE skill only — resolve through the
# base skill or the gate fail-opens for every mode-qualified run (flagged in
# #1990's closure; same pattern as lifecycle-finalize.sh / advance-state.sh).
read -r BASE_SKILL _SKILL_MODE <<< "$(resolve_skill_dir "$ACTIVE_SKILL")"
MANIFEST=$(resolve_framework_manifest "$BASE_SKILL")

if [[ ! -f "$MANIFEST" ]]; then
  # No manifest = no active skill lifecycle — allow.
  # #1349 follow-up: a missing manifest where one is expected is a silent
  # fail-open. Friction-log so config drift is observable in retrospectives.
  _write_hook_friction "skill-agent-gate: manifest $MANIFEST absent for active skill '$ACTIVE_SKILL' — failing open."
  exit 0
fi

export _SAG_MANIFEST="$MANIFEST" _SAG_AGENT="$SUBAGENT_TYPE"
AGENT_IN_MANIFEST=$(python3 -c "
import json, os
m = json.load(open(os.environ['_SAG_MANIFEST']))
agents = m.get('agents', {})
print('yes' if os.environ['_SAG_AGENT'] in agents else 'no')
" 2>/dev/null || echo "no")
unset _SAG_MANIFEST _SAG_AGENT

if [[ "$AGENT_IN_MANIFEST" != "yes" ]]; then
  # Agent not declared in manifest — allow (manifest is authoritative in v2)
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

# ══════════════════════════════════════════════════════════════════════
# MANIFEST PATH
# ══════════════════════════════════════════════════════════════════════

# ── Registry checks (defense-in-depth): required_states, deny_isolation, deny_background, artifacts ──
export _PAYLOAD="$PAYLOAD"
export _AGENT_TYPE="$SUBAGENT_TYPE"
GATE_RESULT=$(python3 "$(dirname "$0")/../scripts/agent-gate-check.py" 2>/dev/null || echo "$ACTIVE_SKILL	")
unset _PAYLOAD _AGENT_TYPE

# Parse tab-separated output: skill\twarn on line 1, errors on lines 2+
GATE_WARN=$(echo "$GATE_RESULT" | head -1 | cut -f2)
if [[ -n "$GATE_WARN" ]]; then
  echo "WARN: skill-agent-gate: $GATE_WARN" >&2
fi

# Accumulate registry errors
while IFS= read -r line; do
  [[ -n "$line" ]] && ERRORS+=("$line")
done < <(echo "$GATE_RESULT" | tail -n +2)

# ── Manifest declarative checks: requires_archetype, requires_traces, scope_condition ──
# REF: Archetype branching — see .claude/patterns/archetype-behavior-check.md Quick-Reference Table.
# All values passed via environment variables to avoid shell injection in Python literals.
export _SAG_MANIFEST="$MANIFEST" _SAG_AGENT="$SUBAGENT_TYPE"
export _SAG_PROJECT="$PROJECT_DIR" _SAG_TRACES="$TRACES_DIR"
export _SAG_SKILL="$ACTIVE_SKILL" _SAG_RUN_ID="$ACTIVE_RUN_ID"
DECL_ERRORS=$(python3 -c "
import json, os

manifest = json.load(open(os.environ['_SAG_MANIFEST']))
agent_type = os.environ['_SAG_AGENT']
agent = manifest.get('agents', {}).get(agent_type, {})
project = os.environ['_SAG_PROJECT']
traces_dir = os.environ['_SAG_TRACES']
skill = os.environ['_SAG_SKILL']
errors = []

# --- requires_archetype ---
req_arch = agent.get('requires_archetype', '')
if req_arch:
    actual_arch = 'web-app'
    for ctx_name in ['verify-context.json', f'{skill}-context.json']:
        ctx_path = os.path.join(project, '.runs', ctx_name)
        if os.path.isfile(ctx_path):
            try:
                actual_arch = json.load(open(ctx_path)).get('archetype', 'web-app')
            except: pass
            break
    if actual_arch != req_arch:
        errors.append(f'{agent_type} requires archetype={req_arch} but got archetype={actual_arch}')

# --- requires_traces ---
def check_traces(trace_names, context_label=''):
    suffix = f' ({context_label})' if context_label else ''
    for tn in trace_names:
        tf = os.path.join(traces_dir, f'{tn}.json')
        if not os.path.isfile(tf):
            errors.append(f'{tn}.json trace missing — prerequisite agent has not completed{suffix}')
            continue
        try:
            td = json.load(open(tf))
        except:
            errors.append(f'{tn}.json could not be parsed{suffix}')
            continue
        if 'verdict' not in td:
            errors.append(f'{tn}.json missing verdict — agent may still be running{suffix}')
        # run_id freshness check — compare trace run_id against the resolved
        # active identity (not a hardcoded verify-context.json). This matches
        # the spawn-log write on line 188+ and closes the embed-verify
        # divergence that motivated issue #941.
        run_id = td.get('run_id', '')
        expected = os.environ.get('_SAG_RUN_ID', '')
        if expected and run_id and run_id != expected:
            errors.append(f'{tn}.json has stale run_id={run_id}, expected {expected}{suffix}')

check_traces(agent.get('requires_traces', []))

# --- mode (foreground vs background) ---
# Prose-gate verify-state-2-phase1-spawn-no-background:
# When skill.yaml declares mode:foreground for an agent, deny spawns with
# run_in_background:true. Declarative opt-in — agents that omit mode: are
# unaffected. (.claude/patterns/prose-gates.json)
declared_mode = agent.get('mode', '')
if declared_mode == 'foreground':
    try:
        _sag_payload = json.loads(os.environ.get('_PAYLOAD', '{}'))
        _run_in_bg = _sag_payload.get('tool_input', {}).get('run_in_background', False)
    except Exception:
        _run_in_bg = False
    if _run_in_bg:
        errors.append(
            f'{agent_type} declares mode:foreground in skill.yaml but Agent '
            'invoked with run_in_background:true — prose-gate '
            'verify-state-2-phase1-spawn-no-background'
        )

# --- scope_condition ---
sc = agent.get('scope_condition', {})
if sc:
    scope_val = sc.get('scope', '')
    actual_scope = ''
    for ctx_name in ['verify-context.json', f'{skill}-context.json']:
        ctx_path = os.path.join(project, '.runs', ctx_name)
        if os.path.isfile(ctx_path):
            try:
                actual_scope = json.load(open(ctx_path)).get('scope', '')
            except: pass
            break
    if actual_scope == scope_val:
        check_traces(sc.get('requires_traces', []), f'scope={scope_val}')

for e in errors:
    print(e)
" 2>/dev/null || echo "")
unset _SAG_MANIFEST _SAG_AGENT _SAG_PROJECT _SAG_TRACES _SAG_SKILL _SAG_RUN_ID

while IFS= read -r line; do
  [[ -n "$line" ]] && ERRORS+=("$line")
done <<< "$DECL_ERRORS"

# ── Convention gate: .claude/skills/<skill>/gates/<subagent>.sh ──
# Skill directories are base-named — use BASE_SKILL for the gate path.
GATE_SCRIPT="$PROJECT_DIR/.claude/skills/$BASE_SKILL/gates/$SUBAGENT_TYPE.sh"

if [[ -f "$GATE_SCRIPT" ]]; then
  export PAYLOAD SUBAGENT_TYPE PROJECT_DIR TRACES_DIR
  GATE_OUTPUT=$(bash "$GATE_SCRIPT" 2>&1) || {
    [[ -n "$GATE_OUTPUT" ]] && ERRORS+=("$GATE_OUTPUT")
  }
fi

# ── Cross-skill agent checks ──
if [[ "$SUBAGENT_TYPE" == "pattern-classifier" ]]; then
  # AOC v1: pattern-classifier classifies from the canonical ledger; fix-log
  # is a rendered artifact. Ledger preferred; fix-log.md accepted as
  # transitional fallback for pre-AOC-v1 skill runs.
  if [[ ! -f "$PROJECT_DIR/.runs/fix-ledger.jsonl" ]] && [[ ! -f "$PROJECT_DIR/.runs/fix-log.md" ]]; then
    ERRORS+=("fix-ledger.jsonl and fix-log.md both missing — required for pattern-classifier (AOC v1 FLS v1)")
  fi
fi

# ── Universal checks ──
check_efficiency_directives

# ── Deny or allow ──
if [[ ${#ERRORS[@]} -gt 0 ]]; then
  deny_errors "State gate blocked: " "Complete prerequisite states before spawning $SUBAGENT_TYPE."
fi

# ── Record spawn in agent-spawn-log.jsonl (tamper-protected) ──
# This file is guarded by trace-write-guard.sh (Bash) and artifact-integrity-gate.sh
# (Write/Edit). Only this hook can write to it because hook execution does not
# trigger PreToolUse hooks.
#
# run_id is the active embedded skill's run_id (from resolve_active_identity —
# authoritative, issue #941 fix).
# spawn_index is monotonic per run, binding aggregate lead-merge traces to
# specific spawns so forged siblings can't pass (R2 C3).
# head_sha is git rev-parse HEAD at spawn time, used by validate-recovery.sh
# diff-fix correlation (R2 C6).
_SAG_SPAWN_LOG="$PROJECT_DIR/.runs/agent-spawn-log.jsonl"
mkdir -p "$PROJECT_DIR/.runs"

# Compute next spawn_index for this run_id (count of existing entries + 1)
_SAG_SPAWN_INDEX=$(python3 -c "
import json, os
log = '$_SAG_SPAWN_LOG'
run_id = '$ACTIVE_RUN_ID'
if not os.path.isfile(log) or not run_id:
    print(1)
else:
    n = 0
    with open(log) as f:
        for line in f:
            try:
                e = json.loads(line)
                if e.get('run_id') == run_id:
                    n += 1
            except: pass
    print(n + 1)
" 2>/dev/null || echo "1")

_SAG_HEAD_SHA=$(git rev-parse HEAD 2>/dev/null || echo "")

python3 -c "
import json, datetime
entry = {
    'agent': '$SUBAGENT_TYPE',
    'skill': '$ACTIVE_SKILL',
    'run_id': '$ACTIVE_RUN_ID',
    'attributed_to': '$ACTIVE_ATTR',
    'spawn_index': $_SAG_SPAWN_INDEX,
    'head_sha': '$_SAG_HEAD_SHA',
    'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'hook': 'skill-agent-gate',
}
with open('$_SAG_SPAWN_LOG', 'a') as f:
    f.write(json.dumps(entry) + '\n')
" 2>/dev/null || true

# friction-skip: trivial-fast-path — input absent or non-applicable
exit 0
