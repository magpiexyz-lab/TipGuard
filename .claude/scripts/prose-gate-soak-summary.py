#!/usr/bin/env python3
"""Per-gate soak summary for prose-gates infrastructure.

Reads .runs/lead-deviation-log.jsonl, groups by gate_id over a time window,
and emits a regime-aware threshold report. Used by operators before/after
each per-gate Phase B/C flip to detect anomalies.

Regime thresholds (auto-selected by sample size):
  - binary  (n < 10):   any new entry within window → status=investigate
  - rate    (10 ≤ n < 100): current > 1.5× baseline_avg → status=rollback
  - stat    (n ≥ 100):  current > baseline + 2σ → status=rollback

Window: --window 24h | 7d | 30d (default 7d). The "current" window is the
most recent --current-window (default 24h), and "baseline" is the rest of
--window minus --current-window.

Usage:
    python3 prose-gate-soak-summary.py --gate <id> --window 7d
    python3 prose-gate-soak-summary.py --gate all --window 7d
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import re
import sys

DEVIATION_LOG_PATH = ".runs/lead-deviation-log.jsonl"
WRITE_FAILURES_PATH = ".runs/lead-deviation-log.write-failures.jsonl"


def _parse_window(s: str) -> datetime.timedelta:
    m = re.match(r"^(\d+)([hdw])$", s.strip())
    if not m:
        raise ValueError(f"window must be like 24h, 7d, 4w; got {s!r}")
    n, unit = int(m.group(1)), m.group(2)
    return {
        "h": datetime.timedelta(hours=n),
        "d": datetime.timedelta(days=n),
        "w": datetime.timedelta(weeks=n),
    }[unit]


def _parse_ts(s: str) -> datetime.datetime | None:
    if not s:
        return None
    try:
        # ISO 8601, may end with Z or +00:00
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _load_entries(path: str = DEVIATION_LOG_PATH) -> list[dict]:
    if not os.path.isfile(path):
        return []
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def _filter_window(entries: list[dict], start: datetime.datetime, end: datetime.datetime) -> list[dict]:
    out = []
    for e in entries:
        ts = _parse_ts(e.get("timestamp", "") or e.get("ts", ""))
        if ts is None:
            continue
        if start <= ts < end:
            out.append(e)
    return out


def _classify_regime(baseline_n: int) -> str:
    if baseline_n < 10:
        return "binary"
    if baseline_n < 100:
        return "rate"
    return "stat"


def _summarize_one_gate(
    gate_id: str,
    entries: list[dict],
    now: datetime.datetime,
    total_window: datetime.timedelta,
    current_window: datetime.timedelta,
) -> dict:
    if current_window > total_window:
        raise ValueError("--current-window must be <= --window")

    current_start = now - current_window
    baseline_start = now - total_window
    baseline_end = current_start

    gate_entries = [e for e in entries if e.get("gate_id") == gate_id]
    current = _filter_window(gate_entries, current_start, now)
    baseline = _filter_window(gate_entries, baseline_start, baseline_end)

    baseline_n = len(baseline)
    current_n = len(current)
    regime = _classify_regime(baseline_n)

    status = "ok"
    threshold_desc = ""

    if regime == "binary":
        threshold_desc = "any new entry → investigate"
        if current_n > 0:
            status = "investigate"
    elif regime == "rate":
        # baseline avg per current_window
        baseline_avg = baseline_n * (current_window.total_seconds() / max(
            (baseline_end - baseline_start).total_seconds(), 1.0))
        threshold = baseline_avg * 1.5
        threshold_desc = f"baseline_avg×1.5 = {threshold:.2f}"
        if current_n > threshold:
            status = "rollback"
    else:  # stat
        baseline_avg = baseline_n * (current_window.total_seconds() / max(
            (baseline_end - baseline_start).total_seconds(), 1.0))
        # crude std: sqrt(avg) for poisson approx (we don't have per-bucket data)
        sigma = math.sqrt(max(baseline_avg, 1.0))
        threshold = baseline_avg + 2.0 * sigma
        threshold_desc = f"baseline_avg + 2σ = {threshold:.2f}"
        if current_n > threshold:
            status = "rollback"

    return {
        "gate_id": gate_id,
        "regime": regime,
        "baseline_count": baseline_n,
        "baseline_window": f"{baseline_start.isoformat()} → {baseline_end.isoformat()}",
        "current_count": current_n,
        "current_window": f"{current_start.isoformat()} → {now.isoformat()}",
        "threshold": threshold_desc,
        "status": status,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--gate", required=True,
        help="Gate id or 'all' for every gate found in deviation log."
    )
    ap.add_argument(
        "--window", default="7d",
        help="Total window (baseline + current). Default 7d."
    )
    ap.add_argument(
        "--current-window", default="24h",
        help="Current window inside --window. Default 24h."
    )
    ap.add_argument(
        "--write-failures", action="store_true",
        help="Also report write-failures.jsonl count (presence is always actionable)."
    )
    args = ap.parse_args()

    total_w = _parse_window(args.window)
    current_w = _parse_window(args.current_window)
    now = datetime.datetime.now(datetime.timezone.utc)

    entries = _load_entries()

    if args.gate == "all":
        gate_ids = sorted({
            e.get("gate_id", "") for e in entries if e.get("gate_id")
        })
    else:
        gate_ids = [args.gate]

    summaries = [
        _summarize_one_gate(g, entries, now, total_w, current_w)
        for g in gate_ids
    ]

    out = {"summaries": summaries, "now": now.isoformat()}

    if args.write_failures:
        wf_count = 0
        if os.path.isfile(WRITE_FAILURES_PATH):
            with open(WRITE_FAILURES_PATH) as f:
                wf_count = sum(1 for line in f if line.strip())
        out["write_failures_count"] = wf_count
        out["write_failures_status"] = "investigate" if wf_count > 0 else "ok"

    print(json.dumps(out, indent=2))
    # Exit 1 if any gate shows status != ok (machine-readable rollback signal)
    statuses = {s["status"] for s in summaries}
    if "rollback" in statuses:
        return 2
    if "investigate" in statuses or out.get("write_failures_status") == "investigate":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
