#!/usr/bin/env python3
"""test_verify_rmg_guard_artifact.py — RMG v2 Phase E.

Exercises `.claude/scripts/verify-rmg-guard-artifact-in-diff.py`. Each test
constructs a synthetic `solve-trace.json`, sets `PROJECT_DIR` to a temp dir,
and asserts the script's exit code.

Cases:
  * recurrence_risk=none          -> exit 0 (no guard required)
  * kind=test, artifact in repo   -> exit 0
  * kind=test, artifact missing   -> exit 2
  * kind=lint, null artifact      -> exit 2
  * kind=none, strong rationale   -> exit 0
  * kind=none, missing rationale  -> exit 1 or 3 (parser or heuristic)
  * kind=none, missing review hint-> exit 1 or 3
  * legacy free-text guard        -> exit 0 with WARN
  * malformed dict                -> exit 1
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / ".claude" / "scripts" / "verify-rmg-guard-artifact-in-diff.py"


def _run(trace: dict, project_dir: Path) -> subprocess.CompletedProcess:
    runs = project_dir / ".runs"
    runs.mkdir(parents=True, exist_ok=True)
    trace_path = runs / "solve-trace.json"
    trace_path.write_text(json.dumps(trace))
    env = dict(os.environ, PROJECT_DIR=str(project_dir))
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--trace", str(trace_path), "--merge-base", "origin/main"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


class GuardArtifactTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="rmg-e-")
        self.project_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_recurrence_risk_none(self):
        result = _run(
            {"prevention_analysis": {"problem_type": "defect", "recurrence_risk": "none"}},
            self.project_dir,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_test_kind_artifact_present(self):
        # Create the artifact under project_dir so the on-disk check passes
        (self.project_dir / "tests").mkdir()
        (self.project_dir / "tests" / "regression.py").write_text("# stub")
        result = _run(
            {
                "prevention_analysis": {
                    "problem_type": "defect",
                    "recurrence_risk": "guarded",
                    "recurrence_guard": {
                        "kind": "test",
                        "artifact": "tests/regression.py",
                        "rationale": "covers the null path",
                    },
                }
            },
            self.project_dir,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_test_kind_artifact_missing_blocks(self):
        result = _run(
            {
                "prevention_analysis": {
                    "problem_type": "defect",
                    "recurrence_risk": "guarded",
                    "recurrence_guard": {
                        "kind": "test",
                        "artifact": "tests/does-not-exist.py",
                        "rationale": "x",
                    },
                }
            },
            self.project_dir,
        )
        self.assertEqual(result.returncode, 2, msg=result.stderr)

    def test_lint_null_artifact_blocks(self):
        result = _run(
            {
                "prevention_analysis": {
                    "problem_type": "defect",
                    "recurrence_risk": "guarded",
                    "recurrence_guard": {
                        "kind": "lint",
                        "artifact": None,
                        "rationale": "x",
                    },
                }
            },
            self.project_dir,
        )
        self.assertEqual(result.returncode, 2, msg=result.stderr)

    def test_none_kind_strong_rationale(self):
        rationale = (
            "no executable check expresses this invariant because it lives in "
            "prose; reviewers monitor the rendered docs page on every PR for drift"
        )
        result = _run(
            {
                "prevention_analysis": {
                    "problem_type": "defect",
                    "recurrence_risk": "unguarded",
                    "recurrence_guard": {
                        "kind": "none",
                        "artifact": None,
                        "rationale": "see unguardability rationale",
                        "unguardability_rationale": rationale,
                    },
                }
            },
            self.project_dir,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_none_kind_missing_review_hint_blocks(self):
        rationale = (
            "no executable check fits because this is a one-off prose change, "
            "and we will rely on developer discipline alone going forward."
        )
        result = _run(
            {
                "prevention_analysis": {
                    "problem_type": "defect",
                    "recurrence_risk": "unguarded",
                    "recurrence_guard": {
                        "kind": "none",
                        "artifact": None,
                        "rationale": "x",
                        "unguardability_rationale": rationale,
                    },
                }
            },
            self.project_dir,
        )
        # Either parser (1) or heuristic (3) blocks; both are correct hard fails.
        self.assertIn(result.returncode, (1, 3), msg=result.stderr)

    def test_legacy_freetext_blocks_by_default(self):
        # Post-cutover: tolerant mode is OFF by default. Legacy free-text fails
        # to parse and exits 1 (hard block).
        prev = os.environ.pop("RMG_V2_TOLERANT", None)
        try:
            result = _run(
                {
                    "prevention_analysis": {
                        "problem_type": "defect",
                        "recurrence_risk": "guarded",
                        "recurrence_guard": "we'll add a regression test later",
                    }
                },
                self.project_dir,
            )
            self.assertEqual(result.returncode, 1, msg=result.stderr)
        finally:
            if prev is not None:
                os.environ["RMG_V2_TOLERANT"] = prev

    def test_legacy_freetext_warns_when_escape_hatch_explicit(self):
        # Setting RMG_V2_TOLERANT=1 re-enables the legacy escape hatch:
        # parser returns kind=legacy_freetext, helper logs WARN and exits 0.
        prev = os.environ.get("RMG_V2_TOLERANT")
        os.environ["RMG_V2_TOLERANT"] = "1"
        try:
            result = _run(
                {
                    "prevention_analysis": {
                        "problem_type": "defect",
                        "recurrence_risk": "guarded",
                        "recurrence_guard": "we'll add a regression test later",
                    }
                },
                self.project_dir,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("legacy", result.stderr.lower())
        finally:
            if prev is None:
                os.environ.pop("RMG_V2_TOLERANT", None)
            else:
                os.environ["RMG_V2_TOLERANT"] = prev

    def test_malformed_dict_blocks(self):
        result = _run(
            {
                "prevention_analysis": {
                    "problem_type": "defect",
                    "recurrence_risk": "guarded",
                    "recurrence_guard": {"kind": "manual", "artifact": "x", "rationale": "y"},
                }
            },
            self.project_dir,
        )
        self.assertEqual(result.returncode, 1, msg=result.stderr)


if __name__ == "__main__":
    unittest.main()
