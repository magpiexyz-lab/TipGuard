#!/usr/bin/env bash
# write-agent-trace.sh — Centralized agent-trace writer (AOC v1.1).
#
# Closes the gap from #1064 Defect 1: the canonical
#   `mkdir -p .runs/agent-traces && echo '<json>' > .runs/agent-traces/<name>.json`
# pattern documented across agent definitions is blocked by the chained-segment
# check in agent-trace-write-guard.sh. Routing through this single sanctioned
# writer eliminates that contradiction without weakening the regex (preserves
# #1023 fd-redirect normalization and #1045 chain-segment defense).
#
# Also adds two AOC v1.1 provenance values that have no agent-side path today:
#   - lead-on-behalf  — agent succeeded; lead transcribed because write blocked
#   - lead-synthesized — agent never spawned; lead writes consistency marker
#
# Usage:
#   bash .claude/scripts/write-agent-trace.sh <agent> --json '<trace-json>' \
#        [--provenance {self|self-degraded|lead-on-behalf|lead-synthesized|lead-fix}] \
#        [--source <attestation>]               # required for lead-on-behalf
#        [--coverage-provider <artifact-path>]  # required for lead-synthesized
#        [--lead-attestation true]              # required for lead-fix
#        [--trace-filename <name>.json]         # default: <agent>.json
#
# Behavior:
#   * Reads the supplied JSON payload (must be a single JSON object).
#   * Sets provenance to the flag value (default: "self").
#   * For lead-on-behalf: requires --source; sets partial:true; recovery_validated
#     starts false (validate-recovery.sh stamps it true after evidence check).
#   * For lead-synthesized: requires --coverage-provider; sets partial:true;
#     defaults no_fixes_claimed:true; rejects if payload contains non-empty fixes[].
#   * Stamps run_id / skill / spawn_sha / spawn_index from active identity +
#     spawn-log lookup (matches write-degraded-trace.py behavior).
#   * Atomic write via tempfile + rename.
#   * Idempotent in the sense that re-running with the same args overwrites
#     the trace deterministically.
#
# Exit codes:
#   0 — trace written
#   1 — input or precondition error
#   2 — JSON / payload validation error
set -euo pipefail

usage() {
  cat <<'EOF' >&2
Usage: write-agent-trace.sh <agent> --json '<trace-json>'
       [--provenance {self|self-degraded|lead-on-behalf|lead-synthesized}]
       [--source <attestation>]
       [--coverage-provider <artifact-path>]
       [--trace-filename <name>.json]
       [--spawn-index <N>]
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -lt 1 ]]; then
  usage
  exit 1
fi

AGENT="$1"
shift

PROVENANCE="self"
JSON_PAYLOAD=""
SOURCE=""
COVERAGE_PROVIDER=""
LEAD_ATTESTATION=""
TRACE_FILENAME=""
SPAWN_INDEX_OVERRIDE=""
SOURCE_RUN_ID=""
SOURCE_SKILL=""
EPOCH="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --json)               JSON_PAYLOAD="${2:-}"; shift 2 ;;
    --provenance)         PROVENANCE="${2:-self}"; shift 2 ;;
    --source)             SOURCE="${2:-}"; shift 2 ;;
    --coverage-provider)  COVERAGE_PROVIDER="${2:-}"; shift 2 ;;
    --lead-attestation)   LEAD_ATTESTATION="${2:-}"; shift 2 ;;
    --trace-filename)     TRACE_FILENAME="${2:-}"; shift 2 ;;
    --spawn-index)        SPAWN_INDEX_OVERRIDE="${2:-}"; shift 2 ;;
    # AOC v1.2: post-completion lead-orchestrated re-spawn override.
    --source-run-id)      SOURCE_RUN_ID="${2:-}"; shift 2 ;;
    --source-skill)       SOURCE_SKILL="${2:-}"; shift 2 ;;
    # #1274: per-page re-evaluation epoch. Default 0 = original trace.
    # When >0, default trace filename gains `--epoch<N>` suffix and the
    # JSON gains an `epoch` field consumed by design_critic_trace_selector.
    --epoch)              EPOCH="${2:-0}"; shift 2 ;;
    -h|--help)            usage; exit 0 ;;
    *)
      echo "ERROR: write-agent-trace.sh — unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -n "$SPAWN_INDEX_OVERRIDE" && ! "$SPAWN_INDEX_OVERRIDE" =~ ^[0-9]+$ ]]; then
  echo "ERROR: write-agent-trace.sh — --spawn-index must be a non-negative integer (got: $SPAWN_INDEX_OVERRIDE)" >&2
  exit 1
fi

if [[ -z "$AGENT" ]]; then
  echo "ERROR: write-agent-trace.sh — agent name is required" >&2
  exit 1
fi

if [[ -z "$JSON_PAYLOAD" ]]; then
  echo "ERROR: write-agent-trace.sh — --json '<...>' is required" >&2
  exit 1
fi

case "$PROVENANCE" in
  self|self-degraded|lead-on-behalf|lead-synthesized|lead-fix|lead-orchestrated) ;;
  *)
    echo "ERROR: write-agent-trace.sh — --provenance must be one of: self, self-degraded, lead-on-behalf, lead-synthesized, lead-fix, lead-orchestrated (got: $PROVENANCE)" >&2
    exit 1
    ;;
esac

# AOC v1.2: lead-orchestrated requires both --source-run-id and --source-skill;
# conversely, supplying source flags implies provenance=lead-orchestrated.
if [[ -n "$SOURCE_RUN_ID" || -n "$SOURCE_SKILL" ]]; then
  if [[ "$PROVENANCE" != "lead-orchestrated" ]]; then
    PROVENANCE="lead-orchestrated"
  fi
  if [[ "$LEAD_ATTESTATION" != "true" ]]; then
    LEAD_ATTESTATION="true"
  fi
fi
if [[ "$PROVENANCE" == "lead-orchestrated" ]]; then
  if [[ -z "$SOURCE_RUN_ID" || -z "$SOURCE_SKILL" ]]; then
    echo "ERROR: write-agent-trace.sh — --provenance lead-orchestrated requires both --source-run-id and --source-skill" >&2
    exit 1
  fi
  # Validate R1-R4 via the shared validator.
  source "$(dirname "$0")/lib/source_identity_validator.sh"
  if ! validate_source_identity "$SOURCE_RUN_ID" "$SOURCE_SKILL" "$AGENT"; then
    echo "ERROR: write-agent-trace.sh — source-identity validation failed (see above)" >&2
    exit 1
  fi
fi

if [[ "$PROVENANCE" == "lead-on-behalf" && -z "$SOURCE" ]]; then
  echo "ERROR: write-agent-trace.sh — --source is required when --provenance lead-on-behalf" >&2
  echo "  Suggested values: 'agent-returned-text', 'agent-tool-output'" >&2
  exit 1
fi

if [[ "$PROVENANCE" == "lead-synthesized" && -z "$COVERAGE_PROVIDER" ]]; then
  echo "ERROR: write-agent-trace.sh — --coverage-provider is required when --provenance lead-synthesized" >&2
  echo "  Provide the artifact path that satisfies coverage (e.g., 'tests/flows.test.ts')" >&2
  exit 1
fi

# EARC slice 3: lead-fix is the canonical provenance for in-flight lead-applied
# fixes (e.g., write-phase-a-repair.sh repairing a Phase A file with build
# evidence). lead-fix has its own preconditions (lead_attestation:true; no
# spawn-log requirement; no recovery_validated chain — the lead has direct
# knowledge). Per agent-trace-protocol.md:89.
if [[ "$PROVENANCE" == "lead-fix" && "$LEAD_ATTESTATION" != "true" ]]; then
  echo "ERROR: write-agent-trace.sh — --lead-attestation true is required when --provenance lead-fix" >&2
  echo "  lead-fix marks an in-flight lead-applied fix; the attestation flag is the consent signal." >&2
  exit 1
fi

# Resolve active identity (single source of truth).
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
cd "$PROJECT_DIR"

if [[ "$PROVENANCE" == "lead-orchestrated" ]]; then
  # AOC v1.2: source flags supplied — bypass resolve_active_identity (which
  # returns empty under post-completion). Validator already enforced R1-R4
  # above (including R4: source_skill differs from any active skill).
  ACTIVE_SKILL="$SOURCE_SKILL"
  ACTIVE_RUN_ID="$SOURCE_RUN_ID"
else
  ACTIVE_IDENTITY="$(bash -c 'source .claude/hooks/lib.sh && resolve_active_identity' 2>/dev/null || true)"
  if [[ -z "$ACTIVE_IDENTITY" ]]; then
    echo "ERROR: write-agent-trace.sh — no active skill context on current branch; cannot resolve run_id" >&2
    echo "  Hint: under post-completion conditions, supply --source-run-id and --source-skill (provenance=lead-orchestrated)." >&2
    exit 1
  fi
  IFS=$'\t' read -r ACTIVE_SKILL ACTIVE_RUN_ID _ACTIVE_ATTR _ACTIVE_ANCESTORS <<< "$ACTIVE_IDENTITY"
  if [[ -z "$ACTIVE_RUN_ID" ]]; then
    echo "ERROR: write-agent-trace.sh — active context has empty run_id" >&2
    exit 1
  fi
fi

# Compose final trace via Python for clean JSON manipulation. Validates the
# payload, stamps identity, applies provenance-specific defaults, atomic write.
AGENT_ENV="$AGENT" \
PROVENANCE_ENV="$PROVENANCE" \
SOURCE_ENV="$SOURCE" \
COVERAGE_PROVIDER_ENV="$COVERAGE_PROVIDER" \
LEAD_ATTESTATION_ENV="$LEAD_ATTESTATION" \
TRACE_FILENAME_ENV="$TRACE_FILENAME" \
SPAWN_INDEX_OVERRIDE_ENV="$SPAWN_INDEX_OVERRIDE" \
JSON_PAYLOAD_ENV="$JSON_PAYLOAD" \
ACTIVE_SKILL_ENV="$ACTIVE_SKILL" \
ACTIVE_RUN_ID_ENV="$ACTIVE_RUN_ID" \
SOURCE_RUN_ID_ENV="$SOURCE_RUN_ID" \
SOURCE_SKILL_ENV="$SOURCE_SKILL" \
EPOCH_ENV="$EPOCH" \
python3 - << 'PYEOF'
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

agent = os.environ["AGENT_ENV"]
provenance = os.environ["PROVENANCE_ENV"]
source = os.environ.get("SOURCE_ENV", "")
coverage_provider = os.environ.get("COVERAGE_PROVIDER_ENV", "")
lead_attestation = os.environ.get("LEAD_ATTESTATION_ENV", "")
trace_filename = os.environ.get("TRACE_FILENAME_ENV", "")
spawn_index_override_str = os.environ.get("SPAWN_INDEX_OVERRIDE_ENV", "")
spawn_index_override = int(spawn_index_override_str) if spawn_index_override_str else None
payload_raw = os.environ["JSON_PAYLOAD_ENV"]
active_skill = os.environ.get("ACTIVE_SKILL_ENV", "")
active_run_id = os.environ.get("ACTIVE_RUN_ID_ENV", "")
source_run_id = os.environ.get("SOURCE_RUN_ID_ENV", "")
source_skill = os.environ.get("SOURCE_SKILL_ENV", "")
try:
    epoch = int(os.environ.get("EPOCH_ENV", "0") or "0")
    if epoch < 0:
        epoch = 0
except (TypeError, ValueError):
    epoch = 0

try:
    payload = json.loads(payload_raw)
except json.JSONDecodeError as exc:
    sys.stderr.write(f"ERROR: write-agent-trace.sh — --json is not valid JSON: {exc}\n")
    sys.exit(2)

if not isinstance(payload, dict):
    sys.stderr.write("ERROR: write-agent-trace.sh — --json payload must be a JSON object\n")
    sys.exit(2)

# Reject any caller attempt to override identity / provenance via payload
# protected fields. The script owns these.
PROTECTED_FIELDS = {
    "agent", "provenance", "run_id", "skill", "spawn_sha", "spawn_index",
    "lead_attestation",  # only valid via the dedicated --provenance lead-fix
}
for f in PROTECTED_FIELDS:
    if f in payload and f != "agent":
        sys.stderr.write(
            f"ERROR: write-agent-trace.sh — payload may not set protected field {f!r}; "
            "use the corresponding flag instead\n"
        )
        sys.exit(2)

# If payload includes an "agent" field, it must match the CLI argument.
if "agent" in payload and payload["agent"] != agent:
    sys.stderr.write(
        f"ERROR: write-agent-trace.sh — payload.agent={payload['agent']!r} != CLI arg {agent!r}\n"
    )
    sys.exit(2)

# Spawn-log lookup for spawn_sha / spawn_index inheritance (matches
# write-degraded-trace.py behavior).
#
# When --spawn-index <N> is supplied: require an exact match on (agent, run_id,
# hook, spawn_index). This disambiguates parallel spawns of the same agent type
# (e.g., scaffold-pages-home / scaffold-pages-pricing). Without the override the
# loop falls back to first-match semantics — preserves single-spawn agents and
# does not change existing migrated callers.
spawn_log_path = ".runs/agent-spawn-log.jsonl"
spawn_sha = ""
spawn_index = None
if os.path.isfile(spawn_log_path):
    with open(spawn_log_path) as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if not (
                e.get("agent") == agent
                and e.get("run_id") == active_run_id
                and e.get("hook") == "skill-agent-gate"
            ):
                continue
            if spawn_index_override is not None:
                if e.get("spawn_index") != spawn_index_override:
                    continue
            spawn_sha = e.get("head_sha", "")
            spawn_index = e.get("spawn_index")
            break

# When the caller supplied --spawn-index but no spawn-log row matched, fail
# closed instead of silently writing with spawn_index=None. The override exists
# precisely to disambiguate parallel spawns; a miss means the caller asserted
# something the spawn-log can't corroborate.
if spawn_index_override is not None and spawn_index is None:
    sys.stderr.write(
        f"ERROR: write-agent-trace.sh — --spawn-index {spawn_index_override} "
        f"requested but no spawn-log row matches "
        f"(agent={agent!r}, run_id={active_run_id!r}, hook=skill-agent-gate, "
        f"spawn_index={spawn_index_override}).\n"
    )
    sys.exit(2)

# For lead-on-behalf: spawn-log entry MUST exist (the agent really was spawned;
# the lead is transcribing its returned output). Otherwise fail-closed: an
# unspawned agent cannot have a "succeeded" trace transcribed.
if provenance == "lead-on-behalf" and not spawn_sha and spawn_index is None:
    sys.stderr.write(
        "ERROR: write-agent-trace.sh — provenance=lead-on-behalf requires a spawn-log "
        f"entry for agent {agent!r} in run_id {active_run_id!r}; none found. "
        "If the agent was never spawned, use --provenance lead-synthesized.\n"
    )
    sys.exit(1)

# Build the trace by overlaying caller payload onto the script-stamped fields.
trace = {
    "agent": agent,
    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "status": "completed",
    "provenance": provenance,
    "run_id": active_run_id,
    "skill": active_skill,
    "spawn_sha": spawn_sha,
    "spawn_index": spawn_index,
}

# Merge caller payload (skipping protected fields the script owns).
for k, v in payload.items():
    if k in PROTECTED_FIELDS:
        continue
    trace[k] = v

# Provenance-specific defaults / requirements.
if provenance == "self":
    trace.setdefault("partial", False)

if provenance == "self-degraded":
    trace.setdefault("partial", True)
    if not trace.get("degraded_reason"):
        sys.stderr.write(
            "ERROR: write-agent-trace.sh — provenance=self-degraded requires payload.degraded_reason\n"
        )
        sys.exit(1)
    trace.setdefault("recovery_validated", False)
    trace.setdefault("recovery", False)

if provenance == "lead-on-behalf":
    trace["partial"] = True
    trace["source"] = source
    trace.setdefault("recovery_validated", False)
    trace.setdefault("recovery", False)
    # checks_performed must reflect the agent's actual checks; granularity
    # gate here is "must be present" — the artifact-integrity-gate enforces
    # non-empty for non-marker provenance.
    if not isinstance(trace.get("checks_performed"), list):
        sys.stderr.write(
            "ERROR: write-agent-trace.sh — provenance=lead-on-behalf requires payload.checks_performed (array)\n"
        )
        sys.exit(1)

if provenance == "lead-synthesized":
    trace["partial"] = True
    trace["coverage_provider"] = coverage_provider
    trace.setdefault("no_fixes_claimed", True)
    trace.setdefault("recovery_validated", False)
    trace.setdefault("recovery", False)
    # Reject non-empty fixes — synthesized markers must not claim work.
    fixes = trace.get("fixes")
    if isinstance(fixes, list) and len(fixes) > 0:
        sys.stderr.write(
            "ERROR: write-agent-trace.sh — provenance=lead-synthesized must not claim fixes; use lead-on-behalf or lead-fix instead\n"
        )
        sys.exit(1)
    # checks_performed may be empty for synthesized markers (artifact-integrity-gate
    # allows empty checks for lead-synthesized).
    trace.setdefault("checks_performed", [])

if provenance == "lead-orchestrated":
    # AOC v1.2: post-completion lead-orchestrated re-spawn. Lead supplied
    # explicit identity via --source-run-id + --source-skill; validator
    # already enforced R1-R4 upstream. Stamp source fields into the trace
    # for audit trail; downstream gates use pass_lead_orchestrated predicate
    # — no recovery_validated chain (lead has direct knowledge).
    trace["partial"] = True
    trace["lead_attestation"] = True
    trace["source_run_id"] = source_run_id
    trace["source_skill"] = source_skill
    if not isinstance(trace.get("checks_performed"), list):
        trace["checks_performed"] = []

if provenance == "lead-fix":
    # EARC slice 3: lead self-applied fix (e.g., write-phase-a-repair.sh).
    # Per agent-trace-protocol.md:89, lead-fix preconditions are
    # lead_attestation:true + partial:true + non-empty fixes[] entries with
    # file/symptom/fix populated. Downstream gates use pass_lead_fix predicate
    # — no recovery_validated chain (lead has direct knowledge).
    trace["partial"] = True
    trace["lead_attestation"] = True
    # Granularity check: at least one fix entry, all with non-empty file,
    # symptom, fix.
    fixes = trace.get("fixes")
    if not isinstance(fixes, list) or len(fixes) == 0:
        sys.stderr.write(
            "ERROR: write-agent-trace.sh — provenance=lead-fix requires payload.fixes to be a non-empty array\n"
        )
        sys.exit(1)
    for i, fix in enumerate(fixes):
        if not isinstance(fix, dict):
            sys.stderr.write(
                f"ERROR: write-agent-trace.sh — fixes[{i}] must be an object\n"
            )
            sys.exit(1)
        for k in ("file", "symptom", "fix"):
            v = fix.get(k)
            if not isinstance(v, str) or not v.strip():
                sys.stderr.write(
                    f"ERROR: write-agent-trace.sh — fixes[{i}].{k} must be a non-empty string (lead-fix granularity gate)\n"
                )
                sys.exit(1)
    # checks_performed should reflect what the lead actually did.
    if not isinstance(trace.get("checks_performed"), list):
        trace["checks_performed"] = []

# #1274: stamp epoch into the trace JSON so design_critic_trace_selector
# can prefer the structured field over filename parsing.
if epoch > 0:
    trace["epoch"] = epoch

# Atomic write to .runs/agent-traces/<name>.json
out_dir = ".runs/agent-traces"
os.makedirs(out_dir, exist_ok=True)
# When the caller did not supply --trace-filename AND --epoch > 0, default
# the basename to `<agent>--epoch<N>.json`. Per-page callers (design-critic
# Single-Page Mode) supply `--trace-filename design-critic-<page>.json`
# explicitly; for re-evaluations they pass `design-critic-<page>--epoch<N>.json`.
if trace_filename:
    out_filename = trace_filename
elif epoch > 0:
    out_filename = f"{agent}--epoch{epoch}.json"
else:
    out_filename = f"{agent}.json"
out_path = os.path.join(out_dir, out_filename)

# tempfile + rename for POSIX atomicity (mirrors write-fix-ledger.py pattern).
fd, tmp_path = tempfile.mkstemp(prefix=".write-agent-trace-", dir=out_dir)
try:
    with os.fdopen(fd, "w") as f:
        json.dump(trace, f, indent=2)
        f.write("\n")
    os.rename(tmp_path, out_path)
except Exception:
    try:
        os.unlink(tmp_path)
    except OSError:
        pass
    raise

sys.stderr.write(
    f"write-agent-trace.sh: wrote {out_path} (provenance={provenance}, run_id={active_run_id})\n"
)
if provenance in ("self-degraded", "lead-on-behalf"):
    sys.stderr.write(
        "  Note: recovery_validated:false — validate-recovery.sh will stamp true after build+e2e+diff evidence.\n"
    )
PYEOF
