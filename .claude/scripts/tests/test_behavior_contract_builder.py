#!/usr/bin/env python3
"""Unit tests for behavior_contract_builder.py (#1387).

Validates directive token parsing, page-keyed contract assembly, known vs
unknown verb tagging, and roadmap-verb flagging. Run via:
    python3 -m unittest .claude.scripts.tests.test_behavior_contract_builder
or via:
    bash .claude/scripts/tests/run-all.sh
"""
from __future__ import annotations

import os
import sys
import unittest

REAL_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REAL_REPO, ".claude", "scripts", "lib"))

from behavior_contract_builder import (  # type: ignore  # noqa: E402
    SCHEMA_VERSION,
    build_contracts,
    parse_test_entry,
    _KNOWN_KINDS,
    _ROADMAP_KINDS,
)


class TestParseTestEntry(unittest.TestCase):
    def test_no_directive(self):
        self.assertEqual(parse_test_entry("plain prose"), [])

    def test_known_verb_api_fetch(self):
        entries = parse_test_entry(
            "[audit:api-fetch=/api/spec-builder/turn] AI asks 5 questions"
        )
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["kind"], "api-fetch")
        self.assertEqual(entries[0]["arg"], "/api/spec-builder/turn")
        self.assertNotIn("unknown_kind", entries[0])
        self.assertNotIn("roadmap", entries[0])

    def test_known_verb_no_arg(self):
        entries = parse_test_entry("[audit:ai-conversation] multi-turn surface")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["kind"], "ai-conversation")
        self.assertIsNone(entries[0]["arg"])

    def test_known_verb_event_with_event_key(self):
        # Registry uses `event` verb, NOT `event-emit`. This test prevents
        # silent re-introduction of the old name.
        entries = parse_test_entry("[audit:event=signup_started] user clicks")
        self.assertEqual(entries[0]["kind"], "event")
        self.assertNotIn("unknown_kind", entries[0])

    def test_unknown_kind_tagged(self):
        # event-emit was the old name; should now flag as unknown.
        entries = parse_test_entry("[audit:event-emit=foo] legacy form")
        self.assertEqual(entries[0]["kind"], "event-emit")
        self.assertTrue(entries[0].get("unknown_kind"))

    def test_roadmap_verb_flagged(self):
        entries = parse_test_entry("[audit:sdk-call=stripe] Stripe Elements")
        self.assertEqual(entries[0]["kind"], "sdk-call")
        self.assertTrue(entries[0].get("roadmap"))

    def test_multiple_directives_in_one_entry(self):
        entries = parse_test_entry(
            "User sees portfolio [audit:api-fetch=/api/portfolio] "
            "[audit:event=portfolio_viewed]"
        )
        self.assertEqual(len(entries), 2)
        self.assertEqual({e["kind"] for e in entries}, {"api-fetch", "event"})

    def test_sitemap_instance_with_segment(self):
        entries = parse_test_entry(
            "[audit:sitemap-instance=portfolio/slug] each fixture slug indexed"
        )
        self.assertEqual(entries[0]["kind"], "sitemap-instance")
        self.assertEqual(entries[0]["arg"], "portfolio/slug")


class TestKnownKindsRegistryAlignment(unittest.TestCase):
    """Verify the in-code KNOWN_KINDS set matches audit-verb-registry.json."""

    def test_known_kinds_set_includes_pr_additions(self):
        # These are the verbs THIS PR (#1387) adds to the registry.
        for v in ("sitemap-instance", "ai-conversation", "render"):
            self.assertIn(v, _KNOWN_KINDS)

    def test_known_kinds_set_includes_pre_existing_registry_verbs(self):
        for v in ("api-fetch", "event", "seo"):
            self.assertIn(v, _KNOWN_KINDS)

    def test_event_emit_is_NOT_a_known_kind(self):
        # Regression guard: registry uses `event`, NOT `event-emit`.
        self.assertNotIn("event-emit", _KNOWN_KINDS)

    def test_roadmap_kinds_disjoint_from_known(self):
        # Roadmap kinds (sdk-call, realtime-sub, external-widget) MUST NOT
        # also be in KNOWN_KINDS — they are explicitly deferred.
        self.assertFalse(_ROADMAP_KINDS & _KNOWN_KINDS)


class TestBuildContracts(unittest.TestCase):
    def _experiment(self, behaviors):
        return {"behaviors": behaviors}

    def test_empty_experiment(self):
        result = build_contracts({})
        # Only meta keys.
        non_meta = [k for k in result if not k.startswith("_")]
        self.assertEqual(non_meta, [])
        self.assertEqual(result["_schema_version"], SCHEMA_VERSION)

    def test_page_keyed_output(self):
        exp = self._experiment([
            {"id": "b-03", "pages": ["spec-builder"], "tests": [
                "[audit:api-fetch=/api/spec-builder/turn] AI asks",
                "[audit:ai-conversation] multi-turn",
            ]},
        ])
        result = build_contracts(exp)
        self.assertIn("spec-builder", result)
        self.assertEqual(len(result["spec-builder"]), 2)
        kinds = {e["kind"] for e in result["spec-builder"]}
        self.assertEqual(kinds, {"api-fetch", "ai-conversation"})

    def test_multi_page_behavior_distributes_entries(self):
        exp = self._experiment([
            {"id": "b-x", "pages": ["a", "b"], "tests": [
                "[audit:render] simple render",
            ]},
        ])
        result = build_contracts(exp)
        self.assertEqual(len(result["a"]), 1)
        self.assertEqual(len(result["b"]), 1)
        self.assertEqual(result["a"][0]["kind"], "render")

    def test_untagged_test_emits_untagged_entry(self):
        exp = self._experiment([
            {"id": "b-04", "pages": ["signup"], "tests": ["user signs up"]},
        ])
        result = build_contracts(exp)
        self.assertEqual(result["signup"][0]["kind"], "untagged")
        self.assertEqual(result["_summary"]["untagged_count"], 1)
        self.assertEqual(result["_summary"]["tagged_count"], 0)

    def test_summary_counts_tagged_untagged_unknown_roadmap(self):
        exp = self._experiment([
            {"id": "b-1", "pages": ["p1"], "tests": [
                "[audit:api-fetch=/api/x] tagged",
                "[audit:event-emit=foo] unknown form",  # unknown_kind
                "[audit:sdk-call=stripe] roadmap",      # roadmap
                "plain prose",                            # untagged
            ]},
        ])
        s = build_contracts(exp)["_summary"]
        self.assertEqual(s["tagged_count"], 3)
        self.assertEqual(s["untagged_count"], 1)
        self.assertEqual(s["unknown_kind_count"], 1)
        self.assertEqual(s["roadmap_count"], 1)

    def test_no_behaviors_pages_yields_no_entries(self):
        # Behaviors without `pages` are skipped (no scaffold-pages target).
        exp = self._experiment([
            {"id": "b-x", "tests": ["[audit:api-fetch=/api/y] noop"]},
        ])
        result = build_contracts(exp)
        self.assertEqual(
            [k for k in result if not k.startswith("_")], []
        )

    def test_no_tests_field_yields_no_entries(self):
        exp = self._experiment([
            {"id": "b-x", "pages": ["only-page"]},
        ])
        result = build_contracts(exp)
        self.assertEqual(
            [k for k in result if not k.startswith("_")], []
        )


if __name__ == "__main__":
    unittest.main()
