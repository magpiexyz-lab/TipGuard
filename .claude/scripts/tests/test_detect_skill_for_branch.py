#!/usr/bin/env python3
"""test_detect_skill_for_branch.py — regression for issue #1347.

`_detect_skill_for_branch_impl` in `.claude/hooks/lib-state.sh` previously
picked newest-by-timestamp across `.runs/*-context.json`. When a parent
skill (e.g. /distribute) embeds /verify, both contexts are completed:true
at PR-creation time and the child's timestamp is newer. The PR-gate
dispatcher (`verify-pr-gate.sh:230`) then loaded `verify`'s `observation:`
config instead of the parent's, emitting a misleading error.

The fix:
  * Pass 1 — when include_completed="true", prefer top-level (parent:null)
    contexts so embedded children no longer shadow their parent.
  * Pass 2 — orphan-child fallback: if Pass 1 returns nothing, accept the
    most-recent context (any parent state) so legacy/orphan contexts still
    resolve.
  * Active variant (include_completed="false") is unchanged: it still
    prefers the most-recent active context, preserving child detection for
    in-flight embed (write-gate/commit-gate per-skill dispatch).

This test mirrors the harness in test_resolve_active_identity.py — same
shell-out pattern, same fixture writer, same setUp/tearDown.
"""
from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
LIB = ROOT / ".claude/hooks/lib.sh"


def now_iso(offset_hours: float = 0) -> str:
    t = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=offset_hours)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def call_detect(project_dir: Path, branch: str, include_completed: str) -> str:
    """Invoke _detect_skill_for_branch_impl via bash; return stdout-stripped skill.

    Must `cd` into project_dir BEFORE sourcing lib.sh: lib-core.sh overrides
    CLAUDE_PROJECT_DIR via `git rev-parse --show-toplevel`, so the working
    directory at source-time decides which `.runs/` the resolver scans.
    Mirrors the pattern in test_resolve_active_identity.py:37.
    """
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    cmd = [
        "bash", "-c",
        f'cd "{project_dir}" && '
        f'source "{LIB}" && _detect_skill_for_branch_impl "{branch}" "{include_completed}"',
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=10)
    return proc.stdout.strip()


class TestDetectSkillForBranch(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_dsfb_"))
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        # Back-date HEAD commit so all contexts written during the test
        # (timestamps near "now") fall AFTER HEAD. runs_reader.discover_current_run_id
        # Pass 2 now rejects completed contexts that predate the HEAD commit
        # (fix for #1417); without back-dating, fixture timestamps could
        # land before the just-created HEAD by a few seconds and be falsely
        # rejected.
        env = os.environ.copy()
        env["GIT_AUTHOR_DATE"] = "2020-01-01T00:00:00+00:00"
        env["GIT_COMMITTER_DATE"] = "2020-01-01T00:00:00+00:00"
        subprocess.run(["git", "-C", str(self.tmp), "commit", "-q", "--allow-empty",
                        "-m", "init"], check=True, env=env)
        self.runs = self.tmp / ".runs"
        self.runs.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_ctx(self, skill: str, *, completed=False, ts_offset=0, branch="main",
                   parent=None, ancestors=None, attributed_to=None,
                   omit_parent_field=False):
        name = f"{skill}-context.json"
        ts = now_iso(ts_offset)
        d = {
            "skill": skill,
            "branch": branch,
            "timestamp": ts,
            "run_id": f"{skill}-{ts}",
            "completed_states": [],
            "ancestors": ancestors or [],
            "attributed_to": attributed_to or skill,
            "completed": completed,
        }
        if not omit_parent_field:
            d["parent"] = parent
        (self.runs / name).write_text(json.dumps(d))
        return d

    def test_completed_embed_child_does_not_shadow_parent(self):
        """#1347 regression: completed parent + completed embedded child →
        PR-gate path (include_completed=true) returns the PARENT, not the
        newer-timestamp child."""
        branch = "chore/distribute"
        parent = self._write_ctx(
            "distribute", completed=True, ts_offset=-0.001, branch=branch,
            parent=None,
        )
        self._write_ctx(
            "verify", completed=True, ts_offset=0, branch=branch,
            parent={"skill": "distribute", "run_id": parent["run_id"]},
            ancestors=[{"skill": "distribute", "run_id": parent["run_id"]}],
        )
        result = call_detect(self.tmp, branch, "true")
        self.assertEqual(result, "distribute",
                         msg="completed embedded child must not shadow its parent on the PR-gate path")

    def test_active_skill_during_embed_returns_child(self):
        """Active variant (include_completed=false) must preserve child-
        preference during in-flight embed so write-gate / commit-gate
        dispatch to the actual writer's per-skill gates/{write,commit}.sh."""
        branch = "chore/distribute"
        parent = self._write_ctx(
            "distribute", completed=False, ts_offset=-0.001, branch=branch,
            parent=None,
        )
        self._write_ctx(
            "verify", completed=False, ts_offset=0, branch=branch,
            parent={"skill": "distribute", "run_id": parent["run_id"]},
            ancestors=[{"skill": "distribute", "run_id": parent["run_id"]}],
        )
        result = call_detect(self.tmp, branch, "false")
        self.assertEqual(result, "verify",
                         msg="active path during embed must return the child (write-gate dispatches to its per-skill gates)")

    def test_pre_field_schema_treated_as_top_level(self):
        """Pre-#941 contexts omit the parent field entirely; .get('parent')
        returns None → falsy → treated as top-level (backwards-compat)."""
        branch = "fix/legacy"
        self._write_ctx(
            "change", completed=True, ts_offset=0, branch=branch,
            omit_parent_field=True,
        )
        result = call_detect(self.tmp, branch, "true")
        self.assertEqual(result, "change",
                         msg="legacy context without parent field must be treated as top-level")

    def test_orphan_child_fallback(self):
        """Only a child context exists (parent context file absent — e.g.
        stale .runs/, partial worktree). Pass 2 fallback must return the
        child so the resolver does not silently return ''."""
        branch = "chore/distribute"
        self._write_ctx(
            "verify", completed=True, ts_offset=0, branch=branch,
            parent={"skill": "distribute", "run_id": "stale-d1"},
            ancestors=[{"skill": "distribute", "run_id": "stale-d1"}],
        )
        result = call_detect(self.tmp, branch, "true")
        self.assertEqual(result, "verify",
                         msg="orphan-child fallback must return the child when no top-level match exists")

    def test_mode_qualified_context_returns_qualified_name(self):
        # Mode-qualified runs write context files whose `skill` field is the
        # qualified key (iterate-cross) — detection must return it verbatim
        # (hooks then derive the BASE skill via resolve_skill_dir only for
        # the framework-manifest path; #1990 follow-up).
        self._write_ctx("iterate-cross", branch="main")
        result = call_detect(self.tmp, "main", "false")
        self.assertEqual(result, "iterate-cross")

    def test_no_match_returns_empty(self):
        """No contexts on the queried branch → empty return."""
        self._write_ctx("change", completed=True, ts_offset=0, branch="other-branch")
        result = call_detect(self.tmp, "main", "true")
        self.assertEqual(result, "",
                         msg="no matching context → empty result")


if __name__ == "__main__":
    unittest.main(verbosity=2)
