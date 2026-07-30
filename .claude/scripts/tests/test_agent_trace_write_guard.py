#!/usr/bin/env python3
"""test_agent_trace_write_guard.py — runtime guard on agent-traces writes.

Simulates Bash PreToolUse payloads and checks the hook's allow/deny behavior.
The hook's exit code is the Claude Code hook protocol signal:
  0 = allow
  non-zero (typically 2) = deny

Covers:
  1. Fast path: command that doesn't mention agent-traces → allow
  2. Allowed: write-recovery-trace.sh with --reason
  3. Allowed: write-recovery-trace.sh via `bash` wrapper with --reason
  4. Denied: write-recovery-trace.sh WITHOUT --reason
  5. Allowed: write-degraded-trace.py with --reason
  6. Denied: write-degraded-trace.py WITHOUT --reason
  7. Allowed: init-trace.py
  8. Allowed: validate-recovery.sh (stamps recovery_validated:true)
  9. Allowed: migrate-legacy-traces.py
 10. Denied: raw redirect `echo {} > .runs/agent-traces/foo.json`
 11. Denied: python open(...,'w') on agent-traces
 12. Denied: chained write after harmless command
 13. Allowed: reading an agent-traces file (no write operator)

Run: python3 .claude/scripts/tests/test_agent_trace_write_guard.py
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
HOOK = ROOT / ".claude/hooks/agent-trace-write-guard.sh"


class TestAgentTraceWriteGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_atwg_"))
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

    def test_fast_path_mentions_traces_but_no_write(self):
        # Reading an agent-trace file is allowed
        self._assert_allowed("cat .runs/agent-traces/design-critic.json",
                             "read of agent-traces")
        self._assert_allowed("ls .runs/agent-traces/", "list of agent-traces")

    # ---- fd-to-fd redirects (not file writes) must not false-positive ----
    # The write-op regex includes a bare `>` that previously matched the `>`
    # inside `2>&1`, and the awk chain splitter's RS=[&|;] previously split
    # on the `&` inside `2>&1`. Fix: the hook strips `\d*>+&\d+` tokens from
    # the command before running the awk/grep checks.

    def test_ls_traces_with_stderr_redirect_allowed(self):
        self._assert_allowed("ls .runs/agent-traces/ 2>&1",
                             "ls with 2>&1 is a read, not a write")

    def test_cat_trace_file_with_stderr_redirect_allowed(self):
        self._assert_allowed("cat .runs/agent-traces/design-critic.json 2>&1",
                             "cat with 2>&1 is a read, not a write")

    def test_chained_read_then_ls_with_stderr_redirect_allowed(self):
        self._assert_allowed(
            "wc -l .runs/observer-diffs.txt ; ls .runs/agent-traces/ 2>&1",
            "chained reads with 2>&1 must pass")

    def test_ls_traces_with_bare_fd_redirect_allowed(self):
        # `>&1` (no leading digit) is the rare but valid bash form.
        self._assert_allowed("ls .runs/agent-traces/ >&1",
                             "bare >&1 is an fd redirect, not a file write")

    def test_trace_path_with_fd3_to_fd2_allowed(self):
        # `3>&2` redirects an arbitrary fd, not a file write.
        self._assert_allowed("ls .runs/agent-traces/ 3>&2",
                             "3>&2 is fd-to-fd, not a file write")

    def test_csh_ampgt_into_traces_still_denied(self):
        # `cmd >& file` is a GNU bash extension meaning
        # `cmd > file 2>&1` — a real file write that must still deny.
        # No digit follows `&`, so the sed fd-strip does NOT remove it, and
        # the `>` survives to match the write-operator regex.
        self._assert_denied(
            "echo x >& .runs/agent-traces/fake.json",
        )

    # ---- Allowed writers ----

    def test_write_recovery_with_reason_allowed(self):
        self._assert_allowed(
            'bash .claude/scripts/write-recovery-trace.sh design-critic --reason "image limit"',
        )

    def test_write_recovery_direct_invocation_allowed(self):
        self._assert_allowed(
            '.claude/scripts/write-recovery-trace.sh design-critic --reason "x"',
        )

    def test_write_degraded_with_reason_allowed(self):
        self._assert_allowed(
            'python3 .claude/scripts/write-degraded-trace.py design-critic --reason "timeout" --checks-performed "a,b"',
        )

    def test_init_trace_allowed(self):
        self._assert_allowed("python3 scripts/init-trace.py design-critic")

    def test_validate_recovery_allowed(self):
        self._assert_allowed("bash .claude/scripts/validate-recovery.sh design-critic")

    def test_migrate_legacy_traces_allowed(self):
        self._assert_allowed("python3 .claude/scripts/migrate-legacy-traces.py")

    def test_merge_design_critic_allowed(self):
        self._assert_allowed("python3 .claude/scripts/merge-design-critic-traces.py")

    def test_merge_scaffold_pages_allowed(self):
        self._assert_allowed("python3 .claude/scripts/merge-scaffold-pages-traces.py")

    def test_merge_design_consistency_checker_allowed(self):
        # #1257: page-batched lead-merge mirror of design-critic merger
        self._assert_allowed("python3 .claude/scripts/merge-design-consistency-checker-traces.py")

    def test_python_open_for_write_to_consistency_checker_batch_denied(self):
        # #1257: only the official merger may write design-consistency-checker-*.json;
        # ad-hoc python3 -c open() must remain blocked.
        self._assert_denied(
            "python3 -c \"import json; json.dump({}, open('.runs/agent-traces/design-consistency-checker-batch1.json','w'))\"",
        )

    # ---- --reason enforcement (hook fires only when command mentions agent-traces) ----
    # Note: when the script is invoked without any agent-traces path in the
    # command string, the hook's fast-path allows it. The script's own
    # argument check is responsible for --reason enforcement in that case.
    # These tests cover the rare but possible case where the command ALSO
    # references agent-traces (e.g., in an embedded echo / diagnostic).

    def test_write_recovery_without_reason_and_traces_mention_denied(self):
        self._assert_denied(
            'bash .claude/scripts/write-recovery-trace.sh design-critic # targets agent-traces/design-critic.json',
            "--reason",
        )

    def test_write_degraded_without_reason_and_traces_mention_denied(self):
        self._assert_denied(
            "python3 .claude/scripts/write-degraded-trace.py design-critic --checks-performed x # writes agent-traces",
            "--reason",
        )

    # ---- Denied: raw writes ----

    def test_raw_redirect_denied(self):
        # Single-segment raw redirect is caught by the chain-check awk pattern
        # (which matches any segment containing both agent-traces/ and a write
        # operator — a single segment qualifies).
        self._assert_denied(
            "echo '{\"agent\":\"fake\"}' > .runs/agent-traces/fake.json",
        )

    def test_append_redirect_denied(self):
        self._assert_denied(
            "echo x >> .runs/agent-traces/fake.json",
        )

    def test_cp_into_traces_denied(self):
        self._assert_denied(
            "cp /tmp/x.json .runs/agent-traces/fake.json",
        )

    def test_python_open_for_write_denied(self):
        self._assert_denied(
            "python3 -c \"open('.runs/agent-traces/fake.json', 'w').write('{}')\"",
            "python open-for-write",
        )

    def test_python_open_for_append_denied(self):
        self._assert_denied(
            "python3 -c \"open('.runs/agent-traces/fake.json', 'a').write('{}')\"",
        )

    # ---- Chained command segments ----

    def test_chained_write_after_innocent_cmd_denied(self):
        self._assert_denied(
            "ls .runs/ && echo {} > .runs/agent-traces/fake.json",
            "chained command segment",
        )

    def test_chained_write_after_allowed_writer_denied(self):
        # Even if the chain starts with an allowed writer, a trailing raw write must be denied.
        self._assert_denied(
            'bash .claude/scripts/write-recovery-trace.sh x --reason "y" ; echo {} > .runs/agent-traces/forged.json',
            "chained command segment",
        )

    def test_chained_write_before_allowed_writer_denied(self):
        self._assert_denied(
            'echo {} > .runs/agent-traces/forged.json && bash .claude/scripts/write-recovery-trace.sh x --reason "y"',
        )

    # ---- Pattern obfuscation attempts ----

    def test_leading_spaces_denied(self):
        self._assert_denied(
            "   echo {} > .runs/agent-traces/fake.json",
        )

    def test_pipe_tee_denied(self):
        self._assert_denied(
            "echo x | tee .runs/agent-traces/fake.json",
        )

    # ---- Variable-indirection (PR3 C1: Python helper) ----
    # Closes the gap from /solve round-2 critic: the literal-path regex matches
    # `open('.runs/agent-traces/foo.json', 'w')` but misses
    # `f="...path..."; open(f, 'w')` because the var name `f` does not contain
    # `agent-traces`. The Python helper scans for `<var> = "...agent-traces/..."`
    # assignments and flags any later `open(<var>, "w")`/`open(<var>, "a")`.

    def test_variable_indirection_double_quoted_denied(self):
        self._assert_denied(
            "python3 -c \"f='.runs/agent-traces/forge.json'; open(f, 'w').write('{}')\"",
            "variable-indirection",
        )

    def test_variable_indirection_double_quoted_python_denied(self):
        # Bash single-quoted command with Python double-quoted strings.
        # Realistic alternative encoding — must also trigger the helper.
        self._assert_denied(
            'python3 -c \'f=".runs/agent-traces/forge.json"; open(f, "w").write("{}")\'',
            "variable-indirection",
        )

    def test_variable_indirection_append_mode_denied(self):
        self._assert_denied(
            "python3 -c \"path='.runs/agent-traces/forge.json'; open(path, 'a').write('x')\"",
            "variable-indirection",
        )

    def test_variable_indirection_with_json_dump_denied(self):
        # Mirrors the pre-PR2 pattern in scaffold-libs/scaffold-pages agents
        # that bypassed via json.dump(d, open(f, 'w')).
        self._assert_denied(
            "python3 -c \"import json; f='.runs/agent-traces/scaffold-libs.json'; d={}; json.dump(d, open(f, 'w'))\"",
            "variable-indirection",
        )

    def test_variable_indirection_with_modeb_suffix_denied(self):
        # Defense-in-depth: 'wb' / 'wb+' / 'a+' modes still write.
        self._assert_denied(
            "python3 -c \"f='.runs/agent-traces/forge.json'; open(f, 'wb').write(b'{}')\"",
            "variable-indirection",
        )

    def test_variable_indirection_unrelated_var_allowed(self):
        # Variable bound to a non-agent-traces path must not trigger.
        self._assert_allowed(
            "python3 -c \"f='/tmp/foo.json'; open(f, 'w').write('{}')\"",
            "variable bound to unrelated path",
        )

    def test_variable_indirection_var_used_for_read_only_allowed(self):
        # Variable bound to agent-traces but only used for read must not trigger.
        self._assert_allowed(
            "python3 -c \"import json; f='.runs/agent-traces/foo.json'; d=json.load(open(f))\"",
            "variable used only for read",
        )

    def test_variable_indirection_open_in_read_mode_allowed(self):
        # open(<var>, 'r') is a read, not a write — must not trigger.
        self._assert_allowed(
            "python3 -c \"f='.runs/agent-traces/foo.json'; data=open(f, 'r').read()\"",
            "open with explicit read mode",
        )

    def test_variable_indirection_python_semicolon_separator(self):
        # Critical: Python source with `;` separator within a single -c argument.
        # The existing chain awk uses RS="[&|;]" which would split this into
        # multiple records; the helper MUST scan COMMAND as a single string.
        self._assert_denied(
            "python3 -c \"import json; f='.runs/agent-traces/forge.json'; json.dump({}, open(f, 'w'))\"",
            "variable-indirection",
        )

    # ---- Issue #1298: heredoc-body false positive class ----

    def test_1298_heredoc_body_mentions_writer_name_allows(self):
        """#1298: prose mentioning write-recovery-trace.sh inside a heredoc
        body must NOT trigger the allow-list and demand --reason."""
        cmd = (
            "cat > /tmp/r.txt << 'EOF'\n"
            "Doc on .claude/scripts/write-recovery-trace.sh in the trace pipeline; "
            "agent-traces/ is the dir.\n"
            "EOF"
        )
        self._assert_allowed(cmd, "heredoc-body writer-name mention must allow")

    def test_1298_heredoc_body_with_redirect_literal_allows(self):
        """#1298: prose containing `> agent-traces/x.json` literal in a heredoc
        body must NOT trigger the catch-all bound-redirect."""
        cmd = (
            "cat > /tmp/r.txt << 'EOF'\n"
            "Example bad command: cat > .runs/agent-traces/forge.json\n"
            "EOF"
        )
        self._assert_allowed(cmd, "heredoc-body redirect literal must allow")

    def test_1298_chained_heredoc_then_real_write_denies(self):
        """#1298 r1-c1 regression vector: trailing real write must NOT be
        wiped by the strip_heredoc_bodies loop bug. The bound-redirect
        catch-all must still fire on the trailing `echo > agent-traces/...`."""
        cmd = (
            "cat << 'EOF'\n"
            "harmless\n"
            "EOF\n"
            "echo {} > .runs/agent-traces/forge.json"
        )
        self._assert_denied(cmd, "agent-traces/")

    def test_1298_python_heredoc_fed_open_still_denies(self):
        """#1298 r1-c2: heredoc-fed python `open()` attack must STILL deny.
        The python-open regex runs on RAW $COMMAND with `coherence-allow:
        raw-command` pragma so canonicalization doesn't hide the attack."""
        cmd = (
            "python3 << 'PY'\n"
            "open('.runs/agent-traces/forge.json', 'w').write('{}')\n"
            "PY"
        )
        self._assert_denied(cmd, "open-for-write")

    def test_1298_heredoc_body_reason_token_does_not_satisfy(self):
        """#1298 security improvement: a `--reason` token hidden inside a
        heredoc body MUST NOT satisfy the writer-script --reason check.

        Pre-fix behavior: shlex tokenized the heredoc body's `--reason crash`
        as separate tokens, allowing a writer call with no real --reason to
        bypass the #963 contract via heredoc-body smuggling.

        Post-fix: canonicalize strips the heredoc body before _check_reason_token
        runs on COMMAND_CANONICAL — the body-only --reason is no longer visible
        to the segment scan, so the check fails and the writer call DENIES.
        """
        cmd = (
            "bash .claude/scripts/write-recovery-trace.sh observer << 'PY'\n"
            "--reason crash\n"
            "PY\n"
            "; ls .runs/agent-traces/"
        )
        self._assert_denied(cmd, "lacks --reason")

    def test_1298_canonicalize_fallback_preserves_baseline_when_python_fails(self):
        """#1298 resilience: when canonicalize_bash_command.py fails (e.g.,
        python3 missing or script crash), the hook falls back to RAW $COMMAND
        for downstream checks. The bound-redirect catch-all on $NORM still
        fires on direct shell writes — heredoc-body false-positive fix is
        the only thing temporarily lost.
        """
        # Replace the canonicalizer with a deliberately broken one for this test
        canon_path = Path(self.tmp) / ".claude/scripts/lib/canonicalize_bash_command.py"
        original = canon_path.read_text()
        canon_path.write_text("import sys\nsys.exit(1)\n")
        try:
            # Direct shell write to agent-traces — must still DENY via NORM check.
            self._assert_denied(
                "echo {} > .runs/agent-traces/forge.json",
                "agent-traces/",
            )
            # Unrelated command — must still ALLOW via fast-path.
            self._assert_allowed(
                "ls .runs/",
                "fast-path on unrelated command",
            )
        finally:
            canon_path.write_text(original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
