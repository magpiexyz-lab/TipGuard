#!/usr/bin/env python3
"""Unit tests for derive_pages.dynamic_public_pages() (#1387).

Validates:
  - empty result when no behaviors declare dynamic_segments
  - concrete_url=None when filesystem has no matching dynamic route
  - URL substitution when filesystem provides src/app/<base>/[<segment>]/
  - stderr warning when anonymous_allowed=true + dynamic-segment page
    has no dynamic_segments declaration

Run via:
    python3 -m unittest .claude.scripts.tests.test_dynamic_public_pages
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

REAL_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REAL_REPO, ".claude", "scripts", "lib"))

from derive_pages import dynamic_public_pages  # type: ignore  # noqa: E402


def _mkpage(root: str, route_path: str, contents: str = "export default function P(){return null;}"):
    """Create src/app/<route_path>/page.tsx with the given contents."""
    full = os.path.join(root, "src", "app", route_path)
    os.makedirs(full, exist_ok=True)
    with open(os.path.join(full, "page.tsx"), "w") as fh:
        fh.write(contents)


class TestDynamicPublicPages(unittest.TestCase):
    def test_empty_when_no_dynamic_segments(self):
        result = dynamic_public_pages({"behaviors": [{"id": "b", "pages": ["a"]}]})
        self.assertEqual(result, [])

    def test_no_anonymous_allowed_skipped(self):
        exp = {
            "behaviors": [
                {"id": "b", "pages": ["portfolio-detail"],
                 "dynamic_segments": {"slug": ["a"]}}
                # anonymous_allowed not set → default false → skipped
            ]
        }
        result = dynamic_public_pages(exp)
        self.assertEqual(result, [])

    def test_concrete_url_substitution_when_route_discoverable(self):
        exp = {
            "behaviors": [
                {"id": "b-13", "pages": ["portfolio-detail"],
                 "anonymous_allowed": True,
                 "dynamic_segments": {"slug": ["a", "b"]}},
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            _mkpage(tmp, "portfolio/[slug]")
            result = dynamic_public_pages(exp, tmp)
        self.assertEqual(len(result), 2)
        urls = {e["concrete_url"] for e in result}
        self.assertEqual(urls, {"/portfolio/a", "/portfolio/b"})

    def test_concrete_url_none_when_no_matching_route(self):
        exp = {
            "behaviors": [
                {"id": "b", "pages": ["nonexistent"],
                 "anonymous_allowed": True,
                 "dynamic_segments": {"slug": ["a"]}},
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            result = dynamic_public_pages(exp, tmp)
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]["concrete_url"])
        self.assertIsNone(result[0]["route_pattern"])

    def test_warning_emitted_when_dynamic_page_lacks_declaration(self):
        # anonymous_allowed=true + page maps to a discovered dynamic route
        # but behavior has no dynamic_segments → stderr warning fires.
        exp = {
            "behaviors": [
                {"id": "b", "pages": ["portfolio-detail"],
                 "anonymous_allowed": True},
                # dynamic_segments missing
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            _mkpage(tmp, "portfolio/[slug]")
            stderr = io.StringIO()
            with patch("sys.stderr", stderr):
                result = dynamic_public_pages(exp, tmp)
            self.assertEqual(result, [])
            self.assertIn("lacks dynamic_segments declaration", stderr.getvalue())

    def test_multiple_segments(self):
        exp = {
            "behaviors": [
                {"id": "b", "pages": ["entries-detail"],
                 "anonymous_allowed": True,
                 "dynamic_segments": {
                     "kind": ["news", "blog"],
                     "slug": ["a", "b"],
                 }},
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            # Page file with single [slug] — only `slug` substitutes.
            _mkpage(tmp, "entries/[slug]")
            result = dynamic_public_pages(exp, tmp)
        # Both segments emit entries; only `slug` produces concrete_url.
        slug_entries = [e for e in result if e["segment"] == "slug"]
        kind_entries = [e for e in result if e["segment"] == "kind"]
        self.assertEqual(len(slug_entries), 2)
        self.assertEqual(len(kind_entries), 2)
        for e in slug_entries:
            self.assertIsNotNone(e["concrete_url"])
        for e in kind_entries:
            # `kind` segment isn't in the route, so no concretization.
            self.assertIsNone(e["concrete_url"])

    def test_sort_order_deterministic(self):
        exp = {
            "behaviors": [
                {"id": "b", "pages": ["portfolio-detail"],
                 "anonymous_allowed": True,
                 "dynamic_segments": {"slug": ["c", "a", "b"]}},
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            _mkpage(tmp, "portfolio/[slug]")
            result = dynamic_public_pages(exp, tmp)
        values = [e["value"] for e in result]
        self.assertEqual(values, sorted(values))


if __name__ == "__main__":
    unittest.main()
