#!/usr/bin/env python3
"""test_dossier_git_fallback.py — regression for #1437.

dossier_builder.build_dossier previously returned phase_1a:0 / phase_4b:0
when fix-ledger.jsonl was empty, even if git log showed many commits on
the divergence files. The fix indexes git-log results into the entry array
with sentinel prior_run_id="git:<sha[:7]>" and dedups against ledger-derived
prior_commit_sha.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / ".claude/scripts/lib"))

from dossier_builder import build_dossier  # noqa: E402
from dossier_verify import assert_dossier_loaded  # noqa: E402


def init_git_repo(path: Path) -> None:
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "commit.gpgsign", "false"], check=True)


def make_commits(path: Path, file_name: str, count: int) -> None:
    for i in range(count):
        (path / file_name).write_text(f"v{i}\n")
        subprocess.run(["git", "-C", str(path), "add", file_name], check=True)
        subprocess.run(
            ["git", "-C", str(path), "commit", "-q", "-m", f"edit {file_name} #{i}"],
            check=True,
        )


class DossierGitFallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_dossier_git_"))
        init_git_repo(self.tmp)
        (self.tmp / ".runs").mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_ledger_emits_git_sentinels(self):
        """Empty fix-ledger + non-empty git log → dossier surfaces git-sentinel entries."""
        make_commits(self.tmp, "app.py", 4)
        d = build_dossier(["app.py"], "symptom signature", str(self.tmp))
        self.assertGreater(len(d["phase_1a"]), 0)
        # All entries should be git-sentinels (no ledger rows present)
        for e in d["phase_1a"]:
            self.assertTrue(e["prior_run_id"].startswith("git:"))
            self.assertEqual(e["files_touched"], ["app.py"])
            self.assertFalse(e["regression_test_present"])
        # Cap at max_per_file=5
        self.assertLessEqual(len(d["phase_1a"]), 5)

    def test_max_per_file_cap_enforced(self):
        """8 commits on a single file → cap at 5 entries (Caveat #3)."""
        make_commits(self.tmp, "x.py", 8)
        d = build_dossier(["x.py"], "test", str(self.tmp))
        self.assertEqual(len(d["phase_1a"]), 5)

    def test_phase_4b_mirrors_phase_1a_with_failure_mode(self):
        """phase_4b is a strict superset with failure_mode + prior_commit_sha."""
        make_commits(self.tmp, "y.py", 2)
        d = build_dossier(["y.py"], "test", str(self.tmp))
        self.assertEqual(len(d["phase_4b"]), len(d["phase_1a"]))
        for e in d["phase_4b"]:
            self.assertIn("failure_mode", e)
            self.assertIn("what_was_missed", e)
            self.assertIn("prior_commit_sha", e)
            # 7-char sentinel matches first 7 of prior_commit_sha
            sentinel = e["prior_run_id"]
            self.assertTrue(sentinel.startswith("git:"))
            self.assertEqual(e["prior_commit_sha"][:7], sentinel[4:])

    def test_empty_ledger_empty_git_log_returns_empty(self):
        """No commits + no ledger → dossier remains empty."""
        d = build_dossier(["does-not-exist.py"], "test", str(self.tmp))
        self.assertEqual(d["phase_1a"], [])
        self.assertEqual(d["phase_4b"], [])

    def test_dossier_verify_passes_with_only_git_sentinels(self):
        """dossier_verify schema relaxation: git-sentinel entries are advisory.
        A solve-trace with empty prior_failure_response is acceptable when
        the dossier has only git-sentinel entries.
        """
        import os
        make_commits(self.tmp, "z.py", 3)
        d = build_dossier(["z.py"], "test", str(self.tmp))
        self.assertGreater(len(d["phase_1a"]), 0)
        # Write dossier to the relative path assert_dossier_loaded reads
        dossier_path = self.tmp / ".runs/prior-failure-dossier.json"
        dossier_path.write_text(json.dumps(d))
        trace = {
            "prevention_analysis": {"problem_type": "defect"},
            "prior_failure_response": [],  # empty even though phase_1a has entries
        }
        # Chdir into tmp so DOSSIER_PATH=".runs/prior-failure-dossier.json" resolves
        old_cwd = os.getcwd()
        try:
            os.chdir(self.tmp)
            assert_dossier_loaded(trace, problem_type="defect",
                                   divergence_files_evidence=["z.py"])
        finally:
            os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
