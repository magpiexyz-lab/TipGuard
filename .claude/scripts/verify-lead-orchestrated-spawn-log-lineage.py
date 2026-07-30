#!/usr/bin/env python3
"""verify-lead-orchestrated-spawn-log-lineage.py — lifecycle-finalize
Step 4.8 gate that verifies every lead-orchestrated trace is anchored to
a real spawn-log entry (closes #1275 round-2 critic — actual recurrence
guard for the post-completion path).

For each `.runs/agent-traces/*.json` whose `provenance == 'lead-orchestrated'`,
asserts that `.runs/agent-spawn-log.jsonl` contains an entry with:

  - `agent` matching the trace's agent
  - `run_id` matching the trace's `source_run_id`
  - `hook == 'skill-agent-gate'`
  - `degraded` either absent or false (the hook's three-gate validator
    only stamps non-degraded entries when SOURCE_RUN_ID/SOURCE_SKILL
    are honored)

Without this gate, a forged trace claiming `provenance: lead-orchestrated`
+ arbitrary `source_run_id` could pass the writer's R3 check at write time
(if a degraded entry already existed for some reason) but later be
indistinguishable from a legitimate post-completion re-spawn.

Exits 0 when no lead-orchestrated traces exist OR every trace has a
matching non-degraded spawn-log entry. Exits 1 otherwise with a
diagnostic message.

Wired from .claude/scripts/lifecycle-finalize.sh as Step 4.8.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path


def _load_json(path: str) -> dict | None:
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _spawn_log_has_non_degraded(
    spawn_log_path: str, agent: str, run_id: str
) -> bool:
    if not os.path.isfile(spawn_log_path):
        return False
    try:
        with open(spawn_log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if (
                    e.get("agent") == agent
                    and e.get("run_id") == run_id
                    and e.get("hook") == "skill-agent-gate"
                    and e.get("degraded") is not True
                ):
                    return True
    except OSError:
        return False
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Step 4.8 gate — verify lead-orchestrated trace ↔ spawn-log lineage."
    )
    parser.add_argument(
        "--project-dir",
        default=os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()),
    )
    args = parser.parse_args(argv)
    project_dir = Path(args.project_dir).resolve()
    traces_dir = str(project_dir / ".runs" / "agent-traces")
    spawn_log = str(project_dir / ".runs" / "agent-spawn-log.jsonl")

    if not os.path.isdir(traces_dir):
        return 0

    missing: list[str] = []
    for path in sorted(glob.glob(os.path.join(traces_dir, "*.json"))):
        trace = _load_json(path)
        if not trace:
            continue
        if trace.get("provenance") != "lead-orchestrated":
            continue
        agent = trace.get("agent")
        source_run_id = trace.get("source_run_id")
        if not (isinstance(agent, str) and isinstance(source_run_id, str)
                and agent and source_run_id):
            missing.append(
                f"  - {os.path.basename(path)}: provenance=lead-orchestrated but "
                f"agent or source_run_id missing/invalid"
            )
            continue
        if not _spawn_log_has_non_degraded(spawn_log, agent, source_run_id):
            missing.append(
                f"  - {os.path.basename(path)}: no non-degraded spawn-log entry for "
                f"(agent={agent!r}, run_id={source_run_id!r}, hook=skill-agent-gate). "
                f"Set SOURCE_RUN_ID + SOURCE_SKILL env vars BEFORE invoking the Agent "
                f"tool so skill-agent-gate.sh can stamp the entry."
            )

    if not missing:
        return 0

    sys.stderr.write(
        "BLOCK: Step 4.8 — lead-orchestrated trace lineage check failed.\n"
        "Every lead-orchestrated trace must be anchored to a non-degraded\n"
        "spawn-log entry (skill-agent-gate.sh's SOURCE_RUN_ID honoring path).\n"
        "Missing:\n"
    )
    sys.stderr.write("\n".join(missing) + "\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
