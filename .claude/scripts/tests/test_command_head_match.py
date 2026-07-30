#!/usr/bin/env python3
"""test_command_head_match.py — regression for issue #1366 + sibling sweep.

`verify-pr-gate.sh:13`, `observe-commit-gate.sh:17`, and `skill-commit-gate.sh:19`
previously used bare substring matches (`*"gh pr create"*`, `*"git commit"*`)
to detect command invocations in `tool_input.command`. These false-fired on
grep patterns, heredoc prose, JSON literals, single/double-quoted strings,
and env-var assignments containing the literal substring.

The fix replaces each substring with a command-head regex anchored at start
of $COMMAND or after a shell separator (;, &, |), with whitespace-tolerant
boundaries.

This test is Layer-1: it isolates the regex semantics from hook side-effects
(which depend on .runs/ evidence and branch state) by driving the regex
through a small bash `-c` shim.

**Drift defense:** the regex is EXTRACTED from each hook file at import time,
not hardcoded. If a hook is edited (regex change, line removal, structure
refactor), the extraction either picks up the new regex automatically or
raises a clear assertion error. Eliminates the silent-drift gap where a
hardcoded test could pass against a frozen copy while the hook's actual
behavior diverged.
"""
from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]

VERIFY_PR_GATE = ROOT / ".claude/hooks/verify-pr-gate.sh"
OBSERVE_COMMIT_GATE = ROOT / ".claude/hooks/observe-commit-gate.sh"
SKILL_COMMIT_GATE = ROOT / ".claude/hooks/skill-commit-gate.sh"


def extract_command_head_regex(hook_path: Path) -> str:
    """Extract the `=~ <regex>` from the first `[[ ! "$COMMAND" =~ ... ]]; then` line.

    Couples the test to the production code: a hook regex change flows
    through automatically; a hook regex deletion raises so the suite fails
    loudly instead of giving false confidence against a stale copy.

    Anchors to the bash `]]; then` idiom — required because the regex
    body itself contains `]]` sequences (e.g. `[[:space:]]`) that would
    otherwise prematurely terminate a generic `]]` match. The required
    `\\s+` before the outer `]]` excludes intra-class brackets (`[[:space:]]`
    has no whitespace before its closing `]]`).
    """
    pattern = re.compile(
        r'\[\[\s*!\s*"\$COMMAND"\s*=~\s+(\S.*?)\s+\]\];\s*then'
    )
    for line in hook_path.read_text().splitlines():
        m = pattern.search(line)
        if m:
            return m.group(1)
    raise AssertionError(
        f'No `[[ ! "$COMMAND" =~ <regex> ]]; then` line found in {hook_path}. '
        "Was the gate removed or refactored to a different structure? "
        "(See #1366 — substring → regex anchor.)"
    )


# Extracted at module load. If extraction fails, the suite fails fast.
GH_PR_CREATE_RE = extract_command_head_regex(VERIFY_PR_GATE)
GIT_COMMIT_RE_OBSERVE = extract_command_head_regex(OBSERVE_COMMIT_GATE)
GIT_COMMIT_RE_SKILL = extract_command_head_regex(SKILL_COMMIT_GATE)


def regex_matches(regex: str, command: str) -> bool:
    """Run the regex against $command in bash; True iff matches."""
    proc = subprocess.run(
        [
            "bash", "-c",
            f'COMMAND="$1"; if [[ "$COMMAND" =~ {regex} ]]; then echo MATCH; else echo NOMATCH; fi',
            "_", command,
        ],
        capture_output=True, text=True, timeout=5,
    )
    return proc.stdout.strip() == "MATCH"


class TestRegexConsistency(unittest.TestCase):
    """Sibling-sweep invariant: observe and skill commit gates share one regex.

    Per `feedback_dedupe_scope_completeness`, when the bare-substring anti-
    pattern was swept across both `git commit` hooks, they were given the
    same regex. A future edit that "fixes" one but forgets the other would
    re-create the same drift class. This test locks the invariant in.
    """

    def test_git_commit_regex_identical_across_sibling_hooks(self):
        self.assertEqual(
            GIT_COMMIT_RE_OBSERVE,
            GIT_COMMIT_RE_SKILL,
            msg=(
                "observe-commit-gate.sh and skill-commit-gate.sh must use the "
                "same `git commit` command-head regex (sibling sweep #1366). "
                f"observe = {GIT_COMMIT_RE_OBSERVE!r}; "
                f"skill = {GIT_COMMIT_RE_SKILL!r}"
            ),
        )


class TestGhPrCreateRegex(unittest.TestCase):
    """Regex contract for verify-pr-gate.sh:13 (#1366)."""

    def _match(self, command: str) -> bool:
        return regex_matches(GH_PR_CREATE_RE, command)

    # --- TRUE positives (must trigger the hook) ---
    def test_bare_command_matches(self):
        self.assertTrue(self._match("gh pr create"))

    def test_with_flags_matches(self):
        self.assertTrue(self._match("gh pr create --title foo"))

    def test_after_and_separator_matches(self):
        self.assertTrue(self._match("cd /tmp && gh pr create"))

    def test_after_semicolon_separator_matches(self):
        self.assertTrue(self._match("echo a; gh pr create"))

    def test_multiple_spaces_matches(self):
        self.assertTrue(self._match("gh   pr   create"))

    # --- FALSE positives (must NOT trigger after the fix) ---
    def test_grep_pattern_does_not_match(self):
        self.assertFalse(self._match('grep "gh pr create" file.txt'))

    def test_single_quoted_does_not_match(self):
        self.assertFalse(self._match("echo 'gh pr create'"))

    def test_env_var_assignment_does_not_match(self):
        self.assertFalse(self._match("GH_PR_CREATE=1 ./script"))

    def test_create_fork_subcommand_does_not_match(self):
        self.assertFalse(self._match("gh pr create-fork"))


class TestGitCommitRegex(unittest.TestCase):
    """Regex contract shared by observe-commit-gate.sh:17 and skill-commit-gate.sh:19.

    Uses the regex extracted from observe-commit-gate.sh; TestRegexConsistency
    asserts the sibling hook uses an identical pattern, so a single test class
    covers both call sites without duplication.
    """

    def _match(self, command: str) -> bool:
        return regex_matches(GIT_COMMIT_RE_OBSERVE, command)

    # --- TRUE positives ---
    def test_bare_command_matches(self):
        self.assertTrue(self._match("git commit"))

    def test_with_message_flag_matches(self):
        self.assertTrue(self._match('git commit -m "msg"'))

    def test_after_and_separator_matches(self):
        self.assertTrue(self._match("cd /tmp && git commit -am foo"))

    def test_after_semicolon_separator_matches(self):
        self.assertTrue(self._match("git status; git commit"))

    def test_amend_subcommand_matches(self):
        self.assertTrue(self._match("git commit --amend"))

    # --- FALSE positives ---
    def test_grep_pattern_does_not_match(self):
        self.assertFalse(self._match('grep "git commit" history.log'))

    def test_double_quoted_does_not_match(self):
        self.assertFalse(self._match('echo "git commit"'))

    def test_committed_word_does_not_match(self):
        self.assertFalse(self._match("git committed"))

    def test_commit_tree_plumbing_does_not_match(self):
        self.assertFalse(self._match("git commit-tree"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
