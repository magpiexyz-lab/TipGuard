#!/usr/bin/env python3
"""Append one hook-friction row to .runs/hook-friction.jsonl (#1128 Layer 2).

Inputs from environment variables (avoids shell-quoting injection — R2.1 fix):
  HOOK_FRICTION_HOOK         hook script basename (e.g., "fix-ledger-write-guard.sh")
  HOOK_FRICTION_REASON       deny() message
  HOOK_FRICTION_TOOL_NAME    Bash | Edit | Write | ...
  HOOK_FRICTION_BLOCKED_CMD  first 200 chars of tool_input (sanitized)
  HOOK_FRICTION_ACTION_TYPE  classification token (#1393, #1379 G-class):
                              "block"                    — hook denied (exit 2)
                              "warn-mode-bypass"         — hook MODE=warn fired
                              "manual-write-sanctioned"  — lead Write of an
                                                            artifact declared
                                                            sanctioned via
                                                            procedure marker
                              "manual-write-deviation"   — lead Write outside
                                                            any sanctioned-marker
                                                            declaration (default
                                                            when no marker)
                             Defaults to "block" (legacy hooks that don't pass
                             the env var still classify as block; safer-default
                             per round-2 plan caveat re: bootstrap-phase-a-write-guard.sh).

Reads run_id and skill from the active context file (.runs/<skill>-context.json,
same scheme used by scan-template-edits.sh and aggregate-hook-friction.py).

Fail-open: never raises. Any error → exit 0 silently. The caller's deny()
contract (stderr + exit 2) is preserved verbatim.
"""
import datetime
import glob
import json
import os
import sys


def _active_context():
    best = None
    best_ts = ''
    try:
        for f in glob.glob('.runs/*-context.json'):
            if 'epilogue' in f:
                continue
            try:
                d = json.load(open(f))
            except Exception:
                continue
            if d.get('completed') is True:
                continue
            ts = d.get('timestamp') or ''
            if ts >= best_ts:
                best = d
                best_ts = ts
    except Exception:
        pass
    return best or {}


VALID_ACTION_TYPES = {
    "block",
    "warn-mode-bypass",
    "manual-write-sanctioned",
    "manual-write-deviation",
}


def main():
    try:
        ctx = _active_context()
        # #1393 + #1379 r3 — action_type discriminator. Default to "block" so
        # legacy hooks that don't set the env var classify as block (safer
        # default; avoids dilution of the deviation signal — round-2 plan caveat
        # re: bootstrap-phase-a-write-guard.sh which currently doesn't set it).
        action_type = os.environ.get("HOOK_FRICTION_ACTION_TYPE", "block")
        if action_type not in VALID_ACTION_TYPES:
            action_type = "block"
        row = {
            "hook": os.environ.get("HOOK_FRICTION_HOOK", "unknown"),
            "tool_name": os.environ.get("HOOK_FRICTION_TOOL_NAME", ""),
            "blocked_command": os.environ.get("HOOK_FRICTION_BLOCKED_CMD", "")[:200],
            "reason": os.environ.get("HOOK_FRICTION_REASON", "")[:500],
            "action_type": action_type,
            "run_id": ctx.get("run_id", ""),
            "skill": ctx.get("skill", ""),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        os.makedirs('.runs', exist_ok=True)
        with open('.runs/hook-friction.jsonl', 'a') as f:
            f.write(json.dumps(row) + '\n')
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
