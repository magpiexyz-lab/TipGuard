#!/usr/bin/env bash
# verify-pr-gate.sh — Claude Code PreToolUse hook for Bash commands.
# Blocks `gh pr create` unless verify-report.md passes integrity checks.

set -euo pipefail

source "$(dirname "$0")/lib.sh"
parse_payload

COMMAND=$(read_payload_field "tool_input.command")

# Match `gh pr create` only as an actual command head — anchored at start
# of $COMMAND or after a shell separator (;, &, |), with whitespace-
# tolerant token boundaries. Bare substring (#1366) false-fires on grep
# patterns, heredoc prose, JSON literals, and env-var assignments.
if [[ ! "$COMMAND" =~ (^|[;\&\|])[[:space:]]*gh[[:space:]]+pr[[:space:]]+create([[:space:]]|$) ]]; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

# --- PR creation detected — run verification checks ---

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
REPORT="$PROJECT_DIR/.runs/verify-report.md"
TRACES_DIR="$PROJECT_DIR/.runs/agent-traces"
ERRORS=()
BRANCH=$(get_branch)

# --- PR check functions ---
# Each function maps to a pr_checks entry in skill.yaml observation config.
# Inputs are passed as parameters; ERRORS is the only top-level state read or
# written by check functions (it's the explicit aggregator drained by deny_errors
# in lib-core.sh). Function ordering in the dispatch loop below is therefore
# safe to change — no implicit data dependency between checks.

# load_report_frontmatter <report>
# Pure helper: prints the YAML frontmatter body (between leading and trailing
# `---` markers) to stdout, or empty on missing file / missing leading marker.
# Mirrors check_frontmatter's existing parse so values are byte-identical.
load_report_frontmatter() {
  local report="$1"
  [[ ! -f "$report" ]] && return 0
  head -1 "$report" | grep -q '^---$' || return 0
  sed -n '2,/^---$/p' "$report" | sed '$d'
}

# check_frontmatter <report> <frontmatter> <project_dir>
# Validates verify-report.md exists, has a YAML frontmatter block, and that
# the frontmatter does not signal process_violation or hard_gate_failure
# (the latter only blocks outside standalone mode).
check_frontmatter() {
  local report="$1"
  local frontmatter="$2"
  local project_dir="$3"

  if [[ ! -f "$report" ]]; then
    ERRORS+=("verify-report.md not found — run /verify first")
    return
  elif ! head -1 "$report" | grep -q '^---$'; then
    ERRORS+=("verify-report.md missing YAML frontmatter")
    return
  fi

  local violation
  violation=$(echo "$frontmatter" | grep 'process_violation: *true' || true)
  if [[ -n "$violation" ]]; then
    ERRORS+=("process_violation is true in verify-report.md — verification agents were skipped")
  fi

  local hard_gate mode
  hard_gate=$(echo "$frontmatter" | grep 'hard_gate_failure: *true' || true)
  mode=$(read_json_field "$project_dir/.runs/verify-context.json" "mode")
  if [[ -n "$hard_gate" && "$mode" != "standalone" ]]; then
    ERRORS+=("hard_gate_failure is true — verification hard gate(s) failed; PR blocked in non-standalone mode")
  fi
}

# check_agent_match <report> <frontmatter>
# Compares agents_expected against agents_completed (sorted) in the
# pre-loaded frontmatter. Silently no-ops when the frontmatter is empty —
# preserves prior behavior when the report is missing or unparseable.
check_agent_match() {
  local report="$1"
  local frontmatter="$2"
  [[ ! -f "$report" || -z "$frontmatter" ]] && return
  local expected completed
  expected=$(echo "$frontmatter" | grep 'agents_expected:' | sed 's/agents_expected: *//' | tr -d '[]' | tr ',' '\n' | sed 's/^ *//;/^$/d' | sort)
  completed=$(echo "$frontmatter" | grep 'agents_completed:' | sed 's/agents_completed: *//' | tr -d '[]' | tr ',' '\n' | sed 's/^ *//;/^$/d' | sort)
  if [[ "$expected" != "$completed" ]]; then
    ERRORS+=("agents_expected does not match agents_completed in verify-report.md")
  fi
}

# check_trace_completeness <report> <frontmatter> <traces_dir>
# Manifest-based trace completeness: checks each agent in agents_completed
# has a matching trace file. Exact match: {agent}.json. Per-page glob:
# {agent}-*.json (e.g. design-critic-landing.json). Suffix-named independent
# agents (e.g. design-critic-shared) must have their own agents_completed entry.
check_trace_completeness() {
  local report="$1"
  local frontmatter="$2"
  local traces_dir="$3"
  [[ ! -f "$report" || -z "$frontmatter" ]] && return
  if [[ ! -d "$traces_dir" ]]; then
    ERRORS+=("Agent traces directory not found at $traces_dir")
    return
  fi

  local agents_str
  agents_str=$(echo "$frontmatter" | grep 'agents_completed:' | \
    sed 's/agents_completed: *//' | tr -d '[]' | tr ',' '\n' | \
    sed 's/^ *//;s/ *$//' | sed '/^$/d')

  while IFS= read -r agent; do
    [[ -z "$agent" ]] && continue
    if [[ -f "$traces_dir/${agent}.json" ]]; then
      continue
    elif ls "$traces_dir/${agent}"-*.json &>/dev/null; then
      continue
    else
      ERRORS+=("Missing trace for agent: $agent")
    fi
  done <<< "$agents_str"
}

# check_gate_verdicts_pr <project_dir> <branch>
# Thin wrapper over the lib check that verifies g4/g5/g6 gate verdicts are
# present and PASS for the current branch.
check_gate_verdicts_pr() {
  local project_dir="$1"
  local branch="$2"
  check_verdict_gates "g4 g5 g6" "$project_dir/.runs/gate-verdicts" "$branch"
}

# check_acceptance_criteria <project_dir>
# Parses acceptance_criteria from current-plan.md frontmatter and verifies each
# AC has either its declared test_file present (unit-test method) or a
# behavior-verifier trace recording the AC id (behavior-verifier method).
check_acceptance_criteria() {
  local project_dir="$1"
  local plan="$project_dir/.runs/current-plan.md"
  [[ ! -f "$plan" ]] && return

  local ac_result
  ac_result=$(python3 -c "
import sys, os, json, glob

content = open('$plan').read()
if not content.startswith('---'):
    # friction-skip: post-validation — SKIP signal — caller decides next action based on stdout
    print('SKIP'); sys.exit(0)
parts = content.split('---', 2)
if len(parts) < 3:
    # friction-skip: post-validation — SKIP signal — caller decides next action based on stdout
    print('SKIP'); sys.exit(0)

try:
    import yaml
    fm = yaml.safe_load(parts[1])
except ImportError:
    import re
    fm_text = parts[1]
    if 'acceptance_criteria:' not in fm_text:
        # friction-skip: post-validation — SKIP signal — caller decides next action based on stdout
        print('SKIP'); sys.exit(0)
    acs = []
    for m in re.finditer(r'-\s*id:\s*(\S+)\s*\n\s*behavior:.*?\n\s*verify_method:\s*(\S+)(?:\s*\n\s*test_file:\s*(\S+))?', fm_text):
        ac = {'id': m.group(1), 'verify_method': m.group(2)}
        if m.group(3): ac['test_file'] = m.group(3)
        acs.append(ac)
    fm = {'acceptance_criteria': acs if acs else None}
except Exception:
    # friction-skip: post-validation — SKIP signal — caller decides next action based on stdout
    print('SKIP'); sys.exit(0)

if not fm or not isinstance(fm, dict):
    # friction-skip: post-validation — SKIP signal — caller decides next action based on stdout
    print('SKIP'); sys.exit(0)

acs = fm.get('acceptance_criteria', None)
if not acs:
    # friction-skip: post-validation — SKIP signal — caller decides next action based on stdout
    print('SKIP'); sys.exit(0)

traces_dir = os.path.join('$project_dir', '.runs/agent-traces')
errors = []
for ac in acs:
    ac_id = ac.get('id', '?')
    method = ac.get('verify_method', '')
    if method == 'unit-test':
        tf = ac.get('test_file', '')
        if tf and not os.path.exists(os.path.join('$project_dir', tf)):
            errors.append(ac_id + ': test_file ' + tf + ' not found')
    elif method == 'behavior-verifier':
        found = False
        for f in glob.glob(os.path.join(traces_dir, 'behavior-verifier-*.json')):
            try:
                d = json.load(open(f))
                checks = d.get('checks_performed', [])
                if any(ac_id in str(c) for c in checks):
                    found = True; break
            except: pass
        if not found:
            errors.append(ac_id + ': no behavior-verifier trace found')

if errors:
    print('FAIL:' + '; '.join(errors))
else:
    print('OK')
" 2>/dev/null || echo "SKIP")

  if [[ "$ac_result" == FAIL:* ]]; then
    ERRORS+=("Acceptance criteria not met: ${ac_result#FAIL:}")
  fi
}

# check_review_metrics <project_dir>
# Confirms review-complete.json (when present) records review_complete=true.
check_review_metrics() {
  local project_dir="$1"
  local review_file="$project_dir/.runs/review-complete.json"
  [[ ! -f "$review_file" ]] && return
  local valid
  valid=$(python3 -c "
import json
d = json.load(open('$review_file'))
if d.get('review_complete') != True:
    print('FAIL: review_complete is not true')
else:
    print('OK')
" 2>/dev/null || echo "SKIP")
  if [[ "$valid" == FAIL:* ]]; then
    ERRORS+=("Review metrics: ${valid#FAIL: }")
  fi
}

# --- Data-driven skill dispatch ---
# Replaces branch-prefix if/elif chain. Skill identity comes from context
# files; check lists come from skill.yaml observation config.
SKILL=$(detect_skill_for_branch "$BRANCH")
if [[ -z "$SKILL" ]]; then
  # friction-skip: post-validation — exit follows authoritative decision (allow-list match, deny path, or successful validation)
  exit 0  # Not skill-driven — allow PR
fi

GATE_ARTIFACTS=$(get_observation_gate "$SKILL" "gate_artifacts")
PR_CHECKS=$(get_observation_gate "$SKILL" "pr_checks")
GATE_MECH=$(get_observation_gate "$SKILL" "gate_mechanism")

# Check gate artifacts exist
if [[ -n "$GATE_ARTIFACTS" ]]; then
  for artifact in $GATE_ARTIFACTS; do
    if [[ ! -f "$PROJECT_DIR/.runs/$artifact" ]]; then
      ERRORS+=("$artifact not found — /$SKILL must produce this before PR")
    fi
  done
fi

# Universal: check skill completion for all commit-pr-gate skills
check_skill_completion "$SKILL" "$PROJECT_DIR/.runs/${SKILL}-context.json"

# Fallback for skills without observation config in skill.yaml
if [[ -z "$GATE_MECH" ]]; then
  if [[ ! -f "$PROJECT_DIR/.runs/observe-result.json" ]]; then
    ERRORS+=("observe-result.json not found — /$SKILL must complete observation before PR")
  fi
else
  # Pre-load frontmatter once so check_* functions are order-independent.
  # All check functions take their inputs as parameters; FRONTMATTER must be
  # threaded explicitly. To add a check: define `check_foo(<args>)`, add a
  # case branch below, thread args from the top-level constants.
  FRONTMATTER=$(load_report_frontmatter "$REPORT")

  # Dispatch pr_checks from registry
  for check in $PR_CHECKS; do
    case "$check" in
      frontmatter-validation) check_frontmatter      "$REPORT" "$FRONTMATTER" "$PROJECT_DIR" ;;
      trace-completeness)     check_trace_completeness "$REPORT" "$FRONTMATTER" "$TRACES_DIR" ;;
      agent-match)            check_agent_match      "$REPORT" "$FRONTMATTER" ;;
      postcondition-rerun)    rerun_postconditions   "$SKILL" ;;
      gate-verdicts)          check_gate_verdicts_pr "$PROJECT_DIR" "$BRANCH" ;;
      acceptance-criteria)    check_acceptance_criteria "$PROJECT_DIR" ;;
      review-metrics)         check_review_metrics   "$PROJECT_DIR" ;;
    esac
  done
fi

# Universal: observation verdict integrity (covers embed:verify skills
# that bypass observe-commit-gate via verify-report.md exemption)
if [[ -f "$PROJECT_DIR/.runs/observe-result.json" ]]; then
  check_verdict_error
  check_fixlog_verdict_consistency
fi

# Universal: BLOCK verdict check (applies to all skill-driven PRs)
check_block_verdicts

# If any check failed, deny the PR creation
if [[ ${#ERRORS[@]} -gt 0 ]]; then
  deny_errors "PR gate blocked: " "Run /verify to complete verification before creating a PR."
fi

# All checks passed — allow
exit 0
