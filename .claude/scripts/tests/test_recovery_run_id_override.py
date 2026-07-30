#!/usr/bin/env python3
"""test_recovery_run_id_override.py — exercise write-recovery-trace.sh --run-id (AOC v1.1 PR3).

Validates the cross-skill / post-completion recovery path (#1064 D3) without
breaking the pre-v1.1 active-run protection (HC11).

Cases:
  * Default path (no --run-id): preserves PR1 behavior — fails when no
    active context.
  * --run-id with valid completed context (different skill): success
  * --run-id with non-existent run_id: refused (forgery defense, #963)
  * --run-id same skill as currently-active: refused (clause d')
  * --run-id with empty target.skill AND empty active.skill: refused
    (double-empty fail-closed, decision 1 from /solve cluster plan)
  * --run-id with empty target.skill AND non-empty active.skill: succeeds
    (legacy context recovered from a different active skill — empty != non-empty)
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


class TestRecoveryRunIdOverride(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_rrio_"))
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.tmp)], check=True)
        subprocess.run(["git", "-C", str(self.tmp), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(self.tmp), "config", "user.name", "test"], check=True)
        subprocess.run(["git", "-C", str(self.tmp), "commit", "-q", "--allow-empty", "-m", "init"], check=True)
        shutil.copytree(ROOT / ".claude", self.tmp / ".claude", dirs_exist_ok=True)
        self.runs = self.tmp / ".runs"
        self.runs.mkdir(exist_ok=True)
        self.traces = self.runs / "agent-traces"
        self.traces.mkdir(exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_ctx(self, skill: str, run_id: str, completed: bool = False) -> dict:
        ts = now_iso()
        ctx = {
            "skill": skill,
            "branch": "main",
            "timestamp": ts,
            "run_id": run_id,
            "completed_states": [],
            "completed": completed,
        }
        (self.runs / f"{skill}-context.json").write_text(json.dumps(ctx))
        return ctx

    def _write_spawn(self, agent: str, run_id: str, skill: str = "verify"):
        entry = {
            "agent": agent,
            "skill": skill,
            "run_id": run_id,
            "spawn_index": 1,
            "head_sha": "0000",
            "timestamp": now_iso(),
            "hook": "skill-agent-gate",
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
            capture_output=True, text=True, env=env, cwd=str(self.tmp), timeout=15,
        )

    # ---- Default path (no --run-id) — pre-v1.1 contract preserved ----

    def test_default_path_requires_active_context(self):
        # No context.json at all
        proc = self._run("observer", "--reason", "test")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("no active skill context", proc.stderr)

    def test_default_path_succeeds_with_active_context(self):
        ctx = self._write_ctx("verify", "verify-active-001")
        self._write_spawn("observer", "verify-active-001")
        self._write_stub("observer", "verify-active-001")
        proc = self._run("observer", "--reason", "test")
        self.assertEqual(proc.returncode, 0, f"stderr={proc.stderr}")

    # ---- --run-id override happy path ----

    def test_override_succeeds_with_valid_completed_context(self):
        # Source: completed bootstrap run
        self._write_ctx("bootstrap", "bootstrap-completed-001", completed=True)
        self._write_spawn("observer", "bootstrap-completed-001", skill="bootstrap")
        self._write_stub("observer", "bootstrap-completed-001")
        # Active: a different skill (e.g., /observe)
        self._write_ctx("observe", "observe-active-002")
        proc = self._run(
            "observer",
            "--reason", "post-completion epilogue audit",
            "--run-id", "bootstrap-completed-001",
        )
        self.assertEqual(proc.returncode, 0, f"stderr={proc.stderr}")
        # Verify the trace got written with the bootstrap run_id (target), not observe (active)
        trace = json.loads((self.traces / "observer.json").read_text())
        self.assertEqual(trace["run_id"], "bootstrap-completed-001")
        self.assertEqual(trace["skill"], "bootstrap")
        self.assertEqual(trace["provenance"], "recovery")

    # ---- --run-id forgery defense ----

    def test_override_refuses_unknown_run_id(self):
        self._write_ctx("verify", "verify-active-003")
        proc = self._run(
            "observer",
            "--reason", "forgery attempt",
            "--run-id", "fabricated-run-id-xxx",
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("not found in any", proc.stderr)

    # ---- Clause (d'): same-skill blocked ----

    def test_override_refuses_same_skill(self):
        # Active: /verify with run_id=verify-active-004 (in standard verify-context.json)
        self._write_ctx("verify", "verify-active-004")
        # Target: a SECOND /verify run (artificial setup — write to a different
        # filename to avoid overwriting the active context). In practice each
        # skill has one context file at a time, but this test exercises clause-d'
        # specifically: the supplied run_id resolves to the same skill as active.
        (self.runs / "verify-old-context.json").write_text(json.dumps({
            "skill": "verify",
            "branch": "main",
            "timestamp": now_iso(),
            "run_id": "verify-completed-005",
            "completed": True,
        }))
        self._write_spawn("observer", "verify-completed-005", skill="verify")
        proc = self._run(
            "observer",
            "--reason", "same-skill recovery attempt",
            "--run-id", "verify-completed-005",
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("currently-active skill", proc.stderr)

    # ---- Clause (d') double-empty: fail-closed ----

    def test_override_refuses_double_empty_skill(self):
        # Target context with empty skill (legacy/orphaned)
        (self.runs / "legacy-context.json").write_text(json.dumps({
            "skill": "",
            "branch": "main",
            "timestamp": now_iso(),
            "run_id": "legacy-006",
            "completed": True,
        }))
        # NO active context (empty active skill)
        proc = self._run(
            "observer",
            "--reason", "legacy recovery",
            "--run-id", "legacy-006",
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("double-empty case", proc.stderr)

    # ---- Empty target skill, non-empty active — different by definition ----

    def test_override_succeeds_with_legacy_target_and_nonempty_active(self):
        """Legacy context with empty skill, recovered from a non-empty active skill,
        succeeds because empty != non-empty (clause d' distinguishes them)."""
        # Target: legacy context (empty skill)
        (self.runs / "legacy-context.json").write_text(json.dumps({
            "skill": "",
            "branch": "main",
            "timestamp": now_iso(),
            "run_id": "legacy-007",
            "completed": True,
        }))
        self._write_spawn("observer", "legacy-007", skill="")
        self._write_stub("observer", "legacy-007")
        # Active: different skill
        self._write_ctx("observe", "observe-active-008")
        proc = self._run(
            "observer",
            "--reason", "legacy recovery",
            "--run-id", "legacy-007",
        )
        self.assertEqual(proc.returncode, 0, f"stderr={proc.stderr}")
        trace = json.loads((self.traces / "observer.json").read_text())
        self.assertEqual(trace["run_id"], "legacy-007")
        # skill field reflects the target (empty), not the active (observe)
        self.assertEqual(trace["skill"], "")

    # ---- --run-id with no spawn-log entry: still refuses (precondition 3) ----

    def test_override_refuses_when_no_spawn_log_entry(self):
        self._write_ctx("bootstrap", "bootstrap-completed-009", completed=True)
        self._write_ctx("observe", "observe-active-010")
        # NO spawn-log entry written
        proc = self._run(
            "observer",
            "--reason", "test",
            "--run-id", "bootstrap-completed-009",
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("no skill-agent-gate spawn-log entry", proc.stderr)


def main():
    if not SCRIPT.is_file():
        print(f"ERROR: script not found at {SCRIPT}", file=sys.stderr)
        return 2
    result = unittest.main(exit=False, verbosity=2).result
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
