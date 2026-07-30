#!/usr/bin/env python3
"""Unit tests for emit-sitemap.py (#1387).

Validates deterministic output: same experiment.yaml + repo state yields
byte-identical src/app/sitemap.ts.

Run via:
    python3 .claude/scripts/tests/test_emit_sitemap.py
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest

REAL_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
# emit-sitemap.py has a hyphen in its filename — load via spec.
EMIT_PATH = os.path.join(REAL_REPO, ".claude", "scripts", "lib", "emit-sitemap.py")
spec = importlib.util.spec_from_file_location("emit_sitemap", EMIT_PATH)
emit_sitemap = importlib.util.module_from_spec(spec)
sys.path.insert(0, os.path.join(REAL_REPO, ".claude", "scripts", "lib"))
spec.loader.exec_module(emit_sitemap)


def _mkpage(root: str, route_path: str):
    full = os.path.join(root, "src", "app", route_path)
    os.makedirs(full, exist_ok=True)
    with open(os.path.join(full, "page.tsx"), "w") as fh:
        fh.write("export default function P() { return null; }")


class TestEmitSitemap(unittest.TestCase):
    def test_empty_experiment_yields_landing_only(self):
        out = emit_sitemap.emit({}, ".")
        self.assertIn("`${b}/`", out)
        self.assertNotIn("spec-builder", out)

    def test_static_pages_emitted(self):
        # #1450 gap 3: emit-sitemap now sources route shape from the
        # filesystem via derive_page_set_for_design_critic, so the test
        # scaffolds the page.tsx files (matching production where scaffold-pages
        # writes pages before emit-sitemap runs at state-11c).
        exp = {
            "stack": {"auth": "supabase"},
            "behaviors": [
                {"id": "b", "pages": ["spec-builder", "portfolio"]},
            ],
            "golden_path": [{"step": "1", "page": "landing"}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            _mkpage(tmp, "spec-builder")
            _mkpage(tmp, "portfolio")
            _mkpage(tmp, "login")
            _mkpage(tmp, "signup")
            out = emit_sitemap.emit(exp, tmp)
        # Static pages — sourced from filesystem-resolved routes.
        self.assertIn("/spec-builder", out)
        self.assertIn("/portfolio", out)
        self.assertIn("/login", out)   # auth-derived
        self.assertIn("/signup", out)  # auth-derived

    def test_dynamic_route_emits_concretized_url_not_page_name(self):
        # #1450 gap 3 regression: experiment.yaml says page=variant but
        # the filesystem route is /v/[variant]. The OLD emit-sitemap wrote
        # /variant (wrong); the NEW emit-sitemap writes /v/<test_url>.
        exp = {"behaviors": [{"id": "b", "pages": ["variant"]}]}
        with tempfile.TemporaryDirectory() as tmp:
            _mkpage(tmp, "v/[variant]")
            out = emit_sitemap.emit(exp, tmp)
        self.assertNotIn(" `${b}/variant`", out)
        # The synthetic test URL is whatever derive_pages substitutes for
        # [variant]; assert the /v/ prefix is present.
        self.assertIn(" `${b}/v/", out)

    def test_dynamic_route_quote_token(self):
        # Sister case to gap 1: page=quote → /quote/[token].
        exp = {"behaviors": [{"id": "b", "pages": ["quote"]}]}
        with tempfile.TemporaryDirectory() as tmp:
            _mkpage(tmp, "quote/[token]")
            out = emit_sitemap.emit(exp, tmp)
        # No bare /quote entry — must be concretized.
        self.assertNotRegex(out, r"`\$\{b\}/quote`")
        self.assertIn(" `${b}/quote/", out)

    def test_no_duplicate_portfolio_slug_entries(self):
        # #1450 gap 3 second-half: portfolio-detail historically produced
        # duplicate /portfolio/<slug> entries. Updated post-#1467 to assert
        # against the new emission shape: slug literals live in a const
        # fixture array (emitted once) and URLs are constructed at runtime
        # via .map((slug) => ({ url: `${b}/portfolio/${slug}`, ... })).
        exp = {
            "behaviors": [
                {"id": "b", "pages": ["portfolio-detail"],
                 "anonymous_allowed": True,
                 "dynamic_segments": {"slug": ["alpha"]}},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            _mkpage(tmp, "portfolio/[slug]")
            out = emit_sitemap.emit(exp, tmp)
        # No literal-bracket leak.
        self.assertNotIn("[slug]", out)
        # Slug literal appears exactly once in the fixture array.
        self.assertEqual(out.count('"alpha"'), 1)
        # The .map iteration over the fixture array appears exactly once.
        self.assertEqual(out.count(".map((slug) =>"), 1)
        # Template-literal URL template appears in the .map() body.
        self.assertIn("/portfolio/${slug}", out)

    def test_dynamic_segment_urls_emitted_when_route_exists(self):
        # Post-#1467: behavior_contract_auditor._sitemap_has_iteration
        # requires the sitemap to expand dynamic fixtures via
        # .map / for / forEach with the contract segment as the arrow
        # parameter. The slug literals MUST also appear (auditor
        # _sitemap_contains_slug greps for slug strings anywhere in src).
        exp = {
            "behaviors": [
                {"id": "b-13", "pages": ["portfolio-detail"],
                 "anonymous_allowed": True,
                 "dynamic_segments": {"slug": ["alpha", "beta"]}},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            _mkpage(tmp, "portfolio/[slug]")
            out = emit_sitemap.emit(exp, tmp)
        # Slug literals are present in the fixture array.
        self.assertIn('"alpha"', out)
        self.assertIn('"beta"', out)
        # The .map() iteration constructs the per-slug URLs at runtime.
        self.assertIn(".map((slug) =>", out)
        self.assertIn("/portfolio/${slug}", out)

    def test_dynamic_segment_skipped_when_route_absent(self):
        # No src/app/portfolio/[slug] → concrete_url is None → no
        # fixture array emitted. The slug literal MUST NOT appear (no
        # fallback emission).
        exp = {
            "behaviors": [
                {"id": "b-13", "pages": ["portfolio-detail"],
                 "anonymous_allowed": True,
                 "dynamic_segments": {"slug": ["alpha"]}},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            out = emit_sitemap.emit(exp, tmp)
        self.assertNotIn('"alpha"', out)
        self.assertNotIn(".map((slug) =>", out)

    def test_deterministic_output(self):
        # Same input → byte-identical output.
        exp = {
            "behaviors": [{"id": "b", "pages": ["a", "b"]}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            out1 = emit_sitemap.emit(exp, tmp)
            out2 = emit_sitemap.emit(exp, tmp)
        self.assertEqual(out1, out2)

    def test_output_is_valid_ts_metadata_route_shape(self):
        out = emit_sitemap.emit({}, ".")
        self.assertIn("import type { MetadataRoute } from 'next';", out)
        self.assertIn("export default function sitemap(): MetadataRoute.Sitemap", out)
        # Each entry has the required shape.
        self.assertIn("lastModified: now", out)
        self.assertIn("changeFrequency:", out)
        self.assertIn("priority:", out)


if __name__ == "__main__":
    unittest.main()
