#!/usr/bin/env python3
"""test_check_fixlog_verdict_per_run.py — regression for #1417b.

check_fixlog_verdict_consistency previously counted ALL fix-ledger.jsonl rows
without run_id filtering. A historical ledger with 150 entries on a re-used
branch produced false-positive "Verdict inconsistency: fix ledger has 150
entries but verdict is 'clean'" when the current run had zero unobserved
fixes.

Fix: filter ledger rows by current run_id (discovered via runs_reader),
with explicit pass-through paths for NO_RUN_ID (HC5 — manual gh pr create)
and STALE_OBSERVE (observe-result.run_id != current run identity).
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
LIB = ROOT / ".claude/hooks/lib.sh"


def now_iso(offset_hours: float = 0) -> str:
    t = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=offset_hours)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def call_check_via_bash(project_dir: Path) -> tuple[int, str]:
    """Invoke check_fixlog_verdict_consistency via bash; return (errors_count, joined_message)."""
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    cmd = [
        "bash", "-c",
        f'cd "{project_dir}" && '
        f'source "{LIB}" && '
        f'ERRORS=() && '
        f'check_fixlog_verdict_consistency && '
        f'echo "ERRCOUNT=${{#ERRORS[@]}}" && '
        f'for e in "${{ERRORS[@]}}"; do echo "ERR: $e"; done',
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=15)
    out = proc.stdout.strip()
    count = 0
    for line in out.splitlines():
        if line.startswith("ERRCOUNT="):
            try:
                count = int(line.split("=", 1)[1])
            except Exception:
                pass
    return count, out


class CheckFixlogVerdictPerRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_fixlog_"))
        self.runs = self.tmp / ".runs"
        self.runs.mkdir()
        subprocess.run(["git", "-C", str(self.tmp), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(self.tmp), "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", str(self.tmp), "config", "user.name", "t"], check=True)
        subprocess.run(
            ["git", "-C", str(self.tmp), "config", "commit.gpgsign", "false"], check=True
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_ledger(self, rows: list[dict]) -> None:
        with open(self.runs / "fix-ledger.jsonl", "w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")

    def _write_observe_result(self, **fields) -> None:
        base = {"verdict": "clean", "strategy": "normal"}
        base.update(fields)
        (self.runs / "observe-result.json").write_text(json.dumps(base))

    def _write_active_context(self, skill: str, run_id: str) -> None:
        ctx = {
            "skill": skill,
            "run_id": run_id,
            "branch": "feat/test",
            "timestamp": now_iso(),
            "completed": False,
            "parent": None,
            "ancestors": [],
        }
        (self.runs / f"{skill}-context.json").write_text(json.dumps(ctx))

    def test_legacy_ledger_no_current_run_no_false_positive(self):
        """#1417b reproduction: 150 historical ledger rows + no active context
        (manual gh pr create) + verdict=clean → check passes (HC5 pass-through).
        """
        self._write_ledger([
            {"run_id": f"stale-{i}", "file": "x.py"} for i in range(150)
        ])
        self._write_observe_result(run_id="stale-1")
        # No .runs/<skill>-context.json exists → discover_current_run_id returns None
        count, output = call_check_via_bash(self.tmp)
        self.assertEqual(count, 0,
                          msg=f"expected 0 errors (HC5 pass-through), got {count}; output: {output}")

    def test_current_run_with_fixes_clean_verdict_blocks(self):
        """Current run has 2 ledger entries + verdict=clean → real inconsistency, error appended."""
        self._write_active_context("change", "change-current")
        self._write_ledger([
            {"run_id": "stale-1", "file": "x.py"},  # ignored (different run)
            {"run_id": "change-current", "file": "a.py"},
            {"run_id": "change-current", "file": "b.py"},
        ])
        self._write_observe_result(run_id="change-current")
        count, output = call_check_via_bash(self.tmp)
        self.assertEqual(count, 1,
                          msg=f"expected 1 error (real inconsistency), got {count}; output: {output}")
        self.assertIn("change-current", output)

    def test_stale_observe_runid_passes_through(self):
        """observe-result.run_id differs from current run identity → STALE_OBSERVE, pass through."""
        self._write_active_context("change", "change-new")
        self._write_ledger([
            {"run_id": "change-old", "file": "a.py"},
            {"run_id": "change-old", "file": "b.py"},
        ])
        self._write_observe_result(run_id="change-old")  # stale relative to current
        count, output = call_check_via_bash(self.tmp)
        self.assertEqual(count, 0,
                          msg=f"expected 0 errors (STALE_OBSERVE pass-through), got {count}; output: {output}")

    def test_current_run_no_fixes_no_error(self):
        """Current run has zero ledger entries + verdict=clean → no error (correct clean state)."""
        self._write_active_context("change", "change-current")
        self._write_ledger([
            {"run_id": "stale-1", "file": "x.py"},  # different run → filtered out
        ])
        self._write_observe_result(run_id="change-current")
        count, output = call_check_via_bash(self.tmp)
        self.assertEqual(count, 0,
                          msg=f"expected 0 errors (clean), got {count}; output: {output}")

    def test_execution_audit_strategy_passes_through(self):
        """strategy=execution-audit bypasses the consistency check."""
        self._write_active_context("change", "change-current")
        self._write_ledger([
            {"run_id": "change-current", "file": "a.py"},
        ])
        self._write_observe_result(run_id="change-current", strategy="execution-audit")
        count, output = call_check_via_bash(self.tmp)
        self.assertEqual(count, 0,
                          msg=f"expected 0 errors (execution-audit bypass), got {count}; output: {output}")


if __name__ == "__main__":
    unittest.main()
