#!/usr/bin/env python3
"""test_resolve_active_identity.py — verify the hook-level identity helper.

Creates synthetic .runs/*-context.json files in a temp dir and calls the
bash helper via `bash -c 'source lib.sh && resolve_active_identity'`.
Covers: top-level, one-level embed, two-level embed, stale abandoned context,
cross-branch context, completed context, all-empty, and >48h staleness cap.
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


def call_resolver(project_dir: Path, branch: str) -> tuple[str, str, str, str]:
    """Invoke resolve_active_identity via bash and split tab-separated output."""
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    cmd = [
        "bash", "-c",
        f'cd "{project_dir}" && git checkout -q "{branch}" 2>/dev/null || true; '
        f'source "{LIB}" && resolve_active_identity',
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=10)
    line = proc.stdout.strip()
    if not line:
        return "", "", "", ""
    parts = line.split("\t")
    while len(parts) < 4:
        parts.append("")
    return tuple(parts[:4])


class TestResolveActiveIdentity(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_rai_"))
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        subprocess.run(["git", "-C", str(self.tmp), "commit", "-q", "--allow-empty",
                        "-m", "init"], check=True)
        self.runs = self.tmp / ".runs"
        self.runs.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_ctx(self, skill: str, *, completed=False, ts_offset=0, branch="main",
                   parent=None, ancestors=None, attributed_to=None):
        name = f"{skill}-context.json"
        ts = now_iso(ts_offset)
        d = {
            "skill": skill,
            "branch": branch,
            "timestamp": ts,
            "run_id": f"{skill}-{ts}",
            "completed_states": [],
            "parent": parent,
            "ancestors": ancestors or [],
            "attributed_to": attributed_to or skill,
            "completed": completed,
        }
        (self.runs / name).write_text(json.dumps(d))
        return d

    def test_empty_returns_nothing(self):
        s, r, a, anc = call_resolver(self.tmp, "main")
        self.assertEqual(s, "")
        self.assertEqual(r, "")

    def test_top_level_active(self):
        d = self._write_ctx("solve")
        s, r, a, anc = call_resolver(self.tmp, "main")
        self.assertEqual(s, "solve")
        self.assertEqual(r, d["run_id"])
        self.assertEqual(a, "solve")
        self.assertEqual(anc, "[]")

    def test_one_level_embed_picks_inner(self):
        parent = self._write_ctx("bootstrap", ts_offset=-0.001)
        self._write_ctx(
            "verify",
            parent={"skill": "bootstrap", "run_id": parent["run_id"]},
            ancestors=[{"skill": "bootstrap", "run_id": parent["run_id"]}],
            attributed_to="bootstrap",
        )
        s, r, a, anc = call_resolver(self.tmp, "main")
        self.assertEqual(s, "verify")
        self.assertEqual(a, "bootstrap")
        anc_j = json.loads(anc)
        self.assertEqual(len(anc_j), 1)
        self.assertEqual(anc_j[0]["skill"], "bootstrap")

    def test_completed_context_skipped(self):
        self._write_ctx("solve", completed=True)
        s, r, a, _ = call_resolver(self.tmp, "main")
        self.assertEqual(s, "")

    def test_stale_context_skipped(self):
        self._write_ctx("solve", ts_offset=-72)  # 72h ago
        s, r, a, _ = call_resolver(self.tmp, "main")
        self.assertEqual(s, "", "stale context >48h must be skipped")

    def test_cross_branch_context_skipped(self):
        subprocess.run(["git", "-C", str(self.tmp), "checkout", "-q", "-b", "feat/x"], check=True)
        self._write_ctx("solve", branch="main")  # not the current branch
        s, r, a, _ = call_resolver(self.tmp, "feat/x")
        self.assertEqual(s, "", "context from a different branch must be skipped")

    def test_most_recent_wins(self):
        self._write_ctx("solve", ts_offset=-0.01)
        d2 = self._write_ctx("change")
        s, r, a, _ = call_resolver(self.tmp, "main")
        self.assertEqual(s, "change")
        self.assertEqual(r, d2["run_id"])

    def test_two_level_embed_picks_innermost(self):
        root = self._write_ctx("bootstrap", ts_offset=-0.002)
        mid = self._write_ctx(
            "change",
            ts_offset=-0.001,
            parent={"skill": "bootstrap", "run_id": root["run_id"]},
            ancestors=[{"skill": "bootstrap", "run_id": root["run_id"]}],
            attributed_to="bootstrap",
        )
        self._write_ctx(
            "verify",
            parent={"skill": "change", "run_id": mid["run_id"]},
            ancestors=[
                {"skill": "bootstrap", "run_id": root["run_id"]},
                {"skill": "change", "run_id": mid["run_id"]},
            ],
            attributed_to="bootstrap",
        )
        s, r, a, anc = call_resolver(self.tmp, "main")
        self.assertEqual(s, "verify")
        anc_j = json.loads(anc)
        self.assertEqual(len(anc_j), 2)
        self.assertEqual(anc_j[0]["skill"], "bootstrap")
        self.assertEqual(anc_j[1]["skill"], "change")


if __name__ == "__main__":
    unittest.main(verbosity=2)
