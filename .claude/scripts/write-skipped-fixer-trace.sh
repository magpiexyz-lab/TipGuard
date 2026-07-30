#!/usr/bin/env bash
# write-skipped-fixer-trace.sh — AOC v1.2 audit-only writer for fixer
# sanctioned-skip (closes #1250).
#
# When an upstream hard gate fires (e.g., security-defender or attacker
# produces critical findings the upstream cannot fix), the fixer agent
# (security-fixer / quality-fixer) is correctly told NOT to spawn. But
# without a trace, downstream gates have no audit record of that decision.
#
# This writer produces an AUDIT-ONLY trace with:
#   provenance: lead-skipped
#   verdict:    skipped     (NEW in AOC v1.2 fixer vocabulary)
#   result:     skipped     (NEW in AOC v1.2 fixer vocabulary)
#
# Critically: NO predicate accepts verdict=skipped. The hard gate blocks
# naturally because no pass_* predicate matches. The trace exists solely
# so observer + audit consumers see the decision; it CANNOT grant pass.
# This is intentional per the design Q1 first-principles analysis: a
# predicate that converted skip into pass would silently approve merging
# code with known-bad findings.
#
# Usage:
#   bash .claude/scripts/write-skipped-fixer-trace.sh <agent> \
#     --reason hard_gate_failure \
#     --upstream-merge-path .runs/security-merge.json \
#     [--source-run-id <ID> --source-skill <NAME>]
#
# Validation (fail-closed):
#   1. <agent> must be in agent-registry.json:recovery_forbidden
#      (currently: security-fixer, quality-fixer)
#   2. --reason must be a known enum value (hard_gate_failure today;
#      extensible). Empty/missing rejected.
#   3. --upstream-merge-path must exist AND parse as JSON AND contain
#      "fixer_skipped": true AND "reason": "<value>" matching --reason.
#   4. unresolved_critical is COMPUTED from the upstream merge file (not
#      caller-supplied). Forging requires editing the upstream merge file
#      in the same PR — visible in diff.
#   5. Identity resolved via resolve_active_identity by default. Under
#      post-completion conditions, supply --source-run-id + --source-skill
#      (validator R1-R4 enforced via shared lib).
#
# Counting algorithm for unresolved_critical:
#   - For security-merge.json: union of defender `fails` + attacker
#     `findings` (already merged into `issues` by state-4-security-merge-fix.md).
#     unresolved_critical = count where severity in {critical, high, serious}.
#   - For quality-merge.json: same algorithm on the unified `issues` array
#     (which already merges a11y violations + consistency inconsistencies
#     by state-3d-quality-fix.md).
#   - Severity vocabulary {critical, high, serious} matches the existing
#     additional_block_conditions semantics for unresolved_critical>0.

set -euo pipefail

AGENT=""
REASON=""
UPSTREAM_MERGE_PATH=""
SOURCE_RUN_ID=""
SOURCE_SKILL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --reason)               REASON="${2:-}"; shift 2 ;;
    --reason=*)             REASON="${1#--reason=}"; shift ;;
    --upstream-merge-path)  UPSTREAM_MERGE_PATH="${2:-}"; shift 2 ;;
    --upstream-merge-path=*) UPSTREAM_MERGE_PATH="${1#--upstream-merge-path=}"; shift ;;
    --source-run-id)        SOURCE_RUN_ID="${2:-}"; shift 2 ;;
    --source-run-id=*)      SOURCE_RUN_ID="${1#--source-run-id=}"; shift ;;
    --source-skill)         SOURCE_SKILL="${2:-}"; shift 2 ;;
    --source-skill=*)       SOURCE_SKILL="${1#--source-skill=}"; shift ;;
    --unresolved-critical|--unresolved-critical=*)
      # AOC v1.2 forgery defense: this writer COMPUTES the count itself.
      # Caller cannot supply a value (would allow forging audit-only-pass
      # by claiming unresolved_critical:0 when the merge file has criticals).
      echo "ERROR: write-skipped-fixer-trace.sh — --unresolved-critical is REJECTED." >&2
      echo "  The writer computes this value from --upstream-merge-path; caller cannot override." >&2
      echo "  Forging would defeat the audit-only safety contract — the upstream gate already" >&2
      echo "  fires when there ARE critical findings, so unresolved_critical > 0 is the expected" >&2
      echo "  honest state for every legitimate sanctioned-skip." >&2
      exit 1
      ;;
    --help|-h)
      sed -n '2,55p' "$0"
      exit 0
      ;;
    -*)
      echo "ERROR: write-skipped-fixer-trace.sh — unknown flag: $1" >&2
      exit 1
      ;;
    *)
      if [[ -z "$AGENT" ]]; then
        AGENT="$1"
      else
        echo "ERROR: write-skipped-fixer-trace.sh — unexpected positional arg: $1" >&2
        exit 1
      fi
      shift
      ;;
  esac
done

if [[ -z "$AGENT" ]]; then
  echo "ERROR: write-skipped-fixer-trace.sh — agent name required" >&2
  echo "  Usage: $0 <agent> --reason hard_gate_failure --upstream-merge-path .runs/security-merge.json" >&2
  exit 1
fi

if [[ -z "$REASON" ]]; then
  echo "ERROR: write-skipped-fixer-trace.sh — --reason is mandatory" >&2
  echo "  Canonical value: hard_gate_failure" >&2
  exit 1
fi

case "$REASON" in
  hard_gate_failure) ;;
  *)
    echo "ERROR: write-skipped-fixer-trace.sh — --reason $REASON is not a recognized value." >&2
    echo "  Accepted: hard_gate_failure" >&2
    exit 1
    ;;
esac

if [[ -z "$UPSTREAM_MERGE_PATH" ]]; then
  echo "ERROR: write-skipped-fixer-trace.sh — --upstream-merge-path is mandatory" >&2
  echo "  Provide the upstream merge file proving the gate fired (e.g., .runs/security-merge.json)" >&2
  exit 1
fi

PROJECT_DIR="$(git rev-parse --show-toplevel 2>/dev/null || echo "${CLAUDE_PROJECT_DIR:-.}")"
cd "$PROJECT_DIR"

# Validation 1: agent must be in recovery_forbidden.
REGISTRY="$PROJECT_DIR/.claude/patterns/agent-registry.json"
if ! python3 -c "
import json, sys
reg = json.load(open('$REGISTRY'))
if '$AGENT' not in reg.get('recovery_forbidden', []):
    sys.exit(1)
" 2>/dev/null; then
  echo "ERROR: write-skipped-fixer-trace.sh — agent '$AGENT' is not in recovery_forbidden." >&2
  echo "  Only fixer agents (security-fixer, quality-fixer) may be sanctioned-skipped via this writer." >&2
  exit 1
fi

# Validation 3: upstream merge file exists + has fixer_skipped:true + reason matches.
if [[ ! -f "$UPSTREAM_MERGE_PATH" ]]; then
  echo "ERROR: write-skipped-fixer-trace.sh — upstream merge file not found: $UPSTREAM_MERGE_PATH" >&2
  exit 1
fi

UPSTREAM_VALIDATION=$(REASON="$REASON" UPSTREAM_PATH="$UPSTREAM_MERGE_PATH" python3 - <<'PYEOF'
import json, os, sys
path = os.environ['UPSTREAM_PATH']
expected_reason = os.environ['REASON']
try:
    d = json.load(open(path))
except (OSError, json.JSONDecodeError) as exc:
    print(f"FAIL:cannot parse {path}: {exc}")
    sys.exit(0)
if not isinstance(d, dict):
    print(f"FAIL:{path} is not a JSON object")
    sys.exit(0)
if d.get("fixer_skipped") is not True:
    print(f"FAIL:{path} does not have fixer_skipped:true (got {d.get('fixer_skipped')!r})")
    sys.exit(0)
if d.get("reason") != expected_reason:
    print(f"FAIL:{path} has reason={d.get('reason')!r}, expected {expected_reason!r}")
    sys.exit(0)
print("OK")
PYEOF
)

if [[ "$UPSTREAM_VALIDATION" != "OK" ]]; then
  echo "ERROR: write-skipped-fixer-trace.sh — upstream merge validation failed:" >&2
  echo "  ${UPSTREAM_VALIDATION#FAIL:}" >&2
  exit 1
fi

# AOC v1.2: validate source-identity flags before computing identity.
if [[ -n "$SOURCE_RUN_ID" || -n "$SOURCE_SKILL" ]]; then
  source "$(dirname "$0")/lib/source_identity_validator.sh"
  if ! validate_source_identity "$SOURCE_RUN_ID" "$SOURCE_SKILL" "$AGENT"; then
    echo "ERROR: write-skipped-fixer-trace.sh — source-identity validation failed (see above)" >&2
    exit 1
  fi
fi

# Resolve identity: prefer source flags (post-completion path), else active.
ACTIVE_SKILL=""
ACTIVE_RUN_ID=""
if [[ -n "$SOURCE_RUN_ID" && -n "$SOURCE_SKILL" ]]; then
  ACTIVE_SKILL="$SOURCE_SKILL"
  ACTIVE_RUN_ID="$SOURCE_RUN_ID"
else
  source "$PROJECT_DIR/.claude/hooks/lib.sh"
  ACTIVE_IDENTITY="$(resolve_active_identity 2>/dev/null || true)"
  if [[ -z "$ACTIVE_IDENTITY" ]]; then
    echo "ERROR: write-skipped-fixer-trace.sh — no active skill context on current branch" >&2
    echo "  Hint: under post-completion conditions, supply --source-run-id and --source-skill" >&2
    exit 1
  fi
  IFS=$'\t' read -r ACTIVE_SKILL ACTIVE_RUN_ID _ATTR _ANC <<< "$ACTIVE_IDENTITY"
  if [[ -z "$ACTIVE_RUN_ID" ]]; then
    echo "ERROR: write-skipped-fixer-trace.sh — active context has empty run_id" >&2
    exit 1
  fi
fi

# Compute unresolved_critical from the upstream merge file's `issues` array.
UNRESOLVED_CRITICAL=$(UPSTREAM_PATH="$UPSTREAM_MERGE_PATH" python3 - <<'PYEOF'
import json, os
path = os.environ['UPSTREAM_PATH']
d = json.load(open(path))
issues = d.get("issues") or []
critical_severities = {"critical", "high", "serious"}
count = 0
for it in issues:
    if not isinstance(it, dict):
        continue
    # Severity may be in `severity` (security shape) or `impact` (quality shape).
    sev = (it.get("severity") or it.get("impact") or "").lower()
    if sev in critical_severities:
        count += 1
print(count)
PYEOF
)

# Compose trace and write atomically.
TRACES_DIR="$PROJECT_DIR/.runs/agent-traces"
mkdir -p "$TRACES_DIR"
TARGET_TRACE="$TRACES_DIR/$AGENT.json"

# AOC v1.2 stub-protection (mirrors write-recovery-trace.sh:249-269 pattern).
# If the target trace already exists AND is NOT a stub (status:started + no
# verdict), REFUSE to overwrite. This prevents the failure mode where the
# fixer actually ran successfully (verdict:pass), wrote its trace, and
# then a buggy state-file or lead miscall re-invokes this writer — which
# would silently downgrade the pass to audit-only blocked, halting the
# pipeline on a false positive.
if [[ -f "$TARGET_TRACE" ]]; then
  TRACE_STATE=$(python3 -c "
import json, sys
try:
    t = json.load(open('$TARGET_TRACE'))
except Exception as e:
    print('READ_ERROR'); sys.exit(0)
status = t.get('status', '')
verdict = t.get('verdict')
provenance = t.get('provenance', '')
# Already lead-skipped: idempotent overwrite is OK (re-run safety).
if provenance == 'lead-skipped':
    print('SKIP_OK')
elif status == 'started' and not verdict:
    print('STUB')
else:
    print(f'NON_STUB:status={status},verdict={verdict},provenance={provenance}')
" 2>/dev/null)
  case "$TRACE_STATE" in
    STUB|SKIP_OK) ;;  # safe to (re)write
    READ_ERROR)
      echo "WARN: write-skipped-fixer-trace.sh — existing trace at $TARGET_TRACE is unreadable; overwriting." >&2
      ;;
    NON_STUB:*)
      echo "ERROR: write-skipped-fixer-trace.sh — REFUSE to overwrite non-stub trace at $TARGET_TRACE" >&2
      echo "  Existing trace state: ${TRACE_STATE#NON_STUB:}" >&2
      echo "  This writer is for sanctioned-skip ONLY — when the fixer was" >&2
      echo "  blocked from spawning by an upstream gate. If the fixer DID" >&2
      echo "  run and wrote a real trace, calling this writer would silently" >&2
      echo "  downgrade verdict=pass to verdict=blocked + result=skipped," >&2
      echo "  halting the pipeline on a false positive. Investigate the" >&2
      echo "  caller — likely a state-file branch error or duplicate invocation." >&2
      exit 1
      ;;
  esac
fi

AGENT_ENV="$AGENT" \
SKILL_ENV="$ACTIVE_SKILL" \
RUN_ID_ENV="$ACTIVE_RUN_ID" \
REASON_ENV="$REASON" \
UPSTREAM_PATH_ENV="$UPSTREAM_MERGE_PATH" \
UNRESOLVED_ENV="$UNRESOLVED_CRITICAL" \
TARGET_ENV="$TARGET_TRACE" \
SOURCE_RUN_ID_ENV="$SOURCE_RUN_ID" \
SOURCE_SKILL_ENV="$SOURCE_SKILL" \
python3 - <<'PYEOF'
import json, os, datetime, tempfile

trace = {
    "agent": os.environ["AGENT_ENV"],
    "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "status": "completed",
    # AOC v1.2: audit-only sanctioned-skip shape. verdict=blocked is in AVS v1
    # core ({pass,fail,blocked,unresolved}); result=skipped is the qualifier
    # (added to fixer allowed_results by PR1 A1.3 + PR6 lint-driven correction).
    # Semantic: "fixer was blocked from spawning by upstream gate". No pass_*
    # predicate accepts verdict=blocked, so the hard gate blocks naturally.
    # ux-journeyer already uses verdict=blocked as a block-condition; precedent.
    "verdict": "blocked",
    "result": "skipped",
    "provenance": "lead-skipped",
    "lead_attestation": True,
    "partial": True,
    "checks_performed": [],
    "fixes": [],
    "no_fixes_claimed": True,
    "upstream_evidence_path": os.environ["UPSTREAM_PATH_ENV"],
    "reason": os.environ["REASON_ENV"],
    "unresolved_critical": int(os.environ["UNRESOLVED_ENV"]),
    "run_id": os.environ["RUN_ID_ENV"],
    "skill": os.environ["SKILL_ENV"],
    # No spawn_sha — the agent was never spawned. The lead-skipped exemption
    # in state-completion-gate.sh accepts the absent spawn-log entry given
    # the upstream_evidence_path proves the upstream gate fired.
    "spawn_sha": "",
    "spawn_index": None,
}

# AOC v1.2: stamp source identity if supplied (post-completion path).
src_run_id = os.environ.get("SOURCE_RUN_ID_ENV", "")
src_skill = os.environ.get("SOURCE_SKILL_ENV", "")
if src_run_id and src_skill:
    trace["source_run_id"] = src_run_id
    trace["source_skill"] = src_skill

# Atomic write via tempfile + rename.
target = os.environ["TARGET_ENV"]
target_dir = os.path.dirname(target)
fd, tmp_path = tempfile.mkstemp(prefix=".write-skipped-fixer-trace-", dir=target_dir)
try:
    with os.fdopen(fd, "w") as f:
        json.dump(trace, f, indent=2)
        f.write("\n")
    os.rename(tmp_path, target)
except Exception:
    try:
        os.unlink(tmp_path)
    except OSError:
        pass
    raise
PYEOF

echo "Sanctioned-skip trace written: $TARGET_TRACE" >&2
echo "  agent: $AGENT" >&2
echo "  reason: $REASON" >&2
echo "  upstream: $UPSTREAM_MERGE_PATH" >&2
echo "  unresolved_critical: $UNRESOLVED_CRITICAL" >&2
echo "  AOC v1.2: AUDIT-ONLY — no pass_* predicate matches verdict=skipped." >&2
echo "  Hard gate will continue to block; this trace exists for observability." >&2
