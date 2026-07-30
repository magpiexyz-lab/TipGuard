#!/usr/bin/env python3
"""agent-trace-schema-validator.py — gate #7 validator (AOC v1.3).

Closes #1449 / #1431 / #1433 Phase C residual: every trace-writing agent
must emit `workarounds[]` and `template_gap_observed[]` keys (empty arrays
allowed) per agent-output-contract.md AOC v1.3. This validator scans
.runs/agent-traces/*.json (filtered to the active run) and logs any
missing-field violations to .runs/lead-deviation-log.jsonl via the shared
atomic appender.

Mode resolution: prose_gate_mode.resolve("agent-trace-schema-completeness",
prior_default="warn"). PR 2 lands in warn mode (collect data); PR 3 flips
to deny after observation.

Required keys per AOC v1.3:
  - workarounds (must be present, value must be a list)
  - template_gap_observed (must be present, value must be a list)

Both default to empty lists when no observations were made — absence is
the violation, not a non-empty value.

Skipped traces:
  - Traces from a different run_id (only validates current run's traces)
  - Traces that are empty/malformed JSON (gracefully skipped, not flagged)

Usage:
  python3 .claude/scripts/lib/agent-trace-schema-validator.py [--mode warn|deny]

Exit codes:
  0 = pass (all traces have keys, OR mode=warn even with violations)
  1 = fail (mode=deny AND ≥1 violation)
"""

from __future__ import annotations

import argparse
import datetime
import glob
import json
import os
import sys
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from prose_gate_mode import resolve  # noqa: E402
from append_deviation_log import append as append_deviation  # noqa: E402

GATE_ID = "agent-trace-schema-completeness"
TRACES_DIR = ".runs/agent-traces"
REQUIRED_KEYS = ("workarounds", "template_gap_observed")


def _active_run_id() -> str:
    """Return the most-recently-written non-completed skill's run_id."""
    best = None
    best_ts = ""
    for f in glob.glob(".runs/*-context.json"):
        if f.endswith("/epilogue-context.json"):
            continue
        try:
            d = json.load(open(f))
        except Exception:
            continue
        if d.get("completed") is True:
            continue
        ts = d.get("timestamp", "") or ""
        if ts >= best_ts:
            best = d
            best_ts = ts
    return (best or {}).get("run_id", "")


def _check_trace(trace: dict) -> list[str]:
    """Return list of missing/malformed required keys."""
    violations: list[str] = []
    for key in REQUIRED_KEYS:
        if key not in trace:
            violations.append(f"missing key: {key!r}")
        elif not isinstance(trace[key], list):
            violations.append(
                f"key {key!r} must be a list, got {type(trace[key]).__name__}"
            )
    return violations


def _log_violation(
    trace_path: str, agent: str, run_id: str, violations: list[str]
) -> None:
    entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "run_id": run_id,
        "skill": "",  # filled below
        "state_id": "",
        "gate_id": GATE_ID,
        "gate_layer": "prose-gates-v1",
        "deviation_type": "schema-incompleteness",
        "evidence": {
            "trace_path": trace_path,
            "agent": agent,
            "violated_fields": violations,
        },
        "auto_filed": False,
    }
    # Resolve active skill from context for the entry's skill field.
    for f in glob.glob(".runs/*-context.json"):
        if f.endswith("/epilogue-context.json"):
            continue
        try:
            d = json.load(open(f))
        except Exception:
            continue
        if d.get("run_id") == run_id:
            entry["skill"] = d.get("skill", "")
            completed = d.get("completed_states", []) or []
            entry["state_id"] = str(completed[-1]) if completed else ""
            break
    append_deviation(entry)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--mode",
        choices=["warn", "deny"],
        default=None,
        help="Override mode resolution. Defaults via prose_gate_mode.resolve().",
    )
    ap.add_argument(
        "--traces-dir",
        default=TRACES_DIR,
        help=f"Path to agent-traces directory (default: {TRACES_DIR})",
    )
    args = ap.parse_args()

    if args.mode:
        mode = args.mode
    else:
        mode = resolve(GATE_ID, prior_default="warn")

    if not os.path.isdir(args.traces_dir):
        # No traces written this run — nothing to validate, exit clean.
        return 0

    rid = _active_run_id()
    violation_count = 0
    examined_count = 0

    for path in sorted(glob.glob(os.path.join(args.traces_dir, "*.json"))):
        try:
            trace = json.load(open(path))
        except Exception:
            # Malformed JSON is a separate concern; skip silently here.
            continue
        # Filter to current run only (avoid flagging stale traces).
        if rid and trace.get("run_id") and trace.get("run_id") != rid:
            continue
        examined_count += 1
        violations = _check_trace(trace)
        if violations:
            violation_count += 1
            agent = trace.get("agent", os.path.basename(path).replace(".json", ""))
            _log_violation(path, agent, rid, violations)
            tag = "BLOCK" if mode == "deny" else "WARN"
            print(
                f"{tag}: {GATE_ID}: {agent} trace at {path} missing AOC v1.3 keys: "
                f"{', '.join(violations)}",
                file=sys.stderr,
            )

    if violation_count == 0:
        return 0

    if mode == "deny":
        print(
            f"BLOCK: {GATE_ID}: {violation_count} of {examined_count} traces "
            f"missing AOC v1.3 required keys (workarounds[]/template_gap_observed[]).",
            file=sys.stderr,
        )
        return 1

    # warn mode: deviations logged, exit 0.
    print(
        f"WARN: {GATE_ID}: {violation_count} of {examined_count} traces missing "
        f"AOC v1.3 keys; logged to .runs/lead-deviation-log.jsonl. "
        f"PR 3 will flip mode to deny.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
