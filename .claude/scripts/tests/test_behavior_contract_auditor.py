#!/usr/bin/env python3
"""Unit tests for behavior_contract_auditor.py (#1387).

Validates Layer 4a static AST/regex heuristics: api-fetch reachability,
stub-catch detection (literal + parenthesized literal), sitemap iteration
detection, ai-conversation combo check, Phase A sentinel exemption, and
runtime-signal routing.

Run via:
    python3 -m unittest .claude.scripts.tests.test_behavior_contract_auditor
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

REAL_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REAL_REPO, ".claude", "scripts", "lib"))

from behavior_contract_auditor import (  # type: ignore  # noqa: E402
    audit,
    _candidate_page_files,
    _fetch_present,
    _fetch_unreachable,
    _has_stub_catch,
    _has_turn_state,
    _has_any_api_fetch,
    _has_track_call,
    _sitemap_has_iteration,
)


def _mkpage_with_files(root: str, route_path: str, extra_files: list[str] | None = None):
    """Scaffold src/app/<route_path>/page.tsx + optional co-located files."""
    full = os.path.join(root, "src", "app", route_path)
    os.makedirs(full, exist_ok=True)
    with open(os.path.join(full, "page.tsx"), "w") as fh:
        fh.write("export default function P() { return null; }")
    for name in (extra_files or []):
        with open(os.path.join(full, name), "w") as fh:
            fh.write("export function C() { return null; }")


class TestCandidatePageFiles(unittest.TestCase):
    """#1450 gaps 1-2: route-shape resolution via derive_page_set_for_design_critic."""

    def test_static_page_returns_page_tsx(self):
        with tempfile.TemporaryDirectory() as tmp:
            _mkpage_with_files(tmp, "spec-builder")
            files = _candidate_page_files(tmp, "spec-builder")
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].endswith("/spec-builder/page.tsx"))

    def test_non_hyphenated_dynamic_route_variant(self):
        # #1450 gap 1 — canonical case from the issue description:
        # scope='variant', filesystem='src/app/v/[variant]/page.tsx'.
        # The URL static prefix ('v') differs from the scope name
        # ('variant'), so neither direct-name nor static-prefix match
        # would succeed; the dynamic-segments fallback resolves this
        # via derive_pages's `dynamic_segments: ['variant']` field.
        with tempfile.TemporaryDirectory() as tmp:
            _mkpage_with_files(tmp, "v/[variant]", ["variant-client.tsx"])
            files = _candidate_page_files(tmp, "variant")
        self.assertGreaterEqual(
            len(files), 1,
            f"variant case must resolve via dynamic_segments fallback (got: {files})",
        )
        self.assertTrue(
            any(f.endswith("/v/[variant]/page.tsx") for f in files),
            f"page.tsx must be in returned files (got: {files})",
        )
        # Co-located client component must also be included (gap 2 sibling).
        self.assertTrue(
            any(f.endswith("variant-client.tsx") for f in files),
            f"co-located *-client.tsx must be in returned files (got: {files})",
        )

    def test_non_hyphenated_dynamic_route_quote_token(self):
        # #1450 gap 1 — sister case: scope='quote', filesystem=
        # 'src/app/quote/[token]/page.tsx'. Here the URL static prefix
        # ('quote') equals the scope name, so the static-prefix fallback
        # resolves it (the dynamic-segments fallback is also satisfied
        # via [token], but prefix match fires first).
        with tempfile.TemporaryDirectory() as tmp:
            _mkpage_with_files(tmp, "quote/[token]")
            files = _candidate_page_files(tmp, "quote")
        self.assertGreaterEqual(
            len(files), 1,
            f"quote case must resolve via static-prefix or dynamic-segments (got: {files})",
        )
        self.assertTrue(
            any(f.endswith("/quote/[token]/page.tsx") for f in files),
            f"page.tsx must be in returned files (got: {files})",
        )

    def test_dynamic_route_static_prefix_portfolio(self):
        # Gap 1 (hyphenated form): page='portfolio-detail', filesystem
        # is src/app/portfolio/[slug]/page.tsx → discovered as
        # 'portfolio-slug'. Static-prefix match ('portfolio') resolves.
        with tempfile.TemporaryDirectory() as tmp:
            _mkpage_with_files(tmp, "portfolio/[slug]", ["portfolio-client.tsx"])
            files = _candidate_page_files(tmp, "portfolio-detail")
        self.assertGreaterEqual(len(files), 1)
        self.assertTrue(any(f.endswith("/portfolio/[slug]/page.tsx") for f in files))

    def test_includes_colocated_client_tsx(self):
        # Gap 2: co-located *-client.tsx must be in the source list so
        # the event-tracking grep finds the trackCall there.
        with tempfile.TemporaryDirectory() as tmp:
            _mkpage_with_files(
                tmp, "portfolio/[slug]",
                ["portfolio-client.tsx", "portfolio-tracker.tsx"],
            )
            files = _candidate_page_files(tmp, "portfolio-detail")
        # Both nested .tsx files appear.
        self.assertTrue(any("portfolio-client.tsx" in f for f in files))
        self.assertTrue(any("portfolio-tracker.tsx" in f for f in files))

    def test_unresolvable_page_returns_empty(self):
        # No filesystem evidence → returns [].
        with tempfile.TemporaryDirectory() as tmp:
            files = _candidate_page_files(tmp, "nonexistent-page")
        self.assertEqual(files, [])


class TestFetchHeuristics(unittest.TestCase):
    def test_fetch_present_simple(self):
        self.assertTrue(_fetch_present("fetch('/api/x')", "/api/x"))
        self.assertTrue(_fetch_present("fetch(\"/api/x\")", "/api/x"))
        self.assertTrue(_fetch_present("fetch(`/api/x`)", "/api/x"))

    def test_fetch_absent(self):
        self.assertFalse(_fetch_present("const x = 1;", "/api/x"))
        self.assertFalse(_fetch_present("fetch('/api/other')", "/api/x"))

    def test_fetch_unreachable_in_if_false(self):
        src = "if (false) {\n  fetch('/api/x');\n"  # unclosed window
        self.assertTrue(_fetch_unreachable(src, "/api/x"))

    def test_fetch_reachable_after_if_false_closes(self):
        # When the if(false) block closes BEFORE the fetch, fetch is reachable.
        src = "if (false) { /*noop*/ }\nfetch('/api/x');"
        self.assertFalse(_fetch_unreachable(src, "/api/x"))


class TestStubCatchDetection(unittest.TestCase):
    def test_catch_returns_object_literal_paren_wrapped(self):
        # The common JS idiom for returning object literals from arrow fns.
        src = "fetch('/api/x').then(r => r.json()).catch(() => ({ messages: [] }))"
        self.assertTrue(_has_stub_catch(src, "/api/x"))

    def test_catch_returns_array_literal(self):
        src = "fetch('/api/x').catch(() => [])"
        self.assertTrue(_has_stub_catch(src, "/api/x"))

    def test_catch_returns_string_literal(self):
        src = "fetch('/api/x').catch(() => 'fallback')"
        self.assertTrue(_has_stub_catch(src, "/api/x"))

    def test_catch_returns_identifier_caught_when_empty_params(self):
        # Empty-param catch returning identifier — caught by layer (b)
        # (issue #1387 follow-up: previously this was the load-bearing
        # gap that the regex missed entirely).
        src = "const STUB = {}; fetch('/api/x').catch(() => STUB)"
        self.assertTrue(_has_stub_catch(src, "/api/x"))

    def test_catch_returns_function_call_caught_when_empty_params(self):
        # The specific failure pattern from the #1387 issue body.
        src = "fetch('/api/x').catch(() => synthesize_stub_spec_id())"
        self.assertTrue(_has_stub_catch(src, "/api/x"))

    def test_catch_with_err_param_returning_derived_NOT_flagged(self):
        # Parameterized catch with err returning derived data — legitimate
        # error handling (the layer (b) check requires EMPTY params).
        src = "fetch('/api/x').catch(err => err.message)"
        self.assertFalse(_has_stub_catch(src, "/api/x"))

    def test_no_catch_no_detection(self):
        src = "fetch('/api/x').then(r => r.json())"
        self.assertFalse(_has_stub_catch(src, "/api/x"))

    def test_trycatch_block_wrapping_fetch_with_no_throw_caught(self):
        # The issue #1387 likely failure pattern: try/catch around fetch
        # where catch synthesizes a stub instead of re-raising.
        src = """
        async function postSpec(data) {
          try {
            const r = await fetch('/api/x', { method: 'POST', body: data });
            return await r.json();
          } catch {
            return { spec_id: synthesize_stub_id() };
          }
        }
        """
        self.assertTrue(_has_stub_catch(src, "/api/x"))

    def test_trycatch_block_with_throw_NOT_flagged(self):
        # Try/catch that re-raises is legitimate error handling.
        src = """
        async function postSpec(data) {
          try {
            const r = await fetch('/api/x', { method: 'POST', body: data });
            return await r.json();
          } catch (err) {
            console.error('failed', err);
            throw err;
          }
        }
        """
        self.assertFalse(_has_stub_catch(src, "/api/x"))

    def test_fetch_without_try_wrap_NOT_flagged_by_trycatch_layer(self):
        # Bare fetch with no surrounding try block — layer (c) MUST NOT fire.
        src = "const data = await fetch('/api/x').then(r => r.json());"
        self.assertFalse(_has_stub_catch(src, "/api/x"))


class TestTurnStateDetection(unittest.TestCase):
    def test_useState(self):
        self.assertTrue(_has_turn_state("const [t, setT] = useState(0);"))

    def test_useReducer(self):
        self.assertTrue(_has_turn_state("const [s, d] = useReducer(reducer);"))

    def test_useChat(self):
        self.assertTrue(_has_turn_state("const { messages } = useChat();"))

    def test_no_state(self):
        self.assertFalse(_has_turn_state("const x = 1;"))


class TestTrackCallDetection(unittest.TestCase):
    def test_camelcase_helper(self):
        self.assertTrue(_has_track_call("trackPortfolioViewed(props)", "portfolio_viewed"))

    def test_serverEvent_string_form(self):
        self.assertTrue(_has_track_call("trackServerEvent('signup_started', uid)", "signup_started"))


class TestSitemapIterationDetection(unittest.TestCase):
    def _write_sitemap(self, root, src):
        d = os.path.join(root, "src", "app")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "sitemap.ts"), "w") as fh:
            fh.write(src)

    def test_map_iteration(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write_sitemap(tmp, "SLUGS.map((slug) => ({ url: `/x/${slug}` }))")
            self.assertTrue(_sitemap_has_iteration(tmp, "slug"))

    def test_for_const_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write_sitemap(tmp, "for (const slug of SLUGS) { entries.push(slug); }")
            self.assertTrue(_sitemap_has_iteration(tmp, "slug"))

    def test_no_iteration(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write_sitemap(tmp, "return [{ url: '/portfolio' }];")
            self.assertFalse(_sitemap_has_iteration(tmp, "slug"))


class TestAuditEndToEnd(unittest.TestCase):
    """Smoke tests on synthetic projects exercising the full audit() flow."""

    def _scaffold(self, root, contracts, pages):
        """Write contracts JSON + page .tsx files."""
        runs = os.path.join(root, ".runs")
        os.makedirs(runs, exist_ok=True)
        with open(os.path.join(runs, "scaffold-pages-contracts.json"), "w") as fh:
            json.dump(contracts, fh)
        for page, src in pages.items():
            d = os.path.join(root, "src", "app", page)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "page.tsx"), "w") as fh:
                fh.write(src)

    def test_fm1_stub_catch_caught(self):
        contracts = {
            "spec-builder": [
                {"kind": "api-fetch", "arg": "/api/spec-builder/turn",
                 "raw_test": "[audit:api-fetch=/api/spec-builder/turn] AI"},
            ],
            "_schema_version": 2,
            "skill": "bootstrap", "run_id": "test", "written_at": "test",
        }
        with tempfile.TemporaryDirectory() as tmp:
            self._scaffold(tmp, contracts, {
                "spec-builder": (
                    "'use client';\n"
                    "fetch('/api/spec-builder/turn')"
                    "  .catch(() => ({ messages: [] }));\n"
                ),
            })
            result = audit(tmp)
            self.assertEqual(result["uncovered_count"], 1)
            self.assertIn("stub-fallback", result["uncovered"][0]["reason"])

    def test_fm2_missing_slug_iteration_caught(self):
        contracts = {
            "portfolio-detail": [
                {"kind": "sitemap-instance", "arg": "portfolio/slug",
                 "raw_test": "[audit:sitemap-instance=portfolio/slug]"},
            ],
            "_schema_version": 2,
            "skill": "bootstrap", "run_id": "test", "written_at": "test",
        }
        with tempfile.TemporaryDirectory() as tmp:
            # Sitemap.ts WITHOUT slug iteration
            d = os.path.join(tmp, "src", "app")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "sitemap.ts"), "w") as fh:
                fh.write("return [{ url: '/portfolio' }];")
            # Page exists but only static folder; no candidate file is needed
            # for the sitemap check.
            d2 = os.path.join(tmp, "src", "app", "portfolio", "[slug]")
            os.makedirs(d2, exist_ok=True)
            with open(os.path.join(d2, "page.tsx"), "w") as fh:
                fh.write("export default function P() { return null; }")

            runs = os.path.join(tmp, ".runs")
            os.makedirs(runs, exist_ok=True)
            with open(os.path.join(runs, "scaffold-pages-contracts.json"), "w") as fh:
                json.dump(contracts, fh)

            result = audit(tmp)
            self.assertEqual(result["uncovered_count"], 1)
            self.assertIn("no iteration over 'slug'", result["uncovered"][0]["reason"])

    def test_clean_pass_when_contract_met(self):
        contracts = {
            "spec-builder": [
                {"kind": "api-fetch", "arg": "/api/spec-builder/turn",
                 "raw_test": "[audit:api-fetch=/api/spec-builder/turn]"},
            ],
            "_schema_version": 2,
            "skill": "bootstrap", "run_id": "test", "written_at": "test",
        }
        with tempfile.TemporaryDirectory() as tmp:
            self._scaffold(tmp, contracts, {
                "spec-builder": (
                    "import { useState } from 'react';\n"
                    "export default function P() {\n"
                    "  const [data, setData] = useState(null);\n"
                    "  fetch('/api/spec-builder/turn').then(r => r.json()).then(setData);\n"
                    "  return <div>{data}</div>;\n"
                    "}"
                ),
            })
            result = audit(tmp)
            self.assertEqual(result["uncovered_count"], 0)
            self.assertEqual(result["covered_static"], 1)

    def test_untagged_emits_warning_not_finding(self):
        contracts = {
            "signup": [
                {"kind": "untagged", "arg": None, "raw_test": "user signs up"},
            ],
            "_schema_version": 2,
            "skill": "bootstrap", "run_id": "test", "written_at": "test",
        }
        with tempfile.TemporaryDirectory() as tmp:
            self._scaffold(tmp, contracts, {"signup": "export default function S() { return null; }"})
            result = audit(tmp)
            self.assertEqual(result["uncovered_count"], 0)
            self.assertEqual(len(result["warnings"]), 1)
            self.assertEqual(result["warnings"][0]["page"], "signup")

    def test_phase_a_sentinel_exempts_page(self):
        contracts = {
            "spec-builder": [
                {"kind": "api-fetch", "arg": "/api/x",
                 "raw_test": "[audit:api-fetch=/api/x]"},
            ],
            "_schema_version": 2,
            "skill": "bootstrap", "run_id": "test", "written_at": "test",
        }
        with tempfile.TemporaryDirectory() as tmp:
            runs = os.path.join(tmp, ".runs", "gate-verdicts")
            os.makedirs(runs, exist_ok=True)
            with open(os.path.join(runs, "phase-a-sentinel.json"), "w") as fh:
                json.dump({"files": ["src/app/spec-builder/page.tsx"]}, fh)
            self._scaffold(tmp, contracts, {
                "spec-builder": "// Phase-A-owned; no fetch needed",
            })
            result = audit(tmp)
            self.assertEqual(result["uncovered_count"], 0)
            # Sentinel-owned page is exempted entirely — not even audited.
            self.assertEqual(result["audited_pages"], 0)

    def test_runtime_signal_emitted_for_api_fetch_and_ai_conv(self):
        contracts = {
            "p1": [
                {"kind": "api-fetch", "arg": "/api/x",
                 "raw_test": "[audit:api-fetch=/api/x]"},
                {"kind": "ai-conversation", "arg": None,
                 "raw_test": "[audit:ai-conversation]"},
                {"kind": "render", "arg": None,
                 "raw_test": "[audit:render]"},  # NOT signaled to B7
            ],
            "_schema_version": 2,
            "skill": "bootstrap", "run_id": "test", "written_at": "test",
        }
        with tempfile.TemporaryDirectory() as tmp:
            self._scaffold(tmp, contracts, {
                "p1": (
                    "import { useState } from 'react';\n"
                    "const [s, setS] = useState(null);\n"
                    "fetch('/api/x').then(r => r.json()).then(setS);\n"
                ),
            })
            result = audit(tmp)
            signaled_kinds = [
                s["contract"]["kind"] for s in result["runtime_check_signaled"]
            ]
            self.assertIn("api-fetch", signaled_kinds)
            self.assertIn("ai-conversation", signaled_kinds)
            self.assertNotIn("render", signaled_kinds)

    def test_no_contracts_file_returns_empty_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = audit(tmp)
            self.assertEqual(result["uncovered_count"], 0)
            self.assertEqual(result["audited_pages"], 0)


if __name__ == "__main__":
    unittest.main()
