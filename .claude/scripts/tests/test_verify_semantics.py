#!/usr/bin/env python3
"""Behavioral tests for review-skill VERIFY semantics.

Validates that the VERIFY commands in state-registry.json review/2e/2f/3/4
correctly accept the post-states their ACTIONS allow, and reject states
their ACTIONS forbid. Catches regressions where VERIFY drifts from ACTIONS
intent (the #928 bug class).

Each test:
  1. Constructs a fixture file mimicking what an upstream state would write
  2. Runs the registry VERIFY command via subprocess
  3. Asserts exit code matches expected accept/reject behavior

Run via: python3 .claude/scripts/tests/test_verify_semantics.py
Or via:  bash .claude/scripts/tests/run-all.sh
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
REGISTRY_PATH = os.path.join(REPO_ROOT, ".claude", "patterns", "state-registry.json")


def load_verify(skill: str, state_id: str) -> str:
    """Extract the VERIFY command for a given skill/state from state-registry.json."""
    with open(REGISTRY_PATH) as f:
        registry = json.load(f)
    entry = registry[skill][state_id]
    if isinstance(entry, dict):
        return entry["verify"]
    return entry


def run_verify(skill: str, state_id: str, cwd: str) -> int:
    """Run the registry VERIFY command in `cwd` and return exit code."""
    cmd = load_verify(skill, state_id)
    result = subprocess.run(
        ["bash", "-c", cmd],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return result.returncode


class TestReviewState2eVerify(unittest.TestCase):
    """STATE 2e VERIFY: requires .runs/review-loop-decision.json with fixes_succeeded + exit_reason."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmpdir, ".runs"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_loop_decision(self, payload: dict):
        path = os.path.join(self.tmpdir, ".runs", "review-loop-decision.json")
        with open(path, "w") as f:
            json.dump(payload, f)

    def test_no_fixes_exit_passes(self):
        """ACTIONS allow zero-fix exit; VERIFY must accept exit_reason='no_fixes'."""
        self._write_loop_decision({
            "fixes_succeeded": 0,
            "fixes_reverted": 0,
            "fixes_skipped": 5,
            "exit_reason": "no_fixes",
        })
        self.assertEqual(run_verify("review", "2e", self.tmpdir), 0)

    def test_all_findings_processed_passes(self):
        """ACTIONS allow exit after all findings processed; VERIFY accepts."""
        self._write_loop_decision({
            "fixes_succeeded": 3,
            "fixes_reverted": 1,
            "fixes_skipped": 2,
            "exit_reason": "all_findings_processed",
        })
        self.assertEqual(run_verify("review", "2e", self.tmpdir), 0)

    def test_missing_fixes_succeeded_fails(self):
        """VERIFY must fail if fixes_succeeded field absent."""
        self._write_loop_decision({"exit_reason": "no_fixes"})
        self.assertNotEqual(run_verify("review", "2e", self.tmpdir), 0)

    def test_missing_exit_reason_fails(self):
        """VERIFY must fail if exit_reason field absent."""
        self._write_loop_decision({"fixes_succeeded": 3})
        self.assertNotEqual(run_verify("review", "2e", self.tmpdir), 0)

    def test_missing_artifact_fails(self):
        """VERIFY must fail if review-loop-decision.json doesn't exist."""
        self.assertNotEqual(run_verify("review", "2e", self.tmpdir), 0)


class TestReviewState2fVerify(unittest.TestCase):
    """STATE 2f VERIFY: must preserve 2e fields AND add iteration/yield/termination/continue."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmpdir, ".runs"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_loop_decision(self, payload: dict):
        path = os.path.join(self.tmpdir, ".runs", "review-loop-decision.json")
        with open(path, "w") as f:
            json.dump(payload, f)

    def test_full_decision_passes(self):
        """All 2e + 2f fields present → VERIFY passes."""
        self._write_loop_decision({
            "fixes_succeeded": 3,
            "exit_reason": "all_findings_processed",
            "iteration": 2,
            "yield_rate": 0.6,
            "termination_condition": "minimum_floor",
            "continue": False,
        })
        self.assertEqual(run_verify("review", "2f", self.tmpdir), 0)

    def test_2e_fields_lost_fails(self):
        """If 2e fields are missing (state-2f overwrote instead of update), VERIFY fails.

        This is the regression guard for the bug where state-2f used
        `json.dump(d, ...)` with a fresh dict instead of read-extend.
        """
        self._write_loop_decision({
            # 2e fields intentionally absent — simulating overwrite bug
            "iteration": 2,
            "yield_rate": 0.6,
            "termination_condition": "minimum_floor",
            "continue": False,
        })
        self.assertNotEqual(run_verify("review", "2f", self.tmpdir), 0)

    def test_2f_fields_missing_fails(self):
        """2e fields present but 2f fields absent → VERIFY fails."""
        self._write_loop_decision({
            "fixes_succeeded": 0,
            "exit_reason": "no_fixes",
            # iteration/yield_rate/termination_condition/continue absent
        })
        self.assertNotEqual(run_verify("review", "2f", self.tmpdir), 0)


class TestReviewState4Verify(unittest.TestCase):
    """STATE 4 VERIFY: accepts final_errors <= baseline_errors (non-regression)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmpdir, ".runs"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_complete(self, baseline: int, final: int):
        path = os.path.join(self.tmpdir, ".runs", "review-complete.json")
        with open(path, "w") as f:
            json.dump({
                "branch": "test",
                "timestamp": "2026-04-22T00:00:00Z",
                "iterations": 1,
                "yield": 0.5,
                "baseline_errors": baseline,
                "final_errors": final,
                "findings_fixed": 1,
                "findings_disputed": 0,
            }, f)

    def test_below_baseline_passes(self):
        """final_errors < baseline_errors → VERIFY accepts (errors decreased)."""
        self._write_complete(baseline=10, final=5)
        self.assertEqual(run_verify("review", "4", self.tmpdir), 0)

    def test_at_baseline_passes(self):
        """final_errors == baseline_errors → VERIFY accepts (no regression).

        This is the #928 case: legacy projects with non-zero baselines must
        not be blocked by VERIFY when no new errors were introduced.
        """
        self._write_complete(baseline=5, final=5)
        self.assertEqual(run_verify("review", "4", self.tmpdir), 0)

    def test_above_baseline_fails(self):
        """final_errors > baseline_errors → VERIFY rejects (regression)."""
        self._write_complete(baseline=5, final=6)
        self.assertNotEqual(run_verify("review", "4", self.tmpdir), 0)

    def test_zero_baseline_zero_final_passes(self):
        """Clean project (baseline=0, final=0) → VERIFY accepts."""
        self._write_complete(baseline=0, final=0)
        self.assertEqual(run_verify("review", "4", self.tmpdir), 0)

    def test_missing_artifact_fails(self):
        """VERIFY must fail if review-complete.json doesn't exist."""
        self.assertNotEqual(run_verify("review", "4", self.tmpdir), 0)

    def test_malformed_artifact_missing_fields_fails(self):
        """VERIFY must fail if final_errors / baseline_errors fields are absent.

        Regression guard: previous VERIFY used d.get('final_errors',0) which
        defaulted missing fields to 0, producing 0 <= 0 = True (false pass).
        """
        path = os.path.join(self.tmpdir, ".runs", "review-complete.json")
        with open(path, "w") as f:
            json.dump({"branch": "x"}, f)
        self.assertNotEqual(run_verify("review", "4", self.tmpdir), 0)

    def test_malformed_artifact_string_types_fails(self):
        """VERIFY must fail if final_errors / baseline_errors are strings.

        Regression guard: Python compares strings lexicographically, so
        '10' <= '5' is True — a 5-error regression would slip through if
        the upstream writer accidentally serialised numerics as strings.
        """
        path = os.path.join(self.tmpdir, ".runs", "review-complete.json")
        with open(path, "w") as f:
            json.dump({
                "branch": "test",
                "baseline_errors": "5",
                "final_errors": "10",
            }, f)
        self.assertNotEqual(run_verify("review", "4", self.tmpdir), 0)


class TestReviewState3Verify(unittest.TestCase):
    """STATE 3 VERIFY: only checks scripts/check-inventory.md exists and non-empty.

    Bug fix: previously checked review-complete.json (which state-4 writes,
    not state-3) and would always fail when state-3 ran immediately after 2f.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmpdir, "scripts"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_inventory_present_passes(self):
        """check-inventory.md exists and non-empty → VERIFY passes."""
        with open(os.path.join(self.tmpdir, "scripts", "check-inventory.md"), "w") as f:
            f.write("# Check Inventory\n\n## Frontmatter checks\n\n- check_1\n")
        self.assertEqual(run_verify("review", "3", self.tmpdir), 0)

    def test_inventory_missing_fails(self):
        """check-inventory.md missing → VERIFY fails."""
        self.assertNotEqual(run_verify("review", "3", self.tmpdir), 0)

    def test_inventory_empty_fails(self):
        """check-inventory.md exists but empty → VERIFY fails."""
        with open(os.path.join(self.tmpdir, "scripts", "check-inventory.md"), "w") as f:
            pass  # empty
        self.assertNotEqual(run_verify("review", "3", self.tmpdir), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
