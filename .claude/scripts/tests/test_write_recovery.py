#!/usr/bin/env python3
"""test_write_recovery.py — exercise the write-recovery-trace.sh preconditions.

Covers legitimate recovery (pass) and six forgery scenarios (fail):
  1. missing --reason
  2. no spawn-log entry
  3. completed trace (not stub)
  4. agent in recovery_forbidden (security-fixer / quality-fixer)
  5. empty run_id context
  6. unknown agent with no spawn record at all

Run: python3 .claude/scripts/tests/test_write_recovery.py
"""
from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / ".claude/scripts/write-recovery-trace.sh"


def now_iso(offset_hours: float = 0) -> str:
    t = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=offset_hours)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


class TestWriteRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_wrt_"))
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        subprocess.run(["git", "-C", str(self.tmp), "commit", "-q", "--allow-empty",
                        "-m", "init"], check=True)
        # Clone .claude/ into temp so the script can find its own helpers
        shutil.copytree(ROOT / ".claude", self.tmp / ".claude", dirs_exist_ok=True)
        self.runs = self.tmp / ".runs"
        self.runs.mkdir()
        self.traces = self.runs / "agent-traces"
        self.traces.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_ctx(self, skill="verify"):
        ts = now_iso()
        ctx = {
            "skill": skill,
            "branch": "main",
            "timestamp": ts,
            "run_id": f"{skill}-{ts}",
            "completed_states": [],
            "parent": None,
            "ancestors": [],
            "attributed_to": skill,
            "completed": False,
        }
        (self.runs / f"{skill}-context.json").write_text(json.dumps(ctx))
        return ctx

    def _write_spawn(self, agent: str, run_id: str, hook: str = "skill-agent-gate"):
        entry = {
            "agent": agent,
            "skill": "verify",
            "run_id": run_id,
            "spawn_index": 1,
            "head_sha": "0000000000000000000000000000000000000000",
            "timestamp": now_iso(),
            "hook": hook,
        }
        with open(self.runs / "agent-spawn-log.jsonl", "a") as f:
            f.write(json.dumps(entry) + "\n")

    def _write_stub(self, agent: str, run_id: str):
        (self.traces / f"{agent}.json").write_text(json.dumps({
            "agent": agent,
            "status": "started",
            "timestamp": now_iso(),
            "run_id": run_id,
        }))

    def _run(self, *args):
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(self.tmp)
        return subprocess.run(
            ["bash", str(SCRIPT)] + list(args),
            capture_output=True, text=True, env=env, cwd=str(self.tmp),
            timeout=10,
        )

    # ---- Happy path ----

    def test_happy_path_writes_recovery(self):
        ctx = self._write_ctx()
        self._write_spawn("design-critic", ctx["run_id"])
        self._write_stub("design-critic", ctx["run_id"])
        proc = self._run("design-critic", "--reason", "image limit exceeded")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        trace = json.loads((self.traces / "design-critic.json").read_text())
        self.assertEqual(trace["provenance"], "recovery")
        # EARC slice 1 (closes #1189): verdict renamed from 'recovery'
        # (anomalous, outside the closed verdict enum) to 'unresolved'
        # (within {pass, fail, blocked, unresolved}). Provenance still
        # carries the recovery semantics.
        self.assertEqual(trace["verdict"], "unresolved")
        self.assertEqual(trace["partial"], True)
        self.assertEqual(trace["recovery"], True)
        self.assertEqual(trace["recovery_validated"], False)
        self.assertEqual(trace["recovery_reason"], "image limit exceeded")
        self.assertEqual(trace["degraded_reason"], "image limit exceeded")
        self.assertEqual(trace["spawn_index"], 1)

    def test_happy_path_no_stub_present(self):
        # If stub is absent, recovery should still work (agent crashed before init-trace)
        ctx = self._write_ctx()
        self._write_spawn("design-critic", ctx["run_id"])
        # NO stub written
        proc = self._run("design-critic", "--reason", "crash before init-trace")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    # ---- Forgery / misuse rejections ----

    def test_missing_reason_rejected(self):
        ctx = self._write_ctx()
        self._write_spawn("design-critic", ctx["run_id"])
        self._write_stub("design-critic", ctx["run_id"])
        proc = self._run("design-critic")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("--reason is mandatory", proc.stderr)

    def test_no_spawn_log_rejected(self):
        self._write_ctx()
        # NO spawn entry written
        proc = self._run("design-critic", "--reason", "some reason")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("no skill-agent-gate spawn-log entry", proc.stderr)

    def test_completed_trace_not_overwritten(self):
        ctx = self._write_ctx()
        self._write_spawn("design-critic", ctx["run_id"])
        # Write a completed trace (not a stub) — recovery should refuse to overwrite
        (self.traces / "design-critic.json").write_text(json.dumps({
            "agent": "design-critic",
            "status": "completed",
            "verdict": "pass",
            "provenance": "self",
            "partial": False,
            "timestamp": now_iso(),
            "run_id": ctx["run_id"],
            "checks_performed": ["x"],
        }))
        proc = self._run("design-critic", "--reason", "forgery attempt")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("not a stub", proc.stderr)

    def test_recovery_forbidden_agent_rejected_security_fixer(self):
        ctx = self._write_ctx()
        self._write_spawn("security-fixer", ctx["run_id"])
        self._write_stub("security-fixer", ctx["run_id"])
        proc = self._run("security-fixer", "--reason", "high-risk attempt")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("recovery_forbidden", proc.stderr)

    def test_recovery_forbidden_agent_rejected_quality_fixer(self):
        ctx = self._write_ctx()
        self._write_spawn("quality-fixer", ctx["run_id"])
        self._write_stub("quality-fixer", ctx["run_id"])
        proc = self._run("quality-fixer", "--reason", "high-risk attempt")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("recovery_forbidden", proc.stderr)

    def test_no_active_context_rejected(self):
        # No *-context.json → no active identity
        proc = self._run("design-critic", "--reason", "x")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("no active skill context", proc.stderr)

    def test_wrong_run_id_spawn_rejected(self):
        # spawn-log entry exists but with a DIFFERENT run_id
        ctx = self._write_ctx()
        self._write_spawn("design-critic", "verify-OLD-run-id")
        proc = self._run("design-critic", "--reason", "try forgery with stale spawn")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("no skill-agent-gate spawn-log entry", proc.stderr)

    def test_recovery_script_hook_only_not_accepted(self):
        # An attacker writes a 'recovery-script' hook entry instead of
        # skill-agent-gate — we accept only skill-agent-gate entries.
        ctx = self._write_ctx()
        self._write_spawn("design-critic", ctx["run_id"], hook="recovery-script")
        proc = self._run("design-critic", "--reason", "x")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("no skill-agent-gate spawn-log entry", proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
