#!/usr/bin/env bash
# lib-verdict-consistency.sh — Verdict / fix-log consistency checks.
# Sourced via lib.sh facade. Do NOT source directly.
# Requires: ERRORS array (from caller).
# Cross-module: read_json_field (lib-core.sh).

# --- check_verdict_error ---
# Unconditionally rejects verdict "error" in observe-result.json.
# Placed BEFORE check_verdict_consistency because that function has early-return
# guards on diffs existence — process-scope skills (e.g., /solve) with no diffs
# would bypass it. This function has NO early-return guards.
# Appends to global ERRORS array. Does not exit — caller decides.
# Usage: check_verdict_error
check_verdict_error() {
  local project_dir="${CLAUDE_PROJECT_DIR:-.}"
  local obs_file="$project_dir/.runs/observe-result.json"

  [[ ! -f "$obs_file" ]] && return 0

  local verdict
  verdict=$(read_json_field "$obs_file" "verdict")

  if [[ "$verdict" == "error" ]]; then
    local reason
    reason=$(read_json_field "$obs_file" "error_reason")
    ERRORS+=("Observation failed with verdict 'error': ${reason:-unknown reason}. Re-run the skill to retry observation.")
  fi
}

# --- check_fixlog_verdict_consistency (AOC v1 FLS v1 canonical) ---
# Blocks if: fix-ledger.jsonl has entries FOR THE CURRENT RUN but verdict is
# "clean" (not execution-audit). Catches the case where observation-phase.md
# was skipped but agents produced fixes that went unobserved IN THE SAME RUN.
#
# Provenance-aware (#1417b fix): cross-run ledger rows from prior runs are
# IGNORED. Single Python subprocess resolves identity + filters ledger.
# Three early-return paths:
#   NO_RUN_ID       — manual gh pr create with no in-flight skill (HC5).
#                     Pass through; nothing to be inconsistent with.
#   STALE_OBSERVE   — observe-result.run_id != current run_id (stale artifact
#                     from a prior run). Pass through.
#   OK              — current run identity resolved; ledger filtered to it.
# Only the OK path with count > 0 + verdict=clean appends an error.
#
# Appends to global ERRORS array. Does not exit — caller decides.
# Usage: check_fixlog_verdict_consistency
check_fixlog_verdict_consistency() {
  local project_dir="${CLAUDE_PROJECT_DIR:-.}"
  local obs_file="$project_dir/.runs/observe-result.json"
  local ledger="$project_dir/.runs/fix-ledger.jsonl"

  [[ ! -f "$obs_file" ]] && return 0

  local lib_dir
  lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../scripts/lib" 2>/dev/null && pwd || echo "$project_dir/.claude/scripts/lib")"

  local result
  result=$(python3 -c "
import sys, json
sys.path.insert(0, '$lib_dir')
from runs_reader import discover_current_run_id, read_jsonl

identity = discover_current_run_id(project_dir='$project_dir')
if not identity:
    print('NO_RUN_ID\t0\t')
    # friction-skip: trivial-fast-path — HC5 manual gh pr create has no active skill to attribute fix counts against; the result token signals 'pass-through' to the bash caller without bash-side exit
    sys.exit(0)

try:
    obs_rid = json.load(open('$obs_file')).get('run_id', '')
except Exception:
    obs_rid = ''
# Narrow-window guard: lifecycle-init.sh clears observe-result.json
# (it is in STALE_ARTIFACTS) at every skill entry, so under normal flow
# observe-result.run_id == current run_id whenever it exists. This branch
# only fires when a prior observe-result survives because (a) verify-pr-gate
# runs from a manual gh pr create BEFORE lifecycle-init has run, or
# (b) a partial lifecycle-init failed to clear the artifact. In either
# case the stale observe is not a real inconsistency for the current
# in-flight skill.
if obs_rid and obs_rid != identity.run_id:
    print('STALE_OBSERVE\t0\t' + identity.run_id)
    # friction-skip: trivial-fast-path — stale observe-result.json; see narrow-window note above
    sys.exit(0)

try:
    r = read_jsonl('$ledger', scope='current-run',
                   current_run_id=identity.run_id, project_dir='$project_dir')
    print('OK\t' + str(len(r.rows)) + '\t' + identity.run_id)
except Exception as e:
    print('ERROR\t0\tsubprocess-failure')
" 2>/dev/null) || result="ERROR	0	subprocess-failure"

  local status count run_id
  IFS=$'\t' read -r status count run_id <<< "$result"
  case "$status" in
    NO_RUN_ID|STALE_OBSERVE|ERROR)
      return 0
      ;;
    OK)
      [[ "$count" -eq 0 ]] && return 0
      local verdict strategy
      verdict=$(read_json_field "$obs_file" "verdict")
      strategy=$(read_json_field "$obs_file" "strategy")
      if [[ "$verdict" == "clean" ]] && [[ "$strategy" != "execution-audit" ]]; then
        ERRORS+=("Verdict inconsistency: fix ledger has $count entries for run $run_id but verdict is 'clean'. Observation was skipped or incomplete.")
      fi
      ;;
  esac
}

# --- check_verdict_consistency ---
# Checks that observe-result.json verdict is consistent with observer-diffs.txt content.
# Blocks if: non-empty diffs + verdict "clean" + not execution-audit + not dry-run.
# Appends to global ERRORS array. Does not exit — caller decides.
# Usage: check_verdict_consistency "$SKILL"
check_verdict_consistency() {
  local skill="$1"
  local project_dir="${CLAUDE_PROJECT_DIR:-.}"
  local diffs_file="$project_dir/.runs/observer-diffs.txt"
  local obs_file="$project_dir/.runs/observe-result.json"
  local ctx_file="$project_dir/.runs/${skill}-context.json"

  # Only check if both files exist and diffs is non-empty
  [[ ! -f "$diffs_file" ]] && return 0
  [[ ! -s "$diffs_file" ]] && return 0
  [[ ! -f "$obs_file" ]] && return 0

  local verdict strategy dry_run
  verdict=$(read_json_field "$obs_file" "verdict")
  strategy=$(read_json_field "$obs_file" "strategy")
  dry_run=$(read_json_field "$ctx_file" "dry_run")

  # Invariant: non-empty diffs + "clean" verdict + Strategy A = violation
  if [[ "$verdict" == "clean" ]] && [[ "$strategy" != "execution-audit" ]] && [[ "$dry_run" != "True" ]]; then
    ERRORS+=("Verdict inconsistency: observer-diffs.txt has content but observe-result.json verdict is 'clean' — the observer was not spawned. Re-run the skill epilogue.")
  fi
}
