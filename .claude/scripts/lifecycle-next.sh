#!/usr/bin/env bash
# lifecycle-next.sh — Phase 2: Dispatch to next state file.
# Usage: bash .claude/scripts/lifecycle-next.sh <skill>
# Output (stdout, one line):
#   /path/to/state-file.md            — next state to execute
#   FINALIZE                           — all states complete
#   EMBED_COMPLETE:<skill>:<state_id>  — embedded skill finished, parent should advance
#   NO_MANIFEST                        — no manifest file found
#   NO_CONTEXT                         — no context file found
set -euo pipefail

SKILL="${1:-}"

if [[ -z "$SKILL" ]]; then
  echo "ERROR: lifecycle-next.sh — skill name required" >&2
  exit 1
fi

PROJECT_DIR="$(git rev-parse --show-toplevel 2>/dev/null || echo "${CLAUDE_PROJECT_DIR:-.}")"

source "$(dirname "$0")/lifecycle-lib.sh"
MANIFEST=$(resolve_framework_manifest "$SKILL")

# --- Check prerequisites ---
if [[ ! -f "$MANIFEST" ]]; then
  echo "NO_MANIFEST"
  exit 0
fi

# Determine context file — mode-aware for iterate --check/--cross
CTX=$(resolve_context_path "$SKILL" "$MANIFEST")

# Missing context = no states completed yet (first dispatch before state-0 creates it)
# --- Dispatch logic (Python for JSON + glob) ---
RESULT=$(PROJECT_DIR_ENV="$PROJECT_DIR" python3 - "$SKILL" "$CTX" "$MANIFEST" << 'PYEOF'
import json, sys, os, glob

skill = sys.argv[1]
ctx_path = sys.argv[2]
manifest_path = sys.argv[3]
project_dir = os.environ.get("PROJECT_DIR_ENV", ".")

ctx = json.load(open(ctx_path)) if os.path.isfile(ctx_path) else {"completed_states": []}
manifest = json.load(open(manifest_path))

# completed_states as string set for consistent comparison
completed = set(str(s) for s in ctx.get("completed_states", []))

# --- Resume-integrity check (closes #1162 part 2) ---
# When a state appears in completed_states, optionally check that any durable
# artifact it declared is still present. Missing durable artifact → BLOCK with
# diagnostic. Fresh bootstrap unaffected (completed == set()).
# transient-cross-skill / transient-intra-skill are skipped (artifacts may
# legitimately be missing per their declared lifecycle).
if completed:
    registry_path = os.path.join(project_dir, ".claude", "patterns", "state-registry.json")
    try:
        registry = json.load(open(registry_path))
    except Exception:
        registry = {}
    resume_override = os.environ.get("RESUME_INTEGRITY_OVERRIDE", "0") == "1"
    skill_states_reg = registry.get(skill, {})
    integrity_failures = []
    for sid in completed:
        entry = skill_states_reg.get(sid)
        if not isinstance(entry, dict):
            continue
        lifecycle = entry.get("lifecycle", "durable")
        if lifecycle != "durable":
            continue
        artifact = entry.get("artifact")
        if not artifact:
            continue
        # Resolve relative to project_dir
        artifact_abs = artifact if os.path.isabs(artifact) else os.path.join(project_dir, artifact)
        if not os.path.isfile(artifact_abs):
            integrity_failures.append((sid, artifact))
    if integrity_failures:
        for sid, art in integrity_failures:
            msg = (
                "Resume integrity violation: skill=%s state=%s artifact=%s missing.\n"
                "  This state is in completed_states but its declared durable artifact has been deleted.\n"
                "  Possible causes: manual cleanup, IDE/trash collector, cross-machine resume after worktree deletion.\n"
                "  To recover, choose one:\n"
                "    (a) Restore the artifact from version control.\n"
                "    (b) Reset the state and re-execute it:\n"
                "          bash .claude/scripts/reset-state.sh %s %s\n"
                "    (c) Override the check for this run (downgrades to WARN):\n"
                "          RESUME_INTEGRITY_OVERRIDE=1 <next-command>" % (skill, sid, art, skill, sid)
            )
            if resume_override:
                sys.stderr.write("WARN: " + msg + "\n")
            else:
                sys.stderr.write("ERROR: " + msg + "\n")
        if not resume_override:
            sys.exit(2)

# Determine active states list
if "active_mode" in manifest and "modes" in manifest:
    mode = manifest["active_mode"]
    states = manifest["modes"][mode]["states"]
else:
    states = manifest.get("states", [])

if not states:
    print("NO_STATES")
    sys.exit(0)

loop_set = set(str(s) for s in manifest.get("loop", []))

# Build embed lookup: state_id -> {skill, scope}
embeds = manifest.get("embed", [])
embed_map = {}
if isinstance(embeds, list):
    for e in embeds:
        at = str(e.get("at", ""))
        if at:
            embed_map[at] = e


def find_state_file(sk, state_id):
    """Find state file in .claude/skills/<skill>/; fall back to .claude/patterns/
    for shared terminal states (e.g. "99" → state-99-epilogue.md)."""
    pattern = os.path.join(project_dir, ".claude", "skills", sk,
                          "state-%s-*.md" % state_id)
    matches = sorted(glob.glob(pattern))
    if not matches:
        patterns_pattern = os.path.join(project_dir, ".claude", "patterns",
                                        "state-%s-*.md" % state_id)
        matches = sorted(glob.glob(patterns_pattern))
    return matches[0] if matches else None


# --- Loop handling ---
# If all loop states are completed, check loop-decision artifact.
# If continue: true → return first loop state, delete decision file.
# If continue: false or missing → skip loop states.
loop_continue = False
if loop_set and loop_set.issubset(completed):
    decision_file = os.path.join(project_dir, ".runs",
                                 "%s-loop-decision.json" % skill)
    if os.path.isfile(decision_file):
        try:
            decision = json.load(open(decision_file))
            if decision.get("continue") is True:
                loop_continue = True
                os.remove(decision_file)
        except (json.JSONDecodeError, OSError):
            pass

# If loop continues, remove loop states from completed so they're re-dispatched
if loop_continue:
    completed = completed - loop_set

# --- Skip handling ---
# If context specifies states to skip, treat them as completed
skip_states = set(str(s) for s in ctx.get("skip_states", []))
completed = completed | skip_states

# Defense-in-depth: if a mid-run state writes skip_states wholesale (e.g. some
# resolve states re-derive the list), embed_skip_epilogue=True still forces
# state "99" to be treated as completed. Only skips for truly-embedded runs.
if ctx.get("embed_skip_epilogue") is True:
    completed = completed | {"99"}

# --- Find next state ---
for state_id in states:
    sid = str(state_id)
    if sid not in completed:
        # Check if this state has an embed annotation
        if sid in embed_map:
            e = embed_map[sid]
            print("EMBED:%s:%s:%s" % (e["skill"], sid, e.get("scope", "full")))
            sys.exit(0)
        path = find_state_file(skill, sid)
        if path:
            print(path)
        else:
            print("STATE_FILE_NOT_FOUND:%s:%s" % (skill, sid), file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

# All states completed
print("FINALIZE")
PYEOF
)

# --- Embed dispatch layer ---
# When Python signals an embed state, transparently delegate to the embedded skill.
# The agent's mechanized loop continues unbroken — it keeps calling lifecycle-next.sh
# for the parent skill and gets embedded skill state files back.
if [[ "$RESULT" == EMBED:* ]]; then
  IFS=':' read -r _ EMBED_SKILL EMBED_AT EMBED_SCOPE <<< "$RESULT"
  EMBED_CTX="$PROJECT_DIR/.runs/${EMBED_SKILL}-context.json"

  # First dispatch for this embed: initialize the embedded skill
  if [[ ! -f "$EMBED_CTX" ]]; then
    # Clean stale output from prior embedded runs (but preserve parent artifacts)
    rm -f "$PROJECT_DIR/.runs/${EMBED_SKILL}-report.md"
    rm -f "$PROJECT_DIR/.runs/fix-log.md"
    # Initialize embedded skill (--embed skips cleanup/validation/branch)
    bash "$(dirname "$0")/lifecycle-init.sh" "$EMBED_SKILL" --embed
  fi

  # Delegate: get next state from the embedded skill
  EMBED_NEXT=$(bash "$0" "$EMBED_SKILL")

  if [[ "$EMBED_NEXT" == "FINALIZE" ]]; then
    # Mark embedded skill's context as completed BEFORE signaling parent.
    # This lets resolve_active_identity() correctly skip the finished embedded
    # context on subsequent hook invocations and pick the parent as active.
    if [[ -f "$EMBED_CTX" ]]; then
      python3 -c "
import json
d = json.load(open('$EMBED_CTX'))
d['completed'] = True
json.dump(d, open('$EMBED_CTX', 'w'))
" 2>/dev/null || true
    fi
    # Embedded skill complete — signal parent to advance this state
    echo "EMBED_COMPLETE:${SKILL}:${EMBED_AT}"
  else
    # Return embedded skill's state file to the agent
    echo "$EMBED_NEXT"
  fi
else
  echo "$RESULT"
fi
