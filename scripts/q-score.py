#!/usr/bin/env python3
"""Q-Score Reader — reads verify-history.jsonl and reports skill quality trends.

Usage: python3 scripts/q-score.py [--skill <name>] [--json]

Part of the Unified Skill Quality Framework (USQF).
See .claude/patterns/q-score.md for the specification.
"""

import json
import os
import sys
from collections import defaultdict
from statistics import median


HISTORY_FILE = ".runs/verify-history.jsonl"
WINDOW_SIZE = 5  # sliding window for median


def load_entries():
    """Load all entries from verify-history.jsonl."""
    if not os.path.exists(HISTORY_FILE):
        return []
    entries = []
    with open(HISTORY_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def group_by_skill(entries):
    """Group entries by skill name."""
    groups = defaultdict(list)
    for e in entries:
        skill = e.get("skill", "unknown")
        groups[skill].append(e)
    return dict(groups)


def compute_trend(q_values):
    """Compute trend direction from Q values.

    Compares median of last 3 runs to prior 3 runs.
    Returns: 'improving', 'degrading', or 'stable'.
    """
    if len(q_values) < 4:
        return "insufficient data"
    recent = q_values[-3:]
    prior = q_values[-6:-3] if len(q_values) >= 6 else q_values[:-3]
    if not prior:
        return "insufficient data"
    recent_med = median(recent)
    prior_med = median(prior)
    diff = recent_med - prior_med
    if diff > 0.05:
        return "improving"
    elif diff < -0.05:
        return "degrading"
    return "stable"


def compute_pipeline_q(skill_groups):
    """Compute pipeline Q: 0 if any Gate fails, else geometric mean."""
    latest_q = {}
    for skill, entries in skill_groups.items():
        last = entries[-1]
        gate = last.get("gate", 1.0)
        if gate == 0.0:
            return 0.0, skill  # pipeline blocked by this skill
        latest_q[skill] = last.get("q_skill", 1.0)

    if not latest_q:
        return None, None

    # Geometric mean
    product = 1.0
    for q in latest_q.values():
        product *= max(q, 0.001)  # floor to avoid zero
    geo_mean = product ** (1.0 / len(latest_q))
    return round(geo_mean, 3), None


def format_table(rows, headers):
    """Format a simple ASCII table."""
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))

    fmt = " | ".join(f"{{:<{w}}}" for w in col_widths)
    sep = "-+-".join("-" * w for w in col_widths)

    lines = [fmt.format(*headers), sep]
    for row in rows:
        lines.append(fmt.format(*[str(c) for c in row]))
    return "\n".join(lines)


def report_skill(skill, entries, verbose=True):
    """Generate report for a single skill."""
    q_values = [e.get("q_skill", None) for e in entries if e.get("q_skill") is not None]

    if not q_values:
        return f"  {skill}: no Q data"

    window = q_values[-WINDOW_SIZE:]
    med_q = round(median(window), 3)
    min_q = round(min(q_values), 3)
    max_q = round(max(q_values), 3)
    trend = compute_trend(q_values)
    runs = len(entries)

    result = {
        "skill": skill,
        "runs": runs,
        "median_q": med_q,
        "min_q": min_q,
        "max_q": max_q,
        "trend": trend,
    }

    if verbose and entries:
        last = entries[-1]
        dims = last.get("dimension_scores", {})
        if dims:
            weakest_dim = min(dims, key=dims.get)
            result["weakest_dimension"] = f"{weakest_dim} ({dims[weakest_dim]})"
        result["last_gate"] = last.get("gate", "N/A")
        result["last_r_system"] = last.get("r_system", "N/A")
        result["last_r_human"] = last.get("r_human", "N/A")

    return result


def main():
    filter_skill = None
    output_json = False

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--skill" and i + 1 < len(args):
            filter_skill = args[i + 1]
            i += 2
        elif args[i] == "--json":
            output_json = True
            i += 1
        else:
            i += 1

    entries = load_entries()
    if not entries:
        print("No verify-history.jsonl found or file is empty.")
        print("Q-scores are generated after running /verify, /bootstrap, or /change.")
        sys.exit(0)

    groups = group_by_skill(entries)

    if filter_skill:
        if filter_skill not in groups:
            print(f"No entries found for skill '{filter_skill}'.")
            print(f"Available skills: {', '.join(sorted(groups.keys()))}")
            sys.exit(0)
        groups = {filter_skill: groups[filter_skill]}

    # Per-skill reports
    reports = []
    for skill in sorted(groups.keys()):
        report = report_skill(skill, groups[skill])
        if isinstance(report, dict):
            reports.append(report)

    if output_json:
        pipeline_q, blocker = compute_pipeline_q(group_by_skill(entries))
        output = {
            "skills": reports,
            "pipeline_q": pipeline_q,
            "pipeline_blocker": blocker,
            "total_entries": len(entries),
        }
        print(json.dumps(output, indent=2))
        return

    # ASCII output
    print(f"\n  Q-Score Report ({len(entries)} total entries)")
    print(f"  {'=' * 60}\n")

    # Summary table
    rows = []
    for r in reports:
        rows.append([
            r["skill"],
            r["runs"],
            r["median_q"],
            r["min_q"],
            r["max_q"],
            r["trend"],
        ])

    print(format_table(rows, ["Skill", "Runs", "Median Q", "Min Q", "Max Q", "Trend"]))

    # Dimension breakdown for each skill
    print(f"\n  Latest Run Details")
    print(f"  {'-' * 40}")
    for r in reports:
        weakest = r.get("weakest_dimension", "N/A")
        gate = r.get("last_gate", "N/A")
        r_sys = r.get("last_r_system", "N/A")
        r_hum = r.get("last_r_human", "N/A")
        print(f"  {r['skill']}: Gate={gate}, R_sys={r_sys}, R_hum={r_hum}, Weakest={weakest}")

    # Pipeline Q
    pipeline_q, blocker = compute_pipeline_q(group_by_skill(entries))
    print(f"\n  Pipeline Q: ", end="")
    if pipeline_q is None:
        print("N/A (no data)")
    elif blocker:
        print(f"0.0 (blocked by {blocker} hard gate failure)")
    else:
        print(f"{pipeline_q}")
    print()


if __name__ == "__main__":
    main()
