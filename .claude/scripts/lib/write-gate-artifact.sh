#!/usr/bin/env bash
# write-gate-artifact.sh — canonical writer for gate-readable .runs/*.json artifacts.
# GRAIM v2 C1 (Identity Stamping): every gate-readable artifact MUST carry
# {skill, run_id, written_at}. This writer stamps those fields from the active
# context resolved via .claude/hooks/lib.sh::resolve_active_identity.
#
# Caller may pass --skill <override> to trump resolved identity (mirrors
# state-completion-gate.sh:79-91 pattern for embed scenarios where the
# caller-passed skill is authoritative). Mismatch warns but does not block.
#
# Migration target paths are listed in:
#   .claude/patterns/gate-readable-artifacts-canonical.json
# Each migration is its own commit/PR per the GRAIM v2 plan (Slice 3).
#
# Usage:
#   bash .claude/scripts/lib/write-gate-artifact.sh \
#     --path .runs/foo.json \
#     --payload '{"pass": true, "missing": []}' \
#     [--skill <override>]
#
# The --payload JSON is merged with the auto-stamped {skill, run_id, written_at}
# fields. Caller-provided fields in --payload take precedence ONLY for fields
# OTHER than skill/run_id (those are protected — caller can override skill via
# --skill, but cannot inject conflicting run_id).

set -euo pipefail

ARTIFACT_PATH=""
PAYLOAD_JSON="{}"
OVERRIDE_SKILL=""
# AOC v1.2: post-completion identity override.
SOURCE_RUN_ID=""
SOURCE_SKILL=""

while [ $# -gt 0 ]; do
  case "$1" in
    --path)          ARTIFACT_PATH="$2"; shift 2 ;;
    --payload)       PAYLOAD_JSON="$2"; shift 2 ;;
    --skill)         OVERRIDE_SKILL="$2"; shift 2 ;;
    --source-run-id) SOURCE_RUN_ID="$2"; shift 2 ;;
    --source-skill)  SOURCE_SKILL="$2"; shift 2 ;;
    *) echo "ERROR: unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$ARTIFACT_PATH" ]; then
  echo "ERROR: write-gate-artifact: --path required" >&2
  exit 2
fi

# AOC v1.2: validate source-identity flags (R1 xor + R2 context-existence).
# R3 spawn-log doesn't apply (this writer isn't agent-specific).
# R4 same-skill forgery doesn't apply when active identity is empty (the
# typical post-completion trigger).
if [ -n "$SOURCE_RUN_ID" ] || [ -n "$SOURCE_SKILL" ]; then
  source "$(dirname "$0")/source_identity_validator.sh"
  if ! validate_source_identity "$SOURCE_RUN_ID" "$SOURCE_SKILL" ""; then
    echo "ERROR: write-gate-artifact: source-identity validation failed (see above)" >&2
    exit 1
  fi
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
cd "$PROJECT_DIR"

# AOC v1.2: source flags take precedence over resolve_active_identity (the
# explicit post-completion path). Validator already enforced R1-R4 above.
if [ -n "$SOURCE_RUN_ID" ] && [ -n "$SOURCE_SKILL" ]; then
  ACTIVE_SKILL="$SOURCE_SKILL"
  ACTIVE_RUN_ID="$SOURCE_RUN_ID"
else
  # Resolve active identity (single source of truth).
  ACTIVE_IDENTITY="$(bash -c 'source .claude/hooks/lib.sh && resolve_active_identity' 2>/dev/null || true)"
  RESOLVED_SKILL=""
  ACTIVE_RUN_ID=""
  if [ -n "$ACTIVE_IDENTITY" ]; then
    IFS=$'\t' read -r RESOLVED_SKILL ACTIVE_RUN_ID _ATTR _ANC <<< "$ACTIVE_IDENTITY"
  fi

  # Caller --skill trumps; cross-check warns on mismatch
  ACTIVE_SKILL="${OVERRIDE_SKILL:-$RESOLVED_SKILL}"
  if [ -n "$RESOLVED_SKILL" ] && [ -n "$OVERRIDE_SKILL" ] && [ "$RESOLVED_SKILL" != "$OVERRIDE_SKILL" ]; then
    echo "WARN: write-gate-artifact: caller-skill='$OVERRIDE_SKILL' but resolve_active_identity returned '$RESOLVED_SKILL' — possible stale context" >&2
  fi

  if [ -z "$ACTIVE_SKILL" ]; then
    echo "ERROR: write-gate-artifact: cannot determine active skill (caller did not pass --skill and resolve_active_identity returned empty)" >&2
    echo "  Hint (AOC v1.2): under post-completion conditions, supply --source-run-id and --source-skill." >&2
    exit 1
  fi
  if [ -z "$ACTIVE_RUN_ID" ]; then
    # If caller passed --skill, try to derive run_id from .runs/<skill>-context.json
    if [ -n "$OVERRIDE_SKILL" ] && [ -f ".runs/${OVERRIDE_SKILL}-context.json" ]; then
      ACTIVE_RUN_ID=$(python3 -c "import json,sys;print(json.load(open('.runs/${OVERRIDE_SKILL}-context.json')).get('run_id',''))" 2>/dev/null || echo "")
    fi
  fi
  if [ -z "$ACTIVE_RUN_ID" ]; then
    echo "ERROR: write-gate-artifact: cannot determine active run_id" >&2
    exit 1
  fi
fi

# Stamp identity onto payload and write atomically
mkdir -p "$(dirname "$ARTIFACT_PATH")"
ARTIFACT_PATH_ENV="$ARTIFACT_PATH" \
PAYLOAD_JSON_ENV="$PAYLOAD_JSON" \
ACTIVE_SKILL_ENV="$ACTIVE_SKILL" \
ACTIVE_RUN_ID_ENV="$ACTIVE_RUN_ID" \
python3 <<'PYEOF'
import json, datetime, os
payload = json.loads(os.environ['PAYLOAD_JSON_ENV'])
# Caller payload may carry its own skill/run_id; canonical writer overrides them.
payload['skill'] = os.environ['ACTIVE_SKILL_ENV']
payload['run_id'] = os.environ['ACTIVE_RUN_ID_ENV']
payload['written_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
with open(os.environ['ARTIFACT_PATH_ENV'], 'w') as f:
    json.dump(payload, f, indent=2)
    f.write('\n')
PYEOF
