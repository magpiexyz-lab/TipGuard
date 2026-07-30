#!/usr/bin/env python3
"""Offline trace aggregation for /resolve --refine.

Reads GitHub trace comments (compact v2 and legacy formats), applies
staleness filtering, computes per-state failure rates, and writes a
compact summary to .runs/refine-analysis.json.

Usage:
  python3 .claude/scripts/refine-analysis.py --repo owner/repo [--compact]

Exit 0 always — never blocks the caller.
"""
import argparse
import glob
import json
import os
import subprocess as sp
import sys


def _gh(args, timeout=15):
    """Run a gh CLI command. Returns stdout or empty string on failure."""
    try:
        r = sp.run(['gh'] + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ''
    except Exception:
        return ''


def _git_hash(path):
    """Get current git blob hash for a file (first 7 chars)."""
    try:
        r = sp.run(['git', 'hash-object', path],
                    capture_output=True, text=True, timeout=5)
        return r.stdout.strip()[:7] if r.returncode == 0 else ''
    except Exception:
        return ''


def fetch_traces(repo):
    """Fetch all trace issue comments. Returns list of (comment_id, body, issue_number)."""
    raw = _gh(['issue', 'list', '--repo', repo, '--label', 'trace',
               '--json', 'number,title', '--limit', '50'])
    if not raw:
        return []
    issues = json.loads(raw)

    traces = []
    for issue in issues:
        num = issue['number']
        page = 1
        while True:
            raw = _gh(['api', f'repos/{repo}/issues/{num}/comments',
                        '--jq', '.[] | [.id, .body] | @tsv',
                        '-f', f'per_page=100', '-f', f'page={page}'],
                       timeout=20)
            if not raw:
                break
            for line in raw.split('\n'):
                if '\t' not in line:
                    continue
                cid, body = line.split('\t', 1)
                traces.append((int(cid), body, num))
            if raw.count('\n') < 99:
                break
            page += 1

    return traces


def parse_comment(body):
    """Parse a trace comment body. Returns normalized dict or None."""
    body = body.strip()
    if not body.startswith('{'):
        # Could be a JSON array from compaction
        if body.startswith('['):
            try:
                arr = json.loads(body)
                return [parse_comment(json.dumps(e)) for e in arr if isinstance(e, dict)]
            except Exception:
                return None
        return None

    try:
        d = json.loads(body)
    except Exception:
        return None

    if d.get('v') == 2:
        # Compact format
        sr = {}
        for sid, vals in d.get('sr', {}).items():
            if isinstance(vals, list) and len(vals) == 2:
                sr[sid] = {'first_pass': vals[0] == 1, 'attempts': vals[1]}
        return {
            'skill': d.get('s', ''),
            'run_id': d.get('r', ''),
            'member': d.get('m', 'unknown'),
            'state_results': sr,
            'hashes': d.get('h', {}),
            'claude_md_hash': d.get('c', ''),
            'format': 'compact',
        }
    elif 'skill' in d and 'state_results' in d:
        # Legacy full format
        skill = d.get('skill', '')
        tv = d.get('template_version', {})
        sr_raw = d.get('state_results', {})
        hashes = {}
        for sid in sr_raw:
            prefix = f'.claude/skills/{skill}/state-{sid}-'
            for path, blob_hash in tv.items():
                if path.startswith(prefix):
                    hashes[sid] = blob_hash[:7]
                    break
        return {
            'skill': skill,
            'run_id': d.get('run_id', ''),
            'member': d.get('team_member', 'unknown'),
            'state_results': sr_raw,
            'hashes': hashes,
            'claude_md_hash': tv.get('CLAUDE.md', '')[:7] if tv.get('CLAUDE.md') else '',
            'format': 'legacy',
        }

    return None


def filter_stale(entries):
    """Apply per-state staleness filter. Returns (entries_with_relevant_states, stale_count)."""
    hash_cache = {}
    stale_count = 0
    result = []

    for entry in entries:
        relevant_states = {}
        for sid, data in entry['state_results'].items():
            skill = entry['skill']
            pattern = f'.claude/skills/{skill}/state-{sid}-*.md'
            matches = glob.glob(pattern)
            if not matches:
                stale_count += 1
                continue

            state_file = matches[0]
            if state_file not in hash_cache:
                hash_cache[state_file] = _git_hash(state_file)

            current = hash_cache[state_file]
            trace_hash = entry['hashes'].get(sid, '')

            if not trace_hash or not current:
                stale_count += 1
                continue

            if current.startswith(trace_hash) or trace_hash.startswith(current):
                relevant_states[sid] = data
            else:
                stale_count += 1

        if relevant_states:
            entry_copy = dict(entry)
            entry_copy['relevant_states'] = relevant_states
            result.append(entry_copy)

    return result, stale_count


def compute_failure_rates(entries):
    """Compute per-(skill, state_id) failure rates from relevant entries."""
    buckets = {}  # key: "skill/state_id"
    for entry in entries:
        skill = entry['skill']
        member = entry['member']
        for sid, data in entry.get('relevant_states', {}).items():
            key = f'{skill}/{sid}'
            if key not in buckets:
                buckets[key] = {'total': 0, 'fails': 0, 'members_failed': set()}
            buckets[key]['total'] += 1
            if not data.get('first_pass', True):
                buckets[key]['fails'] += 1
                buckets[key]['members_failed'].add(member)

    summary = {}
    for key, b in buckets.items():
        total, fails = b['total'], b['fails']
        members = sorted(b['members_failed'])
        if total < 5:
            summary[key] = {
                'failure_rate': round(fails / max(total, 1), 2),
                'total': total, 'fails': fails,
                'team_members_affected': members,
                'status': 'INSUFFICIENT_DATA',
            }
            continue

        rate = round(fails / total, 2)
        if rate > 0.30 and len(members) >= 2:
            status = 'HIGH'
        elif rate > 0.10:
            status = 'MEDIUM'
        else:
            status = 'LOW'

        summary[key] = {
            'failure_rate': rate,
            'total': total, 'fails': fails,
            'team_members_affected': members,
            'status': status,
        }

    return summary


def compute_team_versions(entries):
    """Compute per-member CLAUDE.md version info."""
    current_claude = _git_hash('CLAUDE.md')
    members = {}
    for entry in entries:
        m = entry['member']
        ch = entry.get('claude_md_hash', '')
        if ch and (m not in members or entry.get('run_id', '') > members[m].get('run_id', '')):
            members[m] = {'claude_md_hash': ch, 'run_id': entry.get('run_id', '')}

    result = {}
    for m, info in members.items():
        result[m] = {
            'claude_md_hash': info['claude_md_hash'],
            'latest': current_claude.startswith(info['claude_md_hash']),
        }
    return result


def do_compact(repo, traces, entries):
    """Consolidate old comments into a single JSON array comment per issue."""
    # Group entries and comment IDs by issue number
    by_issue = {}
    for cid, _body, inum in traces:
        by_issue.setdefault(inum, []).append(cid)

    # Group relevant entries by issue (via trace list matching)
    entry_by_issue = {}
    for entry in entries:
        # Find which issue this entry came from (by matching run_id in traces)
        for cid, body, inum in traces:
            if entry.get('run_id', '__none__') in body:
                entry_by_issue.setdefault(inum, []).append(entry)
                break

    for inum, cids in by_issue.items():
        if len(cids) <= 1:
            continue

        # Take the most recent 100 entries for this issue
        issue_entries = entry_by_issue.get(inum, [])[-100:]
        if not issue_entries:
            continue

        # Build compact array from entries
        compact_arr = []
        for e in issue_entries:
            compact = {
                'v': 2, 's': e['skill'], 'r': e['run_id'], 'm': e['member'],
                'sr': {sid: [1 if d.get('first_pass', True) else 0, d.get('attempts', 1)]
                       for sid, d in e.get('relevant_states', e.get('state_results', {})).items()},
                'h': e.get('hashes', {}),
            }
            if e.get('claude_md_hash'):
                compact['c'] = e['claude_md_hash']
            compact_arr.append(compact)

        body = json.dumps(compact_arr, separators=(',', ':'))
        if len(body) > 60000:
            compact_arr = compact_arr[-50:]
            body = json.dumps(compact_arr, separators=(',', ':'))

        # Post consolidated comment
        _gh(['issue', 'comment', str(inum), '--repo', repo, '--body', body], timeout=15)

        # Delete old individual comments
        deleted = 0
        for cid in cids:
            result = _gh(['api', '-X', 'DELETE', f'repos/{repo}/issues/comments/{cid}'],
                         timeout=10)
            deleted += 1

        print(f'Compacted {len(cids)} comments into 1 for issue #{inum} '
              f'({len(compact_arr)} entries kept)', file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description='Offline trace analysis for /resolve --refine')
    parser.add_argument('--repo', required=True, help='Template repo (owner/repo)')
    parser.add_argument('--compact', action='store_true', help='Consolidate old comments')
    args = parser.parse_args()

    # Fetch all trace comments
    traces = fetch_traces(args.repo)
    if not traces:
        print('No trace issues found', file=sys.stderr)
        os.makedirs('.runs', exist_ok=True)
        json.dump({'trace_summary': {}, 'team_versions': {}, 'stats': {
            'total_entries': 0, 'stale_filtered': 0, 'relevant': 0,
        }}, open('.runs/refine-analysis.json', 'w'), indent=2)
        return

    # Parse all comments (handle arrays from prior compaction)
    entries = []
    for _cid, body, _inum in traces:
        parsed = parse_comment(body)
        if parsed is None:
            continue
        if isinstance(parsed, list):
            entries.extend(p for p in parsed if p is not None)
        else:
            entries.append(parsed)

    total_entries = len(entries)

    # Staleness filter
    relevant, stale_count = filter_stale(entries)

    # Compute aggregates
    summary = compute_failure_rates(relevant)
    versions = compute_team_versions(entries)

    # Write output
    os.makedirs('.runs', exist_ok=True)
    result = {
        'trace_summary': summary,
        'team_versions': versions,
        'stats': {
            'total_entries': total_entries,
            'stale_filtered': stale_count,
            'relevant': len(relevant),
        },
    }
    with open('.runs/refine-analysis.json', 'w') as f:
        json.dump(result, f, indent=2)

    print(f'Refine analysis: {total_entries} entries, {stale_count} stale, '
          f'{len(relevant)} relevant, {len(summary)} state buckets', file=sys.stderr)

    # Optional compaction
    if args.compact and len(traces) > 10:
        do_compact(args.repo, traces, relevant)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f'refine-analysis: warning — {e}', file=sys.stderr)
        # Write empty result on failure so caller has a file to read
        os.makedirs('.runs', exist_ok=True)
        json.dump({'trace_summary': {}, 'team_versions': {}, 'stats': {
            'total_entries': 0, 'stale_filtered': 0, 'relevant': 0,
        }}, open('.runs/refine-analysis.json', 'w'), indent=2)
        sys.exit(0)
