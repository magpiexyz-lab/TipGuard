#!/usr/bin/env python3
"""test_clean_stale_worktrees.py — guards for .claude/scripts/lib/clean-stale-worktrees.sh.

Regression coverage for the incident where `clean-stale-worktrees.sh <prefix>`,
invoked at a command's Step 0, force-removed the ACTIVE session's own worktree
(>24h old, with its `.runs/<prefix>-context.json` liveness marker not yet
written), losing uncommitted work and the shell cwd.

The script must:
  1. Never remove the worktree it is running inside (self-exclusion) — even when
     it is stale and has no liveness marker.
  2. Never force-remove a stale worktree that has uncommitted changes.
  3. Still remove a clean, non-active, >24h-stale worktree (the original job).
  4. Keep a fresh (<24h) worktree.

Run: python3 .claude/scripts/tests/test_clean_stale_worktrees.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / ".claude/scripts/lib/clean-stale-worktrees.sh"
STALE_SECONDS = 90_000  # 25h, comfortably over the script's 86400s (24h) threshold
PREFIX = "solve"


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True
    )


def _backdate(path: Path, seconds: int = STALE_SECONDS) -> None:
    old = time.time() - seconds
    os.utime(path, (old, old))


class TestCleanStaleWorktrees(unittest.TestCase):
    """Fixture: a real main repo with linked worktrees under <tmp>/.claude/worktrees/.

    Worktrees live as siblings of the main repo (not nested inside it) so each
    worktree's own `git status` is unaffected by the others, while their paths
    still contain the `/.claude/worktrees/<prefix>-` substring the script greps.
    """

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="clean-stale-test-")).resolve()
        self.main = self.tmp / "main"
        self.main.mkdir()
        _git("init", "-q", cwd=self.main)
        _git("config", "user.email", "t@t.test", cwd=self.main)
        _git("config", "user.name", "t", cwd=self.main)
        (self.main / "README.md").write_text("seed\n")
        _git("add", "-A", cwd=self.main)
        _git("commit", "-qm", "seed", cwd=self.main)
        self.wtbase = self.tmp / ".claude" / "worktrees"
        self.wtbase.mkdir(parents=True)

    def tearDown(self) -> None:
        for d in list(self.wtbase.glob("*")):
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(d)],
                cwd=str(self.main), capture_output=True, text=True,
            )
        subprocess.run(
            ["git", "worktree", "prune"], cwd=str(self.main),
            capture_output=True, text=True,
        )
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _add_worktree(self, name: str, *, dirty: bool = False, stale: bool = True) -> Path:
        path = self.wtbase / f"{PREFIX}-{name}"
        _git("worktree", "add", "--detach", "-q", str(path), "HEAD", cwd=self.main)
        if dirty:
            (path / "README.md").write_text("uncommitted edit\n")
        if stale:
            _backdate(path)  # set mtime LAST so file ops above don't reset it
        return path

    def _run(self, cwd: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(SCRIPT), PREFIX],
            cwd=str(cwd), capture_output=True, text=True,
        )

    def test_self_exclusion_keeps_active_worktree(self) -> None:
        """The decisive guard: a stale worktree run from inside itself survives."""
        wt = self._add_worktree("active", dirty=False, stale=True)
        res = self._run(cwd=wt)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(wt.exists(), "active worktree was deleted by clean-stale (self-exclusion failed)")

    def test_dirty_stale_worktree_skipped(self) -> None:
        """Defense-in-depth: a stale worktree with uncommitted work is not removed."""
        wt = self._add_worktree("dirty", dirty=True, stale=True)
        res = self._run(cwd=self.main)  # run from main, not inside wt
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(wt.exists(), "dirty stale worktree was removed (work would be lost)")
        self.assertIn("uncommitted changes", res.stderr)

    def test_clean_stale_worktree_removed(self) -> None:
        """The original job still works: a clean, non-active, stale worktree is removed."""
        wt = self._add_worktree("staleclean", dirty=False, stale=True)
        res = self._run(cwd=self.main)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertFalse(wt.exists(), "clean stale worktree was NOT removed")

    def test_fresh_worktree_kept(self) -> None:
        """A fresh (<24h) worktree is below the staleness threshold and survives."""
        wt = self._add_worktree("fresh", dirty=False, stale=False)
        res = self._run(cwd=self.main)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(wt.exists(), "fresh worktree was removed")


if __name__ == "__main__":
    unittest.main()
