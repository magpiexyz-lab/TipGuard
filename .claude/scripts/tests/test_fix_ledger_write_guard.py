#!/usr/bin/env python3
"""test_fix_ledger_write_guard.py — runtime guard on .runs/fix-ledger.jsonl
and .runs/fix-log.md writes.

Sibling test for `test_agent_trace_write_guard.py` and
`test_trace_write_guard.py`. AOC v1 FLS v1 protects the canonical fix-log
artifacts from arbitrary shell writes; only `write-fix-ledger.py` and
`render-fix-log.py` are allowed writers.

Closes #1298 — heredoc-body data text in $COMMAND must NOT match the
bound-redirect or allow-list regexes.

Run: python3 .claude/scripts/tests/test_fix_ledger_write_guard.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HOOK = ROOT / ".claude/hooks/fix-ledger-write-guard.sh"


class TestFixLedgerWriteGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_flwg_"))
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        shutil.copytree(ROOT / ".claude", self.tmp / ".claude", dirs_exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _invoke(self, command: str) -> tuple[int, str]:
        payload = json.dumps({
            "tool_name": "Bash",
            "tool_input": {"command": command},
        })
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(self.tmp)
        proc = subprocess.run(
            ["bash", str(HOOK)],
            input=payload,
            capture_output=True, text=True, env=env, timeout=10,
        )
        return proc.returncode, proc.stderr

    def _assert_allowed(self, cmd: str, msg: str = ""):
        rc, err = self._invoke(cmd)
        self.assertEqual(rc, 0, f"expected allow for {cmd!r}; stderr={err} {msg}")

    def _assert_denied(self, cmd: str, substr: str = ""):
        rc, err = self._invoke(cmd)
        self.assertNotEqual(rc, 0, f"expected deny for {cmd!r}")
        if substr:
            self.assertIn(substr, err, f"expected deny reason to mention {substr!r}; got {err}")

    # ---- Fast path ----

    def test_fast_path_no_mention(self):
        self._assert_allowed("ls .runs/", "fast-path: unrelated command")

    def test_fast_path_mentions_fix_ledger_but_no_write(self):
        self._assert_allowed(
            "cat .runs/fix-ledger.jsonl",
            "reading fix-ledger.jsonl must allow",
        )

    def test_fast_path_mentions_fix_log_but_no_write(self):
        self._assert_allowed(
            "grep -c 'Fix' .runs/fix-log.md",
            "reading fix-log.md must allow",
        )

    # ---- Allowed writers ----

    def test_write_fix_ledger_py_allowed(self):
        self._assert_allowed(
            "python3 .claude/scripts/write-fix-ledger.py --consolidate",
            "write-fix-ledger.py must short-circuit",
        )

    def test_render_fix_log_py_allowed(self):
        self._assert_allowed(
            "python3 .claude/scripts/render-fix-log.py",
            "render-fix-log.py must short-circuit",
        )

    def test_state_0_header_init_allowed(self):
        # Benign known-residual: STATE 0 init writes the header to fix-log.md.
        self._assert_allowed(
            "echo '# Error Fix Log' > .runs/fix-log.md",
            "STATE 0 header init must allow",
        )

    # ---- Direct shell-redirect denials ----

    def test_raw_redirect_to_fix_ledger_denied(self):
        self._assert_denied(
            "echo {} > .runs/fix-ledger.jsonl",
            ".runs/fix-ledger.jsonl",
        )

    def test_raw_redirect_to_fix_log_denied(self):
        self._assert_denied(
            "echo 'forge' > .runs/fix-log.md",
            ".runs/fix-log.md",
        )

    def test_chained_write_after_allowed_writer_denied(self):
        """ORDER: bound check runs BEFORE allow-list, so chain bypass is caught."""
        self._assert_denied(
            "python3 .claude/scripts/write-fix-ledger.py && echo forge >> .runs/fix-log.md",
            "fix-log",
        )

    # ---- Python open() denials ----

    def test_python_open_w_on_fix_ledger_denied(self):
        self._assert_denied(
            "python3 -c \"open('.runs/fix-ledger.jsonl', 'w').write('{}')\"",
            "open-for-write",
        )

    def test_python_open_a_on_fix_log_denied(self):
        self._assert_denied(
            "python3 -c \"open('.runs/fix-log.md', 'a').write('forge\\n')\"",
            "open-for-write",
        )

    # ---- Issue #1298: heredoc-body false positive class ----

    def test_1298_heredoc_body_mentions_fix_ledger_path_allows(self):
        """#1298: prose mentioning .runs/fix-ledger.jsonl inside a heredoc
        body must NOT trigger the bound-redirect — the body is data, not shell."""
        cmd = (
            "cat > /tmp/r.txt << 'EOF'\n"
            "Doc on .runs/fix-ledger.jsonl format; see write-fix-ledger.py.\n"
            "Example bad: echo {} > .runs/fix-ledger.jsonl\n"
            "EOF"
        )
        self._assert_allowed(cmd, "heredoc-body mention must allow")

    def test_1298_heredoc_body_mentions_fix_log_path_allows(self):
        """#1298: prose mentioning .runs/fix-log.md inside a heredoc body
        must NOT trigger the bound-redirect."""
        cmd = (
            "cat > /tmp/r.txt << 'EOF'\n"
            "Walkthrough: render-fix-log.py rebuilds .runs/fix-log.md;\n"
            "Example forge: echo bad > .runs/fix-log.md\n"
            "EOF"
        )
        self._assert_allowed(cmd, "heredoc-body mention must allow")

    def test_1298_chained_heredoc_then_real_write_denies(self):
        """#1298 r1-c1: trailing real write to fix-ledger must still deny.
        The strip_heredoc_bodies loop-bug fix preserves the trailing write
        so the bound-redirect catch-all fires correctly."""
        cmd = (
            "cat << 'EOF'\n"
            "harmless body\n"
            "EOF\n"
            "echo {} > .runs/fix-ledger.jsonl"
        )
        self._assert_denied(cmd, "fix-ledger")

    def test_1298_python_heredoc_fed_open_still_denies(self):
        """#1298 r1-c2: heredoc-fed python open() must still deny.
        The python-open regex runs on RAW $COMMAND with `coherence-allow:
        raw-command` pragma so canonicalization doesn't hide the attack."""
        cmd = (
            "python3 << 'PY'\n"
            "open('.runs/fix-ledger.jsonl', 'w').write('{}')\n"
            "PY"
        )
        self._assert_denied(cmd, "open-for-write")


if __name__ == "__main__":
    unittest.main()
