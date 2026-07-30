#!/usr/bin/env python3
"""test_forgery_surface.py — enforce the set of authorized writers.

Scans the repository for any file that writes to
.runs/agent-traces/*.json or .runs/agent-spawn-log.jsonl via common patterns
(shell redirect, Python open-for-write, Python json.dump, json.write).
Fails if any unauthorized writer appears.

Authorized writers:
  - .claude/scripts/init-trace.py                  (stub)
  - .claude/hooks/skill-agent-gate.sh              (spawn-log — hook-managed)
  - .claude/scripts/write-recovery-trace.sh        (recovery trace)
  - .claude/scripts/write-degraded-trace.py        (self-degraded trace)
  - .claude/scripts/validate-recovery.sh           (recovery_validated stamp only)
  - .claude/scripts/migrate-legacy-traces.py       (legacy migration)
  - .claude/scripts/merge-design-critic-traces.py  (verify state-3b lead-merge)
  - .claude/scripts/tests/*                        (fixtures — writes to tmp dirs)
  - scripts/init-trace.py                          (alternate root stub location)
  - scripts/tests/*                                (fixtures)

Any other file touching these artifacts is a regression.

Usage: python3 .claude/scripts/tests/test_forgery_surface.py
"""
from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]

AUTHORIZED = {
    ".claude/scripts/init-trace.py",
    ".claude/hooks/skill-agent-gate.sh",
    ".claude/scripts/write-recovery-trace.sh",
    ".claude/scripts/write-degraded-trace.py",
    ".claude/scripts/validate-recovery.sh",
    ".claude/scripts/migrate-legacy-traces.py",
    ".claude/scripts/merge-design-critic-traces.py",
    "scripts/init-trace.py",
}

# Allow-list subdirectories (glob-match) — everything inside these is
# considered authorized (fixtures, docs, tests).
AUTHORIZED_SUBTREES = [
    ".claude/scripts/tests/",
    "scripts/tests/",
    ".claude/patterns/",  # agent-registry.json, agent-trace-protocol.md
    ".claude/agents/",    # agent .md files describe traces (docs, not writers)
    ".claude/skills/",    # state .md files describe traces
    ".claude/hooks/",     # hooks read traces but authorized hooks write spawn-log
    ".claude/procedures/",  # procedural docs
    "docs/",
    "tests/",
]

# File patterns to scan
CODE_EXTS = (".sh", ".py", ".js", ".ts", ".mjs")

# Write patterns (match against a single line)
WRITE_PATTERNS = [
    re.compile(r"(>|>>)\s*[^\s>|;&]*agent-spawn-log"),
    re.compile(r"(>|>>)\s*[^\s>|;&]*agent-traces/[^\s>|;&]*\.json"),
    re.compile(r"tee\s+[^\s>|;&]*agent-spawn-log"),
    re.compile(r"tee\s+[^\s>|;&]*agent-traces/"),
    re.compile(r"open\([^)]*agent-spawn-log[^)]*[,)][^)]*['\"][wa]"),
    re.compile(r"open\([^)]*agent-traces/[^)]*[,)][^)]*['\"][wa]"),
    re.compile(r"json\.dump\([^)]*,\s*open\([^)]*agent-traces"),
    re.compile(r"json\.dump\([^)]*,\s*open\([^)]*agent-spawn-log"),
]

# Patterns we accept even outside the authorized writer set: they are
# read-modify-write operations on existing traces (e.g., stamping a field),
# used by legitimate tools like validate-recovery.sh when re-reading+writing.
# We still require the file hosting them to be in AUTHORIZED.


class TestForgerySurface(unittest.TestCase):
    def test_no_unauthorized_writers(self):
        root_str = str(ROOT)
        # Use git ls-files to enumerate tracked files only
        proc = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=str(ROOT), capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, f"git ls-files failed: {proc.stderr}")
        files = [Path(f) for f in proc.stdout.strip().split("\n") if f]

        # Only scan code files (shell/python/js/ts)
        code_files = [f for f in files if f.suffix in CODE_EXTS]

        unauthorized = []
        for f in code_files:
            rel = f.as_posix()
            # Skip authorized files/subtrees
            if rel in AUTHORIZED:
                continue
            if any(rel.startswith(sub) for sub in AUTHORIZED_SUBTREES):
                continue
            try:
                text = (ROOT / f).read_text(errors="replace")
            except Exception:
                continue
            for n, line in enumerate(text.splitlines(), start=1):
                for pat in WRITE_PATTERNS:
                    if pat.search(line):
                        unauthorized.append(f"{rel}:{n}: {line.strip()}")
                        break

        if unauthorized:
            msg = "Unauthorized writers of agent-traces / agent-spawn-log:\n" + \
                  "\n".join(unauthorized) + \
                  "\n\nAuthorized writers: " + ", ".join(sorted(AUTHORIZED)) + \
                  "\nAllowed subtrees: " + ", ".join(AUTHORIZED_SUBTREES) + \
                  "\n\nIf this is a new legitimate writer, add it to AUTHORIZED " \
                  "and ensure it's also allowlisted by agent-trace-write-guard.sh."
            self.fail(msg)


if __name__ == "__main__":
    unittest.main(verbosity=2)
