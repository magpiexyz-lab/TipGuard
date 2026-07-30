#!/usr/bin/env python3
"""test_write_recovery_trace_with_fixes — EARC slice 1 (closes #1189).

Covers the new --fixes-json + --evidence-source flags on write-recovery-trace.sh
and the corresponding evidence-anchored validation path in validate-recovery.sh.

Scenario under test (#1189): a fixer-class agent (e.g., scaffold-wire) crashes
mid-flight; the lead completes the work and records the recovery via:

  bash write-recovery-trace.sh scaffold-wire --reason "rate limit" \\
    --fixes-json '[{file:..., symptom:..., fix:...}]' \\
    --evidence-source .runs/build-result.json

Expected trace shape:
  - provenance: 'recovery'  (preserved fidelity)
  - status:     'abandoned'  (preserved fidelity)
  - verdict:    'unresolved' (was 'recovery' — renamed; still in closed enum)
  - fixes[]:    each entry has lead_transcribed: true
  - lead_evidence_source: pointer to evidence file
  - recovery_validated: false (until validate-recovery.sh stamps it)

After validate-recovery.sh runs:
  - recovery_validated: true   (when evidence checks all pass)
  - errors when build-result.json is stale, missing, or shows fail
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
WRITE_RECOVERY = ROOT / ".claude/scripts/write-recovery-trace.sh"
VALIDATE_RECOVERY = ROOT / ".claude/scripts/validate-recovery.sh"


def _setup_repo(td: Path):
    """Build a tiny git repo with the needed scripts, libraries, and context."""
    subprocess.run(["git", "init", "-q", str(td)], check=True)
    subprocess.run(["git", "-C", str(td), "config", "user.email", "t@t.com"], check=True)
    subprocess.run(["git", "-C", str(td), "config", "user.name", "t"], check=True)
    (td / "foo.txt").write_text("x")
    subprocess.run(["git", "-C", str(td), "add", "foo.txt"], check=True)
    subprocess.run(["git", "-C", str(td), "commit", "-q", "-m", "initial"], check=True)
    spawn_sha = subprocess.check_output(
        ["git", "-C", str(td), "rev-parse", "HEAD"], text=True
    ).strip()
    # Create a "fix" — bar.txt — committed AFTER the spawn point.
    (td / "bar.txt").write_text("y")
    subprocess.run(["git", "-C", str(td), "add", "bar.txt"], check=True)
    subprocess.run(["git", "-C", str(td), "commit", "-q", "-m", "bar"], check=True)

    for d in (
        ".runs/agent-traces",
        ".claude/patterns",
        ".claude/scripts/lib",
        ".claude/hooks",
    ):
        (td / d).mkdir(parents=True, exist_ok=True)
    shutil.copy(WRITE_RECOVERY, td / ".claude/scripts/write-recovery-trace.sh")
    shutil.copy(VALIDATE_RECOVERY, td / ".claude/scripts/validate-recovery.sh")
    shutil.copy(
        ROOT / ".claude/scripts/lib/validate_evidence.py",
        td / ".claude/scripts/lib/validate_evidence.py",
    )
    (td / ".claude/scripts/lib/__init__.py").write_text("")

    # Minimal lib.sh stub providing resolve_active_identity (the writer sources it).
    (td / ".claude/hooks/lib.sh").write_text(
        "#!/usr/bin/env bash\n"
        "resolve_active_identity() {\n"
        "  printf '%s\\t%s\\t%s\\t%s' \"bootstrap\" \"test-run-id-1\" \"\" \"\"\n"
        "}\n"
    )
    (td / ".claude/hooks/lib-core.sh").write_text("#!/usr/bin/env bash\n")

    # Spawn-log entry the writer requires.
    spawn_entry = {
        "agent": "scaffold-wire",
        "run_id": "test-run-id-1",
        "hook": "skill-agent-gate",
        "spawn_index": 1,
        "head_sha": spawn_sha,
    }
    (td / ".runs/agent-spawn-log.jsonl").write_text(json.dumps(spawn_entry) + "\n")

    # Active context for the lead.
    json.dump(
        {"skill": "bootstrap", "run_id": "test-run-id-1"},
        (td / ".runs/bootstrap-context.json").open("w"),
    )

    # Minimal registry — non_fixer_agents / recovery_forbidden empty.
    json.dump(
        {"non_fixer_agents": [], "recovery_forbidden": []},
        (td / ".claude/patterns/agent-registry.json").open("w"),
    )

    # build-result.json: passing build (the lead's evidence anchor).
    json.dump({"exit_code": 0}, (td / ".runs/build-result.json").open("w"))
    return spawn_sha


def _run(cmd, cwd, env_extra=None):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(cwd)}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True)


class TestWriteRecoveryTraceWithFixes(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp(prefix="test_earc_s1_"))
        _setup_repo(self.td)

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def test_writes_evidence_anchored_recovery_trace(self):
        """The new flags produce a trace with the EARC fields populated."""
        fixes = [{"file": "bar.txt", "symptom": "scaffold-wire crashed", "fix": "lead completed"}]
        r = _run(
            [
                "bash",
                ".claude/scripts/write-recovery-trace.sh",
                "scaffold-wire",
                "--reason",
                "rate limit during state-14",
                "--fixes-json",
                json.dumps(fixes),
                "--evidence-source",
                ".runs/build-result.json",
            ],
            self.td,
        )
        self.assertEqual(r.returncode, 0, msg=f"stderr={r.stderr}")
        trace = json.load(open(self.td / ".runs/agent-traces/scaffold-wire.json"))

        self.assertEqual(trace.get("provenance"), "recovery")
        self.assertEqual(trace.get("status"), "abandoned")
        # Verdict renamed (round-2 critic Concern 1): 'recovery' was outside
        # the closed enum; now uses 'unresolved'.
        self.assertEqual(trace.get("verdict"), "unresolved")
        self.assertEqual(trace.get("recovery_validated"), False)
        self.assertEqual(trace.get("lead_evidence_source"), ".runs/build-result.json")
        self.assertEqual(len(trace.get("fixes", [])), 1)
        self.assertTrue(trace["fixes"][0].get("lead_transcribed") is True)

    def test_validate_recovery_stamps_recovery_validated_on_evidence(self):
        """validate-recovery.sh accepts the evidence-anchored path and stamps
        recovery_validated:true when the evidence checks pass."""
        fixes = [{"file": "bar.txt", "symptom": "x", "fix": "y"}]
        _run(
            [
                "bash",
                ".claude/scripts/write-recovery-trace.sh",
                "scaffold-wire",
                "--reason",
                "test",
                "--fixes-json",
                json.dumps(fixes),
                "--evidence-source",
                ".runs/build-result.json",
            ],
            self.td,
        )
        r = _run(
            ["bash", ".claude/scripts/validate-recovery.sh", "scaffold-wire"], self.td
        )
        self.assertEqual(r.returncode, 0, msg=f"stderr={r.stderr}")
        trace = json.load(open(self.td / ".runs/agent-traces/scaffold-wire.json"))
        self.assertTrue(trace.get("recovery_validated") is True, trace)

    def test_fixes_json_alone_rejected_without_evidence_source(self):
        """The two flags are paired — supplying --fixes-json without
        --evidence-source must fail at the writer level."""
        r = _run(
            [
                "bash",
                ".claude/scripts/write-recovery-trace.sh",
                "scaffold-wire",
                "--reason",
                "test",
                "--fixes-json",
                "[]",
            ],
            self.td,
        )
        self.assertEqual(r.returncode, 1)
        self.assertIn("evidence-source", r.stderr)

    def test_evidence_source_alone_rejected_without_fixes_json(self):
        r = _run(
            [
                "bash",
                ".claude/scripts/write-recovery-trace.sh",
                "scaffold-wire",
                "--reason",
                "test",
                "--evidence-source",
                ".runs/build-result.json",
            ],
            self.td,
        )
        self.assertEqual(r.returncode, 1)
        self.assertIn("fixes-json", r.stderr)

    def test_invalid_json_rejected(self):
        r = _run(
            [
                "bash",
                ".claude/scripts/write-recovery-trace.sh",
                "scaffold-wire",
                "--reason",
                "test",
                "--fixes-json",
                "not json",
                "--evidence-source",
                ".runs/build-result.json",
            ],
            self.td,
        )
        self.assertEqual(r.returncode, 1)
        self.assertIn("not valid JSON", r.stderr)

    def test_missing_evidence_file_fails_validation(self):
        """When the lead points at a non-existent evidence path, validate-
        recovery rejects."""
        fixes = [{"file": "bar.txt", "symptom": "x", "fix": "y"}]
        _run(
            [
                "bash",
                ".claude/scripts/write-recovery-trace.sh",
                "scaffold-wire",
                "--reason",
                "test",
                "--fixes-json",
                json.dumps(fixes),
                "--evidence-source",
                ".runs/does-not-exist.json",
            ],
            self.td,
        )
        r = _run(
            ["bash", ".claude/scripts/validate-recovery.sh", "scaffold-wire"], self.td
        )
        self.assertEqual(r.returncode, 1)
        self.assertIn("missing", r.stderr.lower())

    def test_legacy_no_fixes_path_still_works(self):
        """Existing callers — write-recovery-trace.sh WITHOUT --fixes-json —
        must continue to write the same shape they did before slice 1."""
        # Set up a non-fixer agent context so no_fixes_claimed:true would pass.
        json.dump(
            {"non_fixer_agents": ["observer"], "recovery_forbidden": []},
            (self.td / ".claude/patterns/agent-registry.json").open("w"),
        )
        spawn_entry = {
            "agent": "observer",
            "run_id": "test-run-id-1",
            "hook": "skill-agent-gate",
            "spawn_index": 1,
            "head_sha": subprocess.check_output(
                ["git", "-C", str(self.td), "rev-parse", "HEAD~"], text=True
            ).strip(),
        }
        (self.td / ".runs/agent-spawn-log.jsonl").write_text(json.dumps(spawn_entry) + "\n")
        r = _run(
            [
                "bash",
                ".claude/scripts/write-recovery-trace.sh",
                "observer",
                "--reason",
                "legacy path",
            ],
            self.td,
        )
        self.assertEqual(r.returncode, 0, msg=f"stderr={r.stderr}")
        trace = json.load(open(self.td / ".runs/agent-traces/observer.json"))
        # Legacy shape: no fixes, no lead_evidence_source.
        self.assertNotIn("fixes", trace)
        self.assertNotIn("lead_evidence_source", trace)
        # Verdict still gets the post-slice-1 'unresolved' rename
        # (intentional — we ARE renaming this universally).
        self.assertEqual(trace.get("verdict"), "unresolved")

    def test_write_fix_ledger_preserves_lead_transcribed(self):
        """write-fix-ledger.py consolidates traces into fix-ledger.jsonl;
        rows from a lead-transcribed fixes[] entry must carry the flag."""
        fixes = [{"file": "bar.txt", "symptom": "x", "fix": "y"}]
        _run(
            [
                "bash",
                ".claude/scripts/write-recovery-trace.sh",
                "scaffold-wire",
                "--reason",
                "test",
                "--fixes-json",
                json.dumps(fixes),
                "--evidence-source",
                ".runs/build-result.json",
            ],
            self.td,
        )
        # Copy the ledger script and run it.
        shutil.copy(
            ROOT / ".claude/scripts/write-fix-ledger.py",
            self.td / ".claude/scripts/write-fix-ledger.py",
        )
        r = _run(
            [
                "python3",
                ".claude/scripts/write-fix-ledger.py",
                "--run-id",
                "test-run-id-1",
            ],
            self.td,
        )
        # Script may exit 0 even if no rows; but we expect at least one row.
        ledger_path = self.td / ".runs/fix-ledger.jsonl"
        self.assertTrue(ledger_path.exists(), msg=f"stderr={r.stderr}")
        rows = [json.loads(ln) for ln in ledger_path.read_text().splitlines() if ln.strip()]
        # Find the row for scaffold-wire
        sw_rows = [r for r in rows if r.get("agent") == "scaffold-wire"]
        self.assertTrue(sw_rows, f"no scaffold-wire row in ledger: {rows}")
        self.assertTrue(sw_rows[0].get("lead_transcribed") is True)


if __name__ == "__main__":
    unittest.main()
