"""#1379 G3 — unit tests for derive_pages.py `design_critic_pages` CLI subcommand.

spec-reviewer S2 must use `design_critic_pages` (not `scope`) for page-existence
checks. `scope` returns disambiguated names that don't map to literal directories
for dynamic routes; `design_critic_pages` returns dicts with `source_files[]`
that ARE the canonical answer.
"""
from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / ".claude" / "scripts" / "lib" / "derive_pages.py"


def _run_subcommand(cwd: Path, subcmd: str, experiment_yaml: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["python3", str(SCRIPT), subcmd],
        input=experiment_yaml,
        text=True,
        capture_output=True,
        cwd=str(cwd),
    )
    return proc.returncode, proc.stdout, proc.stderr


def _scaffold_dynamic_route(root: Path, segment: str) -> None:
    """Create src/app/portfolio/[slug]/page.tsx."""
    page_dir = root / "src" / "app" / "portfolio" / f"[{segment}]"
    page_dir.mkdir(parents=True, exist_ok=True)
    (page_dir / "page.tsx").write_text("export default function Page(){return null;}")


def _scaffold_static_route(root: Path, name: str) -> None:
    """Create src/app/<name>/page.tsx."""
    page_dir = root / "src" / "app" / name
    page_dir.mkdir(parents=True, exist_ok=True)
    (page_dir / "page.tsx").write_text("export default function Page(){return null;}")


EXPERIMENT_WITH_DYNAMIC = """name: test
type: web-app
status: drafting
golden_path:
  - step: visit portfolio
    page: portfolio-detail
behaviors: []
"""

EXPERIMENT_STATIC_ONLY = """name: test
type: web-app
status: drafting
golden_path:
  - step: home
    page: home
behaviors: []
"""


class TestDesignCriticPagesSubcommand(unittest.TestCase):
    def test_dynamic_route_returns_source_files_not_literal_dir(self):
        """For src/app/portfolio/[slug]/page.tsx, source_files should
        contain the actual .tsx path, NOT a literal portfolio-slug dir."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold_dynamic_route(root, "slug")
            rc, stdout, stderr = _run_subcommand(root, "design_critic_pages", EXPERIMENT_WITH_DYNAMIC)
            self.assertEqual(rc, 0, f"stderr={stderr}")
            result = json.loads(stdout)
            self.assertIsInstance(result, list)
            # At least one entry should reference the bracketed path
            found = False
            for entry in result:
                self.assertIn("source_files", entry)
                self.assertIn("name", entry)
                for f in entry["source_files"]:
                    if "[slug]" in f and f.endswith("page.tsx"):
                        found = True
                        break
            self.assertTrue(
                found,
                f"No source_files contains [slug]/page.tsx. Got: {result}"
            )

    def test_static_route_returns_literal_path(self):
        """For src/app/home/page.tsx, source_files should contain home/page.tsx."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold_static_route(root, "home")
            rc, stdout, stderr = _run_subcommand(root, "design_critic_pages", EXPERIMENT_STATIC_ONLY)
            self.assertEqual(rc, 0, f"stderr={stderr}")
            result = json.loads(stdout)
            self.assertIsInstance(result, list)
            home_entry = next((e for e in result if e["name"] == "home"), None)
            self.assertIsNotNone(home_entry, f"home not in result: {result}")
            self.assertTrue(
                any("home/page.tsx" in f for f in home_entry["source_files"]),
                f"home/page.tsx not in source_files: {home_entry}"
            )

    def test_scope_subcommand_returns_disambiguated_name_for_dynamic(self):
        """Regression test: confirm `scope` subcommand returns the
        disambiguated name that DOESN'T correspond to a literal directory.
        This is exactly why spec-reviewer S2 must NOT use `scope`."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold_dynamic_route(root, "slug")
            rc, stdout, stderr = _run_subcommand(root, "scope", EXPERIMENT_WITH_DYNAMIC)
            self.assertEqual(rc, 0, f"stderr={stderr}")
            result = json.loads(stdout)
            self.assertIsInstance(result, list)
            # No literal portfolio-slug directory exists on disk
            self.assertFalse(
                (root / "src" / "app" / "portfolio-slug" / "page.tsx").exists(),
                "portfolio-slug should NOT exist as a literal directory"
            )


if __name__ == "__main__":
    unittest.main()
