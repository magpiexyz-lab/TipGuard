#!/usr/bin/env python3
"""Tests for merge_user_overrides() (Issue #1077, PR1a).

experiment.yaml.design.slots.<slot>: {...} provides per-key user overrides.
Recognized keys overwrite derived values; unknown keys are ignored; the
'source' field is set to 'override' when any recognized key was supplied.

Run via: python3 .claude/scripts/tests/test_design_slots_override.py
"""
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO_ROOT, ".claude", "scripts"))

from lib.derive_slot_intent import merge_user_overrides  # noqa: E402


_BASE_DERIVED = {
    "slot_role": "texture",
    "production_method": "ai_generated",
    "candidate_budget": "low",
    "intended_render": {"opacity": 0.08, "blend_mode": "luminosity",
                        "filter": "none"},
    "evidence": "Linear/Vercel lineage → texture",
}


class TestNoOverride(unittest.TestCase):
    def test_none_overrides_yields_derived_source(self):
        merged = merge_user_overrides(_BASE_DERIVED, None)
        self.assertEqual(merged["source"], "derived")
        self.assertEqual(merged["slot_role"], "texture")

    def test_empty_dict_yields_derived(self):
        merged = merge_user_overrides(_BASE_DERIVED, {})
        self.assertEqual(merged["source"], "derived")


class TestSlotRoleOverride(unittest.TestCase):
    def test_user_promotes_texture_to_focal(self):
        merged = merge_user_overrides(
            _BASE_DERIVED, {"slot_role": "focal"}
        )
        self.assertEqual(merged["slot_role"], "focal")
        self.assertEqual(merged["source"], "override")

    def test_user_demotes_focal_to_none(self):
        derived = {**_BASE_DERIVED, "slot_role": "focal"}
        merged = merge_user_overrides(derived, {"slot_role": "none"})
        self.assertEqual(merged["slot_role"], "none")
        self.assertEqual(merged["source"], "override")


class TestPartialOverride(unittest.TestCase):
    def test_only_candidate_budget_overridden(self):
        merged = merge_user_overrides(
            _BASE_DERIVED, {"candidate_budget": "high"}
        )
        self.assertEqual(merged["candidate_budget"], "high")
        # Other fields untouched
        self.assertEqual(merged["slot_role"], _BASE_DERIVED["slot_role"])
        self.assertEqual(merged["production_method"],
                         _BASE_DERIVED["production_method"])
        self.assertEqual(merged["source"], "override")

    def test_intended_render_overridden(self):
        new_render = {"opacity": 1.0, "blend_mode": "normal", "filter": "none"}
        merged = merge_user_overrides(
            _BASE_DERIVED, {"intended_render": new_render}
        )
        self.assertEqual(merged["intended_render"], new_render)
        self.assertEqual(merged["source"], "override")

    def test_runtime_gate_added(self):
        gate = {"role": "admin", "reason": "manual", "evidence": "user-decided"}
        merged = merge_user_overrides(
            _BASE_DERIVED, {"runtime_gate": gate}
        )
        self.assertEqual(merged["runtime_gate"], gate)
        self.assertEqual(merged["source"], "override")


class TestUnknownKeys(unittest.TestCase):
    def test_unknown_key_ignored(self):
        merged = merge_user_overrides(
            _BASE_DERIVED, {"weird_key": "weird_value"}
        )
        self.assertNotIn("weird_key", merged)
        # Source stays 'derived' because no recognized override was applied
        self.assertEqual(merged["source"], "derived")

    def test_mixed_known_and_unknown(self):
        merged = merge_user_overrides(
            _BASE_DERIVED, {"slot_role": "focal", "unknown": "x"}
        )
        self.assertEqual(merged["slot_role"], "focal")
        self.assertNotIn("unknown", merged)
        self.assertEqual(merged["source"], "override")


class TestNonDictOverrides(unittest.TestCase):
    def test_string_treated_as_no_override(self):
        merged = merge_user_overrides(_BASE_DERIVED, "not-a-dict")
        self.assertEqual(merged["source"], "derived")

    def test_list_treated_as_no_override(self):
        merged = merge_user_overrides(_BASE_DERIVED, ["a", "b"])
        self.assertEqual(merged["source"], "derived")


class TestPreservesEvidence(unittest.TestCase):
    def test_evidence_preserved_through_override(self):
        merged = merge_user_overrides(
            _BASE_DERIVED, {"slot_role": "focal"}
        )
        self.assertEqual(merged["evidence"], _BASE_DERIVED["evidence"])


if __name__ == "__main__":
    unittest.main()
