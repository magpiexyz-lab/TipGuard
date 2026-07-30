#!/usr/bin/env bash
# adversarial-merge-gate.sh — Claude Code PreToolUse hook for Write/Edit.
# Layer 3 adversarial integrity: validates challenge/adversarial artifacts
# match source agent traces. Consolidated gate for resolve, review, change.
# Blocks on mismatch between artifact labels and trace verdicts.

set -euo pipefail

source "$(dirname "$0")/lib.sh"
parse_payload

FILE_PATH=$(read_payload_field "tool_input.file_path")

case "$FILE_PATH" in
  *resolve-challenge*)
    extract_write_content
    # friction-skip: trivial-fast-path — Write/Edit with empty content has no JSON to validate.
    [[ -z "$CONTENT" ]] && exit 0
    PROJECT_DIR=$(get_project_dir)
    VALIDATION=$(echo "$CONTENT" | python3 -c "
import json, sys, os
content = sys.stdin.read().strip()
try:
    merge = json.loads(content)
except Exception:
    # friction-skip: post-validation — PARSE_ERROR is a stdout signal consumed by handle_validation (lib-core.sh:169) which fail-opens on malformed JSON.
    print('PARSE_ERROR'); sys.exit(0)
traces_dir = os.environ.get('CLAUDE_PROJECT_DIR', '.') + '/.runs/agent-traces'
# Read trace names from agent registry
_reg_path = os.path.join(os.environ.get('CLAUDE_PROJECT_DIR', '.'), '.claude/patterns/agent-registry.json')
try:
    _adv = json.load(open(_reg_path)).get('merge_gates', {}).get('adversarial', {}).get('resolve', {})
except Exception:
    _adv = {}
rc_path = os.path.join(traces_dir, _adv.get('light_trace', 'resolve-challenger') + '.json')
sc_path = os.path.join(traces_dir, _adv.get('full_trace', 'solve-critic') + '.json')
# CONTRACT: print 'FAIL:...' + sys.exit(0) is bash-readable surface.
# Bash captures FAIL: into VALIDATION (the "|| echo OK" clause fires
# only on non-zero Python exit). handle_validation matches FAIL:* and
# calls deny() (exit 2). Do NOT change to sys.exit(2) — bash would then
# see python failure, fall through "|| echo OK", and silently allow.
if not os.path.exists(rc_path) and not os.path.exists(sc_path):
    print(f'FAIL:No adversarial trace found ({os.path.basename(rc_path)} or {os.path.basename(sc_path)})')
    # friction-skip: post-validation — FAIL:* surfaces via stdout to handle_validation which calls deny() exit 2. See contract block above.
    sys.exit(0)
errors = []
challenges = merge.get('challenges', [])
if os.path.exists(rc_path):
    # Light mode: per-item label matching against resolve-challenger trace
    trace = json.load(open(rc_path))
    tv = trace.get('verdicts', [])
    for i, c in enumerate(challenges):
        al = c.get('agent_label')
        if i < len(tv):
            tl = tv[i].get('label')
            if al != tl:
                errors.append(f'challenges[{i}].agent_label={al!r} but trace verdict={tl!r}')
elif os.path.exists(sc_path):
    # Full mode: scalar field matching against solve-critic trace
    trace = json.load(open(sc_path))
    t_ta = trace.get('type_a_count')
    m_ta = merge.get('round_1_type_a_count')
    if t_ta is not None and m_ta is not None and t_ta != m_ta:
        errors.append(f'round_1_type_a_count mismatch: merge={m_ta}, trace={t_ta}')
    t_round = trace.get('round')
    m_round = merge.get('critic_rounds')
    if t_round is not None and m_round is not None and t_round != m_round:
        errors.append(f'critic_rounds mismatch: merge={m_round}, trace round={t_round}')
if errors:
    print('FAIL:' + '; '.join(errors))
else:
    print('OK')
" 2>/dev/null || echo "OK")
    handle_validation "$VALIDATION" "Adversarial merge gate (resolve)" "Challenge artifact must match resolve-challenger trace."
    # friction-skip: post-validation — handle_validation already denied on FAIL: or exited 0 on PARSE_ERROR.
    exit 0
    ;;

  *review-adversarial*)
    extract_write_content
    # friction-skip: trivial-fast-path — Write/Edit with empty content has no JSON to validate.
    [[ -z "$CONTENT" ]] && exit 0
    PROJECT_DIR=$(get_project_dir)
    VALIDATION=$(echo "$CONTENT" | python3 -c "
import json, sys, os
content = sys.stdin.read().strip()
try:
    merge = json.loads(content)
except Exception:
    # friction-skip: post-validation — PARSE_ERROR is a stdout signal consumed by handle_validation (lib-core.sh:169) which fail-opens on malformed JSON.
    print('PARSE_ERROR'); sys.exit(0)
traces_dir = os.environ.get('CLAUDE_PROJECT_DIR', '.') + '/.runs/agent-traces'
# Read trace name from agent registry
_reg_path = os.path.join(os.environ.get('CLAUDE_PROJECT_DIR', '.'), '.claude/patterns/agent-registry.json')
try:
    _review_trace = json.load(open(_reg_path)).get('merge_gates', {}).get('adversarial', {}).get('review', {}).get('trace', 'review-challenger')
except Exception:
    _review_trace = 'review-challenger'
trace_path = os.path.join(traces_dir, _review_trace + '.json')
# CONTRACT: see resolve-challenge branch above — print 'FAIL:...' + sys.exit(0)
# is the bash-readable surface; handle_validation translates to deny()/exit 2.
if not os.path.exists(trace_path):
    print(f'FAIL:{os.path.basename(trace_path)} trace not found -- cannot validate adversarial artifact')
    # friction-skip: post-validation — FAIL:* surfaces via stdout to handle_validation which calls deny() exit 2.
    sys.exit(0)
trace = json.load(open(trace_path))
tv = trace.get('verdicts', [])
errors = []
# Build a lookup from trace verdicts by finding title
trace_by_finding = {v.get('finding'): v.get('label') for v in tv}
for lst_name in ('confirmed', 'disputed', 'needs_evidence'):
    for i, item in enumerate(merge.get(lst_name, [])):
        if not isinstance(item, dict):
            continue
        ac = item.get('agent_classification')
        finding = item.get('finding', '')
        tl = trace_by_finding.get(finding)
        if tl and ac and ac != tl:
            errors.append(f'{lst_name}[{i}] ({finding}): agent_classification={ac!r} but trace={tl!r}')
if errors:
    print('FAIL:' + '; '.join(errors))
else:
    print('OK')
" 2>/dev/null || echo "OK")
    handle_validation "$VALIDATION" "Adversarial merge gate (review)" "Adversarial artifact must match review-challenger trace."
    # friction-skip: post-validation — handle_validation already denied on FAIL: or exited 0 on PARSE_ERROR.
    exit 0
    ;;

  *change-challenge*)
    # Check if solve_depth is "full" — skip trace validation for light mode.
    PROJECT_DIR=$(get_project_dir)
    # #1350 fix: SOLVE_DEPTH lookup — explicit field access (no .get() default).
    # Triple fail-open below (try/except + 2>/dev/null + || echo "light") collapsed
    # all error states (file missing, JSON malformed, field missing) into 'light'
    # → silent skip. Now: errors surface as a literal 'error:<reason>' value bash
    # can branch on; field-missing raises KeyError so it isn't silently defaulted.
    SOLVE_DEPTH=$(python3 -c "
import json, sys
try:
    ctx = json.load(open('$PROJECT_DIR/.runs/change-context.json'))
    print(ctx['solve_depth'])  # explicit access — KeyError if missing
except KeyError:
    print('error:solve_depth_field_missing')
except FileNotFoundError:
    print('error:context_file_missing')
except json.JSONDecodeError as e:
    print('error:json_decode_' + type(e).__name__)
except Exception as e:
    print('error:' + type(e).__name__)
" 2>/dev/null) || SOLVE_DEPTH="error:python_invocation_failed"

    if [[ "$SOLVE_DEPTH" == error:* ]]; then
      # FAIL-CLOSED on error states — bypass manifest check is the only
      # legitimate way to skip when SOLVE_DEPTH is unresolvable.
      _write_hook_friction "adversarial-merge-gate (change-challenge): SOLVE_DEPTH unresolvable ($SOLVE_DEPTH) — denying. Fix .runs/change-context.json or declare manifest exemption."
      deny "adversarial-merge-gate: SOLVE_DEPTH could not be resolved ($SOLVE_DEPTH). Either fix .runs/change-context.json or declare a skip exemption in .claude/patterns/adversarial-merge-trace-skip.json."
    fi

    # #1350 fix: when SOLVE_DEPTH != "full", require explicit skip-manifest entry.
    # Previous behavior was silent exit 0 (no friction log, no justification).
    # Now: fail-closed unless manifest declares category=light_mode_skip with
    # justification. Manifest is pre-populated with the legitimate entry; new
    # exemptions require coherence-rule sign-off (hook_bypass_manifest_completeness).
    if [[ "$SOLVE_DEPTH" != "full" ]]; then
      SKIP_MANIFEST="$PROJECT_DIR/.claude/patterns/adversarial-merge-trace-skip.json"
      SKIP_DECISION=$(SKIP_MANIFEST="$SKIP_MANIFEST" SOLVE_DEPTH="$SOLVE_DEPTH" python3 -c "
import json, os, sys
mf = os.environ.get('SKIP_MANIFEST', '')
sd = os.environ.get('SOLVE_DEPTH', '')
try:
    m = json.load(open(mf))
except FileNotFoundError:
    # friction-skip: post-validation — DENY:* is a stdout signal consumed by bash case dispatch which calls deny() exit 2.
    print('DENY:manifest_missing'); sys.exit(0)
except json.JSONDecodeError as e:
    # friction-skip: post-validation — DENY:* is a stdout signal consumed by bash case dispatch.
    print('DENY:manifest_parse_error:' + type(e).__name__); sys.exit(0)
for e in m.get('skip_entries', []):
    if not isinstance(e, dict):
        continue
    if e.get('category') == 'light_mode_skip' and e.get('solve_depth_value') == sd:
        print('ALLOW:' + e.get('justification', '<no justification>'))
        # friction-skip: post-validation — ALLOW:* is a stdout signal consumed by bash; bash side friction-logs after match.
        sys.exit(0)
print('DENY:no_matching_entry_for_solve_depth=' + sd)
" 2>/dev/null) || SKIP_DECISION="DENY:python_invocation_failed"

      case "$SKIP_DECISION" in
        ALLOW:*)
          _write_hook_friction "adversarial-merge-gate (change-challenge): trace validation skipped — solve_depth=$SOLVE_DEPTH; justification: ${SKIP_DECISION#ALLOW:}"
          exit 0
          ;;
        DENY:*)
          deny "adversarial-merge-gate (change-challenge): trace validation skip not authorized (${SKIP_DECISION#DENY:}). Either run /solve --depth full to produce solve-critic.json, or declare a justified skip in .claude/patterns/adversarial-merge-trace-skip.json (category=light_mode_skip + solve_depth_value=$SOLVE_DEPTH + justification)."
          ;;
        *)
          deny "adversarial-merge-gate (change-challenge): manifest decision opaque ($SKIP_DECISION). This is a structural error — investigate the skip manifest."
          ;;
      esac
    fi

    exec_merge_gate "merge_gates.adversarial.change.checks" "change-challenge" "Adversarial merge gate (change)"
    ;;

  *)
    # friction-skip: trivial-fast-path — file_path not in {resolve-challenge, review-adversarial, change-challenge}; hook does not apply.
    exit 0
    ;;
esac
