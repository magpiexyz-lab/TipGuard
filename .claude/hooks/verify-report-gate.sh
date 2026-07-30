#!/usr/bin/env bash
# verify-report-gate.sh — Claude Code PreToolUse hook for Write/Edit.
# Blocks writing verify-report.md unless durable artifacts exist.

set -euo pipefail

source "$(dirname "$0")/lib.sh"
parse_payload

FILE_PATH=$(read_payload_field "tool_input.file_path")

# Only fire when file_path targets the verify-report markdown/json artifact.
# Must NOT match this hook file itself (verify-report-gate.sh) or helpers.
case "$FILE_PATH" in
  *verify-report.md|*verify-report.json) ;;
  *) exit 0 ;;
esac

# --- verify-report.md write detected — run artifact checks ---

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
ERRORS=()
WARNINGS=()

# Self-heal: if agent traces predate the v2 schema (no provenance field),
# run the legacy migration in-place rather than hard-refusing this write.
# Avoids bricking multi-hour workflows after a /upgrade bump (R2 C4 fix).
UNMIGRATED=$(python3 -c "
import json, glob, os
project = os.environ.get('CLAUDE_PROJECT_DIR', '.')
receipt = os.path.join(project, '.runs', 'trace-migration.json')
if os.path.isfile(receipt):
    print(0)
else:
    n = 0
    for f in glob.glob(os.path.join(project, '.runs', 'agent-traces', '*.json')):
        try:
            d = json.load(open(f))
            if 'provenance' not in d:
                n += 1
        except: pass
    print(n)
" 2>/dev/null || echo "0")
if [[ "${UNMIGRATED:-0}" -gt 0 ]]; then
  echo "WARN: verify-report-gate: detected $UNMIGRATED legacy trace(s) without provenance — running migration in-place" >&2
  python3 "$PROJECT_DIR/.claude/scripts/migrate-legacy-traces.py" >&2 || true
fi

# AOC v1 FLS v1: ensure the canonical ledger (.runs/fix-ledger.jsonl) is
# consolidated before downstream checks read it. Idempotent and cheap.
if [[ -d "$PROJECT_DIR/.runs/agent-traces" ]]; then
  python3 "$PROJECT_DIR/.claude/scripts/write-fix-ledger.py" >/dev/null 2>&1 || true
fi

# AOC v1: refuse to proceed when migration marked traces unresolved.
# migrate-legacy-traces.py writes .runs/trace-migration-unresolved.json
# when a known verdict_agent emitted a verdict that the mapping table
# cannot parse (fail-closed — see .claude/patterns/agent-output-contract.md).
UNRESOLVED_COUNT=$(python3 -c "
import json, os
project = os.environ.get('CLAUDE_PROJECT_DIR', '.')
receipt = os.path.join(project, '.runs', 'trace-migration.json')
if os.path.isfile(receipt):
    try:
        d = json.load(open(receipt))
        print(d.get('unresolved_count', 0))
    except Exception:
        print(0)
else:
    print(0)
" 2>/dev/null || echo "0")
if [[ "${UNRESOLVED_COUNT:-0}" -gt 0 ]]; then
  UNRESOLVED_FILE="$PROJECT_DIR/.runs/trace-migration-unresolved.json"
  echo "BLOCK: verify-report-gate: migrate-legacy-traces left $UNRESOLVED_COUNT trace(s) unresolved" >&2
  if [[ -f "$UNRESOLVED_FILE" ]]; then
    echo "Details at: $UNRESOLVED_FILE" >&2
    python3 -c "
import json
d = json.load(open('$UNRESOLVED_FILE'))
for u in d.get('unresolved', []):
    print('  -', u.get('agent'), ':', u.get('reason'))
" >&2 2>/dev/null || true
  fi
  echo "Fix each listed verdict in .claude/scripts/migrate-legacy-traces.py LEGACY_VERDICT_MAP or add structured count fields, then re-run migration with --force." >&2
  exit 1
fi

extract_write_content

# Detect hard_gate_failure in report content — when true, STATEs 4-5 artifacts
# are correctly absent (hard gate skips them). Checks 5, 7, 15 become conditional.
HAS_HARD_GATE=0
if [[ -n "$CONTENT" ]]; then
  HAS_HARD_GATE=$(echo "$CONTENT" | grep -c 'hard_gate_failure: *true' || echo "0")
fi

# ═══════════════════════════════════════════════════════════════════
# === Section A: Artifact Presence (Checks 1-8, 13b, 15) ===
# ═══════════════════════════════════════════════════════════════════

ARTIFACT_RESULT=$(check_artifact_presence "$PROJECT_DIR" "$HAS_HARD_GATE" "$CONTENT")
_parse_check_result "$ARTIFACT_RESULT"

# ═══════════════════════════════════════════════════════════════════
# === Section B: Agent Trace Verdicts (Checks 8-11, 13) ===
# ═══════════════════════════════════════════════════════════════════

TRACE_DIR="$PROJECT_DIR/.runs/agent-traces"

if [[ -f "$PROJECT_DIR/.runs/verify-context.json" ]]; then
  SCOPE=$(read_json_field "$PROJECT_DIR/.runs/verify-context.json" "scope")
  ARCH=$(read_json_field "$PROJECT_DIR/.runs/verify-context.json" "archetype")

  # Check 8: design-ux-merge.json required for full/visual + web-app
  if [[ ("$SCOPE" == "full" || "$SCOPE" == "visual") && "$ARCH" == "web-app" ]]; then
    if [[ ! -f "$PROJECT_DIR/.runs/design-ux-merge.json" ]]; then
      ERRORS+=("design-ux-merge.json not found — Design-UX merge step was skipped (scope=$SCOPE, archetype=$ARCH)")
    fi
  fi

  # Hard gate checks — v2 predicate-based, driven by agent-registry.json.
  # Each hard_gates[] entry declares allow_predicates (named predicates like
  # pass_self_pass_or_fail / validated_fallback / aggregate_ok /
  # legacy_pass_no_recovery) and optional additional_block_conditions.
  # check_hard_gate_predicates evaluates both: the report is allowed only
  # when at least one allow_predicate passes AND no additional_block_condition
  # fires. See .claude/patterns/agent-trace-protocol.md §Provenance for the
  # coherent model; v1 block_rules form was replaced by this v2 dispatch.
  while IFS= read -r _hg_agent; do
    [[ -z "$_hg_agent" ]] && continue
    check_hard_gate_predicates "$_hg_agent" "$TRACE_DIR"
  done < <(python3 -c "
import json, os
reg_path = os.path.join(os.environ.get('CLAUDE_PROJECT_DIR', '.'), '.claude/patterns/agent-registry.json')
try:
    reg = json.load(open(reg_path))
except Exception:
    exit(0)
for hg in reg.get('hard_gates', []):
    a = hg.get('agent')
    if a:
        print(a)
" 2>/dev/null)

  # Trace existence checks — read from agent registry
  while IFS=$'\t' read -r _te_agent _te_scopes _te_arch; do
    [[ -z "$_te_agent" ]] && continue
    if [[ ",$_te_scopes," == *",$SCOPE,"* ]] && [[ "$ARCH" == "$_te_arch" ]]; then
      if [[ ! -f "$TRACE_DIR/${_te_agent}.json" ]]; then
        ERRORS+=("${_te_agent}.json trace missing for scope=$SCOPE archetype=$ARCH")
      fi
    fi
  done < <(python3 -c "
import json, os
reg_path = os.path.join(os.environ.get('CLAUDE_PROJECT_DIR', '.'), '.claude/patterns/agent-registry.json')
try:
    reg = json.load(open(reg_path))
except Exception:
    exit(0)
for tr in reg.get('trace_required', []):
    print(tr['agent'] + '\t' + ','.join(tr['when_scope']) + '\t' + tr['when_archetype'])
" 2>/dev/null)
fi

# ═══════════════════════════════════════════════════════════════════
# === Section C: Cross-Artifact Consistency (Checks 12, 14, 16-18) ===
# ═══════════════════════════════════════════════════════════════════

if [[ -n "$CONTENT" ]]; then
  CONSISTENCY_RESULT=$(check_cross_artifact_consistency "$PROJECT_DIR" "$CONTENT")
  _parse_check_result "$CONSISTENCY_RESULT"
fi

# Output warnings to stderr (non-blocking)
if [[ ${#WARNINGS[@]} -gt 0 ]]; then
  for w in "${WARNINGS[@]}"; do
    echo "WARN: $w" >&2
  done
fi

# If any check failed, deny the write
if [[ ${#ERRORS[@]} -gt 0 ]]; then
  deny_errors "Verify report gate blocked: " "Complete all verification steps before writing verify-report.md."
fi

# All checks passed — allow
exit 0
