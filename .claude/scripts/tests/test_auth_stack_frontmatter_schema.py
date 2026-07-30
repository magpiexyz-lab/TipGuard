#!/usr/bin/env python3
"""Validates that every .claude/stacks/auth/*.md file has a parseable YAML
frontmatter block with a `demo_mode` section (Issue #1077, PR1b).

The DEMO_MODE policy is consumed by
.claude/scripts/lib/derive_slot_intent.py:derive_runtime_gate() to decide
whether a behavior's required_role is reachable in DEMO_MODE.

Run via: python3 .claude/scripts/tests/test_auth_stack_frontmatter_schema.py
"""
import glob
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


def _parse_frontmatter(text: str):
    """Extract YAML frontmatter delimited by '---' on their own lines.

    Naive split('---') breaks on comment lines like '# --- foo ---'.
    We anchor on \\n---\\n delimiters (i.e., '---' as a full line).
    """
    if not text.startswith("---\n"):
        return None
    rest = text[4:]
    end_idx = rest.find("\n---\n")
    if end_idx < 0:
        # also accept trailing '---' followed by EOF
        if rest.endswith("\n---"):
            end_idx = len(rest) - 4
        else:
            return None
    fm_text = rest[:end_idx]
    try:
        import yaml
    except ImportError:
        return {"_yaml_unavailable": True, "_raw": fm_text}
    return yaml.safe_load(fm_text) or {}


class TestAuthStacksHaveDemoMode(unittest.TestCase):
    def setUp(self):
        self.auth_files = glob.glob(
            os.path.join(REPO_ROOT, ".claude/stacks/auth/*.md")
        )
        # Filter out README/index files if any.
        self.auth_files = [
            f for f in self.auth_files
            if not f.lower().endswith("readme.md")
            and not f.lower().endswith("index.md")
        ]

    def test_at_least_one_auth_stack_exists(self):
        # Sanity: there must be ≥1 auth stack file (supabase, at minimum).
        self.assertGreater(len(self.auth_files), 0,
                           "no auth stack files found")

    def test_each_stack_has_frontmatter(self):
        for path in self.auth_files:
            with open(path) as f:
                text = f.read()
            self.assertTrue(
                text.startswith("---"),
                f"{path} does not start with YAML frontmatter delimiter",
            )

    def test_each_stack_has_demo_mode_block(self):
        for path in self.auth_files:
            with open(path) as f:
                text = f.read()
            fm = _parse_frontmatter(text)
            if fm is None:
                self.fail(f"{path} has no parseable frontmatter")
            if fm.get("_yaml_unavailable"):
                # Fallback: just check for the literal 'demo_mode:' string
                self.assertIn(
                    "demo_mode:", fm["_raw"],
                    f"{path} frontmatter missing demo_mode block (PyYAML unavailable)",
                )
                continue
            self.assertIn(
                "demo_mode", fm,
                f"{path} frontmatter missing 'demo_mode' block",
            )

    def test_demo_mode_has_required_keys(self):
        for path in self.auth_files:
            with open(path) as f:
                text = f.read()
            fm = _parse_frontmatter(text)
            if fm is None or fm.get("_yaml_unavailable"):
                self.skipTest(f"PyYAML unavailable; cannot validate {path}")
            demo_mode = fm.get("demo_mode")
            if demo_mode is None:
                continue  # caught by previous test
            self.assertIsInstance(
                demo_mode, dict,
                f"{path} demo_mode must be an object",
            )
            self.assertIn(
                "demo_mode_role", demo_mode,
                f"{path} demo_mode missing 'demo_mode_role' (None or string)",
            )
            # demo_mode_role: None or a string
            role = demo_mode.get("demo_mode_role")
            self.assertTrue(
                role is None or isinstance(role, str),
                f"{path} demo_mode_role must be null or string; got {role!r}",
            )


if __name__ == "__main__":
    unittest.main()
