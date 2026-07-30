#!/usr/bin/env python3
"""test_ux_journeyer_click_vs_goto.py — pin the design contract that
ux-journeyer uses click-driven navigation + classifyCurrentPage, NOT
goto-driven navigation.

Background
----------
The original render-review-detection.md design used `page.goto(route)` +
URL-mismatch comparison. ux-journeyer cannot use that path because:
  - Clicking a CTA may dynamically navigate via JavaScript (e.g., A/B
    rewrite from /login to /signup based on a feature flag)
  - The point of ux-journeyer is to verify the CLICK leads where it
    should, not that the static href would
  - goto-then-classify would short-circuit the click and miss the
    rewrite, producing a false PASS

PR 1 introduced `classifyCurrentPage` (Section 6.3 of
render-review-detection.md) for this exact purpose. PR 3 wired
ux-journeyer to use it.

Coverage
--------
This test verifies via static structural analysis of the procedure +
agent files that:

  T1 ux-journeyer.md procedure mentions click-driven navigation +
     classifyCurrentPage explicitly, and does NOT use page.goto inside
     the per-step loop (only at journey entry).

  T2 ux-journeyer.md agent file declares the per_step_reviews trace
     extension and the firstAuthGatedSeen pattern.

  T3 The Render Review Policy Table in ux-journeyer.md agent file lists
     every review_method emitted by render-review-detection.md.

  T4 The agent file documents anonymous suppression of
     demo-mode-bypass-failed (R2-A3 fix).

Behavioral verification (real Playwright + dynamic href rewrite test)
is deferred to /verify end-to-end runs against a sample fixture project,
since CI doesn't have a sample web-app handy.

Exit 0 on all-pass, 1 on any failure.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PROC_FILE = ROOT / ".claude/procedures/ux-journeyer.md"
AGENT_FILE = ROOT / ".claude/agents/ux-journeyer.md"


class TestUxJourneyerClickContract(unittest.TestCase):
    def setUp(self):
        self.proc = PROC_FILE.read_text()
        self.agent = AGENT_FILE.read_text()

    # ------------------------------------------------------------------
    # T1: procedure uses click + classifyCurrentPage, no goto in loop
    # ------------------------------------------------------------------
    def test_T1_procedure_mentions_classifyCurrentPage(self):
        self.assertIn(
            "classifyCurrentPage",
            self.proc,
            "ux-journeyer procedure must invoke classifyCurrentPage (per-step classification primitive)",
        )

    def test_T1_procedure_warns_against_page_goto_in_loop(self):
        """The per-step loop section must explicitly say "NOT page.goto"
        or equivalent. Find Section 5 (Navigate the Golden Path) and
        check the per-step loop block.
        """
        # Anchor heading to start-of-line (^) so the regex doesn't match
        # the literal string "### 5. Navigate the Golden Path" embedded
        # inside the file's top coherence-allow HTML comment scope list,
        # which would otherwise capture the empty span from line 1 to
        # line 10 (### 1. Prerequisite Check).
        m = re.search(
            r"^### 5\. Navigate the Golden Path(.*?)(?=^### |\Z)",
            self.proc,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(m, "Could not locate Section 5 in procedure")
        section = m.group(1)
        # Must explicitly call out click-driven navigation
        self.assertTrue(
            re.search(r"native click.*NOT.*page\.goto", section, re.IGNORECASE | re.DOTALL),
            "Section 5 must spell out 'native click — NOT page.goto' so the contract is unambiguous",
        )
        self.assertTrue(
            re.search(r"click[- ]driven navigation", section, re.IGNORECASE),
            "Section 5 must use the term 'click-driven navigation'",
        )

    def test_T1_procedure_has_setupAuthContext_at_start(self):
        """Journey entry uses setupAuthContext to handle prereq-unmet correctly."""
        self.assertIn("setupAuthContext", self.proc)
        # And handles the prereq-unmet early-return
        self.assertIn("prereq-unmet", self.proc)

    # ------------------------------------------------------------------
    # T2: agent file declares per_step_reviews + firstAuthGatedSeen
    # ------------------------------------------------------------------
    def test_T2_agent_trace_includes_per_step_reviews(self):
        self.assertIn("per_step_reviews", self.agent)

    def test_T2_agent_uses_firstAuthGatedSeen_pattern(self):
        """The Render Review Policy Table or Halt Conditions section must
        reference firstAuthGatedSeen, NOT i === 0."""
        self.assertIn(
            "firstAuthGatedSeen",
            self.agent,
            "Agent must reference firstAuthGatedSeen (NOT i === 0) per R2-A3",
        )

    def test_T2_procedure_uses_firstAuthGatedSeen_in_loop(self):
        """The per-step loop in the procedure must compute is_first_page
        via firstAuthGatedSeen, not via index."""
        # Find the per-step loop and assert it references firstAuthGatedSeen
        self.assertIn("firstAuthGatedSeen", self.proc)
        # Negative: must NOT use `i === 0` as is_first_page determinant
        self.assertNotRegex(
            self.proc,
            r"is_first_page\s*[:=]\s*\(?\s*i\s*===?\s*0",
            "Procedure uses i===0 for is_first_page — that drifts from accessibility-scanner's firstAuthGatedSeen pattern (R2-A3)",
        )

    # ------------------------------------------------------------------
    # T3: Render Review Policy Table lists every review_method
    # ------------------------------------------------------------------
    def test_T3_policy_table_covers_all_review_methods(self):
        """The Render Review Policy Table section must enumerate every
        possible review_method value emitted by render-review-detection.md."""
        m = re.search(
            r"^## Render Review Policy Table(.*?)(?=^## |\Z)",
            self.agent,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(m, "Render Review Policy Table section missing from agent file")
        table = m.group(1)
        # Every review_method must appear in the table
        for rm in ("rendered-authed", "rendered-demo", "source-only", "unknown", "prereq-unmet"):
            self.assertIn(rm, table, f"Policy table missing review_method={rm}")

    def test_T3_policy_table_has_AUTH_PATHS_branching(self):
        """source-only must split on final_url ∈ AUTH_PATHS vs not (R2-A1
        + AUTH_PATHS-aware classification — same logic as
        review-verdict-gate.md POLICY)."""
        m = re.search(
            r"^## Render Review Policy Table(.*?)(?=^## |\Z)",
            self.agent,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(m)
        table = m.group(1)
        # Look for explicit AUTH_PATHS distinction or auth-vs-non-auth branching
        # in the source-only rows
        self.assertIn("AUTH_PATHS", table, "Policy table must reference AUTH_PATHS for source-only branching")

    # ------------------------------------------------------------------
    # T4: anonymous suppression of demo-mode-bypass-failed documented
    # ------------------------------------------------------------------
    def test_T4_anonymous_suppression_documented(self):
        """The agent file must document that anonymous journeys never fire
        demo-mode-bypass-failed (R2-A3 fix). Either via direct mention or
        via reference to render-review-detection.md Section 3 suppression."""
        # Combine procedure + agent for the search
        combined = self.proc + "\n" + self.agent
        self.assertTrue(
            re.search(
                r"anonymous.*(suppress|never).*demo-mode-bypass-failed",
                combined,
                re.IGNORECASE | re.DOTALL,
            )
            or re.search(
                r"demo-mode-bypass-failed.*(suppress|never).*anonymous",
                combined,
                re.IGNORECASE | re.DOTALL,
            ),
            "ux-journeyer files must document that anonymous journeys suppress demo-mode-bypass-failed (R2-A3)",
        )


if __name__ == "__main__":
    unittest.main()
