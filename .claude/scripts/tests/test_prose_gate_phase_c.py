#!/usr/bin/env python3
"""test_prose_gate_phase_c.py — PR 1 (Phase C-fast) coverage.

Closes #1449/#1431/#1433. Tests:
  - append_deviation_log atomic appender + write-failures channel
  - lifecycle-init Step 5c snapshot mechanism
  - render-fix-log.py invocation in lifecycle-finalize Step 2.5
  - cross-run-channels.json registration

Note: per-gate deny + env rollback tests are covered by test_prose_gate_e2e.py
(updated to use PROSE_GATE_<G>_MODE env vars). The helper resolution chain
is covered by test_prose_gate_mode.py.

Run: python3 .claude/scripts/tests/test_prose_gate_phase_c.py
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


class TestAppendDeviationLog(unittest.TestCase):
    """append_deviation_log atomicity + write-failures channel."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_phase_c_append_"))
        self._orig_cwd = os.getcwd()
        os.chdir(str(self.tmp))
        sys.path.insert(0, str(ROOT / ".claude/scripts/lib"))
        if "append_deviation_log" in sys.modules:
            del sys.modules["append_deviation_log"]
        from append_deviation_log import append
        self.append = append

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_success_writes_jsonl_with_schema_version(self):
        """Successful append writes one line with _meta.schema_version stamp."""
        self.assertTrue(self.append({"gate_id": "test-gate", "evidence": {"k": "v"}}))
        log_path = self.tmp / ".runs/lead-deviation-log.jsonl"
        self.assertTrue(log_path.exists())
        lines = [l for l in log_path.read_text().splitlines() if l.strip()]
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry["gate_id"], "test-gate")
        self.assertEqual(entry["_meta"]["schema_version"], "prose-gates-v1.0")

    def test_invalid_payload_routes_to_failures_log(self):
        """Non-dict payload writes to write-failures.jsonl."""
        self.assertFalse(self.append("not-a-dict"))
        wf_path = self.tmp / ".runs/lead-deviation-log.write-failures.jsonl"
        self.assertTrue(wf_path.exists())
        lines = [l for l in wf_path.read_text().splitlines() if l.strip()]
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertIn("exception", entry)
        self.assertIn("TypeError", entry["exception"])
        # Primary log should NOT have an entry.
        primary = self.tmp / ".runs/lead-deviation-log.jsonl"
        if primary.exists():
            self.assertEqual(primary.read_text().strip(), "")

    def test_io_failure_routes_to_failures_log(self):
        """Filesystem error during primary write goes to failures log."""
        # Create .runs as a regular file (not dir) so makedirs/open fails.
        (self.tmp / ".runs").mkdir()
        log_path = self.tmp / ".runs/lead-deviation-log.jsonl"
        log_path.mkdir()  # primary log path is now a directory → open(...,"a") fails
        self.assertFalse(self.append({"gate_id": "test"}))
        wf_path = self.tmp / ".runs/lead-deviation-log.write-failures.jsonl"
        self.assertTrue(wf_path.exists())
        entries = [json.loads(l) for l in wf_path.read_text().splitlines() if l.strip()]
        self.assertEqual(len(entries), 1)
        self.assertIn("exception", entries[0])

    def test_does_not_mutate_caller_payload(self):
        """append() must not add _meta to the caller's dict (uses shallow copy)."""
        payload = {"gate_id": "test"}
        self.append(payload)
        self.assertNotIn("_meta", payload, "caller's dict should not be mutated")


class TestLifecycleInitSnapshot(unittest.TestCase):
    """lifecycle-init Step 5c writes prose_gates_modes_snapshot."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_phase_c_init_"))
        # Symlink .claude into the tmp dir so init-context.sh + Step 5c can run.
        (self.tmp / ".claude").symlink_to(ROOT / ".claude")
        # Init a git repo so lifecycle-init.sh's git introspection works.
        subprocess.run(["git", "init", "-q"], cwd=str(self.tmp), check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"],
                       cwd=str(self.tmp), check=True)
        subprocess.run(["git", "config", "user.name", "test"],
                       cwd=str(self.tmp), check=True)
        # Need a HEAD for git rev-parse to work; create empty initial commit.
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init", "-q"],
                       cwd=str(self.tmp), check=True)
        self._orig_cwd = os.getcwd()
        os.chdir(str(self.tmp))

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_lifecycle_init_writes_snapshot_with_v2_version(self):
        """Running lifecycle-init for a fresh skill writes the snapshot field."""
        # Run lifecycle-init for a synthetic skill. lifecycle-init.sh requires
        # skill.yaml; "solve" exists in the template.
        result = subprocess.run(
            ["bash", str(ROOT / ".claude/scripts/lifecycle-init.sh"), "solve"],
            capture_output=True, text=True, env={**os.environ},
            cwd=str(self.tmp),
        )
        # Whether the script exits 0 depends on env; what matters is the
        # context file was written with the snapshot.
        ctx_path = self.tmp / ".runs/solve-context.json"
        self.assertTrue(ctx_path.exists(),
                        f"context not written; stderr: {result.stderr[:500]}")
        ctx = json.loads(ctx_path.read_text())
        self.assertIn("prose_gates_modes_snapshot", ctx,
                      "snapshot field missing — lifecycle-init Step 5c didn't run")
        self.assertEqual(ctx["prose_gates_modes_snapshot_at_version"], 2,
                         "snapshot version should match registry _schema_version=2")
        # Snapshot should include all 5 gates with fail_mode (gate 3 omits).
        snap = ctx["prose_gates_modes_snapshot"]
        self.assertIn("lead-synthesized-numerical-bounds", snap)
        self.assertIn("retro-suppressions-confirmation", snap)
        # Gate 3 (binary, no fail_mode) must NOT be in snapshot.
        self.assertNotIn("verify-state-2-phase1-spawn-no-background", snap,
                         "binary gate (no fail_mode) should NOT be in snapshot")


class TestLifecycleFinalizeRendersFixLog(unittest.TestCase):
    """lifecycle-finalize Step 2.5 invokes render-fix-log.py."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_phase_c_finalize_"))
        (self.tmp / ".claude").symlink_to(ROOT / ".claude")
        # Need .runs/ + agent-traces/ for the conditional to fire.
        (self.tmp / ".runs/agent-traces").mkdir(parents=True)
        # Write a minimal context so lifecycle-finalize identifies the active skill.
        ctx = {
            "skill": "solve",
            "run_id": "solve-test-finalize",
            "timestamp": "2026-05-15T00:00:00Z",
            "completed_states": ["0", "1", "2"],
            "completed": False,
        }
        (self.tmp / ".runs/solve-context.json").write_text(json.dumps(ctx))
        self._orig_cwd = os.getcwd()
        os.chdir(str(self.tmp))

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_step_2_5_runs_render_fix_log(self):
        """Step 2.5 invokes render-fix-log.py; .runs/fix-log.md is produced."""
        # Empty agent-traces; both writers are idempotent and produce empty
        # ledger + empty fix-log header.
        result = subprocess.run(
            ["bash", str(ROOT / ".claude/scripts/lifecycle-finalize.sh"), "solve"],
            capture_output=True, text=True, env={**os.environ, "CLAUDE_PROJECT_DIR": str(self.tmp)},
            cwd=str(self.tmp),
        )
        # Don't strictly require exit 0 — finalize does many things;
        # we only care that fix-log.md was produced by Step 2.5.
        fix_log = self.tmp / ".runs/fix-log.md"
        self.assertTrue(
            fix_log.exists(),
            f"fix-log.md not produced by Step 2.5; stderr: {result.stderr[:500]}"
        )


class TestCrossRunChannelsRegistration(unittest.TestCase):
    """cross-run-channels.json registers the new lead-deviation-log channels."""

    def test_lead_deviation_log_registered(self):
        reg = json.loads((ROOT / ".claude/patterns/cross-run-channels.json").read_text())
        self.assertIn("lead-deviation-log", reg["channels"])
        entry = reg["channels"]["lead-deviation-log"]
        self.assertEqual(entry["paths"], [".runs/lead-deviation-log.jsonl"])
        self.assertEqual(entry["owner"], "append_deviation_log.py")

    def test_lead_deviation_log_write_failures_registered(self):
        reg = json.loads((ROOT / ".claude/patterns/cross-run-channels.json").read_text())
        self.assertIn("lead-deviation-log-write-failures", reg["channels"])
        entry = reg["channels"]["lead-deviation-log-write-failures"]
        self.assertEqual(entry["paths"], [".runs/lead-deviation-log.write-failures.jsonl"])


class TestProseGatesRegistrySchemaV2(unittest.TestCase):
    """prose-gates.json schema bump v1→v2 + gate field changes."""

    def setUp(self):
        self.reg = json.loads(
            (ROOT / ".claude/patterns/prose-gates.json").read_text()
        )

    def test_schema_version_is_2(self):
        self.assertEqual(self.reg["_schema_version"], 2)

    def test_v2_notes_present(self):
        self.assertIn("2", self.reg["_schema_version_notes"])

    def test_4_gates_at_deny(self):
        """Gates 1, 2, 4, 6 flipped to deny."""
        gates_by_id = {g["gate_id"]: g for g in self.reg["gates"]}
        for gate_id in [
            "lead-synthesized-numerical-bounds",
            "bootstrap-state-6-user-approval",
            "observation-phase-step5c-anomaly-audit",
            "verify-state-3a-stage0-design-critic",
        ]:
            self.assertEqual(
                gates_by_id[gate_id]["fail_mode"], "deny",
                f"{gate_id} should be deny in v2"
            )

    def test_gate_5_aligned_to_deny(self):
        """Gate 5 registry corrected to match #1393 phase-2 runtime default."""
        gates_by_id = {g["gate_id"]: g for g in self.reg["gates"]}
        self.assertEqual(
            gates_by_id["retro-suppressions-confirmation"]["fail_mode"], "deny"
        )

    def test_gate_3_omits_fail_mode_with_reason(self):
        """Gate 3 (binary skill-yaml-mode) has no fail_mode, but has _no_fail_mode_reason."""
        gates_by_id = {g["gate_id"]: g for g in self.reg["gates"]}
        gate_3 = gates_by_id["verify-state-2-phase1-spawn-no-background"]
        self.assertNotIn("fail_mode", gate_3, "binary gate must omit fail_mode")
        self.assertIn("_no_fail_mode_reason", gate_3,
                      "binary gate must explain why fail_mode is omitted")
        self.assertGreaterEqual(
            len(gate_3["_no_fail_mode_reason"]), 60,
            "_no_fail_mode_reason must be ≥60 chars (per schema)"
        )


class TestEnumeratePendingFindings7thSource(unittest.TestCase):
    """enumerate-pending-retrospective-findings.py adds 7th source."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_phase_c_enum_"))
        (self.tmp / ".claude").symlink_to(ROOT / ".claude")
        (self.tmp / ".runs").mkdir()
        # Write a sample write-failures entry.
        wf_path = self.tmp / ".runs/lead-deviation-log.write-failures.jsonl"
        wf_path.write_text(json.dumps({
            "original_payload": {"gate_id": "test-gate"},
            "exception": "OSError: [Errno 28] No space left on device",
            "ts": "2026-05-15T00:00:00Z",
        }) + "\n")
        # Active context for the enumerator's run_id resolution.
        ctx = {
            "skill": "solve", "run_id": "solve-test-enum",
            "timestamp": "2026-05-15T00:00:00Z",
            "completed_states": [], "completed": False,
        }
        (self.tmp / ".runs/solve-context.json").write_text(json.dumps(ctx))
        self._orig_cwd = os.getcwd()
        os.chdir(str(self.tmp))

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_7th_source_surfaces_log_write_failures(self):
        """Running the enumerator surfaces write-failures as HIGH-confidence finding."""
        result = subprocess.run(
            ["python3", str(ROOT / ".claude/scripts/enumerate-pending-retrospective-findings.py")],
            capture_output=True, text=True, cwd=str(self.tmp),
        )
        self.assertEqual(result.returncode, 0,
                         f"enumerator failed: {result.stderr}")
        out_path = self.tmp / ".runs/retrospective-pending-findings.json"
        self.assertTrue(out_path.exists())
        out = json.loads(out_path.read_text())
        kinds = {c.get("kind") for c in out.get("candidates", [])}
        self.assertIn("log-write-failure", kinds,
                      f"7th source missing; got kinds: {kinds}")
        # The log-write-failure candidate should be HIGH confidence.
        lwf = [c for c in out["candidates"] if c.get("kind") == "log-write-failure"]
        self.assertEqual(lwf[0]["confidence"], "high")


if __name__ == "__main__":
    unittest.main()
