#!/usr/bin/env python3
"""test_render_review_detection_integration.py — end-to-end pin of the
render-review-detection feature for #1013.

Exercises all four reviewer agents' trace-shape contracts against the
shared review-verdict-gate, simulating the full /verify scope=full
runtime path that no CI fixture project exists for. Each scenario
mirrors a realistic problem the original render-review-detection.md
couldn't classify correctly:

  Scenario A (ux-journeyer click-to-login):
    Step 0: click "Log in" from / lands on /login. Pre-PR: source-only
    failure. Post-PR: pass (per-step expected_destination = /login).

  Scenario B (behavior-verifier prereq-unmet):
    Behavior: given "logged-in user". e2e/.auth.json absent. Pre-PR:
    silent failure (verifier ran in demo mode). Post-PR: SKIPPED.

  Scenario C (behavior-verifier product redirect):
    Behavior: entry_route /pricing, redirected to /pricing/individual.
    Pre-PR: would have been FAIL (or unclassified). Post-PR: DEGRADED.

  Scenario D (design-critic backward compat):
    Per-page design-critic trace with review_method=source-only.
    Pre-PR contract: verdict must be unresolved. Post-PR: same — gate
    does NOT touch design-critic (state-3b's merge code does, unchanged).

  Scenario E (4th-reviewer worked example exists in pattern docs):
    The Appendix section exists and references security-attacker as a
    concrete future reviewer that would NOT require pattern changes.

  Scenario F (Caller Policy Table completeness):
    All 4 current callers (design-critic, accessibility-scanner,
    ux-journeyer, behavior-verifier) appear in render-review-detection.md
    Section 7's Caller Policy Table.

Exit 0 on all-pass, 1 on any failure.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
GATE_SCRIPT = ROOT / ".claude/scripts/run-review-verdict-gate.py"
PATTERN_FILE = ROOT / ".claude/patterns/render-review-detection.md"


def gate(trace: dict, agent: str) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{agent}.json"
        path.write_text(json.dumps(trace))
        subprocess.run(
            ["python3", str(GATE_SCRIPT), str(path), agent],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(path.read_text())


class TestRenderReviewDetectionIntegration(unittest.TestCase):
    # ------------------------------------------------------------------
    # Scenario A — ux-journeyer click-to-login is now correctly PASS
    # ------------------------------------------------------------------
    def test_scenario_A_click_to_login_classified_correctly(self):
        """The original failure mode this whole feature exists to fix:
        ux-journeyer step 0 is "click Log in from /" with destination
        /login. Pre-PR, the URL-mismatch gate would fire source-only
        because final_url != source_route. Post-PR, the gate compares
        final_url against expected_destination (/login) — match → pass.
        """
        trace = {
            "agent": "ux-journeyer",
            "verdict": "all pass",
            "per_step_reviews": [
                {
                    "step_index": 0,
                    "source_route": "/",
                    "expected_destination": "/login",
                    "review_method": "rendered-demo",
                    "review_evidence": {
                        "requested_route": "/",
                        "final_url": "http://localhost:3098/login",
                        "expected_destination": "/login",
                    },
                    "status": "pass",
                }
            ],
        }
        post = gate(trace, "ux-journeyer")
        self.assertTrue(post["review_method_gate_evaluated"])
        # Status preserved as pass — gate confirms no correction needed
        self.assertEqual(post["per_step_reviews"][0]["status"], "pass")
        # Top-level verdict NOT forced to blocked (no prereq-unmet step)
        self.assertEqual(post["verdict"], "all pass")
        self.assertNotIn("review_method_gate_corrections", post)

    # ------------------------------------------------------------------
    # Scenario B — behavior-verifier prereq-unmet → SKIPPED, not silent FAIL
    # ------------------------------------------------------------------
    def test_scenario_B_logged_in_behavior_with_no_auth_skipped(self):
        trace = {
            "agent": "behavior-verifier",
            "verdict": "FAIL",  # agent silently mis-emitted FAIL on demo mode
            "per_behavior_reviews": [
                {
                    "behavior_id": "auth-required",
                    "given": "A logged-in user opens the dashboard.",
                    "requires_auth": True,
                    "matched_phrase": "logged-in user",
                    "review_method": "prereq-unmet",
                    "review_evidence": {
                        "requested_route": "/dashboard",
                        "final_url": None,
                        "fallback_reason": "auth.json-absent",
                    },
                    "verdict": "FAIL",  # wrong: gate must correct to SKIPPED
                }
            ],
        }
        post = gate(trace, "behavior-verifier")
        self.assertEqual(post["per_behavior_reviews"][0]["verdict"], "SKIPPED")
        # Correction logged
        self.assertIn("review_method_gate_corrections", post)
        self.assertEqual(post["review_method_gate_corrections"][0]["original_verdict"], "FAIL")
        self.assertEqual(post["review_method_gate_corrections"][0]["corrected_to"], "SKIPPED")

    # ------------------------------------------------------------------
    # Scenario C — product redirect is DEGRADED (not FAIL)
    # ------------------------------------------------------------------
    def test_scenario_C_product_redirect_degraded(self):
        trace = {
            "agent": "behavior-verifier",
            "per_behavior_reviews": [
                {
                    "behavior_id": "pricing-page",
                    "given": "An anonymous visitor opens /pricing.",
                    "requires_auth": False,
                    "matched_phrase": "anonymous visitor",
                    "review_method": "source-only",
                    "review_evidence": {
                        "requested_route": "/pricing",
                        "final_url": "http://localhost:3097/pricing/individual",
                        "fallback_reason": "redirected:/pricing/individual",
                    },
                    "verdict": "FAIL",  # wrong: should be DEGRADED for product redirect
                }
            ],
        }
        post = gate(trace, "behavior-verifier")
        self.assertEqual(post["per_behavior_reviews"][0]["verdict"], "DEGRADED")

    # ------------------------------------------------------------------
    # Scenario D — design-critic backward-compat (gate doesn't touch it)
    # ------------------------------------------------------------------
    def test_scenario_D_design_critic_unaffected_by_shared_gate(self):
        """design-critic's source-only → unresolved enforcement lives in
        state-3b's merge code, not the shared review-verdict-gate. The
        gate must NOT have a policy entry for design-critic that would
        compete with state-3b. This is the regression pin against
        accidentally extending the gate's POLICY to design-critic
        (which would conflict with #1014/#1016 stable contracts)."""
        trace = {
            "agent": "design-critic",
            "verdict": "pass",  # contract-violating but gate ignores
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
        post = gate(trace, "design-critic")
        # Sentinel still written
        self.assertTrue(post["review_method_gate_evaluated"])
        # But verdict NOT touched (state-3b's job)
        self.assertEqual(post["verdict"], "pass")
        self.assertNotIn("review_method_gate_corrections", post)

    # ------------------------------------------------------------------
    # Scenario E — 4th-reviewer extrapolation appendix exists
    # ------------------------------------------------------------------
    def test_scenario_E_4th_reviewer_appendix(self):
        content = PATTERN_FILE.read_text()
        self.assertIn("## Appendix — 4th reviewer worked example", content)
        # The example must be concrete (mention security-attacker) and
        # claim that pattern file changes are bounded
        m = re.search(r"## Appendix.*", content, re.DOTALL)
        appendix = m.group(0)
        self.assertIn("security-attacker", appendix)
        # Must spell out the bounded touch budget
        self.assertTrue(
            re.search(
                r"(zero|one new row|no changes to .*Sections?)",
                appendix,
                re.IGNORECASE,
            ),
            "Appendix must spell out bounded touch budget for adding a 4th reviewer",
        )

    # ------------------------------------------------------------------
    # Scenario F — Caller Policy Table lists all 4 current callers
    # ------------------------------------------------------------------
    def test_scenario_F_caller_policy_table_completeness(self):
        content = PATTERN_FILE.read_text()
        # Locate Section 7
        m = re.search(
            r"## Section 7 — Caller policy table.*?(?=^## )",
            content,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(m, "Section 7 (Caller policy table) missing")
        table = m.group(0)
        for caller in (
            "design-critic",
            "accessibility-scanner",
            "ux-journeyer",
            "behavior-verifier",
        ):
            self.assertIn(caller, table, f"Caller policy table missing {caller}")

    # ------------------------------------------------------------------
    # Scenario G — Sentinel idempotency across multiple gate calls
    # ------------------------------------------------------------------
    def test_scenario_G_idempotent_across_multiple_invocations(self):
        """Running the gate twice on the same trace must not double-log
        corrections. This protects against retry loops in state ACTIONS."""
        trace = {
            "agent": "behavior-verifier",
            "per_behavior_reviews": [
                {
                    "behavior_id": "b1",
                    "review_method": "prereq-unmet",
                    "review_evidence": {"final_url": None},
                    "verdict": "FAIL",
                }
            ],
        }
        post1 = gate(trace, "behavior-verifier")
        # Re-feed post1 through the gate — idempotency
        post2 = gate(post1, "behavior-verifier")
        self.assertEqual(
            len(post1["review_method_gate_corrections"]),
            len(post2["review_method_gate_corrections"]),
            "Re-running gate doubled corrections — not idempotent",
        )
        self.assertEqual(post1["per_behavior_reviews"][0]["verdict"], "SKIPPED")
        self.assertEqual(post2["per_behavior_reviews"][0]["verdict"], "SKIPPED")


if __name__ == "__main__":
    unittest.main()
