#!/usr/bin/env python3
"""test_migrate_legacy_traces.py — verify legacy trace migration logic.

Covers:
  1. Legacy trace with recovery:true → provenance=recovery, partial:true
  2. Legacy trace without recovery → provenance=self, partial:false
  3. Legacy trace with status absent → status derived from verdict presence
  4. Already-migrated trace (has provenance) → untouched
  5. Idempotency: second run is no-op (receipt present)
  6. --force re-runs despite receipt
  7. --dry-run reports but does not mutate
  8. Missing traces dir → writes empty receipt and exits 0
  9. Malformed JSON → warn + skip, continue

Run: python3 .claude/scripts/tests/test_migrate_legacy_traces.py
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
SCRIPT = ROOT / ".claude/scripts/migrate-legacy-traces.py"


class TestMigrateLegacyTraces(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_mlt_"))
        self.runs = self.tmp / ".runs"
        self.traces = self.runs / "agent-traces"
        self.traces.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_trace(self, name: str, data: dict):
        (self.traces / f"{name}.json").write_text(json.dumps(data, indent=2))

    def _run(self, *args):
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(self.tmp)
        return subprocess.run(
            ["python3", str(SCRIPT)] + list(args),
            capture_output=True, text=True, env=env, cwd=str(self.tmp), timeout=10,
        )

    # ---- Basic derivation ----

    def test_legacy_with_recovery_true_derives_recovery_provenance(self):
        self._write_trace("design-critic", {
            "agent": "design-critic",
            "timestamp": "2026-04-20T00:00:00Z",
            "verdict": "recovery",
            "recovery": True,
            "checks_performed": ["exhaustion-recovery"],
            "run_id": "verify-2026-04-20T00:00:00Z",
        })
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        t = json.loads((self.traces / "design-critic.json").read_text())
        self.assertEqual(t["provenance"], "recovery")
        self.assertTrue(t["partial"])
        self.assertEqual(t["status"], "completed")
        self.assertTrue(t["recovery"])
        self.assertFalse(t["recovery_validated"])
        self.assertIn("degraded_reason", t)

    def test_legacy_without_recovery_derives_self(self):
        self._write_trace("observer", {
            "agent": "observer",
            "verdict": "filed",
            "timestamp": "2026-04-20T00:00:00Z",
        })
        proc = self._run()
        self.assertEqual(proc.returncode, 0)
        t = json.loads((self.traces / "observer.json").read_text())
        self.assertEqual(t["provenance"], "self")
        self.assertFalse(t["partial"])
        self.assertEqual(t["status"], "completed")
        self.assertFalse(t["recovery"])
        # self doesn't require degraded_reason
        self.assertNotIn("degraded_reason", t)

    def test_legacy_with_recovery_false_derives_self(self):
        self._write_trace("design-critic", {
            "agent": "design-critic",
            "verdict": "pass",
            "recovery": False,
        })
        proc = self._run()
        self.assertEqual(proc.returncode, 0)
        t = json.loads((self.traces / "design-critic.json").read_text())
        self.assertEqual(t["provenance"], "self")
        self.assertFalse(t["recovery"])

    def test_legacy_status_derived_from_verdict_presence(self):
        # No status and no verdict → status=started (stub)
        self._write_trace("design-critic-stub", {
            "agent": "design-critic",
        })
        proc = self._run()
        self.assertEqual(proc.returncode, 0)
        t = json.loads((self.traces / "design-critic-stub.json").read_text())
        self.assertEqual(t["status"], "started")

    def test_no_fixes_claimed_derived_from_empty_fixes(self):
        self._write_trace("observer", {
            "agent": "observer",
            "verdict": "filed",
            "fixes": [],
        })
        proc = self._run()
        self.assertEqual(proc.returncode, 0)
        t = json.loads((self.traces / "observer.json").read_text())
        self.assertTrue(t["no_fixes_claimed"])

        self._write_trace("quality-fixer", {
            "agent": "quality-fixer",
            "verdict": "partial",
            "fixes": [{"file": "a.ts"}],
            "recovery": False,
        })
        proc = self._run("--force")
        self.assertEqual(proc.returncode, 0)
        t = json.loads((self.traces / "quality-fixer.json").read_text())
        self.assertFalse(t["no_fixes_claimed"])

    # ---- Idempotency and receipt ----

    def test_receipt_written(self):
        self._write_trace("observer", {"agent": "observer", "verdict": "filed"})
        proc = self._run()
        self.assertEqual(proc.returncode, 0)
        r = json.loads((self.runs / "trace-migration.json").read_text())
        self.assertIn("migrated_at", r)
        self.assertGreaterEqual(r["processed"], 1)

    def test_second_run_is_noop(self):
        self._write_trace("observer", {"agent": "observer", "verdict": "filed"})
        self._run()
        # Now corrupt the receipt-hash-less check: mutate the migrated trace manually
        (self.traces / "observer.json").write_text(json.dumps({
            "agent": "observer", "verdict": "filed"  # legacy again, no provenance
        }))
        proc = self._run()  # should be a no-op because receipt exists
        self.assertEqual(proc.returncode, 0)
        t = json.loads((self.traces / "observer.json").read_text())
        self.assertNotIn("provenance", t, "second run should not re-migrate without --force")

    def test_force_reruns_despite_receipt(self):
        self._write_trace("observer", {"agent": "observer", "verdict": "filed"})
        self._run()
        # Reset the trace to legacy form
        (self.traces / "observer.json").write_text(json.dumps({
            "agent": "observer", "verdict": "filed"
        }))
        proc = self._run("--force")
        self.assertEqual(proc.returncode, 0)
        t = json.loads((self.traces / "observer.json").read_text())
        self.assertEqual(t["provenance"], "self")

    def test_dry_run_reports_but_does_not_mutate(self):
        self._write_trace("design-critic", {
            "agent": "design-critic",
            "verdict": "recovery",
            "recovery": True,
        })
        proc = self._run("--dry-run")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("dry-run", proc.stdout)
        t = json.loads((self.traces / "design-critic.json").read_text())
        self.assertNotIn("provenance", t, "dry-run must not mutate")

    # ---- Edge cases ----

    def test_missing_traces_dir_still_writes_receipt(self):
        shutil.rmtree(self.traces)
        proc = self._run()
        self.assertEqual(proc.returncode, 0)
        r = json.loads((self.runs / "trace-migration.json").read_text())
        self.assertFalse(r["traces_dir_existed"])
        self.assertEqual(r["processed"], 0)

    def test_malformed_json_does_not_crash(self):
        (self.traces / "broken.json").write_text("{not json")
        self._write_trace("observer", {"agent": "observer", "verdict": "filed"})
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # Observer should still be migrated
        t = json.loads((self.traces / "observer.json").read_text())
        self.assertEqual(t["provenance"], "self")

    def test_already_migrated_untouched(self):
        original = {
            "agent": "design-critic",
            "timestamp": "2026-04-20T00:00:00Z",
            "status": "completed",
            "verdict": "degraded",
            "provenance": "self-degraded",
            "partial": True,
            "degraded_reason": "already-migrated",
            "recovery_validated": True,  # externally stamped by a prior run
            "recovery": False,
            "checks_performed": ["x"],
        }
        self._write_trace("design-critic", original)
        proc = self._run()
        self.assertEqual(proc.returncode, 0)
        t = json.loads((self.traces / "design-critic.json").read_text())
        self.assertEqual(t, original, "already-migrated trace must not be touched")


if __name__ == "__main__":
    unittest.main(verbosity=2)
