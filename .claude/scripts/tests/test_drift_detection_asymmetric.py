#!/usr/bin/env python3
"""End-to-end tests for check-slot-intent-drift.py asymmetric severity table
(Issue #1077, PR3).

Validates the 4 named cases from #1077 trigger correct severity:
  - hero opacity-0.055 mix-blend-luminosity (focal declared) → BLOCK
  - feature opacity-0.35 grayscale (focal declared) → BLOCK
  - hero opacity-0.055 (texture declared, intentional design) → PASS
  - og-photo dynamic_runtime + image in JSX → BLOCK
  - empty-state conditional → INFO
  - texture × full opacity → WARN

Run via: python3 .claude/scripts/tests/test_drift_detection_asymmetric.py
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


def _run(cwd: str) -> tuple[int, str, dict]:
    r = subprocess.run([sys.executable, TOOL], cwd=cwd,
                       capture_output=True, text=True)
    report_path = os.path.join(cwd, ".runs", "drift-report.json")
    report = {}
    if os.path.exists(report_path):
        with open(report_path) as f:
            report = json.load(f)
    return r.returncode, r.stderr, report


def _setup(tmp: str, slot_intent: dict, src_files: dict):
    os.makedirs(os.path.join(tmp, ".runs"), exist_ok=True)
    with open(os.path.join(tmp, ".runs", "slot-intent.json"), "w") as f:
        json.dump(slot_intent, f)
    for path, content in src_files.items():
        full = os.path.join(tmp, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(content)


def _slot_intent(slots: dict, archetype: str = "web-app") -> dict:
    return {
        "_schema_version": 1,
        "design_slots_enabled": True,
        "archetype": archetype,
        "slots": slots,
    }


class TestNamedCase1HeroOpacity(unittest.TestCase):
    """Hero declared focal but rendered at opacity-0.055 → BLOCK."""

    def test_hero_focal_declared_invisible_render_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp,
                _slot_intent({
                    "hero": {
                        "slot_role": "focal",
                        "production_method": "ai_generated",
                        "intended_render": {"opacity": 1.0,
                                            "blend_mode": "normal",
                                            "filter": "none"},
                        "candidate_budget": "high",
                        "runtime_gate": None,
                        "source": "derived",
                    },
                }),
                {"src/components/Hero.tsx": (
                    'import Image from "next/image";\n'
                    'export function Hero() {\n'
                    '  return <Image src="/images/hero.webp"\n'
                    '    className="opacity-[0.055] mix-blend-luminosity"\n'
                    '    alt="hero" width={1920} height={1080} />;\n'
                    '}\n'
                )},
            )
            rc, stderr, report = _run(tmp)
            self.assertNotEqual(rc, 0)
            self.assertEqual(report["block_count"], 1)
            findings = [f for f in report["findings"]
                       if f["severity"] == "BLOCK"]
            self.assertEqual(findings[0]["slot"], "hero")
            self.assertIn("focal", findings[0]["message"])


class TestHeroDeclaredTextureNoBlock(unittest.TestCase):
    """Hero declared texture intentionally low-opacity → PASS (no false-positive)."""

    def test_hero_texture_declared_low_render_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp,
                _slot_intent({
                    "hero": {
                        "slot_role": "texture",
                        "production_method": "ai_generated",
                        "intended_render": {"opacity": 0.055,
                                            "blend_mode": "luminosity",
                                            "filter": "none"},
                        "candidate_budget": "low",
                        "runtime_gate": None,
                        "source": "derived",
                    },
                }),
                {"src/components/Hero.tsx": (
                    '<Image src="/images/hero.webp"\n'
                    '  className="opacity-[0.055] mix-blend-luminosity" />\n'
                )},
            )
            rc, _, report = _run(tmp)
            self.assertEqual(rc, 0)
            self.assertEqual(report["block_count"], 0)


class TestFeatureGrayscale(unittest.TestCase):
    def test_feature_focal_declared_grayscale_render_blocks(self):
        # focal demands effective_weight >= 0.5; grayscale + 0.35 ≈ 0.131
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp,
                _slot_intent({
                    "feature-1": {
                        "slot_role": "focal",
                        "production_method": "ai_generated",
                        "intended_render": {"opacity": 1.0,
                                            "blend_mode": "normal",
                                            "filter": "none"},
                        "candidate_budget": "medium",
                        "runtime_gate": None,
                        "source": "derived",
                    },
                }),
                {"src/components/FeatureRow.tsx": (
                    '<Image src="/images/feature-1.webp"\n'
                    '  className="opacity-[0.35] grayscale brightness-75" />\n'
                )},
            )
            rc, _, report = _run(tmp)
            self.assertNotEqual(rc, 0)
            self.assertEqual(report["block_count"], 1)


class TestOgPhotoDynamicRuntimeBlock(unittest.TestCase):
    """og-photo declared dynamic_runtime but JSX imports it → BLOCK."""

    def test_dynamic_runtime_with_jsx_import_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp,
                _slot_intent({
                    "og-photo": {
                        "slot_role": "none",
                        "production_method": "dynamic_runtime",
                        "intended_render": None,
                        "candidate_budget": "low",
                        "runtime_gate": None,
                        "source": "derived",
                    },
                }),
                {"src/components/Hero.tsx":
                    '<Image src="/images/og-photo.png" />\n'},
            )
            rc, _, report = _run(tmp)
            self.assertNotEqual(rc, 0)
            blocks = [f for f in report["findings"] if f["severity"] == "BLOCK"]
            self.assertEqual(len(blocks), 1)


class TestOgPhotoDynamicRuntimeNoImportPasses(unittest.TestCase):
    def test_dynamic_runtime_without_import_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp,
                _slot_intent({
                    "og-photo": {
                        "slot_role": "none",
                        "production_method": "dynamic_runtime",
                        "intended_render": None,
                        "candidate_budget": "low",
                        "runtime_gate": None,
                        "source": "derived",
                    },
                }),
                # opengraph-image.tsx contains JSX but no /images/og-photo
                {"src/app/opengraph-image.tsx":
                    'import { ImageResponse } from "next/og";\n'
                    'export default function() { return new ImageResponse(<div/>); }\n'},
            )
            rc, _, report = _run(tmp)
            self.assertEqual(rc, 0)
            self.assertEqual(report["block_count"], 0)


class TestEmptyStateConditionalInfo(unittest.TestCase):
    def test_conditional_yields_info(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp,
                _slot_intent({
                    "empty-state": {
                        "slot_role": "conditional",
                        "production_method": "ai_generated",
                        "intended_render": {"opacity": 1.0,
                                            "blend_mode": "normal",
                                            "filter": "none"},
                        "candidate_budget": "low",
                        "runtime_gate": {
                            "role": "admin",
                            "reason": "demo user lacks admin",
                            "evidence": "behaviors[admin].requires_role",
                        },
                        "source": "derived",
                    },
                }),
                {"src/app/admin/page.tsx":
                    '<Image src="/images/empty-state.webp" />\n'},
            )
            rc, _, report = _run(tmp)
            self.assertEqual(rc, 0)
            infos = [f for f in report["findings"] if f["severity"] == "INFO"]
            self.assertGreater(len(infos), 0)


class TestTextureHighWarns(unittest.TestCase):
    def test_texture_at_full_opacity_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp,
                _slot_intent({
                    "hero": {
                        "slot_role": "texture",
                        "production_method": "ai_generated",
                        "intended_render": {"opacity": 0.08,
                                            "blend_mode": "luminosity",
                                            "filter": "none"},
                        "candidate_budget": "low",
                        "runtime_gate": None,
                        "source": "derived",
                    },
                }),
                {"src/components/Hero.tsx":
                    '<Image src="/images/hero.webp" className="opacity-100" />\n'},
            )
            rc, _, report = _run(tmp)
            self.assertEqual(rc, 0)
            warns = [f for f in report["findings"] if f["severity"] == "WARN"]
            self.assertEqual(len(warns), 1)


class TestFlagDisabledShortCircuits(unittest.TestCase):
    def test_flag_disabled_emits_not_applicable(self):
        with tempfile.TemporaryDirectory() as tmp:
            si = _slot_intent({"hero": {"slot_role": "focal"}})
            si["design_slots_enabled"] = False
            _setup(tmp, si, {})
            rc, _, report = _run(tmp)
            self.assertEqual(rc, 0)
            self.assertTrue(report["not_applicable"])


class TestSlotIntentMissing(unittest.TestCase):
    def test_no_slot_intent_emits_not_applicable(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ".runs"))
            rc, _, report = _run(tmp)
            self.assertEqual(rc, 0)
            self.assertTrue(report["not_applicable"])


if __name__ == "__main__":
    unittest.main()
