#!/usr/bin/env python3
"""test_review_verdict_gate.py — validate the shared review-verdict-gate
procedure (.claude/scripts/run-review-verdict-gate.py + the matching
Python port in .claude/patterns/review-verdict-gate.md).

Coverage:
  T1 behavior-verifier prereq-unmet → SKIPPED (overrides agent-emitted FAIL)
  T2 behavior-verifier source-only on AUTH_PATHS final → FAIL
  T3 behavior-verifier source-only on non-AUTH final → DEGRADED
  T4 ux-journeyer per_step_reviews enforcement (per-step status)
  T5 design-critic regression pin (gate doesn't change verdict — design-critic
     enforcement lives in state-3b's merge code, not this gate)
  T6 idempotency: trace already has sentinel → no-op
  T7 sentinel always written even when 0 corrections applied

Exit 0 on all-pass, 1 on any failure.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
GATE_SCRIPT = ROOT / ".claude/scripts/run-review-verdict-gate.py"


def run_gate(trace: dict, agent: str) -> dict:
    """Write trace to a tmp file, run the gate, return loaded trace + result."""
    with tempfile.TemporaryDirectory() as tmp:
        trace_path = Path(tmp) / f"{agent}.json"
        trace_path.write_text(json.dumps(trace))

        result = subprocess.run(
            ["python3", str(GATE_SCRIPT), str(trace_path), agent],
            capture_output=True,
            text=True,
        )
        # Re-read to capture mutations
        post = json.loads(trace_path.read_text())
        return {
            "post": post,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode,
        }


class TestReviewVerdictGate(unittest.TestCase):
    # ------------------------------------------------------------------
    # T1: behavior-verifier — prereq-unmet → SKIPPED
    # ------------------------------------------------------------------
    def test_T1_prereq_unmet_overrides_agent_FAIL(self):
        trace = {
            "agent": "behavior-verifier",
            "verdict": "FAIL",
            "per_behavior_reviews": [
                {
                    "behavior_id": "b1",
                    "given": "logged-in user",
                    "review_method": "prereq-unmet",
                    "review_evidence": {
                        "requested_route": "/dashboard",
                        "final_url": None,
                        "fallback_reason": "auth.json-absent",
                    },
                    "verdict": "FAIL",  # agent emitted wrong verdict
                }
            ],
        }
        out = run_gate(trace, "behavior-verifier")
        self.assertTrue(out["post"]["review_method_gate_evaluated"])
        self.assertEqual(out["post"]["per_behavior_reviews"][0]["verdict"], "SKIPPED")
        # Correction logged
        corrections = out["post"]["review_method_gate_corrections"]
        self.assertEqual(len(corrections), 1)
        self.assertEqual(corrections[0]["original_verdict"], "FAIL")
        self.assertEqual(corrections[0]["corrected_to"], "SKIPPED")

    # ------------------------------------------------------------------
    # T2: behavior-verifier source-only with auth-path final → FAIL
    # ------------------------------------------------------------------
    def test_T2_source_only_auth_path_FAIL(self):
        trace = {
            "agent": "behavior-verifier",
            "per_behavior_reviews": [
                {
                    "behavior_id": "b2",
                    "review_method": "source-only",
                    "review_evidence": {
                        "requested_route": "/dashboard",
                        "final_url": "http://localhost:3097/login",
                    },
                    "verdict": "DEGRADED",  # wrong: should be FAIL
                }
            ],
        }
        out = run_gate(trace, "behavior-verifier")
        self.assertEqual(out["post"]["per_behavior_reviews"][0]["verdict"], "FAIL")

    # ------------------------------------------------------------------
    # T3: behavior-verifier source-only with non-auth final → DEGRADED
    # ------------------------------------------------------------------
    def test_T3_source_only_non_auth_DEGRADED(self):
        trace = {
            "agent": "behavior-verifier",
            "per_behavior_reviews": [
                {
                    "behavior_id": "b3",
                    "review_method": "source-only",
                    "review_evidence": {
                        "requested_route": "/pricing",
                        "final_url": "http://localhost:3097/pricing/individual",
                    },
                    "verdict": "FAIL",  # wrong: should be DEGRADED (product redirect)
                }
            ],
        }
        out = run_gate(trace, "behavior-verifier")
        self.assertEqual(out["post"]["per_behavior_reviews"][0]["verdict"], "DEGRADED")

    # ------------------------------------------------------------------
    # T4: ux-journeyer per_step_reviews enforcement
    # ------------------------------------------------------------------
    def test_T4_ux_journeyer_per_step_status_enforcement(self):
        trace = {
            "agent": "ux-journeyer",
            "verdict": "pass",  # will get forced to "blocked" by prereq-unmet step
            "per_step_reviews": [
                {
                    "step_index": 0,
                    "review_method": "rendered-demo",
                    "review_evidence": {
                        "requested_route": "/",
                        "final_url": "http://localhost:3098/login",
                    },
                    "status": "dead-end",  # wrong: rendered-demo means pass
                },
                {
                    "step_index": 1,
                    "review_method": "prereq-unmet",
                    "review_evidence": {
                        "requested_route": "/dashboard",
                        "final_url": None,
                    },
                    "status": "pass",  # wrong: should be "blocked"
                },
            ],
        }
        out = run_gate(trace, "ux-journeyer")
        self.assertTrue(out["post"]["review_method_gate_evaluated"])
        self.assertEqual(out["post"]["per_step_reviews"][0]["status"], "pass")
        self.assertEqual(out["post"]["per_step_reviews"][1]["status"], "blocked")
        # prereq-unmet on a step forces top-level verdict=blocked
        self.assertEqual(out["post"]["verdict"], "blocked")

    # ------------------------------------------------------------------
    # T5: design-critic regression pin — gate doesn't reach into design-critic
    # ------------------------------------------------------------------
    def test_T5_design_critic_unaffected_by_gate(self):
        """design-critic's enforcement lives in state-3b's merge code, not
        this gate. The gate must not have a policy entry for design-critic
        that would conflict with state-3b's authoritative rule. Calling
        the gate against a design-critic trace just writes the sentinel."""
        trace = {
            "agent": "design-critic",
            "verdict": "pass",  # contract violation: source-only should be unresolved
            "per_page_reviews": [
                {
                    "page": "landing",
                    "review_method": "source-only",
                    "review_evidence": {
                        "requested_route": "/",
                        "final_url": "http://localhost:3099/login",
                    },
                }
            ],
        }
        out = run_gate(trace, "design-critic")
        self.assertTrue(out["post"]["review_method_gate_evaluated"])
        # Top-level verdict NOT changed — that's state-3b's job, not this gate's
        self.assertEqual(out["post"]["verdict"], "pass")
        # No corrections logged (no policy entry for design-critic)
        self.assertNotIn("review_method_gate_corrections", out["post"])

    # ------------------------------------------------------------------
    # T6: idempotency
    # ------------------------------------------------------------------
    def test_T6_idempotent_when_sentinel_present(self):
        trace = {
            "agent": "behavior-verifier",
            "review_method_gate_evaluated": True,
            "review_method_gate_corrections": [
                {"location": "per_behavior_reviews[0]", "review_method": "prereq-unmet"}
            ],
            "per_behavior_reviews": [
                {
                    "behavior_id": "b1",
                    "review_method": "prereq-unmet",
                    "review_evidence": {"final_url": None},
                    "verdict": "SKIPPED",
                }
            ],
        }
        out = run_gate(trace, "behavior-verifier")
        # Sentinel still True
        self.assertTrue(out["post"]["review_method_gate_evaluated"])
        # Corrections array is unchanged (no new entries appended)
        self.assertEqual(len(out["post"]["review_method_gate_corrections"]), 1)
        self.assertIn("already-evaluated", out["stdout"])

    # ------------------------------------------------------------------
    # T7: sentinel always written even with 0 corrections
    # ------------------------------------------------------------------
    def test_T7_sentinel_written_even_when_zero_corrections(self):
        trace = {
            "agent": "behavior-verifier",
            "per_behavior_reviews": [
                {
                    "behavior_id": "b1",
                    "review_method": "prereq-unmet",
                    "review_evidence": {"final_url": None},
                    "verdict": "SKIPPED",  # already correct
                }
            ],
        }
        out = run_gate(trace, "behavior-verifier")
        self.assertTrue(out["post"]["review_method_gate_evaluated"])
        # No corrections array — nothing was wrong
        self.assertNotIn("review_method_gate_corrections", out["post"])

    # ------------------------------------------------------------------
    # Bonus: trace missing review_method (forward-compat)
    # ------------------------------------------------------------------
    def test_forward_compat_trace_without_review_method(self):
        """Old-format traces without review_method must pass through with
        sentinel only."""
        trace = {
            "agent": "behavior-verifier",
            "verdict": "PASS",
            "checks_performed": ["smoke-test"],
            # No per_*_reviews, no top-level review_method
        }
        out = run_gate(trace, "behavior-verifier")
        self.assertTrue(out["post"]["review_method_gate_evaluated"])
        self.assertEqual(out["post"]["verdict"], "PASS")
        self.assertNotIn("review_method_gate_corrections", out["post"])

    # ------------------------------------------------------------------
    # Bonus: missing trace path → exit 1
    # ------------------------------------------------------------------
    def test_missing_trace_returns_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                ["python3", str(GATE_SCRIPT), str(Path(tmp) / "absent.json"), "behavior-verifier"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("trace-missing", result.stdout)


if __name__ == "__main__":
    unittest.main()
