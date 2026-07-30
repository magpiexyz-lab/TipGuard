#!/usr/bin/env bash
# reset-state.sh — escape-hatch primitive for resume-integrity violations.
# Usage: bash .claude/scripts/reset-state.sh <skill> <state_id>
#
# Removes <state_id> AND all states with later sort-order from <skill>-context.json's
# completed_states array. Also deletes any transient-intra-skill artifacts declared
# at the cleared states (their VERIFY commands re-create them on re-execution).
#
# Pure ledger-edit operation: no destructive side effects beyond the named context
# file and declared transient-intra-skill artifacts. Does NOT delete durable artifacts
# (the user may want to inspect them before re-running the state).
#
# Referenced by:
#   - .claude/scripts/lifecycle-next.sh (resume-integrity diagnostic suggests this command)
#   - .claude/patterns/provenance.md (documentation)
#
# Closes #1162 escape-hatch (Round-2-C7 caveat).

set -euo pipefail

SKILL="${1:-}"
STATE_ID="${2:-}"

if [[ -z "$SKILL" || -z "$STATE_ID" ]]; then
  echo "Usage: bash .claude/scripts/reset-state.sh <skill> <state_id>" >&2
  echo "Example: bash .claude/scripts/reset-state.sh bootstrap 5" >&2
  exit 1
fi

PROJECT_DIR="$(git rev-parse --show-toplevel 2>/dev/null || echo "${CLAUDE_PROJECT_DIR:-.}")"
CTX="$PROJECT_DIR/.runs/${SKILL}-context.json"
REGISTRY="$PROJECT_DIR/.claude/patterns/state-registry.json"

if [[ ! -f "$CTX" ]]; then
  echo "ERROR: $CTX not found. Nothing to reset." >&2
  exit 1
fi

if [[ ! -f "$REGISTRY" ]]; then
  echo "ERROR: $REGISTRY not found." >&2
  exit 1
fi

SKILL_ENV="$SKILL" STATE_ID_ENV="$STATE_ID" CTX_ENV="$CTX" REGISTRY_ENV="$REGISTRY" \
  python3 - <<'PYEOF'
import json, os, sys

skill = os.environ["SKILL_ENV"]
state_id = os.environ["STATE_ID_ENV"]
ctx_path = os.environ["CTX_ENV"]
registry_path = os.environ["REGISTRY_ENV"]

ctx = json.load(open(ctx_path))
registry = json.load(open(registry_path))
states_reg = registry.get(skill, {})

# Determine state ordering from registry insertion order (canonical canonical
# manifest source). Fall back to sorted keys if necessary.
ordered = [s for s in states_reg.keys() if not s.startswith("_")]
if state_id not in ordered:
    sys.stderr.write("ERROR: state %s not found in registry for skill %s\n" % (state_id, skill))
    sys.stderr.write("Known states: %s\n" % ordered)
    sys.exit(1)

target_idx = ordered.index(state_id)

# Filter completed_states: keep only those that come BEFORE target_idx
old_completed = [str(s) for s in ctx.get("completed_states", [])]
keep = []
cleared = []
for s in old_completed:
    if s in ordered and ordered.index(s) < target_idx:
        keep.append(s)
    else:
        cleared.append(s)

ctx["completed_states"] = keep
json.dump(ctx, open(ctx_path, "w"), indent=2)

# Delete transient-intra-skill artifacts associated with cleared states (only).
# Durable artifacts are PRESERVED so the user can inspect them.
removed = []
project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.dirname(os.path.dirname(ctx_path)))
for s in ordered[target_idx:]:
    entry = states_reg.get(s)
    if not isinstance(entry, dict):
        continue
    if entry.get("lifecycle") != "transient-intra-skill":
        continue
    artifact = entry.get("artifact")
    if not artifact:
        continue
    artifact_abs = artifact if os.path.isabs(artifact) else os.path.join(project_dir, artifact)
    if os.path.isfile(artifact_abs):
        os.remove(artifact_abs)
        removed.append(artifact)

print("Reset %s to before state %s." % (skill, state_id))
print("  Cleared from completed_states: %s" % cleared)
print("  Remaining: %s" % keep)
if removed:
    print("  Deleted intra-skill artifacts: %s" % removed)
print("\nNext call to lifecycle-next.sh will dispatch state %s." % state_id)
PYEOF
