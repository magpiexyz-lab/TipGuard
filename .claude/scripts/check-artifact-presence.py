#!/usr/bin/env python3
"""Artifact presence checks for verify-report-gate.

Covers Checks 1-8, 13b, 15: file existence, field validation, trace checks.
Reads report content from stdin. Returns JSON {"errors":[], "warnings":[]}.
"""
import argparse
import glob
import json
import os
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--has-hard-gate", type=int, default=0)
    args = parser.parse_args()

    project = os.environ.get('CLAUDE_PROJECT_DIR', '.')
    hard_gate = args.has_hard_gate > 0
    content = sys.stdin.read()
    errors = []
    warnings = []

    # --- Check 1: verify-context.json exists + field validation ---
    ctx_path = os.path.join(project, '.runs/verify-context.json')
    ctx = {}
    if not os.path.exists(ctx_path):
        errors.append('verify-context.json not found — STATE 0 (Read Context) did not run')
    else:
        try:
            ctx = json.load(open(ctx_path))
            missing = [k for k in ['scope','archetype','run_id','timestamp'] if k not in ctx or not ctx[k]]
            if missing:
                errors.append('verify-context.json missing required fields: ' + ','.join(missing))
        except:
            errors.append('verify-context.json parse error')

    scope = ctx.get('scope', '')
    arch = ctx.get('archetype', '')

    # --- Check 2: fix-log.md exists (rendered artifact) ---
    fix_log_path = os.path.join(project, '.runs/fix-log.md')
    if not os.path.exists(fix_log_path):
        errors.append('fix-log.md not found — STATE 0 (Read Context) did not run')

    # --- Check 2b: AOC v1 FLS v1 ledger exists when any trace has fixes[] ---
    ledger_path = os.path.join(project, '.runs/fix-ledger.jsonl')
    traces_dir_check = os.path.join(project, '.runs/agent-traces')
    if os.path.isdir(traces_dir_check):
        trace_has_fixes = False
        for tf in glob.glob(os.path.join(traces_dir_check, '*.json')):
            try:
                dd = json.load(open(tf))
                if isinstance(dd.get('fixes'), list) and len(dd['fixes']) > 0:
                    trace_has_fixes = True
                    break
            except Exception:
                continue
        if trace_has_fixes and not os.path.exists(ledger_path):
            errors.append('fix-ledger.jsonl not found but agent traces have fixes[] — run '
                          '.claude/scripts/write-fix-ledger.py to consolidate (AOC v1 FLS v1)')

    # --- Check 3: agent-traces/ has >= 1 trace ---
    traces_dir = os.path.join(project, '.runs/agent-traces')
    traces = []
    if not os.path.isdir(traces_dir):
        errors.append('agent-traces/ directory not found — no agents were spawned')
    else:
        traces = glob.glob(os.path.join(traces_dir, '*.json'))
        if len(traces) < 1:
            errors.append('agent-traces/ has 0 trace files — no agents completed')

    # --- Check 4: Each trace has checks_performed ---
    for t in traces:
        try:
            d = json.load(open(t))
            cp = d.get('checks_performed', None)
            recovery = d.get('recovery', False)
            if recovery and isinstance(cp, list): continue
            if isinstance(cp, list) and len(cp) > 0: continue
            errors.append(os.path.basename(t) + ' missing checks_performed array — agent used old trace format')
        except:
            errors.append(os.path.basename(t) + ' parse error')

    # --- Check 5: security-merge.json (skip on hard gate) ---
    if not hard_gate and scope in ('full', 'security'):
        if not os.path.exists(os.path.join(project, '.runs/security-merge.json')):
            errors.append('security-merge.json not found — security merge step was skipped (scope=' + scope + ')')

    # --- Check 6: fix-log vs auto_observe (skip on hard gate) ---
    # With unified observation, auto_observe is "evaluated-in-epilogue" during verify.
    # The epilogue runs observation-phase.md after finalize — observe-result.json
    # may not exist yet at verify-report write time, which is expected.
    if not hard_gate and os.path.exists(fix_log_path):
        try:
            lines = open(fix_log_path).readlines()[1:]  # skip header
            fix_entries = sum(1 for l in lines if l.strip())
            if fix_entries > 0 and 'auto_observe' in content and 'skipped-no-fixes' in content:
                errors.append('fix-log.md has ' + str(fix_entries) + ' fix entries but auto_observe is skipped-no-fixes — observer must run when fixes exist')
        except: pass

    # --- Check 7: e2e-result.json (skip on hard gate) ---
    if not hard_gate:
        e2e_path = os.path.join(project, '.runs/e2e-result.json')
        if not os.path.exists(e2e_path):
            errors.append('e2e-result.json not found — E2E tests (STATE 5) did not run')
        else:
            try:
                e2e = json.load(open(e2e_path))
                if not e2e.get('passed', False):
                    warnings.append('e2e-result.json: passed=false — E2E tests failed')
            except: pass

    # --- Check 8: retrospective-result.json (written by observation-phase.md Step 5a in epilogue) ---
    # With unified observation, retrospective-result.json is written in the epilogue
    # (after finalize), not during verify. At verify-report write time it may not exist.
    # Only check if it exists; missing is expected when auto_observe is "evaluated-in-epilogue".
    if not hard_gate:
        retro_path = os.path.join(project, '.runs/retrospective-result.json')
        if os.path.exists(retro_path):
            try:
                retro = json.load(open(retro_path))
                if not isinstance(retro.get('agent_instruction_compliance'), list):
                    warnings.append('retrospective-result.json: agent_instruction_compliance is not a list')
            except:
                warnings.append('retrospective-result.json: invalid JSON')

    # --- Check 13b: design-critic-shared when per-page has unresolved_shared ---
    if scope in ('full', 'visual') and arch == 'web-app':
        has_shared = False
        for f in glob.glob(os.path.join(traces_dir, 'design-critic-*.json')):
            if 'design-critic-shared' in f: continue
            try:
                d = json.load(open(f))
                if d.get('unresolved_shared', 0) > 0:
                    has_shared = True; break
            except: pass
        if has_shared:
            # Check if all shared issues are for claimed components (handled by per-page claiming agents)
            all_claimed = False
            claims_path = os.path.join(project, '.runs', 'design-claims.json')
            if os.path.exists(claims_path):
                try:
                    claims = json.load(open(claims_path)).get('claims', {})
                    if claims:
                        all_claimed = True
                        for f in glob.glob(os.path.join(traces_dir, 'design-critic-*.json')):
                            if 'design-critic-shared' in f: continue
                            try:
                                d = json.load(open(f))
                                for si in d.get('shared_issues', []):
                                    if si.get('file', '') not in claims:
                                        all_claimed = False; break
                            except: pass
                            if not all_claimed: break
                except: pass
            if not all_claimed and not os.path.exists(os.path.join(traces_dir, 'design-critic-shared.json')):
                errors.append('design-critic-shared.json missing but per-page agents reported shared-component issues for unclaimed components')

    # --- Check 15: Postcondition artifact backstop ---
    for f in ['verify-context.json', 'fix-log.md']:
        if not os.path.exists(os.path.join(project, '.runs', f)):
            errors.append(f + ' missing (STATE 0)')
    if not os.path.exists(os.path.join(project, '.runs/build-result.json')):
        errors.append('build-result.json missing (STATE 1)')
    if scope in ('full', 'visual') and arch == 'web-app':
        if not os.path.exists(os.path.join(project, '.runs/design-ux-merge.json')):
            errors.append('design-ux-merge.json missing (STATE 3)')
        if not os.path.exists(os.path.join(project, '.runs/quality-merge.json')):
            errors.append('quality-merge.json missing (STATE 3d)')
    if not hard_gate:
        if scope in ('full', 'security'):
            if not os.path.exists(os.path.join(project, '.runs/security-merge.json')):
                errors.append('security-merge.json missing (STATE 4)')
        if not os.path.exists(os.path.join(project, '.runs/e2e-result.json')):
            errors.append('e2e-result.json missing (STATE 5)')

    print(json.dumps({'errors': errors, 'warnings': warnings}))


if __name__ == "__main__":
    main()
