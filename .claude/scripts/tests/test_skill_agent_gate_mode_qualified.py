#!/usr/bin/env python3
"""test_skill_agent_gate_mode_qualified.py — regression for the #1990-flagged
hook fail-open: skill-agent-gate.sh resolved the framework manifest with the
MODE-QUALIFIED ACTIVE_SKILL (iterate-cross) → nonexistent
.runs/iterate-cross-lifecycle.json → "manifest absent" friction + exit 0,
skipping the declarative agent checks AND the agent-spawn-log write. The fix
derives BASE_SKILL via resolve_skill_dir for the manifest path only.

Run: python3 -m pytest .claude/scripts/tests/test_skill_agent_gate_mode_qualified.py -v
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
HOOK = ROOT / ".claude/hooks/skill-agent-gate.sh"


def _live_ts() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AgentGateFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_sag_mq_"))
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.tmp, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=self.tmp, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=self.tmp, check=True)
        subprocess.run(
            ["git", "commit", "-q", "--allow-empty", "-m", "init"],
            cwd=self.tmp, check=True,
        )
        self.runs = self.tmp / ".runs"
        self.runs.mkdir()
        (self.runs / "iterate-cross-context.json").write_text(json.dumps({
            "skill": "iterate-cross", "run_id": "run-sag-1", "branch": "main",
            "timestamp": _live_ts(), "completed": False,
        }))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _manifest(self, agents: dict):
        (self.runs / "iterate-lifecycle.json").write_text(json.dumps({
            "skill": "iterate", "active_mode": "cross",
            "modes": {"cross": {"states": ["x0"]}},
            "agents": agents,
        }))

    def _spawn_log(self) -> list[dict]:
        p = self.runs / "agent-spawn-log.jsonl"
        if not p.is_file():
            return []
        return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]

    def run_hook(self, subagent_type="probe-agent"):
        payload = json.dumps({
            "tool_name": "Agent",
            "tool_input": {"subagent_type": subagent_type, "prompt": "do the thing"},
        })
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(self.tmp)
        env.pop("SOURCE_RUN_ID", None)
        env.pop("SOURCE_SKILL", None)
        return subprocess.run(
            ["bash", str(HOOK)], input=payload, cwd=self.tmp,
            capture_output=True, text=True, env=env, timeout=60,
        )


class TestModeQualifiedAgentGate(AgentGateFixture):
    def test_declared_agent_spawn_writes_spawn_log(self):
        self._manifest({"probe-agent": {}})
        r = self.run_hook("probe-agent")
        self.assertEqual(r.returncode, 0, f"stdout={r.stdout}\nstderr={r.stderr}")
        rows = self._spawn_log()
        self.assertTrue(rows, "spawn-log entry not written (the restored write)")
        self.assertEqual(rows[-1].get("skill"), "iterate-cross")
        self.assertEqual(rows[-1].get("run_id"), "run-sag-1")

    def test_undeclared_agent_allowed_without_manifest_absent_warn(self):
        self._manifest({})
        r = self.run_hook("some-other-agent")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("manifest", r.stderr.lower())
        friction = self.runs / "hook-friction.jsonl"
        if friction.is_file():
            self.assertNotIn("failing open", friction.read_text())

    def test_manifest_truly_absent_still_fails_open(self):
        r = self.run_hook("probe-agent")
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    sys.exit(unittest.main())
