#!/usr/bin/env python3
"""Convergence report — standalone, manually-run analysis tool.

Reads the last `window_size` entries from `.runs/convergence-history.jsonl`
(produced by /resolve STATE 9) and prints a flip-rate report. Not wired into
any skill state; safe to run at any time.

Output:
- "Insufficient sample size" when history < min_sample_size (exit 0, silent-ish)
- Summary stats: flip_rate, mean time between same-file resolves (days)
- A single-line warning when the most-recent `consecutive_over_threshold_required`
  runs all exceed `flip_rate_threshold`
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

CONFIG_PATH = os.path.join(REPO_ROOT, ".claude", "patterns", "convergence-config.json")
HISTORY_PATH = os.path.join(REPO_ROOT, ".runs", "convergence-history.jsonl")


def load_config() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def load_history(limit: int) -> list[dict]:
    if not os.path.exists(HISTORY_PATH):
        return []
    out: list[dict] = []
    with open(HISTORY_PATH) as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                out.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
    return out[-limit:] if limit > 0 else out


def _parse_ts(s: str) -> datetime | None:
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def mean_days_between_same_file(entries: list[dict]) -> float | None:
    """For files touched by 2+ runs, compute average inter-run spacing in days.
    Return None when no file recurs.
    """
    by_file: dict[str, list[datetime]] = defaultdict(list)
    for e in entries:
        ts = _parse_ts(e.get("timestamp", ""))
        if ts is None:
            continue
        for f in e.get("files_touched", []) or []:
            by_file[f].append(ts)
    diffs: list[float] = []
    for f, stamps in by_file.items():
        if len(stamps) < 2:
            continue
        stamps.sort()
        for i in range(1, len(stamps)):
            diffs.append((stamps[i] - stamps[i - 1]).total_seconds() / 86400.0)
    if not diffs:
        return None
    return sum(diffs) / len(diffs)


def per_run_flip_rate(e: dict) -> float:
    n = int(e.get("divergence_points_analyzed") or 0)
    if n == 0:
        return 0.0
    return int(e.get("oscillation_count_sum") or 0) / n


def main(argv: list[str]) -> int:
    config = load_config()
    window_size = int(config.get("window_size", 30))
    min_sample = int(config.get("min_sample_size", 10))
    threshold = float(config.get("flip_rate_threshold", 0.05))
    consecutive_required = int(config.get("consecutive_over_threshold_required", 2))

    entries = load_history(window_size)
    if len(entries) < min_sample:
        print(
            f"Insufficient sample size ({len(entries)} < {min_sample}). "
            "Run more /resolve iterations before reading the report."
        )
        return 0

    osc_sum = sum(int(e.get("oscillation_count_sum") or 0) for e in entries)
    dps_sum = sum(int(e.get("divergence_points_analyzed") or 0) for e in entries)
    flip_rate = (osc_sum / dps_sum) if dps_sum else 0.0
    halts = sum(1 for e in entries if e.get("halted"))
    mean_days = mean_days_between_same_file(entries)

    print(f"Convergence report — last {len(entries)} /resolve runs")
    print(f"  flip_rate:                   {flip_rate:.4f}  (sum {osc_sum} / {dps_sum})")
    print(f"  halted runs:                 {halts}")
    if mean_days is None:
        print(f"  mean_days_between_same_file: n/a (no file recurrence)")
    else:
        print(f"  mean_days_between_same_file: {mean_days:.1f}")

    recent = entries[-consecutive_required:]
    if (
        len(recent) == consecutive_required
        and all(per_run_flip_rate(e) > threshold for e in recent)
    ):
        print(
            f"\nWARNING: last {consecutive_required} runs all exceeded flip_rate "
            f"threshold {threshold} — investigate the oscillating fixes."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
