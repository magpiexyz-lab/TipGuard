#!/usr/bin/env python3
"""test_bash_hook_blockquote_precision.py — runtime precision test for the
bound-redirect awk regex in registered write-guard hooks.

Issue #1333: the prior bound regex
  ([0-9]*&?>+|[0-9]*>>?)[[:space:]]*["']?[^|;&"'\\n]*<gated_path>
admitted arbitrary prose between the operator and the gated path via the
open exclusion class `[^|;&"'\\n]*`. Markdown blockquote shapes inside
`gh issue create --body "..."` (e.g., `> 1b. After each fix, log it in
\\`.runs/fix-log.md\\``) false-positively triggered a deny when the body
mentioned the gated path anywhere after the blockquote `>`.

The fix removes the open exclusion so the path must appear immediately
after the operator + optional whitespace + optional quote.

Each test invokes the registered hook with a synthetic Bash command
payload via `tool_input.command` and asserts:
  - The original observed false-positive (prose between `>` and the
    gated path) is now allowed (exit 0, no deny).
  - Real shell redirects (with/without space, with/without quote) still
    fire (exit non-zero with `deny` on stderr).
  - Known-residual cases (bare `> .runs/path` blockquote;
    `tee|cp|mv|dd` keyword in markdown prose) are documented but NOT
    asserted to be rejected — they remain false-positives because shell
    grammar makes them indistinguishable from real redirects/commands.
    Workaround: file via `--body-file` or strip the path from prose.

Run: python3 .claude/scripts/tests/test_bash_hook_blockquote_precision.py
"""
from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def invoke_hook(hook_path: Path, command: str) -> tuple[int, str]:
    """Invoke a hook with a synthetic Bash payload; return (exit_code, stderr)."""
    payload = json.dumps({"tool_input": {"command": command}})
    proc = subprocess.run(
        ["bash", str(hook_path)],
        input=payload,
        capture_output=True, text=True, timeout=15,
    )
    return proc.returncode, proc.stderr


class TestBlockquotePrecisionFixLedgerHook(unittest.TestCase):
    """fix-ledger-write-guard.sh — protects .runs/fix-ledger.jsonl, .runs/fix-log.md."""

    HOOK = ROOT / ".claude/hooks/fix-ledger-write-guard.sh"

    def test_prose_between_operator_and_path_is_allowed(self):
        """The originally-observed false-positive: markdown blockquote
        with prose between `>` and the gated path. After fix, allowed."""
        # Reproduces the gh issue create --body shape from issue #1333.
        cmd = (
            'gh issue create --body "## Template files\n'
            '- `.claude/skills/resolve/state-7-implement-fixes.md` (step 1b)\n'
            '\n'
            '## Symptom\n'
            'state-7 step 1b instructs:\n'
            '\n'
            '> 1b. After each fix, log it in `.runs/fix-log.md`: ..."'
        )
        rc, err = invoke_hook(self.HOOK, cmd)
        self.assertEqual(
            rc, 0,
            f"prose-between-operator-and-path must NOT trigger deny (rc={rc}, stderr={err!r})",
        )

    def test_real_shell_redirect_with_space_still_blocks(self):
        """Real shell redirect `> .runs/fix-log.md` must still be blocked."""
        cmd = "echo bad > .runs/fix-log.md"
        rc, err = invoke_hook(self.HOOK, cmd)
        self.assertNotEqual(
            rc, 0,
            f"real shell redirect must trigger deny (rc={rc}, stderr={err!r})",
        )

    def test_real_shell_redirect_no_space_still_blocks(self):
        """Real shell redirect with no space `>.runs/fix-ledger.jsonl` must still be blocked."""
        cmd = "echo bad>.runs/fix-ledger.jsonl"
        rc, err = invoke_hook(self.HOOK, cmd)
        self.assertNotEqual(
            rc, 0,
            f"real shell redirect (no space) must trigger deny (rc={rc}, stderr={err!r})",
        )

    def test_real_shell_redirect_with_quote_still_blocks(self):
        """Real shell redirect with quoted target `> ".runs/fix-log.md"` must still be blocked."""
        cmd = 'cat foo > ".runs/fix-log.md"'
        rc, err = invoke_hook(self.HOOK, cmd)
        self.assertNotEqual(
            rc, 0,
            f"real shell redirect (quoted) must trigger deny (rc={rc}, stderr={err!r})",
        )

    def test_unrelated_command_passes(self):
        """Commands that don't mention the gated path exit 0 via fast-path."""
        cmd = "echo hello world"
        rc, err = invoke_hook(self.HOOK, cmd)
        self.assertEqual(rc, 0, f"unrelated command must pass (rc={rc}, stderr={err!r})")


class TestBlockquotePrecisionAgentTraceHook(unittest.TestCase):
    """agent-trace-write-guard.sh — protects agent-traces/*.json."""

    HOOK = ROOT / ".claude/hooks/agent-trace-write-guard.sh"

    def test_prose_between_operator_and_path_is_allowed(self):
        cmd = (
            'gh issue create --body "## File\n'
            '- `agent-traces/foo.json`\n'
            '> The agent wrote to `agent-traces/foo.json`."'
        )
        rc, err = invoke_hook(self.HOOK, cmd)
        self.assertEqual(rc, 0, f"prose-between false-positive (rc={rc}, stderr={err!r})")

    def test_real_shell_redirect_still_blocks(self):
        cmd = "echo bad > agent-traces/forge.json"
        rc, err = invoke_hook(self.HOOK, cmd)
        self.assertNotEqual(
            rc, 0, f"real shell redirect must deny (rc={rc}, stderr={err!r})",
        )


class TestBlockquotePrecisionTraceHook(unittest.TestCase):
    """trace-write-guard.sh — protects agent-spawn-log.jsonl."""

    HOOK = ROOT / ".claude/hooks/trace-write-guard.sh"

    def test_prose_between_operator_and_path_is_allowed(self):
        cmd = (
            'gh issue create --body "## Filing about agent-spawn-log\n'
            '> The hook writes to `agent-spawn-log.jsonl`."'
        )
        rc, err = invoke_hook(self.HOOK, cmd)
        self.assertEqual(rc, 0, f"prose-between false-positive (rc={rc}, stderr={err!r})")

    def test_real_shell_redirect_still_blocks(self):
        cmd = "echo forge > agent-spawn-log.jsonl"
        rc, err = invoke_hook(self.HOOK, cmd)
        self.assertNotEqual(rc, 0, f"real shell redirect must deny (rc={rc}, stderr={err!r})")


class TestBlockquotePrecisionGateArtifactHook(unittest.TestCase):
    """gate-artifact-bash-write-guard.sh — protects .runs/*.json gate manifests.

    NOTE: This hook delegates to a manifest of canonical writers; only paths
    in the manifest deny. Tests use a known-gated path from the manifest.
    """

    HOOK = ROOT / ".claude/hooks/gate-artifact-bash-write-guard.sh"

    def test_prose_between_operator_and_path_is_allowed(self):
        # Use the verify-context.json gate-readable artifact path.
        cmd = (
            'gh issue create --body "## Filing\n'
            '> The skill writes to `.runs/verify-context.json` via canonical writer."'
        )
        rc, err = invoke_hook(self.HOOK, cmd)
        # Either rc=0 (fast-path or precision regex skips) or a non-deny exit.
        # We only assert NO deny stderr message about a write target.
        self.assertEqual(rc, 0, f"prose-between false-positive (rc={rc}, stderr={err!r})")


class TestBlockquotePrecisionPhaseAHook(unittest.TestCase):
    """bootstrap-phase-a-write-guard.sh — emits findings (warn-mode) rather than denies."""

    HOOK = ROOT / ".claude/hooks/bootstrap-phase-a-write-guard.sh"

    def test_prose_between_operator_and_path_emits_no_finding(self):
        """The fix tightens both bound-redirect awk blocks; prose-between
        markdown shapes should not emit phase-A findings."""
        # Phase A regex is built dynamically from a manifest at runtime.
        # We use a generic markdown-blockquote-with-path shape.
        cmd = (
            'gh issue create --body "## Filing\n'
            '> Phase A files include `experiment.yaml` per the bootstrap doctrine."'
        )
        rc, err = invoke_hook(self.HOOK, cmd)
        # Hook is informational/warn-mode; rc should be 0 and no "chained
        # shell write" finding text in stderr.
        self.assertNotIn(
            "chained shell write to Phase A file", err,
            f"prose-between must not produce phase-A finding (rc={rc}, stderr={err!r})",
        )


# ---------------------------------------------------------------------------
# Documented known-residual cases (NOT asserted)
# ---------------------------------------------------------------------------
#
# The following shapes remain false-positives after the #1333 fix and
# require the `--body-file` workaround (or stripping the path from prose):
#
#   1. Bare blockquote with naked path:    `\n> .runs/fix-log.md\n`
#      Indistinguishable from real `> file` redirect at the awk level.
#
#   2. tee/cp/mv keyword in markdown prose: `We tee output to .runs/...`
#      The tee/cp/mv variant regex retains the open exclusion class because
#      multi-arg shell semantics legitimately admit prose between command
#      and target (e.g., `tee -a flag1 flag2 file`).
#
# These are documented in the hook source comments and accepted as the
# trade-off for not rejecting real shell redirects.


if __name__ == "__main__":
    unittest.main()
