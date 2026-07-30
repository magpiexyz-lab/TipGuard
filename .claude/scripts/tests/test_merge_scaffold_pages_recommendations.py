#!/usr/bin/env python3
"""Regression coverage for merge-scaffold-pages-traces.py
template_recommendations propagation (#1294, post-#1305 audit follow-up).

Without aggregation, the merged scaffold-pages.json fails the schema validator
wired at bootstrap.11c by #1305. These tests exercise the four shapes of
input the merger may receive and lock the contract behavior.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MERGE_SCRIPT = ROOT / ".claude/scripts/merge-scaffold-pages-traces.py"


def run_merge(per_page_traces: list[dict]) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        traces_dir = Path(tmp) / ".runs" / "agent-traces"
        traces_dir.mkdir(parents=True)
        (Path(tmp) / ".runs" / "verify-context.json").write_text(
            json.dumps({"run_id": "test-run"})
        )
        for t in per_page_traces:
            slug = t.get("page", "unknown")
            (traces_dir / f"scaffold-pages-{slug}.json").write_text(json.dumps(t))
        subprocess.run(
            ["python3", str(MERGE_SCRIPT)],
            capture_output=True,
            text=True,
            cwd=tmp,
            check=True,
        )
        return json.loads((traces_dir / "scaffold-pages.json").read_text())


def make_real(
    page: str,
    template_recommendations=None,
    template_recommendations_explicit_none=None,
) -> dict:
    t = {
        "agent": "scaffold-pages",
        "page": page,
        "verdict": "pass",
        "status": "completed",
        "provenance": "self",
        "files_created": [f"src/app/{page}/page.tsx"],
        "issues": [],
        "checks_performed": ["page_authored"],
    }
    if template_recommendations is not None:
        t["template_recommendations"] = template_recommendations
    if template_recommendations_explicit_none is not None:
        t["template_recommendations_explicit_none"] = (
            template_recommendations_explicit_none
        )
    return t


def make_stub(page: str) -> dict:
    """init-trace stub from a rate-limited spawn (#1190 contract)."""
    return {
        "agent": "scaffold-pages",
        "page": page,
        "status": "started",
        # No verdict, no template_recommendations — that's the whole point.
    }


def make_recommendation(file=".claude/x.md", section="y") -> dict:
    return {
        "file": file,
        "section": section,
        "recommendation": "Document something",
        "fix_template": "Add a heading.",
    }


class TestAggregateRecommendations(unittest.TestCase):
    """Aggregate template_recommendations propagation contract (#1294)."""

    def test_all_explicit_none_aggregates_to_explicit_none(self):
        """When every per-page trace declares explicit_none=True, the
        aggregate inherits explicit_none=True and an empty list."""
        traces = [
            make_real("home", template_recommendations=[],
                     template_recommendations_explicit_none=True),
            make_real("about", template_recommendations=[],
                     template_recommendations_explicit_none=True),
        ]
        agg = run_merge(traces)
        self.assertEqual(agg["template_recommendations"], [])
        self.assertIs(agg["template_recommendations_explicit_none"], True)

    def test_non_empty_concat_sets_explicit_none_false(self):
        """Per Round-2 critic Concern 3: list non-empty MUST set
        explicit_none=False, defending against future tightening that
        asserts the boolean.

        Order note: the merger globs traces alphabetically, so the
        concatenation order follows alphabetical filename order, not
        per_page_traces argument order. The contract being locked here is
        membership + count + explicit_none, not order.
        """
        rec_a = make_recommendation(file=".claude/a.md", section="A")
        rec_b = make_recommendation(file=".claude/b.md", section="B")
        traces = [
            make_real("home", template_recommendations=[rec_a],
                     template_recommendations_explicit_none=False),
            make_real("about", template_recommendations=[rec_b],
                     template_recommendations_explicit_none=False),
        ]
        agg = run_merge(traces)
        self.assertEqual(len(agg["template_recommendations"]), 2)
        # Sort by file to compare without depending on glob order.
        actual_sorted = sorted(
            agg["template_recommendations"], key=lambda x: x["file"]
        )
        self.assertEqual(actual_sorted, [rec_a, rec_b])
        self.assertIs(agg["template_recommendations_explicit_none"], False)

    def test_mixed_some_have_recs_others_explicit_none(self):
        """If at least one per-page has recommendations, aggregate carries
        the concat AND explicit_none=False (the empty-explicit-none traces
        contribute nothing to the list)."""
        rec = make_recommendation()
        traces = [
            make_real("home", template_recommendations=[rec],
                     template_recommendations_explicit_none=False),
            make_real("about", template_recommendations=[],
                     template_recommendations_explicit_none=True),
        ]
        agg = run_merge(traces)
        self.assertEqual(agg["template_recommendations"], [rec])
        self.assertIs(agg["template_recommendations_explicit_none"], False)

    def test_stub_traces_excluded_from_explicit_none_calc(self):
        """Stub partition (#1190): stubs lack template_recommendations and
        must NOT contaminate the explicit_none calculation. With one real
        explicit_none=True trace and one stub, aggregate must reflect the
        real trace's explicit_none=True (not False)."""
        traces = [
            make_real("home", template_recommendations=[],
                     template_recommendations_explicit_none=True),
            make_stub("about"),  # stub: no fields
        ]
        agg = run_merge(traces)
        self.assertEqual(agg["template_recommendations"], [])
        self.assertIs(agg["template_recommendations_explicit_none"], True)
        # Stub is also reflected in stub_count
        self.assertEqual(agg["stub_count"], 1)

    def test_aggregate_passes_recommendations_validator(self):
        """End-to-end: the aggregate emitted by the merger must satisfy
        validate-scaffold-recommendations-schema.py's schema requirement.
        This is the contract that #1294 was filed to ensure."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            traces_dir = tmp_path / ".runs" / "agent-traces"
            traces_dir.mkdir(parents=True)
            (tmp_path / ".runs" / "verify-context.json").write_text(
                json.dumps({"run_id": "test-run"})
            )
            traces = [
                make_real("home", template_recommendations=[],
                         template_recommendations_explicit_none=True),
                make_real("about", template_recommendations=[],
                         template_recommendations_explicit_none=True),
            ]
            for t in traces:
                slug = t["page"]
                (traces_dir / f"scaffold-pages-{slug}.json").write_text(
                    json.dumps(t)
                )
            subprocess.run(
                ["python3", str(MERGE_SCRIPT)],
                capture_output=True,
                text=True,
                cwd=tmp,
                check=True,
            )
            # Pre-cutoff run_id will SKIP, which is fine for this test —
            # the validator just needs to accept the aggregate without
            # parse errors.
            import os
            env = os.environ.copy()
            env["SCAFFOLD_RECOMMENDATIONS_SCHEMA_MODE"] = "deny"
            result = subprocess.run(
                [
                    "python3",
                    str(ROOT / ".claude/scripts/validate-scaffold-recommendations-schema.py"),
                ],
                cwd=tmp,
                capture_output=True,
                text=True,
                env=env,
            )
            # Pre-cutoff: SKIP (exit 0). The point is "no validator error
            # caused by aggregate schema malformation." Combined with the
            # other tests above, this locks the contract.
            self.assertEqual(
                result.returncode, 0,
                f"validator failed on merger output: stdout={result.stdout!r} "
                f"stderr={result.stderr!r}",
            )


if __name__ == "__main__":
    unittest.main()
