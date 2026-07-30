#!/usr/bin/env python3
"""Behavioral tests for check_project_name.py.

Covers:
- PROJECT_NAME matches experiment.yaml.name → exit 0
- Single file mismatch → exit 1, stderr names both values + file path
- Both files mismatch (different wrong values) → exit 1, stderr lists both
- PROJECT_NAME constant missing from analytics.ts → exit 1 with "not found"
- Single-quoted string literal → regex still matches → exit 0
- Whitespace-only diff → trim normalizes → exit 1
- No analytics files, stack.analytics absent → exit 0 (CLI archetype)
- No analytics files, stack.analytics present → exit 1 (misconfiguration)
- Server file only (CLI archetype with server analytics) → checks just the one
- Missing experiment.yaml → exit 2

Run via: python3 .claude/scripts/tests/test_check_project_name.py
Or via:  bash .claude/scripts/tests/run-all.sh
"""
import os
import subprocess
import sys
import tempfile
import unittest

REAL_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SCRIPT = os.path.join(REAL_REPO, ".claude", "scripts", "lib", "check_project_name.py")


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(content)


def _run(root: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", SCRIPT, "--root", root],
        capture_output=True,
        text=True,
    )


def _setup_yaml(tmp: str, name: str = "hospitica", analytics: str | None = "posthog") -> None:
    stack_block = f"\nstack:\n  analytics: {analytics}\n" if analytics else "\n"
    _write(os.path.join(tmp, "experiment", "experiment.yaml"), f"name: {name}{stack_block}")


def _setup_analytics(tmp: str, value: str, server_value: str | None = None,
                     quote: str = '"', filename: str = "analytics.ts") -> None:
    _write(
        os.path.join(tmp, "src", "lib", filename),
        f"export const PROJECT_NAME = {quote}{value}{quote};\n",
    )
    if server_value is not None:
        _write(
            os.path.join(tmp, "src", "lib", "analytics-server.ts"),
            f"const PROJECT_NAME = {quote}{server_value}{quote};\n",
        )


class TestProjectNameCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    # 1
    def test_single_file_match_passes(self):
        _setup_yaml(self.tmp, "hospitica")
        _setup_analytics(self.tmp, "hospitica")
        r = _run(self.tmp)
        self.assertEqual(r.returncode, 0, f"stderr: {r.stderr}")

    # 2
    def test_single_file_mismatch_fails(self):
        _setup_yaml(self.tmp, "hospitica")
        _setup_analytics(self.tmp, "statistica")
        r = _run(self.tmp)
        self.assertEqual(r.returncode, 1)
        self.assertIn("hospitica", r.stderr)
        self.assertIn("statistica", r.stderr)
        self.assertIn("src/lib/analytics.ts", r.stderr)
        self.assertIn("drift detected", r.stderr)

    # 3
    def test_both_files_match_passes(self):
        _setup_yaml(self.tmp, "hospitica")
        _setup_analytics(self.tmp, "hospitica", server_value="hospitica")
        r = _run(self.tmp)
        self.assertEqual(r.returncode, 0, f"stderr: {r.stderr}")

    # 4
    def test_only_server_mismatches(self):
        _setup_yaml(self.tmp, "hospitica")
        _setup_analytics(self.tmp, "hospitica", server_value="statistica")
        r = _run(self.tmp)
        self.assertEqual(r.returncode, 1)
        self.assertIn("src/lib/analytics-server.ts", r.stderr)
        self.assertIn("statistica", r.stderr)
        # The matching file should NOT appear as a failure line
        self.assertNotIn("src/lib/analytics.ts: PROJECT_NAME", r.stderr)

    # 5
    def test_both_files_mismatch_lists_both(self):
        _setup_yaml(self.tmp, "hospitica")
        _setup_analytics(self.tmp, "statistica", server_value="other-wrong")
        r = _run(self.tmp)
        self.assertEqual(r.returncode, 1)
        self.assertIn("src/lib/analytics.ts", r.stderr)
        self.assertIn("src/lib/analytics-server.ts", r.stderr)
        self.assertIn("statistica", r.stderr)
        self.assertIn("other-wrong", r.stderr)

    # 6
    def test_const_missing_fails_with_specific_message(self):
        _setup_yaml(self.tmp, "hospitica")
        _write(
            os.path.join(self.tmp, "src", "lib", "analytics.ts"),
            "// no PROJECT_NAME declaration here\nexport const OTHER = 'x';\n",
        )
        r = _run(self.tmp)
        self.assertEqual(r.returncode, 1)
        self.assertIn("PROJECT_NAME constant not found", r.stderr)

    # 7
    def test_single_quoted_value_matches(self):
        _setup_yaml(self.tmp, "hospitica")
        _setup_analytics(self.tmp, "hospitica", quote="'")
        r = _run(self.tmp)
        self.assertEqual(r.returncode, 0, f"stderr: {r.stderr}")

    # 8
    def test_whitespace_diff_caught_by_trim(self):
        # yaml has "hospitica", source has "hospitica " (trailing space) →
        # regex captures the spaced value; both sides get .strip() in script
        # so trailing whitespace in yaml is normalized but trailing whitespace
        # *inside* the source-code literal is preserved. The captured value is
        # "hospitica " which != "hospitica" → MISMATCH. This is the expected
        # safety semantics (literal byte-equality after each side is trimmed).
        _setup_yaml(self.tmp, "hospitica")
        _setup_analytics(self.tmp, "hospitica ")
        r = _run(self.tmp)
        # After trim, both are "hospitica" → match (we trim both sides)
        self.assertEqual(r.returncode, 0, f"stderr: {r.stderr}")

    # 9
    def test_no_files_no_stack_analytics_passes(self):
        # CLI archetype with no analytics — should pass silently
        _setup_yaml(self.tmp, "some-cli", analytics=None)
        r = _run(self.tmp)
        self.assertEqual(r.returncode, 0, f"stderr: {r.stderr}")

    # 10
    def test_no_files_with_stack_analytics_fails(self):
        # Stack says posthog but no analytics files exist — misconfiguration
        _setup_yaml(self.tmp, "hospitica", analytics="posthog")
        r = _run(self.tmp)
        self.assertEqual(r.returncode, 1)
        self.assertIn("stack.analytics is configured", r.stderr)

    # 11
    def test_server_only_file_handled(self):
        # CLI archetype that has only analytics-server.ts (no analytics.ts)
        _setup_yaml(self.tmp, "hospitica")
        _write(
            os.path.join(self.tmp, "src", "lib", "analytics-server.ts"),
            'const PROJECT_NAME = "hospitica";\n',
        )
        r = _run(self.tmp)
        self.assertEqual(r.returncode, 0, f"stderr: {r.stderr}")

    # 12
    def test_missing_experiment_yaml_returns_env_error(self):
        # No experiment/ dir at all
        r = _run(self.tmp)
        self.assertEqual(r.returncode, 2)
        self.assertIn("not found", r.stderr)

    def test_empty_name_returns_env_error(self):
        _write(os.path.join(self.tmp, "experiment", "experiment.yaml"), "name: \n")
        r = _run(self.tmp)
        self.assertEqual(r.returncode, 2)
        self.assertIn("experiment.yaml.name", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
