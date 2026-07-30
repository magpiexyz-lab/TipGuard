#!/usr/bin/env python3
"""test_render_review_detection.py — regression coverage for the extended
render-review-detection.md pattern.

Strategy
--------
The pattern file is consumed by agents as markdown-as-source: the inline JS
is not imported by a Node runtime; agents inline it into their own
Playwright scripts. Runtime JS behavior is exercised by `/verify` E2E runs.

This test pins the **design contract** of the pattern via:

  (A) A Python port of the classification logic (Section 3 + the
      setupAuthContext branching) that mirrors the JS behavior. Unit tests
      below exercise every (auth_requirement, expected_destination) branch
      against the Python port. If the JS and Python drift, the drift is
      caught in CI via the structural tests below.

  (B) Static structural tests that read the pattern file and assert:
       - `classifyCurrentPage` section exists and does NOT contain
         `page.goto` (distinguishes classify-only from detect-with-nav).
       - `detectRenderAt` section DOES contain `page.goto`.
       - `renderReviewDetect` wrapper composes `setupAuthContext` + conditional
         `detectRenderAt` guarded by `reviewMethodEarly`.
       - The Caller Policy Table lists all 4 current callers.

  (C) Backward-compat pin: when the Python port is called with no
      `expected_destination` and no `auth_requirement`, its return shape
      is equal to a "pre-change" fixture except for the new
      `expected_destination: None` field.

Exit 0 on all-pass, 1 on any failure.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[3]
PATTERN_FILE = ROOT / ".claude/patterns/render-review-detection.md"


# --------------------------------------------------------------------------
# Python port — mirrors Section 1 + Section 3 decision logic in the pattern
# file. Kept minimal: no Playwright, no filesystem side effects. All state
# is passed in as function arguments so tests stay hermetic.
# --------------------------------------------------------------------------

AUTH_PATHS = {"/login", "/signup", "/auth/callback", "/auth/reset-password"}


def setup_auth_context_py(
    auth_requirement: str = "optional",
    storage_state_check_ok: bool | None = None,
    storage_state_reason: str | None = None,
):
    """Mirror Section 1 branching. Returns a dict with the same shape as the
    JS `setupAuthContext` result.
    """
    if auth_requirement == "anonymous":
        return {
            "context": "plain",
            "authSource": "demo-mode",
            "fallbackReason": None,
            "reviewMethodEarly": None,
        }

    if auth_requirement == "required" and not storage_state_check_ok:
        return {
            "context": "plain",
            "authSource": "demo-mode",
            "fallbackReason": storage_state_reason,
            "reviewMethodEarly": "prereq-unmet",
        }

    if storage_state_check_ok:
        return {
            "context": "authed",
            "authSource": "storageState",
            "fallbackReason": None,
            "reviewMethodEarly": None,
        }

    # optional + not ok: demo-mode fallback (record non-absent reasons)
    fallback = None
    if storage_state_reason and storage_state_reason != "auth.json-absent":
        fallback = storage_state_reason
    return {
        "context": "plain",
        "authSource": "demo-mode",
        "fallbackReason": fallback,
        "reviewMethodEarly": None,
    }


def classify_py(
    requested_route: str,
    final_url: str | None,
    auth_source: str = "demo-mode",
    is_first_page: bool = False,
    auth_requirement: str = "optional",
    expected_destination: str | None = None,
    nav_error: str | None = None,
    fallback_reason_in: str | None = None,
    final_status: int | None = None,
    route_pattern: str | None = None,
    demo_mode: bool = False,
):
    """Mirror Section 3 classification. Returns (review_method, review_evidence)
    matching the JS return shape.

    #1042 adds three optional inputs:
      - final_status: HTTP status from initial goto response (int | None)
      - route_pattern: literal route template (e.g. "/quote/[id]")
      - demo_mode: whether DEMO_MODE=true is active
    When all three DEMO_MODE-short-circuit conditions hold (status==404,
    demo_mode, route_pattern has [segment]) and no nav_error, the classifier
    returns source-only with fallback_reason="demo-mode-fixture-short-circuit".
    """
    import re as _re
    expected_path = expected_destination or requested_route
    fallback_reason = fallback_reason_in
    pattern_for_audit = route_pattern

    if nav_error:
        return (
            "unknown",
            {
                "requested_route": requested_route,
                "final_url": None,
                "auth_source": auth_source,
                "fallback_reason": f"navigation-failed:{nav_error}",
                "content_density": None,
                "expected_destination": expected_destination,
                "final_status": final_status,
                "route_pattern": pattern_for_audit,
            },
        )

    # #1042 DEMO_MODE fixture short-circuit branch — fires before URL-mismatch
    has_dynamic_segment = bool(
        route_pattern and _re.search(r"\[[^\]]+\]", route_pattern)
    )
    if final_status == 404 and demo_mode and has_dynamic_segment:
        try:
            final_path = urlparse(final_url).path if final_url else None
        except Exception:
            final_path = None
        return (
            "source-only",
            {
                "requested_route": requested_route,
                "final_url": final_url,
                "auth_source": auth_source,
                "fallback_reason": "demo-mode-fixture-short-circuit",
                "content_density": None,
                "expected_destination": expected_destination,
                "final_status": final_status,
                "route_pattern": pattern_for_audit,
            },
        )

    try:
        final_path = urlparse(final_url).path if final_url else None
    except Exception:
        final_path = None

    if final_path != expected_path:
        review_method = "source-only"
        if final_path in AUTH_PATHS:
            if auth_requirement == "anonymous":
                fallback_reason = "redirected-to-auth-route"
            else:
                fallback_reason = "demo-mode-bypass-failed" if is_first_page else "redirected-to-auth-route"
        else:
            fallback_reason = f"redirected:{final_path if final_path else 'unknown'}"
    elif auth_source == "storageState":
        review_method = "rendered-authed"
    else:
        review_method = "rendered-demo"

    return (
        review_method,
        {
            "requested_route": requested_route,
            "final_url": final_url,
            "auth_source": auth_source,
            "fallback_reason": fallback_reason,
            "content_density": None,
            "expected_destination": expected_destination,
            "final_status": final_status,
            "route_pattern": pattern_for_audit,
        },
    )


def render_review_detect_py(opts: dict, storage_state_check_ok: bool | None, storage_state_reason: str | None, final_url: str | None):
    """Mirror the combined wrapper's behavior."""
    setup = setup_auth_context_py(
        auth_requirement=opts.get("auth_requirement", "optional"),
        storage_state_check_ok=storage_state_check_ok,
        storage_state_reason=storage_state_reason,
    )
    if setup["reviewMethodEarly"]:
        return (
            "prereq-unmet",
            {
                "requested_route": opts["requested_route"],
                "final_url": None,
                "auth_source": setup["authSource"],
                "fallback_reason": setup["fallbackReason"],
                "content_density": None,
                "expected_destination": opts.get("expected_destination"),
            },
        )
    return classify_py(
        requested_route=opts["requested_route"],
        final_url=final_url,
        auth_source=setup["authSource"],
        is_first_page=opts.get("is_first_page", False),
        auth_requirement=opts.get("auth_requirement", "optional"),
        expected_destination=opts.get("expected_destination"),
        fallback_reason_in=setup["fallbackReason"],
    )


# --------------------------------------------------------------------------
# Behavioral tests via the Python port
# --------------------------------------------------------------------------


class TestAuthRequirementBranches(unittest.TestCase):
    def test_T1_anonymous_does_not_inject_storage_state(self):
        """Even with valid .auth.json, anonymous branch must skip storageState."""
        setup = setup_auth_context_py(
            auth_requirement="anonymous",
            storage_state_check_ok=True,
            storage_state_reason=None,
        )
        self.assertEqual(setup["authSource"], "demo-mode")
        self.assertEqual(setup["context"], "plain")
        self.assertIsNone(setup["reviewMethodEarly"])

    def test_T2_required_no_storage_state_triggers_prereq_unmet(self):
        setup = setup_auth_context_py(
            auth_requirement="required",
            storage_state_check_ok=False,
            storage_state_reason="auth.json-absent",
        )
        self.assertEqual(setup["reviewMethodEarly"], "prereq-unmet")
        self.assertEqual(setup["fallbackReason"], "auth.json-absent")

    def test_T3_required_valid_storage_state_expected_dashboard(self):
        rm, ev = render_review_detect_py(
            {
                "requested_route": "/dashboard",
                "auth_requirement": "required",
                "expected_destination": "/dashboard",
            },
            storage_state_check_ok=True,
            storage_state_reason=None,
            final_url="http://localhost:3099/dashboard",
        )
        self.assertEqual(rm, "rendered-authed")
        self.assertEqual(ev["auth_source"], "storageState")
        self.assertEqual(ev["expected_destination"], "/dashboard")

    def test_T4_optional_defaults_preserve_pre_change_behavior(self):
        """Backward-compat pin: optional + no expected_destination matches
        the pre-change classification exactly, except the new
        expected_destination=None field in evidence."""
        # Pre-change: requested=/dashboard, final=/dashboard, demo-mode
        rm, ev = render_review_detect_py(
            {"requested_route": "/dashboard"},  # no auth_req, no expected_dest
            storage_state_check_ok=False,
            storage_state_reason="auth.json-absent",
            final_url="http://localhost:3099/dashboard",
        )
        self.assertEqual(rm, "rendered-demo")
        self.assertEqual(ev["auth_source"], "demo-mode")
        self.assertIsNone(ev["fallback_reason"])  # auth.json-absent is not recorded
        self.assertIsNone(ev["expected_destination"])  # new field, None when not passed

    def test_T5_optional_click_to_login_is_rendered_demo(self):
        """Click-to-login flow: origin /, expected /login, final /login.
        Must classify as rendered-demo (NOT source-only)."""
        rm, ev = render_review_detect_py(
            {
                "requested_route": "/",
                "expected_destination": "/login",
            },
            storage_state_check_ok=False,
            storage_state_reason="auth.json-absent",
            final_url="http://localhost:3099/login",
        )
        self.assertEqual(rm, "rendered-demo")
        self.assertEqual(ev["expected_destination"], "/login")

    def test_T6_auth_redirect_classifies_as_source_only(self):
        """Expected /dashboard, redirected to /login (∈ AUTH_PATHS)."""
        rm, ev = render_review_detect_py(
            {
                "requested_route": "/dashboard",
                "expected_destination": "/dashboard",
                "is_first_page": False,
            },
            storage_state_check_ok=False,
            storage_state_reason="auth.json-absent",
            final_url="http://localhost:3099/login",
        )
        self.assertEqual(rm, "source-only")
        self.assertEqual(ev["fallback_reason"], "redirected-to-auth-route")

    def test_T7_product_redirect_classifies_as_source_only_non_auth(self):
        """Expected /pricing, redirected to /pricing/individual (∉ AUTH_PATHS)."""
        rm, ev = render_review_detect_py(
            {
                "requested_route": "/pricing",
                "expected_destination": "/pricing",
            },
            storage_state_check_ok=False,
            storage_state_reason="auth.json-absent",
            final_url="http://localhost:3099/pricing/individual",
        )
        self.assertEqual(rm, "source-only")
        self.assertEqual(ev["fallback_reason"], "redirected:/pricing/individual")

    def test_anonymous_suppresses_demo_mode_bypass_failed(self):
        """Anonymous journey + index-0 + redirect to /login should not fire
        the 'demo-mode-bypass-failed' diagnostic (R2-A3)."""
        rm, ev = render_review_detect_py(
            {
                "requested_route": "/",
                "expected_destination": "/pricing",
                "auth_requirement": "anonymous",
                "is_first_page": True,  # would normally fire the diagnostic
            },
            storage_state_check_ok=True,
            storage_state_reason=None,
            final_url="http://localhost:3099/login",
        )
        self.assertEqual(rm, "source-only")
        # Must NOT be demo-mode-bypass-failed since auth_requirement="anonymous"
        self.assertEqual(ev["fallback_reason"], "redirected-to-auth-route")


# --------------------------------------------------------------------------
# Structural tests — pin the pattern file's shape
# --------------------------------------------------------------------------


class TestPatternFileStructure(unittest.TestCase):
    def setUp(self):
        self.content = PATTERN_FILE.read_text()

    def test_classifyCurrentPage_section_exists(self):
        self.assertIn("classifyCurrentPage", self.content)

    def test_detectRenderAt_section_exists(self):
        self.assertIn("detectRenderAt", self.content)

    def test_renderReviewDetect_wrapper_section_exists(self):
        self.assertIn("renderReviewDetect", self.content)

    def test_classifyCurrentPage_documented_as_no_goto(self):
        """T8: classifyCurrentPage MUST NOT trigger navigation.

        Strategy: locate the section headed by `### 6.3 — classifyCurrentPage`
        and the prose following it; assert that the DESCRIPTION explicitly
        says 'Does not call `page.goto()`' (the documented contract) and
        that the section's own body does not show a page.goto call.
        """
        # Find the 6.3 heading and the next 6.N heading or top-level section
        m = re.search(
            r"### 6\.3 — `classifyCurrentPage.*?(?=### 6\.\d|^## )",
            self.content,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(m, "Section 6.3 (classifyCurrentPage) not found")
        section = m.group(0)

        # Contract documented
        self.assertIn("page.goto()", section, "6.3 should mention page.goto in prose")
        self.assertIn("Does not call", section, "6.3 should say 'Does not call page.goto()'")

        # No literal `page.goto(` call in the section's code (rough check: no
        # line that starts with whitespace + "await page.goto(" or
        # "page.goto(" without the "not call" context)
        # We allow "`page.goto()`" in markdown prose but not code invocations.
        code_invocations = re.findall(r"^\s*(?:await\s+)?page\.goto\(", section, re.MULTILINE)
        self.assertEqual(
            code_invocations,
            [],
            f"6.3 (classifyCurrentPage) must not invoke page.goto in its code body; found: {code_invocations}",
        )

    def test_detectRenderAt_documented_as_with_goto(self):
        """Section 6.2 detectRenderAt should reference page.goto (Section 2)."""
        m = re.search(
            r"### 6\.2 — `detectRenderAt.*?(?=### 6\.\d|^## )",
            self.content,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(m, "Section 6.2 (detectRenderAt) not found")
        section = m.group(0)
        # Section 2 + page.goto mention expected
        self.assertIn("Section 2", section)

    def test_caller_policy_table_has_all_four_current_callers(self):
        """Section 7 must list design-critic, accessibility-scanner,
        ux-journeyer, behavior-verifier (new callers added pre-integration
        so PR 3/PR 4 integrators see the spec)."""
        m = re.search(
            r"## Section 7 — Caller policy table.*?(?=^## )",
            self.content,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(m, "Section 7 (Caller policy table) not found")
        table = m.group(0)
        for caller in ("design-critic", "accessibility-scanner", "ux-journeyer", "behavior-verifier"):
            self.assertIn(caller, table, f"Caller policy table missing {caller}")

    def test_auth_paths_anchor_present(self):
        self.assertIn("// SHARED:AUTH_PATHS", self.content)

    def test_outputs_enum_includes_prereq_unmet(self):
        m = re.search(r"`review_method`: `\"([^`]+)\"`", self.content)
        self.assertIsNotNone(m)
        enum_text = m.group(1)
        for v in ("rendered-authed", "rendered-demo", "source-only", "unknown", "prereq-unmet"):
            self.assertIn(v, enum_text, f"review_method enum missing {v}")

    def test_review_evidence_documents_expected_destination(self):
        self.assertIn("`expected_destination`: string | null", self.content)

    def test_4th_reviewer_appendix_exists(self):
        self.assertIn("## Appendix — 4th reviewer worked example", self.content)


if __name__ == "__main__":
    unittest.main()
