#!/usr/bin/env bash
# state-completion-gate.sh — Claude Code PreToolUse hook for Bash commands.
# Validates state postconditions before allowing completed_states updates.
# Works with advance-state.sh: when the LLM marks a state complete, this hook
# checks that the state's postcondition artifacts actually exist on disk.
# Supports all skills via per-skill registry in state-registry.json.
set -euo pipefail

source "$(dirname "$0")/lib.sh"
parse_payload

COMMAND=$(read_payload_field "tool_input.command")

# Only fire on actual advance-state.sh invocations at command-head position
# (#1223). Naive substring grep fired on script names appearing inside heredoc
# bodies, --body arguments, and quoted strings — the helper strips heredocs,
# shlex-tokenizes, and only matches at command-head positions. Fails open on
# parse errors so the gate never silently flips to fail-closed (issue #1223).
_PROJECT_DIR_GATE="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || echo .)}"
_INVOCATION_HELPER="$_PROJECT_DIR_GATE/.claude/scripts/lib/check-advance-state-invocation.py"
if [[ ! -f "$_INVOCATION_HELPER" ]]; then
  # Helper missing — fall back to the legacy grep so we do not over-block.
  if ! printf '%s' "$COMMAND" | grep -qE 'bash\s+\S*advance-state\.sh\s'; then
    # friction-skip: trivial-fast-path — input absent or non-applicable
    exit 0
  fi
  parse_advance_state_args
else
  if ! printf '%s' "$COMMAND" | python3 "$_INVOCATION_HELPER"; then
    # friction-skip: trivial-fast-path — input absent or non-applicable
    exit 0
  fi
  SKILL=$(printf '%s' "$COMMAND" | python3 "$_INVOCATION_HELPER" --print-skill)
  STATE_ID=$(printf '%s' "$COMMAND" | python3 "$_INVOCATION_HELPER" --print-state-id)
fi

if [[ -z "$SKILL" || -z "$STATE_ID" ]]; then
  # #1349 fix: empty SKILL/STATE means parse helper succeeded but produced
  # empty fields — a silent fail-open vs malformed input. Friction-log so
  # the parse-failure is observable. Fail-open per Constraint 19.
  _write_hook_friction "state-completion-gate: empty SKILL='$SKILL' / STATE_ID='$STATE_ID' after parse — failing open. COMMAND prefix: ${COMMAND:0:120}"
  exit 0
fi

# Format validation: SKILL and STATE_ID must be safe shell-injection-free identifiers.
# Reject malformed input (kept as defense-in-depth; the helper's tokenization
# normally guarantees well-formed values, but a future caller could still pass
# garbage args).
if ! [[ "$SKILL" =~ ^[a-z][a-z0-9_-]*$ && "$STATE_ID" =~ ^[a-z]?[0-9]+[a-z]?$ ]]; then
  deny "State completion gate: malformed args SKILL='$SKILL' STATE_ID='$STATE_ID'. Run advance-state.sh with one skill/state per Bash call (do not chain with &&)."
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
REGISTRY="$PROJECT_DIR/.claude/patterns/state-registry.json"

if [[ ! -f "$REGISTRY" ]]; then
  deny "State registry missing: $REGISTRY. Cannot verify postconditions for $SKILL STATE $STATE_ID. Restore from git (\`git checkout main -- .claude/patterns/state-registry.json\`) or run /upgrade to sync template."
fi

# --- BLOCK verdict check: deny state advancement if any gate has BLOCK on this branch ---
VERDICTS_DIR="$PROJECT_DIR/.runs/gate-verdicts"
if [[ -d "$VERDICTS_DIR" ]]; then
  BRANCH=$(get_branch)
  for gf in "$VERDICTS_DIR"/*.json; do
    [[ -f "$gf" ]] || continue
    gv=$(read_json_field "$gf" "verdict")
    [[ "$gv" != "BLOCK" ]] && continue
    gvb=$(read_json_field "$gf" "branch")
    if [[ "$gvb" == "$BRANCH" ]]; then
      gate_id=$(basename "$gf" .json)
      deny "Gate $gate_id has BLOCK verdict. Fix blocking items and re-run gate-keeper before advancing."
    fi
  done
fi

# Look up VERIFY command for this skill + state (nested lookup — keep inline)
# Supports both string format ("test -f ...") and object format ({"verify": "...", "calls": [...]})
# defer_verify_when_writer (#1339): per-state opt-in list of artifact paths whose
# presence in a sibling write-gate-artifact.sh chain segment justifies skipping
# synchronous VERIFY (deferred to advance-state.sh's pre-append re-check).
ENTRY_DATA=$(python3 -c "
import json
reg = json.load(open('$REGISTRY'))
entry = reg.get('$SKILL', {}).get('$STATE_ID', '')
if isinstance(entry, dict):
    print(entry.get('verify', '') + '\t' + json.dumps(entry.get('calls', [])) + '\t' + json.dumps(entry.get('defer_verify_when_writer', [])))
else:
    print(str(entry) + '\t\t')
" 2>&1) || {
  deny "State registry parse error: cannot read $REGISTRY for $SKILL STATE $STATE_ID. Output: $ENTRY_DATA. Fix the JSON syntax or restore from git."
}

VERIFY_CMD=$(printf '%s' "$ENTRY_DATA" | cut -f1)
CALLS_JSON=$(printf '%s' "$ENTRY_DATA" | cut -f2)
DEFER_PATHS_JSON=$(printf '%s' "$ENTRY_DATA" | cut -f3)

# --- Chain check: verify all prior states are in completed_states ---
# This prevents skipping states (e.g., jumping from STATE 0 to STATE 3).
# Uses registry key order as the canonical state sequence.
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../scripts" && pwd)"
source "$_SCRIPT_DIR/lifecycle-lib.sh"
CTX_FILE=$(resolve_context_path "$SKILL")

# --- Identity cross-check (issue #941 defense-in-depth) ---
# $SKILL is authoritative (from advance-state.sh args). When the active
# identity from resolve_active_identity disagrees, warn — it indicates a
# stale or crossed context that should be investigated, but don't block
# (the chain check / VERIFY command below are the real gates).
ACTIVE_IDENTITY="$(resolve_active_identity)"
if [[ -n "$ACTIVE_IDENTITY" ]]; then
  IFS=$'\t' read -r _SCG_ACTIVE_SKILL _ _ _ <<< "$ACTIVE_IDENTITY"
  if [[ -n "$_SCG_ACTIVE_SKILL" && "$_SCG_ACTIVE_SKILL" != "$SKILL" ]]; then
    echo "WARN: state-completion-gate: args-skill='$SKILL' but resolve_active_identity returned '$_SCG_ACTIVE_SKILL' — possible stale context" >&2
  fi
  unset _SCG_ACTIVE_SKILL
fi

# --- _log_verify_trace ---
# Append a verify pass/fail entry to the execution trace.
# Args: <skill> <state_id> <result> [verify_cmd]
_log_verify_trace() {
  local skill="$1" state_id="$2" result="$3" verify_cmd="${4:-}"
  python3 -c "
import json, os, datetime
try:
    ctx_path = '$CTX_FILE'
    run_id = json.load(open(ctx_path)).get('run_id', 'unknown') if os.path.exists(ctx_path) else 'unknown'
    trace_file = '.runs/${skill}-execution-trace.jsonl'
    is_first = True
    if os.path.exists(trace_file):
        with open(trace_file) as f:
            for line in f:
                try:
                    e = json.loads(line)
                    if e.get('run_id') == run_id and e.get('state_id') == '$state_id':
                        is_first = False
                        break
                except: pass
    os.makedirs('.runs', exist_ok=True)
    entry = {
        'run_id': run_id,
        'skill': '$skill',
        'state_id': '$state_id',
        'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'verify_result': '$result',
        'is_first_attempt': is_first
    }
    verify_cmd = '''$verify_cmd'''
    if verify_cmd:
        entry['verify_cmd'] = verify_cmd
    with open(trace_file, 'a') as f:
        f.write(json.dumps(entry) + '\n')
except: pass
" 2>/dev/null || true
}

if [[ -f "$CTX_FILE" ]]; then
  CHAIN_RESULT=$(python3 -c "
import json, sys
reg = json.load(open('$REGISTRY'))
ctx = json.load(open('$CTX_FILE'))
cs = [str(s) for s in ctx.get('completed_states', [])]
skip = set(str(s) for s in ctx.get('skip_states', []))
states = list(reg.get('$SKILL', {}).keys())
cur = '$STATE_ID'
if cur in states:
    idx = states.index(cur)
    missing = [s for s in states[:idx] if s not in cs and s not in skip]
    if missing:
        print(','.join(missing))
else:
    print('UNREGISTERED')
" 2>/dev/null || echo "")

  if [[ "$CHAIN_RESULT" == "UNREGISTERED" ]]; then
    deny "State completion gate: $SKILL STATE $STATE_ID — not in state-registry.json. Register before advancing."
  elif [[ -n "$CHAIN_RESULT" ]]; then
    deny "State completion gate: $SKILL STATE $STATE_ID — prior states not complete: [$CHAIN_RESULT]. Complete earlier states before advancing."
  fi
fi

# --- Artifact check: run VERIFY command from registry ---
if [[ "$VERIFY_CMD" == "true" ]]; then
  exit 0  # Intentional no-check (explicitly registered as "true")
fi

if [[ -z "$VERIFY_CMD" ]]; then
  deny "State completion gate: $SKILL STATE $STATE_ID — no VERIFY in registry. Add postcondition entry before advancing."
fi

# --- Chain-aware deferral check (#1339) ---
# When defer_verify_when_writer is set and the Bash chain contains a sibling
# `bash write-gate-artifact.sh --path <P>` whose <P> is enumerated, skip the
# synchronous VERIFY eval. advance-state.sh's pre-append VERIFY (run AFTER
# the chain executes) becomes the gate.
SKIP_VERIFY=0
if [[ -n "$DEFER_PATHS_JSON" && "$DEFER_PATHS_JSON" != "[]" && "$DEFER_PATHS_JSON" != "null" ]]; then
  _DECOMPOSER="$_PROJECT_DIR_GATE/.claude/scripts/lib/decompose-bash-chain.py"
  if [[ -f "$_DECOMPOSER" ]]; then
    _DECOMP_OUT=$(printf '%s' "$COMMAND" | python3 "$_DECOMPOSER" 2>&1)
    _DECOMP_EXIT=$?
    if [[ $_DECOMP_EXIT -ne 0 ]]; then
      # FAIL CLOSED: parse ambiguity → deny rather than silently skip
      deny "State completion gate: chain decomposition failed for $SKILL STATE $STATE_ID (parser uncertain). Run write-gate-artifact.sh and advance-state.sh as separate Bash invocations."
    fi
    # Walk segments — if any sibling is `bash .../write-gate-artifact.sh --path <P>`
    # with <P> in defer_verify_when_writer, set SKIP_VERIFY=1.
    SKIP_VERIFY=$(DEFER_PATHS_JSON_ENV="$DEFER_PATHS_JSON" python3 -c "
import sys, os, json
defer = set(json.loads(os.environ['DEFER_PATHS_JSON_ENV']))
out = sys.stdin.read()
for line in out.split('\n'):
    line = line.rstrip('\r\n')
    if not line: continue
    parts = line.split('\t', 1)
    head = parts[0]
    if not head.endswith('write-gate-artifact.sh'): continue
    args = []
    if len(parts) > 1:
        try: args = json.loads(parts[1])
        except: continue
    # Sibling write-gate-artifact.sh segment can be either:
    #   - bash .../write-gate-artifact.sh ... (head=bash, args[0] ends with write-gate-artifact.sh)
    #   - .../write-gate-artifact.sh ... (head ends with write-gate-artifact.sh)
    # We're already filtering on head endswith write-gate-artifact.sh — this
    # catches the head==write-gate-artifact case. For head==bash, we look at
    # args[0] separately below.
    for i, a in enumerate(args):
        if a == '--path' and i + 1 < len(args) and args[i+1] in defer:
            # friction-skip: post-validation — exit follows authoritative decision (allow-list match, deny path, or successful validation)
            print('1'); sys.exit(0)
# Also handle bash <writer> --path ... shape
for line in out.split('\n'):
    line = line.rstrip('\r\n')
    if not line: continue
    parts = line.split('\t', 1)
    head = parts[0]
    if head != 'bash': continue
    args = []
    if len(parts) > 1:
        try: args = json.loads(parts[1])
        except: continue
    if not args or not args[0].endswith('write-gate-artifact.sh'): continue
    for i, a in enumerate(args):
        if a == '--path' and i + 1 < len(args) and args[i+1] in defer:
            # friction-skip: post-validation — exit follows authoritative decision (allow-list match, deny path, or successful validation)
            print('1'); sys.exit(0)
print('0')
" <<< "$_DECOMP_OUT" 2>/dev/null || echo "0")
  fi
fi

if [[ "$SKIP_VERIFY" == "1" ]]; then
  # Log success-path friction record so the deferral is visible in retrospectives
  HOOK_FRICTION_HOOK="state-completion-gate.sh" \
  HOOK_FRICTION_REASON="deferred-verify (sibling write-gate-artifact in chain) — $SKILL STATE $STATE_ID" \
  HOOK_FRICTION_TOOL_NAME="Bash" \
  HOOK_FRICTION_BLOCKED_CMD="" \
  python3 "$PROJECT_DIR/.claude/scripts/append-hook-friction.py" 2>/dev/null || true
  _log_verify_trace "$SKILL" "$STATE_ID" "deferred" "$VERIFY_CMD"
else
  # Run the verify command from project root
  cd "$PROJECT_DIR"
  if ! eval "$VERIFY_CMD" >/dev/null 2>&1; then
    # Trace: log VERIFY failure
    _log_verify_trace "$SKILL" "$STATE_ID" "fail" "$VERIFY_CMD"
    deny "State completion gate: $SKILL STATE $STATE_ID postconditions not met. VERIFY failed: $VERIFY_CMD — complete this state's actions before marking it done."
  fi
fi

# --- Calls artifact check: verify each call's artifact exists ---
if [[ -n "$CALLS_JSON" && "$CALLS_JSON" != "[]" ]]; then
  MISSING_ARTIFACTS=$(printf '%s' "$CALLS_JSON" | python3 -c "
import json, os, sys
calls = json.load(sys.stdin)
missing = []
for c in calls:
    art = c.get('artifact', '')
    if art and not os.path.isfile(art):
        missing.append(art + ' (required by ' + c.get('path', '?') + ')')
if missing:
    print('; '.join(missing))
" 2>/dev/null || echo "")

  if [[ -n "$MISSING_ARTIFACTS" ]]; then
    deny "State completion gate: $SKILL STATE $STATE_ID postconditions not met. Missing call artifacts: $MISSING_ARTIFACTS"
  fi
fi

# ── Universal spawn provenance check ──
# For each completed trace in agent-traces/, verify a matching spawn record
# exists in agent-spawn-log.jsonl. Excludes recovery traces, started-only
# traces, merge artifacts, and non-manifest agents.
# This is the Option B universal check — works for ALL skills, zero config.
SPAWN_LOG="$PROJECT_DIR/.runs/agent-spawn-log.jsonl"
# $SKILL from the advance-state.sh arg can be mode-qualified (iterate-cross);
# the framework manifest is base-named — resolve through the base skill or
# this provenance check fail-opens for mode-qualified runs (#1990 closure
# flag). NOTE: resolve_context_path "$SKILL" earlier in this file and the
# '$SKILL' + '-context.json' path inside the python below are CORRECT with
# the qualified name (context files ARE mode-qualified) — do not "fix" them.
read -r _SCG_BASE_SKILL _SCG_SKILL_MODE <<< "$(resolve_skill_dir "$SKILL")"
_SCG_MANIFEST=$(resolve_framework_manifest "$_SCG_BASE_SKILL")
if [[ -f "$SPAWN_LOG" && -f "$_SCG_MANIFEST" ]]; then
  PROVENANCE_RESULT=$(python3 -c "
import json, glob, os, sys

# #1256: Sanctioned coverage_provider allowlist for lead-synthesized aggregates
# whose corresponding agents were never spawned (Stage 0 fast-path). Mirrors
# SANCTIONED_DEGRADED_REASONS in merge-design-critic-traces.py:44 — adding a
# new path: append here AND document in agent-output-contract.md. The exemption
# at the per-trace check below skips the no-spawn-record error for traces with
# provenance='lead-synthesized' AND coverage_provider in this set.
SANCTIONED_COVERAGE_PROVIDERS = frozenset({
    '.runs/all-pages-fast-path-decision.json',
})

manifest = json.load(open('$_SCG_MANIFEST'))
declared = set(manifest.get('agents', {}).keys())
if not declared:
    # friction-skip: post-validation — exit follows authoritative decision (allow-list match, deny path, or successful validation)
    sys.exit(0)  # No agents declared in manifest

# Get current run_id to filter stale spawn records from prior runs
ctx_path = os.path.join('$PROJECT_DIR', '.runs', '$SKILL' + '-context.json')
current_run_id = ''
try:
    current_run_id = json.load(open(ctx_path)).get('run_id', '')
except: pass

# Collect spawned agent base names from hook-written spawn-log
# Only count entries matching the current run_id
spawned = set()
with open('$SPAWN_LOG') as f:
    for line in f:
        try:
            e = json.loads(line)
            if e.get('hook') in ('skill-agent-gate', 'recovery-script'):
                if not current_run_id or e.get('run_id') == current_run_id:
                    spawned.add(e['agent'])
        except: pass

# Check each trace file for provenance
errors = []
traces_dir = os.path.join('$PROJECT_DIR', '.runs', 'agent-traces')
for tf in sorted(glob.glob(os.path.join(traces_dir, '*.json'))):
    try:
        td = json.load(open(tf))
    except: continue
    agent_name = td.get('agent', '')
    if not agent_name: continue
    # Skip started-only init traces (no verdict yet)
    if td.get('status') == 'started' and 'verdict' not in td: continue
    # NOTE: recovery traces are NO LONGER skipped here (issue #960 fix).
    # Recovery is now an audit marker, not a spawn-check bypass: recovery
    # traces require a real skill-agent-gate spawn-log entry (per
    # write-recovery-trace.sh preconditions), so they SHOULD pass the
    # universal provenance check below. Semantic validity of a recovery
    # trace is owned by verify-report-gate.sh / validate-recovery.sh.
    # See also the lead-merge exemption in the base-equals-bn block below.
    # (Plain words only in this comment: an inner double quote inside this
    # double-quoted python3 -c string word-splits the code into multiple
    # argv entries, truncating the program at that point — the SyntaxError
    # was then swallowed by 2>/dev/null and the whole provenance check
    # silently never ran.)
    # Skip traces from prior runs (stale run_id)
    trace_run_id = td.get('run_id', '')
    if current_run_id and trace_run_id and trace_run_id != current_run_id: continue

    # Resolve base agent name (e.g., design-critic-landing -> design-critic)
    base = agent_name
    bn = os.path.basename(tf).replace('.json', '')
    for da in sorted(declared, key=len, reverse=True):
        if agent_name == da or bn.startswith(da + '-'):
            base = da
            break

    # Only check manifest-declared agents
    if base not in declared: continue

    # Lead-merge aggregate exemption (now explicit via provenance — R2 C3/C7 fix).
    # When a trace filename equals a declared base agent AND sibling <base>-*.json
    # files exist, this is an orchestrator-composed aggregate (verify STATE 3b
    # merges per-page design-critic-<page>.json into design-critic.json; same
    # shape for scaffold-pages/scaffold-images/implementer in other skills).
    # Aggregates have no direct spawn-log entry. Their validity comes from the
    # sibling spawns, not their own.
    #
    # Invariant (AOC v1.1): if provenance is declared, it MUST be one of
    # {lead-merge, lead-on-behalf} for this exemption. lead-merge is the
    # canonical aggregate composer; lead-on-behalf permits the case where
    # the lead transcribed an agent's reported aggregate result because the
    # agent's own write was blocked. Other lead-* values (lead-synthesized,
    # lead-fix) at the aggregate filename are inconsistent with the per-page
    # sibling pattern and are rejected.
    # If contributing_spawn_indexes is declared, its count must
    # equal the number of skill-agent-gate entries for this base in the
    # current run_id (prevents forged aggregates claiming non-existent spawns).
    # Legacy aggregates missing provenance/contributing_spawn_indexes are
    # accepted for backward compatibility until migration runs.
    if bn == base and glob.glob(os.path.join(traces_dir, base + '-*.json')):
        prov = td.get('provenance')
        if prov and prov not in ('lead-merge', 'lead-on-behalf'):
            errors.append(f'{bn}: aggregate trace has provenance={prov}, expected lead-merge or lead-on-behalf')
            continue
        csi = td.get('contributing_spawn_indexes')
        if isinstance(csi, list):
            # Count spawn-log entries for this base in current run_id
            expected = 0
            with open('$SPAWN_LOG') as _f:
                for _line in _f:
                    try:
                        _e = json.loads(_line)
                    except:
                        continue
                    if _e.get('agent') == base and (not current_run_id or _e.get('run_id') == current_run_id) and _e.get('hook') == 'skill-agent-gate':
                        expected += 1
            if len(csi) != expected:
                errors.append(f'{bn}: lead-merge claims {len(csi)} spawns but spawn-log has {expected} for {base} in current run')
                continue
        continue

    # Provenance check: base agent must appear in spawn-log
    if base not in spawned:
        # #1256 Stage 0 exemption: lead-synthesized aggregate from a sanctioned
        # all-pages-fast-path detector. Agent was never spawned by design — the
        # decision artifact (coverage_provider) is the proof of coverage.
        prov = td.get('provenance')
        cp = td.get('coverage_provider', '')
        if prov == 'lead-synthesized' and cp in SANCTIONED_COVERAGE_PROVIDERS:
            continue
        # AOC v1.2: lead-skipped sanctioned-skip exemption.
        # Fixer agents in recovery_forbidden cannot have a spawn-log entry
        # when the upstream gate blocked their spawn. The lead-skipped trace
        # IS the audit-only record of that decision; require
        # upstream_evidence_path (forging would require editing the upstream
        # merge file in the same PR — visible in diff). The companion F4
        # hook check (added in PR4) validates the upstream-merge marker.
        if prov == 'lead-skipped' and td.get('upstream_evidence_path') and base in {'security-fixer', 'quality-fixer'}:
            continue
        errors.append(f'{bn}: no spawn record for {base}')

if errors:
    print('|'.join(errors))
" 2>/dev/null || echo "")

  if [[ -n "$PROVENANCE_RESULT" ]]; then
    _log_verify_trace "$SKILL" "$STATE_ID" "fail-provenance" ""
    deny "State completion gate: $SKILL STATE $STATE_ID — trace provenance failed. Traces without Agent spawn records: ${PROVENANCE_RESULT//|/, }. You must spawn agents via the Agent tool."
  fi
fi

# AOC v1.2 (PR4) F4 — fixer-trace presence enforcement on state-4 + state-3d.
# When the merge file exists for a fixer state, the fixer trace MUST exist
# UNLESS one of two exemption markers is present in the merge file:
#   (a) source == "no-{security|quality}-agents" (scope-skip; no fixer needed)
#   (b) fixer_skipped:true AND a lead-skipped trace exists with
#       upstream_evidence_path referencing this merge file (audit-skip).
# Otherwise BLOCK with diagnostic.
#
# This closes the new audit-skip slice introduced by PR3 AND surfaces (but
# does not modify, out of scope) the pre-existing lib-hard-gate.sh:24
# silent-pass-on-missing-trace surface.
if [[ "$SKILL" == "verify" && ( "$STATE_ID" == "4" || "$STATE_ID" == "3d" ) ]]; then
  F4_RESULT=$(STATE_ID_ENV="$STATE_ID" PROJECT_DIR_ENV="$PROJECT_DIR" python3 -c "
import json, os, sys
state = os.environ['STATE_ID_ENV']
project_dir = os.environ['PROJECT_DIR_ENV']
merge_path = os.path.join(project_dir, '.runs', 'security-merge.json' if state == '4' else 'quality-merge.json')
fixer = 'security-fixer' if state == '4' else 'quality-fixer'
trace_path = os.path.join(project_dir, '.runs', 'agent-traces', fixer + '.json')

if not os.path.isfile(merge_path):
    # friction-skip: post-validation — exit follows authoritative decision (allow-list match, deny path, or successful validation)
    sys.exit(0)  # Merge file missing — upstream postcondition catches it

try:
    m = json.load(open(merge_path))
except Exception as e:
    print('cannot parse ' + merge_path + ': ' + str(e))
    sys.exit(1)

# (a) Scope-skip exemption: agents were not supposed to spawn this run.
expected_no_agents = 'no-security-agents' if state == '4' else 'no-quality-agents'
if m.get('source') == expected_no_agents:
    # friction-skip: post-validation — exit follows authoritative decision (allow-list match, deny path, or successful validation)
    sys.exit(0)

# (b) Audit-skip exemption: fixer_skipped + lead-skipped trace.
if m.get('fixer_skipped') is True:
    if not os.path.isfile(trace_path):
        print(fixer + ': merge has fixer_skipped:true but no audit trace at ' + trace_path)
        sys.exit(1)
    try:
        t = json.load(open(trace_path))
    except Exception as e:
        print(fixer + ': cannot parse trace: ' + str(e))
        sys.exit(1)
    if t.get('provenance') != 'lead-skipped':
        print(fixer + ': trace exists but provenance=' + repr(t.get('provenance')) + ', expected lead-skipped')
        sys.exit(1)
    expected_evidence = '.runs/' + ('security-merge.json' if state == '4' else 'quality-merge.json')
    if t.get('upstream_evidence_path') != expected_evidence:
        print(fixer + ': trace upstream_evidence_path=' + repr(t.get('upstream_evidence_path')) + ' does not reference ' + expected_evidence)
        sys.exit(1)
    # friction-skip: post-validation — exit follows authoritative decision (allow-list match, deny path, or successful validation)
    sys.exit(0)  # Audit-skip exemption satisfied

# Normal path: fixer trace MUST exist.
if not os.path.isfile(trace_path):
    print(fixer + ': trace missing and no skip-exemption marker in merge file')
    sys.exit(1)
" 2>&1 || true)
  if [[ -n "$F4_RESULT" ]]; then
    _log_verify_trace "$SKILL" "$STATE_ID" "fail-fixer-trace-presence" ""
    deny "State completion gate: $SKILL STATE $STATE_ID — fixer-trace presence (AOC v1.2 F4): $F4_RESULT"
  fi
fi

# Postconditions verified — allow
# Trace: log VERIFY pass
_log_verify_trace "$SKILL" "$STATE_ID" "pass"
# === Template remote + version check (only on STATE 0) ===
if [[ "$STATE_ID" == "0" ]]; then
    python3 -c "
import subprocess, sys, os
try:
    # Step 1: Ensure template remote exists
    check = subprocess.run(['git', 'remote', 'get-url', 'template'],
                           capture_output=True, text=True, timeout=2)
    if check.returncode != 0:
        # Find template repo via GitHub API
        current = subprocess.run(
            ['gh', 'repo', 'view', '--json', 'nameWithOwner', '-q', '.nameWithOwner'],
            capture_output=True, text=True, timeout=10
        ).stdout.strip()
        if current:
            info = subprocess.run(
                ['gh', 'api', f'repos/{current}',
                 '--jq', '.template_repository.full_name // .parent.full_name // empty'],
                capture_output=True, text=True, timeout=10
            ).stdout.strip()
            if info:
                subprocess.run(
                    ['git', 'remote', 'add', 'template', f'https://github.com/{info}.git'],
                    capture_output=True, timeout=5
                )

    # Step 2: Version check
    subprocess.run(['git', 'fetch', 'template', '--quiet'],
                   capture_output=True, timeout=10)
    local_hash = subprocess.run(['git', 'hash-object', 'CLAUDE.md'],
                                capture_output=True, text=True).stdout.strip()
    remote = subprocess.run(['git', 'show', 'template/main:CLAUDE.md'],
                            capture_output=True, text=True)
    if remote.returncode == 0 and remote.stdout:
        import hashlib
        blob_content = f'blob {len(remote.stdout)}\0{remote.stdout}'.encode()
        remote_hash = hashlib.sha1(blob_content).hexdigest()
        if local_hash != remote_hash:
            print('NOTE: Your template is behind upstream. '
                  'Run /upgrade to sync with the latest template.',
                  file=sys.stderr)
except Exception:
    pass
" 2>/dev/null || true
fi
# friction-skip: trivial-fast-path — input absent or non-applicable
exit 0
