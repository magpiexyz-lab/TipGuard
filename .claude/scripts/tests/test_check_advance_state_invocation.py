#!/usr/bin/env python3
"""test_check_advance_state_invocation.py — public-API contract test.

Pins the parse_invocation contract that state-completion-gate.sh and
phase-boundary-gate.sh depend on (issue #1223). Closes a contract gap
exposed by the #1298 refactor — strip_heredoc_bodies was extracted to a
new shared library and three pre-existing correctness bugs were fixed
inside that function. This test ensures #1223's callers receive the
expected behavior contract regardless of the underlying implementation.

What this test pins:
  - Real invocations at head position are detected.
  - Heredoc-body false positives are suppressed (#1223).
  - Pre-existing parser limitations (chained-after-heredoc not detected,
    over-strip-conservative direction) are unchanged.
  - Single-quoted argument-text false positives are suppressed.

Run: python3 .claude/scripts/tests/test_check_advance_state_invocation.py
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIB = HERE.parent / "lib" / "check-advance-state-invocation.py"

_spec = importlib.util.spec_from_file_location("check_advance_state_invocation", LIB)
assert _spec and _spec.loader, f"failed to load module from {LIB}"
_mod = importlib.util.module_from_spec(_spec)
sys.modules["check_advance_state_invocation"] = _mod
_spec.loader.exec_module(_mod)

parse_invocation = _mod.parse_invocation


class TestParseInvocation(unittest.TestCase):
    """Public-API contract for #1223 callers (state-completion-gate.sh,
    phase-boundary-gate.sh). All assertions reflect behavior BOTH before
    and after the #1298 refactor — the refactor must not change any of
    these contracts.
    """

    def test_real_invocation_at_head(self):
        """Simple happy path: bash advance-state.sh skill state."""
        ok, skill, sid = parse_invocation("bash advance-state.sh solve 0")
        self.assertTrue(ok)
        self.assertEqual(skill, "solve")
        self.assertEqual(sid, "0")

    def test_real_invocation_with_path_prefix(self):
        """`bash .claude/scripts/advance-state.sh skill state`."""
        ok, skill, sid = parse_invocation(
            "bash .claude/scripts/advance-state.sh resolve 7"
        )
        self.assertTrue(ok)
        self.assertEqual(skill, "resolve")
        self.assertEqual(sid, "7")

    def test_heredoc_body_advance_state_text_suppressed(self):
        """#1223: prose mentioning advance-state.sh inside a heredoc body
        must NOT be detected as a real invocation."""
        ok, _, _ = parse_invocation(
            "cat << EOF\nbash advance-state.sh solve 0\nEOF"
        )
        self.assertFalse(ok)

    def test_chained_after_heredoc_not_detected_pre_existing(self):
        """Pre-existing parser limitation: shlex tokenizes `EOF` as a
        regular token (not a SEGMENT_SEPARATOR), so a real invocation
        chained AFTER a heredoc close is not at a head position. This
        contract is UNCHANGED by #1298 — the loop-bug fix preserves the
        trailing characters in the canonical string, but parse_invocation's
        head-detection still misses them. Documented here so a future
        maintainer doesn't think they "fixed" #1298 by also "fixing" this."""
        ok, _, _ = parse_invocation(
            "cat << EOF\nharmless\nEOF\nbash advance-state.sh solve 0"
        )
        self.assertFalse(ok, "pre-existing limitation must hold")

    def test_trailing_space_eof_over_strip_conservative(self):
        """POSIX-strict close: trailing whitespace on the close line does
        NOT close the heredoc. Conservative over-strip direction —
        everything after is still in the body."""
        ok, _, _ = parse_invocation(
            "cat << EOF\nbody\nEOF \nbash advance-state.sh solve 0"
        )
        self.assertFalse(ok, "trailing-space EOF over-strip is conservative")

    def test_dash_heredoc_tab_close_works(self):
        """`<<-EOF` permits leading tabs only on close. Combined with the
        chained-after-heredoc limitation (test_chained_after_heredoc_not_detected),
        the trailing real invocation is in shlex-limited territory."""
        ok, _, _ = parse_invocation(
            "cat <<-EOF\n\tbody\n\tEOF\nbash advance-state.sh solve 0"
        )
        self.assertFalse(ok, "trailing real invocation hits shlex limitation")

    def test_single_quoted_argument_text_suppressed(self):
        """Argument text inside a single-quoted string must NOT match —
        shlex treats it as a single token whose value contains
        advance-state.sh but whose token POSITION is not at command head."""
        ok, _, _ = parse_invocation(
            "gh issue create --body 'invokes advance-state.sh internally'"
        )
        self.assertFalse(ok)

    def test_double_quoted_argument_text_suppressed(self):
        """Same as single-quoted: argument text inside double quotes is
        not at head position."""
        ok, _, _ = parse_invocation(
            'gh issue create --body "invokes advance-state.sh internally"'
        )
        self.assertFalse(ok)

    def test_empty_command(self):
        """Empty command: returns (False, "", "") via fail-open contract."""
        ok, skill, sid = parse_invocation("")
        self.assertFalse(ok)
        self.assertEqual(skill, "")
        self.assertEqual(sid, "")

    def test_malformed_shlex_fails_open(self):
        """Unbalanced quotes: shlex raises ValueError → fails open."""
        ok, skill, sid = parse_invocation("bash 'unbalanced quote")
        self.assertFalse(ok)
        self.assertEqual(skill, "")
        self.assertEqual(sid, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
