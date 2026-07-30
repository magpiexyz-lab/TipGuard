#!/usr/bin/env python3
"""test_state_registry_7b.py — coverage for state-7b VERIFY sanctioned-aggregate
exemption (#1042 Sub-branch S1 + #1061 fast-path).

The state-7b VERIFY (state-registry.json verify[7b] + state-7b-compute-qscore.md
L143) cross-validates that hard_gate_failure=true is set whenever any agent
trace is in a failure state. The exemption: when design-critic.json is a
sanctioned aggregate (every contributing per-page sibling is provenance=self
with normal verdict OR provenance=self-degraded with recovery_validated=true
and a sanctioned degraded_reason in {demo-mode-fixture-short-circuit,
empty-boundary-fast-path}), the cross-validation MUST NOT fail with
hard_gate_failure=false.

This test exercises the helper script `check-design-critic-sanctioned.py`
directly, which is the load-bearing primitive.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / ".claude/scripts/check-design-critic-sanctioned.py"


def run_helper(trace: dict) -> int:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(trace, f)
        path = f.name
    try:
        return subprocess.run(
            ["python3", str(HELPER), path],
            capture_output=True,
            text=True,
        ).returncode
    finally:
        Path(path).unlink(missing_ok=True)


class TestSanctionedHelper(unittest.TestCase):
    def test_pure_demo_mode_aggregate_sanctioned(self):
        """Aggregate where every contributing page is sanctioned-demo-mode-
        short-circuit with recovery_validated=true → exit 0."""
        agg = {
            "agent": "design-critic",
            "verdict": "unresolved",
            "provenance": "lead-merge",
            "partial": True,
            "contributing_spawn_indexes": [0],
            "per_page_provenance": {"quote": "self-degraded"},
            "per_page_recovery_validated": {"quote": True},
            "per_page_degraded_reason": {
                "quote": "demo-mode-fixture-short-circuit"
            },
        }
        self.assertEqual(run_helper(agg), 0,
                         "pure demo-mode aggregate must be sanctioned")

    def test_pure_empty_boundary_aggregate_sanctioned(self):
        """Aggregate where every contributing page is empty-boundary-fast-path
        with recovery_validated=true → exit 0."""
        agg = {
            "agent": "design-critic",
            "verdict": "pass",
            "provenance": "lead-merge",
            "partial": True,
            "contributing_spawn_indexes": [0],
            "per_page_provenance": {"dashboard": "self-degraded"},
            "per_page_recovery_validated": {"dashboard": True},
            "per_page_degraded_reason": {"dashboard": "empty-boundary-fast-path"},
        }
        self.assertEqual(run_helper(agg), 0,
                         "pure empty-boundary aggregate must be sanctioned")

    def test_mixed_sanctioned_aggregate_sanctioned(self):
        """Aggregate where landing fast-paths and quote demo-mode-short-circuits
        — every page is in a sanctioned shape → exit 0."""
        agg = {
            "agent": "design-critic",
            "verdict": "unresolved",
            "provenance": "lead-merge",
            "partial": True,
            "contributing_spawn_indexes": [0, 1],
            "per_page_provenance": {
                "landing": "self-degraded",
                "quote": "self-degraded",
            },
            "per_page_recovery_validated": {"landing": True, "quote": True},
            "per_page_degraded_reason": {
                "landing": "empty-boundary-fast-path",
                "quote": "demo-mode-fixture-short-circuit",
            },
        }
        self.assertEqual(run_helper(agg), 0,
                         "mixed sanctioned aggregate must be sanctioned")

    def test_mixed_self_and_self_degraded_sanctioned(self):
        """Aggregate where one page is self/pass (normal review) and another
        is self-degraded with sanctioned reason → exit 0."""
        agg = {
            "agent": "design-critic",
            "verdict": "unresolved",
            "provenance": "lead-merge",
            "partial": True,
            "contributing_spawn_indexes": [0, 1],
            "per_page_provenance": {
                "landing": "self",
                "quote": "self-degraded",
            },
            "per_page_recovery_validated": {"quote": True},
            "per_page_degraded_reason": {
                "quote": "demo-mode-fixture-short-circuit"
            },
        }
        self.assertEqual(run_helper(agg), 0,
                         "self + sanctioned-self-degraded must be sanctioned")

    def test_genuine_unresolved_not_sanctioned(self):
        """Aggregate with provenance=self (single-spawn legacy) and
        verdict=unresolved is genuinely failing → exit 1 (not sanctioned)."""
        agg = {
            "agent": "design-critic",
            "verdict": "unresolved",
            "provenance": "self",
            "unresolved_sections": 3,
        }
        self.assertEqual(run_helper(agg), 1,
                         "genuine unresolved must NOT be sanctioned")

    def test_unvalidated_demo_mode_not_sanctioned(self):
        """Aggregate where the demo-mode page has recovery_validated=false
        → exit 1 (not sanctioned)."""
        agg = {
            "agent": "design-critic",
            "verdict": "unresolved",
            "provenance": "lead-merge",
            "contributing_spawn_indexes": [0],
            "per_page_provenance": {"quote": "self-degraded"},
            "per_page_recovery_validated": {"quote": False},
            "per_page_degraded_reason": {
                "quote": "demo-mode-fixture-short-circuit"
            },
        }
        self.assertEqual(run_helper(agg), 1,
                         "unvalidated demo-mode must NOT be sanctioned")

    def test_unsanctioned_reason_not_sanctioned(self):
        """Aggregate where degraded_reason is something other than the
        sanctioned set → exit 1."""
        agg = {
            "agent": "design-critic",
            "verdict": "unresolved",
            "provenance": "lead-merge",
            "contributing_spawn_indexes": [0],
            "per_page_provenance": {"home": "self-degraded"},
            "per_page_recovery_validated": {"home": True},
            "per_page_degraded_reason": {"home": "unknown-failure"},
        }
        self.assertEqual(run_helper(agg), 1,
                         "non-sanctioned reason must NOT be sanctioned")

    def test_missing_provenance_not_sanctioned(self):
        """Aggregate that lacks per_page_provenance entirely → exit 1.
        Guards against pre-AOC-v1 / incomplete-merge traces."""
        agg = {
            "agent": "design-critic",
            "verdict": "unresolved",
            "provenance": "lead-merge",
            "contributing_spawn_indexes": [0],
            # No per_page_provenance map — incomplete merge
        }
        self.assertEqual(run_helper(agg), 1,
                         "missing per_page_provenance must NOT be sanctioned")

    def test_non_lead_merge_not_sanctioned(self):
        """Aggregate with provenance != lead-merge cannot be sanctioned.
        Guards against accidentally treating per-page traces as aggregates."""
        agg = {
            "agent": "design-critic",
            "verdict": "pass",
            "provenance": "self-degraded",
            "recovery_validated": True,
            "degraded_reason": "empty-boundary-fast-path",
            "per_page_provenance": {"dashboard": "self-degraded"},
            "per_page_recovery_validated": {"dashboard": True},
            "per_page_degraded_reason": {"dashboard": "empty-boundary-fast-path"},
        }
        self.assertEqual(run_helper(agg), 1,
                         "non-lead-merge aggregate must NOT be sanctioned")

    def test_unrelated_provenance_not_sanctioned(self):
        """Aggregate where one page has provenance="recovery" or some other
        non-{self,self-degraded} value → exit 1. Helper restricts to two
        provenance categories explicitly."""
        agg = {
            "agent": "design-critic",
            "verdict": "unresolved",
            "provenance": "lead-merge",
            "contributing_spawn_indexes": [0],
            "per_page_provenance": {"home": "recovery"},
            "per_page_recovery_validated": {"home": True},
            "per_page_degraded_reason": {"home": "empty-boundary-fast-path"},
        }
        self.assertEqual(run_helper(agg), 1,
                         "provenance=recovery must NOT be sanctioned via this path")


if __name__ == "__main__":
    unittest.main()
