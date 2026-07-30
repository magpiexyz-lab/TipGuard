#!/usr/bin/env python3
"""Tests for derive_runtime_gate() (Issue #1077, PR1a).

Reads behaviors[].requires_role (NEW structured field) + auth stack frontmatter
demo_mode_role. Returns runtime_gate dict when slot is unreachable in DEMO_MODE.

Run via: python3 .claude/scripts/tests/test_derive_runtime_gate.py
"""
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO_ROOT, ".claude", "scripts"))

from lib.derive_slot_intent import derive_runtime_gate  # noqa: E402


class TestNoBehaviors(unittest.TestCase):
    def test_no_behaviors_returns_none(self):
        self.assertIsNone(derive_runtime_gate(None, None))
        self.assertIsNone(derive_runtime_gate([], None))

    def test_no_behaviors_with_frontmatter_still_none(self):
        self.assertIsNone(derive_runtime_gate(
            None, {"demo_mode_role": "client"}))


class TestNoRoleRequired(unittest.TestCase):
    def test_behaviors_without_requires_role(self):
        behaviors = [
            {"id": "create_invoice", "pages": ["/invoice/new"]},
            {"id": "view_dashboard", "pages": ["/dashboard"]},
        ]
        self.assertIsNone(derive_runtime_gate(behaviors, None))

    def test_empty_requires_role_string_skipped(self):
        behaviors = [{"id": "x", "requires_role": ""}]
        self.assertIsNone(derive_runtime_gate(behaviors, None))

    def test_non_string_requires_role_skipped(self):
        behaviors = [{"id": "x", "requires_role": True}]
        self.assertIsNone(derive_runtime_gate(behaviors, None))


class TestRoleGated(unittest.TestCase):
    def test_admin_role_required_no_demo_role(self):
        behaviors = [{"id": "admin_dashboard", "requires_role": "admin"}]
        out = derive_runtime_gate(behaviors, None)
        self.assertIsNotNone(out)
        self.assertEqual(out["role"], "admin")
        self.assertIn("admin_dashboard", out["reason"])
        self.assertIn("requires_role", out["evidence"])

    def test_admin_required_demo_role_null(self):
        behaviors = [{"id": "admin_queue", "requires_role": "admin"}]
        frontmatter = {"demo_mode_role": None}
        out = derive_runtime_gate(behaviors, frontmatter)
        self.assertIsNotNone(out)
        self.assertEqual(out["role"], "admin")

    def test_admin_required_demo_role_client(self):
        behaviors = [{"id": "admin_queue", "requires_role": "admin"}]
        frontmatter = {"demo_mode_role": "client"}
        out = derive_runtime_gate(behaviors, frontmatter)
        self.assertIsNotNone(out)
        self.assertEqual(out["role"], "admin")
        self.assertIn("client", out["reason"])

    def test_admin_required_demo_role_admin_NOT_gated(self):
        # Demo user has admin role → slot IS reachable → no gate
        behaviors = [{"id": "admin_queue", "requires_role": "admin"}]
        frontmatter = {"demo_mode_role": "admin"}
        self.assertIsNone(derive_runtime_gate(behaviors, frontmatter))

    def test_custom_role_operator(self):
        behaviors = [{"id": "operations_panel", "requires_role": "operator"}]
        frontmatter = {"demo_mode_role": "client"}
        out = derive_runtime_gate(behaviors, frontmatter)
        self.assertIsNotNone(out)
        self.assertEqual(out["role"], "operator")


class TestMixedBehaviors(unittest.TestCase):
    def test_some_with_role_some_without(self):
        behaviors = [
            {"id": "create_invoice"},  # no role
            {"id": "admin_view", "requires_role": "admin"},
            {"id": "another"},  # no role
        ]
        out = derive_runtime_gate(behaviors, None)
        self.assertIsNotNone(out)
        self.assertEqual(out["role"], "admin")

    def test_first_role_wins_on_multiple(self):
        # Current implementation takes the first declared role.
        # Document this behavior; future iterations may pick strictest.
        behaviors = [
            {"id": "operator_panel", "requires_role": "operator"},
            {"id": "admin_only", "requires_role": "admin"},
        ]
        out = derive_runtime_gate(behaviors, {"demo_mode_role": None})
        self.assertEqual(out["role"], "operator")


class TestEvidenceShape(unittest.TestCase):
    def test_evidence_cites_behavior_id(self):
        behaviors = [{"id": "admin_dashboard", "requires_role": "admin"}]
        out = derive_runtime_gate(behaviors, None)
        self.assertIn("admin_dashboard", out["evidence"])
        self.assertIn("requires_role", out["evidence"])

    def test_unknown_behavior_id(self):
        behaviors = [{"requires_role": "admin"}]  # no id
        out = derive_runtime_gate(behaviors, None)
        self.assertIsNotNone(out)
        self.assertEqual(out["role"], "admin")


if __name__ == "__main__":
    unittest.main()
