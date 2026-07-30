#!/usr/bin/env bash
# smoke-test-phase3.sh — Phase 3 /resolve self-learning smoke tests.
#
# Gate for PR merge: exit non-zero fails CI. Runs seven tests:
#   1. State PRECONDITIONS reads produce non-empty hints from a live entry
#   2. parse_stack_knowledge_file respects *.archive.md suffix (exact match)
#   3. Audit script files pattern-family-candidate for a 5-entry cluster
#   4. Audit script is idempotent (second run files zero new issues)
#   5. Graduation atomicity CI rejects unpaired canonical deletion
#   6. Graduation atomicity CI accepts canonical removal + validator addition
#   7. Both new workflow YAMLs contain the template-repo `if:` guard
#
# Tests construct isolated temp repos under $TMPDIR so they never mutate
# the host repo state.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PARSER="$REPO_ROOT/scripts/lib/stack_knowledge_parser.py"
AUDIT_PY="$REPO_ROOT/.claude/scripts/lib/stack_knowledge_audit.py"
AUDIT_SH="$REPO_ROOT/.claude/scripts/stack-knowledge-audit.sh"
GRAD_PY="$REPO_ROOT/scripts/ci-check-graduation-atomicity.py"
NIGHTLY_YAML="$REPO_ROOT/.github/workflows/stack-knowledge-nightly.yml"
GRAD_YAML="$REPO_ROOT/.github/workflows/stack-knowledge-graduation.yml"

FAIL=0
pass() { echo "  PASS: $*"; }
fail() { echo "  FAIL: $*" >&2; FAIL=1; }

# --- Test 1: active-prevention hints load for stable entry -----------------
test_1_state_reads() {
  local w
  w="$(mktemp -d)"
  mkdir -p "$w/.claude/stacks/framework" "$w/scripts/lib" "$w/.runs"
  cp "$PARSER" "$w/scripts/lib/"
  touch "$w/scripts/lib/__init__.py"
  cat > "$w/.claude/stacks/framework/nextjs.md" <<'STK'
## Stack Knowledge

```yaml
id: nextjs-demo-guard
maturity: stable
composite_identity:
  root_cause_class: demo-mode-leak
  divergence_pattern: env-var-check-missing
  stack_scope: framework/nextjs
composite_identity_hash: abcdef012345
graduated_to: null
occurrence_count: 7
confidence_score: 0.9
fix_template: Add VERCEL guard before DEMO_MODE check
prevention_mechanism: validator
first_seen: 2026-01-01
last_seen: 2026-03-15
linked_issues: []
symptom_keywords: [demo, production]
```
STK
  # Run the exact snippet from .claude/skills/change/state-2-read-context.md
  (cd "$w" && python3 -c "
import json, sys, os
sys.path.insert(0, 'scripts')
from lib.stack_knowledge_parser import iter_stack_knowledge_files, parse_stack_knowledge_file
ACTIVE = {'stable', 'canonical'}
hints = []
sources = []
for path in iter_stack_knowledge_files():
    entries = parse_stack_knowledge_file(path)
    if not entries:
        continue
    sources.append(path)
    for e in entries:
        if e.get('maturity') in ACTIVE and e.get('graduated_to') is None:
            hints.append({'id': e.get('id')})
os.makedirs('.runs', exist_ok=True)
json.dump({'entries': hints, 'source_files': sources, 'count': len(hints)}, open('.runs/change-stack-knowledge-hints.json', 'w'))
")
  local count
  count="$(python3 -c "import json; print(json.load(open('$w/.runs/change-stack-knowledge-hints.json'))['count'])")"
  if [[ "$count" == "1" ]]; then
    pass "Test 1 state read: 1 active hint loaded from stable entry"
  else
    fail "Test 1 expected count=1, got $count"
  fi
  rm -rf "$w"
}

# --- Test 2: archive file suffix semantics ---------------------------------
test_2_archive_skip() {
  local w
  w="$(mktemp -d)"
  mkdir -p "$w/scripts/lib"
  cp "$PARSER" "$w/scripts/lib/"
  touch "$w/scripts/lib/__init__.py"
  # Write an archive file containing a valid Stack Knowledge entry
  mkdir -p "$w/stacks/framework"
  cat > "$w/stacks/framework/nextjs.archive.md" <<'STK'
## Stack Knowledge

```yaml
id: archived-entry
maturity: canonical
graduated_to: null
```
STK
  local result
  result="$(python3 -c "
import sys
sys.path.insert(0, '$w/scripts')
from lib.stack_knowledge_parser import parse_stack_knowledge_file, is_archive_path
# Archive file should return []
ok1 = parse_stack_knowledge_file('$w/stacks/framework/nextjs.archive.md') == []
# Exact-suffix: archive.md.stale/foo.md must NOT match
ok2 = is_archive_path('.claude/stacks/archive.md.stale/foo.md') is False
# Regular .md files should return True for is_archive_path only with exact suffix
ok3 = is_archive_path('.claude/stacks/foo.archive.md') is True
print('OK' if ok1 and ok2 and ok3 else f'FAIL ok1={ok1} ok2={ok2} ok3={ok3}')
")"
  if [[ "$result" == "OK" ]]; then
    pass "Test 2 archive skip + exact-suffix guard"
  else
    fail "Test 2 archive semantics broken: $result"
  fi
  rm -rf "$w"
}

# --- Test 3: audit files pattern-family-candidate for 5-entry cluster ------
test_3_family_candidate() {
  local w shim
  w="$(mktemp -d)"
  shim="$(mktemp -d)"
  # Shim gh to log invocations; always return 0
  cat > "$shim/gh" <<GHSHIM
#!/usr/bin/env bash
# log args to gh-calls.log, print a fake URL on success
echo "\$@" >> "$shim/gh-calls.log"
case "\$1" in
  issue)
    case "\$2" in
      list) echo '[]' ;;
      create) echo "https://github.com/fake/issue/1" ;;
      close) ;;
    esac
    ;;
  api) echo '0' ;;
esac
exit 0
GHSHIM
  chmod +x "$shim/gh"

  mkdir -p "$w/.claude/stacks/framework" "$w/.claude/scripts/lib" "$w/scripts/lib" "$w/.runs"
  cp "$PARSER" "$w/scripts/lib/"
  touch "$w/scripts/lib/__init__.py"
  cp "$AUDIT_PY" "$w/.claude/scripts/lib/"
  cp "$AUDIT_SH" "$w/.claude/scripts/"

  # 5 entries sharing (stack_scope=framework/nextjs, root_cause_class=missing-archetype-guard)
  for i in 1 2 3 4 5; do
    cat > "$w/.claude/stacks/framework/entry-$i.md" <<ENTRY
## Stack Knowledge

\`\`\`yaml
id: nextjs-guard-$i
maturity: raw
composite_identity:
  root_cause_class: missing-archetype-guard
  divergence_pattern: leak-$i
  stack_scope: framework/nextjs
composite_identity_hash: aaaaaaaaaa0$i
graduated_to: null
occurrence_count: 1
confidence_score: 0.5
fix_template: unique
prevention_mechanism: null
first_seen: 2026-01-0$i
last_seen: 2026-01-0$i
linked_issues: []
symptom_keywords: []
\`\`\`
ENTRY
  done

  # Make it a git repo so the audit shell guard doesn't complain
  (cd "$w" && git init -q && git -c user.email=t@t -c user.name=t add -A >/dev/null && git -c user.email=t@t -c user.name=t commit -qm init)

  PATH="$shim:$PATH" bash "$w/.claude/scripts/stack-knowledge-audit.sh" >/dev/null 2>&1 || true

  if grep -q "create .*pattern-family-candidate" "$shim/gh-calls.log" 2>/dev/null; then
    pass "Test 3 audit filed pattern-family-candidate for 5-entry cluster"
  else
    fail "Test 3 expected pattern-family-candidate create call; log: $(cat "$shim/gh-calls.log" 2>/dev/null || echo 'missing')"
  fi
  rm -rf "$w" "$shim"
}

# --- Test 4: audit idempotency (second run files zero new issues) ----------
test_4_audit_idempotent() {
  local w shim
  w="$(mktemp -d)"
  shim="$(mktemp -d)"
  cat > "$shim/gh" <<GHSHIM
#!/usr/bin/env bash
echo "\$@" >> "$shim/gh-calls.log"
case "\$1" in
  issue)
    case "\$2" in
      list) echo '[]' ;;
      create) echo "https://github.com/fake/issue/\$RANDOM" ;;
      close) ;;
    esac
    ;;
  api) echo '0' ;;
esac
exit 0
GHSHIM
  chmod +x "$shim/gh"

  mkdir -p "$w/.claude/stacks/framework" "$w/.claude/scripts/lib" "$w/scripts/lib" "$w/.runs"
  cp "$PARSER" "$w/scripts/lib/"
  touch "$w/scripts/lib/__init__.py"
  cp "$AUDIT_PY" "$w/.claude/scripts/lib/"
  cp "$AUDIT_SH" "$w/.claude/scripts/"

  # One archive candidate: stale (last_seen is very old), low occurrence, low confidence
  cat > "$w/.claude/stacks/framework/stale.md" <<'STK'
## Stack Knowledge

```yaml
id: stale-entry
maturity: raw
composite_identity:
  root_cause_class: whatever
  divergence_pattern: whatever
  stack_scope: framework/x
composite_identity_hash: beefbeef0001
graduated_to: null
occurrence_count: 1
confidence_score: 0.2
fix_template: unused
prevention_mechanism: null
first_seen: 2024-01-01
last_seen: 2024-01-01
linked_issues: []
symptom_keywords: []
```
STK

  (cd "$w" && git init -q && git -c user.email=t@t -c user.name=t add -A >/dev/null && git -c user.email=t@t -c user.name=t commit -qm init)

  # First run — local state empty, GitHub issue list empty → 1 issue filed
  PATH="$shim:$PATH" bash "$w/.claude/scripts/stack-knowledge-audit.sh" >/dev/null 2>&1 || true
  local first_creates=0
  if [[ -f "$shim/gh-calls.log" ]]; then
    first_creates="$(awk '/issue create/ {c++} END {print c+0}' "$shim/gh-calls.log")"
  fi

  # Extract the fingerprint marker from the first filed body (proves Gap #1
  # fix: fingerprints are emitted into issue bodies so GitHub is the source
  # of truth for cross-run idempotency). Portable extraction using sed.
  local fp_marker
  fp_marker="$(sed -n 's/.*audit-fingerprint: \([0-9a-f]\{12\}\).*/\1/p' "$shim/gh-calls.log" 2>/dev/null | head -1 || true)"

  # Simulate the CI condition: wipe local state (gitignored in prod) AND
  # make `gh issue list` return the previously-filed issue with fingerprint
  # marker in its body. Replace the shim so list returns the fingerprinted
  # issue.
  rm -f "$w/.runs/stack-knowledge-audit-filed.json"
  cat > "$shim/gh" <<GHSHIM
#!/usr/bin/env bash
echo "\$@" >> "$shim/gh-calls.log"
case "\$1" in
  issue)
    case "\$2" in
      list)
        # Return the previously-filed issue so the audit's GitHub-backed
        # dedup sees the fingerprint and skips a re-file.
        echo '[{"body":"## Archive candidate\\n\\n<!-- audit-fingerprint: '"$fp_marker"' -->"}]'
        ;;
      create) echo "https://github.com/fake/issue/\$RANDOM" ;;
      close) ;;
    esac
    ;;
  api) echo '0' ;;
esac
exit 0
GHSHIM
  chmod +x "$shim/gh"

  : > "$shim/gh-calls.log"
  PATH="$shim:$PATH" bash "$w/.claude/scripts/stack-knowledge-audit.sh" >/dev/null 2>&1 || true
  local second_creates=0
  if [[ -f "$shim/gh-calls.log" ]]; then
    second_creates="$(awk '/issue create/ {c++} END {print c+0}' "$shim/gh-calls.log")"
  fi

  if (( first_creates >= 1 )) && (( second_creates == 0 )); then
    pass "Test 4 idempotency: first=$first_creates creates, second=$second_creates creates"
  else
    fail "Test 4 expected first>=1, second==0. got first=$first_creates second=$second_creates"
  fi
  rm -rf "$w" "$shim"
}

# --- Test 5: graduation atomicity — violation ------------------------------
test_5_graduation_violation() {
  local w
  w="$(mktemp -d)"
  mkdir -p "$w/scripts/lib"
  cp "$PARSER" "$w/scripts/lib/"
  cp "$GRAD_PY" "$w/scripts/"
  touch "$w/scripts/lib/__init__.py"
  cd "$w"
  git init -q
  git config user.email "t@t"
  git config user.name "t"
  mkdir -p .claude/stacks/framework
  cat > .claude/stacks/framework/nextjs.md <<'STK'
## Stack Knowledge

```yaml
id: nextjs-demo-guard
maturity: canonical
graduated_to: null
composite_identity:
  root_cause_class: x
  divergence_pattern: y
  stack_scope: framework/nextjs
composite_identity_hash: cafecafecafe
occurrence_count: 5
confidence_score: 0.9
fix_template: baseline
prevention_mechanism: validator
first_seen: 2026-01-01
last_seen: 2026-01-01
linked_issues: []
symptom_keywords: []
```
STK
  git add -A
  git commit -qm init
  git branch -M main
  git checkout -qb bad-pr
  # Commit 1 removes canonical entry; no validator added
  rm .claude/stacks/framework/nextjs.md
  git add -A
  git commit -qm "remove canonical, no prevention"
  # Commit 2: unrelated touch (ensures we exercise base...head aggregate)
  echo "noise" > noise.txt
  git add -A
  git commit -qm "noise"

  local exit_code
  set +e
  python3 scripts/ci-check-graduation-atomicity.py --base main --head bad-pr >/dev/null 2>&1
  exit_code=$?
  set -e
  if [[ "$exit_code" == "1" ]]; then
    pass "Test 5 graduation violation detected (exit=1)"
  else
    fail "Test 5 expected exit 1, got $exit_code"
  fi
  cd "$REPO_ROOT"
  rm -rf "$w"
}

# --- Test 6: graduation atomicity — valid ----------------------------------
test_6_graduation_valid() {
  local w
  w="$(mktemp -d)"
  mkdir -p "$w/scripts/lib"
  cp "$PARSER" "$w/scripts/lib/"
  cp "$GRAD_PY" "$w/scripts/"
  touch "$w/scripts/lib/__init__.py"
  cd "$w"
  git init -q
  git config user.email "t@t"
  git config user.name "t"
  mkdir -p .claude/stacks/framework scripts/validators
  # Baseline: canonical with graduated_to pointing to a path that exists
  echo "# placeholder" > scripts/validators/demo_guard.py
  cat > .claude/stacks/framework/nextjs.md <<'STK'
## Stack Knowledge

```yaml
id: nextjs-demo-guard
maturity: canonical
graduated_to: scripts/validators/demo_guard.py
composite_identity:
  root_cause_class: x
  divergence_pattern: y
  stack_scope: framework/nextjs
composite_identity_hash: cafecafecafe
occurrence_count: 5
confidence_score: 0.9
fix_template: baseline
prevention_mechanism: validator
first_seen: 2026-01-01
last_seen: 2026-01-01
linked_issues: []
symptom_keywords: []
```
STK
  git add -A
  git commit -qm init
  git branch -M main
  git checkout -qb good-pr
  # Commit 1: modify the validator
  echo "# strengthened demo guard" >> scripts/validators/demo_guard.py
  git add -A
  git commit -qm "strengthen validator"
  # Commit 2: remove the canonical entry (graduated_to path already modified in commit 1)
  rm .claude/stacks/framework/nextjs.md
  git add -A
  git commit -qm "graduate canonical entry"

  local exit_code
  set +e
  python3 scripts/ci-check-graduation-atomicity.py --base main --head good-pr >/dev/null 2>&1
  exit_code=$?
  set -e
  if [[ "$exit_code" == "0" ]]; then
    pass "Test 6 graduation valid accepted (exit=0)"
  else
    fail "Test 6 expected exit 0, got $exit_code"
  fi
  cd "$REPO_ROOT"
  rm -rf "$w"
}

# --- Test 7: workflow guards present ---------------------------------------
test_7_workflow_guards() {
  local guard_pattern="github.repository == 'magpiexyz-lab/mvp-template'"
  local ok=1
  if ! grep -qF "$guard_pattern" "$NIGHTLY_YAML"; then
    fail "Test 7 nightly workflow missing template-repo guard"
    ok=0
  fi
  if ! grep -qF "$guard_pattern" "$GRAD_YAML"; then
    fail "Test 7 graduation workflow missing template-repo guard"
    ok=0
  fi
  if (( ok )); then
    pass "Test 7 workflow template-repo guards present in both YAMLs"
  fi
}

test_1_state_reads
test_2_archive_skip
test_3_family_candidate
test_4_audit_idempotent
test_5_graduation_violation
test_6_graduation_valid
test_7_workflow_guards

if (( FAIL )); then
  echo ""
  echo "Phase 3 smoke tests FAILED" >&2
  exit 1
fi
echo ""
echo "All Phase 3 smoke tests passed"
