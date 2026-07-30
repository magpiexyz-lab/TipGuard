#!/usr/bin/env bash
# design-consistency-checker.sh — Convention gate for design-consistency-checker in /verify.
# Extracted from agent-state-gate.sh _verify_consistency_checker_checks().
set -euo pipefail

source "$(dirname "$0")/../../../hooks/lib.sh"

if [[ -z "${PAYLOAD:-}" ]]; then parse_payload; fi
PROJECT_DIR="${PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-.}}"
TRACES_DIR="${TRACES_DIR:-$PROJECT_DIR/.runs/agent-traces}"
ERRORS=()

check_postcondition_artifacts 0
check_build_result

# Check if any per-page design-critic traces have unresolved shared-component issues
HAS_SHARED=$(python3 -c "
import json, glob
for f in glob.glob('$TRACES_DIR/design-critic-*.json'):
    if 'design-critic-shared' in f: continue
    try:
        d = json.load(open(f))
        if d.get('unresolved_shared', 0) > 0:
            print('yes'); break
    except: pass
else: print('no')
" 2>/dev/null || echo "no")

if [[ "$HAS_SHARED" == "yes" ]]; then
  # Check if all shared issues are for claimed components (handled by per-page claiming agents)
  ALL_CLAIMED=$(python3 -c "
import json, glob, os
claims = {}
try: claims = json.load(open('$PROJECT_DIR/.runs/design-claims.json')).get('claims', {})
except: pass
if not claims:
    print('no'); exit()
for f in glob.glob('$TRACES_DIR/design-critic-*.json'):
    if 'design-critic-shared' in f: continue
    try:
        d = json.load(open(f))
        for si in d.get('shared_issues', []):
            if si.get('file','') not in claims:
                print('no'); exit()
    except: pass
print('yes')
" 2>/dev/null || echo "no")
  if [[ "$ALL_CLAIMED" != "yes" ]]; then
    if [[ ! -f "$TRACES_DIR/design-critic-shared.json" ]]; then
      ERRORS+=("design-critic-shared.json missing — per-page agents reported shared-component issues for unclaimed components")
    else
      require_trace_verdict "$TRACES_DIR/design-critic-shared.json" "shared-component agent may still be running"
    fi
  fi
fi

if [[ ${#ERRORS[@]} -gt 0 ]]; then
  deny_errors "design-consistency-checker gate blocked: " "Complete prerequisites before spawning consistency checker."
fi

exit 0
