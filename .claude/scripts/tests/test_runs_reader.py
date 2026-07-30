#!/usr/bin/env python3
"""test_runs_reader.py — unit tests for the read-side library introduced by #1437/#1417.

Covers:
- discover_current_run_id: 3-pass precedence (active / completed+recency / orphan), 48h staleness
- read_jsonl: scope=current-run (HC5 sentinel, HC2 legacy-row tolerance), scope=cross-run-by-design (registration enforcement)
- read_context_files: returns full list, no precedence collapse
- read_git_log: per-file granularity, max_per_file cap, non-git graceful
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
sys.path.insert(0, str(ROOT / ".claude/scripts/lib"))

from runs_reader import (  # noqa: E402
    Identity,
    ReadResult,
    STALENESS_HOURS,
    discover_current_run_id,
    read_context_files,
    read_git_log,
    read_jsonl,
)


def now_iso(offset_hours: float = 0) -> str:
    t = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=offset_hours)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def write_context(runs_dir: Path, name: str, **fields) -> None:
    """Write a .runs/<name>-context.json with sensible defaults; fields override."""
    base = {
        "skill": name,
        "run_id": f"{name}-{fields.get('run_id_suffix', 'x')}",
        "branch": fields.get("branch", "feat/test"),
        "timestamp": fields.get("timestamp", now_iso(-0.1)),
        "completed": fields.get("completed", False),
        "parent": fields.get("parent", None),
        "ancestors": fields.get("ancestors", []),
    }
    base.update({k: v for k, v in fields.items() if k not in ("run_id_suffix",)})
    (runs_dir / f"{name}-context.json").write_text(json.dumps(base))


def init_git_repo(path: Path, with_commits: int = 1) -> str:
    """Init a git repo, return HEAD commit ISO timestamp."""
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "commit.gpgsign", "false"], check=True)
    for i in range(with_commits):
        subprocess.run(
            ["git", "-C", str(path), "commit", "--allow-empty", "-q", "-m", f"c{i}"],
            check=True,
        )
    r = subprocess.run(
        ["git", "-C", str(path), "log", "-1", "--format=%cI"],
        capture_output=True, text=True, check=True,
    )
    return r.stdout.strip()


class DiscoverCurrentRunIDTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.runs = self.tmp / ".runs"
        self.runs.mkdir()
        init_git_repo(self.tmp)
        subprocess.run(["git", "-C", str(self.tmp), "checkout", "-q", "-b", "feat/test"], check=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_active_only_when_include_completed_false(self):
        """Caveat #1: with include_completed=False, completed contexts are NOT returned."""
        write_context(self.runs, "observe", completed=True, timestamp=now_iso(-0.5),
                       run_id_suffix="old")
        identity = discover_current_run_id(branch="feat/test", project_dir=self.tmp,
                                            include_completed=False)
        self.assertIsNone(identity)

    def test_active_preferred_over_completed(self):
        """Pass 1 wins: active context returned even when older completed exists."""
        write_context(self.runs, "observe", completed=True, timestamp=now_iso(-0.1),
                       run_id_suffix="old")
        write_context(self.runs, "change", completed=False, timestamp=now_iso(-0.5),
                       run_id_suffix="active")
        identity = discover_current_run_id(branch="feat/test", project_dir=self.tmp,
                                            include_completed=True)
        self.assertIsNotNone(identity)
        self.assertEqual(identity.skill, "change")

    def test_pass2_excludes_pre_head_commits(self):
        """Caveat #2: completed context with timestamp < HEAD commit time is rejected."""
        head_ts = datetime.datetime.now(datetime.timezone.utc)
        # Completed context written 30 min BEFORE the HEAD commit
        stale_ts = (head_ts - datetime.timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        write_context(self.runs, "observe", completed=True, timestamp=stale_ts,
                       run_id_suffix="stale")
        identity = discover_current_run_id(
            branch="feat/test", project_dir=self.tmp,
            include_completed=True, head_commit_timestamp=head_ts,
        )
        self.assertIsNone(identity)

    def test_pass2_includes_post_head_commits(self):
        """Completed context after HEAD commit is accepted by Pass 2."""
        head_ts = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
        ctx_ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        write_context(self.runs, "change", completed=True, timestamp=ctx_ts,
                       run_id_suffix="recent")
        identity = discover_current_run_id(
            branch="feat/test", project_dir=self.tmp,
            include_completed=True, head_commit_timestamp=head_ts,
        )
        self.assertIsNotNone(identity)
        self.assertEqual(identity.skill, "change")

    def test_head_commit_timestamp_auto_detect(self):
        """Caveat #3: when head_commit_timestamp=None and include_completed=True, auto-detect via git log -1."""
        # Repo has 1 commit; a completed context written AFTER HEAD should be returned via Pass 2
        ctx_ts = now_iso(0.1)  # 6 min in the future relative to HEAD (HEAD is "now")
        write_context(self.runs, "change", completed=True, timestamp=ctx_ts,
                       run_id_suffix="auto")
        identity = discover_current_run_id(
            branch="feat/test", project_dir=self.tmp,
            include_completed=True, head_commit_timestamp=None,  # auto-detect
        )
        self.assertIsNotNone(identity)
        self.assertEqual(identity.skill, "change")

    def test_head_commit_timestamp_explicit_overrides_auto(self):
        """Explicit head_commit_timestamp param overrides git auto-detect."""
        # Context timestamped now; explicit head=10h in future → context is BEFORE → rejected
        future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=10)
        write_context(self.runs, "change", completed=True, timestamp=now_iso(),
                       run_id_suffix="explicit")
        identity = discover_current_run_id(
            branch="feat/test", project_dir=self.tmp,
            include_completed=True, head_commit_timestamp=future,
        )
        self.assertIsNone(identity)

    def test_48h_staleness_cap(self):
        """Active contexts older than 48h are ignored."""
        old_ts = now_iso(-50)  # 50h old
        write_context(self.runs, "change", completed=False, timestamp=old_ts,
                       run_id_suffix="stale")
        identity = discover_current_run_id(branch="feat/test", project_dir=self.tmp)
        self.assertIsNone(identity)

    def test_no_runs_dir_returns_none(self):
        shutil.rmtree(self.runs)
        identity = discover_current_run_id(branch="feat/test", project_dir=self.tmp)
        self.assertIsNone(identity)

    def test_epilogue_context_excluded(self):
        # epilogue-context.json should be skipped
        (self.runs / "epilogue-context.json").write_text(json.dumps({
            "skill": "observe", "run_id": "epi", "branch": "feat/test",
            "timestamp": now_iso(), "completed": False,
        }))
        identity = discover_current_run_id(branch="feat/test", project_dir=self.tmp)
        self.assertIsNone(identity)


class ReadJsonlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.runs = self.tmp / ".runs"
        self.runs.mkdir()
        # Write a cross-run-channels.json so cross-run-by-design tests work
        patterns = self.tmp / ".claude/patterns"
        patterns.mkdir(parents=True)
        (patterns / "cross-run-channels.json").write_text(json.dumps({
            "channels": {
                "fix-ledger": {"paths": [".runs/fix-ledger.jsonl"]},
            }
        }))
        # Clear the module-level cache so per-test project_dir works
        import runs_reader
        runs_reader._CHANNELS_CACHE = None
        runs_reader._CHANNELS_CACHE_KEY = None

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        import runs_reader
        runs_reader._CHANNELS_CACHE = None
        runs_reader._CHANNELS_CACHE_KEY = None

    def _write_ledger(self, rows):
        path = self.runs / "fix-ledger.jsonl"
        with open(path, "w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        return path

    def test_scope_required_keyword_only(self):
        with self.assertRaises(TypeError):
            read_jsonl(".runs/fix-ledger.jsonl", "current-run")  # positional

    def test_unknown_scope_rejected(self):
        with self.assertRaises(ValueError) as cm:
            read_jsonl(".runs/fix-ledger.jsonl", scope="weird")
        self.assertIn("unknown scope", str(cm.exception))

    def test_current_run_no_run_id_returns_sentinel(self):
        """HC5: scope=current-run + current_run_id=None → empty + no_current_run=True."""
        self._write_ledger([{"run_id": "r1", "file": "a"}])
        r = read_jsonl(".runs/fix-ledger.jsonl", scope="current-run",
                        current_run_id=None, project_dir=self.tmp)
        self.assertTrue(r.no_current_run)
        self.assertEqual(r.rows, [])

    def test_current_run_filters_by_run_id(self):
        self._write_ledger([
            {"run_id": "r1", "file": "a"},
            {"run_id": "r2", "file": "b"},
            {"run_id": "r1", "file": "c"},
        ])
        r = read_jsonl(".runs/fix-ledger.jsonl", scope="current-run",
                        current_run_id="r1", project_dir=self.tmp)
        self.assertEqual(len(r.rows), 2)
        self.assertEqual(r.skipped_missing_runid, 0)

    def test_current_run_legacy_rows_skipped_and_counted(self):
        """HC2: rows missing run_id are skipped, counted in ReadResult.skipped_missing_runid."""
        self._write_ledger([
            {"run_id": "r1", "file": "a"},
            {"file": "b"},  # missing run_id
            {"run_id": None, "file": "c"},  # null run_id
            {"run_id": "r1", "file": "d"},
        ])
        r = read_jsonl(".runs/fix-ledger.jsonl", scope="current-run",
                        current_run_id="r1", project_dir=self.tmp)
        self.assertEqual(len(r.rows), 2)
        self.assertEqual(r.skipped_missing_runid, 2)

    def test_cross_run_requires_channel(self):
        self._write_ledger([{"run_id": "r1"}])
        with self.assertRaises(ValueError) as cm:
            read_jsonl(".runs/fix-ledger.jsonl", scope="cross-run-by-design",
                        project_dir=self.tmp)
        self.assertIn("cross_run_channel", str(cm.exception))

    def test_cross_run_unregistered_channel(self):
        self._write_ledger([{"run_id": "r1"}])
        with self.assertRaises(ValueError) as cm:
            read_jsonl(".runs/fix-ledger.jsonl", scope="cross-run-by-design",
                        cross_run_channel="bogus", project_dir=self.tmp)
        self.assertIn("not registered", str(cm.exception))

    def test_cross_run_path_not_in_channel(self):
        self._write_ledger([{"run_id": "r1"}])
        with self.assertRaises(ValueError) as cm:
            read_jsonl(".runs/other.jsonl", scope="cross-run-by-design",
                        cross_run_channel="fix-ledger", project_dir=self.tmp)
        self.assertIn("not declared", str(cm.exception))

    def test_cross_run_returns_all_rows(self):
        self._write_ledger([
            {"run_id": "r1", "file": "a"},
            {"run_id": "r2", "file": "b"},
        ])
        r = read_jsonl(".runs/fix-ledger.jsonl", scope="cross-run-by-design",
                        cross_run_channel="fix-ledger", project_dir=self.tmp)
        self.assertEqual(len(r.rows), 2)


class ReadContextFilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.runs = self.tmp / ".runs"
        self.runs.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_returns_list_sorted_by_timestamp_desc(self):
        write_context(self.runs, "a", timestamp=now_iso(-1), run_id_suffix="a")
        write_context(self.runs, "b", timestamp=now_iso(), run_id_suffix="b")
        write_context(self.runs, "c", timestamp=now_iso(-0.5), run_id_suffix="c")
        out = read_context_files(branch="feat/test", project_dir=self.tmp)
        self.assertEqual([d["skill"] for d in out], ["b", "c", "a"])

    def test_excludes_completed_by_default(self):
        write_context(self.runs, "a", completed=True)
        write_context(self.runs, "b", completed=False)
        out = read_context_files(branch="feat/test", project_dir=self.tmp)
        self.assertEqual([d["skill"] for d in out], ["b"])

    def test_include_completed_true_returns_all(self):
        write_context(self.runs, "a", completed=True)
        write_context(self.runs, "b", completed=False)
        out = read_context_files(branch="feat/test", project_dir=self.tmp,
                                  include_completed=True)
        self.assertEqual(sorted([d["skill"] for d in out]), ["a", "b"])

    def test_branch_filter_applied(self):
        write_context(self.runs, "a", branch="feat/x")
        write_context(self.runs, "b", branch="feat/y")
        out = read_context_files(branch="feat/x", project_dir=self.tmp)
        self.assertEqual([d["skill"] for d in out], ["a"])


class ReadGitLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_files_returns_empty(self):
        self.assertEqual(read_git_log([], project_dir=self.tmp), [])

    def test_non_git_dir_returns_empty(self):
        # tmp is not a git repo
        r = read_git_log(["app.py"], project_dir=self.tmp)
        self.assertEqual(r, [])

    def test_per_file_max_cap(self):
        """Caveat #8: each file gets at most max_per_file entries."""
        subprocess.run(["git", "-C", str(self.tmp), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(self.tmp), "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", str(self.tmp), "config", "user.name", "t"], check=True)
        subprocess.run(["git", "-C", str(self.tmp), "config", "commit.gpgsign", "false"], check=True)
        # Create 8 commits touching app.py
        for i in range(8):
            (self.tmp / "app.py").write_text(f"v{i}\n")
            subprocess.run(["git", "-C", str(self.tmp), "add", "app.py"], check=True)
            subprocess.run(["git", "-C", str(self.tmp), "commit", "-q", "-m", f"e{i}"], check=True)
        r = read_git_log(["app.py"], project_dir=self.tmp, max_per_file=5)
        self.assertEqual(len(r), 5)
        for entry in r:
            self.assertIn("sha", entry)
            self.assertIn("subject", entry)
            self.assertIn("timestamp", entry)
            self.assertEqual(entry["files"], ["app.py"])

    def test_per_file_granularity(self):
        """Each file gets its own bucket of commits."""
        subprocess.run(["git", "-C", str(self.tmp), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(self.tmp), "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", str(self.tmp), "config", "user.name", "t"], check=True)
        subprocess.run(["git", "-C", str(self.tmp), "config", "commit.gpgsign", "false"], check=True)
        for name in ["a.py", "b.py"]:
            for i in range(3):
                (self.tmp / name).write_text(f"v{i}")
                subprocess.run(["git", "-C", str(self.tmp), "add", name], check=True)
                subprocess.run(["git", "-C", str(self.tmp), "commit", "-q", "-m", f"{name}{i}"],
                                check=True)
        r = read_git_log(["a.py", "b.py"], project_dir=self.tmp, max_per_file=5)
        files_seen = {entry["files"][0] for entry in r}
        self.assertEqual(files_seen, {"a.py", "b.py"})


if __name__ == "__main__":
    unittest.main()
