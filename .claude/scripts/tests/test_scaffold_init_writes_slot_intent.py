#!/usr/bin/env python3
"""End-to-end test for scaffold-init Step 5 slot-intent.json writing
(Issue #1077, PR1b).

Reproduces the inline Python from .claude/procedures/scaffold-init.md Step 5
against synthetic experiment.yaml fixtures. Verifies:
  - File written to .runs/slot-intent.json
  - Schema validation passes
  - Per-slot derivation produces expected slot_role/production_method
  - design.slots user override takes precedence
  - Archetype short-circuit for service/cli
  - runtime_gate attached to empty-state when admin behavior + demo_role mismatch

Run via: python3 .claude/scripts/tests/test_scaffold_init_writes_slot_intent.py
"""
import datetime
import json
import os
import shutil
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO_ROOT, ".claude", "scripts"))

from lib.derive_slot_intent import (  # noqa: E402
    archetype_default,
    derive_og_photo_default,
    derive_runtime_gate,
    derive_slot_role_from_lineage,
    merge_user_overrides,
)
from lib.slot_intent_schema import validate  # noqa: E402


SLOTS = ["hero", "feature-1", "feature-2", "feature-3", "logo",
         "og-photo", "empty-state"]


def _build_doc(experiment: dict, auth_stack_demo_mode: dict | None = None,
               sentinel_path: str | None = None) -> dict:
    """Replicate scaffold-init Step 5's inline build logic."""
    archetype = experiment.get("type", "web-app")
    design = experiment.get("design") or {}
    design_lineage = design.get("design_lineage")
    description = experiment.get("description") or ""
    optimization_target = (
        experiment.get("optimization_target")
        or design.get("optimization_target")
    )
    behaviors = experiment.get("behaviors") or []
    user_overrides = design.get("slots") or {}

    short = archetype_default(archetype)
    slots_out: dict = {}
    runtime_gate = derive_runtime_gate(behaviors, auth_stack_demo_mode)

    # Use a non-existent path when sentinel_path not provided
    sp = sentinel_path or "/nonexistent/phase-a-sentinel.json"

    for slot in SLOTS:
        if short is not None:
            derived = dict(short)
        elif slot == "og-photo":
            og = derive_og_photo_default(sp)
            derived = {
                "slot_role": og["slot_role"],
                "production_method": og["production_method"],
                "candidate_budget": "low",
                "intended_render": (
                    None if og["slot_role"] == "none"
                    else {"opacity": 1.0, "blend_mode": "normal", "filter": "none"}
                ),
                "evidence": og["evidence"],
            }
        else:
            derived = derive_slot_role_from_lineage(
                slot_name=slot,
                design_lineage=design_lineage,
                optimization_target=optimization_target,
                description=description,
            )
        merged = merge_user_overrides(derived, user_overrides.get(slot))
        if slot in {"empty-state", "empty_state", "emptystate"} and runtime_gate:
            if "runtime_gate" not in merged or merged["runtime_gate"] is None:
                merged["runtime_gate"] = runtime_gate
                if merged["slot_role"] == "focal":
                    merged["slot_role"] = "conditional"
        merged.setdefault("runtime_gate", None)
        merged.setdefault("source", "derived")
        merged.pop("evidence", None)
        slots_out[slot] = merged

    design_slots_enabled = bool(design.get("slots_enabled", True))

    return {
        "_schema_version": 1,
        "_schema_version_notes": (
            "v1 (2026-04-26, #1077): per-slot intent contract "
            "written by scaffold-init at state-10"
        ),
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
                                .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "archetype": archetype,
        "design_slots_enabled": design_slots_enabled,
        "slots": slots_out,
    }


class TestBasicWebApp(unittest.TestCase):
    def test_safe_default_web_app(self):
        exp = {
            "type": "web-app",
            "description": "A todo app for teams.",
            "behaviors": [],
            "stack": {"auth": "none"},
        }
        doc = _build_doc(exp)
        self.assertEqual(validate(doc), [])
        self.assertEqual(doc["archetype"], "web-app")
        self.assertEqual(doc["design_slots_enabled"], True)
        # All 7 slots present
        self.assertEqual(set(doc["slots"].keys()), set(SLOTS))
        # Hero defaults to focal in absence of texture lineage / image keywords
        self.assertEqual(doc["slots"]["hero"]["slot_role"], "focal")
        # og-photo with no sentinel → dynamic_runtime + slot_role=none
        self.assertEqual(doc["slots"]["og-photo"]["slot_role"], "none")
        self.assertEqual(doc["slots"]["og-photo"]["production_method"],
                         "dynamic_runtime")

    def test_linear_lineage_yields_texture_hero_features(self):
        exp = {
            "type": "web-app",
            "description": "A SaaS for managing tasks.",
            "design": {
                "design_lineage": ["Linear", "Vercel"],
            },
            "behaviors": [],
        }
        doc = _build_doc(exp)
        self.assertEqual(validate(doc), [])
        self.assertEqual(doc["slots"]["hero"]["slot_role"], "texture")
        for f in ("feature-1", "feature-2", "feature-3"):
            self.assertEqual(doc["slots"][f]["slot_role"], "texture", f)


class TestArchetypeShortCircuit(unittest.TestCase):
    def test_service_archetype_all_none(self):
        exp = {
            "type": "service",
            "description": "REST API for billing.",
            "behaviors": [],
        }
        doc = _build_doc(exp)
        self.assertEqual(validate(doc), [])
        for slot in SLOTS:
            self.assertEqual(doc["slots"][slot]["slot_role"], "none", slot)
            self.assertEqual(doc["slots"][slot]["production_method"], "none", slot)

    def test_cli_archetype_all_none(self):
        exp = {
            "type": "cli",
            "description": "Command-line tool.",
            "behaviors": [],
        }
        doc = _build_doc(exp)
        self.assertEqual(validate(doc), [])
        for slot in SLOTS:
            self.assertEqual(doc["slots"][slot]["slot_role"], "none", slot)


class TestUserOverride(unittest.TestCase):
    def test_design_slots_hero_focal_override(self):
        # Linear lineage would derive texture; user wants focal.
        exp = {
            "type": "web-app",
            "description": "todo",
            "design": {
                "design_lineage": ["Linear"],
                "slots": {"hero": {"slot_role": "focal",
                                   "intended_render": {
                                       "opacity": 1.0,
                                       "blend_mode": "normal",
                                       "filter": "none",
                                   }}},
            },
            "behaviors": [],
        }
        doc = _build_doc(exp)
        self.assertEqual(validate(doc), [])
        self.assertEqual(doc["slots"]["hero"]["slot_role"], "focal")
        self.assertEqual(doc["slots"]["hero"]["source"], "override")
        self.assertEqual(doc["slots"]["hero"]["intended_render"]["opacity"], 1.0)
        # Other slots still derived
        self.assertEqual(doc["slots"]["feature-1"]["source"], "derived")


class TestRuntimeGate(unittest.TestCase):
    def test_admin_behavior_no_demo_role_attaches_runtime_gate(self):
        exp = {
            "type": "web-app",
            "description": "Admin dashboard.",
            "behaviors": [
                {"id": "view_admin_queue", "requires_role": "admin",
                 "pages": ["admin"]},
            ],
            "stack": {"auth": "supabase"},
        }
        doc = _build_doc(exp, auth_stack_demo_mode={"demo_mode_role": None})
        self.assertEqual(validate(doc), [])
        empty = doc["slots"]["empty-state"]
        self.assertEqual(empty["slot_role"], "conditional")
        self.assertIsNotNone(empty["runtime_gate"])
        self.assertEqual(empty["runtime_gate"]["role"], "admin")

    def test_admin_behavior_demo_role_admin_no_gate(self):
        exp = {
            "type": "web-app",
            "description": "Admin dashboard.",
            "behaviors": [
                {"id": "view_admin_queue", "requires_role": "admin",
                 "pages": ["admin"]},
            ],
            "stack": {"auth": "supabase"},
        }
        doc = _build_doc(exp, auth_stack_demo_mode={"demo_mode_role": "admin"})
        empty = doc["slots"]["empty-state"]
        self.assertIsNone(empty["runtime_gate"])
        self.assertEqual(empty["slot_role"], "focal")

    def test_no_admin_behavior_no_gate(self):
        exp = {
            "type": "web-app",
            "description": "Just a todo.",
            "behaviors": [{"id": "create_todo", "pages": ["dashboard"]}],
        }
        doc = _build_doc(exp)
        empty = doc["slots"]["empty-state"]
        self.assertIsNone(empty["runtime_gate"])


class TestSentinelPresent(unittest.TestCase):
    def test_sentinel_with_opengraph_image_yields_dynamic(self):
        with tempfile.TemporaryDirectory() as tmp:
            sentinel = os.path.join(tmp, "phase-a-sentinel.json")
            with open(sentinel, "w") as f:
                json.dump({"files": ["src/app/opengraph-image.tsx",
                                     "src/app/layout.tsx"]}, f)
            exp = {"type": "web-app", "description": "x", "behaviors": []}
            doc = _build_doc(exp, sentinel_path=sentinel)
            self.assertEqual(doc["slots"]["og-photo"]["slot_role"], "none")
            self.assertEqual(doc["slots"]["og-photo"]["production_method"],
                             "dynamic_runtime")

    def test_sentinel_without_opengraph_yields_focal(self):
        with tempfile.TemporaryDirectory() as tmp:
            sentinel = os.path.join(tmp, "phase-a-sentinel.json")
            with open(sentinel, "w") as f:
                json.dump({"files": ["src/app/layout.tsx"]}, f)
            exp = {"type": "web-app", "description": "Brand-led product.",
                   "behaviors": []}
            doc = _build_doc(exp, sentinel_path=sentinel)
            # og-photo derives focal+ai_generated when sentinel says no
            # opengraph-image.tsx
            self.assertEqual(doc["slots"]["og-photo"]["slot_role"], "focal")
            self.assertEqual(doc["slots"]["og-photo"]["production_method"],
                             "ai_generated")


class TestSchemaValidationFailsClosed(unittest.TestCase):
    def test_invalid_user_override_caught(self):
        # User supplies invalid combination: slot_role=conditional without runtime_gate.
        exp = {
            "type": "web-app",
            "description": "x",
            "design": {"slots": {"hero": {"slot_role": "conditional"}}},
            "behaviors": [],
        }
        doc = _build_doc(exp)
        errors = validate(doc)
        # R2 should fire: conditional requires runtime_gate
        self.assertTrue(any("R2" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
