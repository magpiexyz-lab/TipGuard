#!/usr/bin/env python3
"""test_check_observation_artifacts_fast_path.py — regression for #2009.

The FAST_PATH derivation in check-observation-artifacts.sh previously tested
"fix-log.md has entries". The fix-ledger is append-only across runs by design
and fix-log.md is a whole-history render regenerated at every finalize, so
after the first run that ever recorded a fix the fast path could never fire
again — every zero-fix run walked the full audit-only evaluation.

Fix: the fix condition counts fix-ledger.jsonl rows scoped to the ACTIVE
run_id (runs_reader scope='current-run'); unresolvable run_id degrades to
requiring an entirely empty ledger (the pre-#2009 behavior).

Run: python3 .claude/scripts/tests/test_check_observation_artifacts_fast_path.py
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
SCRIPT = ROOT / ".claude/scripts/check-observation-artifacts.sh"


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class FastPathFixture(unittest.TestCase):
    SKILL = "iterate-cross"
    RUN_ID = "iterate-cross-current-run"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_coa_fp_"))
        self.runs = self.tmp / ".runs"
        self.runs.mkdir()
        subprocess.run(["git", "-C", str(self.tmp), "init", "-q"], check=True)
        # Real helpers the script resolves under $PROJECT_DIR.
        lib = self.tmp / ".claude" / "scripts" / "lib"
        lib.mkdir(parents=True)
        shutil.copy(ROOT / ".claude/scripts/lib/write-gate-artifact.sh",
                    lib / "write-gate-artifact.sh")
        shutil.copy(ROOT / ".claude/scripts/lib/runs_reader.py",
                    lib / "runs_reader.py")
        patterns = self.tmp / ".claude" / "patterns"
        patterns.mkdir(parents=True)
        shutil.copy(ROOT / ".claude/patterns/cross-run-channels.json",
                    patterns / "cross-run-channels.json")
        # audit-only scope: skill.yaml with no critic agents / embed:verify.
        skill_dir = self.tmp / ".claude" / "skills" / "iterate"
        skill_dir.mkdir(parents=True)
        (skill_dir / "skill.yaml").write_text("modes:\n  cross:\n    states: ['x0']\n")
        # Clean-run baseline artifacts.
        (self.runs / "observer-diffs.txt").write_text("")
        (self.runs / "observe-result.json").write_text(json.dumps({
            "skill": self.SKILL, "timestamp": now_iso(),
            "friction_detected": False, "observations_filed": 0,
            "verdict": "clean", "strategy": "execution-audit",
        }))
        self._write_context(self.SKILL, self.RUN_ID)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_context(self, skill: str, run_id: str) -> None:
        (self.runs / f"{skill}-context.json").write_text(json.dumps({
            "skill": skill, "run_id": run_id, "branch": "main",
            "timestamp": now_iso(), "completed": False,
        }))

    def _write_ledger(self, rows: list[dict]) -> None:
        with open(self.runs / "fix-ledger.jsonl", "w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")

    def run_check(self, skill=None) -> dict:
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(self.tmp)
        args = [str(SCRIPT)]
        if skill is not None:
            args.append(skill)
        proc = subprocess.run(
            ["bash", *args], cwd=self.tmp, capture_output=True, text=True,
            env=env, timeout=60,
        )
        artifact = self.runs / "observation-enforcement.json"
        self.assertTrue(
            artifact.is_file(),
            f"no enforcement artifact\nstdout={proc.stdout}\nstderr={proc.stderr}",
        )
        return json.loads(artifact.read_text())

    @staticmethod
    def _ledger_row(run_id: str, idx: int = 0) -> dict:
        return {
            "fix_id": f"lead-x:{run_id}:{idx}", "agent": "lead-x",
            "source_trace": "lead", "run_id": run_id,
            "file": ".claude/scripts/foo.py", "symptom": "s", "fix": "f",
            "timestamp": now_iso(), "batch_id": now_iso(), "batch_size": 1,
            "provenance": "lead",
        }


class TestFastPathRunScoping(FastPathFixture):
    def test_prior_run_ledger_rows_do_not_defeat_fast_path(self):
        # The #2009 shape: historical rows + regenerated whole-history
        # fix-log.md, but ZERO rows for the active run.
        self._write_ledger([
            self._ledger_row("iterate-cross-stale-1", 0),
            self._ledger_row("iterate-cross-stale-2", 1),
        ])
        (self.runs / "fix-log.md").write_text(
            "# Fix Log\n\nFix (lead-x): `foo.py` — Symptom: s — Fix: f\n"
        )
        result = self.run_check(self.SKILL)
        self.assertTrue(result.get("fast_path"), result)
        self.assertTrue(result.get("pass"), result)
        self.assertEqual(result.get("missing"), [], result)

    def test_current_run_ledger_row_disables_fast_path(self):
        self._write_ledger([
            self._ledger_row("iterate-cross-stale-1", 0),
            self._ledger_row(self.RUN_ID, 1),
        ])
        result = self.run_check(self.SKILL)
        self.assertFalse(result.get("fast_path"), result)
        self.assertIn("compliance-audit-result.json", result.get("missing", []), result)

    def test_unresolvable_identity_is_fail_closed(self):
        # No context file → run identity unresolvable. End-to-end the script
        # cannot produce a passing enforcement artifact at all (the canonical
        # writer requires a resolvable run_id and the trap artifact records
        # fast_path=false, pass=false) — the fast path must never fail open.
        # The FAST_PATH derivation's own degraded branch (empty rid → require
        # an entirely empty ledger) is defense-in-depth beneath this envelope.
        (self.runs / f"{self.SKILL}-context.json").unlink()
        self._write_ledger([self._ledger_row("iterate-cross-stale-1", 0)])
        result = self.run_check(self.SKILL)
        self.assertFalse(result.get("fast_path"), result)
        self.assertFalse(result.get("pass"), result)

    def test_empty_run_id_rows_are_historical(self):
        # Legacy rows without run_id must not count as current-run (HC2).
        row = self._ledger_row("", 0)
        row.pop("run_id")
        self._write_ledger([row])
        result = self.run_check(self.SKILL)
        self.assertTrue(result.get("fast_path"), result)


if __name__ == "__main__":
    sys.exit(unittest.main())
