#!/usr/bin/env python3
"""Tests for state-2b boundary-skip handling (Issue #1077, PR3).

When state-2a wrote .runs/page-image-map.json with not_applicable=true
(non-web-app archetype OR scope mismatch), state-2b drift detector
short-circuits with not_applicable=true and PASS exit code (0).

Closes Round 2 critic Concern 4: state-2b cannot read state-3a's flag
because state-2b runs FIRST. Boundary-skip detection is computed locally.

Run via: python3 .claude/scripts/tests/test_drift_boundary_skip.py
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
TOOL = os.path.join(REPO_ROOT, ".claude", "scripts",
                   "check-slot-intent-drift.py")


def _run(cwd: str) -> tuple[int, dict]:
    r = subprocess.run([sys.executable, TOOL], cwd=cwd,
                       capture_output=True, text=True)
    report_path = os.path.join(cwd, ".runs", "drift-report.json")
    with open(report_path) as f:
        return r.returncode, json.load(f)


def _write(path: str, content: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(content, f)


class TestPageImageMapBoundarySkip(unittest.TestCase):
    def test_state_2a_not_applicable_short_circuits(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(os.path.join(tmp, ".runs/page-image-map.json"),
                   {"not_applicable": True,
                    "skip_reason": "non-web-app archetype"})
            # Even if slot-intent.json exists, drift skips when state-2a says not_applicable
            _write(os.path.join(tmp, ".runs/slot-intent.json"), {
                "_schema_version": 1,
                "design_slots_enabled": True,
                "archetype": "service",
                "slots": {"hero": {"slot_role": "focal",
                                   "production_method": "ai_generated"}},
            })
            rc, report = _run(tmp)
            self.assertEqual(rc, 0)
            self.assertTrue(report["not_applicable"])
            self.assertIn("not_applicable", report["skip_reason"])


class TestPageImageMapMalformedTreatedAsActive(unittest.TestCase):
    def test_malformed_page_image_map_proceeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            # corrupt page-image-map.json — should not break drift detector
            os.makedirs(os.path.join(tmp, ".runs"), exist_ok=True)
            with open(os.path.join(tmp, ".runs/page-image-map.json"), "w") as f:
                f.write("not valid json")
            _write(os.path.join(tmp, ".runs/slot-intent.json"), {
                "_schema_version": 1,
                "design_slots_enabled": True,
                "archetype": "web-app",
                "slots": {},
            })
            rc, report = _run(tmp)
            # Drift should still run (no slots → no findings)
            self.assertEqual(rc, 0)
            self.assertEqual(report.get("block_count"), 0)


class TestPageImageMapAbsentTreatedAsActive(unittest.TestCase):
    def test_no_page_image_map_drift_proceeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(os.path.join(tmp, ".runs/slot-intent.json"), {
                "_schema_version": 1,
                "design_slots_enabled": True,
                "archetype": "web-app",
                "slots": {},
            })
            rc, report = _run(tmp)
            self.assertEqual(rc, 0)
            self.assertFalse(report.get("not_applicable", False))


if __name__ == "__main__":
    unittest.main()
