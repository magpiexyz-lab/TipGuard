#!/usr/bin/env python3
"""Schema validation tests for .runs/slot-intent.json (Issue #1077, PR1a).

Covers:
  - Pass: minimal valid doc + all variants of slot_role × production_method
  - Fail: missing required fields, invalid enums, oneOf rejection rules R1-R5

Run via: python3 .claude/scripts/tests/test_slot_intent_schema.py
"""
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO_ROOT, ".claude", "scripts"))

from lib.slot_intent_schema import is_valid, validate  # noqa: E402


def _slot(
    slot_role="focal",
    production_method="ai_generated",
    intended_render=None,
    candidate_budget="medium",
    runtime_gate=None,
    source="derived",
):
    if intended_render is None and production_method == "ai_generated":
        intended_render = {"opacity": 1.0, "blend_mode": "normal", "filter": "none"}
    return {
        "slot_role": slot_role,
        "production_method": production_method,
        "intended_render": intended_render,
        "candidate_budget": candidate_budget,
        "runtime_gate": runtime_gate,
        "source": source,
    }


def _doc(slots):
    return {
        "_schema_version": 1,
        "_schema_version_notes": "v1 (2026-04-26, #1077)",
        "generated_at": "2026-04-26T00:00:00Z",
        "archetype": "web-app",
        "design_slots_enabled": True,
        "slots": slots,
    }


class TestPasses(unittest.TestCase):
    def test_minimal_valid(self):
        doc = _doc({"hero": _slot()})
        self.assertEqual(validate(doc), [])

    def test_all_archetype_values(self):
        for arch in ("web-app", "service", "cli"):
            doc = _doc({"hero": _slot(slot_role="none",
                                      production_method="none",
                                      intended_render=None)})
            doc["archetype"] = arch
            self.assertTrue(is_valid(doc), f"{arch}: {validate(doc)}")

    def test_texture_slot(self):
        doc = _doc({"hero": _slot(
            slot_role="texture",
            intended_render={"opacity": 0.08, "blend_mode": "luminosity",
                             "filter": "none"},
            candidate_budget="low",
        )})
        self.assertTrue(is_valid(doc), validate(doc))

    def test_dynamic_runtime_og(self):
        doc = _doc({"og-photo": _slot(
            slot_role="none",
            production_method="dynamic_runtime",
            intended_render=None,
        )})
        self.assertTrue(is_valid(doc), validate(doc))

    def test_conditional_with_runtime_gate(self):
        doc = _doc({"empty-state": _slot(
            slot_role="conditional",
            production_method="ai_generated",
            intended_render={"opacity": 1.0, "blend_mode": "normal",
                             "filter": "none"},
            runtime_gate={
                "role": "admin",
                "reason": "demo user lacks admin metadata",
                "evidence": "experiment.yaml.behaviors[admin_dashboard].requires_role",
            },
        )})
        self.assertTrue(is_valid(doc), validate(doc))


class TestRequiredFields(unittest.TestCase):
    def test_missing_top_level(self):
        for missing in ("_schema_version", "archetype",
                        "design_slots_enabled", "slots"):
            doc = _doc({"hero": _slot()})
            del doc[missing]
            errors = validate(doc)
            self.assertTrue(
                any(missing in e for e in errors),
                f"missing {missing} not flagged: {errors}",
            )

    def test_wrong_schema_version(self):
        doc = _doc({"hero": _slot()})
        doc["_schema_version"] = 2
        self.assertFalse(is_valid(doc))

    def test_invalid_archetype(self):
        doc = _doc({"hero": _slot()})
        doc["archetype"] = "mobile"
        self.assertFalse(is_valid(doc))

    def test_missing_slot_field(self):
        for missing in ("slot_role", "production_method", "intended_render",
                        "candidate_budget", "runtime_gate", "source"):
            slot = _slot()
            del slot[missing]
            errors = validate(_doc({"hero": slot}))
            self.assertTrue(
                any(f"slots.hero.{missing}" in e for e in errors),
                f"missing {missing} not flagged: {errors}",
            )


class TestInvalidEnums(unittest.TestCase):
    def test_bad_slot_role(self):
        self.assertFalse(is_valid(_doc({"hero": _slot(slot_role="primary")})))

    def test_bad_production_method(self):
        self.assertFalse(is_valid(_doc({"hero": _slot(
            production_method="midjourney")})))

    def test_bad_candidate_budget(self):
        self.assertFalse(is_valid(_doc({"hero": _slot(
            candidate_budget="extreme")})))

    def test_bad_source(self):
        self.assertFalse(is_valid(_doc({"hero": _slot(source="ai")})))

    def test_opacity_out_of_range(self):
        slot = _slot(intended_render={"opacity": 1.5, "blend_mode": "normal",
                                      "filter": "none"})
        self.assertFalse(is_valid(_doc({"hero": slot})))

    def test_opacity_negative(self):
        slot = _slot(intended_render={"opacity": -0.1, "blend_mode": "normal",
                                      "filter": "none"})
        self.assertFalse(is_valid(_doc({"hero": slot})))


class TestOneOfRejections(unittest.TestCase):
    def test_R1_none_with_ai_generated(self):
        slot = _slot(slot_role="none", production_method="ai_generated",
                     intended_render=None)
        errors = validate(_doc({"hero": slot}))
        self.assertTrue(any("R1" in e for e in errors), errors)

    def test_R1_none_with_intended_render(self):
        slot = _slot(slot_role="none", production_method="none",
                     intended_render={"opacity": 1.0, "blend_mode": "normal",
                                      "filter": "none"})
        errors = validate(_doc({"hero": slot}))
        self.assertTrue(any("R1" in e for e in errors), errors)

    def test_R1_none_with_runtime_gate(self):
        slot = _slot(slot_role="none", production_method="none",
                     intended_render=None,
                     runtime_gate={"role": "admin", "reason": "x", "evidence": "y"})
        errors = validate(_doc({"hero": slot}))
        self.assertTrue(any("R1" in e for e in errors), errors)

    def test_R2_conditional_without_runtime_gate(self):
        slot = _slot(slot_role="conditional", production_method="ai_generated",
                     runtime_gate=None)
        errors = validate(_doc({"empty-state": slot}))
        self.assertTrue(any("R2" in e for e in errors), errors)

    def test_R3_ai_generated_without_intended_render(self):
        # Construct directly to bypass _slot()'s auto-fill of intended_render
        slot = {
            "slot_role": "focal",
            "production_method": "ai_generated",
            "intended_render": None,
            "candidate_budget": "medium",
            "runtime_gate": None,
            "source": "derived",
        }
        errors = validate(_doc({"hero": slot}))
        self.assertTrue(any("R3" in e for e in errors), errors)

    def test_R4_dynamic_runtime_with_focal(self):
        slot = _slot(slot_role="focal", production_method="dynamic_runtime",
                     intended_render={"opacity": 1.0, "blend_mode": "normal",
                                      "filter": "none"})
        errors = validate(_doc({"og-photo": slot}))
        self.assertTrue(any("R4" in e for e in errors), errors)

    def test_R5_production_none_with_focal(self):
        slot = _slot(slot_role="focal", production_method="none",
                     intended_render=None)
        errors = validate(_doc({"hero": slot}))
        self.assertTrue(any("R5" in e for e in errors), errors)


class TestStructure(unittest.TestCase):
    def test_root_must_be_object(self):
        self.assertFalse(is_valid([]))
        self.assertFalse(is_valid("string"))

    def test_slots_must_be_object(self):
        doc = _doc({})
        doc["slots"] = []
        self.assertFalse(is_valid(doc))

    def test_design_slots_enabled_must_be_bool(self):
        doc = _doc({"hero": _slot()})
        doc["design_slots_enabled"] = "true"
        self.assertFalse(is_valid(doc))


if __name__ == "__main__":
    unittest.main()
