#!/usr/bin/env python3
"""test_write_agent_trace.py — exercise the AOC v1.1 centralized writer.

Validates:
  * --json + --provenance flag combinations
  * --source required for lead-on-behalf
  * --coverage-provider required for lead-synthesized
  * lead-on-behalf requires spawn-log entry
  * Protected-field rejection (caller cannot set provenance / run_id / etc. via payload)
  * Atomic write produces valid JSON
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
SCRIPT = ROOT / ".claude/scripts/write-agent-trace.sh"


def _setup_repo() -> Path:
    """Create an isolated temp git repo with the minimum scaffolding the script needs.

    resolve_active_identity reads context.json AND filters by current git
    branch, so we need a real git repo (init + initial commit) plus the
    .claude tree copied in.
    """
    tmp = Path(tempfile.mkdtemp(prefix="test-write-agent-trace-"))
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(["git", "-C", str(tmp), "config", "user.name", "test"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp), "commit", "-q", "--allow-empty", "-m", "init"],
        check=True,
    )
    # Copy .claude into the temp repo so resolve_active_identity / lib.sh work.
    shutil.copytree(ROOT / ".claude", tmp / ".claude", dirs_exist_ok=True)
    # Always use a fresh symlink-free runs/ — the temp repo doesn't include .runs/.
    runs = tmp / ".runs"
    runs.mkdir(exist_ok=True)
    # Active context.json on the same branch (main) so resolve_active_identity
    # returns this skill. Use a fresh ISO timestamp so the 48h staleness cap
    # doesn't filter it out.
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (runs / "test-context.json").write_text(json.dumps({
        "skill": "test",
        "branch": "main",
        "timestamp": ts,
        "run_id": f"test-{ts}",
        "completed": False,
    }))
    # Spawn-log with one entry for the agent we'll exercise (to test
    # lead-on-behalf precondition).
    (runs / "agent-spawn-log.jsonl").write_text(json.dumps({
        "agent": "build-info-collector",
        "run_id": f"test-{ts}",
        "skill": "test",
        "spawn_index": 1,
        "head_sha": "abc123",
        "hook": "skill-agent-gate",
        "timestamp": ts,
    }) + "\n")
    return tmp


def _run(repo: Path, *args, env_extra=None) -> tuple[int, str, str]:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(repo),
        timeout=30,
    )
    return proc.returncode, proc.stdout, proc.stderr


class TestWriteAgentTrace(unittest.TestCase):
    def setUp(self):
        self.repo = _setup_repo()
        self.run_id = json.loads(
            (self.repo / ".runs/test-context.json").read_text()
        )["run_id"]

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_self_provenance_writes_trace(self):
        payload = json.dumps({
            "verdict": "pass",
            "result": "clean",
            "checks_performed": ["c1"],
        })
        rc, out, err = _run(
            self.repo, "build-info-collector",
            "--json", payload,
            "--provenance", "self",
        )
        self.assertEqual(rc, 0, f"stderr={err}")
        target = self.repo / ".runs/agent-traces/build-info-collector.json"
        self.assertTrue(target.exists())
        d = json.loads(target.read_text())
        self.assertEqual(d["agent"], "build-info-collector")
        self.assertEqual(d["provenance"], "self")
        self.assertEqual(d["run_id"], self.run_id)
        self.assertEqual(d["partial"], False)

    def test_lead_on_behalf_requires_source_flag(self):
        payload = json.dumps({"verdict": "pass", "result": "clean", "checks_performed": ["c"]})
        rc, _, err = _run(
            self.repo, "build-info-collector",
            "--json", payload,
            "--provenance", "lead-on-behalf",
        )
        self.assertNotEqual(rc, 0)
        self.assertIn("--source is required", err)

    def test_lead_on_behalf_requires_spawn_log_entry(self):
        # Use an agent NOT in spawn-log
        payload = json.dumps({"verdict": "pass", "result": "clean", "checks_performed": ["c"]})
        rc, _, err = _run(
            self.repo, "observer",
            "--json", payload,
            "--provenance", "lead-on-behalf",
            "--source", "agent-returned-text",
        )
        self.assertNotEqual(rc, 0)
        self.assertIn("requires a spawn-log", err)

    def test_lead_on_behalf_with_spawn_log_writes_trace(self):
        payload = json.dumps({
            "verdict": "pass",
            "result": "clean",
            "checks_performed": ["c1", "c2"],
        })
        rc, _, err = _run(
            self.repo, "build-info-collector",
            "--json", payload,
            "--provenance", "lead-on-behalf",
            "--source", "agent-returned-text",
        )
        self.assertEqual(rc, 0, f"stderr={err}")
        target = self.repo / ".runs/agent-traces/build-info-collector.json"
        d = json.loads(target.read_text())
        self.assertEqual(d["provenance"], "lead-on-behalf")
        self.assertEqual(d["partial"], True)
        self.assertEqual(d["source"], "agent-returned-text")
        self.assertEqual(d["recovery_validated"], False)
        self.assertEqual(d["spawn_sha"], "abc123")
        self.assertEqual(d["spawn_index"], 1)

    def test_lead_synthesized_requires_coverage_provider(self):
        payload = json.dumps({
            "verdict": "pass",
            "result": "clean",
            "checks_performed": [],
            "no_fixes_claimed": True,
        })
        rc, _, err = _run(
            self.repo, "build-info-collector",
            "--json", payload,
            "--provenance", "lead-synthesized",
        )
        self.assertNotEqual(rc, 0)
        self.assertIn("--coverage-provider is required", err)

    def test_lead_synthesized_with_coverage_provider_writes_trace(self):
        payload = json.dumps({
            "verdict": "pass",
            "result": "clean",
            "no_fixes_claimed": True,
        })
        rc, _, err = _run(
            self.repo, "build-info-collector",
            "--json", payload,
            "--provenance", "lead-synthesized",
            "--coverage-provider", "tests/flows.test.ts",
        )
        self.assertEqual(rc, 0, f"stderr={err}")
        target = self.repo / ".runs/agent-traces/build-info-collector.json"
        d = json.loads(target.read_text())
        self.assertEqual(d["provenance"], "lead-synthesized")
        self.assertEqual(d["coverage_provider"], "tests/flows.test.ts")
        self.assertEqual(d["partial"], True)
        self.assertEqual(d["no_fixes_claimed"], True)
        self.assertEqual(d["checks_performed"], [])

    def test_lead_synthesized_rejects_fixes(self):
        payload = json.dumps({
            "verdict": "pass",
            "result": "clean",
            "fixes": [{"file": "x.ts", "symptom": "y", "fix": "z"}],
        })
        rc, _, err = _run(
            self.repo, "build-info-collector",
            "--json", payload,
            "--provenance", "lead-synthesized",
            "--coverage-provider", "tests/flows.test.ts",
        )
        self.assertNotEqual(rc, 0)
        self.assertIn("must not claim fixes", err)

    def test_payload_protected_field_rejected(self):
        payload = json.dumps({
            "verdict": "pass",
            "result": "clean",
            "checks_performed": ["c"],
            "provenance": "self-degraded",  # Caller tries to override flag
        })
        rc, _, err = _run(
            self.repo, "build-info-collector",
            "--json", payload,
            "--provenance", "self",
        )
        self.assertNotEqual(rc, 0)
        self.assertIn("protected field", err)

    def test_invalid_provenance_flag(self):
        rc, _, err = _run(
            self.repo, "build-info-collector",
            "--json", "{}",
            "--provenance", "invented",
        )
        self.assertNotEqual(rc, 0)
        self.assertIn("must be one of", err)

    def test_payload_must_be_object(self):
        rc, _, err = _run(
            self.repo, "build-info-collector",
            "--json", "[1,2,3]",
            "--provenance", "self",
        )
        self.assertNotEqual(rc, 0)
        self.assertIn("must be a JSON object", err)

    def test_spawn_index_override_disambiguates_parallel_spawns(self):
        """Two spawn-log rows for scaffold-pages with different spawn_index;
        --spawn-index 2 must select the second row, not first-match the first."""
        spawn_log = self.repo / ".runs/agent-spawn-log.jsonl"
        existing = spawn_log.read_text()
        # Add two rows for the same agent to simulate parallel spawn
        spawn_log.write_text(existing + "".join([
            json.dumps({
                "agent": "scaffold-pages", "run_id": self.run_id,
                "skill": "test", "spawn_index": 1, "head_sha": "sha-page-1",
                "hook": "skill-agent-gate", "timestamp": "2026-01-01T00:00:00Z",
            }) + "\n",
            json.dumps({
                "agent": "scaffold-pages", "run_id": self.run_id,
                "skill": "test", "spawn_index": 2, "head_sha": "sha-page-2",
                "hook": "skill-agent-gate", "timestamp": "2026-01-01T00:00:01Z",
            }) + "\n",
        ]))
        payload = json.dumps({"verdict": "pass", "result": "clean", "checks_performed": ["c"]})
        rc, _, err = _run(
            self.repo, "scaffold-pages",
            "--json", payload,
            "--spawn-index", "2",
            "--trace-filename", "scaffold-pages-pricing.json",
        )
        self.assertEqual(rc, 0, f"stderr={err}")
        target = self.repo / ".runs/agent-traces/scaffold-pages-pricing.json"
        d = json.loads(target.read_text())
        self.assertEqual(d["spawn_index"], 2)
        self.assertEqual(d["spawn_sha"], "sha-page-2")

    def test_spawn_index_override_no_match_fails(self):
        """--spawn-index N with no matching spawn-log row must error out."""
        payload = json.dumps({"verdict": "pass", "result": "clean", "checks_performed": ["c"]})
        rc, _, err = _run(
            self.repo, "build-info-collector",
            "--json", payload,
            "--spawn-index", "99",
        )
        self.assertNotEqual(rc, 0)
        self.assertIn("no spawn-log row matches", err)
        self.assertIn("spawn_index=99", err)

    def test_spawn_index_override_must_be_integer(self):
        rc, _, err = _run(
            self.repo, "build-info-collector",
            "--json", "{}",
            "--spawn-index", "abc",
        )
        self.assertNotEqual(rc, 0)
        self.assertIn("non-negative integer", err)

    def test_spawn_index_default_first_match_preserved(self):
        """Without --spawn-index, the loop falls back to first-match behavior
        (single-spawn agents and existing migrated callers stay unaffected)."""
        spawn_log = self.repo / ".runs/agent-spawn-log.jsonl"
        existing = spawn_log.read_text()
        spawn_log.write_text(existing + "".join([
            json.dumps({
                "agent": "scaffold-pages", "run_id": self.run_id,
                "skill": "test", "spawn_index": 1, "head_sha": "sha-page-1",
                "hook": "skill-agent-gate", "timestamp": "2026-01-01T00:00:00Z",
            }) + "\n",
            json.dumps({
                "agent": "scaffold-pages", "run_id": self.run_id,
                "skill": "test", "spawn_index": 2, "head_sha": "sha-page-2",
                "hook": "skill-agent-gate", "timestamp": "2026-01-01T00:00:01Z",
            }) + "\n",
        ]))
        payload = json.dumps({"verdict": "pass", "result": "clean", "checks_performed": ["c"]})
        rc, _, err = _run(
            self.repo, "scaffold-pages",
            "--json", payload,
        )
        self.assertEqual(rc, 0, f"stderr={err}")
        target = self.repo / ".runs/agent-traces/scaffold-pages.json"
        d = json.loads(target.read_text())
        # First-match: spawn_index 1 wins
        self.assertEqual(d["spawn_index"], 1)
        self.assertEqual(d["spawn_sha"], "sha-page-1")


def main():
    if not SCRIPT.is_file():
        print(f"ERROR: script not found at {SCRIPT}", file=sys.stderr)
        return 2
    result = unittest.main(exit=False, verbosity=2).result
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
