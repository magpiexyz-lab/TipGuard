#!/usr/bin/env bash
# Regression-prevention test for issue #1128 evidence-channel widening.
#
# Asserts the invariants that, if broken, would re-open the gap:
#   1. lib-core.sh deny() / deny_errors() must call _write_hook_friction
#   2. observation-phase.md Step 4 regex must include .py and .sh
#   3. scan-template-edits.sh must exist, be executable, and be invoked from finalize
#   4. write-fix-ledger.py must support --template-edit mode
#   5. observation-phase.md Q2 must cover executor (agent OR lead)
#   6. append-hook-friction.py and aggregate-hook-friction.py must exist
#
# Exit 0 if all invariants hold; exit 1 on any failure.
# Wired into `make lint-template` so CI catches regressions automatically.

set -uo pipefail
ERRORS=0
err() { echo "FAIL: $1" >&2; ERRORS=$((ERRORS+1)); }

# Invariant 1: lib-core.sh deny() must call _write_hook_friction
if ! grep -q "_write_hook_friction" .claude/hooks/lib-core.sh 2>/dev/null; then
  err "lib-core.sh deny() missing _write_hook_friction call (#1128 L2 regression)"
fi

# Invariant 2: observation-phase.md Step 4 regex includes both .py and .sh.
# Use Python to parse the actual re.findall() regex string so the test is
# robust to alternation ordering ("py|sh" vs "sh|py") and reformatting.
if ! python3 - <<'PY' 2>/dev/null
import re, sys
content = open('.claude/patterns/observation-phase.md').read()
# Find the re.findall(...) call and extract the regex literal.
m = re.search(r"re\.findall\(\s*r['\"]([^'\"]+)['\"]", content)
if not m:
    sys.exit(2)  # regex line missing
regex = m.group(1)
# The relevant alternation lives in a (?:...) group. Extract its contents.
g = re.search(r"\(\?\:([^)]+)\)", regex)
if not g:
    sys.exit(3)
exts = set(g.group(1).split('|'))
missing = [e for e in ('py', 'sh') if e not in exts]
if missing:
    sys.exit(4)
PY
then
  err "observation-phase.md Step 4 regex missing .py and/or .sh in extension allowlist (#1128 L1 regression)"
fi

# Invariant 3a: scan-template-edits.sh exists and is executable
if [[ ! -x .claude/scripts/scan-template-edits.sh ]]; then
  err ".claude/scripts/scan-template-edits.sh missing or not executable (#1128 L5 regression)"
fi

# Invariant 3b: lifecycle-finalize.sh invokes scan-template-edits.sh
if ! grep -q "scan-template-edits.sh" .claude/scripts/lifecycle-finalize.sh 2>/dev/null; then
  err "lifecycle-finalize.sh does not invoke scan-template-edits.sh (#1128 L5 regression)"
fi

# Invariant 4: write-fix-ledger.py supports --template-edit mode
if ! grep -q '"--template-edit"' .claude/scripts/write-fix-ledger.py 2>/dev/null; then
  err "write-fix-ledger.py missing --template-edit mode (#1128 L3 regression)"
fi

# Invariant 5: observation-phase.md Q2 covers executor (agent | lead)
if ! grep -q "executor" .claude/patterns/observation-phase.md 2>/dev/null; then
  err "observation-phase.md Q2 not reframed for executor (agent OR lead) (#1128 L6 regression)"
fi

# Invariant 6a: append-hook-friction.py exists
if [[ ! -f .claude/scripts/append-hook-friction.py ]]; then
  err ".claude/scripts/append-hook-friction.py missing (#1128 L2 regression)"
fi

# Invariant 6b: aggregate-hook-friction.py exists
if [[ ! -f .claude/scripts/aggregate-hook-friction.py ]]; then
  err ".claude/scripts/aggregate-hook-friction.py missing (#1128 L6 regression)"
fi

if [[ $ERRORS -gt 0 ]]; then
  echo "" >&2
  echo "test-template-coherence: $ERRORS invariant(s) violated — see above" >&2
  exit 1
fi
echo "test-template-coherence: all invariants pass (#1128 evidence-channel regression guard)"
exit 0
