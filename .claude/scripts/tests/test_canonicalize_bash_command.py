#!/usr/bin/env python3
"""Tests for .claude/scripts/lib/canonicalize_bash_command.py.

Closes #1298. Covers three correctness fixes plus regression cases:

- Loop-restart bug — heredoc + trailing real write must preserve the trailing
  write (the previous strip_heredoc_bodies wiped it).
- Same-line multi-heredoc — `cat <<E1 <<E2 ...` must consume both bodies.
- POSIX strictness — closing delim line must contain ONLY the delim for
  plain `<<DELIM`; `<<-DELIM` permits leading TABS only.

Plus general regression cases: nested heredoc in command-substitution,
unterminated heredoc, quoted-delim heredoc, no-heredoc passthrough.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIB = HERE.parent / "lib" / "canonicalize_bash_command.py"

_spec = importlib.util.spec_from_file_location("canonicalize_bash_command", LIB)
assert _spec and _spec.loader, f"failed to load module from {LIB}"
_mod = importlib.util.module_from_spec(_spec)
sys.modules["canonicalize_bash_command"] = _mod
_spec.loader.exec_module(_mod)

strip = _mod.strip_heredoc_bodies
canonicalize = _mod.canonicalize


class TestStripHeredocBodies(unittest.TestCase):
    """Per-bug-fix and regression tests for strip_heredoc_bodies."""

    # --- Loop-restart bug fix (round-1 c1) -----------------------------------

    def test_heredoc_then_trailing_real_write_preserved(self):
        """The trailing `echo > path` MUST survive heredoc stripping.

        Previous bug: re-matched <<EOF on iter 2, body-end search failed,
        unterminated branch wiped everything from body_start to end.
        """
        inp = "cat << EOF\nbody\nEOF\necho > path"
        out = strip(inp)
        self.assertIn("echo > path", out, f"trailing write lost: {out!r}")
        self.assertNotIn("body", out, f"body not stripped: {out!r}")

    def test_back_to_back_same_delim_both_stripped(self):
        inp = "cat << EOF\na\nEOF\ncat << EOF\nb\nEOF\n"
        out = strip(inp)
        self.assertNotIn("a\n", out, f"first body not stripped: {out!r}")
        self.assertNotIn("b\n", out, f"second body not stripped: {out!r}")
        self.assertEqual(out.count("cat << EOF"), 2,
                         f"both introducers must be preserved: {out!r}")

    # --- Same-line multi-heredoc fix (round-2 c2) ----------------------------

    def test_same_line_multiple_heredocs_both_stripped(self):
        """`cat <<E1 <<E2\\nb1\\nE1\\nb2\\nE2` must consume both bodies.

        Bash queues b1 for E1 and b2 for E2 in introducer order.
        """
        inp = "cat << E1 << E2\nb1\nE1\nb2\nE2\n"
        out = strip(inp)
        self.assertNotIn("b1", out, f"first queued body not stripped: {out!r}")
        self.assertNotIn("b2", out, f"second queued body not stripped: {out!r}")
        # Introducer line preserved
        self.assertIn("cat << E1 << E2", out)

    def test_same_line_multi_heredoc_then_trailing_write(self):
        """Same-line multi-heredoc + trailing real write — write must survive."""
        inp = "cat << E1 << E2\nb1\nE1\nb2\nE2\necho > path"
        out = strip(inp)
        self.assertIn("echo > path", out, f"trailing write lost: {out!r}")
        self.assertNotIn("b1", out)
        self.assertNotIn("b2", out)

    # --- POSIX strictness fix (round-2 c3) -----------------------------------

    def test_plain_heredoc_trailing_space_eof_does_not_close(self):
        """Plain `<<EOF` requires `EOF` exactly; `EOF ` must NOT close.

        Conservative direction: over-strip to end-of-string.
        """
        inp = "cat << EOF\nbody\nEOF \necho > path"
        out = strip(inp)
        # Over-strip is the safe direction. Either the function consumes the
        # rest as still-in-body and emits the intro line + trailing newline,
        # or it leaves it as unterminated. Either way, the trailing real
        # write must NOT escape canonicalization as if it were a fresh shell
        # command — the conservative parser holds the body open.
        self.assertNotIn("echo > path", out,
                         f"trailing write must NOT survive bad close: {out!r}")

    def test_plain_heredoc_leading_space_eof_does_not_close(self):
        """Plain `<<EOF` does NOT permit leading whitespace on close line."""
        inp = "cat << EOF\nbody\n  EOF\necho > path"
        out = strip(inp)
        self.assertNotIn("echo > path", out,
                         f"trailing write must NOT survive bad close: {out!r}")

    def test_dash_heredoc_leading_tab_eof_closes(self):
        """`<<-EOF` permits leading TABS only on close line — closes correctly."""
        inp = "cat <<-EOF\n\tbody\n\tEOF\necho > path"
        out = strip(inp)
        self.assertIn("echo > path", out,
                      f"<<- with leading-tab EOF must close: {out!r}")
        self.assertNotIn("\tbody", out, f"body not stripped: {out!r}")

    def test_dash_heredoc_leading_space_eof_does_not_close(self):
        """`<<-EOF` permits leading TABS only — leading SPACES do NOT close."""
        inp = "cat <<-EOF\nbody\n  EOF\necho > path"
        out = strip(inp)
        self.assertNotIn("echo > path", out,
                         f"<<- must not close on leading-space EOF: {out!r}")

    # --- General regression cases --------------------------------------------

    def test_nested_in_command_substitution(self):
        inp = "echo $(cat << EOF\nbody\nEOF\n) > /tmp/out"
        out = strip(inp)
        self.assertNotIn("body", out)
        self.assertIn("> /tmp/out", out)

    def test_unterminated_heredoc(self):
        inp = "cat << EOF\nbody"
        out = strip(inp)
        # Unterminated → over-strip to end of string, leaving the introducer
        # line + a trailing newline (the function's documented contract).
        self.assertNotIn("body", out)
        self.assertIn("cat << EOF", out)

    def test_quoted_delim(self):
        inp = "cat << 'EOF'\nbody\nEOF\n"
        out = strip(inp)
        self.assertNotIn("body", out)
        self.assertIn("cat << 'EOF'", out)

    def test_double_quoted_delim(self):
        inp = 'cat << "EOF"\nbody\nEOF\n'
        out = strip(inp)
        self.assertNotIn("body", out)

    def test_no_heredoc_passthrough(self):
        inp = "echo hi > path && ls -la"
        self.assertEqual(strip(inp), inp)

    def test_empty_input(self):
        self.assertEqual(strip(""), "")

    def test_writer_name_in_heredoc_body_stripped(self):
        """The exact #1298 false-positive surface: writer-name in body removed."""
        inp = ('cat > /tmp/r.txt << EOF\n'
               'Doc on .claude/scripts/write-recovery-trace.sh in the trace pipeline; '
               'agent-traces/ is the dir.\n'
               'EOF')
        out = strip(inp)
        self.assertNotIn("write-recovery-trace.sh", out)
        self.assertNotIn("agent-traces/", out)
        self.assertIn("cat > /tmp/r.txt", out)

    def test_canonicalize_alias_equivalent(self):
        for inp in ("", "echo hi", "cat << EOF\nbody\nEOF\n"):
            self.assertEqual(canonicalize(inp), strip(inp))


class TestCLIEntryPoint(unittest.TestCase):
    """Smoke test the `python3 canonicalize_bash_command.py` CLI."""

    def test_stdin_to_stdout(self):
        import subprocess
        inp = "cat << EOF\nbody\nEOF\necho > path"
        result = subprocess.run(
            [sys.executable, str(LIB)],
            input=inp,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, f"stderr={result.stderr}")
        self.assertIn("echo > path", result.stdout)
        self.assertNotIn("body", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
