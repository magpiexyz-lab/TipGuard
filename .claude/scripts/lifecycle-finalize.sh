#!/usr/bin/env bash
# lifecycle-finalize.sh — Phase 3: Post-execution audit, Q-score, epilogue.
# Usage: bash .claude/scripts/lifecycle-finalize.sh <skill>
# Output: FINALIZE_COMPLETE + EPILOGUE_STRATEGY=A|B
#
# Steps (unconditional — runs for all skills):
#   1. Verify all states completed (warn if missing)
#   2. Rerun ALL state VERIFY commands from state-registry.json (warn on failure)
#   3. Q-score: read .runs/q-dimensions.json → call write-q-score.py (skip if absent)
#   4. Epilogue strategy: output EPILOGUE_STRATEGY=A (diffs vs main) or B (no diffs)
#
# Steps (unconditional — runs for all skills):
#   5. Delivery: read .runs/ artifacts → gate checks → commit/push/PR/auto-merge
#   6. Write .runs/verify-recheck.json for remediation phase (mandatory execution, graceful degradation)
set -euo pipefail

SKILL="${1:-}"

if [[ -z "$SKILL" ]]; then
  echo "ERROR: lifecycle-finalize.sh — skill name required" >&2
  exit 1
fi

PROJECT_DIR="$(git rev-parse --show-toplevel 2>/dev/null || echo "${CLAUDE_PROJECT_DIR:-.}")"

# Source lifecycle-lib first so resolve_framework_manifest is available below.
source "$(dirname "$0")/lifecycle-lib.sh"

# Normalize a mode-qualified invocation (state-99 passes SKILL_KEY, e.g.
# "iterate-cross") down to the base skill that owns the manifest and command
# file. Issue #1990: resolving these paths with the qualified name pointed at
# nonexistent files, silently degrading the state-completion check and the
# analysis-only delivery gate.
read -r BASE_SKILL SKILL_MODE <<< "$(resolve_skill_dir "$SKILL")"
SKILL_MODE="${SKILL_MODE:-}"
MANIFEST=$(resolve_framework_manifest "$BASE_SKILL")

# Determine context file — the qualified path wins when it exists (state-99
# callers), else derive from the base skill's manifest active_mode. Immune to
# a stale active_mode when the caller passed the qualified name.
CTX="$PROJECT_DIR/.runs/${SKILL}-context.json"
if [[ ! -f "$CTX" ]]; then
  CTX=$(resolve_context_path "$BASE_SKILL" "$MANIFEST")
fi

# Default branch derived once for every downstream git operation (previously
# hardcoded "main" throughout).
DEFAULT_BRANCH=$(resolve_default_branch)

if [[ ! -f "$CTX" ]]; then
  echo "ERROR: lifecycle-finalize.sh — $CTX not found" >&2
  exit 1
fi

# --- Verify all states completed ---
python3 -c "
import json, sys
ctx = json.load(open('$CTX'))
completed = set(str(s) for s in ctx.get('completed_states', []))
skip = set(str(s) for s in ctx.get('skip_states', []))
manifest_path = '$MANIFEST'
try:
    manifest = json.load(open(manifest_path))
    if 'active_mode' in manifest and 'modes' in manifest:
        states = manifest['modes'][manifest['active_mode']]['states']
    else:
        states = manifest.get('states', [])
    missing = [str(s) for s in states if str(s) not in completed and str(s) not in skip]
    # Exclude in-flight epilogue state 99: it is currently running this script, and
    # its VERIFY (state-completion-gate) is the real gate for advancing 99 — see
    # Step 2's same self-skip at L103-L113 and PR #1059 design intent. Without this
    # exclusion, the has_agents branch below hard-errors on every skill entering 99
    # for the first time (fix #1063).
    missing = [s for s in missing if str(s) != '99']
    if missing:
        has_agents = bool(manifest.get('agents', {}))
        if has_agents:
            print('ERROR: lifecycle-finalize.sh — states not completed: %s' % missing, file=sys.stderr)
            sys.exit(1)
        else:
            print('WARN: lifecycle-finalize.sh — states not completed: %s' % missing, file=sys.stderr)
except FileNotFoundError:
    pass
"

# --- Determine skill type ---
HAS_BRANCH=""
if [[ -f "$MANIFEST" ]]; then
  HAS_BRANCH=$(python3 -c "import json; print(json.load(open('$MANIFEST')).get('branch',''))" 2>/dev/null || echo "")
fi

HAS_DIFF=""
if [[ -n "$HAS_BRANCH" ]]; then
  if ! git diff --quiet HEAD 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
    HAS_DIFF="true"
  fi
fi

# --- Step 2: Rerun ALL state VERIFY commands (unconditional, warn-only) ---
# Determine registry key — mode-aware for iterate --check/--cross. A caller
# that already passed the mode-qualified key is authoritative (survives a
# missing manifest, where resolve_registry_key would fall back to the base).
if [[ "$SKILL" != "$BASE_SKILL" ]]; then
  REGISTRY_SKILL="$SKILL"
else
  REGISTRY_SKILL=$(resolve_registry_key "$SKILL" "$MANIFEST")
fi

python3 -c "
import json, subprocess, sys, os

skill = '$REGISTRY_SKILL'
project_dir = '$PROJECT_DIR'
registry_path = os.path.join(project_dir, '.claude/patterns/state-registry.json')

if not os.path.isfile(registry_path):
    print('WARN: state-registry.json not found, skipping VERIFY rerun', file=sys.stderr)
    sys.exit(0)

registry = json.load(open(registry_path))
skill_states = registry.get(skill, {})
failures = 0
verify_results = []

ctx_path = '$CTX'
skip = set()
if os.path.isfile(ctx_path):
    try:
        skip = set(str(s) for s in json.load(open(ctx_path)).get('skip_states', []))
    except: pass

for state_id, raw in skill_states.items():
    if state_id.startswith('_'):
        continue
    if state_id in skip:
        continue
    # State 99 (epilogue) is currently in flight — its VERIFY checks artifacts
    # that THIS script writes (verify-recheck.json at Step 6). Verifying it
    # here would fail self-referentially. State 99's own advance-state hook
    # is the real gate.
    if state_id == '99':
        continue
    if isinstance(raw, str):
        cmd = raw
        lifecycle = 'durable'
    elif isinstance(raw, dict):
        cmd = raw.get('verify', '')
        lifecycle = raw.get('lifecycle', 'durable')
    else:
        continue
    if not cmd or cmd.strip() == 'true':
        continue
    # Skip ONLY transient-intra-skill (closes #1162 part 1). At finalize-time
    # of skill X:
    #   - transient-intra-skill: deleter-state already ran → artifact missing →
    #     skip (reporting WARN trains users to ignore real warnings).
    #   - transient-cross-skill: deleter is lifecycle-init of NEXT skill →
    #     artifact still exists during current finalize → DO NOT skip; rerun
    #     VERIFY to catch real production failures.
    #   - durable: must exist → rerun VERIFY (existing warn-only behavior).
    if lifecycle == 'transient-intra-skill':
        verify_results.append({'state': state_id, 'passed': True, 'error': None,
                               'skipped': 'transient-intra-skill'})
        continue
    entry = {'state': state_id, 'passed': True, 'error': None}
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True,
                                timeout=30, cwd=project_dir)
        if result.returncode != 0:
            stderr = result.stderr.decode().strip()[:200]
            entry['passed'] = False
            entry['error'] = stderr
            print('WARN: VERIFY %s.%s failed: %s' % (skill, state_id, stderr), file=sys.stderr)
            failures += 1
        verify_results.append(entry)
    except subprocess.TimeoutExpired:
        entry['passed'] = False
        entry['error'] = 'timeout'
        verify_results.append(entry)
        print('WARN: VERIFY %s.%s timed out' % (skill, state_id), file=sys.stderr)
        failures += 1
    except Exception as e:
        entry['passed'] = False
        entry['error'] = str(e)[:200]
        verify_results.append(entry)
        print('WARN: VERIFY %s.%s error: %s' % (skill, state_id, e), file=sys.stderr)
        failures += 1

if failures > 0:
    print('WARN: %d VERIFY command(s) failed (non-blocking)' % failures, file=sys.stderr)

# Write raw verify results for remediation phase (Step 6 assembles final JSON)
try:
    raw_path = os.path.join(project_dir, '.runs/.verify-results-raw.json')
    json.dump(verify_results, open(raw_path, 'w'), indent=2)
except Exception as e:
    print('WARN: failed to write .verify-results-raw.json: %s' % e, file=sys.stderr)
"

# --- Step 2.5: AOC v1 FLS v1 — consolidate agent trace fixes[] into ledger ---
# Ensures every skill ends with a fresh .runs/fix-ledger.jsonl for downstream
# consumers (pattern-classifier, observation-phase, write-q-score, verify-report-gate).
# Both writers are idempotent and safe to invoke unconditionally:
#   - write-fix-ledger.py: writes ledger from agent trace fixes[] arrays
#   - render-fix-log.py: renders fix-log.md from the ledger via atomic temp+rename
# AOC v1.1 PR5 retired direct prose appends to fix-log.md (see
# fix-ledger-write-guard.sh:14-28 — direct echo > fix-log.md is now blocked).
# The renderer is the sole writer to fix-log.md; safe to invoke at finalize time.
# Closes #1449: render-fix-log.py promoted from observation-phase Step 2
# conditional fallback to unconditional invocation here.
if [[ -d "$PROJECT_DIR/.runs/agent-traces" ]]; then
  python3 "$PROJECT_DIR/.claude/scripts/write-fix-ledger.py" >/dev/null 2>&1 || true
  python3 "$PROJECT_DIR/.claude/scripts/render-fix-log.py" >/dev/null 2>&1 || true
  # PR 2 post-render verifier (deny mode): render-fix-log.py is required to
  # produce .runs/fix-log.md after invocation. If it doesn't, that's a real
  # bug we want to catch immediately. Defense-in-depth check; always runs
  # here because this is the only place the renderer is invoked unconditionally.
  if [[ ! -f "$PROJECT_DIR/.runs/fix-log.md" ]]; then
    echo "BLOCK: lifecycle-finalize Step 2.5: render-fix-log.py did not produce .runs/fix-log.md (renderer is the sole writer per AOC v1 R2; missing output indicates a renderer regression)" >&2
    exit 1
  fi
fi

# --- Step 2.6: Aggregate hook-friction.jsonl into hook-friction-summary.json (#1226) ---
# Canonical FIRST aggregation (unconditional — the aggregator writes a fresh
# empty summary when the jsonl is missing, so a friction-free run can never
# inherit the previous run's stale summary). Strictly scoped to the active
# run_id inside the aggregator (#1895). observation-phase.md Step 2d re-runs
# it as an epilogue tail refresh (idempotent full rebuild) so the observer
# sees friction generated after this point; if the lead skips 2d, only the
# tail refresh is lost — this first pass keeps the Q2 4th evidence channel
# available to the Step 5a retrospective regardless.
python3 "$PROJECT_DIR/.claude/scripts/aggregate-hook-friction.py" >/dev/null 2>&1 || true

# --- Step 3: Q-score — read q-dimensions.json, call write-q-score.py ---
Q_DIMS_PATH="$PROJECT_DIR/.runs/q-dimensions.json"
if [[ -f "$Q_DIMS_PATH" ]]; then
  python3 -c "
import json, subprocess, sys, os

dims_path = '$Q_DIMS_PATH'
project_dir = '$PROJECT_DIR'
script = os.path.join(project_dir, '.claude/scripts/write-q-score.py')

if not os.path.isfile(script):
    print('WARN: write-q-score.py not found, skipping Q-score', file=sys.stderr)
    sys.exit(0)

d = json.load(open(dims_path))
args = [
    'python3', script,
    '--skill', d.get('skill', '$SKILL'),
    '--scope', d.get('scope', 'N/A'),
    '--dims', json.dumps(d.get('dims', {})),
    '--run-id', d.get('run_id', ''),
]
try:
    result = subprocess.run(args, capture_output=True, timeout=30, cwd=project_dir)
    if result.stdout:
        print(result.stdout.decode().strip())
    if result.returncode != 0:
        print('WARN: write-q-score.py exited %d: %s' % (result.returncode, result.stderr.decode().strip()[:200]), file=sys.stderr)
except Exception as e:
    print('WARN: Q-score write failed: %s' % e, file=sys.stderr)
" || true
else
  echo "WARN: lifecycle-finalize.sh — .runs/q-dimensions.json not found, skipping Q-score" >&2
fi

# --- Step 4: Epilogue strategy determination ---
EPILOGUE_STRATEGY="B"
if [[ -n "$HAS_BRANCH" ]]; then
  # Check for committed diffs relative to main
  MERGE_BASE=$(git merge-base "$DEFAULT_BRANCH" HEAD 2>/dev/null || echo "")
  if [[ -n "$MERGE_BASE" ]] && ! git diff --quiet "$MERGE_BASE"...HEAD 2>/dev/null; then
    EPILOGUE_STRATEGY="A"
    # Collect evidence: diffs for observer
    git diff "$MERGE_BASE"...HEAD > "$PROJECT_DIR/.runs/observer-diffs.txt" 2>/dev/null || true
    # Scan template-owned paths for lead-applied edits not already in the
    # ledger (#1128 Layer 5). Gated on EPILOGUE_STRATEGY="A" — only runs when
    # there is a real branch with real commit-diff. On main or with no diff,
    # the scanner's HEAD~1...HEAD fallback would mis-attribute prior commits
    # (e.g., merged PRs) to the current skill. Idempotent + fail-open.
    if [[ -x "$PROJECT_DIR/.claude/scripts/scan-template-edits.sh" ]]; then
      bash "$PROJECT_DIR/.claude/scripts/scan-template-edits.sh" "$SKILL" 2>/dev/null || true
    fi
  fi
fi

# Collect fix-log availability
if [[ -f "$PROJECT_DIR/.runs/fix-log.md" ]] && [[ -s "$PROJECT_DIR/.runs/fix-log.md" ]]; then
  echo "INFO: fix-log.md present ($(wc -l < "$PROJECT_DIR/.runs/fix-log.md") lines)" >&2
fi

echo "EPILOGUE_STRATEGY=$EPILOGUE_STRATEGY"

# --- Step 4.5: Cross-file coherence lint (cached, gated, warn-only) ---
# Runs verify-linter.sh in --warn-only mode, writing findings to a cache file
# that observation-phase Step 5b-coherence reads. Gated on:
#   (a) cache miss (no prior run), OR
#   (b) template files (.claude/) changed on this branch since last run
# Cache key: git rev-parse HEAD:.claude/  (content-addressed, not mtime)
# Findings are folded into observe-result.json downstream — never blocks here.
COHERENCE_CACHE="$PROJECT_DIR/.runs/template-coherence-cache.json"
if [[ -z "${SKIP_COHERENCE_LINT:-}" ]]; then
  TEMPLATE_HASH=$(git rev-parse HEAD:.claude/ 2>/dev/null || echo "uncommitted")
  CACHED_HASH=""
  if [[ -f "$COHERENCE_CACHE" ]]; then
    CACHED_HASH=$(python3 -c "import json; print(json.load(open('$COHERENCE_CACHE')).get('template_hash',''))" 2>/dev/null || echo "")
  fi
  DIFF_TOUCHES_TEMPLATE="no"
  if [[ -n "$HAS_BRANCH" ]] && [[ -n "${MERGE_BASE:-}" ]]; then
    if git diff "$MERGE_BASE"...HEAD --name-only 2>/dev/null | grep -q '^\.claude/'; then
      DIFF_TOUCHES_TEMPLATE="yes"
    fi
  fi
  if [[ "$TEMPLATE_HASH" != "$CACHED_HASH" ]] || [[ "$DIFF_TOUCHES_TEMPLATE" == "yes" ]]; then
    # AOC v1: --strict-aoc escalates aoc-verdict-vocab-consistency /
    # aoc-fix-ledger-ownership / aoc-consumer-coverage findings to blocking
    # regardless of --warn-only. Other drift classes continue as warn-only
    # discovery. See .claude/patterns/agent-output-contract.md.
    LINTER_EXIT=0
    bash "$PROJECT_DIR/.claude/scripts/verify-linter.sh" --warn-only --strict-aoc --cache "$COHERENCE_CACHE" >/dev/null 2>&1 || LINTER_EXIT=$?
    # Annotate cache with the hash that produced it (so next run can compare)
    if [[ -f "$COHERENCE_CACHE" ]]; then
      python3 -c "
import json
d = json.load(open('$COHERENCE_CACHE'))
d['template_hash'] = '$TEMPLATE_HASH'
json.dump(d, open('$COHERENCE_CACHE', 'w'), indent=2)
" 2>/dev/null || true
    fi
    if [[ "$LINTER_EXIT" -ne 0 ]]; then
      echo "BLOCK: AOC v1 coherence violation (aoc-verdict-vocab-consistency / aoc-fix-ledger-ownership / aoc-consumer-coverage)." >&2
      bash "$PROJECT_DIR/.claude/scripts/verify-linter.sh" --strict-aoc 2>&1 | tail -40 >&2 || true
      echo "Re-run: bash .claude/scripts/verify-linter.sh --strict-aoc" >&2
      exit 1
    fi
  fi

  # Sibling lint (warn-only): scan init-context.sh callers for protected-field
  # drops (the dead-code symptom that produced #1160). Findings written to
  # .runs/init-context-caller-findings.jsonl; never blocks. Phase E2 of
  # canonical-writer-policy work.
  bash "$PROJECT_DIR/.claude/scripts/check-init-context-callers.sh" 2>/dev/null || true

  # Worktree-ownership pattern (issue #1200): blocking. Asserts that every
  # command file calling EnterWorktree also has the canonical IN_WORKTREE
  # detection block + worktree_owner ownership flag + conditional ExitWorktree;
  # and that no state file calls EnterWorktree (Rule 13 forbids it).
  if ! python3 "$PROJECT_DIR/.claude/scripts/check-worktree-ownership-pattern.py" >&2; then
    echo "BLOCK: worktree-ownership-pattern violation (issue #1200)." >&2
    echo "Re-run: python3 .claude/scripts/check-worktree-ownership-pattern.py" >&2
    exit 1
  fi

  # Worktree-boundary hook registration (issue #1225): blocking. Asserts that
  # worktree-boundary-gate.sh exists and is registered under Write, Edit,
  # MultiEdit, and NotebookEdit PreToolUse matchers in settings.json.
  if ! python3 "$PROJECT_DIR/.claude/scripts/check-worktree-boundary-hook-registered.py" >&2; then
    echo "BLOCK: worktree-boundary-hook-registered violation (issue #1225)." >&2
    echo "Re-run: python3 .claude/scripts/check-worktree-boundary-hook-registered.py" >&2
    exit 1
  fi

  # NOTE: Retrospective-completeness gate (#1276) was MOVED from this script
  # to .claude/scripts/check-observation-artifacts.sh. lifecycle-finalize.sh
  # runs in state-99 Step 1, BEFORE observation-phase Step 5a writes
  # retrospective-result.json (which happens in state-99 Step 2). Wiring the
  # gate here always SKIPped because the file doesn't exist yet. The gate
  # now lives at the correct point: check-observation-artifacts.sh, which
  # runs in state-99 Step 2a (after observation completes).
fi

# --- Step 4.5b: PII-in-FakeDoor recurrence guard (issue #1326) ---
# Runs the bash smoke test that scans
# .claude/{stacks,procedures,skills,agents,templates}/ AND src/{app,commands}/
# for activate-event tracking calls that include user PII (email/phone) as
# event properties. Catches:
#   1. Template-side recurrence (a future stack-file edit re-introducing the shape).
#   2. Downstream-MVP migration debt (projects that bootstrapped FakeDoor pre-fix
#      have stale src/app/<page>/<component>.tsx; /upgrade does not auto-update
#      project-owned files).
# Skip via SKIP_PII_FAKEDOOR_GUARD=1 (escape hatch for the post-fix soak window
# or for downstream MVPs that have a planned migration window).
PII_GUARD="$PROJECT_DIR/.claude/scripts/tests/no-pii-in-fakedoor-track-call.sh"
if [[ -z "${SKIP_PII_FAKEDOOR_GUARD:-}" ]] && [[ -f "$PII_GUARD" ]]; then
  if ! bash "$PII_GUARD" >&2; then
    echo "BLOCK: PII-in-FakeDoor recurrence guard failed at lifecycle-finalize Step 4.5b." >&2
    echo "Re-run: bash $PII_GUARD" >&2
    exit 1
  fi
fi

# --- Step 4.6 prelude: derive SKILL_TYPE early ---
# Issue #1356: SKILL_TYPE was previously derived AFTER Step 4.6 (in the
# delivery preamble at Step 5), so Step 4.6's RMG v2 gate could not consult
# it. Derive once here and consume from both Step 4.6 (gate) and Step 5
# (delivery skip). Fail-closed on read error: empty SKILL_TYPE falls through
# to existing gates so a malformed frontmatter does not silently bypass.
#
# Contract: any new gate that enforces SKILL_TYPE-sensitive constraints
# (defect-only checks, code-writing-only checks) MUST consult $SKILL_TYPE
# and branch on `analysis-only`. /solve --defect emits forward-looking
# recurrence guards; the next /resolve cycle materializes the artifact.
SKILL_TYPE=""
SKILL_CMD_FILE="$PROJECT_DIR/.claude/commands/$BASE_SKILL.md"
if [[ -f "$SKILL_CMD_FILE" ]]; then
  SKILL_TYPE=$(python3 -c "
import sys, re
try:
    txt = open(sys.argv[1]).read()
    m = re.match(r'---\n(.*?)\n---', txt, re.DOTALL)
    if m:
        for line in m.group(1).splitlines():
            k, _, v = line.partition(':')
            if k.strip() == 'type':
                print(v.strip().strip('\"\\''))
                break
except Exception:
    pass
" "$SKILL_CMD_FILE" 2>/dev/null || echo "")
fi

# --- Step 4.6: RMG v2 typed-guard artifact existence + advisory recurrence detector ---
# Runs only when .runs/solve-trace.json exists AND prevention_analysis.problem_type
# == "defect". Two responsibilities:
#
#   1. Verify the typed recurrence_guard parses via
#      .claude/scripts/lib/recurrence_guard_parser.py (Phase A). When the guard's
#      kind is in {test, lint, hook, invariant}, assert its `artifact` path is
#      either present in the PR diff (git diff <merge_base>...HEAD --name-only)
#      or already on disk in the repo. When kind=none, assert
#      `unguardability_rationale` is present and non-trivial. Failure BLOCKS
#      delivery. This is the layer that turned recurrence_guard from a
#      documented intent into an enforced artifact.
#
#   1b. Issue #1356: when SKILL_TYPE=analysis-only, pass --analysis-only to the
#       verifier. The flag skips path 1 (artifact-in-diff) because analysis-only
#       skills (e.g. /solve --defect) emit forward-looking guards — the
#       artifact is materialized by the NEXT /resolve cycle, not this one.
#       The kind=none rationale check (path 2) STILL runs unconditionally so
#       analysis-only skills cannot ship `kind=none` without a real rationale.
#
#   2. Best-effort: invoke the recurrence-detector (Phase B) in advisory mode.
#      Wrapped in `set +e` — any non-zero exit logs a warning and is ignored
#      so a flaky detector cannot block delivery (per plan: detector is
#      additive, not load-bearing).
#
# This step exists at lifecycle-finalize time (post-build, pre-PR) rather than
# in adversarial-merge-gate.sh because the hook fires PreToolUse Write/Edit
# when the PR does not yet exist (`gh pr diff` is unavailable). Plan note R2-A7.
SOLVE_TRACE="$PROJECT_DIR/.runs/solve-trace.json"
if [[ -f "$SOLVE_TRACE" ]]; then
  IS_DEFECT=$(python3 -c "
import json
try:
    d = json.load(open('$SOLVE_TRACE'))
    pa = d.get('prevention_analysis') or {}
    print('1' if pa.get('problem_type') == 'defect' else '0')
except Exception:
    print('0')
" 2>/dev/null || echo "0")

  if [[ "$IS_DEFECT" == "1" ]]; then
    MERGE_BASE_REF="${MERGE_BASE:-}"
    if [[ -z "$MERGE_BASE_REF" ]]; then
      MERGE_BASE_REF=$(git -C "$PROJECT_DIR" merge-base "origin/$DEFAULT_BRANCH" HEAD 2>/dev/null || echo "$DEFAULT_BRANCH")
    fi
    RMG_FLAGS=()
    if [[ "$SKILL_TYPE" == "analysis-only" ]]; then
      RMG_FLAGS+=(--analysis-only)
      echo "INFO: Step 4.6 invoking RMG v2 verifier with --analysis-only ($SKILL is analysis-only; forward-looking guard accepted, kind=none rationale still enforced)" >&2
    fi
    # Defensive expansion: bash 3.2 set -u errors on `"${arr[@]}"` when arr is
    # empty. Use `"${arr[@]+...}"` form (consistent with check-observation-
    # artifacts.sh:390 precedent) so an empty RMG_FLAGS expands to nothing
    # without tripping unbound-variable.
    if ! python3 "$PROJECT_DIR/.claude/scripts/verify-rmg-guard-artifact-in-diff.py" \
          --trace "$SOLVE_TRACE" \
          --merge-base "$MERGE_BASE_REF" \
          "${RMG_FLAGS[@]+"${RMG_FLAGS[@]}"}" >&2; then
      echo "BLOCK: RMG v2 typed-guard artifact check failed at lifecycle-finalize Step 4.6." >&2
      echo "Re-run: python3 .claude/scripts/verify-rmg-guard-artifact-in-diff.py --trace .runs/solve-trace.json --merge-base \$(git merge-base origin/$DEFAULT_BRANCH HEAD)" >&2
      exit 1
    fi
  fi
fi

# Advisory recurrence-detector: never blocks. Its output is consumed by Phase 1a
# dossier on the NEXT defect run; this run does not depend on the result.
set +e
PROJECT_DIR="$PROJECT_DIR" python3 "$PROJECT_DIR/.claude/scripts/recurrence-detector.py" \
  --advisory-only >/dev/null 2>&1
RECDET_RC=$?
set -e
if [[ $RECDET_RC -ne 0 ]]; then
  echo "WARN: recurrence-detector exited $RECDET_RC (advisory only — does not block)" >&2
fi

# --- Step 4.7: design-critic post-fix re-spawn obligation gate (#1274) ---
# When the lead applied a shared-component fix at state-3a Stage 1b OR
# ux-journeyer touched a UI file in state-3c, every per-page design-critic
# trace whose `shared_issues[*].file` or `reviewed_files` overlap the
# fixed file MUST be superseded by a `--epoch>=1` re-evaluation trace
# with verdict in {pass, fixed}. Otherwise the merged design-critic.json
# carries a stale unresolved verdict that no longer reflects current
# rendered state. The gate is conditional: when no fix-ledger lead-fix
# entries exist AND ux-journeyer trace has no UI-touching fixes, it is
# a no-op (returns 0 immediately).
if [[ -d "$PROJECT_DIR/.runs/agent-traces" ]]; then
  if ! python3 "$PROJECT_DIR/.claude/scripts/verify-design-critic-post-fix-respawn.py" \
        --project-dir "$PROJECT_DIR" >&2; then
    echo "BLOCK: design-critic post-fix re-spawn check failed at lifecycle-finalize Step 4.7." >&2
    echo "Re-run: python3 .claude/scripts/verify-design-critic-post-fix-respawn.py" >&2
    exit 1
  fi
fi

# --- Step 4.8: lead-orchestrated trace ↔ spawn-log lineage gate (#1275) ---
# Every trace with `provenance: lead-orchestrated` must be anchored to a
# non-degraded spawn-log entry written by skill-agent-gate.sh's
# SOURCE_RUN_ID/SOURCE_SKILL honoring path. Without this, a forged trace
# claiming arbitrary `source_run_id` could pass the writer's R3 check
# (which accepts degraded entries) and look identical to a legitimate
# post-completion re-spawn. The gate is conditional: when no
# lead-orchestrated traces exist, it is a no-op.
if [[ -d "$PROJECT_DIR/.runs/agent-traces" ]]; then
  if ! python3 "$PROJECT_DIR/.claude/scripts/verify-lead-orchestrated-spawn-log-lineage.py" \
        --project-dir "$PROJECT_DIR" >&2; then
    echo "BLOCK: lead-orchestrated trace lineage check failed at lifecycle-finalize Step 4.8." >&2
    echo "Re-run: python3 .claude/scripts/verify-lead-orchestrated-spawn-log-lineage.py" >&2
    exit 1
  fi
fi

# --- Step 4.9: lead-deviation-log write-failures observation (PR 2 — warn) ---
# When .runs/lead-deviation-log.write-failures.jsonl is non-empty, the
# atomic appender (append_deviation_log.py) failed to write a deviation
# entry — a silent observability gap. PR 2 lands warn (logs + continues);
# PR 3 will flip to deny after 1-2 weeks of stable operation. Soak data
# accumulates in the same file the deny-mode check would block on.
WF_PATH="$PROJECT_DIR/.runs/lead-deviation-log.write-failures.jsonl"
if [[ -s "$WF_PATH" ]]; then
  WF_COUNT=$(wc -l < "$WF_PATH" 2>/dev/null | tr -d ' ' || echo 0)
  echo "WARN: lifecycle-finalize Step 4.9 (PR 2): $WF_COUNT lead-deviation-log write-failures detected at $WF_PATH (warn mode; PR 3 will flip to deny after observation)" >&2
  # PR 3 will replace the warn block with: exit 1 to enforce.
fi

# --- Step 4.10: agent-trace-schema-completeness gate #7 (PR 2 — warn) ---
# AOC v1.3: every trace-writing agent MUST emit workarounds[] and
# template_gap_observed[] keys (empty-array defaults allowed). The validator
# scans .runs/agent-traces/*.json for the active run, logs missing-field
# violations to .runs/lead-deviation-log.jsonl. PR 2 lands warn mode
# (validator-extension); PR 3 flips warn→deny after 1-2 weeks observation.
# Mode resolution via prose_gate_mode.resolve("agent-trace-schema-completeness").
if [[ -d "$PROJECT_DIR/.runs/agent-traces" ]]; then
  python3 "$PROJECT_DIR/.claude/scripts/lib/agent-trace-schema-validator.py" >/dev/null 2>&1 || true
fi

# --- Step 5: Delivery (code-writing skills + deliberate record deliveries) ---
DELIVERY_STATUS="none"
COMMIT_MSG="$PROJECT_DIR/.runs/commit-message.txt"
PR_TITLE="$PROJECT_DIR/.runs/pr-title.txt"
PR_BODY="$PROJECT_DIR/.runs/pr-body.md"
SKIP_FLAG="$PROJECT_DIR/.runs/delivery-skip.flag"

# SKILL_TYPE was already derived at the Step 4.6 prelude above. Reuse it here.
# Skill-type gate — analysis-only skills skip delivery when they produced no
# delivery artifacts. The #1004 stale-artifact hazard this gate originally
# closed is now handled upstream: lifecycle-init deletes all delivery
# artifacts at the start of every non-embed run, so commit-message.txt present
# here was written during THIS run — a deliberate record delivery (e.g.
# iterate-cross committing its config + decision-ledger mutations). The
# branch guard below enforces PR-first for it. Fail-open on read error:
# SKILL_TYPE empty falls through to existing gates so a malformed frontmatter
# does not block legitimate code-writing skills.
if [[ "$SKILL_TYPE" == "analysis-only" && ! -f "$COMMIT_MSG" ]]; then
  echo "INFO: $SKILL is analysis-only with no delivery artifacts — skipping delivery" >&2
  DELIVERY_STATUS="skipped-analysis-only"
  echo "DELIVERY=skipped-analysis-only"
elif [[ -f "$SKIP_FLAG" ]]; then
  echo "INFO: delivery-skip.flag present — skipping delivery" >&2
  DELIVERY_STATUS="skipped"
  echo "DELIVERY=skipped"
elif [[ -f "$COMMIT_MSG" ]]; then
  # --- Delivery gates ---
  GATE_ERRORS=()

  # Gate 1: verify-report.md frontmatter validation (if exists)
  REPORT="$PROJECT_DIR/.runs/verify-report.md"
  if [[ -f "$REPORT" ]]; then
    python3 -c "
import sys
c = open('$REPORT').read()
if not c.startswith('---'):
    print('verify-report.md missing frontmatter delimiters', file=sys.stderr); sys.exit(1)
parts = c.split('---', 2)
if len(parts) < 3:
    print('verify-report.md malformed frontmatter', file=sys.stderr); sys.exit(1)
fm = parts[1]
for field in ['overall_verdict:', 'hard_gate_failure:', 'process_violation:', 'agents_expected:', 'agents_completed:']:
    if field not in fm:
        print('verify-report.md missing %s' % field, file=sys.stderr); sys.exit(1)
" 2>&1 || GATE_ERRORS+=("verify-report.md frontmatter validation failed")
  fi

  # Gate 2: gate-verdicts scan for BLOCK
  if [[ -d "$PROJECT_DIR/.runs/gate-verdicts" ]]; then
    BLOCK_FOUND=$(python3 -c "
import json, glob
blocked = []
for f in glob.glob('$PROJECT_DIR/.runs/gate-verdicts/*.json'):
    try:
        d = json.load(open(f))
        if d.get('verdict') == 'BLOCK':
            blocked.append(f.split('/')[-1])
    except: pass
print(' '.join(blocked) if blocked else '')
" 2>/dev/null || echo "")
    if [[ -n "$BLOCK_FOUND" ]]; then
      GATE_ERRORS+=("BLOCK verdict found in: $BLOCK_FOUND")
    fi
  fi

  # Gate 3: observe-result.json validation (if exists)
  if [[ -f "$PROJECT_DIR/.runs/observe-result.json" ]]; then
    python3 -c "
import json, sys
d = json.load(open('$PROJECT_DIR/.runs/observe-result.json'))
if not d.get('verdict'):
    print('observe-result.json missing verdict', file=sys.stderr); sys.exit(1)
if d.get('verdict') == 'error':
    reason = d.get('error_reason', 'unknown')
    print('observe-result.json verdict is error: %s' % reason, file=sys.stderr); sys.exit(1)
" 2>&1 || GATE_ERRORS+=("observe-result.json validation failed")
  fi

  # Gate 4: build-result.json (if exists and no verify-report)
  if [[ ! -f "$REPORT" && -f "$PROJECT_DIR/.runs/build-result.json" ]]; then
    python3 -c "
import json, sys
d = json.load(open('$PROJECT_DIR/.runs/build-result.json'))
if d.get('exit_code') != 0:
    print('build exit_code=%s' % d.get('exit_code'), file=sys.stderr); sys.exit(1)
" 2>&1 || GATE_ERRORS+=("build-result.json exit_code != 0")
  fi

  if [[ ${#GATE_ERRORS[@]} -gt 0 ]]; then
    echo "ERROR: Delivery gate failed:" >&2
    for e in "${GATE_ERRORS[@]}"; do
      echo "  - $e" >&2
    done
    exit 1
  fi

  # --- Delivery branch guard (issue #1990) ---
  # Refuses to commit on the default branch: creates a chore/<skill>-delivery-*
  # branch when needed (lib/delivery-branch-guard.sh). Every failure from here
  # on degrades to a recorded delivery status instead of aborting the script —
  # Steps 6/7 must always run (the #1990 incident aborted mid-Step-5 after the
  # push had already landed).
  DELIVERY_HALT=""
  GUARD_OUT=""
  if ! GUARD_OUT=$(bash "$PROJECT_DIR/.claude/scripts/lib/delivery-branch-guard.sh" "$SKILL" "$DEFAULT_BRANCH"); then
    echo "WARN: delivery branch guard could not guarantee a safe branch — delivery halted before any commit" >&2
    DELIVERY_HALT="branch-guard-failed"
  elif [[ "$GUARD_OUT" == "GUARD=skip-no-changes" ]]; then
    echo "INFO: clean tree on $DEFAULT_BRANCH in sync with origin — nothing to deliver" >&2
    DELIVERY_HALT="skipped-no-changes"
  elif [[ "$GUARD_OUT" == GUARD=branched:* ]]; then
    echo "INFO: delivery branch guard created ${GUARD_OUT#GUARD=branched:}" >&2
  fi
  if [[ -z "$DELIVERY_HALT" && "$SKILL_TYPE" == "analysis-only" ]]; then
    echo "INFO: analysis-only $SKILL supplied fresh delivery artifacts — treating as deliberate record delivery (PR-first enforced by the branch guard)" >&2
  fi

  # --- Git delivery ---
  if [[ -z "$DELIVERY_HALT" ]]; then
    git add -A
    if ! git diff --cached --quiet 2>/dev/null; then
      if ! git commit -m "$(cat "$COMMIT_MSG")"; then
        echo "WARN: git commit failed — delivery halted" >&2
        DELIVERY_HALT="commit-failed"
      fi
    fi
  fi
  if [[ -z "$DELIVERY_HALT" ]]; then
    # Large initial commits (bootstrap: 170+ files) can exceed default http.postBuffer (1MB)
    git config --local http.postBuffer 52428800  # 50MB
    if ! git push -u origin HEAD; then
      echo "WARN: git push failed — delivery halted (commit remains local)" >&2
      DELIVERY_HALT="push-failed"
    fi
  fi

  # --- PR creation (only if pr-title.txt exists) ---
  if [[ -n "$DELIVERY_HALT" ]]; then
    DELIVERY_STATUS="$DELIVERY_HALT"
    echo "DELIVERY=$DELIVERY_HALT"
  elif [[ -f "$PR_TITLE" ]]; then
    PR_TITLE_VAL=$(cat "$PR_TITLE")

    # --- Auto-merge (per .claude/patterns/auto-merge.md) ---
    SKIP_MERGE=""
    PR_CREATE_FAILED=""
    if ! gh pr create --title "$PR_TITLE_VAL" --body-file "$PR_BODY"; then
      # The push already landed; a PR-create failure must not abort the script.
      echo "WARN: gh pr create failed — branch is pushed; open the PR manually" >&2
      PR_CREATE_FAILED="true"
      SKIP_MERGE="pr-create-failed"
    fi

    # Guard 1: Migration guard
    if [[ -z "$SKIP_MERGE" ]] && gh pr diff --name-only 2>/dev/null | grep -q '^supabase/migrations/'; then
      echo "INFO: PR contains database migrations — skipping auto-merge" >&2
      SKIP_MERGE="migrations"
    fi

    # Guard 2: Secret scan (graceful)
    if [[ -z "$SKIP_MERGE" ]] && command -v gitleaks >/dev/null 2>&1; then
      if ! gitleaks detect --source . --no-banner --exit-code 1 2>/dev/null; then
        echo "INFO: gitleaks detected potential secrets — skipping auto-merge" >&2
        SKIP_MERGE="gitleaks"
      fi
    fi

    # Guard 3: template-lint parity. Runs the same validators CI runs on
    # template files. Dispatches by diff type to keep the common case fast:
    #   - .claude/ / .github/workflows/ / Makefile touched -> make lint-template (~1-3s)
    #   - scripts/ touched (validator code or shell tools) -> make lint-template-full (~50s, includes pytest)
    #   - pure src/ -> skip (covered by local /verify)
    #   - diff detection fails -> run lint-template-full (fail-closed)
    # Uses git diff (local, no network) instead of gh pr diff (silent-fails on
    # auth/network blip and would bypass the gate, same class as the bug we fixed).
    # DO_NOT add --auto to the merge command below: repo allow_auto_merge=false
    # makes --auto silently become an immediate non-gated merge. See issue #1003
    # and feedback_gh_pr_merge_auto_fallback memory.
    if [[ -z "$SKIP_MERGE" ]] && command -v make >/dev/null 2>&1; then
      LINT_TARGET=""
      MERGE_BASE=$(git merge-base "origin/$DEFAULT_BRANCH" HEAD 2>/dev/null || git merge-base "$DEFAULT_BRANCH" HEAD 2>/dev/null || echo "")
      if [[ -z "$MERGE_BASE" ]]; then
        LINT_TARGET="lint-template-full"
        echo "INFO: merge-base not resolvable — running lint-template-full (fail-closed)" >&2
      else
        DIFF_FILES=$(git diff --name-only "$MERGE_BASE..HEAD" 2>/dev/null || echo "")
        if [[ -z "$DIFF_FILES" ]]; then
          LINT_TARGET="lint-template-full"
          echo "INFO: diff empty/unreadable — running lint-template-full (fail-closed)" >&2
        elif echo "$DIFF_FILES" | grep -qE '^scripts/'; then
          LINT_TARGET="lint-template-full"
        elif echo "$DIFF_FILES" | grep -qE '^\.claude/|^\.github/workflows/|^Makefile$'; then
          LINT_TARGET="lint-template"
        fi
      fi
      if [[ -n "$LINT_TARGET" ]]; then
        if ! make "$LINT_TARGET" >&2; then
          echo "INFO: make $LINT_TARGET failed — skipping auto-merge" >&2
          SKIP_MERGE="template-lint"
        fi
      fi
    fi

    # Merge
    if [[ -z "$SKIP_MERGE" ]]; then
      FEATURE_BRANCH=$(git branch --show-current)
      if [[ "$(bash .claude/scripts/lib/in-worktree.sh)" == "true" ]]; then
        gh pr merge --squash || {
          echo "WARN: gh pr merge failed — PR left open" >&2
          SKIP_MERGE="merge-failed"
        }
      else
        gh pr merge --squash --delete-branch || {
          echo "WARN: gh pr merge failed — PR left open" >&2
          SKIP_MERGE="merge-failed"
        }
      fi
    fi

    # Post-merge (FEATURE_BRANCH captured just before the merge above). A
    # checkout/pull failure here must not abort Steps 6/7 — warn and continue.
    if [[ -z "$SKIP_MERGE" && "$(bash .claude/scripts/lib/in-worktree.sh)" == "false" ]]; then
      { git checkout "$DEFAULT_BRANCH" && git pull; } || \
        echo "WARN: post-merge checkout/pull of $DEFAULT_BRANCH failed — resolve manually" >&2
      git branch -d "$FEATURE_BRANCH" 2>/dev/null || true
    fi

    if [[ -n "$PR_CREATE_FAILED" ]]; then
      DELIVERY_STATUS="pr-create-failed"
      echo "DELIVERY=pr-create-failed"
    elif [[ -z "$SKIP_MERGE" ]]; then
      DELIVERY_STATUS="merged"
      echo "DELIVERY=merged"
    else
      DELIVERY_STATUS="pr-created:$SKIP_MERGE"
      echo "DELIVERY=pr-created:$SKIP_MERGE"
    fi
  else
    # commit+push only — no PR (bootstrap pattern)
    DELIVERY_STATUS="pushed"
    echo "DELIVERY=pushed"
  fi
else
  # No delivery artifacts — analysis skill
  echo "DELIVERY=none"
fi

# --- Step 6: Write verify-recheck.json for remediation phase ---
# Assembles final structured artifact from Step 2 raw results + missing states + delivery status.
python3 -c "
import json, sys, os

project_dir = '$PROJECT_DIR'
ctx_path = '$CTX'
manifest_path = '$MANIFEST'
delivery_status = '$DELIVERY_STATUS'

result = {
    'skill': '$SKILL',
    'missing_states': [],
    'verify_results': [],
    'total': 0,
    'passed': 0,
    'failed': 0,
    'delivery_status': delivery_status
}

# Read raw verify results from Step 2
raw_path = os.path.join(project_dir, '.runs/.verify-results-raw.json')
if os.path.isfile(raw_path):
    try:
        result['verify_results'] = json.load(open(raw_path))
        result['total'] = len(result['verify_results'])
        result['passed'] = sum(1 for r in result['verify_results'] if r.get('passed'))
        result['failed'] = result['total'] - result['passed']
    except: pass

# Compute missing_states (same logic as Step 1)
try:
    ctx = json.load(open(ctx_path))
    completed = set(str(s) for s in ctx.get('completed_states', []))
    skip = set(str(s) for s in ctx.get('skip_states', []))
    manifest = json.load(open(manifest_path))
    if 'active_mode' in manifest and 'modes' in manifest:
        states = manifest['modes'][manifest['active_mode']]['states']
    else:
        states = manifest.get('states', [])
    result['missing_states'] = [str(s) for s in states if str(s) not in completed and str(s) not in skip]
except: pass

outpath = os.path.join(project_dir, '.runs/verify-recheck.json')
try:
    json.dump(result, open(outpath, 'w'), indent=2)
    print('INFO: Wrote verify-recheck.json (%d passed, %d failed)' % (result['passed'], result['failed']), file=sys.stderr)
except Exception as e:
    print('WARN: Failed to write verify-recheck.json: %s' % e, file=sys.stderr)
" || echo "WARN: verify-recheck.json assembly failed — remediation phase will have no structured input" >&2

# --- Step 7: Teardown transient local services started by this skill ---
# Stops skill-owned Supabase stacks matching the current run_id (or an ancestor
# run_id for /change->embed /verify). No-op in CI and when the stack combo is
# not supabase+playwright. See .claude/scripts/stop-transient-services.sh.
# Writes <git-common-dir>/finalize-completed-<run_id>.flag AFTER stop succeeds
# so that a crash between Step 6 and Step 7 is detected by the next skill's
# lifecycle-init.sh Step 0.5.
TEARDOWN_RUN_ID=$(python3 -c "import json; print(json.load(open('$CTX')).get('run_id',''))" 2>/dev/null || echo "")
TEARDOWN_COMMON_DIR=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null || echo "")
if [[ -n "$TEARDOWN_RUN_ID" && -n "$TEARDOWN_COMMON_DIR" ]]; then
  bash "$PROJECT_DIR/.claude/scripts/stop-transient-services.sh" --for-run "$TEARDOWN_RUN_ID" 2>&1 | sed 's/^/[teardown] /' || \
    echo "WARN: transient-service teardown failed (non-blocking)" >&2
  touch "$TEARDOWN_COMMON_DIR/finalize-completed-$TEARDOWN_RUN_ID.flag" 2>/dev/null || true
fi

echo "FINALIZE_COMPLETE"
