#!/usr/bin/env python3
"""test_gecr_cutover_linter_rule.py — behavioral tests for the
gecr-cutover-overdue coherence rule (#1855 remediation).

Pins: window math (fires only past soak_window_min_days), the
flip_pr_required:false silencer, and the mechanism-split instruction text
(GATE_EVIDENCE_* rules point at gate-evidence-rules.json severity；
CONSULTATION_DENY points at the =1 env spelling the code actually tests).
The real criteria file gets time-INDEPENDENT smoke assertions only — the
"linter is quiet today" check lives in PR verification commands, never in a
test (it would become a scheduled failure the day the window expires).

Run: python3 .claude/scripts/tests/test_gecr_cutover_linter_rule.py
"""
from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LINTER = ROOT / ".claude/scripts/verify-linter.sh"
LIB_DIR = ROOT / ".claude/scripts/lib"
REAL_CRITERIA = ROOT / ".claude/patterns/gecr-cutover-criteria.json"


def _days_ago_iso(days: int) -> str:
    t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


class GecrRuleFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_gecr_lint_"))
        (self.tmp / ".claude/scripts").mkdir(parents=True)
        (self.tmp / ".claude/patterns").mkdir(parents=True)
        (self.tmp / ".claude/skills").mkdir(parents=True)
        shutil.copy(LINTER, self.tmp / ".claude/scripts/verify-linter.sh")
        shutil.copytree(LIB_DIR, self.tmp / ".claude/scripts/lib", dirs_exist_ok=True)
        (self.tmp / ".claude/patterns/state-registry.json").write_text("{}")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_linter(self, criteria: dict) -> str:
        (self.tmp / ".claude/patterns/gecr-cutover-criteria.json").write_text(
            json.dumps(criteria)
        )
        (self.tmp / ".claude/patterns/template-coherence-rules.json").write_text(
            json.dumps({"rules": [{
                "id": "gecr-cutover-overdue",
                "type": "gecr_cutover_overdue",
                "severity": "warn",
                "criteria_path": ".claude/patterns/gecr-cutover-criteria.json",
            }]})
        )
        r = subprocess.run(
            ["bash", str(self.tmp / ".claude/scripts/verify-linter.sh")],
            cwd=self.tmp, capture_output=True, text=True, timeout=120,
        )
        return r.stdout + r.stderr

    @staticmethod
    def _entry(mode_env: str, *, soak: int, merged_days_ago: int,
               flip_required=True) -> dict:
        return {
            "soak_window_min_days": soak,
            "soak_window_min_real_cycles": 2,
            "deny_flip_trigger": "at least 1 candidate",
            "first_merged_at": _days_ago_iso(merged_days_ago),
            "flip_pr_required": flip_required,
            "tracker": "#0000-test",
            "mode_env": mode_env,
        }


class TestGecrCutoverOverdue(GecrRuleFixture):
    def test_inside_window_is_quiet(self):
        out = self.run_linter({"schema_version": 1, "rules": {
            "r1": self._entry("GATE_EVIDENCE_X_MODE", soak=30, merged_days_ago=10),
        }})
        self.assertNotIn("gecr-cutover-overdue", out)

    def test_past_window_fires(self):
        out = self.run_linter({"schema_version": 1, "rules": {
            "r1": self._entry("GATE_EVIDENCE_X_MODE", soak=30, merged_days_ago=40),
        }})
        self.assertIn("gecr-cutover-overdue", out)
        self.assertIn("'r1'", out)

    def test_flip_pr_required_false_silences(self):
        out = self.run_linter({"schema_version": 1, "rules": {
            "r1": self._entry("GATE_EVIDENCE_X_MODE", soak=30, merged_days_ago=40,
                              flip_required=False),
        }})
        self.assertNotIn("gecr-cutover-overdue", out)

    def test_gate_evidence_rule_message_names_severity_mechanism(self):
        out = self.run_linter({"schema_version": 1, "rules": {
            "r1": self._entry("GATE_EVIDENCE_X_MODE", soak=30, merged_days_ago=40),
        }})
        self.assertIn('severity to "block" in', out)
        self.assertIn("gate-evidence-rules.json", out)
        self.assertIn("GATE_EVIDENCE_X_MODE=deny", out)

    def test_consultation_message_names_env_one_spelling(self):
        out = self.run_linter({"schema_version": 1, "rules": {
            "c1": self._entry("CONSULTATION_DENY", soak=30, merged_days_ago=40),
        }})
        self.assertIn("export CONSULTATION_DENY=1", out)
        self.assertNotIn("CONSULTATION_DENY=deny in the rule's severity", out)

    def test_real_criteria_file_time_independent_invariants(self):
        d = json.loads(REAL_CRITERIA.read_text())
        rules = d["rules"]
        self.assertEqual(
            set(rules), {"recovery-path-skip-pairing", "sparse-trace-pairing",
                         "prior-failure-consultation-gate"})
        for rule_id, entry in rules.items():
            self.assertIsNotNone(
                entry["first_merged_at"],
                f"{rule_id}: first_merged_at must be explicit (the git-log "
                f"fallback clock breaks once this file is edited)")
            datetime.datetime.fromisoformat(
                entry["first_merged_at"].replace("Z", "+00:00"))
            self.assertTrue(entry["flip_pr_required"],
                            f"{rule_id}: soak is extended, not faked-flipped")
            self.assertIn("#2013", entry["tracker"])


if __name__ == "__main__":
    sys.exit(unittest.main())
