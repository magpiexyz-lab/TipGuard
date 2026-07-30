#!/usr/bin/env python3
"""test_markdown_cross_file_line_reference.py — pin the rule contract.

Validates the markdown_cross_file_line_reference rule (template-coherence-
rules.json). Issue #1238: line-number cross-references between template
files rot silently when the referenced file is edited.

Branch 1 (cross-file): emits when a strong line-number qualifier
(parenthesized form, range, or `on line N`) co-occurs in a 3-line window
with a path-mention to a template-eligible file (extensions: md, yaml,
yml, json, py, sh; src/-prefixed paths excluded).

Branch 2 (same-file): emits when the qualifier appears with no path-mention
in the 3-line window (and no path of any extension in the same window).

Pragma `<!-- coherence-allow: line-number-cross-reference[: <reason>] -->`
within ±5 lines suppresses both branches.

Run: python3 .claude/scripts/tests/test_markdown_cross_file_line_reference.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


class TestMarkdownCrossFileLineReference(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_mclr_"))
        shutil.copytree(ROOT / ".claude", self.tmp / ".claude", dirs_exist_ok=True)
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_linter(self) -> tuple[int, str, str]:
        env = os.environ.copy()
        env["VL_REPO_ROOT"] = str(self.tmp)
        env["VL_RULES_PATH"] = str(self.tmp / ".claude/patterns/template-coherence-rules.json")
        env["VL_JSON_OUT"] = "1"
        env["VL_WARN_ONLY"] = "1"
        proc = subprocess.run(
            ["python3", str(self.tmp / ".claude/scripts/lib/linter/cli.py")],
            capture_output=True, text=True, env=env, timeout=60,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def _findings_for_file(self, rel: str) -> list[str]:
        rc, stdout, stderr = self._run_linter()
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            self.fail(f"linter did not return JSON: rc={rc} stdout={stdout!r} stderr={stderr!r}")
        return [f for f in data.get("cross_file_contradiction", [])
                if "markdown-cross-file-line-reference" in f and rel in f]

    def _all_findings(self) -> list[str]:
        rc, stdout, stderr = self._run_linter()
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            self.fail(f"linter did not return JSON: rc={rc} stdout={stdout!r}")
        return [f for f in data.get("cross_file_contradiction", [])
                if "markdown-cross-file-line-reference" in f]

    def _write_md(self, rel: str, content: str):
        path = self.tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    # ---- Default repo state (after migrations) ----

    def test_default_repo_state_passes(self):
        """The committed migrations + pragmas + tightened qualifier regex
        should produce zero findings in the default repo state."""
        findings = self._all_findings()
        self.assertEqual(findings, [], f"unexpected default-state findings: {findings}")

    # ---- Branch 1 (cross-file) ----

    def test_cross_file_with_path_and_line_range_fires(self):
        """`merge-design-critic-traces.py L121-138` — historical Branch 1 shape."""
        self._write_md(
            ".claude/skills/test/state-x.md",
            "# Test\n\nThe gate logic in `merge-design-critic-traces.py` L121-138 excludes...\n",
        )
        findings = self._findings_for_file(".claude/skills/test/state-x.md")
        self.assertTrue(
            any("cross-file line-number reference" in f for f in findings),
            f"expected Branch 1 finding, got: {findings}",
        )

    def test_cross_file_with_parenthesized_form_fires(self):
        self._write_md(
            ".claude/skills/test/state-y.md",
            "# Test\n\nSee `helper.py` (line 60-62) for the contract.\n",
        )
        findings = self._findings_for_file(".claude/skills/test/state-y.md")
        self.assertTrue(any("Branch" not in f for f in findings) and findings,
                        f"expected fire on '(line 60-62)', got: {findings}")

    def test_cross_file_with_section_anchor_passes(self):
        self._write_md(
            ".claude/skills/test/state-z.md",
            "# Test\n\nSee `state-3b-quality-gate.md#archetype-gate` for the gate semantics.\n",
        )
        findings = self._findings_for_file(".claude/skills/test/state-z.md")
        self.assertEqual(findings, [], f"section anchor should not fire, got: {findings}")

    def test_cross_file_with_search_anchor_passes(self):
        self._write_md(
            ".claude/skills/test/state-w.md",
            "# Test\n\nThe filter is in `merge-traces.py: search for \"boundary-skip\"`.\n",
        )
        findings = self._findings_for_file(".claude/skills/test/state-w.md")
        self.assertEqual(findings, [], f"search anchor should not fire, got: {findings}")

    def test_src_path_excluded_from_branch_1(self):
        """src/ paths are scaffold-emitted code; line refs to them are
        intentionally not flagged (Branch 1 excludes them)."""
        self._write_md(
            ".claude/skills/test/state-src.md",
            "# Test\n\nSee `src/lib/stripe.ts` (line 60-62) for the throw contract.\n",
        )
        findings = self._findings_for_file(".claude/skills/test/state-src.md")
        # Branch 1 excludes src/. Branch 2 should ALSO not fire because
        # any-path detection finds `src/lib/stripe.ts` in the window.
        self.assertEqual(findings, [], f"src/ path ref should not fire, got: {findings}")

    # ---- Branch 2 (same-file) ----

    def test_same_file_line_range_fires_branch_2(self):
        self._write_md(
            ".claude/skills/test/state-self.md",
            "# Test\n\nApply the same filter at lines 38-42 of this file.\n",
        )
        findings = self._findings_for_file(".claude/skills/test/state-self.md")
        self.assertTrue(
            any("same-file line-number reference" in f for f in findings),
            f"expected Branch 2 finding, got: {findings}",
        )

    def test_on_line_n_fires_branch_2(self):
        self._write_md(
            ".claude/skills/test/state-on-line.md",
            "# Test\n\nThe fallback on line 79 already uses the placeholder.\n",
        )
        findings = self._findings_for_file(".claude/skills/test/state-on-line.md")
        self.assertTrue(
            any("same-file line-number reference" in f for f in findings),
            f"expected Branch 2 finding on 'on line N', got: {findings}",
        )

    # ---- Funnel-stage label false-positives (must NOT fire) ----

    def test_funnel_stage_l1_l2_l3_passes(self):
        """`L1`/`L2`/`L3` standalone funnel labels should not fire (the
        qualifier regex requires a range form for `L\\d+`)."""
        self._write_md(
            ".claude/skills/test/state-funnel.md",
            "# Funnel\n\n- reach: L1\n- demand: L2\n- conversion: L3\n",
        )
        findings = self._findings_for_file(".claude/skills/test/state-funnel.md")
        self.assertEqual(findings, [], f"standalone L1/L2/L3 should not fire, got: {findings}")

    def test_description_line_n_passes(self):
        """`Description line 1` (Google Ads field label) is content prose,
        not a citation. Should not fire."""
        self._write_md(
            ".claude/skills/test/state-ad-labels.md",
            "# Ad Labels\n\n- Description line 1: up to 35 characters\n- Description line 2: up to 35 characters\n",
        )
        findings = self._findings_for_file(".claude/skills/test/state-ad-labels.md")
        self.assertEqual(findings, [], f"Description line N should not fire, got: {findings}")

    # ---- Pragma suppression ----

    def test_pragma_allows_branch_1(self):
        self._write_md(
            ".claude/skills/test/state-pragma1.md",
            "# Test\n\n"
            "<!-- coherence-allow: line-number-cross-reference: legitimate cross-link -->\n"
            "See `helper.py` (line 60-62) for the contract.\n",
        )
        findings = self._findings_for_file(".claude/skills/test/state-pragma1.md")
        self.assertEqual(findings, [], f"pragma should suppress Branch 1, got: {findings}")

    def test_pragma_allows_branch_2(self):
        self._write_md(
            ".claude/skills/test/state-pragma2.md",
            "# Test\n\nApply the same filter at lines 38-42 of this file.\n"
            "<!-- coherence-allow: line-number-cross-reference: same-file ref is stable -->\n",
        )
        findings = self._findings_for_file(".claude/skills/test/state-pragma2.md")
        self.assertEqual(findings, [], f"pragma should suppress Branch 2, got: {findings}")

    def test_pragma_window_5_lines(self):
        """Single bracketing pragma should cover up to 5 surrounding lines
        (covers fenced code blocks and markdown tables)."""
        self._write_md(
            ".claude/skills/test/state-pragma-block.md",
            "# Test\n\n"
            "<!-- coherence-allow: line-number-cross-reference: anti-pattern documentation -->\n"
            "```\n"
            "merge-design-critic-traces.py L121-138        # rotting reference\n"
            "state-3b-quality-gate.md (lines 7-31)         # parenthesized\n"
            "```\n",
        )
        findings = self._findings_for_file(".claude/skills/test/state-pragma-block.md")
        self.assertEqual(findings, [], f"pragma should cover full code block, got: {findings}")


if __name__ == "__main__":
    unittest.main()
