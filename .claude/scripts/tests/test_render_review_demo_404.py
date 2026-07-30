#!/usr/bin/env python3
"""test_render_review_demo_404.py — coverage for the DEMO_MODE fixture
short-circuit branch added to render-review-detection.md (#1042 / Session C).

The branch fires iff ALL three are true:
  1. HTTP status from initial goto() == 404
  2. demo_mode == True
  3. route_pattern matches /\\[[^\\]]+\\]/  (any [segment] substring)

When all three hold, classify source-only with
fallback_reason="demo-mode-fixture-short-circuit". Otherwise fall through
to the existing URL-mismatch / auth-redirect branches.

Also asserts the pattern file contains the branch implementation (structural
drift guard).
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_render_review_detection import classify_py  # noqa: E402


PATTERN_FILE = ROOT / ".claude/patterns/render-review-detection.md"


class TestDemoMode404Branch(unittest.TestCase):
    """Exercise the three-condition classifier."""

    def test_all_three_conditions_fire_dynamic_id(self):
        method, ev = classify_py(
            requested_route="/quote/00000000-0000-0000-0000-000000000000",
            final_url="http://localhost:3099/quote/00000000-0000-0000-0000-000000000000",
            final_status=404,
            demo_mode=True,
            route_pattern="/quote/[id]",
        )
        self.assertEqual(method, "source-only")
        self.assertEqual(ev["fallback_reason"], "demo-mode-fixture-short-circuit")
        self.assertEqual(ev["final_status"], 404)
        self.assertEqual(ev["route_pattern"], "/quote/[id]")

    def test_status_200_falls_through(self):
        method, ev = classify_py(
            requested_route="/quote/00000000-0000-0000-0000-000000000000",
            final_url="http://localhost:3099/quote/00000000-0000-0000-0000-000000000000",
            final_status=200,
            demo_mode=True,
            route_pattern="/quote/[id]",
        )
        self.assertEqual(method, "rendered-demo")
        self.assertIsNone(ev["fallback_reason"])

    def test_demo_mode_off_falls_through(self):
        # Production 404 on dynamic route stays source-only via URL-mismatch
        # only when URL actually diverges. Here URL matches, status is 404,
        # but demo_mode=False → we keep legacy behavior (rendered-demo).
        # The legacy classifier does NOT inspect status.
        method, ev = classify_py(
            requested_route="/quote/00000000-0000-0000-0000-000000000000",
            final_url="http://localhost:3099/quote/00000000-0000-0000-0000-000000000000",
            final_status=404,
            demo_mode=False,
            route_pattern="/quote/[id]",
        )
        self.assertEqual(method, "rendered-demo")
        self.assertNotEqual(ev["fallback_reason"], "demo-mode-fixture-short-circuit")

    def test_static_route_falls_through(self):
        # 404 on static route: demo_mode on + no dynamic segment → legacy logic
        method, ev = classify_py(
            requested_route="/pricing",
            final_url="http://localhost:3099/pricing",
            final_status=404,
            demo_mode=True,
            route_pattern="/pricing",
        )
        self.assertNotEqual(ev["fallback_reason"], "demo-mode-fixture-short-circuit")

    def test_multiple_segments(self):
        method, ev = classify_py(
            requested_route="/team/demo-fixture-org/member/00000000-0000-0000-0000-000000000000",
            final_url="http://localhost:3099/team/demo-fixture-org/member/00000000-0000-0000-0000-000000000000",
            final_status=404,
            demo_mode=True,
            route_pattern="/team/[org]/member/[id]",
        )
        self.assertEqual(method, "source-only")
        self.assertEqual(ev["fallback_reason"], "demo-mode-fixture-short-circuit")

    def test_catchall_bracket_matches(self):
        method, ev = classify_py(
            requested_route="/docs/demo-fixture-slug",
            final_url="http://localhost:3099/docs/demo-fixture-slug",
            final_status=404,
            demo_mode=True,
            route_pattern="/docs/[[...slug]]",
        )
        self.assertEqual(method, "source-only")
        self.assertEqual(ev["fallback_reason"], "demo-mode-fixture-short-circuit")

    def test_nav_error_takes_priority(self):
        # nav_error should return "unknown" regardless of 404/demo_mode
        method, ev = classify_py(
            requested_route="/quote/x",
            final_url=None,
            nav_error="timeout",
            final_status=404,
            demo_mode=True,
            route_pattern="/quote/[id]",
        )
        self.assertEqual(method, "unknown")
        self.assertIn("navigation-failed", ev["fallback_reason"])


class TestPatternFileDrift(unittest.TestCase):
    """Structural guards — the pattern .md must contain the branch code."""

    @classmethod
    def setUpClass(cls):
        cls.text = PATTERN_FILE.read_text()

    def test_branch_literal_fallback_reason(self):
        self.assertIn(
            'fallbackReason = "demo-mode-fixture-short-circuit"',
            self.text,
            "DEMO_MODE short-circuit branch missing from pattern file",
        )

    def test_response_status_capture(self):
        # Section 2 must capture response.status()
        self.assertIn("response.status()", self.text)
        self.assertIn("finalStatus", self.text)

    def test_has_dynamic_segment_regex(self):
        # The bracket-detection regex must be present and match [seg]
        self.assertRegex(
            self.text,
            r"hasDynamicSegment\s*=\s*/\\\[\[\^\\\]\]\+\\\]/\.test",
        )

    def test_route_pattern_opts_documented(self):
        # Inputs section must describe route_pattern + demo_mode
        self.assertIn("`route_pattern`", self.text)
        self.assertIn("`demo_mode`", self.text)

    def test_final_status_in_return_shape(self):
        # Section 5 must surface final_status + route_pattern in evidence
        self.assertIn("final_status: finalStatus", self.text)
        self.assertIn("route_pattern: opts.route_pattern", self.text)


if __name__ == "__main__":
    unittest.main()
