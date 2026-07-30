#!/usr/bin/env python3
"""test_check_init_context_callers.py — static lint for protected-field drops.

Validates the recurrence-prevention linter added in PR3 Phase E2. The linter
scans .claude/{skills,procedures,agents}/**/*.md for init-context.sh callers
that pass protected fields (skill, branch, timestamp, run_id) in extra_json —
fields that init-context.sh silently drops per the #941 protected-fields
policy. Issue #1160 was the prototype symptom (verify state-0 spec drift).

The linter is warn-only (always exits 0). Findings go to:
  - stderr (human-readable)
  - .runs/init-context-caller-findings.jsonl (machine-readable)

Run: python3 .claude/scripts/tests/test_check_init_context_callers.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / ".claude/scripts/check-init-context-callers.sh"


class TestCheckInitContextCallers(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_cicc_"))
        # Need a real git repo because the script uses `git rev-parse --show-toplevel`
        # to resolve PROJECT_DIR. Init + initial commit so PROJECT_DIR resolves.
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        subprocess.run(
            ["git", "-C", str(self.tmp), "config", "user.email", "test@example.com"],
            check=True,
        )
        subprocess.run(["git", "-C", str(self.tmp), "config", "user.name", "test"], check=True)
        # Empty .claude/ scaffolding — tests inject specific .md files per case.
        (self.tmp / ".claude/skills").mkdir(parents=True)
        (self.tmp / ".claude/procedures").mkdir(parents=True)
        (self.tmp / ".claude/agents").mkdir(parents=True)
        (self.tmp / ".runs").mkdir(parents=True)
        # Copy the script itself.
        (self.tmp / ".claude/scripts").mkdir(parents=True, exist_ok=True)
        shutil.copy(SCRIPT, self.tmp / ".claude/scripts/check-init-context-callers.sh")
        # Initial commit so git rev-parse works.
        subprocess.run(
            ["git", "-C", str(self.tmp), "add", "."], check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.tmp), "commit", "-q", "-m", "init"], check=True,
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self) -> tuple[int, str]:
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(self.tmp)
        proc = subprocess.run(
            ["bash", str(self.tmp / ".claude/scripts/check-init-context-callers.sh")],
            capture_output=True, text=True, env=env, cwd=str(self.tmp), timeout=10,
        )
        return proc.returncode, proc.stderr

    def _findings(self) -> list[dict]:
        out = self.tmp / ".runs/init-context-caller-findings.jsonl"
        if not out.exists():
            return []
        return [json.loads(line) for line in out.read_text().splitlines() if line.strip()]

    # ---- Always-exit-0 invariant (warn-only linter) ----

    def test_exits_zero_with_no_callers(self):
        rc, _ = self._run()
        self.assertEqual(rc, 0)

    def test_exits_zero_with_clean_caller(self):
        # init-context.sh caller passing only non-protected fields → no finding.
        (self.tmp / ".claude/skills/test-skill.md").write_text(
            'bash .claude/scripts/init-context.sh test-skill '
            '"{\\"scope\\":\\"full\\",\\"mode\\":\\"standalone\\"}"\n'
        )
        rc, err = self._run()
        self.assertEqual(rc, 0)
        self.assertIn("clean", err)
        self.assertEqual(self._findings(), [])

    def test_exits_zero_with_offender_present(self):
        # Even when a violation is found, exit 0 (warn-only).
        (self.tmp / ".claude/skills/offender.md").write_text(
            'bash .claude/scripts/init-context.sh foo '
            '"{\\"skill\\":\\"bar\\",\\"scope\\":\\"x\\"}"\n'
        )
        rc, _ = self._run()
        self.assertEqual(rc, 0, "linter must always exit 0 (warn-only)")

    # ---- Detection per protected field ----

    def test_detects_skill_protected_field(self):
        path = self.tmp / ".claude/skills/offender.md"
        path.write_text(
            'bash .claude/scripts/init-context.sh foo '
            '"{\\"skill\\":\\"bar\\",\\"scope\\":\\"x\\"}"\n'
        )
        rc, err = self._run()
        findings = self._findings()
        self.assertEqual(len(findings), 1, f"expected 1 finding; got {findings}")
        self.assertIn("skill", findings[0]["protected_fields_passed"])
        self.assertEqual(findings[0]["line"], 1)
        self.assertIn("offender.md", findings[0]["file"])
        self.assertIn("WARN", err)

    def test_detects_branch_protected_field(self):
        (self.tmp / ".claude/skills/offender.md").write_text(
            'bash .claude/scripts/init-context.sh foo '
            '"{\\"branch\\":\\"main\\",\\"scope\\":\\"x\\"}"\n'
        )
        self._run()
        findings = self._findings()
        self.assertEqual(len(findings), 1)
        self.assertIn("branch", findings[0]["protected_fields_passed"])

    def test_detects_timestamp_protected_field(self):
        (self.tmp / ".claude/skills/offender.md").write_text(
            'bash .claude/scripts/init-context.sh foo '
            '"{\\"timestamp\\":\\"2026-01-01\\"}"\n'
        )
        self._run()
        findings = self._findings()
        self.assertEqual(len(findings), 1)
        self.assertIn("timestamp", findings[0]["protected_fields_passed"])

    def test_detects_run_id_protected_field(self):
        (self.tmp / ".claude/skills/offender.md").write_text(
            'bash .claude/scripts/init-context.sh foo '
            '"{\\"run_id\\":\\"abc\\"}"\n'
        )
        self._run()
        findings = self._findings()
        self.assertEqual(len(findings), 1)
        self.assertIn("run_id", findings[0]["protected_fields_passed"])

    def test_attributed_to_is_not_protected(self):
        # attributed_to is the LEGITIMATE override field — must not be flagged.
        (self.tmp / ".claude/skills/legit.md").write_text(
            'bash .claude/scripts/init-context.sh foo '
            '"{\\"attributed_to\\":\\"parent\\",\\"scope\\":\\"x\\"}"\n'
        )
        rc, err = self._run()
        self.assertEqual(self._findings(), [])
        self.assertIn("clean", err)

    # ---- Cross-directory scanning ----

    def test_scans_procedures_directory(self):
        (self.tmp / ".claude/procedures/offender.md").write_text(
            'bash .claude/scripts/init-context.sh foo "{\\"skill\\":\\"x\\"}"\n'
        )
        self._run()
        findings = self._findings()
        self.assertEqual(len(findings), 1)
        self.assertIn("procedures/offender.md", findings[0]["file"])

    def test_scans_agents_directory(self):
        (self.tmp / ".claude/agents/offender.md").write_text(
            'bash .claude/scripts/init-context.sh foo "{\\"skill\\":\\"x\\"}"\n'
        )
        self._run()
        findings = self._findings()
        self.assertEqual(len(findings), 1)
        self.assertIn("agents/offender.md", findings[0]["file"])

    # ---- Multi-field detection ----

    def test_detects_multiple_protected_fields_in_same_call(self):
        (self.tmp / ".claude/skills/offender.md").write_text(
            'bash .claude/scripts/init-context.sh foo '
            '"{\\"skill\\":\\"x\\",\\"run_id\\":\\"y\\",\\"scope\\":\\"z\\"}"\n'
        )
        self._run()
        findings = self._findings()
        self.assertEqual(len(findings), 1)
        # Both protected fields in one finding (deduped + sorted).
        passed = findings[0]["protected_fields_passed"]
        self.assertIn("skill", passed)
        self.assertIn("run_id", passed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
