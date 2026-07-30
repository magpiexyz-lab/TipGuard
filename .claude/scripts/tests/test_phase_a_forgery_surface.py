#!/usr/bin/env python3
"""test_phase_a_forgery_surface — falsifiable evasion catalogue for EARC slice 3.

Each bypass vector must be DENIED by bootstrap-phase-a-write-guard.sh in
deny mode. Vectors mirror the threat model documented in #1182's lead-shell
bypass: python -c, heredoc, sed -i, perl -i, cat redirect, tee redirect,
chained writes, variable indirection, pathlib write_text, etc.

This is the falsifiable acceptance criterion for slice 4's WARN->DENY flip:
when these vectors all reliably DENY, the soak window can be ended safely.

Sibling pattern: test_agent_trace_write_guard.py (existing, validates
agent-trace-write-guard.sh's 4-layer evasion catalogue).
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
HOOK = ROOT / ".claude/hooks/bootstrap-phase-a-write-guard.sh"


def _hook_run(command: str, mode: str = "deny") -> subprocess.CompletedProcess:
    """Run the hook with the given Bash command in the PreToolUse payload.

    Returns the completed process; rc=2 means deny, rc=0 means allow.
    """
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    env = {**os.environ, "BOOTSTRAP_PHASE_A_GUARD_MODE": mode}
    return subprocess.run(
        ["bash", str(HOOK)],
        input=payload,
        env=env,
        capture_output=True,
        text=True,
    )


class TestPhaseAForgerySurface(unittest.TestCase):
    """Each documented bypass vector must DENY in deny mode."""

    def setUp(self):
        # The hook sources lib.sh; lib.sh expects to find lib-core.sh as a
        # sibling. We don't need any worktree setup beyond what the repo
        # provides — the hook reads the COMMAND payload, not the filesystem.
        pass

    # -- Layer (a): chain delimiters ---------------------------------------

    def test_simple_redirect_denied(self):
        r = _hook_run("echo 'x' > src/app/layout.tsx")
        self.assertEqual(r.returncode, 2, msg=r.stderr)

    def test_chained_redirect_denied(self):
        r = _hook_run("true && echo 'x' > src/app/not-found.tsx")
        self.assertEqual(r.returncode, 2, msg=r.stderr)

    def test_appended_redirect_denied(self):
        r = _hook_run("echo 'x' >> src/app/error.tsx")
        self.assertEqual(r.returncode, 2, msg=r.stderr)

    def test_pipe_chain_redirect_denied(self):
        r = _hook_run("ls /tmp | grep foo; echo 'x' > src/app/globals.css")
        self.assertEqual(r.returncode, 2, msg=r.stderr)

    # -- Layer (c): Python literal open() ----------------------------------

    def test_python_open_w_denied(self):
        r = _hook_run("python3 -c \"open('src/app/layout.tsx', 'w').write('x')\"")
        self.assertEqual(r.returncode, 2, msg=r.stderr)

    def test_python_open_a_denied(self):
        r = _hook_run("python3 -c \"open('src/app/error.tsx', 'a').write('x')\"")
        self.assertEqual(r.returncode, 2, msg=r.stderr)

    def test_python_pathlib_write_text_denied(self):
        r = _hook_run(
            "python3 -c \"import pathlib; pathlib.Path('src/app/layout.tsx').write_text('x')\""
        )
        self.assertEqual(r.returncode, 2, msg=r.stderr)

    def test_python_pathlib_write_bytes_denied(self):
        r = _hook_run(
            "python3 -c \"import pathlib; pathlib.Path('src/app/error.tsx').write_bytes(b'x')\""
        )
        self.assertEqual(r.returncode, 2, msg=r.stderr)

    # -- Layer (d): variable indirection -----------------------------------

    def test_python_variable_indirection_denied(self):
        r = _hook_run(
            "python3 -c \"f='src/app/layout.tsx'; open(f, 'w').write('x')\""
        )
        self.assertEqual(r.returncode, 2, msg=r.stderr)

    # -- In-place editors --------------------------------------------------

    def test_sed_inplace_denied(self):
        r = _hook_run("sed -i 's/old/new/' src/app/layout.tsx")
        self.assertEqual(r.returncode, 2, msg=r.stderr)

    def test_perl_inplace_denied(self):
        r = _hook_run("perl -i -pe 's/x/y/' src/app/error.tsx")
        self.assertEqual(r.returncode, 2, msg=r.stderr)

    # -- File copy/move ----------------------------------------------------

    def test_cat_heredoc_denied(self):
        # Heredoc is a chained write target.
        r = _hook_run("cat > src/app/layout.tsx << 'EOF'\nbody\nEOF")
        self.assertEqual(r.returncode, 2, msg=r.stderr)

    def test_tee_redirect_denied(self):
        r = _hook_run("echo 'x' | tee src/app/globals.css")
        self.assertEqual(r.returncode, 2, msg=r.stderr)

    def test_cp_to_phase_a_denied(self):
        r = _hook_run("cp /tmp/new-layout.tsx src/app/layout.tsx")
        self.assertEqual(r.returncode, 2, msg=r.stderr)

    def test_mv_to_phase_a_denied(self):
        r = _hook_run("mv /tmp/new-layout.tsx src/app/layout.tsx")
        self.assertEqual(r.returncode, 2, msg=r.stderr)

    # -- Allowlist short-circuit -------------------------------------------

    def test_authorized_writer_short_circuits(self):
        cmd = (
            "bash .claude/scripts/write-phase-a-repair.sh "
            "--target-file src/app/layout.tsx --evidence-source .runs/build-result.json "
            "--symptom 'x' --lead-attestation 'y'"
        )
        r = _hook_run(cmd)
        self.assertEqual(r.returncode, 0, msg=r.stderr)

    def test_authorized_writer_with_phase_a_path_but_no_target_flag_denied(self):
        """If the command writes to a Phase A path via raw redirect even
        though it mentions write-phase-a-repair.sh, deny — the allowlist
        only short-circuits when --target-file is paired correctly."""
        cmd = (
            "bash .claude/scripts/write-phase-a-repair.sh > src/app/layout.tsx"
        )
        r = _hook_run(cmd)
        self.assertEqual(r.returncode, 2, msg=r.stderr)

    # -- Read-only operations should NOT be flagged -------------------------

    def test_read_phase_a_allowed(self):
        r = _hook_run("cat src/app/layout.tsx")
        self.assertEqual(r.returncode, 0)

    def test_grep_phase_a_allowed(self):
        r = _hook_run("grep -n 'next/font' src/app/layout.tsx")
        self.assertEqual(r.returncode, 0)

    def test_unrelated_command_allowed(self):
        r = _hook_run("ls /tmp")
        self.assertEqual(r.returncode, 0)

    def test_writes_to_other_paths_allowed(self):
        r = _hook_run("echo 'x' > src/lib/utils.ts")
        self.assertEqual(r.returncode, 0)

    # -- False-positive guards ---------------------------------------------
    # Legitimate commands that mention Phase A paths but do NOT write to
    # them must NOT be denied. These cases justify flipping MODE=deny:
    # if any of them fail, real-world workflows would break.

    def test_git_checkout_phase_a_allowed(self):
        """git checkout <phase-a> — no write operator; reverts via git."""
        r = _hook_run("git checkout src/app/layout.tsx")
        self.assertEqual(r.returncode, 0, msg=r.stderr)

    def test_git_status_with_phase_a_path_allowed(self):
        r = _hook_run("git status -- src/app/layout.tsx")
        self.assertEqual(r.returncode, 0, msg=r.stderr)

    def test_git_diff_phase_a_allowed(self):
        r = _hook_run("git diff src/app/layout.tsx")
        self.assertEqual(r.returncode, 0, msg=r.stderr)

    def test_echo_phase_a_path_into_other_file_allowed(self):
        """Writing the Phase A path AS A STRING into a non-Phase-A file."""
        r = _hook_run("echo 'src/app/layout.tsx' > /tmp/audit.log")
        self.assertEqual(r.returncode, 0, msg=r.stderr)

    def test_find_named_after_phase_a_allowed(self):
        r = _hook_run("find . -name layout.tsx -type f")
        self.assertEqual(r.returncode, 0, msg=r.stderr)

    def test_wc_phase_a_allowed(self):
        r = _hook_run("wc -l src/app/layout.tsx")
        self.assertEqual(r.returncode, 0, msg=r.stderr)

    def test_stat_phase_a_allowed(self):
        r = _hook_run("stat src/app/error.tsx")
        self.assertEqual(r.returncode, 0, msg=r.stderr)

    def test_diff_two_phase_a_files_allowed(self):
        r = _hook_run("diff src/app/layout.tsx src/app/layout.tsx.bak")
        self.assertEqual(r.returncode, 0, msg=r.stderr)

    def test_commenting_about_phase_a_in_pipe_allowed(self):
        """A pipe that mentions a Phase A path in a string but writes elsewhere."""
        r = _hook_run("echo 'edited src/app/layout.tsx today' | tee -a /tmp/changes.log")
        self.assertEqual(r.returncode, 0, msg=r.stderr)

    def test_python_read_phase_a_allowed(self):
        """Read-only python access to a Phase A path."""
        r = _hook_run("python3 -c \"print(open('src/app/layout.tsx').read())\"")
        self.assertEqual(r.returncode, 0, msg=r.stderr)

    def test_pathlib_read_text_allowed(self):
        r = _hook_run(
            "python3 -c \"import pathlib; pathlib.Path('src/app/layout.tsx').read_text()\""
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)

    def test_grep_then_unrelated_write_allowed(self):
        """grep on Phase A then write to a non-Phase-A file — chain split
        must not falsely flag the second segment because of the first
        segment's Phase A reference."""
        r = _hook_run("grep next src/app/layout.tsx > /tmp/found.txt")
        self.assertEqual(r.returncode, 0, msg=r.stderr)

    # -- Issue #1298: heredoc-body false positive class -------------------

    def test_1298_heredoc_body_mentions_phase_a_path_allows(self):
        """#1298: prose mentioning a Phase A path inside a heredoc body must
        NOT trigger the bound-redirect — the body is data, not shell."""
        cmd = (
            "cat > /tmp/r.txt << 'EOF'\n"
            "Doc on src/app/layout.tsx repair: example shows cat > src/app/layout.tsx\n"
            "EOF"
        )
        r = _hook_run(cmd)
        self.assertEqual(r.returncode, 0, msg=r.stderr)

    def test_1298_chained_heredoc_then_real_phase_a_write_denies(self):
        """#1298 r1-c1: trailing real write to Phase A must still deny."""
        cmd = (
            "cat << 'EOF'\n"
            "harmless body\n"
            "EOF\n"
            "echo {} > src/app/layout.tsx"
        )
        r = _hook_run(cmd)
        self.assertEqual(r.returncode, 2, msg=r.stderr)

    def test_1298_python_heredoc_fed_open_phase_a_still_denies(self):
        """#1298 r1-c2: heredoc-fed python open() on Phase A must still deny."""
        cmd = (
            "python3 << 'PY'\n"
            "open('src/app/layout.tsx', 'w').write('forge')\n"
            "PY"
        )
        r = _hook_run(cmd)
        self.assertEqual(r.returncode, 2, msg=r.stderr)

    # -- WARN mode: emits stderr but exits 0 -------------------------------

    def test_warn_mode_does_not_deny(self):
        r = _hook_run(
            "echo 'x' > src/app/layout.tsx",
            mode="warn",
        )
        self.assertEqual(r.returncode, 0)
        self.assertIn("WARN", r.stderr)


class TestPhaseAGateAttestationAllow(unittest.TestCase):
    """Verify bootstrap/gates/write.sh ALSO-ALLOWs when a fresh, validated
    attestation matches."""

    def setUp(self):
        self.td = Path(tempfile.mkdtemp(prefix="test_phase_a_gate_"))
        # Bootstrap the gate-verdicts to satisfy the Phase B detection: BG1
        # PASS, no BG2, phase-a-sentinel present.
        (self.td / ".runs/gate-verdicts").mkdir(parents=True)
        json.dump({"verdict": "PASS"}, (self.td / ".runs/gate-verdicts/bg1.json").open("w"))
        json.dump(
            {"phase_a_complete": True, "build_passing": True},
            (self.td / ".runs/gate-verdicts/phase-a-sentinel.json").open("w"),
        )
        # Copy the gate + the entire hooks/ directory (lib.sh transitively
        # sources lib-state.sh, lib-core.sh, lib-paths.sh, etc.).
        (self.td / ".claude/skills/bootstrap/gates").mkdir(parents=True)
        shutil.copy(
            ROOT / ".claude/skills/bootstrap/gates/write.sh",
            self.td / ".claude/skills/bootstrap/gates/write.sh",
        )
        shutil.copytree(ROOT / ".claude/hooks", self.td / ".claude/hooks")

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def _run_gate(self, file_path: str):
        # The gate's case pattern is `*/src/app/...`, so FILE_PATH must
        # have a leading directory component; we use the project_dir prefix
        # to mimic the absolute paths the hook receives at runtime.
        full_path = file_path if file_path.startswith("/") else f"{self.td}/{file_path}"
        env = {
            **os.environ,
            "FILE_PATH": full_path,
            "PROJECT_DIR": str(self.td),
            "CLAUDE_PROJECT_DIR": str(self.td),
        }
        return subprocess.run(
            ["bash", str(self.td / ".claude/skills/bootstrap/gates/write.sh")],
            env=env,
            capture_output=True,
            text=True,
        )

    def test_phase_a_file_denied_without_attestation(self):
        r = self._run_gate("src/app/layout.tsx")
        self.assertEqual(r.returncode, 2, msg=r.stderr)
        self.assertIn("Phase A file", r.stderr)

    def test_phase_a_file_allowed_with_fresh_attestation(self):
        att_dir = self.td / ".runs/phase-a-repair-attestations"
        att_dir.mkdir(parents=True)
        att_path = att_dir / "layout.tsx-2026-04-30T00-00-00Z.json"
        json.dump(
            {
                "target_file": "src/app/layout.tsx",
                "evidence_source": ".runs/build-result.json",
                "evidence_validated": True,
                "lead_attestation": "test",
                "symptom": "test",
                "timestamp": "2026-04-30T00:00:00Z",
            },
            att_path.open("w"),
        )
        # Note: file mtime is now (just written), well within the 5-min freshness.
        r = self._run_gate("src/app/layout.tsx")
        self.assertEqual(r.returncode, 0, msg=r.stderr)

    def test_attestation_with_evidence_validated_false_rejected(self):
        att_dir = self.td / ".runs/phase-a-repair-attestations"
        att_dir.mkdir(parents=True)
        att_path = att_dir / "layout.tsx-2026-04-30T00-00-00Z.json"
        json.dump(
            {
                "target_file": "src/app/layout.tsx",
                "evidence_validated": False,
                "lead_attestation": "test",
                "symptom": "test",
                "timestamp": "2026-04-30T00:00:00Z",
            },
            att_path.open("w"),
        )
        r = self._run_gate("src/app/layout.tsx")
        self.assertEqual(r.returncode, 2, msg=r.stderr)

    def test_stale_attestation_rejected(self):
        att_dir = self.td / ".runs/phase-a-repair-attestations"
        att_dir.mkdir(parents=True)
        att_path = att_dir / "layout.tsx-2026-04-30T00-00-00Z.json"
        json.dump(
            {
                "target_file": "src/app/layout.tsx",
                "evidence_validated": True,
                "lead_attestation": "test",
                "symptom": "test",
                "timestamp": "2026-04-30T00:00:00Z",
            },
            att_path.open("w"),
        )
        # Set mtime to 1 hour ago.
        old = 1700000000  # arbitrary, definitely > 5 min before now
        os.utime(att_path, (old, old))
        r = self._run_gate("src/app/layout.tsx")
        self.assertEqual(r.returncode, 2, msg=r.stderr)

    def test_attestation_for_different_file_does_not_open_gate(self):
        att_dir = self.td / ".runs/phase-a-repair-attestations"
        att_dir.mkdir(parents=True)
        att_path = att_dir / "layout.tsx-2026-04-30T00-00-00Z.json"
        json.dump(
            {
                "target_file": "src/app/layout.tsx",
                "evidence_validated": True,
                "lead_attestation": "test",
                "symptom": "test",
                "timestamp": "2026-04-30T00:00:00Z",
            },
            att_path.open("w"),
        )
        # Try to write to a DIFFERENT Phase A file — gate must still deny.
        r = self._run_gate("src/app/error.tsx")
        self.assertEqual(r.returncode, 2, msg=r.stderr)


class TestWritePhaseARepairPostCondition(unittest.TestCase):
    """Post-condition build verification: write-phase-a-repair.sh must run
    `npm run build` AFTER writing the repaired file, AND only stamp the
    attestation when build passes. If the build still fails after the repair,
    the script must revert the file and refuse to stamp the attestation —
    otherwise the gate ALSO-ALLOWs a still-broken state, just one layer
    removed from the original #1182 failure mode.
    """

    def setUp(self):
        self.td = Path(tempfile.mkdtemp(prefix="test_repair_postcond_"))
        # Bootstrap a tiny "project" with an npm-buildable app.
        subprocess.run(["git", "init", "-q", str(self.td)], check=True)
        subprocess.run(
            ["git", "-C", str(self.td), "config", "user.email", "t@t.com"], check=True
        )
        subprocess.run(["git", "-C", str(self.td), "config", "user.name", "t"], check=True)
        # Copy needed scripts + libs.
        for d in (
            ".claude/scripts/lib",
            ".claude/hooks",
            ".runs",
            "src/app",
        ):
            (self.td / d).mkdir(parents=True, exist_ok=True)
        shutil.copy(
            ROOT / ".claude/scripts/write-phase-a-repair.sh",
            self.td / ".claude/scripts/write-phase-a-repair.sh",
        )
        shutil.copy(
            ROOT / ".claude/scripts/write-agent-trace.sh",
            self.td / ".claude/scripts/write-agent-trace.sh",
        )
        shutil.copy(
            ROOT / ".claude/scripts/lib/validate_evidence.py",
            self.td / ".claude/scripts/lib/validate_evidence.py",
        )
        (self.td / ".claude/scripts/lib/__init__.py").write_text("")
        # lib-core + lib (write-agent-trace.sh sources lib).
        shutil.copytree(
            ROOT / ".claude/hooks", self.td / ".claude/hooks", dirs_exist_ok=True
        )
        # Stub package.json with a controlled `npm run build` script:
        # exit code is whatever we put in /tmp/test-build-rc-<td>.txt.
        rc_file = self.td / ".rc-control"
        rc_file.write_text("0")
        (self.td / "package.json").write_text(
            json.dumps(
                {
                    "name": "test-app",
                    "version": "0.0.0",
                    "scripts": {
                        "build": f"exit $(cat {rc_file})",
                    },
                }
            )
        )
        self.rc_file = rc_file
        # Existing layout.tsx (the "broken" state we'll repair).
        (self.td / "src/app/layout.tsx").write_text("/* broken layout */\n")
        subprocess.run(
            ["git", "-C", str(self.td), "add", "."], check=True, capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(self.td), "commit", "-q", "-m", "init"], check=True
        )
        # Failing build evidence (justifies the repair).
        json.dump({"exit_code": 1}, (self.td / ".runs/build-result.json").open("w"))
        # Active context the writer needs.
        json.dump(
            {"skill": "bootstrap", "run_id": "test-run", "completed": False},
            (self.td / ".runs/bootstrap-context.json").open("w"),
        )
        # spawn-log entry that write-agent-trace.sh expects (lead-fix doesn't
        # require one, but the writer still inspects the spawn log).
        (self.td / ".runs/agent-spawn-log.jsonl").write_text("")

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def _set_post_build_rc(self, rc: int):
        self.rc_file.write_text(str(rc))

    def _run_repair(self, content: str = "/* fixed layout */\n"):
        env = {
            **os.environ,
            "CLAUDE_PROJECT_DIR": str(self.td),
            "PATH": os.environ.get("PATH", ""),
        }
        return subprocess.run(
            [
                "bash",
                ".claude/scripts/write-phase-a-repair.sh",
                "--target-file",
                "src/app/layout.tsx",
                "--evidence-source",
                ".runs/build-result.json",
                "--symptom",
                "test symptom",
                "--lead-attestation",
                "test fix",
            ],
            cwd=str(self.td),
            input=content,
            env=env,
            capture_output=True,
            text=True,
        )

    def test_post_build_pass_stamps_attestation(self):
        """When the post-repair build passes, attestation is stamped with
        post_repair_build_passing:true and the file content is the new one."""
        self._set_post_build_rc(0)
        r = self._run_repair()
        self.assertEqual(r.returncode, 0, msg=f"stderr={r.stderr}")
        # Attestation written
        att_files = list(
            (self.td / ".runs/phase-a-repair-attestations").glob("layout.tsx-*.json")
        )
        self.assertEqual(len(att_files), 1, f"unexpected: {att_files}")
        att = json.load(att_files[0].open())
        self.assertEqual(att["post_repair_build_passing"], True)
        # File content is the new one (note: bash $(cat) strips trailing newline,
        # which printf '%s' preserves verbatim — so we expect no trailing \n)
        self.assertEqual(
            (self.td / "src/app/layout.tsx").read_text(),
            "/* fixed layout */",
        )

    def test_post_build_fail_reverts_and_rejects(self):
        """When the post-repair build still fails, the file is reverted and
        no attestation is written. This is the critical first-principles fix:
        without this, the gate could ALSO-ALLOW a still-broken state."""
        self._set_post_build_rc(1)  # post-build still failing
        r = self._run_repair()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("POST-repair build still failing", r.stderr)
        # File reverted to prior content
        self.assertEqual(
            (self.td / "src/app/layout.tsx").read_text(),
            "/* broken layout */\n",
        )
        # No attestation written
        att_dir = self.td / ".runs/phase-a-repair-attestations"
        if att_dir.exists():
            att_files = list(att_dir.glob("layout.tsx-*.json"))
            self.assertEqual(len(att_files), 0, f"unexpected: {att_files}")

    def test_skip_post_build_env_marks_attestation_skipped(self):
        """The escape hatch (test fixtures) writes 'skipped' explicitly."""
        # post-build would fail, but skip is set
        self._set_post_build_rc(1)
        env = {
            **os.environ,
            "CLAUDE_PROJECT_DIR": str(self.td),
            "WRITE_PHASE_A_REPAIR_SKIP_POST_BUILD": "1",
        }
        r = subprocess.run(
            [
                "bash",
                ".claude/scripts/write-phase-a-repair.sh",
                "--target-file",
                "src/app/layout.tsx",
                "--evidence-source",
                ".runs/build-result.json",
                "--symptom",
                "test symptom",
                "--lead-attestation",
                "test fix",
            ],
            cwd=str(self.td),
            input="/* fixed */\n",
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, msg=f"stderr={r.stderr}")
        att_files = list(
            (self.td / ".runs/phase-a-repair-attestations").glob("layout.tsx-*.json")
        )
        self.assertEqual(len(att_files), 1)
        att = json.load(att_files[0].open())
        # Skip marker — distinguishable from True
        self.assertEqual(att["post_repair_build_passing"], "skipped")

    def test_missing_required_flag_uses_correct_dash_form(self):
        """Bug fix #4: error message used --target_file (underscore), should
        be --target-file (dash). Verify the corrected form."""
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.td)}
        r = subprocess.run(
            [
                "bash",
                ".claude/scripts/write-phase-a-repair.sh",
                "--evidence-source",
                ".runs/build-result.json",
                "--symptom",
                "x",
                "--lead-attestation",
                "y",
            ],
            cwd=str(self.td),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(r.returncode, 0)
        # Correct dash form, not underscore
        self.assertIn("--target-file", r.stderr)
        self.assertNotIn("--target_file", r.stderr)


if __name__ == "__main__":
    unittest.main()
