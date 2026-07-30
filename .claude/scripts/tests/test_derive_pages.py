#!/usr/bin/env python3
"""Behavioral tests for .claude/scripts/lib/derive_pages.py.

Covers SET semantics (derive_scope_pages) and LIST semantics (derive_funnel_steps)
across all archetypes (web-app, service, cli) and key scenarios:
  - golden_path only
  - behaviors with pages
  - auth-derived (login/signup)
  - union + dedup
  - landing exclusion
  - empty/missing fields
  - service/cli archetypes (no pages)
  - funnel order preservation

Run via: python3 .claude/scripts/tests/test_derive_pages.py
Or via:  bash .claude/scripts/tests/run-all.sh
"""
import os
import sys
import unittest

# Make .claude/scripts/lib importable
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO_ROOT, ".claude", "scripts"))

from lib.derive_pages import (  # noqa: E402
    derive_funnel_steps,
    derive_landing_for_design_critic,
    derive_scope_pages,
)


class TestDeriveScopePages(unittest.TestCase):
    def test_golden_path_only(self):
        """Pages from golden_path are collected; landing excluded."""
        exp = {
            "type": "web-app",
            "golden_path": [
                {"step": "Visit", "event": "visit_landing", "page": "landing"},
                {"step": "Sign up", "event": "signup_complete", "page": "signup"},
                {"step": "Use it", "event": "activate", "page": "dashboard"},
            ],
        }
        self.assertEqual(derive_scope_pages(exp), ["dashboard", "signup"])

    def test_behaviors_with_pages(self):
        """Pages from behaviors[*].pages are collected."""
        exp = {
            "type": "web-app",
            "behaviors": [
                {"id": "b-01", "pages": ["dashboard", "admin"]},
                {"id": "b-02", "pages": ["portfolio"]},
            ],
        }
        self.assertEqual(derive_scope_pages(exp), ["admin", "dashboard", "portfolio"])

    def test_auth_derived(self):
        """login and signup are added when stack.auth is set."""
        exp = {"type": "web-app", "stack": {"auth": "supabase"}}
        self.assertEqual(derive_scope_pages(exp), ["login", "signup"])

    def test_no_auth_no_login_signup(self):
        """When stack.auth is absent, login/signup are not added."""
        exp = {"type": "web-app", "stack": {}}
        self.assertEqual(derive_scope_pages(exp), [])

    def test_union_and_dedup(self):
        """golden_path + behaviors + auth-derived merge with dedup."""
        exp = {
            "type": "web-app",
            "golden_path": [
                {"step": "Visit", "event": "x", "page": "landing"},
                {"step": "Dashboard", "event": "y", "page": "dashboard"},
            ],
            "behaviors": [
                {"id": "b-01", "pages": ["dashboard", "admin"]},  # dashboard dup
            ],
            "stack": {"auth": "supabase"},
        }
        self.assertEqual(derive_scope_pages(exp), ["admin", "dashboard", "login", "signup"])

    def test_landing_always_excluded(self):
        """landing in any source is filtered out (scaffold-landing owns it)."""
        exp = {
            "type": "web-app",
            "golden_path": [{"step": "x", "event": "y", "page": "landing"}],
            "behaviors": [{"id": "b-01", "pages": ["landing", "dashboard"]}],
        }
        self.assertEqual(derive_scope_pages(exp), ["dashboard"])

    def test_empty_experiment(self):
        """Empty experiment returns empty list."""
        self.assertEqual(derive_scope_pages({}), [])

    def test_missing_fields(self):
        """Missing/None fields handled gracefully."""
        exp = {
            "type": "web-app",
            "golden_path": None,
            "behaviors": None,
            "stack": None,
        }
        self.assertEqual(derive_scope_pages(exp), [])

    def test_behavior_without_pages(self):
        """Behaviors without `pages` field (e.g., actor: system/cron) are skipped."""
        exp = {
            "type": "web-app",
            "behaviors": [
                {"id": "b-05", "actor": "system", "trigger": "webhook"},  # no pages
                {"id": "b-06", "actor": "cron"},                          # no pages
            ],
        }
        self.assertEqual(derive_scope_pages(exp), [])

    def test_step_without_page_field(self):
        """golden_path entries without page field are skipped."""
        exp = {
            "type": "web-app",
            "golden_path": [
                {"step": "Generic", "event": "x"},  # no page
                {"step": "Real", "event": "y", "page": "dashboard"},
            ],
        }
        self.assertEqual(derive_scope_pages(exp), ["dashboard"])

    def test_service_archetype(self):
        """Service archetype: no pages (no behavior.pages, no golden_path)."""
        exp = {
            "type": "service",
            "behaviors": [
                {"id": "b-01", "endpoints": ["POST /api/foo"]},
            ],
            "endpoints": [{"method": "POST", "path": "/api/foo"}],
        }
        # derive_scope_pages doesn't gate on archetype — it just returns empty
        # because there are no pages to derive from.
        self.assertEqual(derive_scope_pages(exp), [])

    def test_cli_archetype(self):
        """CLI archetype: no pages."""
        exp = {
            "type": "cli",
            "behaviors": [
                {"id": "b-01", "commands": ["foo --bar"]},
            ],
            "commands": [{"name": "foo", "args": ["--bar"]}],
        }
        self.assertEqual(derive_scope_pages(exp), [])


class TestDeriveFunnelSteps(unittest.TestCase):
    def test_preserves_order(self):
        """Order of golden_path is preserved (list semantics)."""
        steps = [
            {"step": "First", "event": "a", "page": "p1"},
            {"step": "Second", "event": "b", "page": "p2"},
            {"step": "Third", "event": "c", "page": "p3"},
        ]
        exp = {"golden_path": steps}
        result = derive_funnel_steps(exp)
        self.assertEqual(result, steps)
        # Ensure order preserved
        self.assertEqual([s["page"] for s in result], ["p1", "p2", "p3"])

    def test_empty_when_no_golden_path(self):
        """Returns empty list when golden_path absent."""
        self.assertEqual(derive_funnel_steps({}), [])
        self.assertEqual(derive_funnel_steps({"golden_path": None}), [])

    def test_returns_full_step_dicts(self):
        """Returned entries preserve all fields (not just page)."""
        exp = {
            "golden_path": [
                {"step": "Sign up", "event": "signup_complete", "page": "signup",
                 "extra_field": "preserved"},
            ]
        }
        result = derive_funnel_steps(exp)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["extra_field"], "preserved")


class TestDeriveLandingForDesignCritic(unittest.TestCase):
    """Tests for derive_landing_for_design_critic helper (#1143).

    Helper produces the operational landing entry consumed by state-2a's
    `design-page-set.json["landing"]` sibling field, which state-3a Stage 1
    reads to spawn a landing-specific design-critic agent.
    """

    def test_landing_tsx_present(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "src/app"))
            with open(os.path.join(tmp, "src/app/page.tsx"), "w") as f:
                f.write("// landing")
            result = derive_landing_for_design_critic(tmp)
            self.assertIsNotNone(result)
            self.assertEqual(result["name"], "landing")
            self.assertEqual(result["route_pattern"], "/")
            self.assertEqual(result["test_url"], "/")
            self.assertEqual(result["source_files"], ["src/app/page.tsx"])
            self.assertEqual(result["dynamic_segments"], [])

    def test_landing_jsx_present(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "src/app"))
            with open(os.path.join(tmp, "src/app/page.jsx"), "w") as f:
                f.write("// landing")
            result = derive_landing_for_design_critic(tmp)
            self.assertEqual(result["source_files"], ["src/app/page.jsx"])

    def test_landing_ts_present(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "src/app"))
            with open(os.path.join(tmp, "src/app/page.ts"), "w") as f:
                f.write("// landing")
            result = derive_landing_for_design_critic(tmp)
            self.assertEqual(result["source_files"], ["src/app/page.ts"])

    def test_landing_absent_returns_none(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "src/app"))
            # No src/app/page.* file
            result = derive_landing_for_design_critic(tmp)
            self.assertIsNone(result)

    def test_landing_unknown_extension_ignored(self):
        """Defensive: src/app/page.md or page.css must NOT match (only
        `tsx`/`jsx`/`ts`/`js` are page sources)."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "src/app"))
            with open(os.path.join(tmp, "src/app/page.md"), "w") as f:
                f.write("# not a page")
            result = derive_landing_for_design_critic(tmp)
            self.assertIsNone(result)

    def test_landing_multiple_extensions_sorted(self):
        """Defensive: if both .tsx and .ts exist (project misconfiguration),
        return both sorted deterministically."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "src/app"))
            for ext in ("tsx", "ts"):
                with open(os.path.join(tmp, f"src/app/page.{ext}"), "w") as f:
                    f.write("// x")
            result = derive_landing_for_design_critic(tmp)
            self.assertEqual(
                result["source_files"],
                ["src/app/page.ts", "src/app/page.tsx"],
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
