#!/usr/bin/env python3
"""Cross-artifact consistency checks for verify-report-gate.

Covers Checks 12, 14, 16-18: verdict matching, fix counts, frontmatter.
Reads report content from stdin. Returns JSON {"errors":[], "warnings":[]}.
"""
import glob
import json
import os
import re
import sys


def main():
    project = os.environ.get('CLAUDE_PROJECT_DIR', '.')
    content = sys.stdin.read()
    traces_dir = os.path.join(project, '.runs/agent-traces')
    errors = []
    warnings = []

    # --- Check 12: agent_verdicts in report vs actual trace verdicts ---
    # Report verdicts may annotate trace verdicts with parenthetical context
    # (e.g., trace "1 FAIL" -> report "1 FAIL (dev-only rate limiter)").
    # Accept when the report equals OR starts with the trace-verdict string —
    # preserves anti-fraud intent (report cannot claim PASS when trace says
    # FAIL) while allowing human annotation. Strict equality forced humans
    # to strip context, losing information.
    # Anchored to start-of-line so the agent_verdicts_after_fixes line
    # (matched by Check 12b below) does not also satisfy this regex.
    match = re.search(r'(?m)^agent_verdicts:\s*(.+)', content)
    if match and os.path.isdir(traces_dir):
        try:
            report_verdicts = json.loads(match.group(1).strip())
            for name, rv in report_verdicts.items():
                tp = os.path.join(traces_dir, name + '.json')
                if os.path.exists(tp):
                    try:
                        tv = json.load(open(tp)).get('verdict', 'missing')
                        rv_s, tv_s = str(rv), str(tv)
                        if rv_s != tv_s and not rv_s.startswith(tv_s):
                            errors.append('agent_verdicts mismatch: ' + name + ': report=' + rv_s + ', trace=' + tv_s)
                    except: pass
        except json.JSONDecodeError:
            pass

    # --- Check 12b: agent_verdicts_after_fixes consistency with derivation source ---
    # Closes #1151. Re-derive the after-fix verdict locally from the source
    # named in agent_verdicts_after_fixes_source and compare against the
    # value in agent_verdicts_after_fixes. Catches drift between the
    # state-7a writer and the schema if they evolve out of sync.
    # Source-of-truth for the algorithm: state-7a-write-report.md.
    FIXER_MAP = {
        'security-defender': 'security-fixer',
        'security-attacker': 'security-fixer',
        'accessibility-scanner': 'quality-fixer',
        'design-consistency-checker': 'quality-fixer',
    }
    def _is_trace_valid_pass(trace):
        prov = trace.get('provenance', 'self')
        if prov == 'self':
            return True
        if prov in ('recovery', 'self-degraded', 'lead-on-behalf'):
            return trace.get('recovery_validated') is True
        if prov == 'lead-fix':
            return trace.get('lead_attestation') is True
        if prov == 'lead-synthesized':
            return trace.get('coverage_provider') is not None
        return False

    after_match = re.search(r'(?m)^agent_verdicts_after_fixes:\s*(\{.*?\})\s*$', content)
    if after_match and os.path.isdir(traces_dir):
        try:
            after_declared = json.loads(after_match.group(1).strip())
            for name, declared in after_declared.items():
                tp = os.path.join(traces_dir, name + '.json')
                if not os.path.exists(tp):
                    continue
                try:
                    d = json.load(open(tp))
                except Exception:
                    continue
                # Compute expected after-fix verdict per the same algorithm
                if name in FIXER_MAP:
                    fixer = FIXER_MAP[name]
                    fpath = os.path.join(traces_dir, fixer + '.json')
                    if os.path.exists(fpath):
                        try:
                            ftrace = json.load(open(fpath))
                            unresolved = ftrace.get('unresolved_critical', -1)
                            valid = _is_trace_valid_pass(ftrace)
                            expected = 'pass' if (unresolved == 0 and valid) else 'fail'
                        except Exception:
                            continue
                    else:
                        expected = d.get('verdict', 'missing')
                elif name == 'ux-journeyer':
                    unresolved = d.get('unresolved_dead_ends', -1)
                    valid = _is_trace_valid_pass(d)
                    expected = 'pass' if (unresolved == 0 and valid) else 'fail'
                else:
                    expected = d.get('verdict', 'missing')
                if str(declared) != str(expected):
                    errors.append('agent_verdicts_after_fixes mismatch: ' + name +
                                  ': report=' + str(declared) + ', derived=' + str(expected))
        except json.JSONDecodeError:
            pass

    # --- Check 12c: hard-gate post-fix consistency (closes #1151) ---
    # When overall_verdict == pass, no hard_gate agent's after-fix verdict may be 'fail'.
    # count_summary agents (security-defender, accessibility-scanner, etc.) may
    # legitimately have after_fixes=fail with overall=pass when their findings
    # are routed through fixers that resolved them; only the hard_gates list
    # blocks. HARD_GATES sourced from agent-registry.json:214-275.
    HARD_GATES = {'design-critic', 'ux-journeyer', 'security-fixer', 'quality-fixer', 'resolve-reviewer'}
    overall_match = re.search(r'(?m)^overall_verdict:\s*(\S+)', content)
    if overall_match and after_match:
        if overall_match.group(1).strip() == 'pass':
            try:
                after_declared = json.loads(after_match.group(1).strip())
                for name, verdict in after_declared.items():
                    if str(verdict) == 'fail':
                        if name in HARD_GATES:
                            errors.append('hard_gate after_fixes=fail with overall_verdict=pass: ' + name)
                        else:
                            warnings.append('non-hard-gate after_fixes=fail with overall_verdict=pass (informational): ' + name)
            except json.JSONDecodeError:
                pass

    # --- Check 14: Fix count cross-reference (AOC v1 FLS v1 authoritative) ---
    # Authoritative source: .runs/fix-ledger.jsonl. Transitional dual-check
    # falls back to fix-log.md prose regex when ledger absent.
    #
    # #1251: filter BOTH ledger aggregation and trace iteration by current
    # run_id so foreign-skill traces (e.g., implementer-* written by bootstrap
    # STATE 16 and read during embedded /verify) do not produce phantom
    # "trace=N, ledger=0" warnings. Read run_id from verify-context.json;
    # fall back to no-filter when run_id is unavailable so this check stays
    # functional in pre-AOC replays and standalone invocations.
    verify_ctx_path = os.path.join(project, '.runs/verify-context.json')
    current_run_id = ''
    try:
        with open(verify_ctx_path) as f:
            current_run_id = json.load(f).get('run_id', '') or ''
    except Exception:
        pass

    ledger_path = os.path.join(project, '.runs/fix-ledger.jsonl')
    fix_log_path = os.path.join(project, '.runs/fix-log.md')
    if os.path.isdir(traces_dir):
        by_agent = None
        source = None
        if os.path.exists(ledger_path):
            by_agent = {}
            # #1417b: read ledger via runs_reader with provenance-aware scope.
            # When current_run_id is known (verify-context exists), filter to
            # that run only; otherwise read cross-run-by-design (registered
            # channel) so legacy/pre-AOC invocations still work.
            try:
                import sys
                _lib_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib')
                if _lib_dir not in sys.path:
                    sys.path.insert(0, _lib_dir)
                from runs_reader import read_jsonl
                if current_run_id:
                    rr = read_jsonl(ledger_path, scope='current-run',
                                    current_run_id=current_run_id, project_dir=project)
                else:
                    rr = read_jsonl(ledger_path, scope='cross-run-by-design',
                                    cross_run_channel='fix-ledger', project_dir=project)
                for r in rr.rows:
                    a = r.get('agent')
                    by_agent[a] = by_agent.get(a, 0) + 1
                source = 'ledger'
            except Exception:
                by_agent = None
        if by_agent is None and os.path.exists(fix_log_path):
            try:
                fix_log = open(fix_log_path).read()
                source = 'prose'
            except Exception:
                fix_log = ''
        for tf in glob.glob(os.path.join(traces_dir, '*.json')):
            name = os.path.basename(tf).replace('.json', '')
            if name.startswith('design-critic-'): continue
            try:
                d = json.load(open(tf))
                if current_run_id and d.get('run_id') and d.get('run_id') != current_run_id:
                    continue
                fixes = d.get('fixes', None)
                if fixes is None: continue
                if source == 'ledger':
                    ledger_n = by_agent.get(name, 0)
                    if len(fixes) != ledger_n:
                        warnings.append(name + ': trace=' + str(len(fixes)) + ', ledger=' + str(ledger_n))
                elif source == 'prose':
                    prefix = 'Fix (' + name + '):'
                    if len(fixes) != fix_log.count(prefix):
                        warnings.append(name + ': trace=' + str(len(fixes)) + ', log=' + str(fix_log.count(prefix)))
                # source is None → silently skip; Check 14 was never authoritative
            except: pass

    # --- Check 16: hard_gate_failure field present ---
    if content and 'hard_gate_failure:' not in content:
        errors.append('hard_gate_failure field missing from report frontmatter — must be true or false')

    # --- Check 17: process_violation field present ---
    if content and 'process_violation:' not in content:
        errors.append('process_violation field missing from report frontmatter — must be true or false')

    # --- Check 18: Lead-side trace field validation ---
    dc_path = os.path.join(traces_dir, 'design-critic.json')
    if os.path.exists(dc_path):
        try:
            d = json.load(open(dc_path))
            pr = d.get('pages_reviewed', 0)
            if not isinstance(pr, int) or pr < 1:
                errors.append('design-critic pages_reviewed=%s (expected int >= 1)' % pr)
        except: pass
    ux_path = os.path.join(traces_dir, 'ux-journeyer.json')
    if os.path.exists(ux_path):
        try:
            d = json.load(open(ux_path))
            ude = d.get('unresolved_dead_ends', None)
            if ude is not None and not isinstance(ude, int):
                errors.append('ux-journeyer unresolved_dead_ends=%s (expected int)' % ude)
        except: pass
    sf_path = os.path.join(traces_dir, 'security-fixer.json')
    if os.path.exists(sf_path):
        try:
            d = json.load(open(sf_path))
            uc = d.get('unresolved_critical', None)
            if uc is not None and not isinstance(uc, int):
                errors.append('security-fixer unresolved_critical=%s (expected int)' % uc)
        except: pass

    print(json.dumps({'errors': errors, 'warnings': warnings}))


if __name__ == "__main__":
    main()
