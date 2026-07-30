#!/usr/bin/env python3
"""test_gate_artifact_bash_write_guard.py — runtime guard on direct-bash
writes to gate-readable .runs/*.json artifacts.

Sibling to .claude/hooks/gate-artifact-write-gate.sh (Write/Edit matcher).
This hook (Bash matcher) catches what the Write/Edit gate cannot see:
shell redirects, tee, cat <<EOF > path, and inline `python3 -c "open(...)"`
writes targeting paths declared in
.claude/patterns/gate-readable-artifacts-canonical.json.

Test cases (R2-C5 falsifiable soak, R1-C8 meta-test convention):
  1. Fast-path: unrelated commands → allow, no friction.
  2. Read-only commands on canonical paths → allow, no friction.
  3. Canonical writer invocation → allow, no friction.
  4. echo > <manifest-path> in warn mode → exits 0 + friction logged.
  5. python3 -c "open(...,'w')" in warn mode → exits 0 + friction logged.
  6. cat > <manifest-path> <<EOF in warn mode → exits 0 + friction logged.
  7. tee <manifest-path> in warn mode → exits 0 + friction logged.
  8. Chained write after canonical writer → friction logged
     (chain-bound check fires before allowlist short-circuit).
  9. Non-manifest-path redirect → allow, no friction.
 10. Each warn-firing branch logs exactly one friction entry per invocation.
 11. MODE=deny: same writes return non-zero exit and deny stderr.

Run: python3 .claude/scripts/tests/test_gate_artifact_bash_write_guard.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HOOK = ROOT / ".claude/hooks/gate-artifact-bash-write-guard.sh"


class GuardHarness(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_gabwg_"))
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        shutil.copytree(ROOT / ".claude", self.tmp / ".claude", dirs_exist_ok=True)
        # Fresh friction log per test.
        runs = self.tmp / ".runs"
        runs.mkdir(exist_ok=True)
        (runs / "hook-friction.jsonl").write_text("")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _invoke(self, command: str, mode: str = "warn") -> tuple[int, str]:
        payload = json.dumps({
            "tool_name": "Bash",
            "tool_input": {"command": command},
        })
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(self.tmp)
        env["GATE_ARTIFACT_BASH_WRITE_GUARD_MODE"] = mode
        proc = subprocess.run(
            ["bash", str(self.tmp / ".claude/hooks/gate-artifact-bash-write-guard.sh")],
            input=payload,
            capture_output=True, text=True, env=env, timeout=15,
            cwd=str(self.tmp),
        )
        return proc.returncode, proc.stderr

    def _friction_lines(self) -> list[dict]:
        f = self.tmp / ".runs/hook-friction.jsonl"
        if not f.exists():
            return []
        out = []
        for line in f.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return [
            e for e in out
            if e.get("hook") == "gate-artifact-bash-write-guard.sh"
        ]


class TestFastPath(GuardHarness):
    def test_no_runs_mention(self):
        rc, err = self._invoke("ls /tmp")
        self.assertEqual(rc, 0)
        self.assertEqual(self._friction_lines(), [])

    def test_runs_dir_only_no_redirect(self):
        rc, err = self._invoke("ls .runs/")
        self.assertEqual(rc, 0)
        self.assertEqual(self._friction_lines(), [])


class TestReadAllowed(GuardHarness):
    def test_cat_runs_json(self):
        rc, err = self._invoke("cat .runs/q-dimensions.json 2>/dev/null || true")
        self.assertEqual(rc, 0)
        self.assertEqual(self._friction_lines(), [])

    def test_python_load(self):
        rc, err = self._invoke("python3 -c \"import json; json.load(open('.runs/q-dimensions.json'))\"")
        self.assertEqual(rc, 0)
        self.assertEqual(self._friction_lines(), [])


class TestCanonicalWriterAllowed(GuardHarness):
    def test_canonical_writer_call(self):
        cmd = (
            "bash .claude/scripts/lib/write-gate-artifact.sh "
            "--path .runs/q-dimensions.json --payload '{}' --skill audit"
        )
        rc, err = self._invoke(cmd)
        self.assertEqual(rc, 0)
        # No bound write detected because the writer is a single-call
        # subprocess, not a shell redirect. Friction should be empty.
        self.assertEqual(self._friction_lines(), [])


class TestWarnMode(GuardHarness):
    """In warn mode, every detect branch must call _write_hook_friction
    (R2-C5 falsifiable soak)."""

    def test_echo_redirect_logs_friction(self):
        rc, err = self._invoke("echo '{}' > .runs/q-dimensions.json")
        self.assertEqual(rc, 0, err)
        lines = self._friction_lines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("[warn-mode]", lines[0]["reason"])

    def test_python_open_logs_friction(self):
        rc, err = self._invoke(
            "python3 -c \"open('.runs/q-dimensions.json', 'w').write('{}')\""
        )
        self.assertEqual(rc, 0, err)
        lines = self._friction_lines()
        self.assertEqual(len(lines), 1, lines)

    def test_cat_heredoc_logs_friction(self):
        # cat > target <<EOF — bound chain-write check should fire.
        rc, err = self._invoke(
            "cat > .runs/q-dimensions.json <<EOF\n{}\nEOF"
        )
        self.assertEqual(rc, 0, err)
        lines = self._friction_lines()
        self.assertEqual(len(lines), 1, lines)

    def test_tee_logs_friction(self):
        rc, err = self._invoke("echo '{}' | tee .runs/q-dimensions.json")
        self.assertEqual(rc, 0, err)
        lines = self._friction_lines()
        self.assertEqual(len(lines), 1, lines)


class TestChainBoundCheck(GuardHarness):
    def test_chain_after_allowed_writer_logs_friction(self):
        # Chain-bound check fires BEFORE allow-list short-circuit.
        cmd = (
            "bash .claude/scripts/lib/write-gate-artifact.sh "
            "--path .runs/q-dimensions.json --payload '{}' --skill audit "
            "&& echo forge > .runs/q-dimensions.json"
        )
        rc, err = self._invoke(cmd)
        self.assertEqual(rc, 0, err)  # warn mode
        lines = self._friction_lines()
        self.assertEqual(len(lines), 1, lines)


class TestNonManifestPath(GuardHarness):
    def test_redirect_to_non_manifest_path_allowed(self):
        # .runs/scratch.json is NOT in the canonical manifest.
        rc, err = self._invoke("echo '{}' > .runs/scratch.json")
        self.assertEqual(rc, 0)
        self.assertEqual(self._friction_lines(), [])


class TestDenyMode(GuardHarness):
    """Confirm flip from warn → deny works (PR-F flips the env var
    default from 'warn' to 'deny')."""

    def test_echo_redirect_denied(self):
        rc, err = self._invoke(
            "echo '{}' > .runs/q-dimensions.json", mode="deny"
        )
        self.assertNotEqual(rc, 0, err)
        self.assertIn("Gate-artifact bash write guard", err)

    def test_python_open_denied(self):
        rc, err = self._invoke(
            "python3 -c \"open('.runs/q-dimensions.json', 'w').write('{}')\"",
            mode="deny",
        )
        self.assertNotEqual(rc, 0, err)


if __name__ == "__main__":
    unittest.main()
