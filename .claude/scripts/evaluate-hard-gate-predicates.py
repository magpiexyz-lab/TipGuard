#!/usr/bin/env python3
"""evaluate-hard-gate-predicates.py — Hard gate predicate evaluator.

Reads agent-registry.json's hard_gates[] for the named agent and evaluates
allow_predicates + additional_block_conditions against the agent's trace JSON.
Extracted from lib-verdict.sh (lines 273-469) so the predicate logic can be
unit-tested directly with pytest instead of through bash subprocess.

INPUT (env vars are PRIMARY contract — preserved from the bash heredoc form):
  AGENT_ENV       — agent name (e.g., "design-critic")
  TRACE_ENV       — path to agent trace JSON
  TRACES_DIR_ENV  — directory holding sibling traces (for aggregate_ok)
  REG_ENV         — path to .claude/patterns/agent-registry.json

OPTIONAL CLI (override convenience for tests; falls back to env when omitted):
  --agent / --trace / --traces-dir / --registry

OUTPUT (stdout, single line, parsed by lib-hard-gate.sh case statement):
  OK
  BLOCK:<reason>
  READ_ERROR:<msg>
  UNKNOWN_PREDICATE:<name>
  (empty string)        — no hard_gate entry registered for this agent

EXIT CODES:
  0  — normal evaluation; caller parses stdout
  2  — required input missing (argparse + env both empty); error to stderr
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys


# --- Predicate definitions (must match agent-registry._hard_gates_predicate_docs) ---

def pass_clean(t):
    # AOC v1: agent found nothing to do. No work performed.
    return (t.get('verdict') == 'pass'
            and t.get('result') == 'clean'
            and t.get('provenance') == 'self')


def pass_after_fixes(t):
    # AOC v1: agent found issues and resolved them; no unresolved criticals.
    try:
        unresolved_critical = int(t.get('unresolved_critical', 0))
    except (TypeError, ValueError):
        unresolved_critical = 0
    return (t.get('verdict') == 'pass'
            and t.get('result') in ('fixed', 'partial')
            and t.get('provenance') == 'self'
            and unresolved_critical == 0)


def pass_self_pass_or_fail(t):
    return t.get('verdict') in ('pass', 'fail') and t.get('provenance') == 'self'


def pass_self_strict(t):
    return t.get('verdict') == 'pass' and t.get('provenance') == 'self'


def validated_fallback(t):
    # AOC v1.1: lead-on-behalf added — agent succeeded but write was blocked,
    # lead transcribed the agent's reported result. Subject to the same
    # recovery_validated discipline as recovery / self-degraded so downstream
    # gates require independent evidence (build + e2e + diff-fix correlation).
    return (t.get('provenance') in ('recovery', 'self-degraded', 'lead-on-behalf')
            and t.get('recovery_validated') is True)


def legacy_pass_no_recovery(t):
    # Pre-migration traces lack provenance; accept verdict==pass without recovery
    if t.get('provenance') is not None:
        return False
    return t.get('verdict') == 'pass' and not t.get('recovery')


# --- AOC v1.1 lead-* predicates ---

def pass_lead_on_behalf(t):
    # Agent succeeded; lead transcribed because the agent's own trace write
    # was blocked or it ran out of tool budget. Spawn-log entry must exist
    # (enforced by state-completion-gate's universal provenance check) — that
    # check is upstream of these predicates, so we trust spawn-log presence
    # here. Source attestation already enforced by artifact-integrity-gate.
    # recovery_validated is required for downstream confidence (the gate
    # operator earns the "agent succeeded" trust by independent evidence).
    return (t.get('verdict') == 'pass'
            and t.get('provenance') == 'lead-on-behalf'
            and t.get('recovery_validated') is True)


def pass_lead_fix(t):
    # Lead applied an in-flight fix during a verify stage. lead_attestation:true
    # is the marker (enforced by artifact-integrity-gate). Lead has direct
    # knowledge — confidence ~1.0, no recovery_validated required.
    return (t.get('verdict') == 'pass'
            and t.get('provenance') == 'lead-fix'
            and t.get('lead_attestation') is True)


def pass_lead_synthesized(t):
    # Agent was never spawned (covered by another mechanism). Lead writes a
    # consistency marker. coverage_provider must name the artifact (enforced
    # by artifact-integrity-gate). no_fixes_claimed:true is the typical case.
    return (t.get('verdict') == 'pass'
            and t.get('provenance') == 'lead-synthesized'
            and bool(t.get('coverage_provider')))


def pass_lead_orchestrated(t):
    # AOC v1.2: lead orchestrated a retrospective re-spawn under
    # post-completion conditions where resolve_active_identity returned
    # empty. Explicit identity supplied via --source-run-id/--source-skill;
    # spawn-log presence enforced upstream by the writer's R3 validation.
    # Schema validation (lead_attestation, source_run_id, source_skill)
    # is enforced by artifact-integrity-gate.sh; this predicate trusts the
    # gate's contract and only re-checks the verdict/provenance pair.
    return (t.get('verdict') == 'pass'
            and t.get('provenance') == 'lead-orchestrated'
            and t.get('lead_attestation') is True
            and bool(t.get('source_run_id'))
            and bool(t.get('source_skill')))


def aggregate_ok(t, agent, traces_dir):
    if t.get('provenance') != 'lead-merge':
        return False
    csi = t.get('contributing_spawn_indexes')
    if not isinstance(csi, list) or len(csi) == 0:
        return False
    # Each contributing sibling trace must satisfy a pass-class predicate.
    # AOC v1.1: lead-* predicates are accepted as siblings (e.g., one
    # design-critic page completed normally, another was lead-on-behalf
    # transcribed because the agent's write was blocked).
    # #1274 round-2 critic C12: dedupe siblings by page_key so a stale
    # OLD trace doesn't fail aggregate_ok after a post-fix re-spawn lands
    # the latest verdict for that page. Same selector the merger uses,
    # so the two consumers cannot drift. Only dedupes for known per-page
    # agents (those whose traces follow `<agent>-<page>--epoch<N>.json`);
    # other agents fall back to the flat glob (no per-page semantics).
    try:
        _selector_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib')
        if _selector_dir not in sys.path:
            sys.path.insert(0, _selector_dir)
        from design_critic_trace_selector import select_latest_per_page_traces
        sibs = select_latest_per_page_traces(traces_dir, agent)
    except Exception:
        sibs = glob.glob(os.path.join(traces_dir, agent + '-*.json'))
    if not sibs:
        return False
    for sf in sibs:
        try:
            sib = json.load(open(sf))
        except Exception:
            return False
        if not (
            pass_clean(sib)
            or pass_after_fixes(sib)
            or pass_self_pass_or_fail(sib)
            or validated_fallback(sib)
            or legacy_pass_no_recovery(sib)
            or pass_lead_on_behalf(sib)
            or pass_lead_fix(sib)
            or pass_lead_synthesized(sib)
            or pass_lead_orchestrated(sib)
        ):
            return False
    return True


def evaluate(agent, trace_path, traces_dir, reg_path):
    """Pure function — easy to unit-test. Returns a single-line stdout string.

    Empty string means "no hard gate registered for this agent" (caller treats as OK).
    """
    try:
        reg = json.load(open(reg_path))
    except Exception as exc:
        return 'READ_ERROR:registry:' + str(exc)

    gate = next((g for g in reg.get('hard_gates', []) if g.get('agent') == agent), None)
    if gate is None:
        return ''

    try:
        trace = json.load(open(trace_path))
    except Exception as exc:
        return 'READ_ERROR:' + str(exc)

    predicate_fns = {
        'pass_clean': lambda t: pass_clean(t),
        'pass_after_fixes': lambda t: pass_after_fixes(t),
        'pass_self_pass_or_fail': lambda t: pass_self_pass_or_fail(t),
        'pass_self_strict': lambda t: pass_self_strict(t),
        'validated_fallback': lambda t: validated_fallback(t),
        'legacy_pass_no_recovery': lambda t: legacy_pass_no_recovery(t),
        'aggregate_ok': lambda t: aggregate_ok(t, agent, traces_dir),
        'pass_lead_on_behalf': lambda t: pass_lead_on_behalf(t),
        'pass_lead_fix': lambda t: pass_lead_fix(t),
        'pass_lead_synthesized': lambda t: pass_lead_synthesized(t),
        'pass_lead_orchestrated': lambda t: pass_lead_orchestrated(t),
    }

    allow_predicates = gate.get('allow_predicates', [])
    any_allowed = False
    for p in allow_predicates:
        fn = predicate_fns.get(p)
        if fn is None:
            return 'UNKNOWN_PREDICATE:' + p
        if fn(trace):
            any_allowed = True
            break

    blocks = []
    for cond in gate.get('additional_block_conditions', []) or []:
        if 'all' in cond:
            sub_all_hit = True
            detail = []
            for sub in cond['all']:
                fld = sub.get('field')
                val = trace.get(fld)
                if 'eq' in sub:
                    hit = str(val) == str(sub['eq'])
                elif 'gt' in sub:
                    try:
                        hit = int(val) > int(sub['gt'])
                    except (TypeError, ValueError):
                        hit = False
                else:
                    hit = False
                if not hit:
                    sub_all_hit = False
                    break
                detail.append(f'{fld}={val}')
            if sub_all_hit:
                blocks.append(' AND '.join(detail))
        else:
            fld = cond.get('field')
            val = trace.get(fld)
            if 'eq' in cond:
                hit = str(val) == str(cond['eq'])
            elif 'gt' in cond:
                try:
                    hit = int(val) > int(cond['gt'])
                except (TypeError, ValueError):
                    hit = False
            else:
                hit = False
            if hit:
                blocks.append(f'{fld}={val}')

    if not any_allowed and blocks:
        return 'BLOCK:no allow_predicate satisfied AND additional block triggered (' + '; '.join(blocks) + ')'
    if not any_allowed:
        reasons = [f'{k}={trace.get(k)}' for k in ('verdict', 'provenance', 'recovery_validated', 'recovery')]
        return 'BLOCK:no allow_predicate satisfied (' + ', '.join(reasons) + ')'
    if blocks:
        return 'BLOCK:additional block triggered (' + '; '.join(blocks) + ')'
    return 'OK'


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--agent', default=os.environ.get('AGENT_ENV'))
    p.add_argument('--trace', default=os.environ.get('TRACE_ENV'))
    p.add_argument('--traces-dir', default=os.environ.get('TRACES_DIR_ENV'))
    p.add_argument('--registry', default=os.environ.get('REG_ENV'))
    args = p.parse_args()

    missing = [k for k, v in vars(args).items() if not v]
    if missing:
        print('READ_ERROR:missing required input: ' + ','.join(missing), file=sys.stderr)
        sys.exit(2)

    print(evaluate(args.agent, args.trace, args.traces_dir, args.registry))


if __name__ == '__main__':
    main()
