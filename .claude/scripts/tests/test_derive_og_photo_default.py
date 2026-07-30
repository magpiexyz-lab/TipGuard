#!/usr/bin/env python3
"""Tests for derive_og_photo_default() (Issue #1077, PR1a).

Reads .runs/gate-verdicts/phase-a-sentinel.json (NOT bash markdown parsing
per Round 2 critic Concern 1). When opengraph-image.tsx is in CORE_FILES,
returns slot_role=none + production_method=dynamic_runtime.

Run via: python3 .claude/scripts/tests/test_derive_og_photo_default.py
"""
import json
import os
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO_ROOT, ".claude", "scripts"))

from lib.derive_slot_intent import derive_og_photo_default  # noqa: E402


class TestSentinelPresent(unittest.TestCase):
    def test_dynamic_og_emitted_yields_dynamic_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "phase-a-sentinel.json")
            with open(path, "w") as f:
                json.dump({
                    "phase_a_complete": True,
                    "timestamp": "2026-04-26T00:00:00Z",
                    "files": [
                        "src/app/layout.tsx",
                        "src/app/not-found.tsx",
                        "src/app/error.tsx",
                        "src/app/icon.tsx",
                        "src/app/opengraph-image.tsx",  # <-- key signal
                        "src/app/sitemap.ts",
                        "src/app/robots.ts",
                        "public/llms.txt",
                    ],
                }, f)
            out = derive_og_photo_default(path)
            self.assertEqual(out["slot_role"], "none")
            self.assertEqual(out["production_method"], "dynamic_runtime")
            self.assertIn("opengraph-image.tsx", out["evidence"])

    def test_no_dynamic_og_yields_ai_generated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "phase-a-sentinel.json")
            with open(path, "w") as f:
                json.dump({
                    "phase_a_complete": True,
                    "timestamp": "2026-04-26T00:00:00Z",
                    "files": [
                        "src/app/layout.tsx",
                        "src/app/not-found.tsx",
                        # NO opengraph-image.tsx
                    ],
                }, f)
            out = derive_og_photo_default(path)
            self.assertEqual(out["slot_role"], "focal")
            self.assertEqual(out["production_method"], "ai_generated")

    def test_unreadable_sentinel_falls_back_focal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "phase-a-sentinel.json")
            with open(path, "w") as f:
                f.write("{ this is not valid JSON")
            out = derive_og_photo_default(path)
            # On parse failure: fall back to focal+ai_generated to avoid
            # silent assumption (drift detection will catch any actual drift)
            self.assertEqual(out["slot_role"], "focal")
            self.assertEqual(out["production_method"], "ai_generated")
            self.assertIn("unreadable", out["evidence"])

    def test_empty_files_array(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "phase-a-sentinel.json")
            with open(path, "w") as f:
                json.dump({"files": []}, f)
            out = derive_og_photo_default(path)
            self.assertEqual(out["slot_role"], "focal")
            self.assertEqual(out["production_method"], "ai_generated")

    def test_missing_files_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "phase-a-sentinel.json")
            with open(path, "w") as f:
                json.dump({"phase_a_complete": True}, f)
            out = derive_og_photo_default(path)
            # Missing files = no opengraph-image.tsx detected = ai_generated
            self.assertEqual(out["slot_role"], "focal")


class TestSentinelMissing(unittest.TestCase):
    def test_typical_scaffold_init_timing_returns_dynamic_default(self):
        # scaffold-init runs at state-10, BEFORE state-11 Phase A.
        # Sentinel doesn't exist yet. Default is dynamic_runtime for web-app
        # because state-11-core-scaffold.md unconditionally emits
        # opengraph-image.tsx for web-app archetype.
        with tempfile.TemporaryDirectory() as tmp:
            nonexistent = os.path.join(tmp, "does", "not", "exist.json")
            out = derive_og_photo_default(nonexistent)
            self.assertEqual(out["slot_role"], "none")
            self.assertEqual(out["production_method"], "dynamic_runtime")
            self.assertIn("not yet written", out["evidence"])


if __name__ == "__main__":
    unittest.main()
