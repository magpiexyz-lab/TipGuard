#!/usr/bin/env python3
"""test_check_observation_artifacts_gate_evidence.py — behavioral tests for the
GECR gate-evidence soak step wired into check-observation-artifacts.sh by the
#1855 remediation (tracker #2013).

Contract under test: on full/process scopes with verify-gate-evidence.py
present, the step invokes the two GATE_EVIDENCE rules in warn mode, records
per-rule statuses in observation-enforcement.json.gate_evidence, and NEVER
blocks (pass/missing unchanged by any gate-evidence outcome). When the script
is absent (degraded fixtures, e.g. the fast-path tests), the step skips and
the artifact carries an empty gate_evidence.

Run: python3 -m pytest .claude/scripts/tests/test_check_observation_artifacts_gate_evidence.py -v
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

try:
    import jsonschema  # noqa: F401
    HAVE_JSONSCHEMA = True
except ImportError:
    HAVE_JSONSCHEMA = False


def _live_ts() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class GateEvidenceFixture(unittest.TestCase):
    SKILL = "solve"
    # Post-migration-cutoff timestamp embedded so schema_version_gate resolves
    # v2 and the GECR rules actually evaluate instead of schema-cutoff-skipping.
    RUN_ID = "solve-2026-07-29T10:00:00Z"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_coa_ge_"))
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.tmp, check=True)
        self.runs = self.tmp / ".runs"
        (self.runs / "agent-traces").mkdir(parents=True)
        # Helpers the enforcement script itself needs.
        lib = self.tmp / ".claude" / "scripts" / "lib"
        lib.mkdir(parents=True)
        for helper in ("write-gate-artifact.sh", "runs_reader.py",
                       "anomaly-audit-evidence.py", "schema_version_gate.py",
                       "prose_gate_mode.py", "prose_gate_mode.sh"):
            src = ROOT / ".claude/scripts/lib" / helper
            if src.is_file():
                shutil.copy(src, lib / helper)
        for validator in ("validate-retrospective-completeness.py",
                          "validate-observer-evidence-coverage.py"):
            src = ROOT / ".claude/scripts" / validator
            if src.is_file():
                shutil.copy(src, self.tmp / ".claude/scripts" / validator)
        patterns = self.tmp / ".claude" / "patterns"
        patterns.mkdir(parents=True)
        shutil.copy(ROOT / ".claude/patterns/cross-run-channels.json",
                    patterns / "cross-run-channels.json")
        shutil.copy(ROOT / ".claude/patterns/prose-gates.json",
                    patterns / "prose-gates.json")
        # process scope: skill.yaml with a critic agent, no diffs.
        skill_dir = self.tmp / ".claude" / "skills" / "solve"
        skill_dir.mkdir(parents=True)
        (skill_dir / "skill.yaml").write_text(
            "agents:\n  solve-critic:\n    role: critic\n"
        )
        (self.runs / "observer-diffs.txt").write_text("")
        (self.runs / f"{self.SKILL}-context.json").write_text(json.dumps({
            "skill": self.SKILL, "run_id": self.RUN_ID, "branch": "main",
            "timestamp": _live_ts(), "completed": False,
        }))
        # Non-fast-path artifacts a process-scope run is expected to carry.
        (self.runs / "observe-result.json").write_text(json.dumps({
            "skill": self.SKILL, "timestamp": _live_ts(),
            "friction_detected": False, "observations_filed": 0,
            "verdict": "no-template-issues", "strategy": "execution-audit",
        }))
        (self.runs / "compliance-audit-result.json").write_text(json.dumps({
            "skill": self.SKILL, "anomaly_count": 0, "checks": [],
        }))
        (self.runs / "retrospective-result.json").write_text(json.dumps({
            "step_5a_executor": "lead", "schema_version": 2,
            "process_compliance": "clean",
            "agent_instruction_compliance": [
                {"agent": "solve-critic", "executor": "agent",
                 "compliant": True, "finding": None, "root_cause": "n-a"}],
            "trace_fidelity": "clean", "observations_filed": 0,
            "suppressions": [], "skipped": False,
        }))
        (self.runs / "hook-friction-summary.json").write_text(json.dumps({
            "run_id": self.RUN_ID, "total": 0, "per_hook": {},
            "aggregated_at": _live_ts(),
        }))
        (self.runs / "retrospective-pending-findings.json").write_text(json.dumps({
            "run_id": self.RUN_ID, "generated_at": _live_ts(), "candidates": [],
        }))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _install_gate_evidence(self):
        scripts = self.tmp / ".claude" / "scripts"
        shutil.copy(ROOT / ".claude/scripts/verify-gate-evidence.py",
                    scripts / "verify-gate-evidence.py")
        lib = scripts / "lib"
        for helper in ("gate_evidence_runner.py", "schema_version_gate.py"):
            shutil.copy(ROOT / ".claude/scripts/lib" / helper, lib / helper)
        patterns = self.tmp / ".claude" / "patterns"
        for pf in ("gate-evidence-rules.json", "gate-evidence-rule-schema.json"):
            shutil.copy(ROOT / ".claude/patterns" / pf, patterns / pf)

    def run_check(self) -> tuple[dict, subprocess.CompletedProcess]:
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(self.tmp)
        for mode_var in ("PROSE_GATE_RETRO_MODE", "OBSERVER_EVIDENCE_COVERAGE_MODE",
                         "ANOMALY_AUDIT_MODE", "GATE_EVIDENCE_RECOVERY_SKIP_MODE",
                         "GATE_EVIDENCE_SPARSE_TRACE_MODE"):
            env.pop(mode_var, None)
        proc = subprocess.run(
            ["bash", str(SCRIPT), self.SKILL], cwd=self.tmp,
            capture_output=True, text=True, env=env, timeout=120,
        )
        artifact = self.runs / "observation-enforcement.json"
        self.assertTrue(artifact.is_file(),
                        f"stdout={proc.stdout}\nstderr={proc.stderr}")
        return json.loads(artifact.read_text()), proc


class TestGateEvidenceStep(GateEvidenceFixture):
    @unittest.skipUnless(HAVE_JSONSCHEMA, "jsonschema not installed")
    def test_statuses_recorded_and_never_blocking(self):
        self._install_gate_evidence()
        result, proc = self.run_check()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        ge = result.get("gate_evidence")
        self.assertIsInstance(ge, dict, result)
        self.assertEqual(
            set(ge), {"recovery-path-skip-pairing", "sparse-trace-pairing"})
        for rule_id, status in ge.items():
            self.assertIn(status, ("pass", "warn", "skip", "deny", "error"),
                          f"{rule_id}: {status}")
        # Whatever the statuses, the step must not have blocked.
        self.assertTrue(result.get("pass"), result)
        self.assertEqual(result.get("missing"), [], result)

    @unittest.skipUnless(HAVE_JSONSCHEMA, "jsonschema not installed")
    def test_sparse_trace_present_still_non_blocking(self):
        self._install_gate_evidence()
        # Init-stub-shaped sparse trace for the declared critic agent.
        (self.runs / "agent-traces" / "solve-critic.json").write_text(json.dumps({
            "agent": "solve-critic", "status": "completed",
            "run_id": self.RUN_ID, "timestamp": _live_ts(), "verdict": "pass",
        }))
        result, proc = self.run_check()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(result.get("pass"), result)
        self.assertIn("sparse-trace-pairing", result.get("gate_evidence", {}))

    def test_script_absent_skips_cleanly(self):
        # Degraded fixture (the fast-path tests' shape): no
        # verify-gate-evidence.py in the project — the step must skip and the
        # artifact must still be written with an empty gate_evidence.
        result, proc = self.run_check()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(result.get("gate_evidence"), {}, result)
        self.assertTrue(result.get("pass"), result)


if __name__ == "__main__":
    sys.exit(unittest.main())
