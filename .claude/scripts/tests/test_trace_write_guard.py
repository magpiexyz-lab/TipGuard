#!/usr/bin/env python3
"""test_trace_write_guard.py — runtime guard on agent-spawn-log.jsonl writes.

Sibling test for `test_agent_trace_write_guard.py`. Exists because issue #1230
identified that `trace-write-guard.sh` was using an unbound co-occurrence
regex that false-positived on pure reads with `2>/dev/null`, gh chains with
`2>&1`, python source mentioning the path inside string literals, and grep
commands with the path as a literal pattern argument. The fix mirrors
agent-trace-write-guard.sh's bound-target awk design and tightens the path
anchor to require the canonical `.jsonl` extension. This test file pins the
contract:
  - reads of the spawn-log (any redirect form) must be ALLOWED
  - writes targeting the canonical spawn-log file must be DENIED
  - paths near-but-not-equal to canonical (no .jsonl) must be ALLOWED
  - the deferred class-level recurrence concern (issue #1236) is out of scope
    for this file — guard against the spawn-log instance only

Run: python3 .claude/scripts/tests/test_trace_write_guard.py
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
HOOK = ROOT / ".claude/hooks/trace-write-guard.sh"


class TestTraceWriteGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_twg_"))
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        shutil.copytree(ROOT / ".claude", self.tmp / ".claude", dirs_exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _invoke(self, command: str) -> tuple[int, str]:
        payload = json.dumps({
            "tool_name": "Bash",
            "tool_input": {"command": command},
        })
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(self.tmp)
        proc = subprocess.run(
            ["bash", str(HOOK)],
            input=payload,
            capture_output=True, text=True, env=env, timeout=10,
        )
        return proc.returncode, proc.stderr

    def _assert_allowed(self, cmd: str, msg: str = ""):
        rc, err = self._invoke(cmd)
        self.assertEqual(rc, 0, f"expected allow for {cmd!r}; stderr={err} {msg}")

    def _assert_denied(self, cmd: str, substr: str = ""):
        rc, err = self._invoke(cmd)
        self.assertNotEqual(rc, 0, f"expected deny for {cmd!r}")
        if substr:
            self.assertIn(substr, err, f"expected deny reason to mention {substr!r}; got {err}")

    # ---- Fast path ----

    def test_fast_path_no_mention(self):
        self._assert_allowed("ls .runs/", "fast-path: unrelated command")

    def test_fast_path_mentions_path_but_no_write(self):
        # Reading the spawn-log file is allowed
        self._assert_allowed("cat .runs/agent-spawn-log.jsonl",
                             "read of spawn-log")
        self._assert_allowed("ls .runs/", "list .runs/ does not match fast-path glob")

    # ---- fd-to-fd redirects must not false-positive ----

    def test_cat_with_stderr_to_stdout_allowed(self):
        # Pre-fix: 2>&1 was correctly stripped by NORM but the line-50 awk
        # then false-positived on co-occurrence. Post-fix: bound-target awk
        # only trips on writes to .jsonl.
        self._assert_allowed("cat .runs/agent-spawn-log.jsonl 2>&1",
                             "cat with 2>&1 is a read, not a write")

    def test_chained_read_with_stderr_redirect_allowed(self):
        # The exact pattern reported in the issue: gh chain ending in cat.
        self._assert_allowed(
            "gh issue list --state open 2>&1 ; cat .runs/agent-spawn-log.jsonl",
            "gh chain followed by read must pass")

    # ---- fd-to-FILE redirects must not false-positive on reads ----

    def test_cat_with_stderr_to_devnull_pipe_allowed(self):
        # Live-observed false-positive from the issue body: 2>/dev/null was
        # NOT stripped by the line-35 normalizer (which only strips fd-to-fd),
        # so `>` survived in the segment alongside the path mention. Post-fix:
        # bound-target awk requires the operator to be adjacent to a .jsonl
        # target — the /dev/null target is not a spawn-log target.
        self._assert_allowed(
            'cat .runs/agent-spawn-log.jsonl 2>/dev/null | python3 -c "import sys; print(sys.stdin.read())"',
            "cat with 2>/dev/null piped to python is a read")

    def test_multi_arg_cat_with_stderr_redirect_allowed(self):
        self._assert_allowed(
            "cat .runs/agent-spawn-log.jsonl /tmp/foo 2>/dev/null | wc -l",
            "multi-arg cat with stderr redirect is a read")

    # ---- Literal-string-in-pattern-argument cases (live false-positive
    # observed during round-1 critic session) ----

    def test_grep_with_path_as_literal_pattern_arg_allowed(self):
        # Pre-fix: grep with the path as a literal arg AND any other shell
        # token containing `>` / `&` would trip the unbound co-occurrence
        # check. Post-fix: no write operator is bound to a .jsonl target.
        self._assert_allowed(
            "grep -rn 'agent-spawn-log' .claude/hooks/lib.sh .claude/scripts/tests/run-all.sh",
            "grep with literal path arg is a read")

    def test_rg_with_path_as_literal_pattern_allowed(self):
        self._assert_allowed(
            "rg -l 'agent-spawn-log' .claude/",
            "rg with literal path arg is a read")

    def test_python_literal_mentioning_path_allowed(self):
        # Python source that prints the path string (no open call) — must allow.
        # The path appears inside a single-quoted Python string; the literal-path
        # check below requires the path AND `open(` AND mode 'w'/'a' — none of
        # which apply to a print.
        self._assert_allowed(
            'python3 -c "print(\\"reading agent-spawn-log.jsonl\\")"',
            "python print mentioning path is not a write")

    # ---- Bare-fd / GNU forms ----

    def test_csh_ampgt_into_spawn_log_still_denied(self):
        # `cmd >& file` is a GNU bash extension meaning `cmd > file 2>&1` — a
        # real file write that must still deny. The pass-2 NORM collapses this
        # to `> file` so the bound-target awk catches it.
        self._assert_denied(
            "echo {} >& .runs/agent-spawn-log.jsonl",
        )

    def test_fd3_to_fd2_allowed(self):
        # `3>&2` redirects an arbitrary fd, not a file write.
        self._assert_allowed("ls .runs/ 3>&2 ; cat .runs/agent-spawn-log.jsonl",
                             "3>&2 is fd-to-fd, not a file write")

    # ---- Tightened-anchor: paths without .jsonl extension must allow ----

    def test_redirect_into_similarly_named_file_without_jsonl_allowed(self):
        # Tightened path anchor: only the canonical spawn-log file is
        # protected. A write to /tmp/agent-spawn-log-debug (no .jsonl) is
        # not the hook-managed file and must be allowed.
        self._assert_allowed(
            "echo x > /tmp/agent-spawn-log-debug",
            "write to non-canonical path is allowed")

    def test_redirect_into_dot_jsonl_dot_bak_form_denied(self):
        # The tee/cp/mv/dd word-list arg-match denies any segment where the
        # path appears as an arg. A backup operation `cp foo.jsonl foo.jsonl.bak`
        # is intentionally denied — the canonical hook-managed file must not
        # be moved/copied without the gate.
        self._assert_denied(
            "cp .runs/agent-spawn-log.jsonl .runs/agent-spawn-log.jsonl.bak",
        )

    # ---- Denied: raw writes ----

    def test_raw_redirect_denied(self):
        self._assert_denied(
            "echo '{}' > .runs/agent-spawn-log.jsonl",
            "hook-managed",
        )

    def test_append_redirect_denied(self):
        self._assert_denied(
            "echo x >> .runs/agent-spawn-log.jsonl",
        )

    def test_cp_into_spawn_log_denied(self):
        self._assert_denied(
            "cp /tmp/x.json .runs/agent-spawn-log.jsonl",
        )

    def test_mv_into_spawn_log_denied(self):
        self._assert_denied(
            "mv /tmp/x.json .runs/agent-spawn-log.jsonl",
        )

    def test_tee_into_spawn_log_denied(self):
        self._assert_denied(
            "echo x | tee .runs/agent-spawn-log.jsonl",
        )

    def test_dd_into_spawn_log_denied(self):
        # `dd` is preserved in the post-fix write-marker set (sibling
        # agent-trace-write-guard.sh lacks it — see #1236).
        self._assert_denied(
            "dd if=/dev/null of=.runs/agent-spawn-log.jsonl",
        )

    def test_python_open_for_write_denied(self):
        self._assert_denied(
            "python3 -c \"open('.runs/agent-spawn-log.jsonl', 'w').write('{}')\"",
            "Python open-for-write",
        )

    def test_python_open_for_append_denied(self):
        self._assert_denied(
            "python3 -c \"open('.runs/agent-spawn-log.jsonl', 'a').write('{}')\"",
        )

    # ---- Chained writes ----

    def test_chained_write_after_innocent_cmd_denied(self):
        self._assert_denied(
            "ls .runs/ && echo {} > .runs/agent-spawn-log.jsonl",
        )

    def test_chained_write_before_innocent_cmd_denied(self):
        self._assert_denied(
            "echo {} > .runs/agent-spawn-log.jsonl ; ls .runs/",
        )

    # ---- Pattern obfuscation attempts ----

    def test_leading_spaces_denied(self):
        self._assert_denied(
            "   echo {} > .runs/agent-spawn-log.jsonl",
        )

    # ---- Variable-indirection ----

    def test_variable_indirection_double_quoted_denied(self):
        # `f='.runs/agent-spawn-log.jsonl'; open(f, 'w')` — the literal-path
        # regex above only catches `open('.runs/agent-spawn-log.jsonl', 'w')`,
        # so the indirection check closes the bypass.
        self._assert_denied(
            "python3 -c \"f='.runs/agent-spawn-log.jsonl'; open(f, 'w').write('{}')\"",
            "variable-indirection",
        )

    def test_variable_indirection_append_mode_denied(self):
        self._assert_denied(
            "python3 -c \"path='.runs/agent-spawn-log.jsonl'; open(path, 'a').write('x')\"",
            "variable-indirection",
        )

    def test_variable_indirection_with_json_dump_denied(self):
        self._assert_denied(
            "python3 -c \"import json; f='.runs/agent-spawn-log.jsonl'; d={}; json.dump(d, open(f, 'w'))\"",
            "variable-indirection",
        )

    def test_variable_indirection_with_modeb_suffix_denied(self):
        # Defense-in-depth: 'wb' / 'wb+' / 'a+' modes still write.
        self._assert_denied(
            "python3 -c \"f='.runs/agent-spawn-log.jsonl'; open(f, 'wb').write(b'{}')\"",
            "variable-indirection",
        )

    def test_variable_indirection_unrelated_var_allowed(self):
        # Variable bound to a non-spawn-log path must not trigger.
        self._assert_allowed(
            "python3 -c \"f='/tmp/foo.json'; open(f, 'w').write('{}')\"",
            "variable bound to unrelated path")

    def test_variable_indirection_var_used_for_read_only_allowed(self):
        # Variable bound to spawn-log but only used for read must not trigger.
        self._assert_allowed(
            "python3 -c \"import json; f='.runs/agent-spawn-log.jsonl'; d=json.load(open(f))\"",
            "variable used only for read")

    def test_variable_indirection_open_in_read_mode_allowed(self):
        # open(<var>, 'r') is a read, not a write.
        self._assert_allowed(
            "python3 -c \"f='.runs/agent-spawn-log.jsonl'; data=open(f, 'r').read()\"",
            "open with explicit read mode")

    # ---- Issue #1298: heredoc-body false positive class ----

    def test_1298_heredoc_body_with_spawn_log_redirect_literal_allows(self):
        """#1298: heredoc body containing `> agent-spawn-log.jsonl` literal
        must NOT trigger the bound-redirect — the body is data, not shell."""
        cmd = (
            "cat > /tmp/r.txt << 'EOF'\n"
            "Example deny: echo {} > .runs/agent-spawn-log.jsonl\n"
            "EOF"
        )
        self._assert_allowed(cmd, "heredoc-body redirect literal must allow")

    def test_1298_chained_heredoc_then_real_write_denies(self):
        """#1298 r1-c1: trailing real write to spawn-log must still deny."""
        cmd = (
            "cat << 'EOF'\n"
            "harmless body\n"
            "EOF\n"
            "echo {} > .runs/agent-spawn-log.jsonl"
        )
        self._assert_denied(cmd, "agent-spawn-log")

    def test_1298_python_heredoc_fed_open_still_denies(self):
        """#1298 r1-c2: heredoc-fed python open() must still deny."""
        cmd = (
            "python3 << 'PY'\n"
            "open('.runs/agent-spawn-log.jsonl', 'w').write('{}')\n"
            "PY"
        )
        self._assert_denied(cmd, "open-for-write")


if __name__ == "__main__":
    unittest.main()
