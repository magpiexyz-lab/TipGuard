#!/usr/bin/env bash
# lifecycle-init.sh — Phase 1: Initialize skill execution from skill.yaml manifest.
# Usage: bash .claude/scripts/lifecycle-init.sh <skill> [--embed] [extra_json]
# Examples:
#   bash .claude/scripts/lifecycle-init.sh solve
#   bash .claude/scripts/lifecycle-init.sh change '{"preliminary_type":null}'
#   bash .claude/scripts/lifecycle-init.sh iterate '{"mode":"check"}'
#   bash .claude/scripts/lifecycle-init.sh verify --embed
#
# Steps:
#   1. Parse .claude/skills/<skill>/skill.yaml → .runs/<skill>-lifecycle.json
#   2. If modes present + extra has mode field → select that mode's states
#   3. If branch field present + not in worktree → create branch
#   4. Create canonical context via init-context.sh <skill>
#
# Fallback: if skill.yaml not found → warn, call init-context.sh only (v1 compat)
set -euo pipefail

# Issue #1328 round-2 C4: stale-sentinel cleanup. Remove any leftover
# .runs/last-branch-checkout.tsv from a prior crashed run BEFORE any git
# checkout -b operations — otherwise the next propagation reads a stale
# timestamp and mis-computes gap_seconds. Idempotent.
rm -f .runs/last-branch-checkout.tsv 2>/dev/null || true

SKILL="${1:-}"

# --- Embed mode: skip cleanup/validation/branch when called by lifecycle-next.sh embed dispatch ---
EMBED_MODE=""
if [[ "${2:-}" == "--embed" ]]; then
  EMBED_MODE=1
  EXTRA="${3:-}"
else
  EXTRA="${2:-}"
fi

if [[ -z "$SKILL" ]]; then
  echo "ERROR: lifecycle-init.sh — skill name required" >&2
  echo "Usage: bash .claude/scripts/lifecycle-init.sh <skill> [extra_json]" >&2
  exit 1
fi

PROJECT_DIR="$(git rev-parse --show-toplevel 2>/dev/null || echo "${CLAUDE_PROJECT_DIR:-.}")"
SKILL_YAML="$PROJECT_DIR/.claude/skills/$SKILL/skill.yaml"
MANIFEST="$PROJECT_DIR/.runs/$SKILL-lifecycle.json"

# --- Step 0.5: Orphan transient-service cleanup from prior uncleaned run ---
# Catches Supabase stacks left running by a skill that crashed, was Ctrl-C'd,
# or had finalize itself die before Step 7. Also runs a defensive reclaim when
# a stack is running with no ownership marker (Claude-bypassed-wrapper path).
# Skipped in embed mode because the parent's init already handled it.
# Non-blocking: init must never fail on cleanup.
if [[ -z "${EMBED_MODE:-}" ]] && [[ -x "$PROJECT_DIR/.claude/scripts/stop-transient-services.sh" ]]; then
  bash "$PROJECT_DIR/.claude/scripts/stop-transient-services.sh" --orphan-cleanup 2>&1 | sed 's/^/[init-cleanup] /' || true
fi

# --- Step 1: Check for skill.yaml ---
if [[ ! -f "$SKILL_YAML" ]]; then
  echo "WARN: lifecycle-init.sh — $SKILL_YAML not found, falling back to v1 (init-context.sh only)" >&2
  bash "$PROJECT_DIR/.claude/scripts/init-context.sh" "$SKILL" "$EXTRA"
  exit 0
fi

# --- Step 1.5: Legacy trace migration (idempotent, runs in BOTH primary and
# --embed paths so embedded verify runs don't carry forward unmigrated traces
# from the parent skill — R2 C4 fix). The script writes
# .runs/trace-migration.json as a receipt and becomes a no-op on subsequent
# invocations.
python3 "$PROJECT_DIR/.claude/scripts/migrate-legacy-traces.py" >&2 || true

# --- Step 2: Parse YAML → lifecycle.json ---
mkdir -p "$PROJECT_DIR/.runs"

EXTRA_ENV="$EXTRA" python3 - "$SKILL_YAML" "$MANIFEST" << 'PYEOF'
import sys, json, os, re

yaml_path = sys.argv[1]
manifest_path = sys.argv[2]
extra_str = os.environ.get("EXTRA_ENV", "")

# --- Regex YAML fallback (defined before use) ---

def _parse_inline(value):
    """Parse an inline YAML value."""
    if value.startswith('[') and value.endswith(']'):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            # Bare-word flow sequence: [foo, bar] -> ["foo", "bar"]
            inner = value[1:-1].strip()
            if not inner:
                return []
            return [item.strip().strip('"').strip("'") for item in inner.split(',')]
    if (value.startswith('"') and value.endswith('"')) or \
       (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    if value.lower() == 'true':
        return True
    if value.lower() == 'false':
        return False
    try:
        return int(value)
    except ValueError:
        pass
    return value

def _collect_block(lines, start, parent_indent):
    """Collect lines that are indented more than parent_indent."""
    block = []
    i = start
    while i < len(lines):
        line = lines[i]
        stripped = line.rstrip()
        if not stripped or stripped.lstrip().startswith('#'):
            block.append(line)
            i += 1
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= parent_indent:
            break
        block.append(line)
        i += 1
    return block, i

def _parse_block_sequence(block_lines):
    """Parse a YAML block sequence (list of items)."""
    items = []
    current_item = {}
    for line in block_lines:
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        if s.startswith('- '):
            if current_item:
                items.append(current_item)
            current_item = {}
            rest = s[2:].strip()
            m = re.match(r'([\w-]+):\s*(.*)', rest)
            if m:
                current_item[m.group(1)] = _parse_inline(m.group(2).strip())
        else:
            m = re.match(r'\s*([\w-]+):\s*(.*)', s)
            if m:
                current_item[m.group(1)] = _parse_inline(m.group(2).strip())
    if current_item:
        items.append(current_item)
    return items

def _parse_block_map(block_lines):
    """Parse a YAML block map (dict of key: value or nested maps)."""
    result = {}
    i = 0
    while i < len(block_lines):
        line = block_lines[i]
        stripped = line.rstrip()
        if not stripped or stripped.lstrip().startswith('#'):
            i += 1
            continue
        indent = len(line) - len(line.lstrip())
        m = re.match(r'\s*([\w-]+):\s*(.*)', stripped)
        if m:
            k, v = m.group(1), m.group(2).strip()
            if v:
                result[k] = _parse_inline(v)
                i += 1
            else:
                sub_block, i = _collect_block(block_lines, i + 1, indent)
                result[k] = _parse_block(k, sub_block)
        else:
            i += 1
    return result

def _parse_block(key, block_lines):
    """Parse a block of indented YAML lines."""
    first_content = None
    for line in block_lines:
        s = line.strip()
        if s and not s.startswith('#'):
            first_content = s
            break
    if first_content and first_content.startswith('- '):
        return _parse_block_sequence(block_lines)
    return _parse_block_map(block_lines)

def _regex_parse_yaml(text):
    """Parse the constrained YAML subset used in skill.yaml files."""
    result = {}
    lines = text.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.rstrip()
        if not stripped or stripped.lstrip().startswith('#'):
            i += 1
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            m = re.match(r'^([\w-]+):\s*(.*)', stripped)
            if m:
                key, value = m.group(1), m.group(2).strip()
                if value:
                    result[key] = _parse_inline(value)
                    i += 1
                else:
                    block, i = _collect_block(lines, i + 1, 0)
                    result[key] = _parse_block(key, block)
            else:
                i += 1
        else:
            i += 1
    return result

# --- YAML parsing: try PyYAML, fallback to regex ---
try:
    import yaml
    with open(yaml_path) as f:
        data = yaml.safe_load(f)
except ImportError:
    with open(yaml_path) as f:
        text = f.read()
    data = _regex_parse_yaml(text)

# --- Step 3: Mode selection ---
if "modes" in data and extra_str:
    try:
        extra_data = json.loads(extra_str)
        mode = extra_data.get("mode")
        if mode and mode in data["modes"]:
            data["active_mode"] = mode
    except (json.JSONDecodeError, TypeError):
        pass

# Default to "default" mode when modes present but no mode specified
if "modes" in data and "active_mode" not in data and "default" in data["modes"]:
    data["active_mode"] = "default"

# --- Step 3.5: Promote allowlisted mode-level keys to manifest root ---
# Some flags (e.g., skip_experiment_validation) vary by mode. Lift them onto
# the manifest root so single-read consumers (Step 3b validation gate et al.)
# stay mode-agnostic. The allowlist is explicit — generic promotion would
# clobber `states`/`trigger`, which have different semantics under
# `modes[<mode>]`. Mode-level explicit value (even false) overrides top-level.
PROMOTABLE_MODE_KEYS = {"skip_experiment_validation"}
if "modes" in data and "active_mode" in data:
    mode_cfg = data["modes"].get(data["active_mode"]) or {}
    if isinstance(mode_cfg, dict):
        for k in PROMOTABLE_MODE_KEYS:
            if k in mode_cfg:
                data[k] = mode_cfg[k]

# --- Write manifest ---
with open(manifest_path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PYEOF

# --- Steps 3a-4 skipped in embed mode (parent skill already ran them) ---
if [[ -z "$EMBED_MODE" ]]; then

# --- Embed-mode policy (Slice 5b documentation) ---
# When this skill runs as an EMBED (parent skill called us via lifecycle-next.sh
# embed dispatch), $EMBED_MODE is set and the cleanup steps below are SKIPPED
# (parent already ran them). Skill-owned artifacts (declared in
# state-registry.json["skill_owned_artifacts"]) belonging to the PARENT skill
# are therefore preserved automatically — the embed never enters this branch.
# When the embedded skill runs standalone, its own skill_owned_artifacts are
# preserved by the per-SKILL match in Edit 2 above.

# --- Step 3a-delivery: Delivery artifact cleanup (skipped in embed mode) ---
# These files gate delivery in lifecycle-finalize.sh Step 5. A stale copy from a
# prior code-writing skill MUST NOT survive into a subsequent run (analysis-only
# or code-writing) where finalize could interpret it as a ship signal. See
# observation #1004. In EMBED_MODE the parent skill has already written its
# delivery artifacts (e.g., bootstrap state-18 writes commit-message.txt before
# spawning embedded /verify); deleting them here would force the embed's own
# state to rewrite or the parent's finalize-rerun would fail (observation #1430).
DELIVERY_ARTIFACTS=(
  "$PROJECT_DIR/.runs/commit-message.txt"
  "$PROJECT_DIR/.runs/pr-body.md"
  "$PROJECT_DIR/.runs/pr-title.txt"
  "$PROJECT_DIR/.runs/delivery-skip.flag"
)
for f in "${DELIVERY_ARTIFACTS[@]}"; do
  rm -f "$f"
done

# --- Step 3a: Clean stale artifacts from prior runs ---
# NOTE: .runs/lead-deviation-log.jsonl is intentionally preserved across runs
# (scope=cross-run-by-design per .claude/patterns/prose-gates.json). It feeds
# the 6th retrospective enumerator channel
# (.claude/scripts/enumerate-pending-retrospective-findings.py:_candidates_from_lead_deviations).
# DO NOT add .runs/lead-deviation-log.jsonl to STALE_ARTIFACTS — adding here
# would silently break Phase B soak data collection and Phase C deny-mode
# signal attribution. Same preservation convention as hook-friction.jsonl,
# fix-ledger.jsonl, agent-spawn-log.jsonl (preserved by absence from this list).
STALE_ARTIFACTS=(
  "$PROJECT_DIR/.runs/observe-result.json"
  "$PROJECT_DIR/.runs/epilogue-context.json"
  "$PROJECT_DIR/.runs/observer-diffs.txt"
  "$PROJECT_DIR/.runs/observe-evidence-check.json"
  "$PROJECT_DIR/.runs/compliance-audit-result.json"
  "$PROJECT_DIR/.runs/q-dimensions.json"
  "$PROJECT_DIR/.runs/verify-report.md"
  "$PROJECT_DIR/.runs/fix-log.md"
  "$PROJECT_DIR/.runs/quality-merge.json"
  "$PROJECT_DIR/.runs/security-merge.json"
  "$PROJECT_DIR/.runs/design-ux-merge.json"
  "$PROJECT_DIR/.runs/review-complete.json"
  "$PROJECT_DIR/.runs/review-loop-decision.json"
  # #1152: prevent stale prior-run files from satisfying lead-only schema checks
  "$PROJECT_DIR/.runs/retrospective-result.json"
  "$PROJECT_DIR/.runs/observation-evidence.json"
  # #1198: backstop for state-99 identity assertion — UNION sweep in Slice 5b
  # will preserve this; for the hotfix window, ensure prior-skill artifact is gone.
  "$PROJECT_DIR/.runs/observation-enforcement.json"
  # #1331: solve-critic round-1 archive sidecar (outside .runs/agent-traces/,
  # so the directory wipe does not catch it). Without this entry, a stale
  # archive from a prior /resolve|/change|/solve run silently satisfies
  # verify-*.py runtime postconditions on the next run.
  "$PROJECT_DIR/.runs/solve-critic-round1.json"
  # #1331: /solve challenge artifact (closes contract from solve-reasoning.md
  # Phase 5). Cross-skill transient — lifecycle is bound to the active
  # /solve run; cleared at the start of each new skill run so stale prior-run
  # data does not leak into the next solve.1 VERIFY.
  "$PROJECT_DIR/.runs/solve-challenge.json"
  # Auth preflight verdict from /iterate --cross state-x0/x5 Step 0. A stale
  # all_required_ok:true from a prior run must never satisfy a new run's
  # VERIFY (registry entries are string-form, so no lifecycle declaration).
  "$PROJECT_DIR/.runs/iterate-cross-auth-preflight.json"
)

# --- Slice 5b: UNION with registry-derived transient-cross-skill artifacts ---
# Source of truth for cross-skill transient lifecycle is state-registry.json
# `lifecycle: transient-cross-skill` declarations + the new top-level
# `epilogue_artifacts` and `transient_artifacts` sections. Manual list above
# remains as legacy backstop (Plan-agent Q1: 9 skills have zero lifecycle
# declarations; replacing the manual list outright would lose their cleanups).
REGISTRY_TRANSIENTS=$(PROJECT_DIR_ENV="$PROJECT_DIR" python3 <<'PYEOF' 2>/dev/null || true
import json, os, sys
try:
    r = json.load(open(os.environ['PROJECT_DIR_ENV'] + '/.claude/patterns/state-registry.json'))
except Exception:
    sys.exit(0)
paths = set()

# Walk per-state lifecycle declarations.
# Canonical schema (per state-registry.json today): each state entry uses
# the SINGULAR `artifact: <string>` field. The original Slice 5b walker read
# `node.get('artifacts', [])` (plural list), which silently matched zero
# entries — every per-state transient-cross-skill declaration was dropped.
# Fixed: read singular `artifact` first; keep plural `artifacts` as a
# forward-compat fallback for entries that may use the array form.
def _walk(node):
    if isinstance(node, dict):
        if node.get('lifecycle') == 'transient-cross-skill':
            single = node.get('artifact')
            if isinstance(single, str) and single:
                paths.add(single)
            multi = node.get('artifacts')
            if isinstance(multi, list):
                for p in multi:
                    if isinstance(p, str) and p:
                        paths.add(p)
        for v in node.values():
            _walk(v)
    elif isinstance(node, list):
        for v in node:
            _walk(v)

_walk(r)

# Top-level epilogue_artifacts (Slice 1)
for path, meta in (r.get('epilogue_artifacts') or {}).items():
    if isinstance(meta, dict) and meta.get('lifecycle') == 'transient-cross-skill':
        paths.add(path)

for p in sorted(paths):
    print(p)
PYEOF
)

# Some `artifact` values are PREFIXES (e.g. ".runs/agent-traces/" or
# ".runs/agent-traces/design-critic-") rather than full filenames. The
# directory wipes at lines 339-340 (`rm -rf .runs/agent-traces/` and
# `.runs/gate-verdicts/`) already cover those. For full-filename entries,
# `rm -f` handles them. For filename prefixes (e.g. "design-critic-"), use
# glob expansion via `compgen -G` so we sweep matching files explicitly —
# defensive against future schema where the directory wipe may be removed.
while IFS= read -r p; do
  [ -z "$p" ] && continue
  if [[ "$p" == */ ]]; then
    # Directory prefix — covered by directory wipes below; rm -rf for safety.
    rm -rf "$PROJECT_DIR/$p"
  elif [[ "$p" == *- || "$p" == *_ ]]; then
    # Filename prefix — glob-expand via compgen (no failure if nothing matches).
    while IFS= read -r match; do
      [ -n "$match" ] && rm -f "$match"
    done < <(compgen -G "$PROJECT_DIR/${p}*" 2>/dev/null || true)
  else
    STALE_ARTIFACTS+=( "$PROJECT_DIR/$p" )
  fi
done <<< "$REGISTRY_TRANSIENTS"

for f in "${STALE_ARTIFACTS[@]}"; do
  rm -f "$f"
done
# --- Slice 5b: declarative skill_owned_artifacts carve-out ---
# Replaces the hardcoded verify-context.json/verify-lifecycle.json carve-out
# (#1074 + #877 regression). state-registry.json["skill_owned_artifacts"][SKILL]
# enumerates artifacts owned by a skill — they MUST NOT be deleted when that
# skill is the active SKILL. For all other skills, they ARE deleted (stale
# from a prior embedded run).
SKILL_OWNED_ALL=$(python3 -c "
import json
try:
    r = json.load(open('$PROJECT_DIR/.claude/patterns/state-registry.json'))
except Exception:
    exit()
owned = r.get('skill_owned_artifacts', {}) or {}
# Print 'SKILL\tPATH' tab-separated for all skills
for s, paths in owned.items():
    for p in (paths or []):
        print(f'{s}\t{p}')
" 2>/dev/null || true)

while IFS=$'\t' read -r owner_skill path; do
  [ -z "$owner_skill" ] || [ -z "$path" ] && continue
  if [ "$owner_skill" != "$SKILL" ]; then
    rm -f "$PROJECT_DIR/$path"
  fi
done <<< "$SKILL_OWNED_ALL"
rm -rf "$PROJECT_DIR/.runs/gate-verdicts/"
rm -rf "$PROJECT_DIR/.runs/agent-traces/"

# --- Step 3b: Validate experiment.yaml (if exists) ---
EXPERIMENT_YAML="$PROJECT_DIR/experiment/experiment.yaml"
VALIDATE_SCRIPT="$PROJECT_DIR/scripts/validate-experiment.py"

SKIP_VALIDATE=""
if [[ -f "$MANIFEST" ]]; then
  SKIP_VALIDATE=$(python3 -c "import json; print(json.load(open('$MANIFEST')).get('skip_experiment_validation',''))" 2>/dev/null || echo "")
fi

if [[ -z "$SKIP_VALIDATE" && -f "$EXPERIMENT_YAML" && -f "$VALIDATE_SCRIPT" ]]; then
  VALIDATE_EXIT=0
  python3 "$VALIDATE_SCRIPT" || VALIDATE_EXIT=$?
  if [[ $VALIDATE_EXIT -eq 1 ]]; then
    echo "ERROR: experiment.yaml validation failed" >&2
    exit 1
  fi
  # exit code 0 = pass, exit code 2 = warnings only, continue
fi

fi # end embed guard for Steps 3a-3b

# --- Step 4: Branch creation (skipped in embed mode) ---
BRANCH=$(python3 -c "import json; print(json.load(open('$MANIFEST')).get('branch',''))" 2>/dev/null || echo "")

if [[ -z "$EMBED_MODE" && -n "$BRANCH" && "$(bash "$PROJECT_DIR/.claude/scripts/lib/in-worktree.sh")" == "false" ]]; then
  # Extract slug from EXTRA if present
  SLUG=""
  if [[ -n "$EXTRA" ]]; then
    SLUG=$(python3 -c "
import json
try:
    d = json.loads('''$EXTRA''')
    print(d.get('slug',''))
except: print('')
" 2>/dev/null || echo "")
  fi
  if [[ -n "$SLUG" ]]; then
    BRANCH="${BRANCH//\{slug\}/$SLUG}"
  else
    # Remove {slug} placeholder and any trailing hyphen
    BRANCH="${BRANCH//\{slug\}/}"
    BRANCH="${BRANCH%-}"
  fi
  # Bundled checkout + propagation (issue #1328): stamp sentinel, capture
  # OLD_BRANCH, run `git checkout -b`, propagate to active context — all
  # in one Bash invocation so resolve_active_identity cannot see a stale
  # context.branch field. branch-checkout-propagation-gate.sh enforces
  # this pairing structurally; bundling here matches the contract.
  echo "$(date +%s)" > .runs/last-branch-checkout.tsv && \
    OLD_BRANCH_LI="$(git branch --show-current)" && \
    git checkout -b "$BRANCH" && \
    bash .claude/scripts/update-context-branch.sh "$OLD_BRANCH_LI" \
    || echo "WARN: lifecycle-init.sh — bundled checkout+propagate failed for $BRANCH (branch may already exist or checkout failed)" >&2
fi

# --- Step 5: Create canonical context (run_id, branch, timestamp) ---
CTX_SKILL="$SKILL"
if [[ -n "$EXTRA" ]]; then
  MODE=$(python3 -c "import json; d=json.loads('''$EXTRA'''); m=d.get('mode',''); print(m if m and m!='default' else '')" 2>/dev/null || echo "")
  [[ -n "$MODE" ]] && CTX_SKILL="${SKILL}-${MODE}"
fi

# In embed mode: derive parent/ancestors/attributed_to from the parent's
# on-disk context file (issue #941 fix + R2 C8: NEVER trust a CLI-arg chain).
# The parent is identified as the latest non-completed *-context.json on the
# current branch, excluding the child we are about to create and the epilogue.
EMBED_EXTRA_JSON=""
if [[ -n "$EMBED_MODE" ]]; then
  CURRENT_BRANCH="$(git branch --show-current 2>/dev/null || echo "")"
  EMBED_EXTRA_JSON=$(CTX_SKILL_ENV="$CTX_SKILL" BRANCH_ENV="$CURRENT_BRANCH" PROJECT_DIR_ENV="$PROJECT_DIR" python3 - << 'PYEOF'
import json, glob, os
project = os.environ['PROJECT_DIR_ENV']
child_ctx_file = os.environ['CTX_SKILL_ENV'] + '-context.json'
branch = os.environ.get('BRANCH_ENV', '')
best = None
best_ts = ''
for f in glob.glob(os.path.join(project, '.runs', '*-context.json')):
    if os.path.basename(f) == child_ctx_file:
        continue
    if 'epilogue-context' in f:
        continue
    try:
        d = json.load(open(f))
    except:
        continue
    if branch and d.get('branch') and d.get('branch') != branch:
        continue
    if d.get('completed') is True:
        continue
    ts = d.get('timestamp', '')
    if ts > best_ts:
        best_ts = ts
        best = d
if best is None:
    print('{}')
else:
    parent = {'skill': best.get('skill', ''), 'run_id': best.get('run_id', '')}
    ancestors = list(best.get('ancestors') or []) + [parent]
    attr = best.get('attributed_to') or best.get('skill', '') or ''
    print(json.dumps({'parent': parent, 'ancestors': ancestors, 'attributed_to': attr}))
PYEOF
)
fi

if [[ -n "$EMBED_EXTRA_JSON" && "$EMBED_EXTRA_JSON" != "{}" ]]; then
  bash "$PROJECT_DIR/.claude/scripts/init-context.sh" "$CTX_SKILL" "$EMBED_EXTRA_JSON"
else
  bash "$PROJECT_DIR/.claude/scripts/init-context.sh" "$CTX_SKILL"
fi

# --- Step 5b: Embed → auto-skip the shared epilogue state (state 99) ---
# When a skill is embedded inside another (e.g. /verify inside /bootstrap at
# state 19b), only the parent runs the observation/delivery epilogue. Adding
# "99" to the embedded context's skip_states ensures lifecycle-next.sh returns
# FINALIZE for the embed (triggering EMBED_COMPLETE upstream) instead of
# dispatching to state-99-epilogue.md. Also sets embed_skip_epilogue=true as
# a belt-and-suspenders flag that survives state-level wholesale rewrites of
# skip_states (e.g. resolve/state-3b).
if [[ -n "$EMBED_MODE" ]]; then
  EMBED_CTX_PATH="$PROJECT_DIR/.runs/${CTX_SKILL}-context.json"
  if [[ -f "$EMBED_CTX_PATH" ]]; then
    python3 - "$EMBED_CTX_PATH" <<'PYEOF'
import json, sys
path = sys.argv[1]
d = json.load(open(path))
skip = set(str(s) for s in d.get('skip_states', []))
skip.add('99')
d['skip_states'] = sorted(skip)
d['embed_skip_epilogue'] = True
json.dump(d, open(path, 'w'), indent=2)
PYEOF
  fi
fi

# --- Step 5c: snapshot prose-gates fail_mode for in-flight safety ---
# Freezes per-gate fail_mode at run-start so mid-run registry changes do
# not affect this run. prose_gate_mode.resolve() consults this snapshot
# (gated on schema_version) before falling back to caller-passed prior_default.
# Legacy contexts (no snapshot field, or older snapshot version) fall through
# to prior_default → no in-flight regression. Closes #1449/#1431/#1433 in-flight
# safety requirement.
SNAP_CTX_PATH="$PROJECT_DIR/.runs/${CTX_SKILL}-context.json"
if [[ -f "$SNAP_CTX_PATH" ]]; then
  python3 - "$SNAP_CTX_PATH" "$PROJECT_DIR/.claude/patterns/prose-gates.json" <<'PYEOF'
import json, sys, datetime
ctx_path = sys.argv[1]
reg_path = sys.argv[2]
try:
    ctx = json.load(open(ctx_path))
    reg = json.load(open(reg_path))
    snap = {}
    for g in reg.get("gates", []) or []:
        gid = g.get("gate_id")
        fm = g.get("fail_mode")
        # Only snapshot gates with fail_mode (binary gates omit the field).
        if gid and fm in ("warn", "deny"):
            snap[gid] = fm
    ctx["prose_gates_modes_snapshot"] = snap
    ctx["prose_gates_modes_snapshot_at_version"] = reg.get("_schema_version", 1)
    ctx["prose_gates_modes_snapshot_taken_at"] = datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat()
    json.dump(ctx, open(ctx_path, "w"), indent=2)
except Exception as e:
    # Non-fatal: helper falls back to prior_default if snapshot absent.
    print(f"WARN: lifecycle-init.sh Step 5c — snapshot prose_gates_modes failed: {e}", file=sys.stderr)
PYEOF
fi
