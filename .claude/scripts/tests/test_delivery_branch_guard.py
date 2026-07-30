#!/usr/bin/env python3
"""test_delivery_branch_guard.py — unit tests for lib/delivery-branch-guard.sh.

The guard is lifecycle-finalize.sh's pre-commit safety unit (issue #1990):
it must make committing on the default branch impossible while staying a
no-op for code-writing skills already on their init-created branch.

Run: python3 .claude/scripts/tests/test_delivery_branch_guard.py
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GUARD = ROOT / ".claude/scripts/lib/delivery-branch-guard.sh"
LIB = ROOT / ".claude/scripts/lifecycle-lib.sh"


def _git(cwd, *args, check=True):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=check, capture_output=True, text=True
    )


class GuardFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_dbg_"))
        self.origin = self.tmp / "origin.git"
        self.work = self.tmp / "work"
        subprocess.run(
            ["git", "init", "--bare", str(self.origin)],
            check=True, capture_output=True,
        )
        self.work.mkdir()
        _git(self.work, "init", "-b", "main")
        _git(self.work, "config", "user.email", "test@example.com")
        _git(self.work, "config", "user.name", "test")
        (self.work / "tracked.txt").write_text("v1\n")
        _git(self.work, "add", "-A")
        _git(self.work, "commit", "-m", "initial")
        _git(self.work, "remote", "add", "origin", str(self.origin))
        _git(self.work, "push", "-u", "origin", "main")
        _git(self.work, "remote", "set-head", "origin", "main")
        (self.work / ".runs").mkdir()
        scripts = self.work / ".claude" / "scripts"
        scripts.mkdir(parents=True)
        shutil.copy(LIB, scripts / "lifecycle-lib.sh")
        self.ucb_marker = self.work / ".runs" / "ucb-called.txt"
        ucb = scripts / "update-context-branch.sh"
        ucb.write_text(
            "#!/usr/bin/env bash\n"
            f'echo "$1" >> "{self.ucb_marker}"\n'
        )
        os.chmod(ucb, 0o755)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_guard(self, *args, env_extra=None):
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(self.work)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            ["bash", str(GUARD), *args],
            cwd=self.work, capture_output=True, text=True, env=env,
        )

    def current_branch(self):
        return _git(self.work, "branch", "--show-current").stdout.strip()


class TestDeliveryBranchGuard(GuardFixture):
    def test_on_default_with_changes_branches(self):
        (self.work / "tracked.txt").write_text("v2\n")
        r = self.run_guard("iterate-cross")
        self.assertEqual(r.returncode, 0, r.stderr)
        m = re.match(
            r"^GUARD=branched:(chore/iterate-cross-delivery-\d{8}-\d{6}Z)$",
            r.stdout.strip(),
        )
        self.assertIsNotNone(m, f"unexpected stdout: {r.stdout!r}")
        self.assertEqual(self.current_branch(), m.group(1))
        self.assertTrue(
            (self.work / ".runs" / "last-branch-checkout.tsv").is_file(),
            "checkout sentinel not written",
        )
        self.assertEqual(
            self.ucb_marker.read_text().strip(), "main",
            "update-context-branch.sh not invoked with the old branch",
        )

    def test_on_feature_branch_noop(self):
        _git(self.work, "checkout", "-b", "feature/x")
        (self.work / "tracked.txt").write_text("v2\n")
        r = self.run_guard("change")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "GUARD=noop")
        self.assertEqual(self.current_branch(), "feature/x")
        self.assertFalse(self.ucb_marker.exists())

    def test_clean_synced_default_skips(self):
        r = self.run_guard("iterate-cross")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "GUARD=skip-no-changes")
        self.assertEqual(self.current_branch(), "main")

    def test_ahead_of_origin_warns_and_branches(self):
        (self.work / "tracked.txt").write_text("v2\n")
        _git(self.work, "add", "-A")
        _git(self.work, "commit", "-m", "local-only")
        r = self.run_guard("iterate-cross")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("GUARD=branched:", r.stdout)
        self.assertIn("ahead of origin/main", r.stderr)

    def test_collision_suffixes_then_exhausts(self):
        ts = "20260729-000000Z"
        base = f"chore/iterate-cross-delivery-{ts}"
        _git(self.work, "branch", base)
        (self.work / "tracked.txt").write_text("v2\n")
        r = self.run_guard("iterate-cross", env_extra={"DELIVERY_GUARD_TS": ts})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), f"GUARD=branched:{base}-2")
        # Exhaust -2..-5 (the -2 branch now exists from the previous run).
        _git(self.work, "checkout", "main")
        for sfx in ("3", "4", "5"):
            _git(self.work, "branch", f"{base}-{sfx}")
        (self.work / "tracked.txt").write_text("v3\n")
        r2 = self.run_guard("iterate-cross", env_extra={"DELIVERY_GUARD_TS": ts})
        self.assertEqual(r2.returncode, 1, r2.stdout)
        self.assertIn("refusing to guess", r2.stderr)
        self.assertEqual(self.current_branch(), "main")

    def test_default_branch_derivation_master(self):
        _git(self.work, "checkout", "-b", "master")
        _git(self.work, "push", "-u", "origin", "master")
        _git(self.work, "remote", "set-head", "origin", "master")
        (self.work / "tracked.txt").write_text("v2\n")
        # No explicit default-branch arg → guard derives master via lib.
        r = self.run_guard("iterate-cross")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("GUARD=branched:", r.stdout)
        # main is now a non-default branch → noop there.
        _git(self.work, "checkout", "main")
        (self.work / "tracked.txt").write_text("v3\n")
        r2 = self.run_guard("iterate-cross")
        self.assertEqual(r2.stdout.strip(), "GUARD=noop")

    def test_default_branch_derivation_without_origin_head(self):
        _git(self.work, "remote", "set-head", "origin", "--delete")
        (self.work / "tracked.txt").write_text("v2\n")
        r = self.run_guard("iterate-cross")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("GUARD=branched:", r.stdout, "origin/main probe should derive main")

    def test_detached_head_branches(self):
        sha = _git(self.work, "rev-parse", "HEAD").stdout.strip()
        _git(self.work, "checkout", sha)
        (self.work / "tracked.txt").write_text("v2\n")
        r = self.run_guard("iterate-cross")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("GUARD=branched:", r.stdout)


if __name__ == "__main__":
    sys.exit(unittest.main())
