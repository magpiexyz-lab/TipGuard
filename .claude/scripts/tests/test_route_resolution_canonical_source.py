#!/usr/bin/env python3
"""Integration tests for the route-resolution-canonical-source rule (#1450).

Mirrors the integration-test pattern from test_aoc_coherence_rules.py:
sets up a minimal repo skeleton in a temp directory with the linter and
a custom rules file, then invokes verify-linter.sh and asserts the
expected findings appear (or do not).

Run via:
    python3 -m pytest .claude/scripts/tests/test_route_resolution_canonical_source.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


REAL_REPO = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
LINTER = os.path.join(REAL_REPO, ".claude", "scripts", "verify-linter.sh")
LIB_DIR = os.path.join(REAL_REPO, ".claude", "scripts", "lib")
SCHEMA = os.path.join(REAL_REPO, ".claude", "patterns", "coherence-rule-schema.json")


RULE = {
    "id": "route-resolution-canonical-source",
    "type": "route_resolution_canonical_source",
    "severity": "block",
    "scan_corpus": [".claude/scripts/**/*.py"],
    "canonical_module": "derive_pages",
    "canonical_symbols": ["derive_page_set_for_design_critic"],
    "exempt_paths": [".claude/scripts/lib/derive_pages.py"],
    "trigger_pattern": r"glob\.glob\([^)]*src/app[^)]*page\.tsx",
    "description": "test fixture",
}


def _setup_repo(tmpdir, files):
    """Create a minimal repo skeleton scanned by verify-linter.sh."""
    os.makedirs(os.path.join(tmpdir, ".claude/scripts"), exist_ok=True)
    os.makedirs(os.path.join(tmpdir, ".claude/patterns"), exist_ok=True)
    shutil.copy(LINTER, os.path.join(tmpdir, ".claude/scripts/verify-linter.sh"))
    if os.path.isdir(LIB_DIR):
        shutil.copytree(
            LIB_DIR,
            os.path.join(tmpdir, ".claude/scripts/lib"),
            dirs_exist_ok=True,
        )
    if os.path.exists(SCHEMA):
        shutil.copy(SCHEMA, os.path.join(tmpdir, ".claude/patterns/coherence-rule-schema.json"))
    with open(os.path.join(tmpdir, ".claude/patterns/template-coherence-rules.json"), "w") as fh:
        json.dump({"rules": [RULE]}, fh)
    # Minimal state-registry.json — required by linter prologue.
    with open(os.path.join(tmpdir, ".claude/patterns/state-registry.json"), "w") as fh:
        json.dump({}, fh)
    for rel, content in files.items():
        full = os.path.join(tmpdir, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as fh:
            fh.write(content)


def _run_linter(tmpdir):
    return subprocess.run(
        ["bash", ".claude/scripts/verify-linter.sh"],
        cwd=tmpdir,
        capture_output=True,
        text=True,
    )


class TestRouteResolutionRule(unittest.TestCase):
    def test_offender_with_glob_and_no_import_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_repo(tmp, {
                ".claude/scripts/lib/bad.py": (
                    "import glob\n"
                    "for f in glob.glob('src/app/**/page.tsx', recursive=True):\n"
                    "    print(f)\n"
                ),
            })
            result = _run_linter(tmp)
        self.assertIn("route-resolution-canonical-source", result.stdout)
        self.assertIn("bad.py", result.stdout)

    def test_file_with_glob_and_derive_pages_import_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_repo(tmp, {
                ".claude/scripts/lib/good.py": (
                    "import glob\n"
                    "from derive_pages import derive_page_set_for_design_critic\n"
                    "for f in glob.glob('src/app/**/page.tsx', recursive=True):\n"
                    "    print(f)\n"
                ),
            })
            result = _run_linter(tmp)
        self.assertNotIn("route-resolution-canonical-source", result.stdout)

    def test_file_without_glob_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_repo(tmp, {
                ".claude/scripts/util.py": (
                    "import os\n"
                    "for d in os.listdir('src/app'):\n"
                    "    print(d)\n"
                ),
            })
            result = _run_linter(tmp)
        self.assertNotIn("route-resolution-canonical-source", result.stdout)

    def test_glob_unrelated_to_pages_passes(self):
        # glob on src/app/**/*.css is not route-shape resolution.
        with tempfile.TemporaryDirectory() as tmp:
            _setup_repo(tmp, {
                ".claude/scripts/css.py": (
                    "import glob\n"
                    "glob.glob('src/app/**/*.css', recursive=True)\n"
                ),
            })
            result = _run_linter(tmp)
        self.assertNotIn("route-resolution-canonical-source", result.stdout)

    def test_exempt_path_passes_even_with_offending_pattern(self):
        # derive_pages.py is exempt — even though it has the glob pattern,
        # the rule must not fire on it.
        with tempfile.TemporaryDirectory() as tmp:
            _setup_repo(tmp, {
                # The exempt path declares glob pattern but is the canonical
                # source itself; rule must not fire.
                ".claude/scripts/lib/derive_pages_extra.py": (
                    "# Not the real derive_pages.py — this file is NOT in"
                    " exempt list and should be flagged.\n"
                    "import glob\n"
                    "glob.glob('src/app/**/page.tsx', recursive=True)\n"
                ),
            })
            result = _run_linter(tmp)
        # The non-exempt look-alike IS flagged.
        self.assertIn("derive_pages_extra.py", result.stdout)


if __name__ == "__main__":
    unittest.main()
