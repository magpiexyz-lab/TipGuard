#!/usr/bin/env bash
# no-pii-in-fakedoor-track-call.sh — recurrence guard for issue #1326.
#
# Asserts no `email` (or other PII) property appears inside any
# `track("activate", ...)` call across template-owned files (.claude/) AND
# project-owned files (src/). Catches:
#   1. Template-side recurrence (a future stack-file edit re-introducing the shape).
#   2. Downstream-MVP migration debt (projects that bootstrapped FakeDoor pre-fix
#      and have stale src/app/<page>/<component>.tsx with the old shape;
#      /upgrade does not auto-update project-owned files).
#
# Wired into lifecycle-finalize.sh Step 4.5b; non-zero exit BLOCKS delivery.
# Also runnable standalone for downstream /verify or manual audit.

set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
cd "$REPO_ROOT"

# PII property names to scan for inside track("activate", ...) calls.
# Adding entries here extends the guard.
PII_PATTERNS=(
  '\bemail\b'
  '\bphone\b'
  '\bphone_number\b'
  # Note: "name" is not included because of false-positive risk
  # ({ action: "feature-name" } would falsely match). Re-add with a
  # tighter regex if a real PII name leak is discovered.
)

# Search corpus.
SEARCH_DIRS=(
  ".claude/stacks"
  ".claude/procedures"
  ".claude/skills"
  ".claude/agents"
  ".claude/templates"
  "src"   # project-owned in downstream MVPs (template repo: empty)
)

FOUND=0
for dir in "${SEARCH_DIRS[@]}"; do
  [ -d "$dir" ] || continue
  for pii in "${PII_PATTERNS[@]}"; do
    # Match: track("activate", { ... <pii> ... })
    # Allowlist: lines that explicitly opt-in via the `pii-in-track-allowlist:`
    # magic marker (for legitimate anti-pattern documentation). Note: the
    # smoke test's own file is at .claude/scripts/tests/ which is not in
    # SEARCH_DIRS, so a filename-based skip is unnecessary.
    HITS=$(grep -rEn "track\([\"']activate[\"'][^)]*${pii}" "$dir" 2>/dev/null \
      | grep -v 'pii-in-track-allowlist:' \
      || true)
    if [ -n "$HITS" ]; then
      echo "FAIL: PII pattern '${pii}' in track(\"activate\", ...) call:" >&2
      echo "$HITS" >&2
      FOUND=1
    fi
  done
done

if [ "$FOUND" -ne 0 ]; then
  echo "" >&2
  echo "BLOCK: PII (email/phone/...) leaked into track(\"activate\", ...) call." >&2
  echo "       FakeDoor is demand-validation-only at the template default." >&2
  echo "       For projects needing real lead capture: add via /change as a Feature." >&2
  echo "       See issue #1326, scaffold-externals.md Rule 4, posthog.md PII rule." >&2
  echo "       To allow a legitimate anti-pattern doc, add the magic marker" >&2
  echo "       'pii-in-track-allowlist:' as a comment on the same line." >&2
  exit 1
fi

echo "PASS: no PII in track(\"activate\", ...) calls"
exit 0
