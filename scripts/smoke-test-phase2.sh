#!/usr/bin/env bash
# smoke-test-phase2.sh — Phase 2 /resolve self-learning smoke tests.
#
# Gate for PR merge: exit non-zero fails CI. Runs six tests:
#   1. Artificial oscillation triggers halt_required=true
#   2. Escalate choice writes delivery-skip.flag + skip_states
#   3. Override choice records halt_override_reason
#   4. Shallow clone sets causal_unavailable=true (no halt)
#   5. Convergence history append produces 2 lines after 2 runs
#   6. Analyzer respects timeout via overridden config
#
# These tests construct isolated temp repos under $TMPDIR so they never mutate
# the host repo state.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ANALYZER="$REPO_ROOT/.claude/scripts/resolve-causal-analyzer.py"
REPORT="$REPO_ROOT/.claude/scripts/convergence-report.py"
DEFAULT_CONFIG="$REPO_ROOT/.claude/patterns/convergence-config.json"

FAIL=0
pass() { echo "  PASS: $*"; }
fail() { echo "  FAIL: $*" >&2; FAIL=1; }

# Build a self-contained clone of the target repo layout inside a workdir.
# We copy only the analyzer + parser + config so the scripts run without
# requiring any other part of the template.
setup_workdir() {
  local w="$1"
  mkdir -p "$w/.claude/scripts" "$w/.claude/patterns" "$w/.claude/stacks" \
           "$w/scripts/lib" "$w/.runs"
  cp "$ANALYZER" "$w/.claude/scripts/"
  cp "$REPORT" "$w/.claude/scripts/"
  cp "$REPO_ROOT/scripts/lib/stack_knowledge_parser.py" "$w/scripts/lib/"
  touch "$w/scripts/lib/__init__.py"
  cp "$DEFAULT_CONFIG" "$w/.claude/patterns/convergence-config.json"
  git -C "$w" init -q
  git -C "$w" config user.email "smoke@test.local"
  git -C "$w" config user.name "smoke"
  # Create a target file we will flip
  printf 'line one\nline two\nline three\n' > "$w/target.txt"
  git -C "$w" add -A
  git -C "$w" commit -q -m "initial"
  echo '{"reproductions":[{"issue":42,"divergence_point":"target.txt:2","expected":"x","actual":"y","reproduced":true}],"pre_fix_baseline":{"frontmatter":0,"semantics":0,"consistency":0}}' \
    > "$w/.runs/resolve-reproduction.json"
  echo '{"run_id":"smoke-test"}' > "$w/.runs/resolve-context.json"
}

# Apply a flip at target.txt:2 and commit with a /resolve-looking message.
flip_line() {
  local w="$1" content="$2" msg="$3"
  printf 'line one\n%s\nline three\n' "$content" > "$w/target.txt"
  git -C "$w" add -A
  git -C "$w" commit -q -m "$msg"
}

# --- Test 1: oscillation triggers halt -------------------------------------
test_1_oscillation() {
  local w
  w="$(mktemp -d)"
  setup_workdir "$w"
  # The initial setup already seeded line 2 = "line two".
  # Produce: A(original) -> B -> A -> B -> A -> B  (5 flip pairs total)
  flip_line "$w" "B-form" "Fix #100: switch to B"
  flip_line "$w" "line two" "Fix #200: revert to A"
  flip_line "$w" "B-form" "Fix #300: switch to B again"
  flip_line "$w" "line two" "Fix #400: revert again"
  flip_line "$w" "B-form" "Fix #500: B one more time"

  (cd "$w" && python3 .claude/scripts/resolve-causal-analyzer.py)
  local halt
  halt="$(python3 -c "import json; print(json.load(open('$w/.runs/resolve-causal-analysis.json'))['halt_required'])")"
  if [[ "$halt" == "True" ]]; then
    pass "Test 1 oscillation detected (halt_required=True)"
  else
    local dump
    dump="$(cat "$w/.runs/resolve-causal-analysis.json")"
    fail "Test 1 expected halt_required=True. Artifact: $dump"
  fi
  rm -rf "$w"
}

# --- Test 2: escalate writes delivery-skip.flag + skip_states --------------
test_2_escalate() {
  local w
  w="$(mktemp -d)"
  setup_workdir "$w"
  # Simulate the STATE 3b escalate handler (same shell operations the state
  # file performs on user reply=1, minus gh create which is network-bound).
  cat > "$w/.runs/resolve-causal-analysis.json" <<'EOF'
{"run_id":"smoke","divergence_points_analyzed":[],"halt_required":true,"halted":false,"halt_override_reason":null,"causal_unavailable":false,"analysis_complete":true}
EOF
  (cd "$w" && python3 -c "
import json
ctx = json.load(open('.runs/resolve-context.json'))
ctx['skip_states'] = ['4','4b','5','5d','6','7','8','8b','9','9a','10']
ctx['halted_at'] = '3b'
json.dump(ctx, open('.runs/resolve-context.json','w'), indent=2)
")
  (cd "$w" && printf 'halted:oscillation-or-antipattern\n' > .runs/delivery-skip.flag)
  (cd "$w" && python3 -c "
import json
a = json.load(open('.runs/resolve-causal-analysis.json'))
a['halted'] = True
json.dump(a, open('.runs/resolve-causal-analysis.json','w'), indent=2)
")
  if [[ -f "$w/.runs/delivery-skip.flag" ]] \
    && python3 -c "import json; ctx=json.load(open('$w/.runs/resolve-context.json')); assert ctx.get('skip_states')==['4','4b','5','5d','6','7','8','8b','9','9a','10']; assert ctx.get('halted_at')=='3b'"; then
    pass "Test 2 escalate: delivery-skip.flag + skip_states set"
  else
    fail "Test 2 escalate: artifacts missing"
  fi
  rm -rf "$w"
}

# --- Test 3: override records halt_override_reason -------------------------
test_3_override() {
  local w
  w="$(mktemp -d)"
  setup_workdir "$w"
  echo '{"run_id":"smoke","divergence_points_analyzed":[],"halt_required":true,"halted":false,"halt_override_reason":null,"causal_unavailable":false,"analysis_complete":true}' \
    > "$w/.runs/resolve-causal-analysis.json"
  (cd "$w" && python3 -c "
import json
reason = 'historical reversals are unrelated; new fix touches different semantics'
a = json.load(open('.runs/resolve-causal-analysis.json'))
a['halt_override_reason'] = reason
json.dump(a, open('.runs/resolve-causal-analysis.json','w'), indent=2)
ctx = json.load(open('.runs/resolve-context.json'))
ctx['halt_override_reason'] = reason
json.dump(ctx, open('.runs/resolve-context.json','w'), indent=2)
")
  if python3 -c "
import json
a = json.load(open('$w/.runs/resolve-causal-analysis.json'))
ctx = json.load(open('$w/.runs/resolve-context.json'))
assert a['halt_override_reason'], 'artifact missing reason'
assert ctx['halt_override_reason'], 'context missing reason'
"; then
    pass "Test 3 override reason propagated to artifact + context"
  else
    fail "Test 3 override reason missing"
  fi
  rm -rf "$w"
}

# --- Test 4: shallow clone → causal_unavailable ----------------------------
test_4_shallow() {
  local src
  src="$(mktemp -d)"
  git -C "$src" init -q -b main
  git -C "$src" config user.email "smoke@test.local"
  git -C "$src" config user.name "smoke"
  (cd "$src" && printf 'one\ntwo\n' > f.txt && git add -A && git commit -q -m "c1")
  (cd "$src" && printf 'one\nTWO\n' > f.txt && git add -A && git commit -q -m "c2")

  local dst
  dst="$(mktemp -d)"
  rm -rf "$dst"
  git clone -q --depth 1 "file://$src" "$dst"
  # Install analyzer + config into the shallow clone
  mkdir -p "$dst/.claude/scripts" "$dst/.claude/patterns" "$dst/scripts/lib" "$dst/.runs"
  cp "$ANALYZER" "$dst/.claude/scripts/"
  cp "$REPO_ROOT/scripts/lib/stack_knowledge_parser.py" "$dst/scripts/lib/"
  touch "$dst/scripts/lib/__init__.py"
  cp "$DEFAULT_CONFIG" "$dst/.claude/patterns/convergence-config.json"
  echo '{"reproductions":[{"issue":1,"divergence_point":"f.txt:2","expected":"x","actual":"y","reproduced":true}]}' \
    > "$dst/.runs/resolve-reproduction.json"
  echo '{"run_id":"shallow-smoke"}' > "$dst/.runs/resolve-context.json"

  (cd "$dst" && python3 .claude/scripts/resolve-causal-analyzer.py)
  local unavailable halt
  unavailable="$(python3 -c "import json; print(json.load(open('$dst/.runs/resolve-causal-analysis.json'))['causal_unavailable'])")"
  halt="$(python3 -c "import json; print(json.load(open('$dst/.runs/resolve-causal-analysis.json'))['halt_required'])")"
  if [[ "$unavailable" == "True" && "$halt" == "False" ]]; then
    pass "Test 4 shallow clone → causal_unavailable=True, halt_required=False"
  else
    fail "Test 4 expected unavailable=True halt=False; got unavailable=$unavailable halt=$halt"
  fi
  rm -rf "$src" "$dst"
}

# --- Test 5: convergence-history.jsonl append --------------------------
test_5_history_append() {
  local w
  w="$(mktemp -d)"
  setup_workdir "$w"
  (cd "$w" && python3 .claude/scripts/resolve-causal-analyzer.py >/dev/null)
  # Emulate STATE 9 append twice (same script form used in state-9 ACTIONS)
  for i in 1 2; do
    (cd "$w" && python3 -c "
import json, datetime, os
ctx = json.load(open('.runs/resolve-context.json'))
causal_path = '.runs/resolve-causal-analysis.json'
causal = json.load(open(causal_path)) if os.path.exists(causal_path) else {}
dps = causal.get('divergence_points_analyzed', []) or []
entry = {
    'run_id': ctx.get('run_id','') + '-iter-$i',
    'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'divergence_points_analyzed': len(dps),
    'oscillation_count_sum': sum(int(dp.get('oscillation_count') or 0) for dp in dps),
    'halted': bool(causal.get('halted')),
    'files_touched': sorted({dp.get('divergence_point','').split(':',1)[0] for dp in dps if dp.get('divergence_point')}),
    'patterns_matched': [],
}
open('.runs/convergence-history.jsonl','a').write(json.dumps(entry) + '\n')
")
  done
  local count
  count="$(wc -l < "$w/.runs/convergence-history.jsonl" | tr -d ' ')"
  if [[ "$count" == "2" ]]; then
    pass "Test 5 convergence-history.jsonl has 2 lines"
  else
    fail "Test 5 expected 2 lines, got $count"
  fi
  rm -rf "$w"
}

# --- Test 6: timeout respected ---------------------------------------------
test_6_timeout() {
  local w
  w="$(mktemp -d)"
  setup_workdir "$w"
  # Override config with 1-second timeout
  python3 -c "
import json
c = json.load(open('$w/.claude/patterns/convergence-config.json'))
c['causal_analysis_timeout_seconds'] = 1
json.dump(c, open('$w/.claude/patterns/convergence-config.json','w'), indent=2)
"
  # Shim `git` in PATH so `git log` sleeps. Hard-code the real git path
  # to avoid the shim calling itself via PATH.
  local shim real_git
  shim="$(mktemp -d)"
  real_git="$(command -v git)"
  cat > "$shim/git" <<SHIM
#!/usr/bin/env bash
if [[ "\$1" == "log" ]]; then
  sleep 30
  exit 0
fi
exec "$real_git" "\$@"
SHIM
  chmod +x "$shim/git"

  local start_s end_s elapsed
  start_s=$(date +%s)
  # Rely on the analyzer's own signal.alarm (1 second per overridden config).
  # The subprocess.run inside analyzer has its own timeout=25s fallback; we
  # wrap the whole thing in Python to avoid depending on GNU `timeout`.
  (cd "$w" && PATH="$shim:$PATH" python3 -c "
import subprocess, sys
p = subprocess.run(['python3', '.claude/scripts/resolve-causal-analyzer.py'], timeout=15)
sys.exit(p.returncode)
") || true
  end_s=$(date +%s)
  elapsed=$((end_s - start_s))
  local unavailable
  unavailable="$(python3 -c "import json,os; p='$w/.runs/resolve-causal-analysis.json'; print(json.load(open(p)).get('causal_unavailable') if os.path.exists(p) else 'NO_FILE')")"
  if (( elapsed <= 12 )) && [[ "$unavailable" == "True" ]]; then
    pass "Test 6 timeout respected (elapsed=${elapsed}s, causal_unavailable=True)"
  else
    fail "Test 6 timeout bad (elapsed=${elapsed}s, causal_unavailable=$unavailable)"
  fi
  rm -rf "$w" "$shim"
}

test_1_oscillation
test_2_escalate
test_3_override
test_4_shallow
test_5_history_append
test_6_timeout

if (( FAIL )); then
  echo ""
  echo "Phase 2 smoke tests FAILED" >&2
  exit 1
fi
echo ""
echo "All Phase 2 smoke tests passed"
