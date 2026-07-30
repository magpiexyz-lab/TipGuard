#!/usr/bin/env python3
"""test_behavior_verifier_auth_semantics.py — pin behavior-verifier's
auth-aware per-behavior render-review classification.

Strategy
--------
behavior-verifier consumes:
  - .claude/patterns/given-auth-matcher.md (requires_auth function)
  - .claude/patterns/render-review-detection.md (renderReviewDetect)
  - .claude/patterns/review-verdict-gate.md (POLICY for behavior-verifier)

This test verifies via static structural analysis + Python-port
behavior tests that:

  T1 logged-in given + missing auth.json → SKIPPED (NOT FAIL)
  T2 anonymous given + no auth dependency → optional, no skip
  T3 unknown given (fail-closed) → required + unmatched_given_phrase set
  T4 product redirect (entry /pricing → /pricing/individual) → DEGRADED
  T5 auth redirect (entry /dashboard → /login) → FAIL [B3]

Behavioral verification (real Playwright + actual Supabase login)
deferred to /verify end-to-end runs against a sample fixture project.

Exit 0 on all-pass, 1 on any failure.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[3]
AGENT_FILE = ROOT / ".claude/agents/behavior-verifier.md"
PROC_FILE = ROOT / ".claude/procedures/behavior-verifier.md"
GATE_SCRIPT = ROOT / ".claude/scripts/run-review-verdict-gate.py"
MATCHER_FILE = ROOT / ".claude/patterns/given-auth-matcher.md"


# Same Python port of requires_auth as test_given_auth_matcher.py uses
def extract_python_port() -> str:
    content = MATCHER_FILE.read_text()
    after = content.split("## Python port", 1)[1]
    m = re.search(r"```python\n(.*?)\n```", after, re.DOTALL)
    return m.group(1)


def requires_auth(given: str) -> dict:
    port = extract_python_port()
    script = port + textwrap.dedent(
        f"""

        import json
        print(json.dumps(requires_auth({given!r})))
        """
    )
    result = subprocess.run(
        ["python3", "-c", script],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout.strip())


def gate(trace: dict) -> dict:
    """Run the shared gate against a behavior-verifier trace."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "behavior-verifier.json"
        path.write_text(json.dumps(trace))
        subprocess.run(
            ["python3", str(GATE_SCRIPT), str(path), "behavior-verifier"],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(path.read_text())


def derive_verdict(review_method: str, final_url: str | None) -> str:
    """Mirror the Render Review Policy Table in behavior-verifier.md.
    Used to construct test fixtures with realistic verdicts before passing
    them to the gate. The gate auto-corrects mismatches; this helper just
    saves duplication in test setup."""
    if review_method in ("rendered-authed", "rendered-demo"):
        return "PASS"
    if review_method == "prereq-unmet":
        return "SKIPPED"
    if review_method == "unknown":
        return "FAIL"
    if review_method == "source-only":
        try:
            path = urlparse(final_url).path if final_url else ""
        except Exception:
            path = ""
        AUTH_PATHS = {"/login", "/signup", "/auth/callback", "/auth/reset-password"}
        return "FAIL" if path in AUTH_PATHS else "DEGRADED"
    return "FAIL"


class TestBehaviorVerifierAuthSemantics(unittest.TestCase):
    # ------------------------------------------------------------------
    # T1: logged-in user + missing auth → SKIPPED
    # ------------------------------------------------------------------
    def test_T1_logged_in_user_missing_auth_skipped(self):
        auth = requires_auth("A logged-in user opens the dashboard.")
        self.assertTrue(auth["result"])
        self.assertEqual(auth["matched_phrase"], "logged-in user")

        # Simulate the trace the agent would write when prereq is unmet
        trace = {
            "agent": "behavior-verifier",
            "verdict": "PASS",  # would be wrong without gate correction
            "per_behavior_reviews": [
                {
                    "behavior_id": "b1",
                    "given": "A logged-in user opens the dashboard.",
                    "requires_auth": True,
                    "matched_phrase": "logged-in user",
                    "review_method": "prereq-unmet",
                    "review_evidence": {
                        "requested_route": "/dashboard",
                        "final_url": None,
                        "fallback_reason": "auth.json-absent",
                        "expected_destination": "/dashboard",
                    },
                    "verdict": "FAIL",  # agent emitted wrong verdict
                }
            ],
        }
        post = gate(trace)
        self.assertEqual(post["per_behavior_reviews"][0]["verdict"], "SKIPPED")
        # Correction logged
        corrections = post["review_method_gate_corrections"]
        self.assertEqual(corrections[0]["original_verdict"], "FAIL")
        self.assertEqual(corrections[0]["corrected_to"], "SKIPPED")

    # ------------------------------------------------------------------
    # T2: anonymous given → no auth, no skip
    # ------------------------------------------------------------------
    def test_T2_anonymous_visitor_optional_proceeds(self):
        auth = requires_auth("An anonymous visitor lands on /pricing.")
        self.assertFalse(auth["result"])
        self.assertEqual(auth["matched_phrase"], "anonymous visitor")
        # auth_requirement would be "optional" → no prereq-unmet possible

    # ------------------------------------------------------------------
    # T3: unknown given → fail-closed required + unmatched diagnostic
    # ------------------------------------------------------------------
    def test_T3_unknown_given_fail_closed_to_required(self):
        auth = requires_auth("After onboarding completes.")
        self.assertTrue(auth["result"])  # fail-closed
        self.assertTrue(auth["unmatched"])
        self.assertIsNone(auth["matched_phrase"])

        trace = {
            "agent": "behavior-verifier",
            "verdict": "FAIL",
            "unmatched_given_phrase": "After onboarding completes.",
            "per_behavior_reviews": [
                {
                    "behavior_id": "b3",
                    "given": "After onboarding completes.",
                    "requires_auth": True,
                    "matched_phrase": None,
                    "unmatched_given_phrase": "After onboarding completes.",
                    "review_method": "prereq-unmet",
                    "review_evidence": {
                        "requested_route": "/onboarding",
                        "final_url": None,
                        "fallback_reason": "auth.json-absent",
                    },
                    "verdict": derive_verdict("prereq-unmet", None),
                }
            ],
        }
        post = gate(trace)
        # Verdict already correct (SKIPPED), gate writes sentinel
        self.assertEqual(post["per_behavior_reviews"][0]["verdict"], "SKIPPED")
        self.assertTrue(post["review_method_gate_evaluated"])
        # Diagnostic preserved
        self.assertEqual(post["unmatched_given_phrase"], "After onboarding completes.")

    # ------------------------------------------------------------------
    # T4: product-level redirect → DEGRADED (not FAIL)
    # ------------------------------------------------------------------
    def test_T4_product_redirect_degraded_not_fail(self):
        trace = {
            "agent": "behavior-verifier",
            "per_behavior_reviews": [
                {
                    "behavior_id": "b4",
                    "given": "An anonymous visitor opens /pricing.",
                    "requires_auth": False,
                    "matched_phrase": "anonymous visitor",
                    "review_method": "source-only",
                    "review_evidence": {
                        "requested_route": "/pricing",
                        "final_url": "http://localhost:3097/pricing/individual",
                        "fallback_reason": "redirected:/pricing/individual",
                    },
                    "verdict": "FAIL",  # wrong: should be DEGRADED
                }
            ],
        }
        post = gate(trace)
        self.assertEqual(post["per_behavior_reviews"][0]["verdict"], "DEGRADED")

    # ------------------------------------------------------------------
    # T5: auth redirect on expected dashboard → FAIL [B3]
    # ------------------------------------------------------------------
    def test_T5_auth_redirect_on_expected_dashboard_FAIL(self):
        trace = {
            "agent": "behavior-verifier",
            "per_behavior_reviews": [
                {
                    "behavior_id": "b5",
                    "given": "A logged-in user opens the dashboard.",
                    "requires_auth": True,
                    "matched_phrase": "logged-in user",
                    "review_method": "source-only",
                    "review_evidence": {
                        "requested_route": "/dashboard",
                        "final_url": "http://localhost:3097/login",
                        "fallback_reason": "redirected-to-auth-route",
                    },
                    "verdict": "DEGRADED",  # wrong: should be FAIL (auth redirect on expected route)
                }
            ],
        }
        post = gate(trace)
        self.assertEqual(post["per_behavior_reviews"][0]["verdict"], "FAIL")

    # ------------------------------------------------------------------
    # Structural pins
    # ------------------------------------------------------------------
    def test_agent_documents_per_behavior_reviews(self):
        content = AGENT_FILE.read_text()
        self.assertIn("per_behavior_reviews", content)
        self.assertIn("Per-Behavior Render Review Policy Table", content)
        # All review_method values mentioned
        for rm in ("rendered-authed", "rendered-demo", "source-only", "unknown", "prereq-unmet"):
            self.assertIn(rm, content)

    def test_procedure_invokes_requires_auth(self):
        """The procedure must invoke the canonical requires_auth/requiresAuth
        function from given-auth-matcher.md. Accept either case (Python
        snake_case for procedures that shell out, JS camelCase for
        procedures that inline the function into a Playwright script)."""
        content = PROC_FILE.read_text()
        self.assertTrue(
            "requires_auth" in content or "requiresAuth" in content,
            "Procedure must invoke requires_auth or requiresAuth (canonical phrase classifier)",
        )
        self.assertIn("given-auth-matcher", content)

    def test_procedure_invokes_render_review_detect(self):
        """Same casing-flexibility for renderReviewDetect/render_review_detect."""
        content = PROC_FILE.read_text()
        self.assertTrue(
            "renderReviewDetect" in content or "render_review_detect" in content,
            "Procedure must invoke renderReviewDetect (combined wrapper from render-review-detection.md)",
        )

    def test_procedure_uses_firstAuthGatedSeen(self):
        """R2-A3: behavior-verifier loop must use firstAuthGatedSeen, not i===0."""
        content = PROC_FILE.read_text()
        self.assertIn("firstAuthGatedSeen", content)
        # Negative pin
        self.assertNotRegex(
            content,
            r"is_first_page\s*[:=]\s*\(?\s*i\s*===?\s*0",
            "Procedure uses i===0 for is_first_page — drift from firstAuthGatedSeen pattern (R2-A3)",
        )

    def test_agent_verdict_vocabulary_includes_skipped_and_degraded(self):
        content = AGENT_FILE.read_text()
        # Both verdicts must appear in the Overall Verdict table
        m = re.search(r"## Overall Verdict(.*?)(?=^## |\Z)", content, re.DOTALL | re.MULTILINE)
        self.assertIsNotNone(m)
        section = m.group(1)
        self.assertIn("SKIPPED", section)
        self.assertIn("DEGRADED", section)


if __name__ == "__main__":
    unittest.main()
