#!/usr/bin/env python3
"""Phase gate validation for skill orchestration pipeline.

Usage: python3 .claude/scripts/phase-gate.py <config_path> <phase_index>
Exit 0 = all gates passed
Exit 1 = gate failure (reasons printed to stderr)
"""
import json
import os
import subprocess
import sys


def check_completed_states(skill, required_states, errors):
    """Check that specific state IDs are present in completed_states."""
    ctx_file = '.runs/verify-context.json' if skill == 'verify' else f'.runs/{skill}-context.json'

    if not os.path.isfile(ctx_file):
        errors.append(f'{ctx_file} not found')
        return

    ctx = json.load(open(ctx_file))
    completed = [str(s) for s in ctx.get('completed_states', [])]
    skip = [str(s) for s in ctx.get('skip_states', [])]
    satisfied = set(completed + skip)

    for state in required_states:
        if str(state) not in satisfied:
            errors.append(f'State {state} not in completed_states (have: {completed})')


def check_files_exist(paths, errors):
    """Check that required files exist."""
    for path in paths:
        if not os.path.exists(path):
            errors.append(f'Required file missing: {path}')


def check_postconditions(skill, state_range, errors):
    """Re-run state-registry.json postcondition commands for states in range."""
    registry_path = '.claude/patterns/state-registry.json'
    if not os.path.isfile(registry_path):
        errors.append('state-registry.json not found')
        return

    registry = json.load(open(registry_path))
    skill_states = registry.get(skill, {})

    start = str(state_range[0])
    end = str(state_range[1])

    # Iterate registry keys in order from start to end
    in_range = False
    for state_id in skill_states:
        if state_id == start:
            in_range = True
        if in_range:
            raw = skill_states[state_id]
            cmd = raw.get('verify', '') if isinstance(raw, dict) else raw
            if cmd and cmd != 'true':
                try:
                    result = subprocess.run(cmd, shell=True, capture_output=True, timeout=30)
                    if result.returncode != 0:
                        stderr = result.stderr.decode().strip()
                        errors.append(f'Postcondition failed for {skill} state {state_id}: {cmd} (stderr: {stderr})')
                except subprocess.TimeoutExpired:
                    errors.append(f'Postcondition timed out for {skill} state {state_id}: {cmd}')
            if state_id == end:
                break


def check_plan_fields(fields, errors):
    """Check that current-plan.md YAML frontmatter contains specified fields."""
    plan_path = '.runs/current-plan.md'
    if not os.path.isfile(plan_path):
        errors.append('current-plan.md not found')
        return

    content = open(plan_path).read()
    if not content.startswith('---'):
        errors.append('current-plan.md has no YAML frontmatter')
        return

    parts = content.split('---', 2)
    if len(parts) < 3:
        errors.append('current-plan.md frontmatter malformed')
        return

    frontmatter = parts[1]
    for field in fields:
        if not any(line.strip().startswith(f'{field}:') for line in frontmatter.split('\n')):
            errors.append(f'current-plan.md frontmatter missing field: {field}')


def check_q_score(skill, min_score, errors):
    """Check verify-history.jsonl for Q-score at or above threshold."""
    history_path = '.runs/verify-history.jsonl'
    if not os.path.isfile(history_path):
        errors.append('verify-history.jsonl not found')
        return

    # Read run_id from context
    ctx_file = '.runs/verify-context.json' if skill == 'verify' else f'.runs/{skill}-context.json'
    run_id = None
    if os.path.isfile(ctx_file):
        ctx = json.load(open(ctx_file))
        run_id = ctx.get('run_id', '')

    # Scan history for matching entry (last match wins)
    best_q = None
    with open(history_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (run_id and entry.get('run_id') == run_id) or entry.get('skill') == skill:
                best_q = entry.get('q_skill', 0)

    if best_q is None:
        errors.append(f'No Q-score entry found for skill={skill}')
        return

    if best_q < min_score:
        errors.append(f'Q-score {best_q} below minimum {min_score}')


def main():
    if len(sys.argv) < 3:
        print('Usage: phase-gate.py <config_path> <phase_index>', file=sys.stderr)
        sys.exit(1)

    config_path = sys.argv[1]
    phase_index = int(sys.argv[2])

    config = json.load(open(config_path))
    skill = config['skill']
    phase = config['phases'][phase_index]
    gate = phase.get('gate')

    # Null gate -> always pass
    if gate is None:
        sys.exit(0)

    errors = []

    if 'completed_states' in gate:
        check_completed_states(skill, gate['completed_states'], errors)
    if 'files_exist' in gate:
        check_files_exist(gate['files_exist'], errors)
    if 'postconditions' in gate:
        check_postconditions(skill, phase['state_range'], errors)
    if 'plan_fields' in gate:
        check_plan_fields(gate['plan_fields'], errors)
    if 'q_score_min' in gate:
        check_q_score(skill, gate['q_score_min'], errors)

    if errors:
        for e in errors:
            print(f'GATE FAIL: {e}', file=sys.stderr)
        sys.exit(1)

    sys.exit(0)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f'GATE ERROR: {e}', file=sys.stderr)
        sys.exit(1)
