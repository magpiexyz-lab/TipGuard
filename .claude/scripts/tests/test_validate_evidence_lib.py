#!/usr/bin/env python3
"""test_validate_evidence_lib — unit tests for the EARC evidence-validation library.

Library: .claude/scripts/lib/validate_evidence.py
Tests three primitives extracted from validate-recovery.sh in slice 0:
  - validate_build_evidence: exit_code, freshness, commit_sha
  - validate_diff_evidence:  per-fix file ↔ git diff correlation
  - validate_manifest_evidence: presence of expected entries

Plus a sanity test that the refactored validate-recovery.sh still works on
the same fixtures the legacy implementation handled.

Run: python3 -m pytest .claude/scripts/tests/test_validate_evidence_lib.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / ".claude/scripts"))

from lib.validate_evidence import (  # noqa: E402
    validate_build_evidence,
    validate_diff_evidence,
    validate_manifest_evidence,
)


class TestValidateBuildEvidence(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_ve_build_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_exit_code_zero_passes(self):
        p = self.tmp / "br.json"
        p.write_text(json.dumps({"exit_code": 0}))
        ok, errors = validate_build_evidence(str(p))
        self.assertTrue(ok, errors)
        self.assertEqual(errors, [])

    def test_exit_code_nonzero_fails(self):
        p = self.tmp / "br.json"
        p.write_text(json.dumps({"exit_code": 1}))
        ok, errors = validate_build_evidence(str(p))
        self.assertFalse(ok)
        self.assertTrue(any("exit_code=1" in e for e in errors))

    def test_missing_file_fails(self):
        p = self.tmp / "doesnotexist.json"
        ok, errors = validate_build_evidence(str(p))
        self.assertFalse(ok)
        self.assertTrue(any("missing" in e for e in errors))

    def test_malformed_json_fails(self):
        p = self.tmp / "bad.json"
        p.write_text("not json")
        ok, errors = validate_build_evidence(str(p))
        self.assertFalse(ok)
        self.assertTrue(any("malformed" in e for e in errors))

    def test_freshness_check_rejects_stale(self):
        # Freshness check (round-2 critic Concern 4): if trace_timestamp is
        # provided and the file is older than max_age_seconds, validation
        # fails.
        p = self.tmp / "br.json"
        p.write_text(json.dumps({"exit_code": 0}))
        # Set mtime to 1 hour ago.
        old = time.time() - 3600
        os.utime(p, (old, old))
        # Trace timestamp = now.
        now_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        ok, errors = validate_build_evidence(
            str(p), trace_timestamp=now_ts, max_age_seconds=300
        )
        self.assertFalse(ok)
        self.assertTrue(any("stale" in e for e in errors))

    def test_freshness_check_passes_fresh(self):
        p = self.tmp / "br.json"
        p.write_text(json.dumps({"exit_code": 0}))
        # mtime is now (write just happened).
        now_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        ok, errors = validate_build_evidence(
            str(p), trace_timestamp=now_ts, max_age_seconds=300
        )
        self.assertTrue(ok, errors)

    def test_commit_sha_mismatch_fails(self):
        # When build-result.json records a commit_sha and it doesn't match
        # HEAD, validation fails.
        td = Path(tempfile.mkdtemp(prefix="test_ve_csha_"))
        try:
            subprocess.run(["git", "init", "-q", str(td)], check=True)
            subprocess.run(
                ["git", "-C", str(td), "config", "user.email", "t@t.com"], check=True
            )
            subprocess.run(["git", "-C", str(td), "config", "user.name", "t"], check=True)
            (td / "f.txt").write_text("a")
            subprocess.run(["git", "-C", str(td), "add", "f.txt"], check=True)
            subprocess.run(["git", "-C", str(td), "commit", "-q", "-m", "i"], check=True)
            head = subprocess.check_output(
                ["git", "-C", str(td), "rev-parse", "HEAD"], text=True
            ).strip()
            br = td / "br.json"
            # Record a different sha
            br.write_text(json.dumps({"exit_code": 0, "commit_sha": "deadbeef" * 5}))
            ok, errors = validate_build_evidence(str(br), project_dir=str(td))
            self.assertFalse(ok)
            self.assertTrue(any("commit_sha" in e for e in errors))
            # Record matching sha → pass
            br.write_text(json.dumps({"exit_code": 0, "commit_sha": head}))
            ok, errors = validate_build_evidence(str(br), project_dir=str(td))
            self.assertTrue(ok, errors)
        finally:
            shutil.rmtree(td, ignore_errors=True)


class TestValidateDiffEvidence(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_ve_diff_"))
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        subprocess.run(
            ["git", "-C", str(self.tmp), "config", "user.email", "t@t.com"], check=True
        )
        subprocess.run(
            ["git", "-C", str(self.tmp), "config", "user.name", "t"], check=True
        )
        (self.tmp / "foo.txt").write_text("x")
        subprocess.run(["git", "-C", str(self.tmp), "add", "foo.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(self.tmp), "commit", "-q", "-m", "initial"], check=True
        )
        self.spawn_sha = subprocess.check_output(
            ["git", "-C", str(self.tmp), "rev-parse", "HEAD"], text=True
        ).strip()
        (self.tmp / "bar.txt").write_text("y")
        subprocess.run(["git", "-C", str(self.tmp), "add", "bar.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(self.tmp), "commit", "-q", "-m", "bar"], check=True
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fix_file_in_diff_passes(self):
        ok, errors = validate_diff_evidence(
            [{"file": "bar.txt", "symptom": "x", "fix": "y"}],
            self.spawn_sha,
            project_dir=str(self.tmp),
        )
        self.assertTrue(ok, errors)

    def test_fix_file_not_in_diff_fails(self):
        ok, errors = validate_diff_evidence(
            [{"file": "phantom.ts", "symptom": "x", "fix": "y"}],
            self.spawn_sha,
            project_dir=str(self.tmp),
        )
        self.assertFalse(ok)
        self.assertTrue(any("phantom.ts" in e for e in errors))

    def test_empty_fixes_passes(self):
        ok, errors = validate_diff_evidence(
            [], self.spawn_sha, project_dir=str(self.tmp)
        )
        self.assertTrue(ok)
        self.assertEqual(errors, [])

    def test_porcelain_picks_up_untracked(self):
        # An untracked new file should appear in the diff set via porcelain.
        (self.tmp / "untracked.txt").write_text("z")
        ok, errors = validate_diff_evidence(
            [{"file": "untracked.txt", "symptom": "x", "fix": "y"}],
            self.spawn_sha,
            project_dir=str(self.tmp),
        )
        self.assertTrue(ok, errors)


class TestValidateManifestEvidence(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_ve_manifest_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_all_entries_present_passes(self):
        p = self.tmp / "m.json"
        p.write_text(json.dumps({"entries": ["a", "b", "c"]}))
        ok, errors = validate_manifest_evidence(str(p), ["a", "b"])
        self.assertTrue(ok, errors)

    def test_missing_entry_fails(self):
        p = self.tmp / "m.json"
        p.write_text(json.dumps({"entries": ["a"]}))
        ok, errors = validate_manifest_evidence(str(p), ["a", "b"])
        self.assertFalse(ok)
        self.assertTrue(any("'b'" in e for e in errors))

    def test_missing_file_fails(self):
        ok, errors = validate_manifest_evidence(str(self.tmp / "no.json"), ["a"])
        self.assertFalse(ok)
        self.assertTrue(any("missing" in e for e in errors))


class TestValidateRecoveryStillWorks(unittest.TestCase):
    """Pin the refactored validate-recovery.sh: same behavior on existing
    fixtures. If this test fails, the slice 0 refactor regressed legacy
    callers (verify-report-gate, lifecycle-finalize, adversarial-merge-gate).
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_validate_recovery_"))
        # Bootstrap a tiny repo with one prior commit and one new file.
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        subprocess.run(
            ["git", "-C", str(self.tmp), "config", "user.email", "t@t.com"], check=True
        )
        subprocess.run(
            ["git", "-C", str(self.tmp), "config", "user.name", "t"], check=True
        )
        (self.tmp / "foo.txt").write_text("x")
        subprocess.run(["git", "-C", str(self.tmp), "add", "foo.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(self.tmp), "commit", "-q", "-m", "initial"], check=True
        )
        self.spawn_sha = subprocess.check_output(
            ["git", "-C", str(self.tmp), "rev-parse", "HEAD"], text=True
        ).strip()
        (self.tmp / "bar.txt").write_text("y")
        subprocess.run(["git", "-C", str(self.tmp), "add", "bar.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(self.tmp), "commit", "-q", "-m", "bar"], check=True
        )
        # Copy the script + library + minimal lib-core.sh
        for d in (".runs/agent-traces", ".claude/patterns", ".claude/scripts/lib", ".claude/hooks"):
            (self.tmp / d).mkdir(parents=True, exist_ok=True)
        shutil.copy(
            ROOT / ".claude/scripts/validate-recovery.sh",
            self.tmp / ".claude/scripts/validate-recovery.sh",
        )
        shutil.copy(
            ROOT / ".claude/scripts/lib/validate_evidence.py",
            self.tmp / ".claude/scripts/lib/validate_evidence.py",
        )
        (self.tmp / ".claude/scripts/lib/__init__.py").write_text("")

        # Trace and supporting evidence.
        traces_dir = self.tmp / ".runs/agent-traces"
        json.dump(
            {
                "agent": "test-agent",
                "provenance": "recovery",
                "spawn_sha": self.spawn_sha,
                "fixes": [{"file": "bar.txt", "symptom": "x", "fix": "y"}],
            },
            (traces_dir / "test-agent.json").open("w"),
        )
        json.dump({"exit_code": 0}, (self.tmp / ".runs/build-result.json").open("w"))
        json.dump(
            {"non_fixer_agents": []},
            (self.tmp / ".claude/patterns/agent-registry.json").open("w"),
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self):
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.tmp)}
        return subprocess.run(
            ["bash", ".claude/scripts/validate-recovery.sh", "test-agent"],
            cwd=str(self.tmp),
            env=env,
            capture_output=True,
            text=True,
        )

    def test_passing_trace_stamps_recovery_validated(self):
        r = self._run()
        self.assertEqual(r.returncode, 0, msg=f"stderr={r.stderr}")
        trace = json.load(open(self.tmp / ".runs/agent-traces/test-agent.json"))
        self.assertTrue(trace.get("recovery_validated") is True, trace)

    def test_failing_build_rejects(self):
        json.dump({"exit_code": 1}, (self.tmp / ".runs/build-result.json").open("w"))
        r = self._run()
        self.assertEqual(r.returncode, 1)
        self.assertIn("exit_code=1", r.stderr)

    def test_self_provenance_skips(self):
        traces_dir = self.tmp / ".runs/agent-traces"
        json.dump(
            {"agent": "test-agent", "provenance": "self"},
            (traces_dir / "test-agent.json").open("w"),
        )
        r = self._run()
        self.assertEqual(r.returncode, 0)
        trace = json.load(open(traces_dir / "test-agent.json"))
        self.assertNotIn("recovery_validated", trace)


if __name__ == "__main__":
    unittest.main()
