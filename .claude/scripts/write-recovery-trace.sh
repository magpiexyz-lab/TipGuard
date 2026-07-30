#!/usr/bin/env bash
# write-recovery-trace.sh — Controlled recovery trace writer.
# Use ONLY when an agent genuinely crashed after being spawned but before
# writing its completion trace. Writes the trace only — does NOT append to
# the spawn-log (the skill-agent-gate hook entry is the authoritative spawn
# evidence; recovery reuses it — issue #963 fix removes the forgery surface).
#
# Usage: bash .claude/scripts/write-recovery-trace.sh <agent-name> --reason "<specific cause>"
#        bash .claude/scripts/write-recovery-trace.sh <agent-name> --reason "..." \
#             --run-id <RUN_ID>     # AOC v1.1 (PR3): cross-skill / post-completion recovery
#
# Preconditions (ALL enforced):
#   1. --reason "<text>" is mandatory
#   2. Target agent is not in agent-registry.json.recovery_forbidden
#      (TYPE C-1: high-risk fixer agents (security-fixer, quality-fixer)
#      cannot be recovered externally; they must self-degrade instead)
#   3. A spawn-log entry from skill-agent-gate exists for <agent> in the
#      target run_id (proves Agent tool was really invoked — LLM
#      cannot forge this via Bash because skill-agent-gate is a hook)
#   4. Target trace file is absent OR a stub ({status:"started"} no verdict) —
#      refuses to overwrite a potentially legitimate completed trace
#
# AOC v1.1 (#1064 D3): When --run-id <ID> is provided, the script:
#   * Skips resolve_active_identity (allows recovery when source skill is
#     completed, or from a different active skill via /observe etc.)
#   * Validates the supplied ID exists in some .runs/*-context.json.run_id
#   * Validates spawn-log entry for <agent> + supplied ID
#   * Clause (d'): the supplied ID's context.skill MUST differ from the
#     currently-active skill (if any). Blocks same-skill forgery while
#     permitting cross-skill recovery (e.g., /observe recovering a
#     completed /resolve agent's stub).
#   * Double-empty case: when both supplied-context.skill AND active.skill
#     are empty, FAIL-CLOSED (refuses recovery — this is a data-health
#     scenario, not a normal recovery path).
set -euo pipefail

AGENT=""
REASON=""
OVERRIDE_RUN_ID=""
FIXES_JSON=""
EVIDENCE_SOURCE=""
SOURCE_SKILL=""
PROVENANCE_VARIANT="recovery"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --reason)
      REASON="${2:-}"
      shift 2
      ;;
    --reason=*)
      REASON="${1#--reason=}"
      shift
      ;;
    --run-id)
      OVERRIDE_RUN_ID="${2:-}"
      shift 2
      ;;
    --run-id=*)
      OVERRIDE_RUN_ID="${1#--run-id=}"
      shift
      ;;
    # AOC v1.2: post-completion lead-orchestrated re-spawn variant.
    # Use with --run-id to attribute the trace to a specific run + skill
    # (validator R4 enforces: source_skill must differ from active skill).
    --source-skill)
      SOURCE_SKILL="${2:-}"
      shift 2
      ;;
    --source-skill=*)
      SOURCE_SKILL="${1#--source-skill=}"
      shift
      ;;
    --provenance-variant)
      PROVENANCE_VARIANT="${2:-recovery}"
      shift 2
      ;;
    --provenance-variant=*)
      PROVENANCE_VARIANT="${1#--provenance-variant=}"
      shift
      ;;
    --fixes-json)
      FIXES_JSON="${2:-}"
      shift 2
      ;;
    --fixes-json=*)
      FIXES_JSON="${1#--fixes-json=}"
      shift
      ;;
    --evidence-source)
      EVIDENCE_SOURCE="${2:-}"
      shift 2
      ;;
    --evidence-source=*)
      EVIDENCE_SOURCE="${1#--evidence-source=}"
      shift
      ;;
    --help|-h)
      echo "Usage: $0 <agent-name> --reason \"<specific cause>\" [--run-id <RUN_ID>] [--fixes-json '<json>' --evidence-source <path>]"
      exit 0
      ;;
    -*)
      echo "ERROR: write-recovery-trace.sh — unknown flag: $1" >&2
      exit 1
      ;;
    *)
      if [[ -z "$AGENT" ]]; then
        AGENT="$1"
      else
        echo "ERROR: write-recovery-trace.sh — unexpected positional arg: $1" >&2
        exit 1
      fi
      shift
      ;;
  esac
done

if [[ -z "$AGENT" ]]; then
  echo "ERROR: write-recovery-trace.sh — agent name required" >&2
  echo "Usage: $0 <agent-name> --reason \"<specific cause>\"" >&2
  exit 1
fi

if [[ -z "$REASON" ]]; then
  echo "ERROR: write-recovery-trace.sh — --reason is mandatory (issue #963 precondition)" >&2
  echo "Usage: $0 <agent-name> --reason \"<specific cause>\"" >&2
  exit 1
fi

# AOC v1.2: validate provenance variant + source-skill pairing.
case "$PROVENANCE_VARIANT" in
  recovery|lead-orchestrated) ;;
  *)
    echo "ERROR: write-recovery-trace.sh — --provenance-variant must be 'recovery' (default) or 'lead-orchestrated' (got: $PROVENANCE_VARIANT)" >&2
    exit 1
    ;;
esac
if [[ "$PROVENANCE_VARIANT" == "lead-orchestrated" ]]; then
  if [[ -z "$OVERRIDE_RUN_ID" || -z "$SOURCE_SKILL" ]]; then
    echo "ERROR: write-recovery-trace.sh — --provenance-variant lead-orchestrated requires both --run-id and --source-skill" >&2
    exit 1
  fi
  # Validate R1-R4 via the shared validator (R1 xor checked here implicitly
  # by requiring both flags above; R2/R3/R4 checked by the validator).
  source "$(dirname "$0")/lib/source_identity_validator.sh"
  if ! validate_source_identity "$OVERRIDE_RUN_ID" "$SOURCE_SKILL" "$AGENT"; then
    echo "ERROR: write-recovery-trace.sh — source-identity validation failed (see above)" >&2
    exit 1
  fi
fi

# EARC slice 1 (closes #1189): if either --fixes-json or --evidence-source is
# provided, both must be — they are paired so the validator can enforce the
# evidence-anchored recovery path.
if [[ -n "$FIXES_JSON" && -z "$EVIDENCE_SOURCE" ]]; then
  echo "ERROR: write-recovery-trace.sh — --fixes-json requires --evidence-source (paired flags)." >&2
  echo "       Lead-transcribed fixes must point to an external evidence file (build-result.json, etc.)" >&2
  exit 1
fi
if [[ -n "$EVIDENCE_SOURCE" && -z "$FIXES_JSON" ]]; then
  echo "ERROR: write-recovery-trace.sh — --evidence-source requires --fixes-json (paired flags)." >&2
  exit 1
fi

PROJECT_DIR="$(git rev-parse --show-toplevel 2>/dev/null || echo "${CLAUDE_PROJECT_DIR:-.}")"
SPAWN_LOG="$PROJECT_DIR/.runs/agent-spawn-log.jsonl"
TRACES_DIR="$PROJECT_DIR/.runs/agent-traces"
REGISTRY="$PROJECT_DIR/.claude/patterns/agent-registry.json"
TARGET_TRACE="$TRACES_DIR/$AGENT.json"

# Resolve active identity (single source of truth for run_id when no override)
# shellcheck source=../hooks/lib.sh
source "$PROJECT_DIR/.claude/hooks/lib.sh"
ACTIVE_IDENTITY="$(resolve_active_identity)"
ACTIVE_SKILL=""
ACTIVE_RUN_ID=""
if [[ -n "$ACTIVE_IDENTITY" ]]; then
  IFS=$'\t' read -r ACTIVE_SKILL ACTIVE_RUN_ID _ _ <<< "$ACTIVE_IDENTITY"
fi

# AOC v1.1 (#1064 D3) cross-skill / post-completion recovery.
# When --run-id is supplied, validate it and use it as the target run_id.
# When --run-id is NOT supplied, require an active context (preserves
# pre-v1.1 in-skill recovery semantics — HC11 active-run protection).
TARGET_RUN_ID=""
TARGET_SKILL=""
if [[ -n "$OVERRIDE_RUN_ID" ]]; then
  # Validate the supplied --run-id appears in some context.run_id field
  # (proves the run actually existed at some point — defends against
  # arbitrary-ID forgery, per #963 security intent).
  TARGET_SKILL=$(OVERRIDE_RUN_ID_ENV="$OVERRIDE_RUN_ID" PROJECT_DIR_ENV="$PROJECT_DIR" python3 -c "
import json, glob, os, sys
target = os.environ['OVERRIDE_RUN_ID_ENV']
proj = os.environ['PROJECT_DIR_ENV']
matched_skill = None
for f in glob.glob(os.path.join(proj, '.runs', '*-context.json')):
    if os.path.basename(f) == 'epilogue-context.json':
        continue
    try:
        d = json.load(open(f))
    except:
        continue
    if d.get('run_id') == target:
        matched_skill = d.get('skill', '') or ''
        break
if matched_skill is None:
    sys.stderr.write('NO_MATCH\n')
    sys.exit(1)
print(matched_skill)
" 2>/dev/null) || {
    echo "ERROR: write-recovery-trace.sh — --run-id $OVERRIDE_RUN_ID not found in any .runs/*-context.json" >&2
    echo "       Refusing to recover an unknown run (forgery defense, per #963)." >&2
    exit 1
  }
  # Clause (d'): the target run's skill MUST differ from currently-active
  # skill (when an active skill exists). Same-skill recovery is forgery
  # surface (the active skill should self-handle its own crashes via the
  # default no-override path).
  # Double-empty case: both target.skill and active.skill empty → fail-closed.
  if [[ -z "$TARGET_SKILL" && -z "$ACTIVE_SKILL" ]]; then
    echo "ERROR: write-recovery-trace.sh — --run-id $OVERRIDE_RUN_ID context has empty skill AND no active skill on branch (double-empty case)." >&2
    echo "       Fail-closed: refuses recovery in this configuration. If the legacy context is genuinely orphaned, repair it directly rather than via --run-id." >&2
    exit 1
  fi
  if [[ -n "$ACTIVE_SKILL" && "$TARGET_SKILL" == "$ACTIVE_SKILL" ]]; then
    echo "ERROR: write-recovery-trace.sh — --run-id $OVERRIDE_RUN_ID belongs to the currently-active skill ($ACTIVE_SKILL)." >&2
    echo "       Same-skill recovery is forbidden via --run-id (use the no-override path instead)." >&2
    exit 1
  fi
  TARGET_RUN_ID="$OVERRIDE_RUN_ID"
else
  # Default: require active identity (HC11 — preserves pre-v1.1 contract).
  if [[ -z "$ACTIVE_IDENTITY" ]]; then
    echo "ERROR: write-recovery-trace.sh — no active skill context on current branch; cannot resolve run_id" >&2
    echo "       For cross-skill or post-completion recovery, supply --run-id <RUN_ID>." >&2
    exit 1
  fi
  if [[ -z "$ACTIVE_RUN_ID" ]]; then
    echo "ERROR: write-recovery-trace.sh — active context has empty run_id" >&2
    exit 1
  fi
  TARGET_RUN_ID="$ACTIVE_RUN_ID"
  TARGET_SKILL="$ACTIVE_SKILL"
fi

# Precondition 2: agent must not be in recovery_forbidden
FORBIDDEN=$(AGENT_ENV="$AGENT" REGISTRY_ENV="$REGISTRY" python3 -c "
import json, os
agent = os.environ['AGENT_ENV']
try:
    r = json.load(open(os.environ['REGISTRY_ENV']))
    print('yes' if agent in r.get('recovery_forbidden', []) else 'no')
except:
    print('no')
" 2>/dev/null || echo "no")
if [[ "$FORBIDDEN" == "yes" ]]; then
  echo "ERROR: write-recovery-trace.sh — '$AGENT' is in recovery_forbidden (high-risk fixer)." >&2
  echo "       Recovery is refused for this agent; it must self-degrade via write-degraded-trace.py." >&2
  exit 1
fi

# Precondition 3: spawn-log entry from skill-agent-gate exists for this agent + target run_id
SPAWN_INFO=$(AGENT_ENV="$AGENT" RUN_ID_ENV="$TARGET_RUN_ID" SPAWN_LOG_ENV="$SPAWN_LOG" python3 -c "
import json, os
agent = os.environ['AGENT_ENV']
run_id = os.environ['RUN_ID_ENV']
path = os.environ['SPAWN_LOG_ENV']
if not os.path.isfile(path):
    print('')
    exit(0)
found = None
with open(path) as f:
    for line in f:
        try:
            e = json.loads(line)
        except:
            continue
        if e.get('agent') == agent and e.get('run_id') == run_id and e.get('hook') == 'skill-agent-gate':
            found = e
            break
if found is None:
    print('')
else:
    print(json.dumps({'spawn_index': found.get('spawn_index'), 'head_sha': found.get('head_sha', '')}))
" 2>/dev/null || echo "")
if [[ -z "$SPAWN_INFO" ]]; then
  echo "ERROR: write-recovery-trace.sh — no skill-agent-gate spawn-log entry for '$AGENT' in run_id=$TARGET_RUN_ID" >&2
  echo "       Recovery requires the Agent tool to have actually been invoked." >&2
  exit 1
fi

# Precondition 4: target trace absent OR a stub
if [[ -f "$TARGET_TRACE" ]]; then
  TRACE_STATE=$(TARGET_ENV="$TARGET_TRACE" python3 -c "
import json, os
try:
    d = json.load(open(os.environ['TARGET_ENV']))
    has_verdict = 'verdict' in d
    status = d.get('status', '')
    if status == 'started' and not has_verdict:
        print('stub')
    else:
        print('completed')
except:
    print('error')
" 2>/dev/null || echo "error")
  if [[ "$TRACE_STATE" != "stub" ]]; then
    echo "ERROR: write-recovery-trace.sh — target trace at $TARGET_TRACE is not a stub (has verdict or malformed)" >&2
    echo "       Refusing to overwrite a potentially legitimate completed trace." >&2
    exit 1
  fi
fi

# All preconditions met — write recovery trace
mkdir -p "$TRACES_DIR"
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

SPAWN_INDEX=$(echo "$SPAWN_INFO" | python3 -c "import json,sys; print(json.load(sys.stdin).get('spawn_index', ''))")
HEAD_SHA=$(echo "$SPAWN_INFO" | python3 -c "import json,sys; print(json.load(sys.stdin).get('head_sha', ''))")

AGENT_ENV="$AGENT" TS_ENV="$TS" REASON_ENV="$REASON" RUN_ID_ENV="$TARGET_RUN_ID" \
SKILL_ENV="$TARGET_SKILL" SPAWN_SHA_ENV="$HEAD_SHA" SPAWN_IDX_ENV="$SPAWN_INDEX" \
TARGET_ENV="$TARGET_TRACE" FIXES_JSON_ENV="$FIXES_JSON" EVIDENCE_SOURCE_ENV="$EVIDENCE_SOURCE" \
PROVENANCE_VARIANT_ENV="$PROVENANCE_VARIANT" SOURCE_SKILL_ENV="$SOURCE_SKILL" \
python3 - << 'PYEOF'
import json, os, sys

variant = os.environ.get('PROVENANCE_VARIANT_ENV', 'recovery')
source_skill = os.environ.get('SOURCE_SKILL_ENV', '')

if variant == 'lead-orchestrated':
    # AOC v1.2: lead-orchestrated re-spawn variant. Lead supplied --run-id and
    # --source-skill; validator already enforced R1-R4. Stamp pass-able shape
    # (verdict=pass, lead_attestation, source fields) so downstream gates can
    # accept via pass_lead_orchestrated predicate.
    trace = {
        'agent': os.environ['AGENT_ENV'],
        'timestamp': os.environ['TS_ENV'],
        'status': 'completed',
        'verdict': 'pass',
        'provenance': 'lead-orchestrated',
        'partial': True,
        'lead_attestation': True,
        'source_run_id': os.environ['RUN_ID_ENV'],
        'source_skill': source_skill,
        'checks_performed': ['lead-orchestrated-respawn'],
        'degraded_reason': os.environ['REASON_ENV'],
        'recovery': False,
        'run_id': os.environ['RUN_ID_ENV'],
        'skill': source_skill,
        'spawn_sha': os.environ['SPAWN_SHA_ENV'],
        'spawn_index': int(os.environ['SPAWN_IDX_ENV']) if os.environ['SPAWN_IDX_ENV'] else None,
    }
else:
    trace = {
        'agent': os.environ['AGENT_ENV'],
        'timestamp': os.environ['TS_ENV'],
        'status': 'abandoned',
        # EARC slice 1: 'verdict' renamed from 'recovery' (anomalous, outside the
        # closed verdict enum {pass,fail,blocked,unresolved}) to 'unresolved'
        # (within the enum). Provenance stays 'recovery' — that's the correct
        # signal for downstream gates (validate_fallback predicate keys on
        # provenance). No consumer hardcoded verdict=='recovery'; safe rename.
        'verdict': 'unresolved',
        'provenance': 'recovery',
        'partial': True,
        'checks_performed': ['exhaustion-recovery'],
        'degraded_reason': os.environ['REASON_ENV'],
        'recovery_reason': os.environ['REASON_ENV'],
        'recovery': True,
        'recovery_validated': False,
        'run_id': os.environ['RUN_ID_ENV'],
        'skill': os.environ['SKILL_ENV'],
        'spawn_sha': os.environ['SPAWN_SHA_ENV'],
        'spawn_index': int(os.environ['SPAWN_IDX_ENV']) if os.environ['SPAWN_IDX_ENV'] else None,
    }

# EARC slice 1 (closes #1189): when the lead supplies --fixes-json with an
# anchored --evidence-source, attach the fixes (each stamped with
# lead_transcribed:true so downstream consumers can distinguish "agent's own
# claim" from "lead's recovery-evidence claim") and the lead_evidence_source
# pointer. validate-recovery.sh reads these to stamp recovery_validated:true.
fixes_raw = os.environ.get('FIXES_JSON_ENV', '').strip()
ev_source = os.environ.get('EVIDENCE_SOURCE_ENV', '').strip()
if fixes_raw:
    try:
        fixes = json.loads(fixes_raw)
    except json.JSONDecodeError as exc:
        sys.stderr.write(f'ERROR: --fixes-json is not valid JSON: {exc}\n')
        sys.exit(1)
    if not isinstance(fixes, list):
        sys.stderr.write('ERROR: --fixes-json must be a JSON array\n')
        sys.exit(1)
    for f in fixes:
        if isinstance(f, dict):
            f['lead_transcribed'] = True
    trace['fixes'] = fixes
    trace['no_fixes_claimed'] = False
if ev_source:
    trace['lead_evidence_source'] = ev_source

json.dump(trace, open(os.environ['TARGET_ENV'], 'w'), indent=2)
PYEOF

echo "Recovery trace written: $TARGET_TRACE (reason: \"$REASON\")"
if [[ -n "$FIXES_JSON" ]]; then
  echo "Lead-transcribed fixes attached; lead_evidence_source: $EVIDENCE_SOURCE"
fi
echo "Note: recovery_validated:false — run .claude/scripts/validate-recovery.sh $AGENT to stamp it true after evidence check."
