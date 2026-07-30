#!/usr/bin/env python3
"""Behavioral tests for .claude/scripts/validate-behavior-pages.py.

Covers both modes (--all and --diff-vs-main), archetype gating, and the
legacy-hint UX path. All tests construct a temporary project skeleton with
experiment/experiment.yaml and invoke the validator as a subprocess.

Run via: python3 .claude/scripts/tests/test_validate_behavior_pages.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest


REAL_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
VALIDATOR = os.path.join(REAL_REPO, ".claude", "scripts", "validate-behavior-pages.py")


def _make_experiment(tmpdir, yaml_text):
    path = os.path.join(tmpdir, "experiment")
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "experiment.yaml"), "w") as f:
        f.write(yaml_text)


def _run(tmpdir, *args):
    return subprocess.run(
        [sys.executable, VALIDATOR, *args],
        capture_output=True,
        text=True,
        cwd=tmpdir,
    )


def _init_git_with_base(tmpdir, initial_yaml, branch_yaml=None, branch="feature/test"):
    """Init a git repo with main @ initial_yaml and optionally a branch with branch_yaml.

    Returns: (merge_base_sha, branch_head_sha) when branch_yaml provided, else (main_sha,).
    """
    env = os.environ.copy()
    env.update({
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    })

    def run(cmd, check=True):
        return subprocess.run(
            cmd, cwd=tmpdir, env=env, capture_output=True, text=True, check=check
        )

    run(["git", "init", "-q", "-b", "main"])
    _make_experiment(tmpdir, initial_yaml)
    run(["git", "add", "."])
    run(["git", "commit", "-q", "-m", "base"])
    main_sha = run(["git", "rev-parse", "HEAD"]).stdout.strip()

    if branch_yaml is not None:
        run(["git", "checkout", "-q", "-b", branch])
        _make_experiment(tmpdir, branch_yaml)
        run(["git", "add", "."])
        run(["git", "commit", "-q", "-m", "branch change"])
        head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
        return main_sha, head
    return (main_sha,)


class TestAllMode(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_all_behaviors_with_pages_passes(self):
        _make_experiment(self.tmpdir, textwrap.dedent("""
            type: web-app
            behaviors:
              - id: b1
                actor: user
                pages: [dashboard]
              - id: b2
                actor: user
                pages: [admin/quotes]
        """).strip())
        r = _run(self.tmpdir, "--all")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_actor_user_without_pages_fails_with_legacy_hint(self):
        _make_experiment(self.tmpdir, textwrap.dedent("""
            type: web-app
            behaviors:
              - id: b1
                actor: user
              - id: b2
                actor: user
                pages: [dashboard]
        """).strip())
        r = _run(self.tmpdir, "--all")
        self.assertEqual(r.returncode, 1)
        self.assertIn("b1", r.stderr)
        self.assertIn("HINT", r.stderr)
        self.assertIn("/upgrade", r.stderr)

    def test_actor_system_without_pages_passes(self):
        _make_experiment(self.tmpdir, textwrap.dedent("""
            type: web-app
            behaviors:
              - id: cron_job
                actor: cron
              - id: system_job
                actor: system
        """).strip())
        r = _run(self.tmpdir, "--all")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_service_archetype_skips(self):
        _make_experiment(self.tmpdir, textwrap.dedent("""
            type: service
            behaviors:
              - id: b1
                actor: user
        """).strip())
        r = _run(self.tmpdir, "--all")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_actor_absent_treated_as_user(self):
        """Default actor is 'user' — missing pages should fail."""
        _make_experiment(self.tmpdir, textwrap.dedent("""
            type: web-app
            behaviors:
              - id: b1
                given: "a user"
                when: "they click"
                then: "something"
        """).strip())
        r = _run(self.tmpdir, "--all")
        self.assertEqual(r.returncode, 1)
        self.assertIn("b1", r.stderr)

    def test_empty_pages_list_fails(self):
        _make_experiment(self.tmpdir, textwrap.dedent("""
            type: web-app
            behaviors:
              - id: b1
                actor: user
                pages: []
        """).strip())
        r = _run(self.tmpdir, "--all")
        self.assertEqual(r.returncode, 1)

    def test_missing_experiment_yaml_errors(self):
        r = _run(self.tmpdir, "--all")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not found", r.stderr)


class TestDiffVsMainMode(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_new_behavior_with_pages_passes(self):
        base = textwrap.dedent("""
            type: web-app
            behaviors:
              - id: b1
                actor: user
                pages: [dashboard]
        """).strip()
        branch = textwrap.dedent("""
            type: web-app
            behaviors:
              - id: b1
                actor: user
                pages: [dashboard]
              - id: b2
                actor: user
                pages: [admin]
        """).strip()
        _init_git_with_base(self.tmpdir, base, branch)
        r = _run(self.tmpdir, "--diff-vs-main")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_new_behavior_without_pages_fails_no_legacy_hint(self):
        base = textwrap.dedent("""
            type: web-app
            behaviors:
              - id: b1
                actor: user
                pages: [dashboard]
        """).strip()
        branch = textwrap.dedent("""
            type: web-app
            behaviors:
              - id: b1
                actor: user
                pages: [dashboard]
              - id: b2
                actor: user
        """).strip()
        _init_git_with_base(self.tmpdir, base, branch)
        r = _run(self.tmpdir, "--diff-vs-main")
        self.assertEqual(r.returncode, 1)
        self.assertIn("b2", r.stderr)
        self.assertNotIn("b1", r.stderr)
        self.assertNotIn("HINT", r.stderr)

    def test_legacy_behaviors_without_pages_do_not_block(self):
        """When existing behaviors lack pages AND branch doesn't modify them,
        diff-vs-main lets the unrelated change through."""
        base = textwrap.dedent("""
            type: web-app
            behaviors:
              - id: legacy1
                actor: user
              - id: legacy2
                actor: user
        """).strip()
        branch = textwrap.dedent("""
            type: web-app
            behaviors:
              - id: legacy1
                actor: user
              - id: legacy2
                actor: user
              - id: new_one
                actor: user
                pages: [admin]
        """).strip()
        _init_git_with_base(self.tmpdir, base, branch)
        r = _run(self.tmpdir, "--diff-vs-main")
        self.assertEqual(r.returncode, 0,
                         f"legacy behaviors should not block; stderr={r.stderr}")

    def test_modifying_legacy_behavior_fails(self):
        """Touching a legacy behavior that lacks pages brings it into the diff."""
        base = textwrap.dedent("""
            type: web-app
            behaviors:
              - id: legacy
                actor: user
                when: "old"
        """).strip()
        branch = textwrap.dedent("""
            type: web-app
            behaviors:
              - id: legacy
                actor: user
                when: "new"
        """).strip()
        _init_git_with_base(self.tmpdir, base, branch)
        r = _run(self.tmpdir, "--diff-vs-main")
        self.assertEqual(r.returncode, 1)
        self.assertIn("legacy", r.stderr)

    def test_unchanged_behaviors_pass(self):
        """If the diff is non-behavior changes, diff-vs-main passes even
        when legacy behaviors lack pages."""
        base = textwrap.dedent("""
            type: web-app
            name: original
            behaviors:
              - id: legacy
                actor: user
        """).strip()
        branch = textwrap.dedent("""
            type: web-app
            name: renamed
            behaviors:
              - id: legacy
                actor: user
        """).strip()
        _init_git_with_base(self.tmpdir, base, branch)
        r = _run(self.tmpdir, "--diff-vs-main")
        self.assertEqual(r.returncode, 0, r.stderr)


class TestCLIValidation(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        _make_experiment(self.tmpdir, "type: web-app\nbehaviors: []\n")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_both_modes_required_one(self):
        r = _run(self.tmpdir)
        self.assertEqual(r.returncode, 2)
        self.assertIn("exactly one", r.stderr)

    def test_both_modes_given_rejected(self):
        r = _run(self.tmpdir, "--all", "--diff-vs-main")
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
