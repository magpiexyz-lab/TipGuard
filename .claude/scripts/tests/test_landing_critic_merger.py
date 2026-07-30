#!/usr/bin/env python3
"""test_landing_critic_merger.py — Smoke tests for merge-landing-critic-traces.py (#1468).

Covers:
  1. Both sub-traces present + complete → aggregate with all required fields
  2. sections-critic partial → aggregate partial=true, degraded_reason populated
  3. images-critic sanctioned-skip + recovery_validated → aggregate propagates self-degraded
  4. images-critic sparse (init-stub) → merger logs warning, aggregate skips fields gracefully
  5. Missing one sub-trace → exit 1 with clear error
  6. Field ownership: min_score from sections, candidates_tried from images

Run: python3 .claude/scripts/tests/test_landing_critic_merger.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_MERGER = os.path.normpath(os.path.join(
    _HERE, "..", "merge-landing-critic-traces.py"))

_PASS = 0
_FAIL = 0


def _t(name: str, cond: bool, hint: str = "") -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  PASS  {name}")
    else:
        _FAIL += 1
        print(f"  FAIL  {name}")
        if hint:
            print(f"        {hint}")


def _build_fixture(root: str, sections: dict | None, images: dict | None,
                   run_id: str = "test-run-1") -> None:
    """Create a fixture worktree with `sections` and `images` sub-traces."""
    traces = os.path.join(root, ".runs", "agent-traces")
    os.makedirs(traces, exist_ok=True)
    if sections is not None:
        with open(os.path.join(traces, "landing-sections-critic.json"), "w") as fh:
            json.dump(sections, fh)
    if images is not None:
        with open(os.path.join(traces, "landing-images-critic.json"), "w") as fh:
            json.dump(images, fh)
    with open(os.path.join(root, ".runs", "verify-context.json"), "w") as fh:
        json.dump({"skill": "verify", "run_id": run_id}, fh)


def _run(root: str) -> tuple[int, str, str]:
    proc = subprocess.run(["python3", _MERGER], cwd=root,
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def _load_aggregate(root: str) -> dict | None:
    p = os.path.join(root, ".runs", "agent-traces", "design-critic-landing.json")
    if not os.path.isfile(p):
        return None
    return json.load(open(p))


# ----------------------------------------------------------------------------

def test_happy_path() -> None:
    print("\n[test_happy_path]")
    with tempfile.TemporaryDirectory() as root:
        sections = {
            "agent": "landing-sections-critic", "verdict": "pass", "result": "clean",
            "status": "completed", "provenance": "self", "partial": False,
            "pages_reviewed": 1, "page": "landing",
            "min_score": 9, "sections_below_8": 0, "weakest_page": "landing",
            "pre_existing_debt": [], "image_issues_for_landing": [],
            "checks_performed": ["layer1_functional", "layer2_taste", "layer3_antipattern_sections"],
            "review_method": "rendered-demo",
            "fixes": [{"file": "src/app/landing/page.tsx", "fix": "improved CTA"}],
            "workarounds": [], "template_gap_observed": [],
        }
        images = {
            "agent": "landing-images-critic", "verdict": "pass", "result": "fixed",
            "status": "completed", "provenance": "self", "partial": False,
            "pages_reviewed": 1, "page": "landing",
            "candidates_tried": 3, "new_candidates_generated": 0,
            "unresolved_images": [], "image_scores": [], "image_fixes": 2,
            "images_evaluated": 4,
            "checks_performed": ["image_candidate_confirmation", "layer3_image_antipattern"],
            "review_method": "rendered-demo",
            "fixes": [{"file": "public/images/hero.png", "fix": "swapped to candidate b"}],
            "workarounds": [], "template_gap_observed": [],
        }
        _build_fixture(root, sections, images)
        rc, stdout, stderr = _run(root)
        _t("merger exits 0", rc == 0, f"rc={rc} stderr={stderr}")
        agg = _load_aggregate(root)
        _t("aggregate written", agg is not None)
        if agg:
            _t("agent=design-critic", agg.get("agent") == "design-critic")
            _t("provenance=lead-merge", agg.get("provenance") == "lead-merge")
            _t("min_score from sections (9)", agg.get("min_score") == 9)
            _t("candidates_tried from images (3)", agg.get("candidates_tried") == 3)
            _t("image_fixes from images (2)", agg.get("image_fixes") == 2)
            _t("fixes concatenated (2 total)", len(agg.get("fixes", [])) == 2)
            _t("page=landing", agg.get("page") == "landing")
            _t("sub_traces declared",
               set(agg.get("sub_traces", [])) ==
               {"landing-sections-critic.json", "landing-images-critic.json"})
            _t("AOC v1.3 workarounds present", "workarounds" in agg)
            _t("AOC v1.3 template_gap_observed present",
               "template_gap_observed" in agg)


def test_sections_partial() -> None:
    print("\n[test_sections_partial]")
    with tempfile.TemporaryDirectory() as root:
        sections = {
            "agent": "landing-sections-critic", "verdict": "unresolved", "result": None,
            "status": "completed", "provenance": "self-degraded", "partial": True,
            "degraded_reason": "turn-budget-exhausted-layer2",
            "pages_reviewed": 1, "page": "landing",
            "min_score": 6, "sections_below_8": 3, "weakest_page": "landing",
            "checks_performed": ["layer1_functional", "layer2_taste"],
            "workarounds": [], "template_gap_observed": [],
        }
        images = {
            "agent": "landing-images-critic", "verdict": "pass", "result": "clean",
            "status": "completed", "provenance": "self", "partial": False,
            "pages_reviewed": 1, "page": "landing",
            "candidates_tried": 3, "image_fixes": 0,
            "checks_performed": ["image_candidate_confirmation"],
            "workarounds": [], "template_gap_observed": [],
        }
        _build_fixture(root, sections, images)
        rc, _, _ = _run(root)
        _t("merger exits 0", rc == 0)
        agg = _load_aggregate(root)
        if agg:
            _t("aggregate partial=true", agg.get("partial") is True)
            _t("verdict=unresolved (worst-of)",
               agg.get("verdict") == "unresolved")
            _t("degraded_reason mentions sections",
               "sections:" in (agg.get("degraded_reason") or ""))


def test_images_sanctioned_skip_propagates() -> None:
    """When images-critic was sanctioned-skipped with recovery_validated=True,
    the aggregate should propagate `provenance=self-degraded` + `recovery_validated=true`
    so the legacy state-registry.json line 22 landing_sd check accepts."""
    print("\n[test_images_sanctioned_skip_propagates]")
    with tempfile.TemporaryDirectory() as root:
        sections = {
            "agent": "landing-sections-critic", "verdict": "pass", "result": "clean",
            "status": "completed", "provenance": "self", "partial": False,
            "pages_reviewed": 1, "page": "landing",
            "min_score": 9, "sections_below_8": 0,
            "checks_performed": ["layer1_functional"],
            "workarounds": [], "template_gap_observed": [],
        }
        images = {
            "agent": "landing-images-critic", "verdict": "pass", "result": None,
            "status": "completed", "provenance": "self-degraded", "partial": True,
            "degraded_reason": "empty-boundary-fast-path",
            "recovery_validated": True,
            "pages_reviewed": 1, "page": "landing",
            "candidates_tried": 0,
            "checks_performed": ["import-chain-check"],
            "workarounds": [], "template_gap_observed": [],
        }
        _build_fixture(root, sections, images)
        rc, _, _ = _run(root)
        _t("merger exits 0", rc == 0)
        agg = _load_aggregate(root)
        if agg:
            _t("provenance propagated to self-degraded",
               agg.get("provenance") == "self-degraded",
               f"got {agg.get('provenance')!r}")
            _t("recovery_validated=true propagated",
               agg.get("recovery_validated") is True)
            _t("degraded_reason includes images:empty-boundary-fast-path",
               "empty-boundary-fast-path" in (agg.get("degraded_reason") or ""))


def test_sparse_sub_trace_warning() -> None:
    print("\n[test_sparse_sub_trace_warning]")
    with tempfile.TemporaryDirectory() as root:
        # sections-critic init-stub survived
        sections = {"agent": "landing-sections-critic", "status": "started",
                    "timestamp": "2026-05-18T11:00:00Z", "run_id": "test-run-1"}
        images = {
            "agent": "landing-images-critic", "verdict": "pass", "result": "clean",
            "status": "completed", "provenance": "self", "partial": False,
            "pages_reviewed": 1, "page": "landing",
            "candidates_tried": 3, "image_fixes": 0,
            "checks_performed": ["image_candidate_confirmation"],
            "workarounds": [], "template_gap_observed": [],
        }
        _build_fixture(root, sections, images)
        rc, stdout, stderr = _run(root)
        _t("merger exits 0 (does not crash on sparse)", rc == 0,
           f"rc={rc} stderr={stderr}")
        _t("warning mentions sparse",
           "sparse" in stderr.lower(), f"stderr={stderr!r}")
        agg = _load_aggregate(root)
        if agg:
            _t("aggregate partial=true (sparse → partial)",
               agg.get("partial") is True)


def test_missing_one_subtrace() -> None:
    print("\n[test_missing_one_subtrace]")
    with tempfile.TemporaryDirectory() as root:
        sections = {
            "agent": "landing-sections-critic", "verdict": "pass", "result": "clean",
            "status": "completed", "provenance": "self", "partial": False,
            "pages_reviewed": 1, "page": "landing",
            "min_score": 9, "workarounds": [], "template_gap_observed": [],
        }
        _build_fixture(root, sections, None)  # No images-critic
        rc, _, stderr = _run(root)
        _t("missing images-critic → exit 1", rc == 1, f"rc={rc}")
        _t("stderr mentions missing", "missing" in stderr.lower(),
           f"stderr={stderr!r}")


def main() -> int:
    test_happy_path()
    test_sections_partial()
    test_images_sanctioned_skip_propagates()
    test_sparse_sub_trace_warning()
    test_missing_one_subtrace()
    print()
    print(f"=== {_PASS} passed, {_FAIL} failed ===")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
