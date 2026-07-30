#!/usr/bin/env python3
"""Initialize agent trace with started status.

Usage:
    python3 scripts/init-trace.py <agent-name>
    python3 scripts/init-trace.py <agent-name> <trace-filename>
    python3 scripts/init-trace.py <agent-name> --context <context-file>
    python3 scripts/init-trace.py <agent-name> --context <context-file> <trace-filename>

Args:
    agent-name:     Required. E.g. "design-critic"
    --context:      Optional. Path to context JSON file for run_id.
                    Defaults to ".runs/verify-context.json".
                    Use for cross-skill agents: --context .runs/resolve-context.json
                    AOC v1.2 NOTE: this flag IS the post-completion identity
                    override for init-trace.py — pass `.runs/<skill>-context.json`
                    explicitly even when that file has completed:true. init-trace
                    does not call resolve_active_identity (which would otherwise
                    return empty); it reads the supplied context file directly.
    trace-filename: Optional. Defaults to "<agent-name>.json".
                    Use for per-page traces: "design-critic-landing.json"

Writes: .runs/agent-traces/<trace-filename>
Schema: {"agent": str, "status": "started", "timestamp": str, "run_id": str}
"""
import json
import os
import sys
from datetime import datetime, timezone

if len(sys.argv) < 2:
    print("Usage: init-trace.py <agent-name> [trace-filename]", file=sys.stderr)
    sys.exit(1)

agent = sys.argv[1]
context_file = ".runs/verify-context.json"
trace_file = f"{agent}.json"
i = 2
while i < len(sys.argv):
    if sys.argv[i] == "--context" and i + 1 < len(sys.argv):
        context_file = sys.argv[i + 1]
        i += 2
    else:
        trace_file = sys.argv[i]
        i += 1

run_id = ""
try:
    with open(context_file) as f:
        run_id = json.load(f).get("run_id", "")
except Exception:
    pass

os.makedirs(".runs/agent-traces", exist_ok=True)

trace = {
    "agent": agent,
    "status": "started",
    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "run_id": run_id,
}

with open(f".runs/agent-traces/{trace_file}", "w") as f:
    json.dump(trace, f, indent=2)
    f.write("\n")
