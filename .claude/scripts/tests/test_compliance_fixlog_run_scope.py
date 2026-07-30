#!/usr/bin/env python3
"""test_compliance_fixlog_run_scope.py — regression for the whole-ledger drift
in compliance-audit.py's check_fix_log_count (same defect class as #1417b and
#2009): the ledger is append-only ACROSS runs by design while the observer
evaluates the current run, so an unscoped count is a guaranteed false anomaly
after the first run that ever recorded a fix — and one false anomaly resets
audit-sample's decay ladder (rate 0.5, 10-run cooldown). The fix counts only
rows whose run_id matches --run-id; degraded inputs skip, never fail.

Run: python3 -m pytest .claude/scripts/tests/test_compliance_fixlog_run_scope.py -v
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
SCRIPT = ROOT / ".claude/scripts/compliance-audit.py"
RUN_ID = "iterate-cross-fixlog-run-1"


class ComplianceFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_caflc_"))
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.tmp, check=True)
        self.runs = self.tmp / ".runs"
        (self.runs / "agent-traces").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _ledger(self, rows: list[dict]):
        with open(self.runs / "fix-ledger.jsonl", "w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")

    @staticmethod
    def _row(run_id, idx=0):
        d = {"fix_id": f"a:{run_id}:{idx}", "agent": "a", "file": "f",
             "symptom": "s", "fix": "x", "provenance": "lead"}
        if run_id is not None:
            d["run_id"] = run_id
        return d

    def _observer(self, fixes_evaluated, run_id=RUN_ID):
        d = {"agent": "observer", "verdict": "clean",
             "fixes_evaluated": fixes_evaluated}
        if run_id is not None:
            d["run_id"] = run_id
        (self.runs / "agent-traces" / "observer.json").write_text(json.dumps(d))

    def run_check(self, run_id=RUN_ID) -> dict:
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(self.tmp)
        r = subprocess.run(
            ["python3", str(SCRIPT), "--skill", "iterate-cross", "--run-id", run_id],
            cwd=self.tmp, capture_output=True, text=True, env=env, timeout=60,
        )
        result = json.loads((self.runs / "compliance-audit-result.json").read_text())
        checks = {c["name"]: c for c in result["checks"]}
        self.assertIn("fix_log_count", checks, r.stderr)
        return checks["fix_log_count"]

    def test_prior_run_rows_do_not_count(self):
        self._ledger([self._row("stale-run-1"), self._row("stale-run-2", 1)])
        self._observer(0)
        c = self.run_check()
        self.assertEqual(c["result"], "pass", c)

    def test_mixed_history_matches_current_run(self):
        rows = [self._row("stale-run-1", i) for i in range(150)]
        rows += [self._row(RUN_ID, 200), self._row(RUN_ID, 201)]
        self._ledger(rows)
        self._observer(2)
        c = self.run_check()
        self.assertEqual(c["result"], "pass", c)
        self.assertIn("150 prior-run", c["detail"])

    def test_current_run_mismatch_fails(self):
        self._ledger([self._row(RUN_ID), self._row(RUN_ID, 1)])
        self._observer(1)
        c = self.run_check()
        self.assertEqual(c["result"], "fail", c)

    def test_legacy_rows_without_run_id_are_excluded(self):
        self._ledger([self._row(None), self._row(RUN_ID, 1)])
        self._observer(1)
        c = self.run_check()
        self.assertEqual(c["result"], "pass", c)
        self.assertIn("1 legacy no-run_id", c["detail"])

    def test_observer_trace_absent_skips(self):
        self._ledger([self._row(RUN_ID)])
        c = self.run_check()
        self.assertEqual(c["result"], "skip", c)

    def test_stale_observer_trace_skips(self):
        self._ledger([self._row(RUN_ID)])
        self._observer(1, run_id="some-older-run")
        c = self.run_check()
        self.assertEqual(c["result"], "skip", c)
        self.assertIn("stale observer trace", c["detail"])

    def test_empty_run_id_skips(self):
        self._ledger([self._row(RUN_ID)])
        self._observer(1)
        c = self.run_check(run_id="")
        self.assertEqual(c["result"], "skip", c)
        self.assertIn("run_id unavailable", c["detail"])

    def test_ledger_absent_skips_with_render_note(self):
        (self.runs / "fix-log.md").write_text("# Fix Log\n\nFix (a): `f` — s — x\n")
        self._observer(1)
        c = self.run_check()
        self.assertEqual(c["result"], "skip", c)
        self.assertIn("whole-history render", c["detail"])


if __name__ == "__main__":
    sys.exit(unittest.main())
