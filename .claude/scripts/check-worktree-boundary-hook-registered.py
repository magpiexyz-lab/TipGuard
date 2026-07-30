#!/usr/bin/env python3
"""
Recurrence guard for issue #1225 — worktree-boundary hook registration.

Asserts that:
  1. .claude/hooks/worktree-boundary-gate.sh exists and is executable.
  2. settings.json registers it under PreToolUse for every tool that takes a
     write-target path: Write, Edit, MultiEdit, NotebookEdit.

Position within each matcher's hooks list is unconstrained (PreToolUse hooks
run independently — order has no filtering effect).

Exits non-zero on violation. Intended to run from lifecycle-finalize.sh
alongside check-worktree-ownership-pattern.py.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # .claude/scripts/<this> → repo root
HOOK_REL = ".claude/hooks/worktree-boundary-gate.sh"
SETTINGS = ROOT / ".claude" / "settings.json"
REQUIRED_MATCHERS = ("Write", "Edit", "MultiEdit", "NotebookEdit")

errors: list[str] = []


def check_hook_file() -> None:
    hook_path = ROOT / HOOK_REL
    if not hook_path.exists():
        errors.append(f"{HOOK_REL}: hook file missing")
        return
    if not os.access(hook_path, os.X_OK):
        errors.append(f"{HOOK_REL}: hook file not executable (chmod +x)")


def check_registration() -> None:
    if not SETTINGS.exists():
        errors.append(".claude/settings.json: missing")
        return
    try:
        data = json.loads(SETTINGS.read_text())
    except json.JSONDecodeError as e:
        errors.append(f".claude/settings.json: invalid JSON ({e})")
        return

    pretool = data.get("hooks", {}).get("PreToolUse", [])
    matchers_seen: dict[str, bool] = {m: False for m in REQUIRED_MATCHERS}

    for entry in pretool:
        matcher = entry.get("matcher")
        if matcher not in REQUIRED_MATCHERS:
            continue
        for hook in entry.get("hooks", []):
            cmd = hook.get("command", "")
            if "worktree-boundary-gate.sh" in cmd:
                matchers_seen[matcher] = True
                break

    for matcher, seen in matchers_seen.items():
        if not seen:
            errors.append(
                f".claude/settings.json: worktree-boundary-gate.sh not registered "
                f"under PreToolUse matcher '{matcher}'"
            )


def main() -> int:
    check_hook_file()
    check_registration()
    if errors:
        print("worktree-boundary-hook-registered violations:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("worktree-boundary-hook-registered: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
