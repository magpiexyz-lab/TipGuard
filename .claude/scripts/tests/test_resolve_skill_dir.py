#!/usr/bin/env python3
"""test_resolve_skill_dir.py — unit tests for lifecycle-lib.sh resolve_skill_dir.

Pins the three hardcoded iterate arms and the filesystem-derived fallback added
for issue #1990 (mode-qualified keys previously echoed unchanged, which made
lifecycle-finalize.sh resolve nonexistent command files and manifests).

Run: python3 .claude/scripts/tests/test_resolve_skill_dir.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LIB = ROOT / ".claude/scripts/lifecycle-lib.sh"


class TestResolveSkillDir(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_rsd_"))
        (self.tmp / ".runs").mkdir()
        for skill in ("iterate", "ads-ready", "foo"):
            d = self.tmp / ".claude" / "skills" / skill
            d.mkdir(parents=True)
            (d / "skill.yaml").write_text("modes: {}\n")
        (self.tmp / ".runs" / "foo-lifecycle.json").write_text(
            json.dumps({"modes": {"bar": {"states": ["0"]}}})
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def resolve(self, key: str):
        r = subprocess.run(
            ["bash", "-c",
             f'PROJECT_DIR="{self.tmp}"; source "{LIB}"; resolve_skill_dir "{key}"'],
            capture_output=True, text=True, check=True,
        )
        return r.stdout.strip(), r.stderr

    def test_hardcoded_iterate_arms_unchanged(self):
        self.assertEqual(self.resolve("iterate-check")[0], "iterate check")
        self.assertEqual(self.resolve("iterate-cross")[0], "iterate cross")
        self.assertEqual(
            self.resolve("iterate-cross-phase2")[0], "iterate cross-phase2"
        )

    def test_plain_skill_passthrough(self):
        self.assertEqual(self.resolve("iterate")[0], "iterate")

    def test_hyphenated_real_skill_returns_itself(self):
        out, _ = self.resolve("ads-ready")
        self.assertEqual(out, "ads-ready")

    def test_unknown_qualified_key_splits_on_declared_mode(self):
        out, _ = self.resolve("foo-bar")
        self.assertEqual(out, "foo bar")

    def test_undeclared_mode_warns_and_falls_through(self):
        out, err = self.resolve("foo-baz")
        self.assertEqual(out, "foo-baz")
        self.assertIn("not a declared mode", err)

    def test_missing_manifest_is_fail_open(self):
        (self.tmp / ".runs" / "foo-lifecycle.json").unlink()
        out, _ = self.resolve("foo-baz")
        self.assertEqual(out, "foo baz")

    def test_fully_unknown_key_passthrough(self):
        self.assertEqual(
            self.resolve("totally-unknown-thing")[0], "totally-unknown-thing"
        )


if __name__ == "__main__":
    sys.exit(unittest.main())
