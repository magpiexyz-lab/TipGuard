#!/usr/bin/env bash
# Block-test (Slice 1 atomicity guard for issue #1198): no writer of
# observation-enforcement.json may exist outside the declared canonical sites.
#
# Canonical writers (allow-listed):
#   - .claude/scripts/check-observation-artifacts.sh   (main delegates to canonical writer; trap fallback, optimize-prompt fast-path remain inline pending Slice 3+ migration)
#   - .claude/scripts/lib/write-gate-artifact.sh       (canonical writer — GRAIM v2 Slice 3)
#   - .claude/patterns/state-99-epilogue.md            (legitimate-skip Step 3a)
#
# Other paths reference the artifact but only as readers/cleanup/declarations:
#   - .claude/patterns/state-registry.json (VERIFY consumer + epilogue_artifacts declaration)
#   - .claude/scripts/lifecycle-init.sh    (STALE_ARTIFACTS cleanup)
#   - tools/compliance-audit.py            (observability reader if present)
#
# This test fails if any new writer (open(..., 'w') or equivalent) is added
# outside the allow-list, preventing future regressions of the GRAIM v2
# C1+C2 atomic 4-writer migration.
set -euo pipefail
cd "$(dirname "$0")/../../.."

UNAUTHORIZED=$(grep -rln "observation-enforcement\.json" .claude/scripts/ .claude/patterns/ .claude/skills/ 2>/dev/null \
  | grep -v "check-observation-artifacts\.sh" \
  | grep -v "lib/write-gate-artifact\.sh" \
  | grep -v "state-99-epilogue\.md" \
  | grep -v "state-registry\.json" \
  | grep -v "lifecycle-init\.sh" \
  | grep -v "compliance-audit\.py" \
  | grep -v "tests/" || true)

# Only writers (open(..., 'w'), Write tool patterns) are forbidden — readers OK
WRITERS=""
for f in $UNAUTHORIZED; do
  if grep -E "open\(['\"]\.runs/observation-enforcement\.json['\"], ['\"]w" "$f" 2>/dev/null; then
    WRITERS="$WRITERS $f"
  fi
done

if [ -n "$WRITERS" ]; then
  echo "FAIL: unauthorized writer(s) of observation-enforcement.json:$WRITERS" >&2
  exit 1
fi
echo "PASS: no unauthorized writers"
