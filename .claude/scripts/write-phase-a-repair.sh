#!/usr/bin/env bash
# write-phase-a-repair.sh — EARC Half II canonical repair writer (slice 3).
#
# Closes the residual half of #1182. When state-11's build self-check (slice
# 2) passed but a Phase A file later breaks (post-seal regression, runtime-
# only failure invisible to npm run build, upstream dependency drift), the
# lead can repair the file via this writer:
#
#   * Validates external evidence (build-result.json shows the build was
#     actually failing — defends against gratuitous repairs).
#   * Performs the file write atomically.
#   * Stamps a lead-fix trace via write-agent-trace.sh --provenance lead-fix.
#   * Writes an attestation artifact at
#     .runs/phase-a-repair-attestations/<file-basename>-<ts>.json
#     that bootstrap/gates/write.sh reads to ALSO-ALLOW the write.
#
# Usage:
#   echo '<new file content>' | bash .claude/scripts/write-phase-a-repair.sh \
#     --target-file src/app/layout.tsx \
#     --evidence-source .runs/build-result.json \
#     --symptom "next/font config rejects weight + axes together" \
#     --lead-attestation "removed weight key, kept axes — minimal diff"
#
# Allowed targets are exactly the four files protected by the Phase A gate:
#   src/app/layout.tsx, src/app/not-found.tsx, src/app/error.tsx,
#   src/app/globals.css.
#
# Exit codes:
#   0 — file written, attestation + lead-fix trace stamped
#   1 — input or precondition error
#   2 — evidence validation failed
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

TARGET_FILE=""
EVIDENCE_SOURCE=""
LEAD_ATTESTATION=""
SYMPTOM=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target-file)        TARGET_FILE="${2:-}"; shift 2 ;;
    --target-file=*)      TARGET_FILE="${1#--target-file=}"; shift ;;
    --evidence-source)    EVIDENCE_SOURCE="${2:-}"; shift 2 ;;
    --evidence-source=*)  EVIDENCE_SOURCE="${1#--evidence-source=}"; shift ;;
    --lead-attestation)   LEAD_ATTESTATION="${2:-}"; shift 2 ;;
    --lead-attestation=*) LEAD_ATTESTATION="${1#--lead-attestation=}"; shift ;;
    --symptom)            SYMPTOM="${2:-}"; shift 2 ;;
    --symptom=*)          SYMPTOM="${1#--symptom=}"; shift ;;
    -h|--help)
      sed -n '/^# /,/^set -e/{/^set -e/!p;}' "$0" | sed 's/^# \?//' >&2
      exit 0 ;;
    *)
      echo "ERROR: write-phase-a-repair.sh — unknown flag: $1" >&2
      exit 1 ;;
  esac
done

# Required args. Explicit per-flag check — original code used the bash-4-only
# lower-casing parameter expansion ("dollar brace var comma comma") which
# produced --target_file (underscore) instead of --target-file. Description
# spelled out to keep this script bash-3.2-compatible (consistency-check
# Check 25 flags the literal token even inside a comment).
[[ -n "$TARGET_FILE" ]]      || { echo "ERROR: write-phase-a-repair.sh — --target-file is required" >&2; exit 1; }
[[ -n "$EVIDENCE_SOURCE" ]]  || { echo "ERROR: write-phase-a-repair.sh — --evidence-source is required" >&2; exit 1; }
[[ -n "$LEAD_ATTESTATION" ]] || { echo "ERROR: write-phase-a-repair.sh — --lead-attestation is required" >&2; exit 1; }
[[ -n "$SYMPTOM" ]]          || { echo "ERROR: write-phase-a-repair.sh — --symptom is required" >&2; exit 1; }

# Allowed targets — must match the four files protected by bootstrap/gates/write.sh.
case "$TARGET_FILE" in
  src/app/layout.tsx|src/app/not-found.tsx|src/app/error.tsx|src/app/globals.css)
    ;;
  *)
    echo "ERROR: write-phase-a-repair.sh — --target-file must be one of:" >&2
    echo "       src/app/layout.tsx, src/app/not-found.tsx, src/app/error.tsx, src/app/globals.css" >&2
    echo "       (got: $TARGET_FILE)" >&2
    exit 1 ;;
esac

# Resolve project dir (worktree-aware via lib-core.sh).
LIB_CORE="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || echo .)}/.claude/hooks/lib-core.sh"
# shellcheck disable=SC1090
[[ -f "$LIB_CORE" ]] && source "$LIB_CORE"
if declare -f get_project_dir >/dev/null 2>&1; then
  PROJECT_DIR="$(get_project_dir)"
else
  PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || echo .)}"
fi

EVIDENCE_PATH="$EVIDENCE_SOURCE"
if [[ "$EVIDENCE_PATH" != /* ]]; then
  EVIDENCE_PATH="$PROJECT_DIR/$EVIDENCE_PATH"
fi

if [[ ! -f "$EVIDENCE_PATH" ]]; then
  echo "ERROR: write-phase-a-repair.sh — evidence file not found: $EVIDENCE_SOURCE" >&2
  exit 2
fi

# Validate evidence: build-result.json must show the build is currently failing
# (else the repair is gratuitous), AND the evidence must be fresh + on HEAD.
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EVIDENCE_PATH_ENV="$EVIDENCE_PATH" PROJECT_DIR_ENV="$PROJECT_DIR" TS_ENV="$TS" python3 - <<'PYEOF'
import json, os, sys
sys.path.insert(0, os.path.join(os.environ['PROJECT_DIR_ENV'], '.claude', 'scripts'))
from lib.validate_evidence import validate_build_evidence

ev = os.environ['EVIDENCE_PATH_ENV']
project = os.environ['PROJECT_DIR_ENV']
ts = os.environ['TS_ENV']

# Freshness + commit_sha check (when recorded).
ok, errors = validate_build_evidence(ev, trace_timestamp=ts, project_dir=project)
# We INVERT one piece of the check: build_evidence treats exit_code != 0 as
# an error (build failing); for the repair-justification check, exit_code != 0
# is what we WANT (the build IS failing — that's why we're repairing).
# So: walk errors and discard the "exit_code=N (need 0)" message; treat any
# OTHER error as a real validation failure.
real_errors = [e for e in errors if 'exit_code=' not in e]
# Additionally, REQUIRE that exit_code is non-zero (build failing); otherwise
# the repair is unjustified.
try:
    br = json.load(open(ev))
    if br.get('exit_code') == 0:
        sys.stderr.write(
            f'ERROR: write-phase-a-repair.sh — evidence shows build PASSING (exit_code=0); '
            f'repair is not justified. If the failure is runtime-only, capture it in a different '
            f'evidence file (e.g., e2e-result.json or a runtime-error log) and point --evidence-source there.\n'
        )
        sys.exit(2)
except Exception as exc:
    real_errors.append(f'evidence file unreadable: {exc}')

if real_errors:
    sys.stderr.write('ERROR: write-phase-a-repair.sh — evidence validation failed:\n')
    for e in real_errors:
        sys.stderr.write(f'  - {e}\n')
    sys.exit(2)
PYEOF

# Read new content from stdin.
if [[ -t 0 ]]; then
  echo "ERROR: write-phase-a-repair.sh — file content must be piped via stdin" >&2
  echo "  Example: cat new-layout.tsx | bash write-phase-a-repair.sh ..." >&2
  exit 1
fi
NEW_CONTENT="$(cat)"
if [[ -z "$NEW_CONTENT" ]]; then
  echo "ERROR: write-phase-a-repair.sh — empty stdin (no new file content provided)" >&2
  exit 1
fi

# Atomic write.
TARGET_FULL="$PROJECT_DIR/$TARGET_FILE"
mkdir -p "$(dirname "$TARGET_FULL")"
TMP="$(mktemp "${TARGET_FULL}.XXXXXX")"
printf '%s' "$NEW_CONTENT" > "$TMP"
# Save a copy of the prior content so the post-condition check can revert
# if the repair makes things worse (e.g., new build still fails).
PRIOR_CONTENT_PATH=""
if [[ -f "$TARGET_FULL" ]]; then
  PRIOR_CONTENT_PATH="$(mktemp "${TARGET_FULL}.prior.XXXXXX")"
  cp "$TARGET_FULL" "$PRIOR_CONTENT_PATH"
fi
mv "$TMP" "$TARGET_FULL"

# POST-REPAIR build verification — first-principles fix.
#
# The pre-repair evidence check confirms the build was failing (justifying
# the repair). But that doesn't guarantee the repair WORKS — the lead could
# write a still-broken file, and the attestation would falsely claim
# "evidence_validated:true" with the gate ALSO-ALLOWing a still-broken state.
# That's exactly the #1182 failure mode (broken Phase A escapes into the
# sealed window) shifted by one layer.
#
# Skip when --skip-post-build is set (test fixtures, dry runs); the flag
# requires an explicit acknowledgement so production paths can't silently
# skip the check.
if [[ "${WRITE_PHASE_A_REPAIR_SKIP_POST_BUILD:-0}" != "1" ]]; then
  echo "write-phase-a-repair.sh: running post-repair build verification..." >&2
  POST_BUILD_LOG="$(mktemp /tmp/phase-a-repair-postbuild.XXXXXX.log)"
  if ! ( cd "$PROJECT_DIR" && npm run build > "$POST_BUILD_LOG" 2>&1 ); then
    echo "ERROR: write-phase-a-repair.sh — POST-repair build still failing." >&2
    echo "       Reverting $TARGET_FILE and refusing to stamp the attestation." >&2
    echo "       --- npm run build (tail) ---" >&2
    tail -30 "$POST_BUILD_LOG" >&2
    if [[ -n "$PRIOR_CONTENT_PATH" && -f "$PRIOR_CONTENT_PATH" ]]; then
      mv "$PRIOR_CONTENT_PATH" "$TARGET_FULL"
    fi
    rm -f "$POST_BUILD_LOG"
    exit 2
  fi
  rm -f "$POST_BUILD_LOG"
  echo "write-phase-a-repair.sh: post-repair build PASSED." >&2
fi
# Repair confirmed effective; remove the prior-content backup.
[[ -n "$PRIOR_CONTENT_PATH" && -f "$PRIOR_CONTENT_PATH" ]] && rm -f "$PRIOR_CONTENT_PATH"

# Write attestation artifact (bootstrap/gates/write.sh reads this for ALSO-ALLOW).
ATTEST_DIR="$PROJECT_DIR/.runs/phase-a-repair-attestations"
mkdir -p "$ATTEST_DIR"
BASENAME="$(basename "$TARGET_FILE")"
ATTEST_PATH="$ATTEST_DIR/${BASENAME}-${TS}.json"
COMMIT_SHA="$(git -C "$PROJECT_DIR" rev-parse HEAD 2>/dev/null || echo "")"

POST_BUILD_SKIPPED="${WRITE_PHASE_A_REPAIR_SKIP_POST_BUILD:-0}"
ATTEST_PATH_ENV="$ATTEST_PATH" \
TARGET_FILE_ENV="$TARGET_FILE" \
EVIDENCE_SOURCE_ENV="$EVIDENCE_SOURCE" \
LEAD_ATTESTATION_ENV="$LEAD_ATTESTATION" \
SYMPTOM_ENV="$SYMPTOM" \
COMMIT_SHA_ENV="$COMMIT_SHA" \
TS_ENV="$TS" \
POST_BUILD_SKIPPED_ENV="$POST_BUILD_SKIPPED" \
python3 - <<'PYEOF'
import json, os
attest = {
    'target_file':              os.environ['TARGET_FILE_ENV'],
    'evidence_source':          os.environ['EVIDENCE_SOURCE_ENV'],
    'evidence_validated':       True,
    # post_repair_build_passing is the post-condition the lead now owes the
    # gate. 'true' iff `npm run build` succeeded after the file was written;
    # 'skipped' only when WRITE_PHASE_A_REPAIR_SKIP_POST_BUILD=1 (test mode).
    # The gate (bootstrap/gates/write.sh) reads this field; downstream PRs
    # may add a stricter ALSO-ALLOW that requires post_repair_build_passing
    # == 'true' to deflect skipped attestations from production.
    'post_repair_build_passing': 'skipped' if os.environ['POST_BUILD_SKIPPED_ENV'] == '1' else True,
    'lead_attestation':         os.environ['LEAD_ATTESTATION_ENV'],
    'symptom':                  os.environ['SYMPTOM_ENV'],
    'commit_sha_before':        os.environ['COMMIT_SHA_ENV'],
    'timestamp':                os.environ['TS_ENV'],
    'writer':                   'write-phase-a-repair.sh',
}
json.dump(attest, open(os.environ['ATTEST_PATH_ENV'], 'w'), indent=2)
PYEOF

# Stamp lead-fix in the lead's trace via write-agent-trace.sh.
SKILL=$(python3 -c "
import glob, json, os
for f in sorted(glob.glob(os.path.join(os.environ.get('CLAUDE_PROJECT_DIR', '.'), '.runs/*-context.json')), reverse=True):
    if 'epilogue' in os.path.basename(f):
        continue
    try:
        d = json.load(open(f))
    except Exception:
        continue
    if not d.get('completed'):
        print(d.get('skill', ''))
        break
" 2>/dev/null || echo "bootstrap")
[[ -n "$SKILL" ]] || SKILL="bootstrap"

# Build the trace JSON. Lead-fix requires non-empty fixes[] with file/symptom/fix.
# NOTE: `VAR=val FOO=$(cmd)` does NOT pass VAR to cmd — bash applies env-vars
# only to direct command invocations, not to the assignment. The env-vars
# must be set INSIDE the $(...) subshell, or exported, or passed via env.
TRACE_JSON=$(
  TRACE_JSON_ENV_TARGET="$TARGET_FILE" \
  TRACE_JSON_ENV_SYM="$SYMPTOM" \
  TRACE_JSON_ENV_FIX="$LEAD_ATTESTATION" \
  python3 -c "
import json, os
print(json.dumps({
    'verdict': 'pass',
    'result': 'fixed',
    'partial': True,
    'fixes': [{
        'file': os.environ['TRACE_JSON_ENV_TARGET'],
        'symptom': os.environ['TRACE_JSON_ENV_SYM'],
        'fix': os.environ['TRACE_JSON_ENV_FIX'],
    }],
    'checks_performed': ['earc-phase-a-repair'],
}))
"
)

# Note: write-agent-trace.sh requires an active skill context. lead-fix does
# NOT require a spawn-log entry (lead has direct knowledge). The trace agent
# name is "lead-<skill>" by convention — matches the existing FLS v1 lead-fix
# pattern in write-fix-ledger.py.
#
# Soft-fail if the trace can't be stamped (e.g., no active context on current
# branch). The ATTESTATION is the critical artifact for the gate; the
# lead-fix trace is downstream telemetry for Q-score / pattern-classifier.
# Without the trace, observability is reduced but the contract (gate
# ALSO-ALLOW + audit-trail of the repair) still holds via the attestation.
TRACE_AGENT="lead-${SKILL}"
TRACE_PATH=".runs/agent-traces/${TRACE_AGENT}-phase-a-repair.json"
TRACE_STATUS="ok"
if ! bash "$SCRIPT_DIR/write-agent-trace.sh" "$TRACE_AGENT" \
       --provenance lead-fix \
       --lead-attestation true \
       --trace-filename "${TRACE_AGENT}-phase-a-repair.json" \
       --json "$TRACE_JSON" 2> /tmp/phase-a-repair-trace.err; then
  TRACE_STATUS="skipped"
  echo "WARN: write-phase-a-repair.sh — could not stamp lead-fix trace; attestation still written." >&2
  echo "  Reason: $(cat /tmp/phase-a-repair-trace.err 2>/dev/null | head -1)" >&2
  rm -f /tmp/phase-a-repair-trace.err
  TRACE_PATH=""
fi

echo "Phase A repair complete:"
echo "  target:          $TARGET_FILE"
echo "  attestation:     $ATTEST_PATH"
if [[ "$TRACE_STATUS" == "ok" ]]; then
  echo "  lead-fix trace:  $TRACE_PATH"
else
  echo "  lead-fix trace:  (skipped — see WARN above)"
fi
