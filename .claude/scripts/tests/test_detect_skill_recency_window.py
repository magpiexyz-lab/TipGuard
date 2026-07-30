#!/usr/bin/env python3
"""test_detect_skill_recency_window.py — regression for #1417a.

verify-pr-gate.sh dispatches skill-specific checks via detect_skill_for_branch.
Previously: branch name + timestamp tie-break only → stale completed
observe-context.json on a re-used branch was dispatched as the current PR's
skill identity, leading to false-positive verdict-consistency blocks.

Fix: when include_completed=True, Pass 2 of discover_current_run_id rejects
completed contexts whose timestamp predates the HEAD commit timestamp. A
stale context written before HEAD cannot win.

Pass 3 (orphan-child fallback) requires parent != None, so a stale
completed top-level context cannot sneak through that path either.
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
sys.path.insert(0, str(ROOT / ".claude/scripts/lib"))
LIB = ROOT / ".claude/hooks/lib.sh"

from runs_reader import discover_current_run_id  # noqa: E402


def now_iso(offset_hours: float = 0) -> str:
    t = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=offset_hours)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def call_detect_via_bash(project_dir: Path, branch: str, include_completed: str) -> str:
    """Invoke _detect_skill_for_branch_impl via bash; return stdout-stripped skill."""
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    cmd = [
        "bash", "-c",
        f'cd "{project_dir}" && '
        f'source "{LIB}" && _detect_skill_for_branch_impl "{branch}" "{include_completed}"',
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=10)
    return proc.stdout.strip()


class DetectSkillRecencyWindowTests(unittest.TestCase):
    """Validates the #1417a fix: stale completed contexts predating HEAD are rejected."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_recency_"))
        self.runs = self.tmp / ".runs"
        self.runs.mkdir()
        subprocess.run(["git", "-C", str(self.tmp), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(self.tmp), "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", str(self.tmp), "config", "user.name", "t"], check=True)
        subprocess.run(
            ["git", "-C", str(self.tmp), "config", "commit.gpgsign", "false"], check=True
        )
        subprocess.run(["git", "-C", str(self.tmp), "checkout", "-q", "-b", "feat/x"], check=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_ctx(self, name: str, *, branch="feat/x", completed=True, parent=None,
                    ts: str = "", run_id_suffix: str = "x") -> None:
        d = {
            "skill": name,
            "run_id": f"{name}-{run_id_suffix}",
            "branch": branch,
            "timestamp": ts or now_iso(),
            "completed": completed,
            "parent": parent,
            "ancestors": [],
        }
        (self.runs / f"{name}-context.json").write_text(json.dumps(d))

    def _commit_head_at(self, when_iso: str) -> None:
        env = os.environ.copy()
        env["GIT_AUTHOR_DATE"] = when_iso
        env["GIT_COMMITTER_DATE"] = when_iso
        subprocess.run(
            ["git", "-C", str(self.tmp), "commit", "-q", "--allow-empty", "-m", "head"],
            check=True, env=env,
        )

    def test_stale_completed_predating_head_is_rejected(self):
        """#1417a real-bug scenario: completed observe-context from 19 min
        before HEAD must not be dispatched as the PR's skill identity.
        """
        # Old observe context (HEAD - 19min)
        old_ts = now_iso(-0.32)  # ~19 minutes ago
        self._write_ctx("observe", completed=True, parent=None, ts=old_ts,
                         run_id_suffix="stale")
        # HEAD commit at "now"
        head_when = now_iso(0)
        self._commit_head_at(head_when)
        # PR-gate path (include_completed=true)
        result = call_detect_via_bash(self.tmp, "feat/x", "true")
        self.assertEqual(result, "",
                          msg="stale completed observe-context predating HEAD must be rejected")

    def test_completed_post_head_is_accepted(self):
        """Completed context written AFTER HEAD commit is accepted by Pass 2."""
        head_when = now_iso(-1)  # HEAD 1h ago
        self._commit_head_at(head_when)
        # Context from now (after HEAD)
        self._write_ctx("change", completed=True, parent=None, ts=now_iso(),
                         run_id_suffix="recent")
        result = call_detect_via_bash(self.tmp, "feat/x", "true")
        self.assertEqual(result, "change")

    def test_active_context_preferred_over_stale_completed(self):
        """When active context exists, Pass 1 wins regardless of completed
        contexts (and regardless of HEAD timing).
        """
        old_ts = now_iso(-0.5)
        self._write_ctx("observe", completed=True, parent=None, ts=old_ts,
                         run_id_suffix="stale")
        self._write_ctx("change", completed=False, parent=None, ts=now_iso(),
                         run_id_suffix="active")
        head_when = now_iso(0)
        self._commit_head_at(head_when)
        result = call_detect_via_bash(self.tmp, "feat/x", "true")
        self.assertEqual(result, "change")

    def test_active_only_caller_does_not_trigger_pass2(self):
        """include_completed=false (skill-write-gate, observe-commit-gate
        callers): never falls back to completed contexts even when Pass 1
        is empty. Preserves child-preference during in-flight embed."""
        # Only a completed top-level context exists
        head_when = now_iso(-1)
        self._commit_head_at(head_when)
        self._write_ctx("change", completed=True, parent=None, ts=now_iso(),
                         run_id_suffix="completed")
        result = call_detect_via_bash(self.tmp, "feat/x", "false")
        self.assertEqual(result, "",
                          msg="active variant must not pick up completed contexts even when post-HEAD")


class DiscoverCurrentRunIDHC5Tests(unittest.TestCase):
    """Direct Python tests for HC5 (no active skill → None)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_hc5_"))
        (self.tmp / ".runs").mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_contexts_returns_none(self):
        """Manual gh pr create with no .runs/<skill>-context.json → None (HC5)."""
        identity = discover_current_run_id(branch="feat/x", project_dir=self.tmp,
                                            include_completed=True)
        self.assertIsNone(identity)


if __name__ == "__main__":
    unittest.main()
