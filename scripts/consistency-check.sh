#!/usr/bin/env bash
set -euo pipefail

# consistency-check.sh — Verify facts live in canonical sources, not in rules/skills
#
# Canonical (facts SHOULD appear here):
#   experiment/EVENTS.yaml, .claude/stacks/**/*.md, experiment/experiment.yaml
#
# Reference-only (facts should NOT appear here):
#   CLAUDE.md, .claude/commands/*.md

ERRORS=0
WARNINGS=0

# Derive code-writing skills dynamically from frontmatter type
CODE_WRITING_SKILLS=()
for f in .claude/commands/*.md; do
  [ -f "$f" ] || continue
  if head -20 "$f" | grep -q 'type: code-writing'; then
    CODE_WRITING_SKILLS+=("$f")
  fi
done

check_absent() {
  local file="$1" pattern="$2" desc="$3"
  [ -f "$file" ] || return 0
  if grep -qE "$pattern" "$file"; then
    echo "FAIL: $file — $desc"
    grep -nE "$pattern" "$file" | head -5
    echo ""
    ERRORS=$((ERRORS + 1))
  fi
}

echo "=== Consistency Check: Reference, Never Restate ==="
echo ""

# 1. Event name enumerations in CLAUDE.md (bullet + backtick-event + dash)
check_absent "CLAUDE.md" \
  '^\s*-\s*`(visit_landing|signup_start|signup_complete|activate|retain_return|pay_start|pay_success)` — ' \
  "enumerated event definitions (should reference experiment/EVENTS.yaml)"

# 2. Event name enumerations in skill files
for f in .claude/commands/*.md; do
  [ -f "$f" ] || continue
  check_absent "$f" \
    '^\s*[\-\|]\s*`?(visit_landing|signup_start|signup_complete|activate|retain_return|pay_start|pay_success)`?\s*(on |— |\| [a-z])' \
    "enumerated event names (should reference experiment/EVENTS.yaml)"
done

# 3. Hardcoded analytics import path in skills, agents, and procedures
for f in .claude/commands/*.md .claude/agents/*.md .claude/procedures/*.md; do
  [ -f "$f" ] || continue
  check_absent "$f" '@/lib/analytics' \
    "hardcoded import path (should reference analytics stack file)"
done

# 4. Framework-specific terms in CLAUDE.md
check_absent "CLAUDE.md" \
  'Server Actions|parallel routes|intercepting routes' \
  "framework-specific terms (belong in framework stack file)"

# 5. Framework-specific terms in skill files
for f in .claude/commands/*.md; do
  [ -f "$f" ] || continue
  check_absent "$f" '"use client"' \
    "Next.js directive (should reference framework stack file)"
  check_absent "$f" 'Server Actions' \
    "Next.js term (should reference framework stack file)"
  check_absent "$f" '\buseEffect\b' \
    "React-specific term (use generic or reference framework stack file)"
done

# 6. Hardcoded analytics constants in CLAUDE.md
check_absent "CLAUDE.md" 'PROJECT_NAME|PROJECT_OWNER' \
  "hardcoded constant names (should reference analytics stack file)"

# 7. Hardcoded framework paths in feature skill
check_absent ".claude/commands/change.md" 'src/app/api/' \
  "hardcoded API path (should reference framework stack file)"
check_absent ".claude/commands/change.md" 'src/lib/types\.ts' \
  "hardcoded types path (should reference database stack file)"

# 8. (removed)

# 9. Hardcoded analytics path in PR template
check_absent ".github/PULL_REQUEST_TEMPLATE.md" 'src/lib/analytics' \
  "hardcoded analytics path (should say 'the analytics library')"

# 10. All code-writing skills reference verify.md
for f in "${CODE_WRITING_SKILLS[@]}"; do
  [ -f "$f" ] || continue
  if ! grep -q 'patterns/verify.md' "$f"; then
    echo "FAIL: $f — missing verify.md reference (all code-writing skills must reference the verification procedure)"
    ERRORS=$((ERRORS + 1))
  fi
done

# 11. (removed)

# 12. (removed)

# 13. Hardcoded analytics provider names in skill, agent, and procedure section headings
# (Check numbers 14-15 added below)

for f in .claude/commands/*.md .claude/agents/*.md .claude/procedures/*.md; do
  [ -f "$f" ] || continue
  if grep -qiE '^###.*PostHog' "$f"; then
    echo "FAIL: $f — hardcoded analytics provider name in section heading (should be provider-agnostic)"
    grep -niE '^###.*PostHog' "$f" | head -5
    echo ""
    ERRORS=$((ERRORS + 1))
  fi
done

# 14. Verify lib.sh function calls have space before arguments in hook scripts
LIB_FUNCS="compute_missing_states|require_trace_verdict|check_trace_run_id|check_trace_verdict|check_postcondition_artifacts|check_tier1_retry_complete|check_efficiency_directives|check_build_result|check_file_boundary|check_verdict_gates|check_skill_completion|check_block_verdicts|check_verdict_consistency|check_verdict_error|check_fixlog_verdict_consistency|rerun_postconditions|require_trace_verdict|handle_validation|deny_errors|exec_merge_gate|run_merge_gate"
for f in .claude/hooks/*.sh; do
  [ -f "$f" ] || continue
  [[ "$(basename "$f")" =~ ^lib(-[a-z-]+)?\.sh$ ]] && continue
  if grep -qE "($LIB_FUNCS)\"" "$f"; then
    echo "FAIL: $f — function call missing space before argument (concatenates function name with argument)"
    grep -nE "($LIB_FUNCS)\"" "$f" | head -5
    echo ""
    ERRORS=$((ERRORS + 1))
  fi
done

# 15. Verify STATE_ID regex character class matches between state-completion-gate and phase-boundary-gate
SCG=".claude/hooks/state-completion-gate.sh"
PBG=".claude/hooks/phase-boundary-gate.sh"
if [ -f "$SCG" ] && [ -f "$PBG" ]; then
  SCG_CLASS=$(grep -oE 'advance-state.*\[0-9a-z[_]*\]' "$SCG" | head -1 | grep -oE '\[0-9a-z[_]*\]' || echo "")
  PBG_CLASS=$(grep -oE 'advance-state.*\[0-9a-z[_]*\]' "$PBG" | head -1 | grep -oE '\[0-9a-z[_]*\]' || echo "")
  if [ -n "$SCG_CLASS" ] && [ -n "$PBG_CLASS" ] && [ "$SCG_CLASS" != "$PBG_CLASS" ]; then
    echo "FAIL: STATE_ID regex mismatch — state-completion-gate.sh uses $SCG_CLASS, phase-boundary-gate.sh uses $PBG_CLASS"
    ERRORS=$((ERRORS + 1))
  fi
fi

# 16. Verify verify.md STATE 5 branches on testing framework type
STATE5=".claude/skills/verify/state-5-e2e-tests.md"
if [ -f "$STATE5" ]; then
  if grep -q 'playwright' "$STATE5" && ! grep -q 'vitest' "$STATE5"; then
    echo "FAIL: $STATE5 — hardcodes playwright without vitest branch (must handle all testing frameworks)"
    ERRORS=$((ERRORS + 1))
  fi
  if grep -q 'vitest' "$STATE5" && ! grep -q 'playwright' "$STATE5"; then
    echo "FAIL: $STATE5 — hardcodes vitest without playwright branch (must handle all testing frameworks)"
    ERRORS=$((ERRORS + 1))
  fi
fi

# 17. Non-STATE-0 registry entries should use content validation, not just test -f
REGISTRY=".claude/patterns/state-registry.json"
if [ -f "$REGISTRY" ]; then
  WEAK=$(python3 -c "
import json, sys
data = json.load(open('$REGISTRY'))
skip = {'trace_schemas'}
s0 = {'0', 'c0', 'x0'}
weak = []
for skill, states in data.items():
    if skill in skip or not isinstance(states, dict): continue
    for sid, pc in states.items():
        if sid in s0: continue
        if isinstance(pc, str) and pc.startswith('test -f ') and 'python3' not in pc and 'grep' not in pc:
            weak.append(f'{skill}[{sid}]')
for w in weak:
    print(w)
" 2>/dev/null)
  if [ -n "$WEAK" ]; then
    echo "WARN: state-registry.json — non-STATE-0 entries use file-existence-only postconditions (consider content validation):"
    echo "$WEAK" | sed 's/^/  /'
    echo ""
    WARNINGS=$((WARNINGS + 1))
  fi
fi

# --- Check 18: Verify gate-keeper spawn prompts include Verify criteria ---
echo -n "Check 18: gate-keeper prompts include Verify criteria... "
GATE_MISSING=0
for f in .claude/skills/bootstrap/state-*.md .claude/skills/*/state-*.md; do
  [ -f "$f" ] || continue
  while IFS= read -r line; do
    if echo "$line" | grep -qi 'gate-keeper.*Pass:' && ! echo "$line" | grep -qi 'Verify:'; then
      echo ""
      echo "  WARN: $f: gate-keeper prompt missing 'Verify:' criteria"
      echo "    $line"
      GATE_MISSING=$((GATE_MISSING + 1))
    fi
  done < "$f"
done
if [ "$GATE_MISSING" -gt 0 ]; then
  echo ""
  echo "  $GATE_MISSING gate-keeper prompt(s) missing Verify criteria (non-blocking)."
  WARNINGS=$((WARNINGS + GATE_MISSING))
else
  echo "ok"
fi

# 19. Non-STATE-0 VERIFY commands must include content assertions, not just isinstance/type checks
echo -n "Check 19: VERIFY commands include content assertions... "
if [ -f "$REGISTRY" ]; then
  WEAK_TYPE=$(python3 -c "
import json, re, sys
data = json.load(open('$REGISTRY'))
skip = {'trace_schemas'}
s0 = {'0', 'c0', 'x0'}
content_patterns = [
    r'len\(', r'>=', r'<=', r'>\s*0', r'==\s', r'!=',
    r'is True', r'is False', r'is not None',
    r'\ball\(', r'\bany\(', r'\bnot in\b', r'\bin [a-z\[\(]',
    r'\.get\([^)]+\)\s*[><=!]'
]
weak = []
for skill, states in data.items():
    if skill in skip or not isinstance(states, dict): continue
    for sid, pc in states.items():
        if sid in s0: continue
        verify_cmd = pc
        if isinstance(pc, dict):
            verify_cmd = pc.get('verify', '')
        if not isinstance(verify_cmd, str): continue
        if 'isinstance(' not in verify_cmd: continue
        if verify_cmd == 'true': continue
        has_content = any(re.search(p, verify_cmd) for p in content_patterns)
        if not has_content:
            weak.append(f'{skill}[{sid}]')
for w in weak:
    print(w)
" 2>/dev/null)
  if [ -n "$WEAK_TYPE" ]; then
    echo ""
    echo "  FAIL: state-registry.json — VERIFY commands use isinstance() without content assertions:"
    echo "$WEAK_TYPE" | sed 's/^/    /'
    echo "  Add content checks (len()>0, >=0, is True, all(), etc.) alongside isinstance() checks."
    ERRORS=$((ERRORS + 1))
  else
    echo "ok"
  fi
else
  echo "skip (no registry)"
fi

# 20. Makefile lint-template target must cover every template validator CI runs.
# Rationale (issue #1003): auto-merge Guard 3 delegates to `make lint-template`
# as a local mirror of CI. If CI gains a new validator without a matching
# Makefile edit, the local mirror drifts and auto-merge lets CI-red PRs land.
# Validators that cannot meaningfully run outside CI (require PR SHAs, scheduled
# nightly, etc.) are declared in a `# CI-ONLY:` comment directly above the
# Makefile `lint-template:` target and skipped from the parity assertion.
echo -n "Check 20: Makefile lint-template ↔ CI validators parity... "
PARITY_ERR=""
PARITY_RC=0
# Wrap command-substitution in `if` so `set -e` treats a non-zero Python exit
# as ordinary control flow, not a fatal error that terminates the script.
if PARITY_ERR=$(python3 - <<'PY' 2>&1
import re, pathlib, sys
VAL_RE = re.compile(r'(python3\s+-m\s+pytest\s+scripts/|python3\s+scripts/[A-Za-z0-9_-]+\.py|bash\s+scripts/[A-Za-z0-9_-]+\.sh|bash\s+\.claude/scripts/[A-Za-z0-9_-]+\.sh)')
def extract(text):
    return {re.sub(r'\s+', ' ', m.group(1)).strip() for m in VAL_RE.finditer(text)}
ci = set()
wf_dir = pathlib.Path('.github/workflows')
if wf_dir.is_dir():
    for p in sorted(wf_dir.glob('*.yml')):
        ci |= extract(p.read_text())
mk_path = pathlib.Path('Makefile')
mk = set()
ci_only = set()
if mk_path.is_file():
    mk_text = mk_path.read_text()
    # Union the body of every target whose name starts with `lint-template`
    # (lint-template, lint-template-tests, lint-template-full). Splitting the
    # local mirror into fast + heavy targets is legitimate — Check 20 treats
    # the lint-template* family as a single allowed set.
    for m in re.finditer(r'^(lint-template[A-Za-z0-9_-]*):.*?(?=^[A-Za-z_][A-Za-z0-9_-]*:|\Z)', mk_text, re.M | re.S):
        mk |= extract(m.group(0))
    lines = mk_text.splitlines()
    for i, line in enumerate(lines):
        # Find the CI-ONLY comment above the first lint-template* target
        if re.match(r'^lint-template[A-Za-z0-9_-]*:', line) and i > 0:
            for j in range(i - 1, -1, -1):
                s = lines[j].strip()
                if not s.startswith('#'): break
                if s.startswith('# CI-ONLY:'):
                    for v in s.split(':', 1)[1].split(','):
                        v = v.strip()
                        if v: ci_only.add(re.sub(r'\s+', ' ', v))
            break
missing = ci - mk - ci_only
extra = ci_only - ci
if missing or extra:
    if missing:
        print('MISSING: ' + '; '.join(sorted(missing)))
    if extra:
        print('STALE-CI-ONLY: ' + '; '.join(sorted(extra)))
    sys.exit(1)
PY
); then
  PARITY_RC=0
else
  PARITY_RC=1
fi
if [ "$PARITY_RC" -ne 0 ]; then
  echo ""
  echo "  FAIL: Makefile lint-template drifted from CI validators:"
  echo "$PARITY_ERR" | sed 's/^/    /'
  echo "  Add missing validators to Makefile lint-template target, or declare them in a '# CI-ONLY:' comment."
  ERRORS=$((ERRORS + 1))
else
  echo "ok"
fi

# 21. No `gh pr merge --auto` anywhere under .claude/. Repo allow_auto_merge=false
# makes --auto silently fire an immediate non-gated merge — see issue #1003 and
# feedback_gh_pr_merge_auto_fallback memory. Lines with a DO_NOT comment marker
# are skipped so auto-merge.md can document "do not use this" without tripping.
# .claude/worktrees/ (transient, gitignored) is excluded.
echo -n "Check 21: No gh pr merge --auto under .claude/... "
AUTO_HITS=$(
  grep -rnE 'pr merge[^\n]*--auto' \
    --include='*.sh' --include='*.md' \
    --exclude-dir=worktrees \
    .claude/scripts/ .claude/patterns/ .claude/hooks/ 2>/dev/null \
    | grep -vE '\bDO_NOT\b' \
    || true
)
if [ -n "$AUTO_HITS" ]; then
  echo ""
  echo "  FAIL: forbidden --auto flag (repo allow_auto_merge=false — silent immediate-merge):"
  echo "$AUTO_HITS" | sed 's/^/    /'
  ERRORS=$((ERRORS + 1))
else
  echo "ok"
fi

# 22. gh pr merge callers restricted to an explicit allowlist.
# Prevents a future script from adding a merge call that bypasses the Guard chain
# in lifecycle-finalize.sh. DO_NOT-marked lines are skipped (doc mentions).
# .claude/worktrees/ (transient, gitignored) is excluded.
echo -n "Check 22: gh pr merge callers restricted to allowlist... "
MERGE_HITS=$(
  grep -rnE 'gh pr merge\b' \
    --include='*.sh' --include='*.md' \
    --exclude-dir=worktrees \
    .claude/ 2>/dev/null \
    | grep -vE '\bDO_NOT\b' \
    || true
)
VIOLATIONS=$(
  echo "$MERGE_HITS" \
    | grep -vE '^\.claude/scripts/lifecycle-finalize\.sh:|^\.claude/patterns/auto-merge\.md:' \
    | grep -v '^$' \
    || true
)
if [ -n "$VIOLATIONS" ]; then
  echo ""
  echo "  FAIL: gh pr merge called outside allowlist (lifecycle-finalize.sh, auto-merge.md):"
  echo "$VIOLATIONS" | sed 's/^/    /'
  ERRORS=$((ERRORS + 1))
else
  echo "ok"
fi

# Check 23: archetype consistency (absorbs former scripts/check-archetype-consistency.sh)
# Files that semantically branch on archetype must include `## Archetype Gate` H2 heading
# AND a reference to .claude/patterns/archetype-behavior-check.md.
# Canonical: .claude/patterns/archetype-behavior-check.md (Quick-Reference Table + Compound Dimensions)
ARCHETYPE_BRANCHING_FILES=(
  # Procedures
  ".claude/procedures/accessibility-scanner.md"
  ".claude/procedures/behavior-verifier.md"
  ".claude/procedures/change-feature.md"
  ".claude/procedures/change-plans.md"
  ".claude/procedures/change-test.md"
  ".claude/procedures/plan-exploration.md"
  ".claude/procedures/plan-validation.md"
  ".claude/procedures/scaffold-images.md"
  ".claude/procedures/scaffold-init.md"
  ".claude/procedures/scaffold-landing.md"
  ".claude/procedures/scaffold-libs.md"
  ".claude/procedures/scaffold-pages.md"
  ".claude/procedures/wire.md"
  # Agents
  ".claude/agents/accessibility-scanner.md"
  ".claude/agents/behavior-verifier.md"
  ".claude/agents/performance-reporter.md"
  ".claude/agents/scaffold-pages.md"
  ".claude/agents/security-attacker.md"
  ".claude/agents/security-defender.md"
  ".claude/agents/spec-reviewer.md"
  # Patterns (manual fallback — first-class branching)
  ".claude/patterns/security-review.md"
  # State files (Rule 13 JIT — H2 inside ACTIONS does not break verify-linter section parser)
  ".claude/skills/audit/state-1-parallel-analysis.md"
  ".claude/skills/bootstrap/state-2-resolve-archetype.md"
  ".claude/skills/bootstrap/state-3-validate-experiment.md"
  ".claude/skills/bootstrap/state-9-setup-phase.md"
  ".claude/skills/bootstrap/state-11-core-scaffold.md"
  ".claude/skills/bootstrap/state-11a-lib-spawn.md"
  ".claude/skills/bootstrap/state-11b-lib-verify.md"
  ".claude/skills/bootstrap/state-11c-page-scaffold.md"
  ".claude/skills/bootstrap/state-13-merged-validation.md"
  ".claude/skills/bootstrap/state-13a-analytics-design-check.md"
  ".claude/skills/bootstrap/state-13b-content-seo-check.md"
  ".claude/skills/bootstrap/state-13c-bg2-gate.md"
  ".claude/skills/bootstrap/state-14-wire-phase.md"
  ".claude/skills/bootstrap/state-14a-bg2-wire-gate.md"
  ".claude/skills/bootstrap/state-15-scan-and-classify.md"
  ".claude/skills/bootstrap/state-18-commit-and-push.md"
  ".claude/skills/change/state-2-read-context.md"
  ".claude/skills/change/state-5-check-preconditions.md"
  ".claude/skills/change/state-9-update-specs.md"
  ".claude/skills/change/state-10-implement.md"
  ".claude/skills/change/state-11a-verify-prep.md"
  ".claude/skills/change/state-12-commit-and-pr.md"
  ".claude/skills/deploy/state-0-pre-flight.md"
  ".claude/skills/deploy/state-3c-deploy-services.md"
  ".claude/skills/deploy/state-4a-health-fix.md"
  ".claude/skills/deploy/state-4b-production-validation.md"
  ".claude/skills/distribute/state-0-init.md"
  ".claude/skills/iterate/state-0-read-context.md"
  ".claude/skills/iterate/state-4-output.md"
  ".claude/skills/iterate/state-x1a-validate-data-integrity.md"
  ".claude/skills/retro/state-3-file-issue.md"
  ".claude/skills/spec/state-4-golden-path.md"
  ".claude/skills/spec/state-6-stack-funnel.md"
  ".claude/skills/teardown/state-0-pre-flight.md"
  ".claude/skills/teardown/state-2-destroy-resources.md"
  ".claude/skills/verify/state-0-read-context.md"
  ".claude/skills/verify/state-2-phase1-parallel.md"
  ".claude/skills/verify/state-2a-page-image-map.md"
  ".claude/skills/verify/state-2b-drift-detection.md"
  ".claude/skills/verify/state-3a-design-agents.md"
  ".claude/skills/verify/state-3b-quality-gate.md"
  ".claude/skills/verify/state-3c-ux-merge.md"
  ".claude/skills/verify/state-3d-quality-fix.md"
  ".claude/skills/verify/state-8-save-patterns.md"
  # Additional state files with semantic archetype branching (Phase 2.7 audit)
  ".claude/skills/bootstrap/state-5-present-plan.md"
  ".claude/skills/distribute/state-2-validate-analytics.md"
  ".claude/skills/distribute/state-3-implement.md"
  ".claude/skills/distribute/state-4-generate.md"
  ".claude/skills/deploy/state-2-user-approval.md"
  ".claude/skills/iterate/state-1-gather-data.md"
  ".claude/skills/iterate/state-2-compute-verdicts.md"
  ".claude/skills/retro/state-0-read-context.md"
  ".claude/skills/review/state-2a-review-scan.md"
  ".claude/skills/rollback/state-3-execute.md"
  ".claude/skills/spec/state-3-behaviors.md"
  ".claude/skills/upgrade/state-1-merge-validate.md"
)

# Files that mention archetype strings but do NOT branch — REF only, no heading required.
# Includes: thin pass-through agents, non-markdown shell scripts, overview patterns,
# context-readers that pass archetype downstream without branching.
ARCHETYPE_REFERENCE_ONLY_FILES=(
  ".claude/agents/gate-keeper.md"
  ".claude/agents/provision-scanner.md"
  ".claude/hooks/skill-agent-gate.sh"
  ".claude/stacks/framework/nextjs.md"
  ".claude/patterns/verify.md"
  ".claude/patterns/analytics-verification.md"
  ".claude/procedures/scaffold-externals.md"
  ".claude/skills/ARCHITECTURE.md"
  # Context-readers / passers (read archetype but delegate branching)
  ".claude/skills/bootstrap/state-3a-bg1-gate.md"
  ".claude/skills/bootstrap/state-7-save-plan.md"
  ".claude/skills/change/state-7-user-approval.md"
  ".claude/skills/deploy/state-5-manifest-write.md"
  ".claude/skills/iterate/state-c0-read-ads-context.md"
  ".claude/skills/resolve/state-6-branch-setup.md"
  ".claude/skills/resolve/state-9a-graduate-external.md"
  ".claude/skills/rollback/state-0-read-context.md"
  # Substring false positives ('cli' in 'click', 'service' in 'service role', etc.).
  # These mention archetype-related substrings but do not semantically branch.
  # Listed explicitly so the user's naive grep verification can document them as exceptions.
  ".claude/procedures/change-upgrade.md"
  ".claude/procedures/design-critic.md"
  ".claude/procedures/google-ads-setup.md"
  ".claude/procedures/ux-journeyer.md"
  ".claude/agents/pattern-classifier.md"
  ".claude/agents/scaffold-externals.md"
  ".claude/agents/scaffold-wire.md"
  ".claude/agents/security-fixer.md"
  ".claude/agents/ux-journeyer.md"
)

echo -n "Check 23: archetype consistency... "
CHECK_23_FAILED=0

# Skip Check 23 entirely when canonical source is absent (test fixtures, partial template
# clones). Same pattern as Checks 1-22 which silently skip when their target file is absent.
if [ ! -f .claude/patterns/archetype-behavior-check.md ]; then
  echo "skip (no canonical)"
else

# 23a — Canonical source has Quick-Reference Table (absorbed from check-archetype-consistency.sh)
if ! grep -qE 'Quick-Reference Table' .claude/patterns/archetype-behavior-check.md 2>/dev/null; then
  [ "$CHECK_23_FAILED" -eq 0 ] && echo ""
  echo "  FAIL: archetype-behavior-check.md — missing Quick-Reference Table section"
  CHECK_23_FAILED=$((CHECK_23_FAILED + 1))
fi

# 23b — Quick-Reference Table has ≥14 data rows (absorbed)
QRT_DATA_ROWS=$(sed -n '/^## Quick-Reference Table/,/^## [^Q]/p' \
  .claude/patterns/archetype-behavior-check.md \
  | grep -c '^| [A-Z]' 2>/dev/null || echo "0")
if [ "$QRT_DATA_ROWS" -lt 14 ]; then
  [ "$CHECK_23_FAILED" -eq 0 ] && echo ""
  echo "  FAIL: archetype-behavior-check.md — Quick-Reference Table has $QRT_DATA_ROWS rows, expected >=14"
  CHECK_23_FAILED=$((CHECK_23_FAILED + 1))
fi

# 23c — Compound Dimensions section exists (absorbed)
if ! grep -qE 'Compound Dimensions' .claude/patterns/archetype-behavior-check.md 2>/dev/null; then
  [ "$CHECK_23_FAILED" -eq 0 ] && echo ""
  echo "  FAIL: archetype-behavior-check.md — missing Compound Dimensions section"
  CHECK_23_FAILED=$((CHECK_23_FAILED + 1))
fi

# 23d — get_archetype utility function present (absorbed)
if ! grep -qE 'get_archetype' .claude/hooks/lib-state.sh 2>/dev/null; then
  [ "$CHECK_23_FAILED" -eq 0 ] && echo ""
  echo "  FAIL: .claude/hooks/lib-state.sh — missing get_archetype utility"
  CHECK_23_FAILED=$((CHECK_23_FAILED + 1))
fi

# 23e — All BRANCHING files have `## Archetype Gate` H2
for f in "${ARCHETYPE_BRANCHING_FILES[@]}"; do
  if [ ! -f "$f" ]; then
    [ "$CHECK_23_FAILED" -eq 0 ] && echo ""
    echo "  FAIL: $f — file not found (BRANCHING list out of date?)"
    CHECK_23_FAILED=$((CHECK_23_FAILED + 1))
    continue
  fi
  if ! grep -qE '^## Archetype Gate$' "$f" 2>/dev/null; then
    [ "$CHECK_23_FAILED" -eq 0 ] && echo ""
    echo "  FAIL: $f — missing canonical heading '## Archetype Gate'"
    CHECK_23_FAILED=$((CHECK_23_FAILED + 1))
  fi
done

# 23f — All BRANCHING + REFERENCE_ONLY files contain `archetype-behavior-check.md` REF
for f in "${ARCHETYPE_BRANCHING_FILES[@]}" "${ARCHETYPE_REFERENCE_ONLY_FILES[@]}"; do
  [ -f "$f" ] || continue
  if ! grep -qE 'archetype-behavior-check\.md' "$f" 2>/dev/null; then
    [ "$CHECK_23_FAILED" -eq 0 ] && echo ""
    echo "  FAIL: $f — missing REF to archetype-behavior-check.md"
    CHECK_23_FAILED=$((CHECK_23_FAILED + 1))
  fi
done

# 23g — BLOCKING: word-boundary regex catches uncurated archetype-branching files.
# A file matching this regex must be in BRANCHING, REFERENCE_ONLY, OR carry an
# explicit `<!-- archetype-gate-exempt: <reason> -->` marker. This converts what
# would otherwise be a WARN-fatigued non-enforcement into a real contract: new
# branching files cannot land without classification.
# Word boundaries avoid 'service' in 'API service' / 'cli' substring in 'client'.
WARN_FILES=$(grep -rlE '\b(web-app|cli)\b|\barchetype\b.*\bservice\b|stack\.type' \
  --include='*.md' \
  --exclude-dir=worktrees \
  .claude/procedures .claude/agents .claude/skills 2>/dev/null \
  | grep -vE 'archetype-behavior-check\.md' \
  | sort -u)
KNOWN=$(printf '%s\n' "${ARCHETYPE_BRANCHING_FILES[@]}" "${ARCHETYPE_REFERENCE_ONLY_FILES[@]}" | sort -u)
UNCURATED=$(comm -23 <(echo "$WARN_FILES") <(echo "$KNOWN") 2>/dev/null)
# Filter out files carrying the explicit exempt marker
UNCLASSIFIED=""
if [ -n "$UNCURATED" ]; then
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    if ! grep -qE '<!-- archetype-gate-exempt:' "$f" 2>/dev/null; then
      UNCLASSIFIED="${UNCLASSIFIED}${f}"$'\n'
    fi
  done <<< "$UNCURATED"
fi
if [ -n "$UNCLASSIFIED" ]; then
  [ "$CHECK_23_FAILED" -eq 0 ] && echo ""
  echo "  FAIL: uncurated archetype-mention files. Each must be:"
  echo "    (a) in ARCHETYPE_BRANCHING_FILES with '## Archetype Gate' heading, OR"
  echo "    (b) in ARCHETYPE_REFERENCE_ONLY_FILES with REF to archetype-behavior-check.md, OR"
  echo "    (c) carry inline marker: <!-- archetype-gate-exempt: <reason> -->"
  printf '%s' "$UNCLASSIFIED" | sed 's/^/    /'
  CHECK_23_FAILED=$((CHECK_23_FAILED + 1))
fi

# 23h — Row-citing REFs must embed verbatim canonical labeled lines.
# Scope: BRANCHING + REFERENCE_ONLY files whose REF cites `row "X"` or
# `rows "X", "Y"` syntax, EXCLUDING REFs containing `Compound Dimensions`.
# Sub-rules: slug-existence, multi-row count, verbatim match, slug uniqueness.
# Backed by .claude/scripts/lib/check-archetype-canonical.py — exits 0 if clean,
# 1 with stderr enumeration of failing files on drift.
CHECK_23H_OUT=$(python3 .claude/scripts/lib/check-archetype-canonical.py 2>&1)
CHECK_23H_RC=$?
if [ "$CHECK_23H_RC" -ne 0 ]; then
  [ "$CHECK_23_FAILED" -eq 0 ] && echo ""
  echo "$CHECK_23H_OUT" | sed 's/^/  /'
  CHECK_23_FAILED=$((CHECK_23_FAILED + 1))
fi

if [ "$CHECK_23_FAILED" -eq 0 ]; then
  echo "ok"
else
  ERRORS=$((ERRORS + CHECK_23_FAILED))
fi

fi  # end Check 23 canonical-source guard

# Check 24: demo-server-startup canonical snippet drift.
# Canonical: .claude/patterns/demo-server-startup.md
# Four verification procedures inline an identical demo-mode dev-server start
# command + 15s poll directive — only the port number varies. The pattern file
# documents the canonical form; this check enforces that:
#   24a. The pattern file exists.
#   24b. Each registered procedure inlines the canonical command with the
#        registered port AND carries a `> REF: see ...` line.
#   24c. No unregistered procedure inlines the snippet (a fifth caller must
#        register here, in the pattern file's port table, and add a REF).
echo -n "Check 24: demo-server-startup canonical snippet drift... "
DEMO_PATTERN_FILE=".claude/patterns/demo-server-startup.md"
DEMO_REF_LINE='> REF: see `.claude/patterns/demo-server-startup.md`'
DEMO_REGISTRY=(
  "accessibility-scanner:3096"
  "behavior-verifier:3097"
  "ux-journeyer:3098"
  "design-critic:3099"
)
DEMO_VIOLATIONS=""

# Skip when the canonical pattern file is absent — fresh /bootstrap projects
# may not yet have pulled in the pattern. Matches Check 23's "skip (no canonical)" idiom.
if [ ! -f "$DEMO_PATTERN_FILE" ]; then
  echo "skip (no canonical)"
else

for entry in "${DEMO_REGISTRY[@]}"; do
  proc="${entry%%:*}"
  port="${entry##*:}"
  file=".claude/procedures/${proc}.md"
  if [ ! -f "$file" ]; then
    DEMO_VIOLATIONS+="missing registered procedure: $file"$'\n'
    continue
  fi
  expected_cmd="DEMO_MODE=true NEXT_PUBLIC_DEMO_MODE=true npm run start -- -p ${port} &"
  if ! grep -qF -- "$expected_cmd" "$file"; then
    DEMO_VIOLATIONS+="${file}: canonical command absent or port drifted (expected '... -p ${port} &')"$'\n'
  fi
  if ! grep -qF -- "$DEMO_REF_LINE" "$file"; then
    DEMO_VIOLATIONS+="${file}: missing REF line '${DEMO_REF_LINE}.'"$'\n'
  fi
done

REGISTERED_BASENAMES=$(printf '%s\n' "${DEMO_REGISTRY[@]}" | cut -d: -f1)
DEMO_INLINE_FILES=$(grep -lE 'DEMO_MODE=true.*npm run start' .claude/procedures/*.md 2>/dev/null || true)
if [ -n "$DEMO_INLINE_FILES" ]; then
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    base="$(basename "$f" .md)"
    if ! echo "$REGISTERED_BASENAMES" | grep -qx "$base"; then
      DEMO_VIOLATIONS+="${f}: inlines DEMO_MODE startup but is not in Check 24 registry — add to registry + ${DEMO_PATTERN_FILE} port table + add REF line"$'\n'
    fi
  done <<< "$DEMO_INLINE_FILES"
fi

if [ -n "$DEMO_VIOLATIONS" ]; then
  echo ""
  echo "  FAIL: demo-server-startup drift detected:"
  printf '%s' "$DEMO_VIOLATIONS" | sed 's/^/    /'
  ERRORS=$((ERRORS + 1))
else
  echo "ok"
fi

fi  # end Check 24 canonical-pattern-present guard

# Check 25: bash 4+ uppercase/lowercase parameter expansion in hook + script files
# (recurrence guard for #1141 — macOS default bash 3.2 silently fails on ${var^^} / ${var,,})
echo -n "Check 25: bash 4+ parameter expansion in shell files... "
BASH4_FILES=$(grep -lE '\$\{[a-zA-Z_][a-zA-Z0-9_]*(\^\^?|,,?)\}' .claude/hooks/*.sh .claude/scripts/*.sh 2>/dev/null || true)
if [ -n "$BASH4_FILES" ]; then
  echo ""
  echo "  FAIL: bash 4+ parameter expansion detected — fails silently on macOS default bash 3.2:"
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    grep -nE '\$\{[a-zA-Z_][a-zA-Z0-9_]*(\^\^?|,,?)\}' "$f" | sed "s|^|    $f:|"
  done <<< "$BASH4_FILES"
  echo "  Replace \${var^^} / \${var,,} with: var_upper=\$(printf '%s' \"\$var\" | tr '[:lower:]' '[:upper:]')"
  ERRORS=$((ERRORS + 1))
else
  echo "ok"
fi

# Check 26: thin-wrapper / claim-extraction antipattern without shadcn-primitive filter
# (recurrence guard for #1154 — extracting @/components/* imports must filter ui/ + magicui/)
echo -n "Check 26: shadcn-primitive filter on @/components/ extraction... "
EXTRACTION_VIOLATIONS=""
# Match `from [...]@/components/...` in either quote order (`['"]` or `["']`),
# with or without a leading capture-group paren (`from ['"](@/components/...)`).
# Both forms appear across skill / agent file regex strings.
EXTRACTION_REGEX="from \\[[\"'][\"']\\]\\(?@/components/"
while IFS= read -r f; do
  [ -z "$f" ] && continue
  # Files that grep / regex-extract @/components/ imports must reference @/components/ui/ or
  # @/components/magicui/ as a filter within the same file. Otherwise the extraction bundles
  # auto-generated shadcn primitives into claim candidates / wrapper detectors.
  if grep -qE "$EXTRACTION_REGEX" "$f" 2>/dev/null; then
    if ! grep -qE '@/components/(ui/|magicui/)' "$f" 2>/dev/null; then
      EXTRACTION_VIOLATIONS+="${f}: regex extracts @/components/ imports without @/components/ui/ or @/components/magicui/ filter (#1154)"$'\n'
    fi
  fi
done <<< "$(find .claude/skills .claude/agents -type f -name '*.md' 2>/dev/null)"
if [ -n "$EXTRACTION_VIOLATIONS" ]; then
  echo ""
  echo "  FAIL: thin-wrapper-style extraction of @/components/ paths must exclude shadcn primitives:"
  printf '%s' "$EXTRACTION_VIOLATIONS" | sed 's/^/    /'
  ERRORS=$((ERRORS + 1))
else
  echo "ok"
fi

# Check 27: rate-limit examples must derive client IP via clientIpFromHeaders helper
# (recurrence guard for #1361 — Vercel proxy appends verified client IP as LAST
# X-Forwarded-For entry; raw header read lets attackers rotate prefix to bypass
# per-IP cap.) Scans .claude/stacks/**/*.md fenced TS/JS code blocks for the
# anti-pattern `headers.get("x-forwarded-for")` and FAILs unless the SAME code
# block also contains `function clientIpFromHeaders` (the helper definition
# itself, by design, contains the literal — and is the one canonical location).
# Only TS/JS code blocks are scanned: YAML/bash/sql/sh blocks may legitimately
# quote the literal in prose (Stack Knowledge fix_template fields, anti-pattern
# warnings) without it being executable code.
echo -n "Check 27: rate-limit clientIpFromHeaders helper (#1361)... "
XFF_VIOLATIONS=""
while IFS= read -r f; do
  [ -z "$f" ] && continue
  # Walk fenced TS/JS code blocks. Per-block flags: in_ts_block (set on the
  # opening ```ts / ```typescript / ```tsx / ```js / ```javascript / ```jsx),
  # helper_defined (set on `function clientIpFromHeaders`), xff_seen (set on
  # `headers.get("x-forwarded-for")`). On end-of-block (closing ```), if
  # xff_seen && !helper_defined: violation. Non-TS/JS blocks are skipped.
  block_violations=$(awk -v file="$f" '
    /^[[:space:]]*```[[:space:]]*(ts|typescript|tsx|js|javascript|jsx)[[:space:]]*$/ {
      in_ts_block = 1; xff_seen = 0; helper_defined = 0; lines = 0
      next
    }
    /^[[:space:]]*```[[:space:]]*$/ {
      if (in_ts_block) {
        if (xff_seen && !helper_defined) {
          for (i = 0; i < lines; i++) print file ":" line_nums[i] ": raw headers.get(\"x-forwarded-for\") in TS/JS code block; use clientIpFromHeaders(headers) helper from src/lib/rate-limit (#1361)"
        }
        in_ts_block = 0; xff_seen = 0; helper_defined = 0; lines = 0
      }
      next
    }
    /^[[:space:]]*```/ {
      # Non-TS opening fence — ignore until closing fence resets state above.
      next
    }
    in_ts_block && /headers\.get\("x-forwarded-for"\)/ {
      xff_seen = 1
      line_nums[lines++] = NR
    }
    in_ts_block && /function clientIpFromHeaders/ {
      helper_defined = 1
    }
  ' "$f")
  if [ -n "$block_violations" ]; then
    XFF_VIOLATIONS+="$block_violations"$'\n'
  fi
done <<< "$(find .claude/stacks -type f -name '*.md' 2>/dev/null)"
if [ -n "$XFF_VIOLATIONS" ]; then
  echo ""
  echo "  FAIL: stack-file rate-limit examples must use clientIpFromHeaders helper (Vercel last-XFF-entry semantics):"
  printf '%s' "$XFF_VIOLATIONS" | sed 's/^/    /'
  echo "  Fix: import { clientIpFromHeaders } from \"@/lib/rate-limit\"; const ip = clientIpFromHeaders(request.headers);"
  ERRORS=$((ERRORS + 1))
else
  echo "ok"
fi

echo ""
if [ "$WARNINGS" -gt 0 ]; then
  echo "WARNINGS: $WARNINGS weak postcondition(s) detected (non-blocking)."
fi
if [ "$ERRORS" -gt 0 ]; then
  echo "FAILED: $ERRORS violation(s). Move facts to canonical sources (experiment/EVENTS.yaml, stack files)."
  exit 1
else
  echo "PASSED: No consistency violations."
fi
