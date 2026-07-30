#!/usr/bin/env python3
"""#1335 signal 3 — detect agent-trace overwrites that may indicate
unsanctioned workaround patterns silently bypassing lead self-judgment in
the retrospective enumerator.

Reads .runs/agent-spawn-log.jsonl. Groups entries by (agent, run_id). For
each agent with 2+ spawns in a single run_id:

  - If agent is in sanctioned-respawn-flows.json AND precondition (if any)
    is met → no candidate (legitimate respawn).
  - If agent is in sanctioned-respawn-flows.json BUT precondition is unmet
    (e.g., solve-critic round-2 with no sidecar archive) → emit candidate
    with high confidence.
  - If agent is NOT sanctioned at all → emit candidate with high confidence.

Output: .runs/trace-overwrite-candidates.json with kind='trace-overwrite'.
Wired into enumerate-pending-retrospective-findings.py as the 5th candidate
source (per /solve plan PR 3 step 10).

Spawn-log schema (verified main, post-#1360):
  {agent, attributed_to, head_sha, hook, run_id, skill, spawn_index, timestamp}

NOTE: spawn-log records SPAWN events, not WRITE events. The 'sanctioned'
classification uses agent identity + an optional precondition_artifact
check (round-2 critic concern 58c839632d84: spawn-log lacks source_state
field; manifest sanctions by agent identity instead).

Fail-open: missing inputs OR parse errors → empty candidate list, exit 0.
This script is a candidate generator, not a gate.
"""
from __future__ import annotations

import datetime
import glob
import hashlib
import json
import os
import sys
from collections import defaultdict


def _hash_key(kind: str, key: str) -> str:
    return hashlib.sha256(f"{kind}:{key}".encode()).hexdigest()[:12]


def _active_run_id() -> str:
    """Find the most recent non-completed skill context's run_id."""
    best = None
    best_ts = ""
    for f in glob.glob(".runs/*-context.json"):
        if "epilogue" in f:
            continue
        try:
            d = json.load(open(f))
        except Exception:
            continue
        if d.get("completed") is True:
            continue
        ts = d.get("timestamp") or ""
        if ts >= best_ts:
            best = d
            best_ts = ts
    return (best or {}).get("run_id", "")


def _load_sanctioned_flows() -> dict:
    """Load sanctioned-respawn-flows.json keyed by agent name."""
    path = ".claude/patterns/sanctioned-respawn-flows.json"
    if not os.path.exists(path):
        return {}
    try:
        data = json.load(open(path))
    except Exception:
        return {}
    out = {}
    for entry in data.get("flows", []):
        if entry.get("agent"):
            out[entry["agent"]] = entry
    return out


def _check_precondition(entry: dict) -> tuple[bool, str]:
    """Return (precondition_met, reason) for a sanctioned-flow entry.

    Returns (True, "") when no precondition is required OR precondition is
    satisfied. Returns (False, reason_string) otherwise.
    """
    pre_path = entry.get("precondition_artifact")
    if not pre_path:
        return True, ""
    if not os.path.exists(pre_path):
        return False, f"precondition artifact missing: {pre_path}"
    try:
        d = json.load(open(pre_path))
    except Exception as e:
        return False, f"cannot parse precondition artifact {pre_path}: {e}"
    field = entry.get("precondition_field")
    value = entry.get("precondition_value")
    if field is None:
        return True, ""
    if d.get(field) != value:
        return False, (
            f"{pre_path}.{field}={d.get(field)!r} expected {value!r}"
        )
    return True, ""


def detect(rid: str) -> list[dict]:
    """Detect trace overwrites for the given run_id."""
    sanctioned = _load_sanctioned_flows()

    spawn_log = ".runs/agent-spawn-log.jsonl"
    if not os.path.exists(spawn_log):
        return []

    groups: dict[str, list[dict]] = defaultdict(list)
    try:
        with open(spawn_log) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if rid and row.get("run_id") != rid:
                    continue
                agent = row.get("agent", "")
                if not agent:
                    continue
                groups[agent].append(row)
    except Exception:
        return []

    candidates: list[dict] = []
    for agent, entries in groups.items():
        if len(entries) < 2:
            continue  # single spawn — no overwrite

        sanction = sanctioned.get(agent)
        precondition_met = True
        precondition_reason = ""
        if sanction:
            precondition_met, precondition_reason = _check_precondition(sanction)
            if precondition_met:
                continue  # sanctioned + precondition met → legitimate

        # Not sanctioned OR sanctioned-but-precondition-failed → emit candidate
        key = f"trace-overwrite:{agent}"
        candidate = {
            "candidate_id": _hash_key("trace-overwrite", key),
            "kind": "trace-overwrite",
            "confidence": "high",
            "key": key,
            "evidence": {
                "agent": agent,
                "spawn_count": len(entries),
                "spawn_indexes": sorted(
                    e.get("spawn_index", -1) for e in entries
                ),
                "sanctioned_in_manifest": bool(sanction),
                "precondition_met": precondition_met,
                "precondition_reason": precondition_reason,
                "first_timestamp": entries[0].get("timestamp"),
                "last_timestamp": entries[-1].get("timestamp"),
            },
            "source_files": [
                ".runs/agent-spawn-log.jsonl",
                ".claude/patterns/sanctioned-respawn-flows.json",
            ],
        }
        candidates.append(candidate)

    return candidates


def main() -> int:
    rid = _active_run_id()
    candidates = detect(rid)
    out = {
        "run_id": rid,
        "schema_version": 1,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "candidates": candidates,
    }
    os.makedirs(".runs", exist_ok=True)
    with open(".runs/trace-overwrite-candidates.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"detect-trace-overwrites: {len(candidates)} candidates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
