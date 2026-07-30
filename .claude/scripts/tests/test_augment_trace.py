#!/usr/bin/env python3
"""test_augment_trace.py — exercise the AOC v1.1 narrow trace-augmenter.

Validates:
  * Whitelisted fields are accepted; unknown fields are rejected
  * Protected fields cannot be set even if listed in ALLOWED (defensive double-check)
  * Spawn-log match is required (precondition for augmenting any trace)
  * Idempotent: re-running with same args overwrites with consistent result
  * augmented_at audit log records each augmentation
  * Agent / run_id mismatch refused
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
SCRIPT = ROOT / ".claude/scripts/augment-trace.py"


def _setup_repo() -> Path:
    """Real git repo + .claude tree + active context (mirrors test_write_recovery.py)."""
    tmp = Path(tempfile.mkdtemp(prefix="test-augment-trace-"))
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp)], check=True)
    subprocess.run(["git", "-C", str(tmp), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(tmp), "config", "user.name", "test"], check=True)
    subprocess.run(["git", "-C", str(tmp), "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    shutil.copytree(ROOT / ".claude", tmp / ".claude", dirs_exist_ok=True)
    runs = tmp / ".runs"
    runs.mkdir(exist_ok=True)
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id = f"test-{ts}"
    (runs / "test-context.json").write_text(json.dumps({
        "skill": "test",
        "branch": "main",
        "timestamp": ts,
        "run_id": run_id,
        "completed": False,
    }))
    # Spawn-log entry for design-critic with spawn_index=2
    (runs / "agent-spawn-log.jsonl").write_text(json.dumps({
        "agent": "design-critic",
        "run_id": run_id,
        "skill": "test",
        "spawn_index": 2,
        "head_sha": "abc",
        "hook": "skill-agent-gate",
        "timestamp": ts,
    }) + "\n")
    # Pre-existing trace file (augment can't create traces)
    traces = runs / "agent-traces"
    traces.mkdir()
    (traces / "design-critic-landing.json").write_text(json.dumps({
        "agent": "design-critic",
        "timestamp": ts,
        "status": "completed",
        "verdict": "pass",
        "provenance": "self",
        "partial": False,
        "checks_performed": ["layer1"],
        "run_id": run_id,
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


class TestAugmentTrace(unittest.TestCase):
    def setUp(self):
        self.repo = _setup_repo()

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_allowed_field_accepted(self):
        rc, _, err = _run(
            self.repo,
            "--agent", "design-critic",
            "--augment-spawn-index", "2",
            "--field", "page=landing",
            "--trace-filename", "design-critic-landing.json",
        )
        self.assertEqual(rc, 0, f"stderr={err}")
        d = json.loads((self.repo / ".runs/agent-traces/design-critic-landing.json").read_text())
        self.assertEqual(d["page"], "landing")
        self.assertIsInstance(d.get("augmented_at"), list)
        self.assertEqual(len(d["augmented_at"]), 1)

    def test_unknown_field_rejected(self):
        rc, _, err = _run(
            self.repo,
            "--agent", "design-critic",
            "--augment-spawn-index", "2",
            "--field", "arbitrary_key=value",
            "--trace-filename", "design-critic-landing.json",
        )
        self.assertNotEqual(rc, 0)
        self.assertIn("not in ALLOWED_AUGMENT_FIELDS", err)

    def test_protected_field_rejected(self):
        rc, _, err = _run(
            self.repo,
            "--agent", "design-critic",
            "--augment-spawn-index", "2",
            "--field", "provenance=self-degraded",
            "--trace-filename", "design-critic-landing.json",
        )
        self.assertNotEqual(rc, 0)
        self.assertIn("protected", err)

    def test_spawn_log_mismatch_refused(self):
        rc, _, err = _run(
            self.repo,
            "--agent", "design-critic",
            "--augment-spawn-index", "99",  # Doesn't exist in spawn-log
            "--field", "page=landing",
            "--trace-filename", "design-critic-landing.json",
        )
        self.assertNotEqual(rc, 0)
        self.assertIn("no spawn-log entry", err)

    def test_missing_target_trace_refused(self):
        rc, _, err = _run(
            self.repo,
            "--agent", "design-critic",
            "--augment-spawn-index", "2",
            "--field", "page=landing",
            "--trace-filename", "does-not-exist.json",
        )
        self.assertNotEqual(rc, 0)
        self.assertIn("does not exist", err)

    def test_idempotent_overwrite(self):
        # First call sets page=landing
        rc1, _, _ = _run(
            self.repo,
            "--agent", "design-critic",
            "--augment-spawn-index", "2",
            "--field", "page=landing",
            "--trace-filename", "design-critic-landing.json",
        )
        # Second call sets page=pricing — last writer wins
        rc2, _, _ = _run(
            self.repo,
            "--agent", "design-critic",
            "--augment-spawn-index", "2",
            "--field", "page=pricing",
            "--trace-filename", "design-critic-landing.json",
        )
        self.assertEqual(rc1, 0)
        self.assertEqual(rc2, 0)
        d = json.loads((self.repo / ".runs/agent-traces/design-critic-landing.json").read_text())
        self.assertEqual(d["page"], "pricing")
        # Audit list grew
        self.assertEqual(len(d["augmented_at"]), 2)

    def test_json_value_parsed(self):
        rc, _, err = _run(
            self.repo,
            "--agent", "design-critic",
            "--augment-spawn-index", "2",
            "--field", "candidates_tried=3",
            "--trace-filename", "design-critic-landing.json",
        )
        self.assertEqual(rc, 0, f"stderr={err}")
        d = json.loads((self.repo / ".runs/agent-traces/design-critic-landing.json").read_text())
        self.assertEqual(d["candidates_tried"], 3)
        self.assertNotEqual(d["candidates_tried"], "3")  # parsed as int, not string

    def test_array_value_parsed(self):
        rc, _, err = _run(
            self.repo,
            "--agent", "design-critic",
            "--augment-spawn-index", "2",
            "--field", 'pages_reviewed=["landing","pricing"]',
            "--trace-filename", "design-critic-landing.json",
        )
        self.assertEqual(rc, 0, f"stderr={err}")
        d = json.loads((self.repo / ".runs/agent-traces/design-critic-landing.json").read_text())
        self.assertEqual(d["pages_reviewed"], ["landing", "pricing"])

    # ---- PR2b: --augment-spawn-index optional (per-page parallel spawn case) ----

    def test_omitted_spawn_index_accepts_any_matching_entry(self):
        """When spawn_index is omitted, any spawn-log entry for agent+run_id satisfies."""
        rc, _, err = _run(
            self.repo,
            "--agent", "design-critic",
            "--field", "page=landing",
            "--trace-filename", "design-critic-landing.json",
        )
        self.assertEqual(rc, 0, f"stderr={err}")
        d = json.loads((self.repo / ".runs/agent-traces/design-critic-landing.json").read_text())
        self.assertEqual(d["page"], "landing")
        # Audit entry should NOT include spawn_index when not supplied
        self.assertEqual(len(d["augmented_at"]), 1)
        self.assertNotIn("spawn_index", d["augmented_at"][0])

    def test_omitted_spawn_index_still_requires_some_entry(self):
        """When spawn_index is omitted, but no spawn-log entry exists for agent+run_id,
        augmentation is still refused (forgery defense unchanged)."""
        rc, _, err = _run(
            self.repo,
            "--agent", "observer",  # NOT in spawn-log
            "--field", "fixes_evaluated=5",
            "--trace-filename", "design-critic-landing.json",
        )
        self.assertNotEqual(rc, 0)
        self.assertIn("no spawn-log entry", err)

    def test_field_only_no_spawn_index_audit_entry_clean(self):
        """Audit list must be a clean shape when spawn_index is omitted."""
        _run(
            self.repo,
            "--agent", "design-critic",
            "--field", "page=landing",
            "--trace-filename", "design-critic-landing.json",
        )
        d = json.loads((self.repo / ".runs/agent-traces/design-critic-landing.json").read_text())
        entry = d["augmented_at"][0]
        self.assertIn("timestamp", entry)
        self.assertIn("fields", entry)
        self.assertEqual(entry["fields"], ["page"])


def main():
    if not SCRIPT.is_file():
        print(f"ERROR: script not found at {SCRIPT}", file=sys.stderr)
        return 2
    result = unittest.main(exit=False, verbosity=2).result
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
