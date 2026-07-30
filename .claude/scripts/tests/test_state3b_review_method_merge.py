#!/usr/bin/env python3
"""test_state3b_review_method_merge.py — validate the design-critic merge script
and the source-only → unresolved invariant enforcement.

Invokes `.claude/scripts/merge-design-critic-traces.py` (extracted from
`state-3b-quality-gate.md` inline python per issue #1045) against synthetic
per-page design-critic traces, and asserts:

1. per_page_review_methods aggregates correctly per page.
2. per_page_review_evidence contains one entry per page with the review_evidence
   fields carried through.
3. Invariant enforcement: any per-page trace with review_method in
   {source-only, unknown} whose verdict is not unresolved is self-healed to
   unresolved, AND a review_method_gate_corrections entry is recorded.
4. The existing worst-case merge (unresolved > fixed > pass) picks up the
   corrected verdict.

Exit 0 on all-pass, 1 on any failure.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MERGE_SCRIPT = ROOT / ".claude/scripts/merge-design-critic-traces.py"


def run_merge(per_page_traces: list[dict]) -> tuple[dict, str]:
    """Write synthetic traces to a tmp dir, run the merge, return (merged_json, stderr)."""
    with tempfile.TemporaryDirectory() as tmp:
        traces_dir = Path(tmp) / ".runs" / "agent-traces"
        traces_dir.mkdir(parents=True)
        # Write synthetic verify-context.json so run_id resolves
        (Path(tmp) / ".runs" / "verify-context.json").write_text(
            json.dumps({"run_id": "test-run"})
        )
        for t in per_page_traces:
            page = t.get("page", "unknown")
            (traces_dir / f"design-critic-{page}.json").write_text(json.dumps(t))

        result = subprocess.run(
            ["python3", str(MERGE_SCRIPT)],
            capture_output=True,
            text=True,
            cwd=tmp,
            check=True,
        )
        merged = json.loads((traces_dir / "design-critic.json").read_text())
        return merged, result.stdout + result.stderr


def make_trace(
    page: str,
    verdict: str = "pass",
    review_method: str | None = None,
    review_evidence: dict | None = None,
    min_score: int = 9,
    **extra,
) -> dict:
    t = {
        "agent": "design-critic",
        "page": page,
        "pages_reviewed": 1,
        "verdict": verdict,
        "checks_performed": ["layer1_functional"],
        "min_score": min_score,
        "min_score_all": min_score,
        "sections_below_8": 0,
        "fixes_applied": 0,
        "unresolved_sections": 0,
        "pre_existing_debt": [],
        "fixes": [],
    }
    if review_method is not None:
        t["review_method"] = review_method
    if review_evidence is not None:
        t["review_evidence"] = review_evidence
    t.update(extra)
    return t


class TestReviewMethodMerge(unittest.TestCase):
    def test_aggregates_review_methods_and_evidence(self):
        traces = [
            make_trace(
                "landing",
                verdict="pass",
                review_method="rendered-demo",
                review_evidence={
                    "requested_route": "/",
                    "final_url": "http://localhost:3099/",
                    "auth_source": "demo-mode",
                    "fallback_reason": None,
                    "content_density": 320,
                },
            ),
            make_trace(
                "dashboard",
                verdict="pass",
                review_method="rendered-demo",
                review_evidence={
                    "requested_route": "/dashboard",
                    "final_url": "http://localhost:3099/dashboard",
                    "auth_source": "demo-mode",
                    "fallback_reason": None,
                    "content_density": 220,
                },
            ),
        ]
        merged, _ = run_merge(traces)
        self.assertEqual(
            merged["per_page_review_methods"],
            {"landing": "rendered-demo", "dashboard": "rendered-demo"},
        )
        self.assertEqual(len(merged["per_page_review_evidence"]), 2)
        evidence_by_page = {e["page"]: e for e in merged["per_page_review_evidence"]}
        self.assertEqual(evidence_by_page["landing"]["auth_source"], "demo-mode")
        self.assertEqual(evidence_by_page["dashboard"]["content_density"], 220)
        # Happy path: no verdict corrections
        self.assertNotIn("review_method_gate_corrections", merged)
        # Happy path: merged verdict is pass (worst of two passes)
        self.assertEqual(merged["verdict"], "pass")

    def test_invariant_forces_unresolved_on_source_only(self):
        """If an agent emits source-only + pass, merge must self-heal to unresolved."""
        traces = [
            make_trace(
                "landing",
                verdict="pass",
                review_method="rendered-demo",
            ),
            make_trace(
                "dashboard",
                verdict="pass",  # BUG: should be unresolved per Rendered-Review Contract
                review_method="source-only",
                review_evidence={
                    "requested_route": "/dashboard",
                    "final_url": "http://localhost:3099/login",
                    "auth_source": "demo-mode",
                    "fallback_reason": "demo-mode-bypass-failed",
                    "content_density": None,
                },
            ),
        ]
        merged, output = run_merge(traces)
        # Invariant enforcement fired
        self.assertIn("review_method_gate_corrections", merged)
        corrections = merged["review_method_gate_corrections"]
        self.assertEqual(len(corrections), 1)
        self.assertEqual(corrections[0]["page"], "dashboard")
        self.assertEqual(corrections[0]["review_method"], "source-only")
        self.assertEqual(corrections[0]["original_verdict"], "pass")
        # Warning surfaced to stderr/stdout
        self.assertIn("WARN", output)
        self.assertIn("forcing verdict=unresolved", output)
        # Final merged verdict reflects the correction
        self.assertEqual(merged["verdict"], "unresolved")
        # Per-page review methods unchanged (recorded honestly)
        self.assertEqual(merged["per_page_review_methods"]["dashboard"], "source-only")

    def test_invariant_forces_unresolved_on_unknown(self):
        """review_method=unknown with non-unresolved verdict triggers same healing."""
        traces = [
            make_trace(
                "checkout",
                verdict="fixed",  # BUG
                review_method="unknown",
                review_evidence={
                    "requested_route": "/checkout",
                    "final_url": None,
                    "auth_source": "demo-mode",
                    "fallback_reason": "navigation-failed:timeout",
                    "content_density": None,
                },
            ),
        ]
        merged, _ = run_merge(traces)
        corrections = merged["review_method_gate_corrections"]
        self.assertEqual(len(corrections), 1)
        self.assertEqual(corrections[0]["original_verdict"], "fixed")
        self.assertEqual(merged["verdict"], "unresolved")

    def test_invariant_no_correction_when_contract_honored(self):
        """Agent correctly emits unresolved on source-only: no correction needed."""
        traces = [
            make_trace(
                "dashboard",
                verdict="unresolved",
                review_method="source-only",
                review_evidence={
                    "requested_route": "/dashboard",
                    "final_url": "http://localhost:3099/login",
                    "auth_source": "demo-mode",
                    "fallback_reason": "redirected-to-auth-route",
                    "content_density": None,
                },
                caveat="redirected-to-auth-route",
            ),
        ]
        merged, _ = run_merge(traces)
        self.assertNotIn("review_method_gate_corrections", merged)
        self.assertEqual(merged["verdict"], "unresolved")

    def test_missing_review_method_is_backward_compat(self):
        """Traces without review_method (pre-migration or opt-out) merge cleanly."""
        traces = [
            make_trace("landing", verdict="pass"),  # no review_method
            make_trace("about", verdict="pass"),
        ]
        merged, _ = run_merge(traces)
        # per_page_review_methods is empty, not populated
        self.assertEqual(merged["per_page_review_methods"], {})
        self.assertEqual(merged["per_page_review_evidence"], [])
        self.assertNotIn("review_method_gate_corrections", merged)
        self.assertEqual(merged["verdict"], "pass")


if __name__ == "__main__":
    unittest.main(verbosity=2)
