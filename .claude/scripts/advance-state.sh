#!/usr/bin/env bash
# advance-state.sh — Advances a skill's state machine by adding a state to completed_states.
# Usage: bash .claude/scripts/advance-state.sh <skill> <state_number>
# Examples:
#   bash .claude/scripts/advance-state.sh verify 1
#   bash .claude/scripts/advance-state.sh bootstrap 3a
# Guarded by state-completion-gate.sh hook which validates postconditions before allowing execution.
set -euo pipefail
SKILL="$1"
STATE_NUM="$2"
PROJECT_DIR="$(git rev-parse --show-toplevel 2>/dev/null || echo "${CLAUDE_PROJECT_DIR:-.}")"

# Determine context file — mode-aware for iterate --check/--cross
source "$(dirname "$0")/lifecycle-lib.sh"
read -r SKILL_DIR _SKILL_MODE <<< "$(resolve_skill_dir "$SKILL")"
MANIFEST=$(resolve_framework_manifest "$SKILL_DIR")
CTX=$(resolve_context_path "$SKILL")

# Fail-closed: verify STATE_NUM exists in registry
REGISTRY="$PROJECT_DIR/.claude/patterns/state-registry.json"
if [[ -f "$REGISTRY" ]]; then
  STATE_EXISTS=$(python3 -c "
import json
reg = json.load(open('$REGISTRY'))
print('yes' if '$STATE_NUM' in reg.get('$SKILL', {}) else 'no')
" 2>/dev/null || echo "error")
  if [[ "$STATE_EXISTS" == "no" ]]; then
    echo "ERROR: advance-state.sh — $SKILL.$STATE_NUM not in state-registry.json" >&2
    exit 1
  fi
fi

python3 -c "
import json, os, sys, subprocess
f='$CTX'; d=json.load(open(f))
state=str('$STATE_NUM')

# Verify BEFORE append (#1339 round-2 C4) — atomic verify-then-append in
# this single python3 invocation eliminates the revert-race that an
# append-then-verify-then-revert design would have. When the
# state-completion-gate hook deferred its synchronous VERIFY (because a
# sibling write-gate-artifact.sh appears in the chain), this is the
# actual gate: the chain has now executed, so the artifact exists and
# VERIFY can run authoritatively.
reg_path = '$REGISTRY'
if os.path.exists(reg_path):
    try:
        reg = json.load(open(reg_path))
    except Exception as e:
        sys.stderr.write('advance-state: cannot parse registry: ' + str(e) + chr(10))
        sys.exit(1)
    entry = reg.get('$SKILL', {}).get(state, '')
    if isinstance(entry, dict):
        verify_cmd = entry.get('verify', '')
    else:
        verify_cmd = str(entry)
    if verify_cmd and verify_cmd != 'true':
        r = subprocess.run(verify_cmd, shell=True, capture_output=True)
        if r.returncode != 0:
            sys.stderr.write('advance-state: verify failed for $SKILL.' + state + ': ' + verify_cmd + chr(10))
            if r.stderr:
                sys.stderr.write(r.stderr.decode(errors='replace') + chr(10))
            sys.exit(1)

cs=d.get('completed_states',[])
if state not in cs: cs.append(state)
d['completed_states']=cs

# Read required states from manifest (already parsed by lifecycle-init.sh)
manifest_path = '$MANIFEST'
if os.path.exists(manifest_path):
    manifest = json.load(open(manifest_path))
    if 'active_mode' in manifest and 'modes' in manifest:
        req = [str(s) for s in manifest['modes'][manifest['active_mode']].get('states', [])]
    else:
        req = [str(s) for s in manifest.get('states', [])]
    if req:
        cs_set = set(str(s) for s in cs)
        skip = set(str(s) for s in d.get('skip_states', []))
        if set(req).issubset(cs_set | skip):
            d['completed'] = True

json.dump(d, open(f, 'w'))
"
