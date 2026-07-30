#!/usr/bin/env python3
"""test_consultation_deny_values.py — regression for the CONSULTATION_DENY
value mismatch fixed by the #1855 remediation: the gecr-cutover-overdue linter
message historically suggested `CONSULTATION_DENY=deny` while
verify-recurrence-guard.py Step 14c tested `== "1"`, so following the message
silently kept the gate in warn mode. The gate now accepts {"1", "deny"};
anything else (including unset and "0") stays warn-only.

Run: python3 -m pytest .claude/scripts/tests/test_consultation_deny_values.py -v
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
SCRIPT = ROOT / ".claude/scripts/verify-recurrence-guard.py"


class ConsultationFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_cdv_"))
        self.runs = self.tmp / ".runs"
        self.runs.mkdir()
        # Minimal structurally-valid solve trace whose prevention_analysis is a
        # defect, with NO prior_failure_consultation — the Step 14c violation.
        (self.runs / "solve-trace.json").write_text(json.dumps({
            "mode": "light",
            "problem_decomposition": "d",
            "constraint_enumeration": "c",
            "solution_design": "s",
            "self_check": "ok",
            "output": "o",
            "prevention_analysis": {"problem_type": "defect"},
            # Satisfies assert_dossier_loaded contract (b)+(d) so execution
            # reaches the Step 14c consultation gate under test.
            "prior_failure_response": [
                {"prior_run_id": "solve-prior-1", "response": "reviewed"}],
        }))
        (self.runs / "prior-failure-dossier.json").write_text(json.dumps({
            "phase_1a": [{
                "prior_run_id": "solve-prior-1",
                "designer_consultation_attestation_required": True,
            }],
        }))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_guard(self, deny_value=None) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.pop("CONSULTATION_DENY", None)
        if deny_value is not None:
            env["CONSULTATION_DENY"] = deny_value
        return subprocess.run(
            ["python3", str(SCRIPT), "--skill", "solve", "--require-dossier"],
            cwd=self.tmp, capture_output=True, text=True, env=env, timeout=60,
        )

    def test_unset_warns_and_passes(self):
        r = self.run_guard(None)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("VERIFY WARN", r.stderr)
        self.assertIn("prior_failure_consultation", r.stderr)

    def test_one_denies(self):
        r = self.run_guard("1")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("VERIFY FAIL", r.stderr)

    def test_deny_spelling_denies(self):
        r = self.run_guard("deny")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("VERIFY FAIL", r.stderr)

    def test_zero_warns_only(self):
        r = self.run_guard("0")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("VERIFY WARN", r.stderr)


if __name__ == "__main__":
    sys.exit(unittest.main())
