#!/usr/bin/env python3
"""test_oarc_matcher.py — OARC (Observation-Anchored Recovery Contract) tests.

Closes #1468 + #1456. Covers:

  recovery_skip_extraction matcher:
    1. Sparse-trace init-stub survived → emit sparse-trace event
    2. Sparse-trace lead-orchestrated missing AOC v1.3 fields → emit
    3. Sparse-trace lead-orchestrated with all AOC v1.3 fields → no emit
    4. Recovery-path-skip self-degraded + landing + unused candidates → emit
    5. Sanctioned skip (empty-boundary-fast-path) → no emit
    6. Sanctioned skip (demo-mode-fixture-short-circuit) → no emit
    7. Sanctioned skip (redirect-source-only) → no emit
    8. provenance=self (non-fallback) → no emit
    9. partial=false → no emit
    10. Absent image-candidates.json → no emit (no contract)
    11. has_images=false non-landing → no emit
    12. Non-landing has_images=true missing image_issues_for_landing → emit

  enumerator candidates:
    13. _candidates_from_sparse_traces detects survivors
    14. _candidates_from_recovery_skips detects unsanctioned partial traces
    15. candidate_id stable across runs (deterministic hash)

Run: python3 .claude/scripts/tests/test_oarc_matcher.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_LIB = os.path.normpath(os.path.join(_HERE, "..", "lib"))
sys.path.insert(0, _LIB)

from gate_evidence_runner import apply_matcher  # type: ignore


_PASS = 0
_FAIL = 0
_NAMES: list[tuple[str, bool]] = []


def _t(name: str, cond: bool, hint: str = "") -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        _NAMES.append((name, True))
        print(f"  PASS  {name}")
    else:
        _FAIL += 1
        _NAMES.append((name, False))
        print(f"  FAIL  {name}")
        if hint:
            print(f"        {hint}")


def _rule(target_kinds: list[str]) -> dict:
    return {"matcher": {"kind": "recovery_skip_extraction", "params": {"target_kinds": target_kinds}}}


# ----------------------------------------------------------------------------
# Sparse-trace detection
# ----------------------------------------------------------------------------

def test_sparse_init_stub_survived() -> None:
    print("\n[test_sparse_init_stub_survived]")
    rows = [{
        "path": ".runs/agent-traces/solve-critic.json",
        "content": {"agent": "solve-critic", "status": "started",
                    "timestamp": "2026-05-18T11:00:00Z", "run_id": "r1"},
    }]
    out = apply_matcher(_rule(["sparse-trace"]), rows)
    _t("init-stub emits 1 sparse-trace event", len(out) == 1,
       f"got {len(out)} events: {out}")
    if out:
        _t("event kind=sparse-trace", out[0].get("kind") == "sparse-trace")
        _t("event shape=init-stub-survived",
           out[0].get("shape") == "init-stub-survived")


def test_lead_orchestrated_missing_aoc_v13() -> None:
    print("\n[test_lead_orchestrated_missing_aoc_v13]")
    rows = [{
        "path": ".runs/agent-traces/foo.json",
        "content": {"agent": "foo", "provenance": "lead-orchestrated",
                    "verdict": "pass", "run_id": "r1",
                    # Missing workarounds + template_gap_observed
                    },
    }]
    out = apply_matcher(_rule(["sparse-trace"]), rows)
    _t("lead-orchestrated missing AOC v1.3 → 1 event", len(out) == 1,
       f"got {out}")
    if out:
        _t("shape=lead-orchestrated-missing-aoc-v1.3",
           out[0].get("shape") == "lead-orchestrated-missing-aoc-v1.3")


def test_lead_orchestrated_complete() -> None:
    print("\n[test_lead_orchestrated_complete]")
    rows = [{
        "path": ".runs/agent-traces/foo.json",
        "content": {"agent": "foo", "provenance": "lead-orchestrated",
                    "verdict": "pass", "run_id": "r1",
                    "workarounds": [], "template_gap_observed": []},
    }]
    out = apply_matcher(_rule(["sparse-trace"]), rows)
    _t("lead-orchestrated with AOC v1.3 fields → 0 events", len(out) == 0,
       f"got {out}")


# ----------------------------------------------------------------------------
# Recovery-path-skip detection
# ----------------------------------------------------------------------------

def test_recovery_skip_landing_unused_candidates() -> None:
    print("\n[test_recovery_skip_landing_unused_candidates]")
    rows = [
        {"path": ".runs/agent-traces/design-critic-landing.json",
         "content": {"agent": "design-critic", "provenance": "self-degraded",
                     "partial": True, "degraded_reason": "turn-budget-exhausted",
                     "page": "landing", "candidates_tried": 0,
                     "unresolved_images": []}},
        {"path": ".runs/image-candidates.json",
         "content": {"landing": {"hero": {"candidates": ["a.jpg", "b.jpg", "c.jpg"]}}}},
    ]
    out = apply_matcher(_rule(["recovery-path-skip"]), rows)
    _t("landing partial with unused candidates → 1 event", len(out) == 1,
       f"got {out}")
    if out:
        _t("skipped_check=step-5.5-image-candidate-inspection",
           out[0].get("skipped_check") == "step-5.5-image-candidate-inspection")


def test_sanctioned_skip_empty_boundary() -> None:
    print("\n[test_sanctioned_skip_empty_boundary]")
    rows = [
        {"path": ".runs/agent-traces/design-critic-landing.json",
         "content": {"agent": "design-critic", "provenance": "self-degraded",
                     "partial": True, "degraded_reason": "empty-boundary-fast-path",
                     "page": "landing", "candidates_tried": 0}},
        {"path": ".runs/image-candidates.json",
         "content": {"landing": {"hero": {"candidates": ["a", "b"]}}}},
    ]
    out = apply_matcher(_rule(["recovery-path-skip"]), rows)
    _t("sanctioned empty-boundary-fast-path → 0 events", len(out) == 0, f"got {out}")


def test_sanctioned_skip_demo_mode() -> None:
    print("\n[test_sanctioned_skip_demo_mode]")
    rows = [
        {"path": ".runs/agent-traces/design-critic-landing.json",
         "content": {"agent": "design-critic", "provenance": "self-degraded",
                     "partial": True,
                     "degraded_reason": "demo-mode-fixture-short-circuit",
                     "page": "landing"}},
        {"path": ".runs/image-candidates.json",
         "content": {"landing": {"hero": {"candidates": ["a", "b"]}}}},
    ]
    out = apply_matcher(_rule(["recovery-path-skip"]), rows)
    _t("sanctioned demo-mode-fixture-short-circuit → 0 events", len(out) == 0,
       f"got {out}")


def test_sanctioned_skip_redirect_source_only() -> None:
    print("\n[test_sanctioned_skip_redirect_source_only]")
    rows = [
        {"path": ".runs/agent-traces/design-critic-landing.json",
         "content": {"agent": "design-critic", "provenance": "self-degraded",
                     "partial": True, "degraded_reason": "redirect-source-only",
                     "page": "landing"}},
        {"path": ".runs/image-candidates.json",
         "content": {"landing": {"hero": {"candidates": ["a", "b"]}}}},
    ]
    out = apply_matcher(_rule(["recovery-path-skip"]), rows)
    _t("sanctioned redirect-source-only → 0 events", len(out) == 0, f"got {out}")


def test_provenance_self_no_emit() -> None:
    print("\n[test_provenance_self_no_emit]")
    rows = [
        {"path": ".runs/agent-traces/design-critic-landing.json",
         "content": {"agent": "design-critic", "provenance": "self",
                     "partial": False, "page": "landing", "candidates_tried": 3}},
        {"path": ".runs/image-candidates.json",
         "content": {"landing": {"hero": {"candidates": ["a", "b"]}}}},
    ]
    out = apply_matcher(_rule(["recovery-path-skip"]), rows)
    _t("provenance=self (non-fallback) → 0 events", len(out) == 0, f"got {out}")


def test_partial_false_no_emit() -> None:
    print("\n[test_partial_false_no_emit]")
    rows = [
        {"path": ".runs/agent-traces/design-critic-landing.json",
         "content": {"agent": "design-critic", "provenance": "self-degraded",
                     "partial": False, "page": "landing"}},
        {"path": ".runs/image-candidates.json",
         "content": {"landing": {"hero": {"candidates": ["a", "b"]}}}},
    ]
    out = apply_matcher(_rule(["recovery-path-skip"]), rows)
    _t("partial=false → 0 events", len(out) == 0, f"got {out}")


def test_absent_sidecar_no_emit() -> None:
    print("\n[test_absent_sidecar_no_emit]")
    rows = [{
        "path": ".runs/agent-traces/design-critic-landing.json",
        "content": {"agent": "design-critic", "provenance": "self-degraded",
                    "partial": True, "page": "landing",
                    "degraded_reason": "turn-budget-exhausted",
                    "candidates_tried": 0},
    }]
    out = apply_matcher(_rule(["recovery-path-skip"]), rows)
    _t("absent image-candidates.json → 0 events", len(out) == 0,
       f"got {out}")


def test_non_landing_has_images_missing_iifl() -> None:
    print("\n[test_non_landing_has_images_missing_iifl]")
    rows = [
        {"path": ".runs/agent-traces/design-critic-pricing.json",
         "content": {"agent": "design-critic", "provenance": "self-degraded",
                     "partial": True,
                     "degraded_reason": "turn-budget-exhausted",
                     "page": "pricing",
                     # image_issues_for_landing key absent
                     }},
        {"path": ".runs/image-candidates.json", "content": {}},
        {"path": ".runs/page-image-map.json",
         "content": {"pricing": {"has_images": True, "detected_via": "img-tag"}}},
    ]
    out = apply_matcher(_rule(["recovery-path-skip"]), rows)
    _t("non-landing has_images=true + missing iifl key → 1 event",
       len(out) == 1, f"got {out}")
    if out:
        _t("skipped_check=image_issues_for_landing-key-absent",
           out[0].get("skipped_check") == "image_issues_for_landing-key-absent")


# ----------------------------------------------------------------------------
# Enumerator candidate-id stability
# ----------------------------------------------------------------------------

def test_enumerator_candidate_id_deterministic() -> None:
    """Two enumerator calls on the same fixture produce the same candidate_id.

    Critical for the GECR matches_friction_count predicate: the rule's
    failures must reference the SAME candidate_id as the enumerator wrote
    to .runs/retrospective-pending-findings.json (avoids
    re-derivation drift — same anti-pattern caef8ab fix dropped).
    """
    print("\n[test_enumerator_candidate_id_deterministic]")
    import importlib.util
    enum_path = os.path.join(_HERE, "..", "enumerate-pending-retrospective-findings.py")
    spec = importlib.util.spec_from_file_location("enum_mod", enum_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    with tempfile.TemporaryDirectory() as root:
        runs = os.path.join(root, ".runs")
        os.makedirs(os.path.join(runs, "agent-traces"))
        trace = {"agent": "solve-critic", "status": "started",
                 "timestamp": "2026-05-18T11:00:00Z", "run_id": "test-r1"}
        with open(os.path.join(runs, "agent-traces", "solve-critic.json"), "w") as fh:
            json.dump(trace, fh)
        cwd = os.getcwd()
        os.chdir(root)
        try:
            out_a = mod._candidates_from_sparse_traces("")
            out_b = mod._candidates_from_sparse_traces("")
        finally:
            os.chdir(cwd)
    cid_a = out_a[0]["candidate_id"] if out_a else ""
    cid_b = out_b[0]["candidate_id"] if out_b else ""
    _t("candidate_id deterministic", cid_a and cid_a == cid_b,
       f"a={cid_a!r} b={cid_b!r}")


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main() -> int:
    test_sparse_init_stub_survived()
    test_lead_orchestrated_missing_aoc_v13()
    test_lead_orchestrated_complete()
    test_recovery_skip_landing_unused_candidates()
    test_sanctioned_skip_empty_boundary()
    test_sanctioned_skip_demo_mode()
    test_sanctioned_skip_redirect_source_only()
    test_provenance_self_no_emit()
    test_partial_false_no_emit()
    test_absent_sidecar_no_emit()
    test_non_landing_has_images_missing_iifl()
    test_enumerator_candidate_id_deterministic()

    print()
    print(f"=== {_PASS} passed, {_FAIL} failed ===")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
