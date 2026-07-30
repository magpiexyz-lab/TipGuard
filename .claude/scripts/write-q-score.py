#!/usr/bin/env python3
"""Shared Q-score writer — consolidates all Q computation and storage.

Usage (compute mode):
  python3 .claude/scripts/write-q-score.py \
    --skill <name> --scope <scope> --archetype <arch> \
    --gate <0|1> --dims '{"dim1": 0.9}' \
    [--r-human <float>] [--run-id <id>] \
    [--build-attempts N] [--fix-log-entries N] \
    [--hard-gate-failure] [--process-violation] \
    [--overall-verdict pass|fail]

Usage (raw mode — pre-built entry):
  python3 .claude/scripts/write-q-score.py --raw '{"skill":"verify",...}'

Exit 0 always — never blocks the caller.
"""
import argparse
import datetime
import json
import os
import sys


def compute_q(gate, dimension_scores, r_human=0.0):
    """Q_skill = Gate * (1 - R), R = 0.3 * R_system + 0.7 * R_human."""
    active = list(dimension_scores.values())
    r_system = round(1 - (sum(active) / max(len(active), 1)), 3) if active else 0.0
    r = round(0.3 * r_system + 0.7 * r_human, 3)
    q_skill = round(gate * (1 - r), 3)
    return q_skill, r_system, r


def _compact_entry(entry):
    """Create a compact trace entry (~150-200 bytes) for GitHub upload.

    Compact format (v2) stores only what /resolve --refine needs:
    state_results, per-state file hashes, team member, and CLAUDE.md hash.
    """
    skill = entry.get('skill', '')
    tv = entry.get('template_version', {})
    sr_raw = entry.get('state_results', {})

    # Compact state_results: {state_id: [first_pass_as_0_or_1, attempts]}
    sr = {}
    for sid, data in sr_raw.items():
        fp = 1 if data.get('first_pass', True) else 0
        sr[sid] = [fp, data.get('attempts', 1)]

    # Per-state file hashes: only for states that ran
    h = {}
    for sid in sr_raw:
        prefix = f'.claude/skills/{skill}/state-{sid}-'
        for path, blob_hash in tv.items():
            if path.startswith(prefix):
                h[sid] = blob_hash[:7]
                break

    compact = {
        'v': 2,
        's': skill,
        'r': entry.get('run_id', ''),
        'm': entry.get('team_member', 'unknown'),
        'sr': sr,
        'h': h,
    }

    # CLAUDE.md hash for team version report
    claude_hash = tv.get('CLAUDE.md', '')
    if claude_hash:
        compact['c'] = claude_hash[:7]

    return compact


def write_entry(entry):
    """Write entry: always local, then attempt GitHub if configured."""
    import subprocess as sp

    # ALWAYS write local
    os.makedirs('.runs', exist_ok=True)
    with open('.runs/verify-history.jsonl', 'a') as f:
        f.write(json.dumps(entry) + '\n')

    backend = os.environ.get('SKILL_HISTORY_BACKEND', 'github')

    if backend == 'github':
        _upload_to_github(entry)
    elif backend == 'api':
        _upload_to_api(entry)

    print(f"Q-score: {entry['q_skill']} (Gate={entry['gate']}, "
          f"R={entry.get('r_system', 0)}) — appended to verify-history.jsonl")


def _upload_to_github(entry):
    """Post trace as GitHub issue comment. Best-effort."""
    import subprocess as sp
    try:
        # Find template repo via GitHub API
        current_repo = sp.run(
            ['gh', 'repo', 'view', '--json', 'nameWithOwner', '-q', '.nameWithOwner'],
            capture_output=True, text=True, timeout=10
        ).stdout.strip()
        if not current_repo:
            return

        repo_info = sp.run(
            ['gh', 'api', f'repos/{current_repo}',
             '--jq', '.template_repository.full_name // .parent.full_name // empty'],
            capture_output=True, text=True, timeout=10
        ).stdout.strip()
        if not repo_info:
            repo_info = current_repo  # Template repo or standalone — trace to self

        member = entry.get('team_member', 'unknown')

        # Find existing trace issue for this member
        result = sp.run(
            ['gh', 'issue', 'list', '--repo', repo_info, '--label', 'trace',
             '--search', f'Trace: {member} in:title', '--json', 'number', '--limit', '1'],
            capture_output=True, text=True, timeout=10
        )
        issues = json.loads(result.stdout) if result.stdout.strip() else []

        if issues:
            issue_num = issues[0]['number']
        else:
            # Create new trace issue
            create = sp.run(
                ['gh', 'issue', 'create', '--repo', repo_info, '--label', 'trace',
                 '--title', f'Trace: {member}',
                 '--body', f'Automated trace collection for {member}'],
                capture_output=True, text=True, timeout=15
            )
            url = create.stdout.strip()
            issue_num = url.rstrip('/').split('/')[-1] if '/' in url else None

        if issue_num:
            sp.run(
                ['gh', 'issue', 'comment', str(issue_num), '--repo', repo_info,
                 '--body', json.dumps(_compact_entry(entry), separators=(',', ':'))],
                capture_output=True, text=True, timeout=10
            )
    except Exception:
        pass  # Silent — local already written


def _upload_to_api(entry):
    """Legacy HTTP API upload. Best-effort."""
    import urllib.request
    endpoint = os.environ.get('SKILL_HISTORY_ENDPOINT', '')
    if not endpoint:
        return
    try:
        req = urllib.request.Request(
            endpoint, data=json.dumps(entry).encode(),
            headers={'Content-Type': 'application/json'}, method='POST'
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass  # Silent — local already written


def _enrich_entry(entry, skill=None, run_id=None):
    """Add team_member, template_version, schema_version, state_results if missing."""
    import subprocess

    if 'template_version' not in entry:
        try:
            result = subprocess.run(
                ['git', 'ls-tree', '-r', 'HEAD', '.claude/', 'CLAUDE.md'],
                capture_output=True, text=True, timeout=5
            )
            file_hashes = {}
            for line in result.stdout.strip().split('\n'):
                if line:
                    parts = line.split('\t')
                    if len(parts) == 2:
                        blob_hash = parts[0].split()[2]
                        file_path = parts[1]
                        file_hashes[file_path] = blob_hash
            entry['template_version'] = file_hashes
        except Exception:
            entry['template_version'] = {}

    if 'team_member' not in entry:
        try:
            gh_result = subprocess.run(
                ['gh', 'api', 'user', '-q', '.login'],
                capture_output=True, text=True, timeout=10
            )
            gh_login = gh_result.stdout.strip() if gh_result.returncode == 0 else ''
            entry['team_member'] = gh_login or subprocess.run(
                ['git', 'config', 'user.name'],
                capture_output=True, text=True, timeout=2
            ).stdout.strip() or 'unknown'
        except Exception:
            entry['team_member'] = 'unknown'

    if 'schema_version' not in entry:
        entry['schema_version'] = 1

    if 'state_results' not in entry:
        skill_name = skill or entry.get('skill', '')
        rid = run_id or entry.get('run_id', '')
        state_results = {}
        trace_file = f'.runs/{skill_name}-execution-trace.jsonl'
        if skill_name and os.path.exists(trace_file):
            with open(trace_file) as f:
                for line in f:
                    try:
                        t = json.loads(line)
                        if t.get('run_id') != rid:
                            continue
                        sid = t['state_id']
                        if sid not in state_results:
                            state_results[sid] = {
                                'first_pass': t['verify_result'] == 'pass',
                                'attempts': 0
                            }
                        state_results[sid]['attempts'] += 1
                    except Exception:
                        continue
        entry['state_results'] = state_results


def main():
    parser = argparse.ArgumentParser(description='Compute and record Q-score')
    parser.add_argument('--raw', type=str, help='Pre-built entry JSON (raw mode)')
    parser.add_argument('--skill', type=str)
    parser.add_argument('--scope', type=str)
    parser.add_argument('--archetype', type=str, default='N/A')
    parser.add_argument('--gate', type=float, default=1.0)
    parser.add_argument('--dims', type=str, default='{}')
    parser.add_argument('--r-human', type=float, default=0.0)
    parser.add_argument('--run-id', type=str, default='')
    parser.add_argument('--build-attempts', type=int, default=0)
    parser.add_argument('--fix-log-entries', type=int, default=0)
    parser.add_argument('--hard-gate-failure', action='store_true')
    parser.add_argument('--process-violation', action='store_true')
    parser.add_argument('--overall-verdict', type=str, default='pass')
    args = parser.parse_args()

    # Raw mode: write pre-built entry with enrichment
    if args.raw:
        entry = json.loads(args.raw)
        _enrich_entry(entry)
        write_entry(entry)
        return

    # Compute mode: calculate Q and build entry
    dims = json.loads(args.dims)
    q_skill, r_system, r = compute_q(args.gate, dims, args.r_human)

    ts = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    run_id = args.run_id if args.run_id else f"{args.skill}-{ts}"

    # AOC v1 FLS v1: when --fix-log-entries is 0 (default), auto-source from
    # the authoritative ledger. If the ledger is absent, fall back to the
    # CLI value (which remains 0 in the default case).
    fix_log_entries = args.fix_log_entries
    if fix_log_entries == 0:
        import os
        ledger_path = os.path.join(os.environ.get('CLAUDE_PROJECT_DIR', '.'),
                                   '.runs', 'fix-ledger.jsonl')
        if os.path.isfile(ledger_path):
            try:
                with open(ledger_path) as _f:
                    fix_log_entries = sum(1 for ln in _f if ln.strip())
            except OSError:
                pass

    entry = {
        'timestamp': ts,
        'run_id': run_id,
        'skill': args.skill,
        'scope': args.scope or args.skill,
        'archetype': args.archetype,
        'build_attempts': args.build_attempts,
        'fix_log_entries': fix_log_entries,
        'hard_gate_failure': args.hard_gate_failure,
        'process_violation': args.process_violation,
        'overall_verdict': args.overall_verdict,
        'dimension_scores': dims,
        'gate': args.gate,
        'r_system': r_system,
        'r_human': args.r_human,
        'q_skill': q_skill,
    }

    _enrich_entry(entry, skill=args.skill, run_id=run_id)
    write_entry(entry)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"Q-score: warning — scoring failed ({e})", file=sys.stderr)
        sys.exit(0)  # Never block the caller
