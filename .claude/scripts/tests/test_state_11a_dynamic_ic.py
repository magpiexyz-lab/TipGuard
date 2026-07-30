#!/usr/bin/env python3
"""Tests for verify-state-11a-image-count.py (Issue #1077, PR2).

Closes Round 2 critic Concern 6: state-11a hardcoded `ic >= 7` conflicts
with slot-intent skip-on-non-ai-generated semantics. The dynamic threshold:
  - When slot-intent.json has design_slots_enabled=true → expect EXACTLY
    sum(production_method == "ai_generated") slots
  - Otherwise (no slot-intent OR flag false) → legacy >= 7

Run via: python3 .claude/scripts/tests/test_state_11a_dynamic_ic.py
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
SCRIPT = os.path.join(REPO_ROOT, ".claude", "scripts",
                     "verify-state-11a-image-count.py")


def _run(cwd: str) -> tuple[int, str]:
    r = subprocess.run([sys.executable, SCRIPT], cwd=cwd,
                       capture_output=True, text=True)
    return r.returncode, r.stderr


def _write(path: str, content: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(content, f, indent=2)


class TestNoManifest(unittest.TestCase):
    def test_no_manifest_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, _ = _run(tmp)
            self.assertEqual(rc, 0)


class TestLegacyThreshold(unittest.TestCase):
    """No slot-intent OR design_slots_enabled=false → legacy >= 7."""

    def test_legacy_7_images_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(os.path.join(tmp, ".runs/image-manifest.json"), {
                "status": "complete",
                "images": [{"filename": f"img{i}.webp"} for i in range(7)],
            })
            rc, err = _run(tmp)
            self.assertEqual(rc, 0, err)

    def test_legacy_6_images_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(os.path.join(tmp, ".runs/image-manifest.json"), {
                "status": "complete",
                "images": [{"filename": f"img{i}.webp"} for i in range(6)],
            })
            rc, err = _run(tmp)
            self.assertNotEqual(rc, 0)
            self.assertIn(">=7", err)

    def test_slot_intent_disabled_falls_back_to_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(os.path.join(tmp, ".runs/image-manifest.json"), {
                "status": "complete",
                "images": [{"filename": f"img{i}.webp"} for i in range(7)],
            })
            _write(os.path.join(tmp, ".runs/slot-intent.json"), {
                "_schema_version": 1,
                "design_slots_enabled": False,
                "archetype": "web-app",
                "slots": {"hero": {"production_method": "ai_generated"}},
            })
            rc, _ = _run(tmp)
            self.assertEqual(rc, 0)


class TestSlotIntentDynamic(unittest.TestCase):
    """slot-intent enabled → exact match required."""

    def test_6_ai_slots_exact_match_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(os.path.join(tmp, ".runs/image-manifest.json"), {
                "status": "complete",
                "images": [{"filename": f"img{i}.webp"} for i in range(6)],
            })
            slots = {f"slot{i}": {"production_method": "ai_generated"}
                     for i in range(6)}
            slots["og-photo"] = {"production_method": "dynamic_runtime"}
            _write(os.path.join(tmp, ".runs/slot-intent.json"), {
                "_schema_version": 1,
                "design_slots_enabled": True,
                "archetype": "web-app",
                "slots": slots,
            })
            rc, err = _run(tmp)
            self.assertEqual(rc, 0, err)

    def test_extra_images_allowed(self):
        # #1186 fix: slot-intent count is now a FLOOR, not strict equality.
        # Manifests may legitimately contain extras (e.g., svg_icon slots that
        # scaffold-images chose to record alongside AI photos). slot-intent
        # says 6 ai_generated; manifest has 7 → must pass (>= floor met).
        # Renamed from test_too_many_images_fails (legacy strict-equality
        # behaviour was reverted in #1186).
        with tempfile.TemporaryDirectory() as tmp:
            _write(os.path.join(tmp, ".runs/image-manifest.json"), {
                "status": "complete",
                "images": [{"filename": f"img{i}.webp"} for i in range(7)],
            })
            slots = {f"slot{i}": {"production_method": "ai_generated"}
                     for i in range(6)}
            slots["og-photo"] = {"production_method": "dynamic_runtime"}
            _write(os.path.join(tmp, ".runs/slot-intent.json"), {
                "_schema_version": 1,
                "design_slots_enabled": True,
                "archetype": "web-app",
                "slots": slots,
            })
            rc, err = _run(tmp)
            self.assertEqual(rc, 0, err)

    def test_too_few_images_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(os.path.join(tmp, ".runs/image-manifest.json"), {
                "status": "complete",
                "images": [{"filename": f"img{i}.webp"} for i in range(5)],
            })
            slots = {f"slot{i}": {"production_method": "ai_generated"}
                     for i in range(6)}
            _write(os.path.join(tmp, ".runs/slot-intent.json"), {
                "_schema_version": 1,
                "design_slots_enabled": True,
                "archetype": "web-app",
                "slots": slots,
            })
            rc, _ = _run(tmp)
            self.assertNotEqual(rc, 0)


class TestStatusVariants(unittest.TestCase):
    def test_placeholders_status_skips_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(os.path.join(tmp, ".runs/image-manifest.json"), {
                "status": "placeholders",
                "images": [],
            })
            rc, _ = _run(tmp)
            self.assertEqual(rc, 0)

    def test_skipped_status_skips_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(os.path.join(tmp, ".runs/image-manifest.json"), {
                "status": "skipped",
                "images": [],
            })
            rc, _ = _run(tmp)
            self.assertEqual(rc, 0)

    def test_invalid_status_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(os.path.join(tmp, ".runs/image-manifest.json"), {
                "status": "weird",
                "images": [],
            })
            rc, err = _run(tmp)
            self.assertNotEqual(rc, 0)
            self.assertIn("bad status", err)


class TestServiceArchetype(unittest.TestCase):
    """Service archetype: all slots production_method=none → expected=0."""

    def test_service_archetype_zero_images_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(os.path.join(tmp, ".runs/image-manifest.json"), {
                "status": "complete",
                "images": [],
            })
            slots = {f"slot{i}": {"production_method": "none"}
                     for i in range(7)}
            _write(os.path.join(tmp, ".runs/slot-intent.json"), {
                "_schema_version": 1,
                "design_slots_enabled": True,
                "archetype": "service",
                "slots": slots,
            })
            rc, _ = _run(tmp)
            self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
