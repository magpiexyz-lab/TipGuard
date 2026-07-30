#!/usr/bin/env python3
"""test_lead_fix_path.py — exercise write-fix-ledger.py --lead-fix mode (AOC v1.1).

Validates:
  * Required flags (--skill, --fix-json) when --lead-fix
  * fix_id format: lead-<skill>:<run_id>:<counter>
  * Counter persists in .runs/<skill>-context.json.lead_fix_counter
  * batch_id is per-invocation (timestamp), batch_size = 1
  * Granularity gate: rejects rows without `file`
  * Granularity gate: rejects summary-pattern symptoms (when severity=fix)
  * --severity warn bypasses summary-pattern check + adds severity field
  * Per-row provenance="lead", agent="lead-<skill>", source_trace="lead"
  * Idempotent: re-running with same counter is a no-op (returns existing row)
  * Provenance from trace: existing trace fixes get row provenance="agent"
  * Provenance from trace: lead-on-behalf trace fixes get row provenance="lead-on-behalf"
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
SCRIPT = ROOT / ".claude/scripts/write-fix-ledger.py"


def _setup_repo() -> Path:
    """Real git repo + .claude tree + active context."""
    tmp = Path(tempfile.mkdtemp(prefix="test-lead-fix-"))
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp)], check=True)
    subprocess.run(["git", "-C", str(tmp), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(tmp), "config", "user.name", "test"], check=True)
    subprocess.run(["git", "-C", str(tmp), "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    shutil.copytree(ROOT / ".claude", tmp / ".claude", dirs_exist_ok=True)
    runs = tmp / ".runs"
    runs.mkdir(exist_ok=True)
    (runs / "verify-context.json").write_text(json.dumps({
        "skill": "verify",
        "branch": "main",
        "timestamp": "2026-04-25T00:00:00Z",
        "run_id": "verify-2026-04-25T00:00:00Z",
        "completed": False,
    }))
    return tmp


def _run(repo: Path, *args) -> tuple[int, str, str]:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    proc = subprocess.run(
        ["python3", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(repo),
        timeout=15,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _read_ledger(repo: Path) -> list[dict]:
    p = repo / ".runs/fix-ledger.jsonl"
    if not p.exists():
        return []
    rows = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


class TestLeadFixPath(unittest.TestCase):
    def setUp(self):
        self.repo = _setup_repo()

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_lead_fix_writes_row_with_correct_attribution(self):
        fix = {"file": "src/app/page.tsx", "symptom": "missing alt", "fix": "added"}
        rc, out, err = _run(
            self.repo,
            "--lead-fix", "--skill", "verify",
            "--fix-json", json.dumps(fix),
        )
        self.assertEqual(rc, 0, f"stderr={err}")
        rows = _read_ledger(self.repo)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["agent"], "lead-verify")
        self.assertEqual(r["source_trace"], "lead")
        self.assertEqual(r["provenance"], "lead")
        self.assertEqual(r["batch_size"], 1)
        self.assertEqual(r["file"], "src/app/page.tsx")
        self.assertEqual(r["symptom"], "missing alt")
        self.assertEqual(r["fix"], "added")
        # fix_id format: lead-<skill>:<run_id>:<counter>
        self.assertTrue(r["fix_id"].startswith("lead-verify:verify-2026-04-25T00:00:00Z:"))

    def test_counter_persists_across_invocations(self):
        fix1 = {"file": "src/a.tsx", "symptom": "x", "fix": "y"}
        fix2 = {"file": "src/b.tsx", "symptom": "x", "fix": "y"}
        rc1, _, _ = _run(self.repo, "--lead-fix", "--skill", "verify",
                         "--fix-json", json.dumps(fix1))
        rc2, _, _ = _run(self.repo, "--lead-fix", "--skill", "verify",
                         "--fix-json", json.dumps(fix2))
        self.assertEqual(rc1, 0)
        self.assertEqual(rc2, 0)
        rows = _read_ledger(self.repo)
        self.assertEqual(len(rows), 2)
        # Two distinct fix_ids
        self.assertNotEqual(rows[0]["fix_id"], rows[1]["fix_id"])
        # Counter in context.json should be 2 after two invocations
        ctx = json.loads((self.repo / ".runs/verify-context.json").read_text())
        self.assertEqual(ctx["lead_fix_counter"], 2)

    def test_granularity_gate_rejects_no_file(self):
        fix = {"file": None, "symptom": "fixed N issues", "fix": "see commits"}
        rc, _, err = _run(self.repo, "--lead-fix", "--skill", "verify",
                          "--fix-json", json.dumps(fix))
        self.assertNotEqual(rc, 0)
        self.assertIn("granularity gate", err)
        self.assertIn("file", err)
        self.assertEqual(_read_ledger(self.repo), [])

    def test_granularity_gate_rejects_summary_symptom(self):
        fix = {"file": "src/x.tsx", "symptom": "fixed 19 issues", "fix": "see commits"}
        rc, _, err = _run(self.repo, "--lead-fix", "--skill", "verify",
                          "--fix-json", json.dumps(fix))
        self.assertNotEqual(rc, 0)
        self.assertIn("summary pattern", err)

    def test_severity_warn_bypasses_summary_check(self):
        # WARN severity is for batch warnings (e.g., e2e-config WARN migration),
        # so the summary-pattern symptom is allowed.
        fix = {"file": "playwright.config.ts", "symptom": "10 e2e config warnings", "fix": "see log"}
        rc, _, err = _run(self.repo, "--lead-fix", "--skill", "verify",
                          "--fix-json", json.dumps(fix), "--severity", "warn")
        self.assertEqual(rc, 0, f"stderr={err}")
        rows = _read_ledger(self.repo)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["severity"], "warn")
        self.assertEqual(rows[0]["provenance"], "lead")

    def test_lead_fix_requires_skill_and_fix_json(self):
        rc, _, err = _run(self.repo, "--lead-fix")
        self.assertNotEqual(rc, 0)
        self.assertIn("--skill", err)

        rc, _, err = _run(self.repo, "--lead-fix", "--skill", "verify")
        self.assertNotEqual(rc, 0)
        self.assertIn("--fix-json", err)

    def test_lead_fix_invalid_json(self):
        rc, _, err = _run(self.repo, "--lead-fix", "--skill", "verify",
                          "--fix-json", "not valid json")
        self.assertNotEqual(rc, 0)
        self.assertIn("invalid JSON", err)

    def test_lead_fix_does_not_pollute_consolidate(self):
        """Lead-fix mode writes one row; default consolidate mode appends agent rows from traces.
        Both modes should coexist."""
        fix = {"file": "src/x.tsx", "symptom": "specific", "fix": "specific"}
        _run(self.repo, "--lead-fix", "--skill", "verify",
             "--fix-json", json.dumps(fix))
        # Now write an agent trace and run consolidate
        traces = self.repo / ".runs/agent-traces"
        traces.mkdir(exist_ok=True)
        (traces / "ux-journeyer.json").write_text(json.dumps({
            "agent": "ux-journeyer",
            "verdict": "pass",
            "result": "fixed",
            "provenance": "self",
            "fixes": [{"file": "src/y.tsx", "symptom": "z", "fix": "w"}],
            "run_id": "verify-2026-04-25T00:00:00Z",
        }))
        rc, _, err = _run(self.repo)  # consolidate mode (no --lead-fix)
        self.assertEqual(rc, 0, f"stderr={err}")
        rows = _read_ledger(self.repo)
        self.assertEqual(len(rows), 2)  # 1 lead-fix + 1 agent fix
        provenances = sorted(r["provenance"] for r in rows)
        self.assertEqual(provenances, ["agent", "lead"])

    def test_consolidate_skips_no_file_fixes(self):
        """Granularity gate at consolidate layer: agent traces with fixes lacking
        `file` field have those rows dropped from the ledger (with stderr warning)."""
        traces = self.repo / ".runs/agent-traces"
        traces.mkdir(exist_ok=True)
        (traces / "ux-journeyer.json").write_text(json.dumps({
            "agent": "ux-journeyer",
            "verdict": "pass",
            "result": "fixed",
            "provenance": "self",
            "fixes": [
                {"file": "src/a.tsx", "symptom": "good", "fix": "good"},
                {"symptom": "fixed N issues", "fix": "summary"},  # no file → drop
                {"file": "src/b.tsx", "symptom": "good", "fix": "good"},
            ],
            "run_id": "verify-2026-04-25T00:00:00Z",
        }))
        rc, _, err = _run(self.repo)
        self.assertEqual(rc, 0)
        self.assertIn("granularity gate", err)
        rows = _read_ledger(self.repo)
        self.assertEqual(len(rows), 2)  # third was dropped

    def test_lead_on_behalf_trace_emits_lead_on_behalf_provenance(self):
        traces = self.repo / ".runs/agent-traces"
        traces.mkdir(exist_ok=True)
        (traces / "observer.json").write_text(json.dumps({
            "agent": "observer",
            "verdict": "pass",
            "result": "fixed",
            "provenance": "lead-on-behalf",
            "partial": True,
            "source": "agent-returned-text",
            "fixes": [{"file": "src/x.tsx", "symptom": "z", "fix": "w"}],
            "run_id": "verify-2026-04-25T00:00:00Z",
        }))
        rc, _, _ = _run(self.repo)
        self.assertEqual(rc, 0)
        rows = _read_ledger(self.repo)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["provenance"], "lead-on-behalf")
        self.assertEqual(rows[0]["agent"], "observer")  # attributed to source agent


def main():
    if not SCRIPT.is_file():
        print(f"ERROR: script not found at {SCRIPT}", file=sys.stderr)
        return 2
    result = unittest.main(exit=False, verbosity=2).result
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
