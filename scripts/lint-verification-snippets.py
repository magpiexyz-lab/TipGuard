#!/usr/bin/env python3
"""
lint-verification-snippets.py — CI-only lint for SK verification_snippet fields.

Added M3 (PR #1397 retro). Runs from .github/workflows/stack-knowledge-validate.yml.

For each Stack Knowledge entry that has a `verification_snippet` field:

1. Project-agnostic check — reject any snippet containing user-specific paths
   (`/Users/`, `/home/<lowercase>`). Cross-project SK entries must be runnable
   from any repo root on any developer's machine.

2. Shellcheck — pipe the snippet through shellcheck (bash dialect). Any
   shellcheck error fails the lint.

Snippets without a verification_snippet field are silently skipped.

Exit codes:
  0 — all snippets pass (or no snippets present)
  1 — at least one snippet failed (full error report to stderr)
  2 — bootstrap failure (shellcheck not installed, parser broken, etc.)
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

USER_PATH_RE = re.compile(r"(/Users/|/home/[a-z])")


def main() -> int:
    if shutil.which("shellcheck") is None:
        print(
            "FAIL: shellcheck not installed. CI workflow installs via apt-get. "
            "Local lint: brew install shellcheck",
            file=sys.stderr,
        )
        return 2

    try:
        from stack_knowledge_parser import (
            iter_stack_knowledge_files,
            parse_stack_knowledge_file,
        )
    except ImportError as e:
        print(f"FAIL: cannot import stack_knowledge_parser: {e}", file=sys.stderr)
        return 2

    failures: list[str] = []
    snippets_checked = 0

    for sf_path in iter_stack_knowledge_files():
        try:
            entries = parse_stack_knowledge_file(sf_path)
        except Exception as e:
            print(f"WARN: cannot parse {sf_path}: {e}", file=sys.stderr)
            continue

        for entry in entries:
            snippet = entry.get("verification_snippet")
            if not snippet or not isinstance(snippet, str):
                continue

            entry_id = entry.get("id", "<unknown>")
            snippets_checked += 1

            # Project-agnostic check
            if USER_PATH_RE.search(snippet):
                failures.append(
                    f"{sf_path} entry {entry_id!r}: verification_snippet "
                    "contains user-specific path (/Users/ or /home/<user>)"
                )
                continue

            # Shellcheck pipe
            try:
                r = subprocess.run(
                    ["shellcheck", "-s", "bash", "-"],
                    input=snippet,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            except subprocess.TimeoutExpired:
                failures.append(
                    f"{sf_path} entry {entry_id!r}: shellcheck timed out (>10s)"
                )
                continue

            if r.returncode != 0:
                failures.append(
                    f"{sf_path} entry {entry_id!r}: shellcheck reported issues:\n"
                    + (r.stdout or r.stderr or "(no shellcheck output)")
                )

    for f in failures:
        print("FAIL: " + f, file=sys.stderr)

    print(
        f"verification_snippet lint: {snippets_checked} snippet(s) checked, "
        f"{len(failures)} failure(s)"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
