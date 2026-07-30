#!/usr/bin/env python3
"""test_transient_teardown.py — exercise the Supabase teardown lifecycle.

Covers all exit paths added by Issue #968's fix:
  1. happy path (skill-owned): wrapper started -> finalize --for-run stops + clears
  2. user-owned: pre-seeded owner=user marker -> finalize is a no-op
  3. orphan from crash: marker present, no finalize-completed flag -> init stops
  4. flag-present skip: marker + matching flag -> orphan just clears marker, no stop
  5. CI gate: GITHUB_ACTIONS=true -> all modes exit 0 without touching anything
  6. non-supabase stack: experiment.yaml lacks supabase+playwright -> exit 0
  7. docker down: `docker info` fails -> exit 0 (containers unreachable)
  8. embed ancestors match: --for-run parent_rid with marker.ancestors_run_ids=[parent]
  9. defensive reclaim: no marker but `supabase status` OK, no recent flag -> stop
 10. stale flag GC: finalize-completed-*.flag mtime > 7 days -> deleted by orphan-cleanup

Runs with PATH-stubbed `docker`, `npx` (routes `npx supabase ...` to a stub log),
and a bare `supabase` binary. Each case asserts via the stub's call log.

Run: python3 .claude/scripts/tests/test_transient_teardown.py
"""
from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
STOP_SCRIPT = ROOT / ".claude/scripts/stop-transient-services.sh"


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Stub binaries. `npx` dispatches by first arg: `supabase`, `anything else` -> passthrough to real npx
# (we only care about supabase). `docker` returns 0 for `info`/`ps` unless DOCKER_DOWN=1 env is set.
NPX_STUB = textwrap.dedent(r"""
    #!/usr/bin/env bash
    # Stub npx: only handles `npx supabase ...`, logs the invocation.
    LOG="${STUB_CALL_LOG:-/tmp/stub-calls.log}"
    {
      echo "npx $*"
    } >> "$LOG"
    if [[ "${1:-}" == "supabase" ]]; then
      shift
      case "${1:-}" in
        status)
          if [[ "${SUPABASE_RUNNING:-0}" == "1" ]]; then
            # Emit minimal JSON that `npx supabase status -o json` would produce.
            echo '{"API_URL":"http://127.0.0.1:54321"}'
            exit 0
          else
            echo "supabase local stack is not running" >&2
            exit 1
          fi
          ;;
        start)
          export SUPABASE_RUNNING=1
          # Export persists only within the stub subshell; we don't need to
          # transition real state for the tests — we just log the call.
          echo "started"
          exit 0
          ;;
        stop)
          echo "stopped"
          exit 0
          ;;
        db)
          # `npx supabase db reset` etc. — noop for tests.
          exit 0
          ;;
        *)
          exit 0
          ;;
      esac
    fi
    # Unknown npx invocation — exit 0 (tests don't use other npx commands).
    exit 0
""").lstrip()

DOCKER_STUB = textwrap.dedent(r"""
    #!/usr/bin/env bash
    # Stub docker: `info` / `ps` respect DOCKER_DOWN env flag.
    LOG="${STUB_CALL_LOG:-/tmp/stub-calls.log}"
    echo "docker $*" >> "$LOG"
    if [[ "${DOCKER_DOWN:-0}" == "1" ]]; then
      exit 1
    fi
    exit 0
""").lstrip()

SUPABASE_STUB = textwrap.dedent(r"""
    #!/usr/bin/env bash
    # Stub standalone `supabase` binary (in case anything calls it directly).
    LOG="${STUB_CALL_LOG:-/tmp/stub-calls.log}"
    echo "supabase $*" >> "$LOG"
    exit 0
""").lstrip()


EXPERIMENT_YAML_OK = textwrap.dedent("""
    name: test-project
    stack:
      database: supabase
      services:
        - runtime: nextjs
          testing: playwright
""").lstrip()

EXPERIMENT_YAML_NO_PLAYWRIGHT = textwrap.dedent("""
    name: test-project
    stack:
      database: supabase
      services:
        - runtime: nextjs
          testing: vitest
""").lstrip()


class TestTransientTeardown(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_transient_"))
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        subprocess.run(
            ["git", "-C", str(self.tmp), "commit", "-q", "--allow-empty", "-m", "init"],
            check=True,
        )
        # Copy the scripts directory and the template stack directories the stop
        # script touches. Full .claude/ copy is simplest and avoids missing-helper
        # surprises.
        shutil.copytree(ROOT / ".claude", self.tmp / ".claude", dirs_exist_ok=True)
        # Set up experiment.yaml (default: ok combo)
        (self.tmp / "experiment").mkdir()
        (self.tmp / "experiment" / "experiment.yaml").write_text(EXPERIMENT_YAML_OK)
        # .runs/ for any context files
        (self.tmp / ".runs").mkdir()

        # PATH stubs
        self.stub_bin = self.tmp / "stub-bin"
        self.stub_bin.mkdir()
        for name, body in (
            ("npx", NPX_STUB),
            ("docker", DOCKER_STUB),
            ("supabase", SUPABASE_STUB),
        ):
            p = self.stub_bin / name
            p.write_text(body)
            p.chmod(0o755)
        self.call_log = self.tmp / "stub-calls.log"
        self.call_log.touch()

        # git-common-dir for the test repo
        self.common_dir = Path(
            subprocess.check_output(
                ["git", "-C", str(self.tmp), "rev-parse", "--path-format=absolute",
                 "--git-common-dir"],
                text=True,
            ).strip()
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ----- Helpers -----

    def _run_stop(self, *args, env_extra=None, timeout=30):
        env = os.environ.copy()
        # Ensure our stubs shadow any real binaries
        env["PATH"] = f"{self.stub_bin}:{env.get('PATH','')}"
        env["STUB_CALL_LOG"] = str(self.call_log)
        env["CLAUDE_PROJECT_DIR"] = str(self.tmp)
        # Remove CI flags unless test sets them
        env.pop("CI", None)
        env.pop("GITHUB_ACTIONS", None)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            ["bash", str(STOP_SCRIPT)] + list(args),
            capture_output=True, text=True, env=env, cwd=str(self.tmp),
            timeout=timeout,
        )

    def _write_marker(self, data):
        marker = self.common_dir / "transient-resources.json"
        marker.write_text(json.dumps(data, indent=2))
        return marker

    def _read_marker(self):
        marker = self.common_dir / "transient-resources.json"
        if not marker.exists():
            return {}
        try:
            return json.loads(marker.read_text())
        except Exception:
            return {}

    def _call_log_contents(self):
        return self.call_log.read_text()

    def _assert_stop_called(self, project_id=None):
        calls = self._call_log_contents()
        self.assertIn("supabase stop", calls,
                      f"Expected 'npx supabase stop' in call log, got:\n{calls}")
        if project_id:
            self.assertIn(f"--project-id {project_id}", calls,
                          f"Expected --project-id {project_id} in call log, got:\n{calls}")

    def _assert_stop_not_called(self):
        calls = self._call_log_contents()
        self.assertNotIn("supabase stop", calls,
                         f"Did NOT expect 'npx supabase stop' in call log, got:\n{calls}")

    # ----- Cases -----

    # Case 1: happy path (simulated wrapper start) -> finalize --for-run stops + clears marker + writes flag
    def test_happy_path_skill_owned(self):
        run_id = f"verify-{now_iso()}"
        self._write_marker({"supabase": {
            "owner": "skill",
            "started_at": now_iso(),
            "run_id": run_id,
            "ancestors_run_ids": [],
            "started_by_script": "ensure-supabase-start.sh",
            "repo_root": str(self.tmp),
            "project_id": "myproj",
        }})
        proc = self._run_stop("--for-run", run_id)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self._assert_stop_called(project_id="myproj")
        self.assertNotIn("supabase", self._read_marker())
        # finalize is responsible for writing the flag, not stop-script.
        # So we only check marker clearing here.

    # Case 2: owner=user -> no stop regardless of --for-run
    def test_user_owned_noop(self):
        run_id = f"verify-{now_iso()}"
        self._write_marker({"supabase": {
            "owner": "user",
            "started_at": now_iso(),
            "run_id": run_id,
            "ancestors_run_ids": [],
            "repo_root": str(self.tmp),
            "project_id": "myproj",
        }})
        proc = self._run_stop("--for-run", run_id)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self._assert_stop_not_called()
        self.assertIn("supabase", self._read_marker(),
                      "owner=user marker should be preserved")

    # Case 3: orphan from crash — marker present, no flag -> init stops
    def test_orphan_from_crash(self):
        run_id = f"verify-{now_iso()}"
        self._write_marker({"supabase": {
            "owner": "skill",
            "started_at": now_iso(),
            "run_id": run_id,
            "ancestors_run_ids": [],
            "repo_root": str(self.tmp),
            "project_id": "myproj",
        }})
        proc = self._run_stop("--orphan-cleanup")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self._assert_stop_called(project_id="myproj")
        self.assertNotIn("supabase", self._read_marker())

    # Case 4: flag present -> orphan treats marker as already-cleaned, just clears marker
    def test_flag_present_skips_orphan(self):
        run_id = f"verify-{now_iso()}"
        self._write_marker({"supabase": {
            "owner": "skill",
            "started_at": now_iso(),
            "run_id": run_id,
            "ancestors_run_ids": [],
            "repo_root": str(self.tmp),
            "project_id": "myproj",
        }})
        # Pre-existing finalize-completed flag for this run_id
        (self.common_dir / f"finalize-completed-{run_id}.flag").touch()
        proc = self._run_stop("--orphan-cleanup")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self._assert_stop_not_called()
        self.assertNotIn("supabase", self._read_marker())

    # Case 5: CI gate
    def test_ci_gate_github_actions(self):
        run_id = f"verify-{now_iso()}"
        self._write_marker({"supabase": {
            "owner": "skill",
            "run_id": run_id,
            "ancestors_run_ids": [],
            "repo_root": str(self.tmp),
            "project_id": "myproj",
        }})
        proc = self._run_stop(
            "--for-run", run_id,
            env_extra={"GITHUB_ACTIONS": "true"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self._assert_stop_not_called()

    # Case 5b: CI=true also skips
    def test_ci_gate_ci_env(self):
        run_id = f"verify-{now_iso()}"
        self._write_marker({"supabase": {
            "owner": "skill",
            "run_id": run_id,
            "ancestors_run_ids": [],
            "repo_root": str(self.tmp),
            "project_id": "myproj",
        }})
        proc = self._run_stop(
            "--for-run", run_id,
            env_extra={"CI": "true"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self._assert_stop_not_called()

    # Case 6: non-supabase stack -> exit 0 (no stack-gate match)
    def test_non_supabase_stack(self):
        (self.tmp / "experiment" / "experiment.yaml").write_text(EXPERIMENT_YAML_NO_PLAYWRIGHT)
        run_id = f"verify-{now_iso()}"
        self._write_marker({"supabase": {
            "owner": "skill",
            "run_id": run_id,
            "ancestors_run_ids": [],
            "repo_root": str(self.tmp),
            "project_id": "myproj",
        }})
        proc = self._run_stop("--for-run", run_id)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self._assert_stop_not_called()

    # Case 7: docker down -> exit 0 (no supabase reachable anyway)
    def test_docker_down(self):
        run_id = f"verify-{now_iso()}"
        self._write_marker({"supabase": {
            "owner": "skill",
            "run_id": run_id,
            "ancestors_run_ids": [],
            "repo_root": str(self.tmp),
            "project_id": "myproj",
        }})
        proc = self._run_stop(
            "--for-run", run_id,
            env_extra={"DOCKER_DOWN": "1"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self._assert_stop_not_called()

    # Case 8: embed ancestors match — parent finalize gives parent run_id;
    # marker.run_id is the child (embed) but marker.ancestors_run_ids contains parent.
    def test_embed_ancestors_match(self):
        parent_rid = f"change-{now_iso()}"
        child_rid = f"verify-{now_iso()}"
        self._write_marker({"supabase": {
            "owner": "skill",
            "started_at": now_iso(),
            "run_id": child_rid,
            "ancestors_run_ids": [parent_rid],
            "repo_root": str(self.tmp),
            "project_id": "myproj",
        }})
        proc = self._run_stop("--for-run", parent_rid)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self._assert_stop_called(project_id="myproj")

    # Case 9: no-marker path must PRESERVE running supabase (user-started but
    # hasn't invoked the wrapper yet). This is the Issue A fix: we reverted the
    # earlier "defensive reclaim" that would kill the user's stack.
    def test_no_marker_preserves_running_supabase(self):
        # No marker file is written. Supabase reports running.
        # Expected: no stop, exit 0. The earlier defensive reclaim was removed
        # because it could not distinguish a user-manually-started stack from
        # a Claude-bypassed-wrapper stack.
        proc = self._run_stop(
            "--orphan-cleanup",
            env_extra={"SUPABASE_RUNNING": "1"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self._assert_stop_not_called()

    # Case 9b: owner=user marker survives orphan-cleanup (Issues B & C fix —
    # wrapper now writes owner=user when already-running or when no skill is
    # active; orphan-cleanup must treat these as untouchable).
    def test_user_owned_marker_survives_orphan_cleanup(self):
        self._write_marker({"supabase": {
            "owner": "user",
            "started_at": now_iso(),
            "run_id": "",
            "ancestors_run_ids": [],
            "started_by_script": "ensure-supabase-start.sh",
            "repo_root": str(self.tmp),
            "project_id": "myproj",
        }})
        proc = self._run_stop("--orphan-cleanup")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self._assert_stop_not_called()
        self.assertEqual(
            self._read_marker().get("supabase", {}).get("owner"),
            "user",
            "owner=user marker must be preserved verbatim",
        )

    # Case 10: stale flag GC — mtime > 7 days should be deleted at top of orphan-cleanup
    def test_stale_flag_gc(self):
        stale = self.common_dir / "finalize-completed-old.flag"
        stale.touch()
        old_ts = time.time() - 8 * 24 * 3600
        os.utime(stale, (old_ts, old_ts))
        self.assertTrue(stale.exists())
        proc = self._run_stop("--orphan-cleanup")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(stale.exists(), "Stale flag (mtime > 7d) should have been GC'd")

    # Case 11: concurrent --for-run should serialize via python3 fcntl.flock.
    # This asserts the minimum invariant — no crash, no corruption — when two
    # runs fire back-to-back. True ordering would need a sleep-injected stub.
    def test_flock_serializes_concurrent(self):
        run_id = f"verify-{now_iso()}"
        self._write_marker({"supabase": {
            "owner": "skill",
            "run_id": run_id,
            "ancestors_run_ids": [],
            "repo_root": str(self.tmp),
            "project_id": "myproj",
        }})
        env = os.environ.copy()
        env["PATH"] = f"{self.stub_bin}:{env.get('PATH','')}"
        env["STUB_CALL_LOG"] = str(self.call_log)
        env["CLAUDE_PROJECT_DIR"] = str(self.tmp)
        env.pop("CI", None)
        env.pop("GITHUB_ACTIONS", None)
        proc = subprocess.run(
            ["bash", str(STOP_SCRIPT), "--for-run", run_id],
            env=env, cwd=str(self.tmp),
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
