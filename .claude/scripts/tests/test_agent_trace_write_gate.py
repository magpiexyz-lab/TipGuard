#!/usr/bin/env python3
"""test_agent_trace_write_gate.py — runtime guard on Write/Edit to agent-traces.

Companion test to test_agent_trace_write_guard.py (which exercises the Bash
guard). This file exercises the Write/Edit gate added in PR3 Phase C2.

Hook protocol (Claude Code):
  exit 0 = allow
  exit non-zero = block

The gate ships in WARN-mode (PR3): emits stderr WARN, exits 0. PR4 will flip
the MODE sentinel to "deny" after a soak window. These tests cover both
modes by reading and patching the MODE line so they remain meaningful in
either configuration.

Run: python3 .claude/scripts/tests/test_agent_trace_write_gate.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HOOK_SRC = ROOT / ".claude/hooks/agent-trace-write-gate.sh"


class TestAgentTraceWriteGate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_atwgate_"))
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        shutil.copytree(ROOT / ".claude", self.tmp / ".claude", dirs_exist_ok=True)
        # Hook copy is mutable — tests may flip MODE via _patch_mode.
        self.hook = self.tmp / ".claude/hooks/agent-trace-write-gate.sh"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _patch_mode(self, mode: str) -> None:
        """Patch the MODE sentinel in the test copy of the hook."""
        text = self.hook.read_text()
        # Replace the existing MODE="..." line.
        new_text = []
        replaced = False
        for line in text.splitlines(True):
            if line.startswith("MODE=") and not replaced:
                new_text.append(f'MODE="{mode}"\n')
                replaced = True
            else:
                new_text.append(line)
        if not replaced:
            raise AssertionError("MODE sentinel not found in hook source")
        self.hook.write_text("".join(new_text))

    def _invoke(self, file_path: str, tool_name: str = "Write") -> tuple[int, str]:
        if tool_name == "Write":
            payload_input = {"file_path": file_path, "content": "{}"}
        else:  # Edit
            payload_input = {"file_path": file_path, "old_string": "x", "new_string": "y"}
        payload = json.dumps({
            "tool_name": tool_name,
            "tool_input": payload_input,
        })
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(self.tmp)
        proc = subprocess.run(
            ["bash", str(self.hook)],
            input=payload,
            capture_output=True, text=True, env=env, timeout=10,
        )
        return proc.returncode, proc.stderr

    # ---- Path fast-path: unrelated paths must always allow silently ----

    def test_unrelated_file_path_silent_allow(self):
        rc, err = self._invoke("src/app/page.tsx")
        self.assertEqual(rc, 0)
        self.assertEqual(err.strip(), "", "unrelated path must produce no output")

    def test_runs_non_traces_file_silent_allow(self):
        rc, err = self._invoke(".runs/verify-context.json")
        self.assertEqual(rc, 0)
        self.assertEqual(err.strip(), "")

    def test_agent_traces_non_json_silent_allow(self):
        rc, err = self._invoke(".runs/agent-traces/notes.txt")
        self.assertEqual(rc, 0)
        self.assertEqual(err.strip(), "", ".txt outside .json scope")

    # ---- WARN mode (PR3 default): stderr WARN, exit 0 ----

    def test_warn_mode_agent_traces_write_emits_warn(self):
        self._patch_mode("warn")
        rc, err = self._invoke(".runs/agent-traces/forge.json", tool_name="Write")
        self.assertEqual(rc, 0, f"WARN mode must exit 0; got {rc}; stderr={err}")
        self.assertIn("WARN", err)
        self.assertIn("agent-traces", err)
        self.assertIn("write-agent-trace.sh", err)

    def test_warn_mode_agent_traces_edit_emits_warn(self):
        self._patch_mode("warn")
        rc, err = self._invoke(".runs/agent-traces/foo.json", tool_name="Edit")
        self.assertEqual(rc, 0)
        self.assertIn("WARN", err)

    # ---- DENY mode (PR4 after soak): exit non-zero ----

    def test_deny_mode_agent_traces_write_blocks(self):
        self._patch_mode("deny")
        rc, err = self._invoke(".runs/agent-traces/forge.json", tool_name="Write")
        self.assertNotEqual(rc, 0, "deny mode must exit non-zero")
        self.assertIn("agent-traces", err)
        self.assertIn("write-agent-trace.sh", err)

    def test_deny_mode_agent_traces_edit_blocks(self):
        self._patch_mode("deny")
        rc, err = self._invoke(".runs/agent-traces/foo.json", tool_name="Edit")
        self.assertNotEqual(rc, 0)

    def test_deny_mode_unrelated_path_still_silent_allow(self):
        # Mode flip must NOT regress the path fast-path.
        self._patch_mode("deny")
        rc, err = self._invoke("src/app/page.tsx", tool_name="Write")
        self.assertEqual(rc, 0)
        self.assertEqual(err.strip(), "")

    # ---- Misconfiguration: unknown MODE must error out, not silently allow ----

    def test_unknown_mode_errors(self):
        self._patch_mode("audit")  # not "warn" or "deny"
        rc, err = self._invoke(".runs/agent-traces/forge.json", tool_name="Write")
        self.assertEqual(rc, 1, "unknown MODE must exit 1")
        self.assertIn("unknown MODE", err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
