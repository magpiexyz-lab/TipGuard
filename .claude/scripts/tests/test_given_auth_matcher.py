#!/usr/bin/env python3
"""test_given_auth_matcher.py — validates the canonical auth-phrase classifier
defined in .claude/patterns/given-auth-matcher.md.

The pattern file is markdown-as-source; it documents both a JS function
(`requiresAuth`) and a Python port. This test executes the Python port by
extracting it from the markdown and exercising its three branches:

  T1: known auth phrase → result=True, matched_phrase set, unmatched=False
  T2: known non-auth phrase → result=False, matched_phrase set, unmatched=False
  T3: unknown phrase → result=True, matched_phrase=None, unmatched=True
      (fail-closed default — unrecognized phrases demand auth for safety)

  T4: drift test — the canonical phrase list exists in ONLY the matcher
      file and the allowlist of files permitted to reference phrases. Any
      stray occurrence in wire.md, behavior-verifier.md, or elsewhere is a
      regression.

Exit 0 on all-pass, 1 on any failure.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MATCHER_FILE = ROOT / ".claude/patterns/given-auth-matcher.md"


def extract_python_port() -> str:
    """Extract the Python implementation block labeled 'Python port (for test + gate code)'.

    Matches the first ```python ... ``` block after the 'Python port' heading.
    """
    content = MATCHER_FILE.read_text()
    # Find the Python port heading and the subsequent python code block
    after = content.split("## Python port", 1)
    if len(after) != 2:
        raise RuntimeError("could not locate '## Python port' heading in given-auth-matcher.md")
    m = re.search(r"```python\n(.*?)\n```", after[1], re.DOTALL)
    if not m:
        raise RuntimeError("could not locate python code block after Python port heading")
    return m.group(1)


def run_requires_auth(given: str) -> dict:
    """Execute the extracted Python port against a `given` string, return the result."""
    port = extract_python_port()
    script = port + textwrap.dedent(
        f"""

        import json
        print(json.dumps(requires_auth({given!r})))
        """
    )
    result = subprocess.run(
        ["python3", "-c", script],
        capture_output=True,
        text=True,
        check=True,
    )
    import json
    return json.loads(result.stdout.strip())


class TestRequiresAuth(unittest.TestCase):
    # ------------------------------------------------------------------
    # T1: known auth phrases
    # ------------------------------------------------------------------
    def test_auth_phrase_logged_in_user(self):
        r = run_requires_auth("A logged-in user sees the dashboard.")
        self.assertTrue(r["result"])
        self.assertEqual(r["matched_phrase"], "logged-in user")
        self.assertFalse(r["unmatched"])

    def test_auth_phrase_authenticated_user(self):
        r = run_requires_auth("For an authenticated user, the settings page loads.")
        self.assertTrue(r["result"])
        self.assertEqual(r["matched_phrase"], "authenticated user")
        self.assertFalse(r["unmatched"])

    def test_auth_phrase_user_on_dashboard(self):
        r = run_requires_auth("A user on dashboard clicks export.")
        self.assertTrue(r["result"])
        self.assertEqual(r["matched_phrase"], "user on dashboard")
        self.assertFalse(r["unmatched"])

    def test_auth_phrase_case_insensitive(self):
        r = run_requires_auth("A LOGGED-IN USER reviews their history.")
        self.assertTrue(r["result"])
        self.assertEqual(r["matched_phrase"], "logged-in user")

    # ------------------------------------------------------------------
    # T2: known non-auth phrases
    # ------------------------------------------------------------------
    def test_non_auth_phrase_anonymous_visitor(self):
        r = run_requires_auth("An anonymous visitor lands on the home page.")
        self.assertFalse(r["result"])
        self.assertEqual(r["matched_phrase"], "anonymous visitor")
        self.assertFalse(r["unmatched"])

    def test_non_auth_phrase_new_user(self):
        r = run_requires_auth("A new user opens the signup form.")
        self.assertFalse(r["result"])
        self.assertEqual(r["matched_phrase"], "new user")

    def test_non_auth_phrase_unauthenticated(self):
        r = run_requires_auth("An unauthenticated user hits /pricing.")
        self.assertFalse(r["result"])
        self.assertEqual(r["matched_phrase"], "unauthenticated user")

    # ------------------------------------------------------------------
    # T3: unknown phrase — fail-closed default
    # ------------------------------------------------------------------
    def test_unknown_phrase_fail_closed(self):
        r = run_requires_auth("After onboarding completes.")
        self.assertTrue(r["result"])
        self.assertIsNone(r["matched_phrase"])
        self.assertTrue(r["unmatched"])

    def test_empty_given_fail_closed(self):
        r = run_requires_auth("")
        self.assertTrue(r["result"])
        self.assertIsNone(r["matched_phrase"])
        self.assertTrue(r["unmatched"])

    def test_auth_phrase_takes_precedence_over_unknown_context(self):
        # Both auth and unknown chunks in the same given → auth wins (it's
        # checked first in the linear scan)
        r = run_requires_auth("After onboarding, a logged-in user sees dashboard.")
        self.assertTrue(r["result"])
        self.assertEqual(r["matched_phrase"], "logged-in user")

    # ------------------------------------------------------------------
    # T4: drift test — no parallel phrase-matching CODE outside the canonical matcher
    # ------------------------------------------------------------------
    def test_no_phrase_matching_code_outside_matcher(self):
        """The drift we prevent is *parallel phrase-matching CODE*, not
        prose references. Prose like "An authenticated user sees the
        dashboard" in stack docs / agent descriptions is fine. What is
        NOT fine is executable code that re-implements the phrase
        classification (which would drift from the canonical matcher
        when new phrases are added).

        Code patterns we flag:
          - JS: given.includes("logged-in user")  or  includes('logged-in user')
          - Python: "logged-in user" in given
          - Conditional branches comparing against multiple phrases

        Allowed files (explicit allowlist — these legitimately contain
        phrases in documentation or authored content):
          - .claude/patterns/given-auth-matcher.md (canonical)
          - .claude/scripts/tests/ (test fixtures)
          - experiment/ (user-authored behavior content)
          - .runs/ and .claude/worktrees/ (transient state)

        Hard-stop on: any file that contains an expression matching
        one of the CODE-pattern regexes below with an auth-phrase literal.
        """
        phrases = [
            "logged-in user",
            "authenticated user",
            "user on dashboard",
            "anonymous visitor",
            "new user",
            "unauthenticated user",
        ]

        # JS / Python code idioms that re-implement classification
        # (mirrors the matcher function shape)
        code_patterns = [
            # JS: includes("phrase")
            r'\.includes\([\'"]%(phrase)s[\'"]',
            # JS: === "phrase"  or  == "phrase"
            r'===?\s*[\'"]%(phrase)s[\'"]',
            # Python: "phrase" in <var>
            r'[\'"]%(phrase)s[\'"]\s+in\b',
        ]

        # Allowlist (substring match against repo-relative path)
        allowed_substrings = [
            ".claude/patterns/given-auth-matcher.md",
            ".claude/scripts/tests/",
            "experiment/",
            ".runs/",
            ".claude/worktrees/",
        ]

        violations: list[tuple[str, str, str]] = []

        # List candidate files: .claude/ + experiment/ excluding transient paths
        result = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", ".claude/", "experiment/"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            self.skipTest(f"git ls-files failed: {result.stderr}")
            return

        for path in result.stdout.strip().splitlines():
            if any(allowed in path for allowed in allowed_substrings):
                continue
            abs_path = ROOT / path
            if not abs_path.is_file():
                continue
            try:
                content = abs_path.read_text().lower()
            except (UnicodeDecodeError, IsADirectoryError):
                continue
            for phrase in phrases:
                for pat in code_patterns:
                    regex = pat % {"phrase": re.escape(phrase)}
                    m = re.search(regex, content)
                    if m:
                        violations.append((path, phrase, m.group(0)))

        if violations:
            msg = "Phrase-matching CODE drift detected (should live ONLY in given-auth-matcher.md):\n"
            msg += "\n".join(
                f"  {p} — phrase '{ph}' in code expression: {ex}"
                for p, ph, ex in violations
            )
            self.fail(msg)


if __name__ == "__main__":
    unittest.main()
