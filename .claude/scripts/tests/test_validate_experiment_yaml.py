#!/usr/bin/env python3
"""Behavioral tests for validate_experiment_yaml.py.

Covers:
- Valid kebab-case names pass and write a clean trace
- Various invalid names fail with a kebab-case suggestion
- Missing `name` field fails distinctly from non-kebab `name`
- Trace file is written on BOTH success and failure paths (state-3 VERIFY
  audits the trace, so it must always exist after a script run)

Run via: python3 .claude/scripts/tests/test_validate_experiment_yaml.py
Or via:  bash .claude/scripts/tests/run-all.sh
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

REAL_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SCRIPT = os.path.join(REAL_REPO, ".claude", "scripts", "lib", "validate_experiment_yaml.py")


def _run(yaml_text: str, tmpdir: str) -> tuple[int, str, dict]:
    """Run the validator with yaml_text written to a temp file.

    Returns (exit_code, stderr_text, trace_dict).
    """
    yaml_path = os.path.join(tmpdir, "experiment.yaml")
    trace_path = os.path.join(tmpdir, "trace.json")
    with open(yaml_path, "w") as fh:
        fh.write(yaml_text)
    result = subprocess.run(
        ["python3", SCRIPT, "--yaml", yaml_path, "--trace", trace_path],
        capture_output=True,
        text=True,
    )
    if os.path.exists(trace_path):
        with open(trace_path) as fh:
            trace = json.load(fh)
    else:
        trace = {}
    return result.returncode, result.stderr, trace


class TestValidateKebab(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_valid_kebab_passes(self):
        for name in ("stylica-ai", "xpredict", "a", "a-b-c-1", "agent-cost-monitor"):
            with self.subTest(name=name):
                code, err, trace = _run(f"name: {name}\n", self.tmpdir)
                self.assertEqual(code, 0, f"expected pass for {name!r}; stderr={err}")
                self.assertTrue(trace.get("experiment_valid"))
                self.assertEqual(trace.get("checks_failed"), [])
                self.assertIn("name", trace.get("checks_passed", []))

    def test_uppercase_fails_with_suggestion(self):
        code, err, trace = _run('name: "Stylica AI"\n', self.tmpdir)
        self.assertEqual(code, 1)
        self.assertFalse(trace.get("experiment_valid"))
        self.assertIn("name_not_kebab", trace.get("checks_failed"))
        self.assertIn("stylica-ai", err)
        self.assertIn("Stylica AI", err)

    def test_underscore_fails_with_suggestion(self):
        code, err, trace = _run('name: "stylica_ai"\n', self.tmpdir)
        self.assertEqual(code, 1)
        self.assertIn("name_not_kebab", trace.get("checks_failed"))
        self.assertIn("stylica-ai", err)

    def test_camelcase_fails_with_suggestion(self):
        code, err, trace = _run('name: "StylicaAI"\n', self.tmpdir)
        self.assertEqual(code, 1)
        self.assertIn("name_not_kebab", trace.get("checks_failed"))
        self.assertIn("stylicaai", err)

    def test_leading_digit_fails(self):
        # The pattern requires a letter prefix; "1foo" is rejected.
        # kebab_suggest cannot auto-fix this safely (it doesn't know what
        # prefix to add), so the suggestion message should signal manual fix.
        code, err, trace = _run('name: "1foo"\n', self.tmpdir)
        self.assertEqual(code, 1)
        self.assertIn("name_not_kebab", trace.get("checks_failed"))

    def test_consecutive_punctuation_collapsed_in_suggestion(self):
        code, err, trace = _run('name: "stylica   AI"\n', self.tmpdir)
        self.assertEqual(code, 1)
        self.assertIn("stylica-ai", err)
        self.assertNotIn("stylica---ai", err)

    def test_trailing_punctuation_trimmed_in_suggestion(self):
        code, err, trace = _run('name: "stylica-ai-"\n', self.tmpdir)
        self.assertEqual(code, 1)
        self.assertIn("stylica-ai", err)

    def test_missing_name_fails_distinctly(self):
        code, err, trace = _run("owner: lego\n", self.tmpdir)
        self.assertEqual(code, 1)
        self.assertIn("name_missing", trace.get("checks_failed"))
        self.assertNotIn("name_not_kebab", trace.get("checks_failed"))
        self.assertIn("missing", err.lower())

    def test_empty_name_fails(self):
        code, err, trace = _run('name: ""\n', self.tmpdir)
        self.assertEqual(code, 1)
        self.assertIn("name_missing", trace.get("checks_failed"))

    def test_trace_always_written_on_failure(self):
        # State-3 VERIFY reads the trace — must always exist after a run.
        code, err, trace = _run('name: "BAD"\n', self.tmpdir)
        self.assertEqual(code, 1)
        self.assertTrue(trace, "trace must be written even on failure")
        self.assertEqual(trace.get("experiment_valid"), False)

    def test_trace_always_written_on_success(self):
        code, err, trace = _run("name: ok-name\n", self.tmpdir)
        self.assertEqual(code, 0)
        self.assertTrue(trace)
        self.assertEqual(trace.get("experiment_valid"), True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
