#!/usr/bin/env python3
"""Tests for null/unresolved render_context handling (Issue #1077, PR3).

Closes Round 2 critic Concern 7: when clsx/cn/cva or dynamic className
makes effective_weight unresolvable, severity must be INFO with a
secondary 'unresolved-class-expression' finding signal — NOT silent PASS
or false-BLOCK.

Run via: python3 .claude/scripts/tests/test_drift_null_unresolved.py
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
TOOL = os.path.join(REPO_ROOT, ".claude", "scripts",
                   "check-slot-intent-drift.py")


def _run(cwd: str) -> tuple[int, dict]:
    r = subprocess.run([sys.executable, TOOL], cwd=cwd,
                       capture_output=True, text=True)
    report_path = os.path.join(cwd, ".runs", "drift-report.json")
    with open(report_path) as f:
        return r.returncode, json.load(f)


def _setup(tmp: str, slot_intent: dict, src_files: dict):
    os.makedirs(os.path.join(tmp, ".runs"), exist_ok=True)
    with open(os.path.join(tmp, ".runs/slot-intent.json"), "w") as f:
        json.dump(slot_intent, f)
    for path, content in src_files.items():
        full = os.path.join(tmp, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(content)


def _slot_intent(slots: dict) -> dict:
    return {
        "_schema_version": 1,
        "design_slots_enabled": True,
        "archetype": "web-app",
        "slots": slots,
    }


class TestClsxYieldsInfo(unittest.TestCase):
    def test_clsx_branches_yield_info_not_block(self):
        # focal × clsx with conflicting branches → INFO (cannot statically resolve)
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp,
                _slot_intent({
                    "hero": {
                        "slot_role": "focal",
                        "production_method": "ai_generated",
                        "intended_render": {"opacity": 1.0,
                                            "blend_mode": "normal",
                                            "filter": "none"},
                        "candidate_budget": "high",
                        "runtime_gate": None,
                        "source": "derived",
                    },
                }),
                {"src/components/Hero.tsx": (
                    'import { clsx } from "clsx";\n'
                    'export function Hero({hidden}: {hidden:boolean}) {\n'
                    '  return <Image src="/images/hero.webp"\n'
                    '    className={clsx("opacity-100", hidden && "opacity-0")} />;\n'
                    '}\n'
                )},
            )
            rc, report = _run(tmp)
            self.assertEqual(rc, 0)
            # No BLOCK
            self.assertEqual(report["block_count"], 0)
            # At least one INFO with mention of clsx/unresolvable
            infos = [f for f in report["findings"] if f["severity"] == "INFO"]
            self.assertGreater(len(infos), 0)
            self.assertTrue(any("clsx" in f["message"].lower()
                                or "unresolvable" in f["message"].lower()
                                or "manual" in f["message"].lower()
                                for f in infos))


class TestCvaYieldsInfo(unittest.TestCase):
    def test_cva_variant_yields_info(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp,
                _slot_intent({
                    "hero": {
                        "slot_role": "focal",
                        "production_method": "ai_generated",
                        "intended_render": {"opacity": 1.0,
                                            "blend_mode": "normal",
                                            "filter": "none"},
                        "candidate_budget": "high",
                        "runtime_gate": None,
                        "source": "derived",
                    },
                }),
                {"src/components/Hero.tsx": (
                    'export function Hero() {\n'
                    '  return <Image src="/images/hero.webp"\n'
                    '    className={imageVariants({variant: "ghost"})} />;\n'
                    '}\n'
                )},
            )
            rc, report = _run(tmp)
            self.assertEqual(rc, 0)
            self.assertEqual(report["block_count"], 0)
            infos = [f for f in report["findings"] if f["severity"] == "INFO"]
            self.assertGreater(len(infos), 0)


class TestStaticHighConfidence(unittest.TestCase):
    """Sanity: static className still produces high-confidence detection."""

    def test_static_string_no_info(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp,
                _slot_intent({
                    "hero": {
                        "slot_role": "focal",
                        "production_method": "ai_generated",
                        "intended_render": {"opacity": 1.0,
                                            "blend_mode": "normal",
                                            "filter": "none"},
                        "candidate_budget": "high",
                        "runtime_gate": None,
                        "source": "derived",
                    },
                }),
                {"src/components/Hero.tsx":
                    '<Image src="/images/hero.webp" className="opacity-100" />\n'},
            )
            rc, report = _run(tmp)
            self.assertEqual(rc, 0)
            # Should be PASS, not INFO
            passes = [f for f in report["findings"] if f["severity"] == "PASS"]
            self.assertEqual(len(passes), 1)
            self.assertEqual(passes[0]["observed"]["confidence"], "high")


if __name__ == "__main__":
    unittest.main()
