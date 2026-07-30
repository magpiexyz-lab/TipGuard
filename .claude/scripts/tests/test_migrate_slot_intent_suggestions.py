#!/usr/bin/env python3
"""Tests for migrate-slot-intent.py (Issue #1077, PR1.5).

Validates that the migration tool:
  - Reads image-manifest.json + greps src/ for usage sites
  - Maps observed CSS to inferred slot_role (focal vs texture)
  - Detects og-photo dead asset when opengraph-image.tsx exists
  - Detects unused assets (no import sites)
  - Sets correct confidence (high / medium / low) based on AST features
  - Writes to .runs/slot-intent-migration-suggestions.json (NEVER to
    .runs/slot-intent.json) — guards Round 2 critic Concern 5

Run via: python3 .claude/scripts/tests/test_migrate_slot_intent_suggestions.py
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
TOOL = os.path.join(REPO_ROOT, ".claude", "scripts", "migrate-slot-intent.py")


def _run(cwd: str, *extra_args) -> tuple[int, str, str]:
    """Run the tool with cwd set; return (exit_code, stdout, stderr)."""
    cmd = [sys.executable, TOOL, *extra_args]
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def _setup_project(tmp: str, manifest: dict, files: dict[str, str]):
    """Write a fixture project: manifest + src tree."""
    os.makedirs(os.path.join(tmp, ".runs"), exist_ok=True)
    with open(os.path.join(tmp, ".runs", "image-manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    for path, content in files.items():
        full = os.path.join(tmp, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(content)


def _read_suggestions(tmp: str) -> dict:
    out_path = os.path.join(tmp, ".runs", "slot-intent-migration-suggestions.json")
    with open(out_path) as f:
        return json.load(f)


class TestHeroOpacityDetection(unittest.TestCase):
    def test_hero_low_opacity_yields_texture_high_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = {
                "status": "complete",
                "images": [{"filename": "hero.webp", "publicPath": "/images/hero.webp"}],
            }
            files = {
                "src/components/Hero.tsx": (
                    'import Image from "next/image";\n'
                    'export function Hero() {\n'
                    '  return <Image\n'
                    '    src="/images/hero.webp"\n'
                    '    className="opacity-[0.055] mix-blend-luminosity"\n'
                    '    alt="hero" width={1920} height={1080} />;\n'
                    '}\n'
                ),
            }
            _setup_project(tmp, manifest, files)
            rc, _, err = _run(tmp)
            self.assertEqual(rc, 0, err)

            suggestions = _read_suggestions(tmp)["suggestions"]
            self.assertIn("hero", suggestions)
            self.assertEqual(suggestions["hero"]["slot_role"], "texture")
            self.assertEqual(suggestions["hero"]["confidence"], "high")
            self.assertAlmostEqual(
                suggestions["hero"]["intended_render"]["opacity"], 0.055, places=3,
            )
            self.assertEqual(
                suggestions["hero"]["intended_render"]["blend_mode"], "luminosity",
            )

    def test_hero_full_opacity_yields_focal(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = {"images": [{"filename": "hero.webp",
                                    "publicPath": "/images/hero.webp"}]}
            files = {
                "src/components/Hero.tsx": (
                    'import Image from "next/image";\n'
                    'export function Hero() {\n'
                    '  return <Image src="/images/hero.webp" alt="hero" '
                    'width={1920} height={1080} />;\n'
                    '}\n'
                ),
            }
            _setup_project(tmp, manifest, files)
            rc, _, _ = _run(tmp)
            self.assertEqual(rc, 0)
            suggestions = _read_suggestions(tmp)["suggestions"]
            self.assertEqual(suggestions["hero"]["slot_role"], "focal")
            self.assertEqual(suggestions["hero"]["intended_render"]["opacity"], 1.0)


class TestFeatureGrayscale(unittest.TestCase):
    def test_feature_grayscale_low_opacity_yields_texture(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = {
                "images": [
                    {"filename": "feature-1.webp", "publicPath": "/images/feature-1.webp"},
                ],
            }
            files = {
                "src/components/FeatureRow.tsx": (
                    'import Image from "next/image";\n'
                    'export function FeatureRow() {\n'
                    '  return <Image src="/images/feature-1.webp"\n'
                    '    className="opacity-[0.35] grayscale brightness-75"\n'
                    '    alt="feature" width={800} height={600} />;\n'
                    '}\n'
                ),
            }
            _setup_project(tmp, manifest, files)
            rc, _, _ = _run(tmp)
            self.assertEqual(rc, 0)
            suggestions = _read_suggestions(tmp)["suggestions"]
            self.assertEqual(suggestions["feature-1"]["slot_role"], "texture")
            render = suggestions["feature-1"]["intended_render"]
            self.assertAlmostEqual(render["opacity"], 0.35, places=2)
            self.assertIn("grayscale", render["filter"])


class TestOgPhotoDeadAsset(unittest.TestCase):
    def test_og_photo_with_opengraph_image_tsx_yields_dynamic_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = {"images": [{"filename": "og-photo.png",
                                    "publicPath": "/images/og-photo.png"}]}
            files = {
                "src/app/opengraph-image.tsx": '// next/og dynamic OG\n',
            }
            _setup_project(tmp, manifest, files)
            rc, _, _ = _run(tmp)
            self.assertEqual(rc, 0)
            sug = _read_suggestions(tmp)["suggestions"]
            self.assertEqual(sug["og-photo"]["slot_role"], "none")
            self.assertEqual(sug["og-photo"]["production_method"], "dynamic_runtime")
            self.assertEqual(sug["og-photo"]["confidence"], "high")


class TestUnusedAsset(unittest.TestCase):
    def test_no_imports_yields_none_with_recommendation(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = {"images": [{"filename": "ghost.webp",
                                    "publicPath": "/images/ghost.webp"}]}
            files = {
                "src/components/Hero.tsx": (
                    'export function Hero() { return <h1>Hello</h1>; }\n'
                ),
            }
            _setup_project(tmp, manifest, files)
            rc, _, _ = _run(tmp)
            self.assertEqual(rc, 0)
            sug = _read_suggestions(tmp)["suggestions"]
            self.assertEqual(sug["ghost"]["slot_role"], "none")
            self.assertEqual(sug["ghost"]["production_method"], "none")
            self.assertIn("unused", sug["ghost"]["evidence"])


class TestConfidenceFlags(unittest.TestCase):
    def test_clsx_yields_low_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = {"images": [{"filename": "hero.webp",
                                    "publicPath": "/images/hero.webp"}]}
            files = {
                "src/components/Hero.tsx": (
                    'import Image from "next/image";\n'
                    'import { clsx } from "clsx";\n'
                    'export function Hero({ hidden }: { hidden: boolean }) {\n'
                    '  return <Image src="/images/hero.webp"\n'
                    '    className={clsx("opacity-100", hidden && "opacity-0")}\n'
                    '    alt="hero" width={1920} height={1080} />;\n'
                    '}\n'
                ),
            }
            _setup_project(tmp, manifest, files)
            rc, _, _ = _run(tmp)
            self.assertEqual(rc, 0)
            sug = _read_suggestions(tmp)["suggestions"]
            self.assertEqual(sug["hero"]["confidence"], "low")


class TestOutputContract(unittest.TestCase):
    """Round 2 critic Concern 5: output MUST be suggestions sidecar,
    NEVER canonical slot-intent.json."""

    def test_output_writes_suggestions_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = {"images": [{"filename": "hero.webp",
                                    "publicPath": "/images/hero.webp"}]}
            files = {"src/components/Hero.tsx":
                     '<Image src="/images/hero.webp" />\n'}
            _setup_project(tmp, manifest, files)
            rc, _, _ = _run(tmp)
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(os.path.join(
                tmp, ".runs", "slot-intent-migration-suggestions.json")))
            self.assertFalse(os.path.exists(os.path.join(
                tmp, ".runs", "slot-intent.json")))

    def test_output_has_disclaimer(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = {"images": [{"filename": "hero.webp",
                                    "publicPath": "/images/hero.webp"}]}
            files = {"src/components/Hero.tsx":
                     '<Image src="/images/hero.webp" />\n'}
            _setup_project(tmp, manifest, files)
            rc, _, _ = _run(tmp)
            self.assertEqual(rc, 0)
            doc = _read_suggestions(tmp)
            self.assertIn("_disclaimer", doc)
            self.assertIn("SUGGESTIONS", doc["_disclaimer"])
            self.assertEqual(doc["_kind"], "slot-intent-migration-suggestions")


class TestMissingManifest(unittest.TestCase):
    def test_no_manifest_exits_with_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ".runs"), exist_ok=True)
            rc, _, err = _run(tmp)
            self.assertEqual(rc, 1)
            self.assertIn("manifest not found", err)


if __name__ == "__main__":
    unittest.main()
