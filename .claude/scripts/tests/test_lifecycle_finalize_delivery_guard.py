#!/usr/bin/env python3
"""test_lifecycle_finalize_delivery_guard.py — integration recurrence guard for
issue #1990: lifecycle-finalize.sh must never commit on the default branch.

Runs the REAL lifecycle-finalize.sh (with the real lifecycle-lib.sh and
lib/delivery-branch-guard.sh) inside a throwaway repo that reproduces the
incident fixture: the analysis-only skill iterate-cross invoked with its
mode-qualified SKILL_KEY, delivery artifacts present, HEAD on main.

Run: python3 .claude/scripts/tests/test_lifecycle_finalize_delivery_guard.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FINALIZE = ROOT / ".claude/scripts/lifecycle-finalize.sh"
LIB = ROOT / ".claude/scripts/lifecycle-lib.sh"
GUARD = ROOT / ".claude/scripts/lib/delivery-branch-guard.sh"

# Scripts finalize may invoke that are irrelevant to the delivery contract —
# stubbed to exit 0 in the fixture tree.
STUB_SCRIPTS = [
    ".claude/scripts/stop-transient-services.sh",
    ".claude/scripts/check-init-context-callers.sh",
    ".claude/scripts/scan-template-edits.sh",
    ".claude/scripts/check-observation-artifacts.sh",
    ".claude/scripts/update-context-branch.sh",
    ".claude/scripts/verify-linter.sh",
    ".claude/scripts/tests/no-pii-in-fakedoor-track-call.sh",
]
STUB_PY = [
    ".claude/scripts/check-worktree-boundary-hook-registered.py",
    ".claude/scripts/check-worktree-ownership-pattern.py",
    ".claude/scripts/write-fix-ledger.py",
    ".claude/scripts/render-fix-log.py",
    ".claude/scripts/aggregate-hook-friction.py",
]


def _git(cwd, *args, check=True):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=check, capture_output=True, text=True
    )


class FinalizeFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_lf_dg_"))
        self.origin = self.tmp / "origin.git"
        self.work = self.tmp / "work"
        subprocess.run(["git", "init", "--bare", str(self.origin)],
                       check=True, capture_output=True)
        self.work.mkdir()
        _git(self.work, "init", "-b", "main")
        _git(self.work, "config", "user.email", "test@example.com")
        _git(self.work, "config", "user.name", "test")

        # Real scripts under test.
        scripts = self.work / ".claude" / "scripts"
        (scripts / "lib").mkdir(parents=True)
        (scripts / "tests").mkdir(parents=True)
        shutil.copy(FINALIZE, scripts / "lifecycle-finalize.sh")
        shutil.copy(LIB, scripts / "lifecycle-lib.sh")
        shutil.copy(GUARD, scripts / "lib" / "delivery-branch-guard.sh")
        (scripts / "lib" / "in-worktree.sh").write_text(
            "#!/usr/bin/env bash\necho false\n"
        )
        for rel in STUB_SCRIPTS:
            p = self.work / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("#!/usr/bin/env bash\nexit 0\n")
        for rel in STUB_PY:
            p = self.work / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("#!/usr/bin/env python3\nimport sys; sys.exit(0)\n")
        for p in scripts.rglob("*.sh"):
            os.chmod(p, 0o755)

        # Skill definition: iterate is analysis-only with a cross mode.
        cmd_dir = self.work / ".claude" / "commands"
        cmd_dir.mkdir(parents=True)
        (cmd_dir / "iterate.md").write_text(
            "---\ndescription: test\ntype: analysis-only\n---\nbody\n"
        )
        (cmd_dir / "change.md").write_text(
            "---\ndescription: test\ntype: code-writing\n---\nbody\n"
        )
        skill_dir = self.work / ".claude" / "skills" / "iterate"
        skill_dir.mkdir(parents=True)
        (skill_dir / "skill.yaml").write_text("modes:\n  cross:\n    states: ['x0']\n")

        runs = self.work / ".runs"
        runs.mkdir()
        (runs / "iterate-lifecycle.json").write_text(json.dumps({
            "skill": "iterate", "active_mode": "cross",
            "modes": {"cross": {"states": ["x0"]}},
        }))
        (runs / "iterate-cross-context.json").write_text(json.dumps({
            "skill": "iterate-cross",
            "run_id": "iterate-cross-test",
            "branch": "main",
            "timestamp": "2026-07-29T00:00:00Z",
            "completed_states": ["x0"],
        }))

        # Tracked run-record files, committed then mutated (the incident shape).
        exp = self.work / "experiment"
        exp.mkdir()
        (exp / "mvp-decision-ledger.jsonl").write_text('{"mvp": "a"}\n')
        _git(self.work, "add", "-A")
        _git(self.work, "commit", "-m", "baseline")
        _git(self.work, "remote", "add", "origin", str(self.origin))
        _git(self.work, "push", "-u", "origin", "main")
        _git(self.work, "remote", "set-head", "origin", "main")
        (exp / "mvp-decision-ledger.jsonl").write_text(
            '{"mvp": "a"}\n{"mvp": "b"}\n'
        )
        self.main_sha = _git(self.work, "rev-parse", "origin/main").stdout.strip()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_finalize(self, skill, extra_path=None):
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(self.work)
        env["SKIP_COHERENCE_LINT"] = "1"
        if extra_path:
            env["PATH"] = f"{extra_path}:{env['PATH']}"
        return subprocess.run(
            ["bash", ".claude/scripts/lifecycle-finalize.sh", skill],
            cwd=self.work, capture_output=True, text=True, env=env,
        )

    def origin_main_sha(self):
        return _git(self.work, "rev-parse", "origin/main").stdout.strip()


class TestFinalizeDeliveryGuard(FinalizeFixture):
    def test_recurrence_guard_never_commits_on_main(self):
        (self.work / ".runs" / "commit-message.txt").write_text("Record run\n")
        r = self.run_finalize("iterate-cross")
        self.assertEqual(r.returncode, 0, f"stdout={r.stdout}\nstderr={r.stderr}")
        self.assertIn("DELIVERY=pushed", r.stdout)
        branch = _git(self.work, "branch", "--show-current").stdout.strip()
        self.assertRegex(branch, r"^chore/iterate-cross-delivery-")
        # origin/main untouched — the recurrence guard.
        self.assertEqual(self.origin_main_sha(), self.main_sha)
        # The chore branch exists on origin and carries the record commit.
        remote_heads = _git(self.work, "ls-remote", "--heads", "origin").stdout
        self.assertIn(branch, remote_heads)
        recheck = json.loads(
            (self.work / ".runs" / "verify-recheck.json").read_text()
        )
        self.assertEqual(recheck.get("delivery_status"), "pushed")

    def test_mode_qualified_key_resolves_analysis_only(self):
        (self.work / ".runs" / "commit-message.txt").write_text("Record run\n")
        r = self.run_finalize("iterate-cross")
        self.assertIn("deliberate record delivery", r.stderr)
        self.assertNotIn("skipped-analysis-only", r.stdout)

    def test_analysis_only_without_artifacts_still_skips(self):
        r = self.run_finalize("iterate-cross")
        self.assertEqual(r.returncode, 0, f"stdout={r.stdout}\nstderr={r.stderr}")
        self.assertIn("DELIVERY=skipped-analysis-only", r.stdout)
        self.assertEqual(
            _git(self.work, "branch", "--show-current").stdout.strip(), "main"
        )
        self.assertEqual(self.origin_main_sha(), self.main_sha)

    def test_code_writing_skill_on_feature_branch_unaffected(self):
        _git(self.work, "checkout", "-b", "feature/x")
        (self.work / ".runs" / "change-context.json").write_text(json.dumps({
            "skill": "change", "run_id": "change-test", "branch": "feature/x",
            "timestamp": "2026-07-29T00:00:00Z", "completed_states": [],
        }))
        (self.work / ".runs" / "commit-message.txt").write_text("Change\n")
        r = self.run_finalize("change")
        self.assertEqual(r.returncode, 0, f"stdout={r.stdout}\nstderr={r.stderr}")
        self.assertIn("DELIVERY=pushed", r.stdout)
        self.assertEqual(
            _git(self.work, "branch", "--show-current").stdout.strip(),
            "feature/x",
        )
        self.assertEqual(self.origin_main_sha(), self.main_sha)

    def test_pr_create_failure_degrades_not_aborts(self):
        (self.work / ".runs" / "commit-message.txt").write_text("Record run\n")
        (self.work / ".runs" / "pr-title.txt").write_text("Record PR\n")
        (self.work / ".runs" / "pr-body.md").write_text("body\n")
        fake_bin = self.tmp / "fakebin"
        fake_bin.mkdir()
        gh = fake_bin / "gh"
        gh.write_text(
            "#!/usr/bin/env bash\n"
            'echo "fake gh: $*" >&2\n'
            "exit 1\n"
        )
        os.chmod(gh, 0o755)
        r = self.run_finalize("iterate-cross", extra_path=str(fake_bin))
        self.assertEqual(r.returncode, 0, f"stdout={r.stdout}\nstderr={r.stderr}")
        self.assertIn("DELIVERY=pr-create-failed", r.stdout)
        # Steps 6/7 still ran: recheck artifact exists with the status.
        recheck = json.loads(
            (self.work / ".runs" / "verify-recheck.json").read_text()
        )
        self.assertEqual(recheck.get("delivery_status"), "pr-create-failed")
        self.assertEqual(self.origin_main_sha(), self.main_sha)


if __name__ == "__main__":
    sys.exit(unittest.main())
