"""Unit tests for .claude/scripts/lib/dossier_verify.py (Issue #1415).

Six cases lock dossier-verification edge cases:
  (a) defect + missing dossier file               -> raise
  (b) defect + valid dossier + matching response  -> pass
  (c) defect + empty dossier + empty response     -> pass (fresh project)
  (d) defect + _meta empty but evidence non-empty -> raise (no-empty-bypass)
  (e) non-defect + missing dossier                -> no-op pass
  (f) defect + mismatched response count          -> raise
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / ".claude" / "scripts" / "lib"))

from dossier_verify import DossierVerifyError, assert_dossier_loaded  # noqa: E402


class TestDossierVerify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.tmp)
        os.makedirs(".runs", exist_ok=True)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_dossier(self, phase_1a, divergence_files=None):
        Path(".runs/prior-failure-dossier.json").write_text(json.dumps({
            "phase_1a": phase_1a,
            "phase_4b": phase_1a,
            "_meta": {
                "divergence_files": divergence_files or [],
                "symptom_signature": "test",
            },
        }))

    def test_a_defect_missing_dossier_raises(self):
        with self.assertRaises(DossierVerifyError) as cm:
            assert_dossier_loaded(
                {"prior_failure_response": []},
                problem_type="defect",
                divergence_files_evidence=[],
            )
        self.assertIn("missing", str(cm.exception))

    def test_b_defect_valid_match_passes(self):
        self._write_dossier(
            phase_1a=[{"prior_run_id": "x"}],
            divergence_files=["a.py"],
        )
        trace = {"prior_failure_response": [{"prior_run_id": "x"}]}
        assert_dossier_loaded(
            trace,
            problem_type="defect",
            divergence_files_evidence=["a.py"],
        )

    def test_c_defect_empty_dossier_empty_response_passes(self):
        self._write_dossier(phase_1a=[], divergence_files=["a.py"])
        trace = {"prior_failure_response": []}
        assert_dossier_loaded(
            trace,
            problem_type="defect",
            divergence_files_evidence=["a.py"],
        )

    def test_d_no_empty_bypass(self):
        self._write_dossier(phase_1a=[], divergence_files=[])
        trace = {"prior_failure_response": []}
        with self.assertRaises(DossierVerifyError) as cm:
            assert_dossier_loaded(
                trace,
                problem_type="defect",
                divergence_files_evidence=["a.py"],
            )
        self.assertIn("empty", str(cm.exception).lower())

    def test_e_non_defect_noop(self):
        assert_dossier_loaded(
            {},
            problem_type="feature",
            divergence_files_evidence=[],
        )

    def test_f_mismatched_response_count_raises(self):
        self._write_dossier(
            phase_1a=[{"prior_run_id": str(i)} for i in range(3)],
            divergence_files=["a.py"],
        )
        trace = {
            "prior_failure_response": [
                {"prior_run_id": "0"},
                {"prior_run_id": "1"},
            ],
        }
        with self.assertRaises(DossierVerifyError) as cm:
            assert_dossier_loaded(
                trace,
                problem_type="defect",
                divergence_files_evidence=["a.py"],
            )
        self.assertIn("phase_1a", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
