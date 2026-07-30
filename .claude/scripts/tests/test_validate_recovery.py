#!/usr/bin/env python3
"""test_validate_recovery.py — exercise validate-recovery.sh evidence chain.

Covers the three-evidence verdict derivation (build + e2e + diff-fix):
  1. Happy path with fixes[] present in diff → stamps recovery_validated:true
  2. Happy path with no_fixes_claimed + non-fixer agent + sibling pass
  3. Fail: build exit_code != 0
  4. Fail: e2e passed false (when tests in scope)
  5. Fail: fixes[].file not in diff set
  6. Fail: no_fixes_claimed but agent is a fixer (not in non_fixer_agents)
  7. Fail: no_fixes_claimed without any sibling non-degraded trace
  8. Missing build-result.json → fails
  9. Skip path: trace is provenance=self (should short-circuit skip)

Run: python3 .claude/scripts/tests/test_validate_recovery.py
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
SCRIPT = ROOT / ".claude/scripts/validate-recovery.sh"


def now_iso(offset_hours: float = 0) -> str:
    t = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=offset_hours)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


class TestValidateRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_vr_"))
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        # Configure a user so commits don't fail
        subprocess.run(["git", "-C", str(self.tmp), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(self.tmp), "config", "user.name", "test"], check=True)
        # Initial commit that serves as the spawn_sha baseline
        (self.tmp / "README.md").write_text("initial\n")
        subprocess.run(["git", "-C", str(self.tmp), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.tmp), "commit", "-q", "-m", "initial"], check=True)
        # Clone .claude so validate-recovery.sh can find agent-registry.json
        shutil.copytree(ROOT / ".claude", self.tmp / ".claude", dirs_exist_ok=True)
        self.spawn_sha = subprocess.check_output(
            ["git", "-C", str(self.tmp), "rev-parse", "HEAD"], text=True).strip()
        self.runs = self.tmp / ".runs"
        self.runs.mkdir()
        self.traces = self.runs / "agent-traces"
        self.traces.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_build(self, exit_code: int):
        (self.runs / "build-result.json").write_text(json.dumps({"exit_code": exit_code}))

    def _write_e2e(self, passed: bool, skipped: bool = False):
        (self.runs / "e2e-result.json").write_text(json.dumps({
            "passed": passed,
            "skipped": skipped,
        }))

    def _write_trace(self, name: str, data: dict):
        (self.traces / f"{name}.json").write_text(json.dumps(data, indent=2))

    def _modify_tracked_file(self, filename: str, content: str):
        """Commit a file so it shows up in git diff spawn_sha..HEAD."""
        (self.tmp / filename).parent.mkdir(parents=True, exist_ok=True)
        (self.tmp / filename).write_text(content)
        subprocess.run(["git", "-C", str(self.tmp), "add", filename], check=True)
        subprocess.run(["git", "-C", str(self.tmp), "commit", "-q", "-m", f"add {filename}"],
                       check=True)

    def _create_untracked(self, filename: str, content: str):
        """Leave file untracked so it shows up in git status --porcelain."""
        (self.tmp / filename).parent.mkdir(parents=True, exist_ok=True)
        (self.tmp / filename).write_text(content)

    def _run(self, name):
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(self.tmp)
        return subprocess.run(
            ["bash", str(SCRIPT), name],
            capture_output=True, text=True, env=env, cwd=str(self.tmp), timeout=15,
        )

    # ---- Happy paths ----

    def test_happy_path_fixer_with_tracked_fix(self):
        self._write_build(0)
        self._write_e2e(True)
        self._modify_tracked_file("src/app/landing/page.tsx", "// fix")
        self._write_trace("quality-fixer", {
            "agent": "quality-fixer",
            "provenance": "recovery",
            "verdict": "recovery",
            "partial": True,
            "recovery": True,
            "recovery_validated": False,
            "spawn_sha": self.spawn_sha,
            "fixes": [{"file": "src/app/landing/page.tsx", "type": "typo"}],
        })
        proc = self._run("quality-fixer")
        self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout} stderr={proc.stderr}")
        t = json.loads((self.traces / "quality-fixer.json").read_text())
        self.assertTrue(t["recovery_validated"], "recovery_validated should be True after pass")

    def test_happy_path_untracked_file_via_porcelain(self):
        self._write_build(0)
        self._write_e2e(True)
        self._create_untracked("public/images/new-hero.png", "fake-image-bytes")
        self._write_trace("scaffold-images", {
            "agent": "scaffold-images",
            "provenance": "self-degraded",
            "verdict": "degraded",
            "partial": True,
            "degraded_reason": "rate-limit",
            "recovery_validated": False,
            "spawn_sha": self.spawn_sha,
            "fixes": [{"file": "public/images/new-hero.png", "type": "image-new"}],
        })
        proc = self._run("scaffold-images")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        t = json.loads((self.traces / "scaffold-images.json").read_text())
        self.assertTrue(t["recovery_validated"])

    def test_happy_path_non_fixer_no_fixes_claimed_with_sibling(self):
        self._write_build(0)
        self._write_e2e(True)
        # A sibling trace proves scope actually executed
        self._write_trace("ux-journeyer-sibling", {
            "agent": "ux-journeyer",
            "provenance": "self",
            "verdict": "pass",
            "checks_performed": ["journey"],
        })
        self._write_trace("design-critic", {
            "agent": "design-critic",
            "provenance": "recovery",
            "verdict": "recovery",
            "partial": True,
            "recovery": True,
            "recovery_validated": False,
            "no_fixes_claimed": True,
            "spawn_sha": self.spawn_sha,
        })
        proc = self._run("design-critic")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        t = json.loads((self.traces / "design-critic.json").read_text())
        self.assertTrue(t["recovery_validated"])

    # ---- Failure modes ----

    def test_fail_build_exit_nonzero(self):
        self._write_build(1)
        self._write_e2e(True)
        self._modify_tracked_file("src/x.ts", "// fix")
        self._write_trace("quality-fixer", {
            "agent": "quality-fixer",
            "provenance": "recovery",
            "verdict": "recovery",
            "partial": True,
            "recovery": True,
            "recovery_validated": False,
            "spawn_sha": self.spawn_sha,
            "fixes": [{"file": "src/x.ts"}],
        })
        proc = self._run("quality-fixer")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("exit_code=1", proc.stderr)
        t = json.loads((self.traces / "quality-fixer.json").read_text())
        self.assertFalse(t["recovery_validated"])

    def test_pass_e2e_failed_but_agent_is_non_fixer(self):
        """Issue #1046: read-only (non_fixer) agents skip the e2e-result.json.passed
        precondition — e2e outcome doesn't semantically bear on whether their
        analysis completed correctly. Otherwise every read-only agent's trace
        stays stuck at recovery_validated:false during bootstrap-verify."""
        self._write_build(0)
        self._write_e2e(False)  # e2e failed — acceptable for non-fixer
        # design-critic is a non-fixer AND a sibling trace proves scope ran
        self._write_trace("ux-journeyer-sibling", {
            "agent": "ux-journeyer",
            "provenance": "self",
            "verdict": "pass",
            "checks_performed": ["journey"],
        })
        self._write_trace("design-critic", {
            "agent": "design-critic",
            "provenance": "recovery",
            "verdict": "recovery",
            "partial": True,
            "recovery": True,
            "recovery_validated": False,
            "no_fixes_claimed": True,
            "spawn_sha": self.spawn_sha,
        })
        proc = self._run("design-critic")
        self.assertEqual(proc.returncode, 0, f"stderr={proc.stderr}")
        t = json.loads((self.traces / "design-critic.json").read_text())
        self.assertTrue(t["recovery_validated"])

    def test_fail_e2e_not_passed(self):
        self._write_build(0)
        self._write_e2e(False)
        self._modify_tracked_file("src/x.ts", "// fix")
        self._write_trace("quality-fixer", {
            "agent": "quality-fixer",
            "provenance": "self-degraded",
            "verdict": "degraded",
            "partial": True,
            "degraded_reason": "timeout",
            "recovery_validated": False,
            "spawn_sha": self.spawn_sha,
            "fixes": [{"file": "src/x.ts"}],
        })
        proc = self._run("quality-fixer")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("e2e-result.json shows failure", proc.stderr)

    def test_fail_fixes_not_in_diff(self):
        self._write_build(0)
        self._write_e2e(True)
        # No file modifications — diff set is empty
        self._write_trace("quality-fixer", {
            "agent": "quality-fixer",
            "provenance": "recovery",
            "verdict": "recovery",
            "partial": True,
            "recovery": True,
            "recovery_validated": False,
            "spawn_sha": self.spawn_sha,
            "fixes": [{"file": "src/nonexistent.ts"}],
        })
        proc = self._run("quality-fixer")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("not present in diff", proc.stderr)

    def test_fail_no_fixes_claimed_on_fixer_agent(self):
        self._write_build(0)
        self._write_e2e(True)
        # quality-fixer is NOT in non_fixer_agents — cannot claim no_fixes
        self._write_trace("quality-fixer", {
            "agent": "quality-fixer",
            "provenance": "self-degraded",
            "verdict": "degraded",
            "partial": True,
            "degraded_reason": "x",
            "recovery_validated": False,
            "no_fixes_claimed": True,
            "spawn_sha": self.spawn_sha,
        })
        proc = self._run("quality-fixer")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("non_fixer_agents", proc.stderr)

    def test_pass_no_fixes_claimed_without_sibling_but_build_ok(self):
        """Issue #1046 Option B: when no non-degraded sibling exists (e.g., ALL
        agents self-degrade because the guard blocks all trace writes), accept
        a successful build-result.json as alternative evidence that the scope
        actually executed."""
        self._write_build(0)
        self._write_e2e(True)
        # design-critic is a non-fixer, no sibling trace, but build is green
        self._write_trace("design-critic", {
            "agent": "design-critic",
            "provenance": "recovery",
            "verdict": "recovery",
            "partial": True,
            "recovery": True,
            "recovery_validated": False,
            "no_fixes_claimed": True,
            "spawn_sha": self.spawn_sha,
        })
        proc = self._run("design-critic")
        self.assertEqual(proc.returncode, 0,
                         f"expected pass when no sibling but build=0: stderr={proc.stderr}")

    def test_fail_no_fixes_claimed_without_sibling_and_build_fails(self):
        """When there's neither a non-degraded sibling nor a successful build,
        the findings-only path must still fail — the scope didn't execute."""
        self._write_build(1)  # build failed
        self._write_e2e(True)
        self._write_trace("design-critic", {
            "agent": "design-critic",
            "provenance": "recovery",
            "verdict": "recovery",
            "partial": True,
            "recovery": True,
            "recovery_validated": False,
            "no_fixes_claimed": True,
            "spawn_sha": self.spawn_sha,
        })
        proc = self._run("design-critic")
        self.assertNotEqual(proc.returncode, 0)
        # Either the build-result failure or the sibling fallback message is acceptable
        self.assertTrue(
            "non-degraded sibling" in proc.stderr or "build-result.json" in proc.stderr or "exit_code" in proc.stderr,
            f"expected sibling/build error in stderr: {proc.stderr}"
        )

    def test_fail_missing_build_result(self):
        # No build-result.json written
        self._write_e2e(True)
        self._write_trace("quality-fixer", {
            "agent": "quality-fixer",
            "provenance": "recovery",
            "verdict": "recovery",
            "partial": True,
            "recovery": True,
            "recovery_validated": False,
            "spawn_sha": self.spawn_sha,
            "fixes": [{"file": "x"}],
        })
        proc = self._run("quality-fixer")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("build-result.json missing", proc.stderr)

    # ---- Skip path ----

    def test_skip_when_provenance_self(self):
        # provenance=self traces should short-circuit — the script is not
        # responsible for them. Returns 0 with a stderr SKIP note.
        self._write_trace("observer", {
            "agent": "observer",
            "provenance": "self",
            "verdict": "filed",
        })
        proc = self._run("observer")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("SKIP", proc.stderr)

    def test_skip_when_missing_trace(self):
        proc = self._run("does-not-exist")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("trace not found", proc.stderr)

    # ---- AOC v1.1: lead-on-behalf goes through the validation chain ----

    def test_lead_on_behalf_validates_with_tracked_fix(self):
        """lead-on-behalf is a validate-eligible provenance (AOC v1.1).
        Same diff-fix correlation rules as recovery / self-degraded apply.
        """
        self._write_build(0)
        self._write_e2e(True)
        self._modify_tracked_file("src/app/landing/page.tsx", "// fix")
        self._write_trace("ux-journeyer", {
            "agent": "ux-journeyer",
            "provenance": "lead-on-behalf",
            "partial": True,
            "source": "agent-returned-text",
            "verdict": "pass",
            "fixes": [{"file": "src/app/landing/page.tsx",
                       "symptom": "missing alt", "fix": "added"}],
            "spawn_sha": self.spawn_sha,
            "recovery_validated": False,
        })
        proc = self._run("ux-journeyer")
        self.assertEqual(proc.returncode, 0,
                         f"lead-on-behalf with tracked fix should validate: {proc.stderr}")
        # recovery_validated stamped true
        d = json.loads((self.traces / "ux-journeyer.json").read_text())
        self.assertTrue(d.get("recovery_validated"))

    def test_lead_on_behalf_blocked_when_fix_not_in_diff(self):
        self._write_build(0)
        self._write_e2e(True)
        # No file actually modified — the fixes[] file should NOT appear in diff
        self._write_trace("ux-journeyer", {
            "agent": "ux-journeyer",
            "provenance": "lead-on-behalf",
            "partial": True,
            "source": "agent-returned-text",
            "verdict": "pass",
            "fixes": [{"file": "src/forged.ts", "symptom": "x", "fix": "y"}],
            "spawn_sha": self.spawn_sha,
            "recovery_validated": False,
        })
        proc = self._run("ux-journeyer")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("not present in diff", proc.stderr)

    def test_lead_synthesized_skipped_by_validate(self):
        """lead-synthesized has its own attestation path (coverage_provider);
        validate-recovery.sh skips it just like provenance=self."""
        self._write_trace("observer", {
            "agent": "observer",
            "provenance": "lead-synthesized",
            "partial": True,
            "coverage_provider": "tests/flows.test.ts",
            "no_fixes_claimed": True,
            "verdict": "pass",
        })
        proc = self._run("observer")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("SKIP", proc.stderr)

    def test_lead_fix_skipped_by_validate(self):
        """lead-fix has its own attestation (lead_attestation:true); skipped here."""
        self._write_trace("observer", {
            "agent": "observer",
            "provenance": "lead-fix",
            "partial": True,
            "lead_attestation": True,
            "verdict": "pass",
        })
        proc = self._run("observer")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("SKIP", proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
