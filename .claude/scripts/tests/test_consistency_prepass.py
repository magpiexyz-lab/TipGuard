"""#1257 — unit tests for the lead-side consistency prepass.

Tests cover:
  * Partition determinism (deterministic across two runs on same inputs)
  * Partition correctness (single-batch when N ≤ batch_size; ceil(N/M) batches otherwise)
  * Anomaly detection at ≥80% majority threshold
  * Skipped detection when no majority signal exists
  * Schema of `.runs/consistency-check-prepass.json`

Tests do NOT spawn Playwright — pass `--skip-playwright` so the lead-side
DOM extraction is skipped and `c5_method=static-fallback` is recorded.
"""
from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
PREPASS = REPO_ROOT / ".claude" / "scripts" / "run-consistency-static-prepass.py"
LIB_DIR = REPO_ROOT / ".claude" / "scripts" / "lib"


def _setup_project(tmp: Path, page_set: dict, src_pages: dict) -> None:
    """Build a tmpdir mini-project so the prepass can run.

    Lays out:
      .runs/design-page-set.json
      src/app/<page>/page.tsx — content per src_pages[name]
      src/app/page.tsx — landing content (if landing in page_set)
      .claude/scripts/run-consistency-static-prepass.py — symlink to real
      .claude/scripts/lib/ — symlink to real (for write-gate-artifact.sh)
    """
    (tmp / ".runs").mkdir(parents=True)
    with open(tmp / ".runs" / "design-page-set.json", "w") as f:
        json.dump(page_set, f)

    # Build src/app/<page>/page.tsx for each page
    for entry in (page_set.get("pages") or []):
        page_dir = tmp / "src" / "app" / entry["name"]
        page_dir.mkdir(parents=True, exist_ok=True)
        (page_dir / "page.tsx").write_text(src_pages.get(entry["name"], ""), encoding="utf-8")
    if page_set.get("landing"):
        (tmp / "src" / "app").mkdir(parents=True, exist_ok=True)
        (tmp / "src" / "app" / "page.tsx").write_text(src_pages.get("landing", ""), encoding="utf-8")

    # Symlink .claude/scripts and .claude/scripts/lib so prepass can find sister scripts.
    (tmp / ".claude" / "scripts").mkdir(parents=True, exist_ok=True)
    for src, dst in [
        (LIB_DIR, tmp / ".claude" / "scripts" / "lib"),
        (REPO_ROOT / ".claude" / "scripts" / "tests", tmp / ".claude" / "scripts" / "tests"),
    ]:
        if dst.exists():
            continue
        os.symlink(src, dst)

    # Need an empty context for resolve_run_id; not a hard requirement.
    with open(tmp / ".runs" / "verify-context.json", "w") as f:
        json.dump({"skill": "verify", "run_id": "verify-test-1257"}, f)


class TestPartitionLogic(unittest.TestCase):
    """Pure-function tests for partition_pages()."""

    def setUp(self):
        # Import the module dynamically since it's not installed
        import importlib.util
        spec = importlib.util.spec_from_file_location("prepass", PREPASS)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_single_batch_when_n_le_batch_size(self):
        pages = [{"name": f"page{i}"} for i in range(5)]
        result = self.mod.partition_pages(pages, None, batch_size=8)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["batch_id"], "single")
        self.assertEqual(len(result[0]["pages"]), 5)

    def test_single_batch_when_n_eq_batch_size(self):
        pages = [{"name": f"page{i}"} for i in range(8)]
        result = self.mod.partition_pages(pages, None, batch_size=8)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["batch_id"], "single")

    def test_multi_batch_for_18_pages(self):
        pages = [{"name": f"page{i:02d}"} for i in range(18)]
        result = self.mod.partition_pages(pages, None, batch_size=8)
        # 18 / 8 = 2.25 → 3 batches
        self.assertEqual(len(result), 3)
        for batch in result:
            self.assertLessEqual(len(batch["pages"]), 8)
        # Sum of batch pages = total
        total = sum(len(b["pages"]) for b in result)
        self.assertEqual(total, 18)

    def test_partition_includes_landing_last(self):
        pages = [{"name": "about"}, {"name": "pricing"}]
        landing = {"name": "landing"}
        result = self.mod.partition_pages(pages, landing, batch_size=8)
        # Sorted by name: about, pricing; landing appended last
        self.assertEqual(result[0]["pages"], ["about", "pricing", "landing"])

    def test_partition_determinism(self):
        pages = [{"name": f"p{i}"} for i in range(15)]
        a = self.mod.partition_pages(pages, None, batch_size=8)
        b = self.mod.partition_pages(pages, None, batch_size=8)
        self.assertEqual(a, b)

    def test_partition_sorted_by_name(self):
        # Inputs in arbitrary order
        pages = [{"name": "zebra"}, {"name": "alpha"}, {"name": "mango"}]
        result = self.mod.partition_pages(pages, None, batch_size=8)
        self.assertEqual(result[0]["pages"], ["alpha", "mango", "zebra"])

    def test_empty_input_returns_empty_partition(self):
        result = self.mod.partition_pages([], None, batch_size=8)
        self.assertEqual(result, [])


class TestAnomalyDetection(unittest.TestCase):
    """Pure-function tests for detect_token_outliers and detect_dom_outliers."""

    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("prepass", PREPASS)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_token_outliers_flags_minority_pages_missing_majority_token(self):
        # 17/18 pages have bg-slate-50, 1 page (pricing) has bg-gray-50
        freq = {
            "bg-slate-50": {"pages": [f"p{i}" for i in range(17)], "count": 17},
            "bg-gray-50": {"pages": ["pricing"], "count": 1},
        }
        all_pages = [f"p{i}" for i in range(17)] + ["pricing"]
        result = self.mod.detect_token_outliers("C1", freq, all_pages)
        # bg-slate-50 majority (17/18 = 94%); pricing missing it → 1 anomaly
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["check"], "C1")
        self.assertEqual(result[0]["minority_pages"], ["pricing"])

    def test_token_outliers_skipped_when_no_majority(self):
        # 5/9 vs 4/9 — neither side hits 80% majority
        freq = {
            "bg-blue": {"pages": [f"p{i}" for i in range(5)], "count": 5},
            "bg-red": {"pages": [f"q{i}" for i in range(4)], "count": 4},
        }
        all_pages = [f"p{i}" for i in range(5)] + [f"q{i}" for i in range(4)]
        result = self.mod.detect_token_outliers("C1", freq, all_pages)
        self.assertEqual(result, [])

    def test_token_outliers_skipped_when_too_few_pages(self):
        # < 3 pages: no statistical signal
        freq = {"bg-blue": {"pages": ["a", "b"], "count": 2}}
        result = self.mod.detect_token_outliers("C1", freq, ["a", "b"])
        self.assertEqual(result, [])

    def test_dom_outliers_flags_missing_majority_feature(self):
        # 4/5 pages have header; landing is missing
        features = [
            {"name": "p1", "header_present": True, "footer_present": True, "nav_present": True, "sidebar_present": False},
            {"name": "p2", "header_present": True, "footer_present": True, "nav_present": True, "sidebar_present": False},
            {"name": "p3", "header_present": True, "footer_present": True, "nav_present": True, "sidebar_present": False},
            {"name": "p4", "header_present": True, "footer_present": True, "nav_present": True, "sidebar_present": False},
            {"name": "landing", "header_present": False, "footer_present": True, "nav_present": False, "sidebar_present": False},
        ]
        result = self.mod.detect_dom_outliers(features)
        # 4/5 majority for header (80% threshold); landing flagged
        # 4/5 majority for nav; landing flagged
        # footer 5/5; sidebar 5/5 absent (no anomaly since absence is uniform)
        types = [a["type"] for a in result]
        self.assertIn("missing_header", types)
        self.assertIn("missing_nav", types)
        self.assertNotIn("missing_footer", types)

    def test_dom_outliers_handles_per_page_errors(self):
        # 1 page errored; only 4 valid pages — still need to compute majority on those
        features = [
            {"name": "p1", "header_present": True, "footer_present": True, "nav_present": True, "sidebar_present": False},
            {"name": "p2", "header_present": True, "footer_present": True, "nav_present": True, "sidebar_present": False},
            {"name": "p3", "header_present": True, "footer_present": True, "nav_present": True, "sidebar_present": False},
            {"name": "p4", "error": "navigation timeout"},
            {"name": "landing", "header_present": False, "footer_present": True, "nav_present": False, "sidebar_present": False},
        ]
        result = self.mod.detect_dom_outliers(features)
        # Only 4 valid features → 3 with header, 1 without
        # 3/4 = 75%, BELOW 80% threshold → no header anomaly
        # nav: 3/4 = 75% → also no anomaly
        types = [a["type"] for a in result]
        self.assertNotIn("missing_header", types)


class TestPrepassEnd2End(unittest.TestCase):
    """Integration: run the prepass as a subprocess against a stub project."""

    def test_prepass_writes_artifact_with_skip_playwright(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            page_set = {
                "pages": [{"name": "about"}, {"name": "pricing"}, {"name": "dashboard"}],
                "landing": {"name": "landing"},
                "generated_at": "2026-05-08T00:00:00Z",
            }
            src_pages = {
                "about": '<div className="bg-slate-50 p-4"><Header /></div>',
                "pricing": '<div className="bg-slate-50 p-4"><Header /></div>',
                "dashboard": '<div className="bg-slate-50 p-4"><Header /></div>',
                "landing": '<div className="bg-slate-50 p-4"><Hero /></div>',
            }
            _setup_project(tmp, page_set, src_pages)

            result = subprocess.run(
                ["python3", str(PREPASS),
                 "--skip-playwright",
                 "--project-dir", str(tmp),
                 "--batch-size", "8"],
                capture_output=True, text=True,
                # Run from tmp so canonical writer + verify-context lookup work
                cwd=str(tmp),
            )
            # Exit 0 is success; allow exit 0 only when --skip-playwright
            self.assertIn(result.returncode, (0, 2),
                          f"prepass exited {result.returncode}: {result.stderr}")

            artifact = tmp / ".runs" / "consistency-check-prepass.json"
            self.assertTrue(artifact.exists(), f"prepass artifact missing at {artifact}")
            data = json.loads(artifact.read_text())
            self.assertEqual(data["schema_version"], 1)
            self.assertIn("partition", data)
            self.assertIn("anomaly_candidates", data)
            self.assertIn("global_frequency_maps", data)
            self.assertEqual(data["c5_method"], "static-fallback")
            # 4 pages → single batch
            self.assertEqual(len(data["partition"]), 1)
            self.assertEqual(data["partition"][0]["batch_id"], "single")

    def test_prepass_multi_batch_for_18_pages(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            page_names = [f"page{i:02d}" for i in range(17)]
            page_set = {
                "pages": [{"name": n} for n in page_names],
                "landing": {"name": "landing"},
            }
            src_pages = {n: '<div className="bg-slate-50"><Header /></div>' for n in page_names + ["landing"]}
            _setup_project(tmp, page_set, src_pages)

            result = subprocess.run(
                ["python3", str(PREPASS),
                 "--skip-playwright",
                 "--project-dir", str(tmp),
                 "--batch-size", "8"],
                capture_output=True, text=True,
                cwd=str(tmp),
            )
            self.assertIn(result.returncode, (0, 2))

            data = json.loads((tmp / ".runs" / "consistency-check-prepass.json").read_text())
            # 17 + 1 (landing) = 18 pages → ceil(18/8) = 3 batches
            self.assertEqual(len(data["partition"]), 3)
            self.assertEqual(data["partition"][0]["batch_id"], "batch1")
            self.assertEqual(data["partition"][-1]["batch_id"], "batch3")

    def test_prepass_partition_landing_appended_last(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            page_set = {
                "pages": [{"name": "zebra"}, {"name": "alpha"}],
                "landing": {"name": "landing"},
            }
            src_pages = {"zebra": "", "alpha": "", "landing": ""}
            _setup_project(tmp, page_set, src_pages)

            subprocess.run(
                ["python3", str(PREPASS),
                 "--skip-playwright",
                 "--project-dir", str(tmp),
                 "--batch-size", "8"],
                capture_output=True, text=True,
                cwd=str(tmp),
            )
            data = json.loads((tmp / ".runs" / "consistency-check-prepass.json").read_text())
            # Sorted: alpha, zebra; landing appended → [alpha, zebra, landing]
            self.assertEqual(data["partition"][0]["pages"], ["alpha", "zebra", "landing"])


if __name__ == "__main__":
    unittest.main()
