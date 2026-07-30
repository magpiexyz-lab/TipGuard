#!/usr/bin/env python3
"""Tests for archetype_default() (Issue #1077, PR1a).

Service and CLI archetypes do NOT run the image pipeline. archetype_default()
returns a slot descriptor that uniformly sets slot_role=none for these,
short-circuiting per-slot derivation entirely.

Run via: python3 .claude/scripts/tests/test_archetype_short_circuit.py
"""
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO_ROOT, ".claude", "scripts"))

from lib.derive_slot_intent import archetype_default  # noqa: E402
from lib.slot_intent_schema import is_valid  # noqa: E402


class TestWebApp(unittest.TestCase):
    def test_web_app_returns_none_proceed_with_per_slot(self):
        self.assertIsNone(archetype_default("web-app"))


class TestService(unittest.TestCase):
    def test_service_short_circuits_to_none(self):
        out = archetype_default("service")
        self.assertEqual(out["slot_role"], "none")
        self.assertEqual(out["production_method"], "none")
        self.assertIsNone(out["intended_render"])
        self.assertEqual(out["candidate_budget"], "low")

    def test_service_evidence_cites_archetype(self):
        out = archetype_default("service")
        self.assertIn("service", out["evidence"])
        self.assertIn("none", out["evidence"])


class TestCli(unittest.TestCase):
    def test_cli_short_circuits_to_none(self):
        out = archetype_default("cli")
        self.assertEqual(out["slot_role"], "none")
        self.assertEqual(out["production_method"], "none")
        self.assertIsNone(out["intended_render"])

    def test_cli_evidence_cites_archetype(self):
        out = archetype_default("cli")
        self.assertIn("cli", out["evidence"])


class TestDescriptorSchemaCompliance(unittest.TestCase):
    """The short-circuit descriptor must produce a slot-intent.json that
    PASSES the schema validator (so PR1b can write a valid file for
    service/cli archetypes)."""

    def _build_doc(self, archetype: str, descriptor: dict) -> dict:
        # Add the schema-required `source` field that scaffold-init populates.
        slot = dict(descriptor)
        slot["runtime_gate"] = None
        slot["source"] = "derived"
        return {
            "_schema_version": 1,
            "_schema_version_notes": "v1 (test)",
            "generated_at": "2026-04-26T00:00:00Z",
            "archetype": archetype,
            "design_slots_enabled": True,
            "slots": {"hero": slot},
        }

    def test_service_descriptor_schema_valid(self):
        out = archetype_default("service")
        doc = self._build_doc("service", out)
        self.assertTrue(is_valid(doc), "service descriptor must pass schema")

    def test_cli_descriptor_schema_valid(self):
        out = archetype_default("cli")
        doc = self._build_doc("cli", out)
        self.assertTrue(is_valid(doc), "cli descriptor must pass schema")


class TestUnknownArchetype(unittest.TestCase):
    def test_unknown_archetype_short_circuits(self):
        # Defensive: any non-web-app archetype short-circuits.
        out = archetype_default("mobile")
        self.assertEqual(out["slot_role"], "none")
        self.assertEqual(out["production_method"], "none")


if __name__ == "__main__":
    unittest.main()
