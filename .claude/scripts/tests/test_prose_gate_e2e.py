#!/usr/bin/env python3
"""test_prose_gate_e2e.py — E2E coverage for unified prose-gate enforcement.

Closes #1434/#1431/#1393/#1433. Three cases for attribution falsification:

Case 1 (bash write → only new layer fires):
  Synthesize a lead-synthesized trace via `write-agent-trace.sh` with an
  out-of-bound numerical claim. Assert:
    - bound-by-coverage-provider-gate.sh fires (warn-mode: exit 0 with
      lead-deviation-log.jsonl entry carrying gate_layer:prose-gates-v1;
      deny-mode: exit 2)
    - agent-trace-write-gate.sh does NOT fire (Write/Edit matcher, not Bash)

Case 2 (Write tool → only pre-existing layer fires):
  Attempt direct Write of `.runs/agent-traces/design-critic.json`. Assert:
    - bound-by-coverage-provider-gate.sh does NOT fire (Bash matcher; no Bash
      invocation involved)
    - The new layer leaves no gate_layer:prose-gates-v1 attribution

Case 3 (mode flip):
  Same case-1 violation with PROSE_GATE_LEAD_SYNTHESIZED_NUMERICAL_BOUNDS_MODE=warn vs deny.
  Assert exit codes 0 vs 2 respectively, and that deviation-log entries
  are written in both modes (warn-mode logs but does not block).

Run: python3 .claude/scripts/tests/test_prose_gate_e2e.py
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
HOOK = ROOT / ".claude/hooks/bound-by-coverage-provider-gate.sh"
VALIDATOR = ROOT / ".claude/scripts/lib/bound-by-coverage-provider.py"


def _run_hook(payload: dict, env: dict | None = None) -> subprocess.CompletedProcess:
    """Invoke the hook with the given payload via stdin."""
    full_env = dict(os.environ)
    full_env["CLAUDE_PROJECT_DIR"] = str(ROOT)
    if env:
        full_env.update(env)
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=full_env,
        cwd=str(ROOT),
    )


class TestProseGateE2E(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_prose_gate_"))
        # Mirror minimal repo state into a temp workspace so the hook + validator
        # see a clean .runs/ for log assertions.
        (self.tmp / ".runs").mkdir(parents=True, exist_ok=True)
        (self.tmp / ".claude").mkdir(parents=True, exist_ok=True)
        # Symlink hooks/scripts/patterns so they point at the repo's checked-in
        # versions, not stale copies.
        for sub in ("hooks", "scripts", "patterns"):
            src = ROOT / ".claude" / sub
            dst = self.tmp / ".claude" / sub
            if src.exists():
                os.symlink(src, dst)
        # Provide a synthetic coverage_provider for case 1.
        cp = {
            "page_set": ["page-a", "page-b", "page-c"],
            "all_pages_fast_path": True,
            "pr_relevant": 0,
        }
        self.cp_path = self.tmp / ".runs/all-pages-fast-path-decision.json"
        self.cp_path.write_text(json.dumps(cp))
        # Provide an active skill context for run_id resolution.
        ctx = {
            "skill": "verify",
            "run_id": "verify-test-e2e",
            "timestamp": "2026-05-14T00:00:00Z",
            "completed_states": ["3a"],
            "completed": False,
        }
        (self.tmp / ".runs/verify-context.json").write_text(json.dumps(ctx))
        self.log_path = self.tmp / ".runs/lead-deviation-log.jsonl"
        if self.log_path.exists():
            self.log_path.unlink()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _violating_command(self) -> str:
        """A write-agent-trace.sh invocation with out-of-bound numerical claim."""
        trace = {
            "agent": "design-critic",
            "provenance": "lead-synthesized",
            "coverage_provider": str(self.cp_path),
            "verdict": "pass",
            "pages": 5,            # > page_set length of 3
            "pages_reviewed": 10,  # > page_set length of 3
            "min_score": 9,        # < 10 (all-pages-fast-path requires >=10)
            "sections_below_8": 3,  # != 0 (all-pages-fast-path)
        }
        # The hook regex matches `write-agent-trace.sh.*--provenance lead-synthesized`.
        # We invoke the validator directly via the same hook codepath by
        # crafting a Bash payload that the hook will detect.
        return (
            "bash .claude/scripts/write-agent-trace.sh design-critic "
            "--provenance lead-synthesized "
            "--coverage-provider " + str(self.cp_path) + " "
            "--json " + json.dumps(json.dumps(trace))
        )

    def test_case_1_bash_lead_synthesized_violation_warn(self):
        """Hook fires in warn mode: exit 0 + deviation log entry."""
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": self._violating_command()},
        }
        # Run from the tmp workspace so .runs/lead-deviation-log.jsonl lands there.
        result = subprocess.run(
            ["bash", str(HOOK)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            env={
                **os.environ,
                "CLAUDE_PROJECT_DIR": str(self.tmp),
                "PROSE_GATE_LEAD_SYNTHESIZED_NUMERICAL_BOUNDS_MODE": "warn",
            },
            cwd=str(self.tmp),
        )
        # warn-mode: hook should exit 0 (allow); validator output goes to stderr.
        self.assertEqual(result.returncode, 0,
                         f"hook should pass in warn mode; stderr: {result.stderr}")
        # Deviation log should have one entry with gate_layer attribution.
        self.assertTrue(self.log_path.exists(),
                        "lead-deviation-log.jsonl should be created")
        entries = [json.loads(l) for l in self.log_path.read_text().splitlines() if l.strip()]
        self.assertEqual(len(entries), 1, f"expected 1 entry, got {len(entries)}")
        e = entries[0]
        self.assertEqual(e.get("gate_layer"), "prose-gates-v1",
                         "deviation entry must carry gate_layer:prose-gates-v1")
        self.assertEqual(e.get("gate_id"), "lead-synthesized-numerical-bounds")
        self.assertEqual(e.get("deviation_type"), "artifact-fabrication")

    def test_case_2_write_tool_no_new_layer(self):
        """Direct Write payload does NOT fire bound-by-coverage-provider-gate
        (Bash matcher; no Bash invocation).

        We exercise this by invoking the hook with tool_name=Write — the hook
        must fast-path exit 0 and not write any deviation log entry.
        """
        write_payload = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(self.tmp / ".runs/agent-traces/design-critic.json"),
                "content": json.dumps({"agent": "design-critic",
                                       "provenance": "lead-synthesized"}),
            },
        }
        result = subprocess.run(
            ["bash", str(HOOK)],
            input=json.dumps(write_payload),
            text=True,
            capture_output=True,
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(self.tmp)},
            cwd=str(self.tmp),
        )
        self.assertEqual(result.returncode, 0,
                         f"hook must fast-path on non-Bash tool; stderr: {result.stderr}")
        # No new-layer entry should be in the deviation log.
        if self.log_path.exists():
            entries = [json.loads(l) for l in self.log_path.read_text().splitlines() if l.strip()]
            for e in entries:
                self.assertNotEqual(
                    e.get("gate_layer"), "prose-gates-v1",
                    f"Write payload should not produce prose-gates-v1 entry; got: {e}"
                )

    def test_case_3_mode_flip_deny(self):
        """Same case-1 violation with deny mode blocks the write (exit 2)."""
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": self._violating_command()},
        }
        result = subprocess.run(
            ["bash", str(HOOK)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            env={
                **os.environ,
                "CLAUDE_PROJECT_DIR": str(self.tmp),
                "PROSE_GATE_LEAD_SYNTHESIZED_NUMERICAL_BOUNDS_MODE": "deny",
            },
            cwd=str(self.tmp),
        )
        self.assertEqual(result.returncode, 2,
                         f"hook must deny (exit 2) in deny mode; stderr: {result.stderr}")
        # Deviation log should still have an entry (validator logs before exit).
        self.assertTrue(self.log_path.exists())
        entries = [json.loads(l) for l in self.log_path.read_text().splitlines() if l.strip()]
        self.assertTrue(any(e.get("gate_layer") == "prose-gates-v1" for e in entries),
                        "deny-mode deviation entry should still carry gate_layer:prose-gates-v1")

    def test_case_4_test_mode_bypass(self):
        """CLAUDE_HOOK_TEST_MODE=1 bypasses the gate (exit 0, no log entry)."""
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": self._violating_command()},
        }
        result = subprocess.run(
            ["bash", str(HOOK)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            env={
                **os.environ,
                "CLAUDE_PROJECT_DIR": str(self.tmp),
                "CLAUDE_HOOK_TEST_MODE": "1",
                "PROSE_GATE_LEAD_SYNTHESIZED_NUMERICAL_BOUNDS_MODE": "deny",
            },
            cwd=str(self.tmp),
        )
        self.assertEqual(result.returncode, 0, "test-mode bypass should exit 0")
        # No log entry should be written.
        if self.log_path.exists():
            entries = [json.loads(l) for l in self.log_path.read_text().splitlines() if l.strip()]
            self.assertEqual(len([e for e in entries if e.get("gate_layer") == "prose-gates-v1"]), 0,
                             "test-mode bypass should not write deviation entries")

    def test_case_5_prose_gates_tolerant_escape(self):
        """PROSE_GATES_TOLERANT=1 bypasses (mirrors RMG_V2_TOLERANT)."""
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": self._violating_command()},
        }
        result = subprocess.run(
            ["bash", str(HOOK)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            env={
                **os.environ,
                "CLAUDE_PROJECT_DIR": str(self.tmp),
                "PROSE_GATES_TOLERANT": "1",
                "PROSE_GATE_LEAD_SYNTHESIZED_NUMERICAL_BOUNDS_MODE": "deny",
            },
            cwd=str(self.tmp),
        )
        self.assertEqual(result.returncode, 0, "tolerant escape should exit 0")
        self.assertIn("PROSE_GATES_TOLERANT=1", result.stderr,
                      "tolerant bypass should warn on stderr")


if __name__ == "__main__":
    unittest.main()
