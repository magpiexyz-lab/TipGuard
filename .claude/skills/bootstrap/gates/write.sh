#!/usr/bin/env bash
# write.sh — Convention gate for /bootstrap write protection.
# Blocks writes to protected root files during bootstrap Phase B.
# Protected files: layout.tsx, not-found.tsx, error.tsx, globals.css
#
# Extracted from bootstrap-root-protection.sh (bootstrap-specific logic only).
# Called by: skill-write-gate.sh (PR 5) after framework checks pass.
# NOT called yet — created in PR 4c, enabled in PR 5.
set -euo pipefail

source "$(dirname "$0")/../../../hooks/lib.sh"

# Accept env vars (convention gate protocol)
FILE_PATH="${FILE_PATH:-}"
PROJECT_DIR="${PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-.}}"

# Only care about protected root files
case "$FILE_PATH" in
  */src/app/layout.tsx|*/src/app/not-found.tsx|*/src/app/error.tsx|*/src/app/globals.css)
    ;;
  *)
    exit 0
    ;;
esac

VERDICTS_DIR="$PROJECT_DIR/.runs/gate-verdicts"

# Phase B detection: BG1 PASS + BG2 absent + phase-a-sentinel present
if [[ ! -f "$VERDICTS_DIR/bg1.json" ]]; then exit 0; fi

BG1_VERDICT=$(read_json_field "$VERDICTS_DIR/bg1.json" "verdict")
if [[ "$BG1_VERDICT" != "PASS" ]]; then exit 0; fi

# If BG2 already exists, Phase B is over — allow
if [[ -f "$VERDICTS_DIR/bg2.json" ]]; then exit 0; fi

# If Phase A sentinel doesn't exist, Phase A hasn't completed — allow
if [[ ! -f "$VERDICTS_DIR/phase-a-sentinel.json" ]]; then exit 0; fi

# All conditions met: Phase B, root files are protected.
# EARC slice 3 (closes #1182 residual): before denying, check for a fresh
# repair attestation written by .claude/scripts/write-phase-a-repair.sh.
# When present, the gate ALSO-ALLOWs the write — the attestation proves the
# lead validated external evidence (build-result.json showing the build was
# failing) and stamped a lead-fix trace. This closes the bypass motivation
# (#1182's `python -c` shell write) by giving the lead a legal repair path
# for residual cases not caught by state-11's seal-time self-check (slice 2).
BASENAME=$(basename "$FILE_PATH")
ATTEST_DIR="$PROJECT_DIR/.runs/phase-a-repair-attestations"
if [[ -d "$ATTEST_DIR" ]]; then
  # Find the newest attestation matching this file basename.
  LATEST=""
  for f in "$ATTEST_DIR/${BASENAME}-"*.json; do
    [[ -f "$f" ]] || continue
    LATEST="$f"
  done
  if [[ -n "$LATEST" ]]; then
    # Attestation freshness: within last 5 minutes (matches the validate-
    # evidence library's max_age_seconds default; covers an active repair
    # session without letting stale attestations linger).
    if [[ -f "$LATEST" ]]; then
      NOW=$(date +%s)
      # Linux first: `stat -c %Y` succeeds and exits 0. macOS lacks `-c`, so it
      # fails (silently) and the `-f %m` fallback runs. The reverse order would
      # silently corrupt the captured value on Linux because `stat -f %m FILE`
      # there interprets `%m` as a file arg (no such file) AND continues to
      # stat FILE, so it exits 1 BUT also writes garbage to stdout, which the
      # `||` shell still appends to the captured value, producing
      # multi-line output that crashes the next `$((...))` expansion under
      # `set -u` with a "File: unbound variable" error.
      ATTEST_MTIME=$(stat -c %Y "$LATEST" 2>/dev/null || stat -f %m "$LATEST" 2>/dev/null)
      if [[ -n "$ATTEST_MTIME" ]]; then
        AGE=$((NOW - ATTEST_MTIME))
        if (( AGE <= 300 )); then
          # Verify attestation has evidence_validated:true.
          EV_OK=$(python3 -c "import json,sys; d=json.load(open('$LATEST')); print('1' if d.get('evidence_validated') is True else '0')" 2>/dev/null || echo "0")
          if [[ "$EV_OK" == "1" ]]; then
            # ALSO-ALLOW path — fresh, validated EARC attestation present.
            exit 0
          fi
        fi
      fi
    fi
  fi
fi

deny "Bootstrap root protection: '$BASENAME' is a Phase A file and cannot be modified during Phase B. These files were created by the lead before fan-out and must not be overwritten by subagents. To repair Phase A files with external evidence (build-result.json showing the build is failing), use: bash .claude/scripts/write-phase-a-repair.sh --target-file <path> --evidence-source <path> --symptom '<description>' --lead-attestation '<rationale>' < new-content. The gate ALSO-ALLOWs writes when a fresh attestation (within 5 min, evidence_validated:true) exists at .runs/phase-a-repair-attestations/."
