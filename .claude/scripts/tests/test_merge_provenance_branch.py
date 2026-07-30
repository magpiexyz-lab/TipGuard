#!/usr/bin/env python3
"""test_merge_provenance_branch.py — #1042 Session C coverage for
merge-design-critic-traces.py self-heal provenance gate and aggregate
lead-merge propagation.

Each test synthesises per-page traces in a tempdir, runs the merge script,
and asserts the aggregate `design-critic.json` is well-formed.

Test matrix (from plan §7):
  C1: 2× (self, pass, rendered-demo) — clean happy path; no self-heal;
      aggregate provenance=lead-merge, partial=true, contributing_spawn_indexes.
  C2: 1× (self, source-only, verdict=pass) — classic agent bug; self-heal
      forces verdict=unresolved; review_method_gate_corrections recorded;
      NOT treated as demo-mode-short-circuit (no provenance=self-degraded).
  C3: 1× (self-degraded, source-only, demo-mode-fixture-short-circuit,
      verdict=unresolved) — sanctioned path; self-heal does NOT fire;
      demo_mode_short_circuit_pages records the page; per_page_provenance
      entry present.
  C4: 1× landing (self, pass) + 1× quote (self-degraded, demo-mode-fixture)
      — mixed run; aggregate verdict=unresolved (worst); contributing indexes
      cover both pages; per_page_provenance populated for both.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MERGE_SCRIPT = ROOT / ".claude/scripts/merge-design-critic-traces.py"


def run_merge(per_page_traces: list[dict]) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        traces_dir = Path(tmp) / ".runs" / "agent-traces"
        traces_dir.mkdir(parents=True)
        (Path(tmp) / ".runs" / "verify-context.json").write_text(
            json.dumps({"run_id": "test-run"})
        )
        # Also synthesise a minimal agent-spawn-log.jsonl so
        # contributing_spawn_indexes is populated from real data.
        spawn_log = Path(tmp) / ".runs" / "agent-spawn-log.jsonl"
        with open(spawn_log, "w") as f:
            for i, t in enumerate(per_page_traces):
                f.write(
                    json.dumps(
                        {
                            "agent": "design-critic",
                            "run_id": "test-run",
                            "spawn_index": i,
                            # hook=skill-agent-gate is required for merge +
                            # state-completion-gate to match identically
                            "hook": "skill-agent-gate",
                        }
                    )
                    + "\n"
                )
        for t in per_page_traces:
            page = t.get("page", "unknown")
            (traces_dir / f"design-critic-{page}.json").write_text(json.dumps(t))
        subprocess.run(
            ["python3", str(MERGE_SCRIPT)],
            capture_output=True,
            text=True,
            cwd=tmp,
            check=True,
        )
        return json.loads((traces_dir / "design-critic.json").read_text())


def make_trace(
    page: str,
    verdict: str = "pass",
    provenance: str = "self",
    review_method: str | None = None,
    degraded_reason: str | None = None,
    recovery_validated: bool = False,
    source_review_verdict: str | None = None,
    **extra,
) -> dict:
    t = {
        "agent": "design-critic",
        "page": page,
        "pages_reviewed": 1,
        "verdict": verdict,
        "provenance": provenance,
        "checks_performed": ["layer1_functional"],
        "min_score": 9,
        "min_score_all": 9,
        "sections_below_8": 0,
        "fixes_applied": 0,
        "unresolved_sections": 0,
        "pre_existing_debt": [],
        "fixes": [],
    }
    if review_method is not None:
        t["review_method"] = review_method
        t["review_evidence"] = {
            "requested_route": f"/{page}",
            "final_url": f"http://localhost/{page}",
            "auth_source": "demo-mode",
            "fallback_reason": degraded_reason,
            "content_density": None,
            "final_status": 404 if degraded_reason == "demo-mode-fixture-short-circuit" else None,
            "route_pattern": f"/{page}/[id]" if degraded_reason == "demo-mode-fixture-short-circuit" else f"/{page}",
        }
    if degraded_reason is not None:
        t["degraded_reason"] = degraded_reason
    if provenance == "self-degraded":
        t["partial"] = True
        t["recovery_validated"] = recovery_validated
        t["no_fixes_claimed"] = True
    if source_review_verdict is not None:
        t["source_review_verdict"] = source_review_verdict
    t.update(extra)
    return t


class TestMergeProvenanceBranch(unittest.TestCase):
    # ----- C1 -----
    def test_c1_clean_happy_path(self):
        """Two rendered-demo traces, no self-heal, aggregate is lead-merge."""
        per_page = [
            make_trace("landing", review_method="rendered-demo"),
            make_trace("dashboard", review_method="rendered-demo"),
        ]
        merged = run_merge(per_page)
        self.assertEqual(merged["verdict"], "pass")
        self.assertEqual(merged["provenance"], "lead-merge")
        self.assertIs(merged["partial"], True)
        self.assertEqual(sorted(merged["contributing_spawn_indexes"]), [0, 1])
        # Self-heal did not fire
        self.assertNotIn("review_method_gate_corrections", merged)
        # No demo-mode short-circuit pages
        self.assertNotIn("demo_mode_short_circuit_pages", merged)
        # Per-page provenance all "self"
        self.assertEqual(merged["per_page_provenance"], {"landing": "self", "dashboard": "self"})

    # ----- C2 -----
    def test_c2_self_heal_fires_for_plain_source_only(self):
        """Agent bug: verdict=pass on source-only → forced unresolved."""
        per_page = [
            make_trace(
                "quote",
                verdict="pass",
                review_method="source-only",
                degraded_reason="redirected-to-auth-route",
                provenance="self",
            ),
        ]
        merged = run_merge(per_page)
        self.assertEqual(merged["verdict"], "unresolved")
        # Self-heal recorded
        self.assertIn("review_method_gate_corrections", merged)
        self.assertEqual(len(merged["review_method_gate_corrections"]), 1)
        self.assertEqual(
            merged["review_method_gate_corrections"][0]["original_verdict"], "pass"
        )
        # NOT classified as demo-mode short-circuit
        self.assertNotIn("demo_mode_short_circuit_pages", merged)
        self.assertEqual(merged["per_page_provenance"], {"quote": "self"})

    # ----- C3 -----
    def test_c3_demo_mode_short_circuit_preserved(self):
        """self-degraded + demo-mode-fixture-short-circuit trace is NOT self-healed;
        verdict no longer propagates unresolved from validated_fallback siblings
        (#1265 — alignment with aggregate_ok hard-gate predicate); aggregate
        verdict is "pass" (initial); validated_fallback_pages records the
        sibling; all_validated_fallback flag fires when 100% of effective
        siblings are validated_fallback. demo_mode_short_circuit_pages and
        per_page_provenance still track it."""
        per_page = [
            make_trace(
                "quote",
                verdict="unresolved",
                provenance="self-degraded",
                review_method="source-only",
                degraded_reason="demo-mode-fixture-short-circuit",
                recovery_validated=True,
                source_review_verdict="pass",
            ),
        ]
        merged = run_merge(per_page)
        # #1265: validated_fallback sibling no longer pulls down aggregate verdict
        self.assertEqual(merged["verdict"], "pass")
        self.assertEqual(merged["validated_fallback_pages"], ["quote"])
        self.assertIs(merged["all_validated_fallback"], True)
        # Self-heal did NOT fire (provenance carve-out)
        self.assertNotIn("review_method_gate_corrections", merged)
        # Demo-mode short-circuit recorded
        self.assertEqual(merged["demo_mode_short_circuit_pages"], ["quote"])
        self.assertEqual(
            merged["per_page_provenance"], {"quote": "self-degraded"}
        )
        self.assertEqual(
            merged["per_page_recovery_validated"], {"quote": True}
        )
        self.assertEqual(
            merged["per_page_source_review_verdict"], {"quote": "pass"}
        )
        self.assertEqual(
            merged["per_page_degraded_reason"], {"quote": "demo-mode-fixture-short-circuit"}
        )
        self.assertEqual(merged["provenance"], "lead-merge")
        self.assertIs(merged["partial"], True)

    # ----- C4 -----
    def test_c4_mixed_run_landing_pass_quote_degraded(self):
        # #1265: quote's validated_fallback unresolved no longer propagates;
        # landing (self-pass) determines the aggregate verdict.
        per_page = [
            make_trace("landing", review_method="rendered-demo"),
            make_trace(
                "quote",
                verdict="unresolved",
                provenance="self-degraded",
                review_method="source-only",
                degraded_reason="demo-mode-fixture-short-circuit",
                recovery_validated=True,
                source_review_verdict="pass",
            ),
        ]
        merged = run_merge(per_page)
        # #1265: landing's pass propagates; quote's validated_fallback skipped
        self.assertEqual(merged["verdict"], "pass")
        self.assertEqual(merged["validated_fallback_pages"], ["quote"])
        # NOT all-validated-fallback — landing is provenance=self
        self.assertNotIn("all_validated_fallback", merged)
        self.assertEqual(
            merged["per_page_provenance"],
            {"landing": "self", "quote": "self-degraded"},
        )
        self.assertEqual(merged["demo_mode_short_circuit_pages"], ["quote"])
        # contributing_spawn_indexes covers both siblings
        self.assertEqual(sorted(merged["contributing_spawn_indexes"]), [0, 1])
        self.assertEqual(merged["provenance"], "lead-merge")

    # ----- C6 — #1061 empty-boundary fast-path -----
    def test_c6_empty_boundary_fast_path_preserved(self):
        """#1061: state-3a fast-path emits self-degraded + boundary-skip +
        degraded_reason=empty-boundary-fast-path + verdict=pass. The merge
        tight gate at L121-128 does NOT fire (review_method='boundary-skip'
        is not in ('source-only','unknown')). The trace stays verdict=pass.
        The aggregate records the page in empty_boundary_fast_path_pages
        for downstream visibility (and check-design-critic-sanctioned.py)."""
        per_page = [
            make_trace(
                "dashboard",
                verdict="pass",
                provenance="self-degraded",
                review_method="boundary-skip",
                degraded_reason="empty-boundary-fast-path",
                recovery_validated=True,
                fast_path=True,
            ),
        ]
        merged = run_merge(per_page)
        self.assertEqual(merged["verdict"], "pass")
        # No force-unresolve corrections
        self.assertNotIn("review_method_gate_corrections", merged)
        # Aggregate records sanctioned page
        self.assertEqual(merged["empty_boundary_fast_path_pages"], ["dashboard"])
        # Per-page propagation populated for sanctioned-aggregate detection
        self.assertEqual(merged["per_page_provenance"], {"dashboard": "self-degraded"})
        self.assertEqual(merged["per_page_recovery_validated"], {"dashboard": True})
        self.assertEqual(
            merged["per_page_degraded_reason"], {"dashboard": "empty-boundary-fast-path"}
        )

    def test_c7_mixed_fast_path_and_demo_mode(self):
        """#1061 + #1042 + #1265: real fresh-bootstrap shape — landing
        fast-paths + quote demo-mode-short-circuits. ALL per-page siblings
        are validated_fallback (self-degraded + recovery_validated=True),
        so worst-wins skips both → aggregate verdict stays "pass" (initial)
        with all_validated_fallback marker for downstream visibility. Both
        sanctioned paths recorded separately."""
        per_page = [
            make_trace(
                "landing",
                verdict="pass",
                provenance="self-degraded",
                review_method="boundary-skip",
                degraded_reason="empty-boundary-fast-path",
                recovery_validated=True,
                fast_path=True,
            ),
            make_trace(
                "quote",
                verdict="unresolved",
                provenance="self-degraded",
                review_method="source-only",
                degraded_reason="demo-mode-fixture-short-circuit",
                recovery_validated=True,
                source_review_verdict="pass",
            ),
        ]
        merged = run_merge(per_page)
        # #1265: both siblings are validated_fallback → both skipped from
        # worst-wins; aggregate verdict stays "pass" with all-fallback marker.
        # aggregate_ok validates per-sibling so this is the contract-correct
        # shape (no false-positive design-ux-merge.json verdict=fail
        # cascade-blocking downstream fixers).
        self.assertEqual(merged["verdict"], "pass")
        self.assertEqual(
            sorted(merged["validated_fallback_pages"]), ["landing", "quote"]
        )
        self.assertIs(merged["all_validated_fallback"], True)
        # Both sanctioned paths tracked separately
        self.assertEqual(merged["empty_boundary_fast_path_pages"], ["landing"])
        self.assertEqual(merged["demo_mode_short_circuit_pages"], ["quote"])
        # No force-unresolve corrections — landing is boundary-skip, quote is
        # already unresolved (no self-heal needed)
        self.assertNotIn("review_method_gate_corrections", merged)
        # Per-page provenance covers both
        self.assertEqual(
            merged["per_page_provenance"],
            {"landing": "self-degraded", "quote": "self-degraded"},
        )
        self.assertEqual(
            merged["per_page_degraded_reason"],
            {
                "landing": "empty-boundary-fast-path",
                "quote": "demo-mode-fixture-short-circuit",
            },
        )

    def test_c5_aggregate_required_fields_always_present(self):
        """Bare minimum invariant: lead-merge + partial + contributing_spawn_indexes
        are populated even with a single trace and no spawn log."""
        per_page = [make_trace("landing", review_method="rendered-demo")]
        merged = run_merge(per_page)
        self.assertIn("provenance", merged)
        self.assertIn("partial", merged)
        self.assertIn("contributing_spawn_indexes", merged)
        self.assertEqual(merged["provenance"], "lead-merge")
        self.assertTrue(merged["partial"])
        self.assertIsInstance(merged["contributing_spawn_indexes"], list)
        self.assertGreaterEqual(len(merged["contributing_spawn_indexes"]), 1)


if __name__ == "__main__":
    unittest.main()
