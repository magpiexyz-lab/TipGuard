#!/usr/bin/env python3
"""Tests for render_context.py — CSS/className parser (Issue #1077, PR3).

Covers:
  - Tailwind opacity classes (opacity-N)
  - Arbitrary opacity (opacity-[0.055], opacity-[5%])
  - CSS-style arbitrary ([opacity:0.5])
  - Mix-blend-mode classes
  - Inline style={{}} extraction
  - Filter classes (grayscale, brightness-N)
  - clsx/cva → confidence='low'
  - effective_weight computation
  - severity_for_drift table

Run via: python3 .claude/scripts/tests/test_render_context.py
"""
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO_ROOT, ".claude", "scripts"))

from lib.render_context import (  # noqa: E402
    compute_effective_weight,
    extract_render_from_text,
    severity_for_drift,
)


class TestOpacityExtraction(unittest.TestCase):
    def test_arbitrary_opacity_decimal(self):
        text = '<Image className="opacity-[0.055]" src="/x" />'
        render, conf = extract_render_from_text(text)
        self.assertAlmostEqual(render["opacity"], 0.055, places=3)
        self.assertEqual(conf, "high")

    def test_arbitrary_opacity_percent(self):
        text = '<Image className="opacity-[5%]" />'
        render, _ = extract_render_from_text(text)
        self.assertAlmostEqual(render["opacity"], 0.05, places=3)

    def test_css_style_arbitrary(self):
        text = '<Image className="[opacity:0.35]" />'
        render, _ = extract_render_from_text(text)
        self.assertAlmostEqual(render["opacity"], 0.35, places=2)

    def test_tailwind_opacity_50(self):
        text = '<Image className="opacity-50" />'
        render, _ = extract_render_from_text(text)
        self.assertEqual(render["opacity"], 0.5)

    def test_tailwind_opacity_100_default(self):
        text = '<Image className="text-white" />'
        render, _ = extract_render_from_text(text)
        self.assertEqual(render["opacity"], 1.0)  # no opacity class → default

    def test_inline_style_opacity_overrides_class(self):
        text = '<Image className="opacity-50" style={{opacity: 0.1}} />'
        render, _ = extract_render_from_text(text)
        self.assertAlmostEqual(render["opacity"], 0.1, places=2)


class TestBlendMode(unittest.TestCase):
    def test_mix_blend_luminosity(self):
        text = '<Image className="mix-blend-luminosity" />'
        render, _ = extract_render_from_text(text)
        self.assertEqual(render["blend_mode"], "luminosity")

    def test_mix_blend_normal_default(self):
        text = '<Image className="opacity-100" />'
        render, _ = extract_render_from_text(text)
        self.assertEqual(render["blend_mode"], "normal")

    def test_inline_blend_mode_overrides(self):
        text = ('<Image className="mix-blend-multiply" '
                'style={{mixBlendMode: "screen"}} />')
        render, _ = extract_render_from_text(text)
        self.assertEqual(render["blend_mode"], "screen")


class TestFilters(unittest.TestCase):
    def test_grayscale_bare(self):
        text = '<Image className="grayscale" />'
        render, _ = extract_render_from_text(text)
        self.assertIn("grayscale(1)", render["filter"])

    def test_brightness_75(self):
        text = '<Image className="brightness-75" />'
        render, _ = extract_render_from_text(text)
        self.assertIn("brightness(0.75)", render["filter"])

    def test_combined_grayscale_brightness(self):
        text = '<Image className="grayscale brightness-75" />'
        render, _ = extract_render_from_text(text)
        self.assertIn("grayscale(1)", render["filter"])
        self.assertIn("brightness(0.75)", render["filter"])

    def test_no_filter_yields_none(self):
        text = '<Image className="opacity-100" />'
        render, _ = extract_render_from_text(text)
        self.assertEqual(render["filter"], "none")


class TestConfidence(unittest.TestCase):
    def test_clsx_yields_low(self):
        text = ('<Image className={clsx("opacity-100", '
                'hidden && "opacity-0")} />')
        _, conf = extract_render_from_text(text)
        self.assertEqual(conf, "low")

    def test_cn_yields_low(self):
        text = '<Image className={cn("opacity-50")} />'
        _, conf = extract_render_from_text(text)
        self.assertEqual(conf, "low")

    def test_cva_yields_low(self):
        text = '<Image className={imageVariants({variant: "ghost"})} />'
        _, conf = extract_render_from_text(text)
        # cva detected via cva regex + dynamic className regex
        self.assertEqual(conf, "low")

    def test_static_string_yields_high(self):
        text = '<Image className="opacity-50 mix-blend-multiply" />'
        _, conf = extract_render_from_text(text)
        self.assertEqual(conf, "high")


class TestEffectiveWeight(unittest.TestCase):
    def test_full_opacity_normal_blend_no_filter(self):
        w = compute_effective_weight({"opacity": 1.0, "blend_mode": "normal",
                                      "filter": "none"})
        self.assertEqual(w, 1.0)

    def test_hero_case_055_luminosity(self):
        w = compute_effective_weight({"opacity": 0.055, "blend_mode": "luminosity",
                                      "filter": "none"})
        # 0.055 × 0.3 = ~0.0165
        self.assertAlmostEqual(w, 0.0165, places=3)

    def test_feature_case_grayscale_brightness(self):
        w = compute_effective_weight({"opacity": 0.35, "blend_mode": "normal",
                                      "filter": "grayscale(1) brightness(0.75)"})
        # 0.35 × 1.0 × 0.5 (grayscale) × 0.75 (brightness) = ~0.131
        self.assertAlmostEqual(w, 0.131, places=2)

    def test_null_yields_none(self):
        self.assertIsNone(compute_effective_weight(None))

    def test_blur_reduces(self):
        w_no_blur = compute_effective_weight({"opacity": 1.0,
                                             "blend_mode": "normal",
                                             "filter": "none"})
        w_blur = compute_effective_weight({"opacity": 1.0,
                                          "blend_mode": "normal",
                                          "filter": "blur(8px)"})
        self.assertLess(w_blur, w_no_blur)


class TestSeverityTable(unittest.TestCase):
    def test_focal_low_weight_blocks(self):
        sev, msg = severity_for_drift("focal", 0.1, {}, has_image_in_jsx=True)
        self.assertEqual(sev, "BLOCK")

    def test_focal_high_weight_passes(self):
        sev, _ = severity_for_drift("focal", 0.9, {}, has_image_in_jsx=True)
        self.assertEqual(sev, "PASS")

    def test_focal_exactly_05_passes(self):
        sev, _ = severity_for_drift("focal", 0.5, {}, has_image_in_jsx=True)
        self.assertEqual(sev, "PASS")

    def test_texture_low_weight_passes(self):
        sev, _ = severity_for_drift("texture", 0.1, {}, has_image_in_jsx=True)
        self.assertEqual(sev, "PASS")

    def test_texture_high_weight_warns(self):
        sev, _ = severity_for_drift("texture", 0.9, {}, has_image_in_jsx=True)
        self.assertEqual(sev, "WARN")

    def test_watermark_in_band_passes(self):
        sev, _ = severity_for_drift("watermark", 0.5, {}, has_image_in_jsx=True)
        self.assertEqual(sev, "PASS")

    def test_watermark_outside_band_warns(self):
        sev, _ = severity_for_drift("watermark", 0.95, {}, has_image_in_jsx=True)
        self.assertEqual(sev, "WARN")
        sev, _ = severity_for_drift("watermark", 0.1, {}, has_image_in_jsx=True)
        self.assertEqual(sev, "WARN")

    def test_conditional_returns_info(self):
        sev, _ = severity_for_drift("conditional", 0.5, {}, has_image_in_jsx=True)
        self.assertEqual(sev, "INFO")

    def test_none_with_image_blocks(self):
        sev, _ = severity_for_drift("none", 1.0, {}, has_image_in_jsx=True)
        self.assertEqual(sev, "BLOCK")

    def test_none_without_image_passes(self):
        sev, _ = severity_for_drift("none", None, {}, has_image_in_jsx=False)
        self.assertEqual(sev, "PASS")

    def test_null_weight_yields_info(self):
        sev, _ = severity_for_drift("focal", None, {}, has_image_in_jsx=True)
        self.assertEqual(sev, "INFO")


if __name__ == "__main__":
    unittest.main()
