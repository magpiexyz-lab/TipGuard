#!/usr/bin/env python3
"""test_skill_commit_gate_mode_qualified.py — regression for the #1990-flagged
hook fail-open: skill-commit-gate.sh resolved the framework manifest with the
MODE-QUALIFIED ACTIVE_SKILL (iterate-cross), hit the nonexistent
.runs/iterate-cross-lifecycle.json, and exited 0 — disabling postcondition
reruns, BLOCK-verdict checks, and completion checks for every mode-qualified
run. The fix derives BASE_SKILL via resolve_skill_dir for the manifest path
only (registry keys and ctx paths stay qualified).

Run: python3 -m pytest .claude/scripts/tests/test_skill_commit_gate_mode_qualified.py -v
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[3]
HOOK = ROOT / ".claude/hooks/skill-commit-gate.sh"


def _live_ts() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class CommitGateFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_scg_mq_"))
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.tmp, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=self.tmp, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=self.tmp, check=True)
        subprocess.run(
            ["git", "commit", "-q", "--allow-empty", "-m", "init"],
            cwd=self.tmp, check=True,
        )
        self.runs = self.tmp / ".runs"
        self.runs.mkdir()
        patterns = self.tmp / ".claude" / "patterns"
        patterns.mkdir(parents=True)
        # Registry VERIFYs are "true" → filtered out by rerun_postconditions;
        # completion is the check under test.
        (patterns / "state-registry.json").write_text(json.dumps({
            "iterate-cross": {"x0": "true"},
            "change": {"0": "true"},
        }))
        skills = self.tmp / ".claude" / "skills"
        (skills / "iterate").mkdir(parents=True)
        (skills / "iterate" / "skill.yaml").write_text(
            "modes:\n  cross:\n    states: ['x0']\n"
        )
        (skills / "change").mkdir(parents=True)
        (skills / "change" / "skill.yaml").write_text("states: ['0']\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _context(self, skill: str, completed_states: list, run_id="run-1"):
        (self.runs / f"{skill}-context.json").write_text(json.dumps({
            "skill": skill, "run_id": run_id, "branch": "main",
            "timestamp": _live_ts(), "completed": False,
            "completed_states": completed_states,
        }))

    def _manifest(self, base: str, body: dict):
        (self.runs / f"{base}-lifecycle.json").write_text(json.dumps(body))

    def run_hook(self, command="git commit -m x"):
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(self.tmp)
        return subprocess.run(
            ["bash", str(HOOK)], input=payload, cwd=self.tmp,
            capture_output=True, text=True, env=env, timeout=60,
        )


class TestModeQualifiedCommitGate(CommitGateFixture):
    def test_incomplete_mode_qualified_run_is_denied(self):
        self._context("iterate-cross", completed_states=[])
        self._manifest("iterate", {
            "skill": "iterate", "active_mode": "cross",
            "modes": {"cross": {"states": ["x0"]}},
        })
        r = self.run_hook()
        self.assertEqual(r.returncode, 2, f"stdout={r.stdout}\nstderr={r.stderr}")
        self.assertIn("Commit blocked (iterate-cross)", r.stderr)
        self.assertIn("x0", r.stderr)

    def test_complete_mode_qualified_run_is_allowed(self):
        self._context("iterate-cross", completed_states=["x0"])
        self._manifest("iterate", {
            "skill": "iterate", "active_mode": "cross",
            "modes": {"cross": {"states": ["x0"]}},
        })
        r = self.run_hook()
        self.assertEqual(r.returncode, 0, f"stdout={r.stdout}\nstderr={r.stderr}")

    def test_base_skill_behavior_unchanged(self):
        self._context("change", completed_states=[])
        self._manifest("change", {"skill": "change", "states": ["0"]})
        r = self.run_hook()
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("Commit blocked (change)", r.stderr)
        self._context("change", completed_states=["0"])
        r2 = self.run_hook()
        self.assertEqual(r2.returncode, 0, r2.stderr)

    def test_no_manifest_still_fails_open(self):
        self._context("iterate-cross", completed_states=[])
        r = self.run_hook()
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_non_commit_command_ignored(self):
        self._context("iterate-cross", completed_states=[])
        self._manifest("iterate", {
            "skill": "iterate", "active_mode": "cross",
            "modes": {"cross": {"states": ["x0"]}},
        })
        r = self.run_hook(command="git status")
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    sys.exit(unittest.main())
