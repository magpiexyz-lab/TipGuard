#!/usr/bin/env python3
"""check-1257-attestation.py — Operator helper for issue #1257 closure attestation.

Reads .runs/consistency-soak-telemetry.jsonl (raw-fields records appended by
merge-design-consistency-checker-traces.py on every multi-batch run) and
applies the closure criterion documented in step55-evidence-rollout.md:

  * provenance == "lead-merge"
  * contributing_spawn_indexes_count >= 2
  * contributing_spawn_indexes_count >= partition_size  (full batch coverage)
  * pages_reviewed_total >= 12
  * status == "completed"

The 4th clause (`csi_count >= partition_size`) closes the asymmetric-defense gap:
state-3b VERIFY gates partial-spawn at pipeline-time, but the merger emits
telemetry BEFORE VERIFY runs, so partial-spawn records persist on disk. Without
this clause, an 18-page project where batch 3 never spawned would still show
csi_count=2, pages=12, status=completed and falsely attest.

The predicate is evaluated at READ time (NOT precomputed at WRITE time) so future
criterion changes (e.g., raising the page threshold) do NOT strand existing records.

Exit codes:
  0 — ATTESTED: at least one telemetry record satisfies the criterion.
  1 — NOT ATTESTED: telemetry exists but no record attests, OR no telemetry yet.

Usage:
  python3 .claude/scripts/check-1257-attestation.py
  python3 .claude/scripts/check-1257-attestation.py --telemetry-path /path/to/file.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any


DEFAULT_TELEMETRY = ".runs/consistency-soak-telemetry.jsonl"


def is_attesting(rec: dict[str, Any]) -> bool:
    """Apply the #1257 closure criterion at READ time.

    Full attestation requires (a) the multi-batch path ran (provenance, csi>=2),
    (b) the project was non-trivial (pages>=12), (c) the merger completed, AND
    (d) full batch coverage (csi_count >= partition_size).

    The 4th clause closes the asymmetric-defense gap exposed during /solve --defect
    post-merge audit: state-3b VERIFY gates partial-spawn at pipeline-time, but the
    merger emits telemetry BEFORE VERIFY runs, so partial-spawn records persist on
    disk. Without the read-time `csi_count >= partition_size` check, an 18-page
    project where batch 3 silently never spawned would still show
    `csi_count=2, pages_reviewed_total=12, status=completed` and falsely attest.

    The criterion is applied at READ time (NOT precomputed at write time) so future
    changes do not strand existing records — see step55-evidence-rollout.md
    `## #1257 Attestation Telemetry` for the canonical declaration."""
    # `(rec.get(k) or 0)` handles both missing key and explicit null value;
    # `rec.get(k, 0)` would propagate a json-null and TypeError on `>=` (mirrors
    # the R2 critic isinstance-guard defensive pattern).
    csi_count = rec.get("contributing_spawn_indexes_count") or 0
    partition_size = rec.get("partition_size") or 0
    pages = rec.get("pages_reviewed_total") or 0
    return (
        rec.get("provenance") == "lead-merge"
        and csi_count >= 2
        and csi_count >= partition_size
        and pages >= 12
        and rec.get("status") == "completed"
    )


def _read_records(path: str) -> list[dict[str, Any]]:
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return []
    records: list[dict[str, Any]] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                records.append(rec)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check issue #1257 production attestation status from telemetry.",
    )
    parser.add_argument(
        "--telemetry-path",
        default=DEFAULT_TELEMETRY,
        help=f"Telemetry JSONL path (default: {DEFAULT_TELEMETRY})",
    )
    args = parser.parse_args(argv)

    records = _read_records(args.telemetry_path)
    if not records:
        print(
            f"NOT ATTESTED: no telemetry yet ({args.telemetry_path} absent or empty)",
            file=sys.stderr,
        )
        return 1

    for rec in records:
        if is_attesting(rec):
            print(f"ATTESTED: {json.dumps(rec, sort_keys=True)}")
            return 0

    print(
        f"NOT ATTESTED: {len(records)} records inspected; "
        f"latest={json.dumps(records[-1], sort_keys=True)}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
