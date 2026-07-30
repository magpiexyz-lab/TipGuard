#!/usr/bin/env python3
"""test_state_completion_gate_mode_qualified_provenance.py — regression for the
#1990-flagged fail-open: state-completion-gate.sh resolved the framework
manifest with the mode-qualified advance-state arg (iterate-cross) →
nonexistent .runs/iterate-cross-lifecycle.json → the universal spawn-provenance
check silently skipped for every mode-qualified run. The fix derives
BASE_SKILL via resolve_skill_dir for the manifest path; the qualified context
path (.runs/iterate-cross-context.json) stays as-is.

Run: python3 -m pytest .claude/scripts/tests/test_state_completion_gate_mode_qualified_provenance.py -v
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
HOOK = ROOT / ".claude/hooks/state-completion-gate.sh"
RUN_ID = "run-scg-prov-1"


def _live_ts() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ProvenanceFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_scgp_mq_"))
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.tmp, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=self.tmp, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=self.tmp, check=True)
        subprocess.run(
            ["git", "commit", "-q", "--allow-empty", "-m", "init"],
            cwd=self.tmp, check=True,
        )
        self.runs = self.tmp / ".runs"
        (self.runs / "agent-traces").mkdir(parents=True)
        patterns = self.tmp / ".claude" / "patterns"
        patterns.mkdir(parents=True)
        # VERIFY must be a real (passing) command: a literal "true" entry takes
        # the intentional no-check fast path and exits before the provenance
        # section this test targets.
        (patterns / "state-registry.json").write_text(json.dumps({
            "iterate-cross": {"x0": "test -f .runs/iterate-cross-context.json"},
        }))
        (self.runs / "iterate-cross-context.json").write_text(json.dumps({
            "skill": "iterate-cross", "run_id": RUN_ID, "branch": "main",
            "timestamp": _live_ts(), "completed": False,
            "completed_states": [],
        }))
        (self.runs / "iterate-lifecycle.json").write_text(json.dumps({
            "skill": "iterate", "active_mode": "cross",
            "modes": {"cross": {"states": ["x0"]}},
            "agents": {"probe-agent": {}},
        }))
        (self.runs / "agent-traces" / "probe-agent.json").write_text(json.dumps({
            "agent": "probe-agent", "run_id": RUN_ID, "status": "completed",
            "verdict": "pass", "timestamp": _live_ts(),
        }))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _spawn_log(self, rows: list[dict]):
        with open(self.runs / "agent-spawn-log.jsonl", "w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")

    def run_hook(self):
        payload = json.dumps({
            "tool_name": "Bash",
            "tool_input": {"command": "bash .claude/scripts/advance-state.sh iterate-cross x0"},
        })
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(self.tmp)
        return subprocess.run(
            ["bash", str(HOOK)], input=payload, cwd=self.tmp,
            capture_output=True, text=True, env=env, timeout=60,
        )


class TestModeQualifiedProvenance(ProvenanceFixture):
    def test_completed_trace_without_spawn_record_is_denied(self):
        self._spawn_log([{
            "agent": "probe-agent", "run_id": "some-prior-run",
            "hook": "skill-agent-gate", "timestamp": _live_ts(),
        }])
        r = self.run_hook()
        self.assertEqual(r.returncode, 2, f"stdout={r.stdout}\nstderr={r.stderr}")
        self.assertIn("no spawn record", r.stderr.lower())

    def test_matching_spawn_record_allows(self):
        self._spawn_log([{
            "agent": "probe-agent", "run_id": RUN_ID,
            "hook": "skill-agent-gate", "timestamp": _live_ts(),
        }])
        r = self.run_hook()
        self.assertEqual(r.returncode, 0, f"stdout={r.stdout}\nstderr={r.stderr}")

    def test_qualified_context_path_still_used(self):
        # Control for the deliberate non-change: the provenance python reads
        # .runs/iterate-cross-context.json (qualified). Break the run_id there
        # and a matching spawn row keyed on the OLD id must stop matching.
        self._spawn_log([{
            "agent": "probe-agent", "run_id": RUN_ID,
            "hook": "skill-agent-gate", "timestamp": _live_ts(),
        }])
        (self.runs / "iterate-cross-context.json").write_text(json.dumps({
            "skill": "iterate-cross", "run_id": "rotated-run", "branch": "main",
            "timestamp": _live_ts(), "completed": False,
            "completed_states": [],
        }))
        # Trace must belong to the rotated run to stay eligible.
        (self.runs / "agent-traces" / "probe-agent.json").write_text(json.dumps({
            "agent": "probe-agent", "run_id": "rotated-run", "status": "completed",
            "verdict": "pass", "timestamp": _live_ts(),
        }))
        r = self.run_hook()
        self.assertEqual(r.returncode, 2, r.stderr)


if __name__ == "__main__":
    sys.exit(unittest.main())
