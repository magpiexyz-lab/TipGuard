#!/usr/bin/env python3
"""Tests for auth_routing.py — scaffold-wire's auth-routing.json builder
(Issue #1077, PR3 gap fix).

Closes the PR2 gap where scaffold-wire wrote vacuous None placeholders.
The helper now reads auth stack frontmatter + greps src/ for role checks
to populate real signals downstream consumers can rely on.

Run via: python3 .claude/scripts/tests/test_auth_routing.py
"""
import os
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO_ROOT, ".claude", "scripts"))

from lib.auth_routing import (  # noqa: E402
    build_auth_routing,
    consistency_warnings,
    parse_frontmatter,
    read_demo_mode,
    discover_role_checks,
)


def _write(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


class TestFrontmatterParser(unittest.TestCase):
    def test_line_anchored_split(self):
        # Tests the same edge case scaffold-init Step 5 fixes:
        # bare split('---') breaks on '# --- foo ---' comment lines.
        text = (
            "---\n"
            "files:\n"
            "  # --- comment with triple-dash inside ---\n"
            "  - src/foo.ts\n"
            "demo_mode:\n"
            "  demo_mode_role: client\n"
            "---\n"
            "# Body\n"
        )
        fm = parse_frontmatter(text)
        self.assertIsNotNone(fm)
        self.assertEqual(fm.get("demo_mode"), {"demo_mode_role": "client"})


class TestReadDemoMode(unittest.TestCase):
    def test_missing_file_returns_defaults(self):
        out = read_demo_mode("/nonexistent/path.md")
        self.assertEqual(out, {"demo_mode_role": None, "demo_user_metadata": {}})

    def test_role_extracted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "supabase.md")
            _write(path,
                "---\n"
                "demo_mode:\n"
                "  demo_mode_role: null\n"
                "  demo_user_metadata: {}\n"
                "---\n"
                "# Body\n"
            )
            out = read_demo_mode(path)
            self.assertIsNone(out["demo_mode_role"])
            self.assertEqual(out["demo_user_metadata"], {})

    def test_explicit_role_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "stack.md")
            _write(path,
                "---\n"
                "demo_mode:\n"
                "  demo_mode_role: client\n"
                "  demo_user_metadata: {role: client}\n"
                "---\n"
            )
            out = read_demo_mode(path)
            self.assertEqual(out["demo_mode_role"], "client")
            self.assertEqual(out["demo_user_metadata"], {"role": "client"})


class TestDiscoverRoleChecks(unittest.TestCase):
    def test_admin_role_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            _write(os.path.join(src, "lib/auth.ts"),
                'export function isAdmin(user: User) {\n'
                '  return user.app_metadata?.role === "admin";\n'
                '}\n'
            )
            roles = discover_role_checks(src)
            self.assertIn("admin", roles)

    def test_multiple_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            _write(os.path.join(src, "lib/auth.ts"),
                'if (user.app_metadata?.role === "admin") return true;\n'
                'if (user.app_metadata.role === "operator") return true;\n'
                'if (user.app_metadata?.role === "supervisor") return true;\n'
            )
            roles = discover_role_checks(src)
            self.assertEqual(set(roles), {"admin", "operator", "supervisor"})

    def test_no_role_checks_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            _write(os.path.join(src, "lib/foo.ts"), 'export const X = 1;\n')
            roles = discover_role_checks(src)
            self.assertEqual(roles, [])

    def test_no_src_returns_empty(self):
        roles = discover_role_checks("/nonexistent")
        self.assertEqual(roles, [])


class TestBuildAuthRouting(unittest.TestCase):
    def test_no_auth_stack(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                routing = build_auth_routing(auth_stack=None, src_root="src")
                self.assertIsNone(routing["demo_mode_role"])
                self.assertEqual(routing["role_checks_observed"], [])
                self.assertEqual(routing["unreachable_demo_routes"], [])
            finally:
                os.chdir(REPO_ROOT)

    def test_admin_role_unreachable_in_demo(self):
        # Demo user is null-role; src/ checks for admin → admin is unreachable
        with tempfile.TemporaryDirectory() as tmp:
            old_cwd = os.getcwd()
            os.chdir(tmp)
            try:
                _write(".claude/stacks/auth/test.md",
                    "---\n"
                    "demo_mode:\n"
                    "  demo_mode_role: null\n"
                    "  demo_user_metadata: {}\n"
                    "---\n"
                )
                _write("src/lib/auth.ts",
                    'if (user.app_metadata?.role === "admin") allow();\n'
                )
                routing = build_auth_routing(auth_stack="test", src_root="src")
                self.assertEqual(routing["role_checks_observed"], ["admin"])
                self.assertEqual(len(routing["unreachable_demo_routes"]), 1)
                self.assertEqual(routing["unreachable_demo_routes"][0]["role"],
                                 "admin")
            finally:
                os.chdir(old_cwd)

    def test_demo_role_admin_no_unreachable(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_cwd = os.getcwd()
            os.chdir(tmp)
            try:
                _write(".claude/stacks/auth/test.md",
                    "---\n"
                    "demo_mode:\n"
                    "  demo_mode_role: admin\n"
                    "---\n"
                )
                _write("src/lib/auth.ts",
                    'if (user.app_metadata?.role === "admin") allow();\n'
                )
                routing = build_auth_routing(auth_stack="test", src_root="src")
                self.assertEqual(routing["role_checks_observed"], ["admin"])
                # demo user has admin → admin not unreachable
                self.assertEqual(routing["unreachable_demo_routes"], [])
            finally:
                os.chdir(old_cwd)


class TestConsistencyWarnings(unittest.TestCase):
    def test_no_slot_intent_no_warnings(self):
        routing = {"role_checks_observed": [], "demo_mode_role": None}
        self.assertEqual(consistency_warnings(routing, None), [])

    def test_flag_disabled_no_warnings(self):
        routing = {"role_checks_observed": [], "demo_mode_role": None}
        slot_intent = {"design_slots_enabled": False, "slots": {
            "empty-state": {"runtime_gate": {"role": "admin"}}
        }}
        self.assertEqual(consistency_warnings(routing, slot_intent), [])

    def test_role_not_checked_warns(self):
        routing = {"role_checks_observed": [], "demo_mode_role": None}
        slot_intent = {
            "design_slots_enabled": True,
            "slots": {
                "empty-state": {"runtime_gate": {"role": "admin"}},
            },
        }
        warns = consistency_warnings(routing, slot_intent)
        self.assertEqual(len(warns), 1)
        self.assertIn("admin", warns[0])
        self.assertIn("no `app_metadata.role === 'admin'`", warns[0])

    def test_role_matches_demo_role_warns(self):
        # Slot says gate by role X but demo user has role X → not gated
        routing = {"role_checks_observed": ["admin"], "demo_mode_role": "admin"}
        slot_intent = {
            "design_slots_enabled": True,
            "slots": {
                "empty-state": {"runtime_gate": {"role": "admin"}},
            },
        }
        warns = consistency_warnings(routing, slot_intent)
        self.assertEqual(len(warns), 1)
        self.assertIn("SAME", warns[0])

    def test_consistent_no_warnings(self):
        routing = {"role_checks_observed": ["admin"], "demo_mode_role": None}
        slot_intent = {
            "design_slots_enabled": True,
            "slots": {
                "empty-state": {"runtime_gate": {"role": "admin"}},
            },
        }
        self.assertEqual(consistency_warnings(routing, slot_intent), [])

    def test_slot_without_gate_no_warning(self):
        routing = {"role_checks_observed": [], "demo_mode_role": None}
        slot_intent = {
            "design_slots_enabled": True,
            "slots": {"hero": {"runtime_gate": None}},
        }
        self.assertEqual(consistency_warnings(routing, slot_intent), [])


if __name__ == "__main__":
    unittest.main()
