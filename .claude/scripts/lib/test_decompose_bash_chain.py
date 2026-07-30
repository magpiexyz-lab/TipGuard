#!/usr/bin/env python3
"""Meta-test for decompose-bash-chain.py."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Hyphenated module name — import via importlib.
import importlib.util as _ilu

_MOD_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "decompose-bash-chain.py"
)
_spec = _ilu.spec_from_file_location("decompose_bash_chain", _MOD_PATH)
assert _spec is not None and _spec.loader is not None
decompose_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(decompose_mod)
decompose = decompose_mod.decompose


class DecomposeChainTests(unittest.TestCase):
    def test_single_command(self) -> None:
        segs = decompose("bash a.sh foo bar")
        self.assertEqual(segs, [("bash", ["a.sh", "foo", "bar"])])

    def test_double_and(self) -> None:
        segs = decompose("bash a.sh && bash b.sh c")
        self.assertEqual(
            segs,
            [("bash", ["a.sh"]), ("bash", ["b.sh", "c"])],
        )

    def test_or_separator(self) -> None:
        segs = decompose("a.sh || b.sh")
        self.assertEqual(segs, [("a.sh", []), ("b.sh", [])])

    def test_semicolon(self) -> None:
        segs = decompose("a.sh; b.sh; c.sh")
        self.assertEqual(
            segs, [("a.sh", []), ("b.sh", []), ("c.sh", [])]
        )

    def test_pipe(self) -> None:
        segs = decompose("cat foo | grep bar")
        self.assertEqual(segs, [("cat", ["foo"]), ("grep", ["bar"])])

    def test_heredoc_body_stripped(self) -> None:
        # Heredoc body should not be attributed to any segment.
        cmd = (
            "bash a.sh <<EOF\n"
            "this is body content && fake.sh\n"
            "EOF\n"
            "&& bash b.sh"
        )
        segs = decompose(cmd)
        # Should be exactly two segments: a.sh and b.sh (content inside
        # heredoc was stripped — no spurious "fake.sh" segment).
        heads = [s[0] for s in segs]
        self.assertEqual(heads, ["bash", "bash"])
        self.assertEqual(segs[0][1][0], "a.sh")
        self.assertEqual(segs[1][1][0], "b.sh")

    def test_quoted_args_preserved(self) -> None:
        segs = decompose('bash a.sh --path ".runs/foo.json" --skill solve')
        self.assertEqual(
            segs,
            [
                (
                    "bash",
                    ["a.sh", "--path", ".runs/foo.json", "--skill", "solve"],
                )
            ],
        )

    def test_unbalanced_quote_raises(self) -> None:
        with self.assertRaises(ValueError):
            decompose('bash a.sh "unbalanced')

    def test_empty_command(self) -> None:
        self.assertEqual(decompose(""), [])

    def test_bundled_checkout_chain(self) -> None:
        # The exact #1328 bundled-chain shape. Note that $(...) substitution
        # and > redirects produce noise segments, but the two key segments
        # (git checkout -b AND bash update-context-branch.sh) MUST still
        # appear so the Fix B hook can detect them.
        cmd = (
            'echo "$(date +%s)" > .runs/last-branch-checkout.tsv && '
            'OLD_BRANCH="$(git branch --show-current)" && '
            'git checkout -b "feat/x" && '
            'bash .claude/scripts/update-context-branch.sh "$OLD_BRANCH"'
        )
        segs = decompose(cmd)
        # Find a segment matching `git checkout -b ...`
        has_checkout = any(
            head == "git"
            and len(args) >= 2
            and args[0] == "checkout"
            and args[1] == "-b"
            for head, args in segs
        )
        # Find a segment matching `bash .../update-context-branch.sh ...`
        has_propagate = any(
            head == "bash"
            and any("update-context-branch.sh" in a for a in args)
            for head, args in segs
        )
        self.assertTrue(has_checkout, f"git checkout -b segment missing: {segs}")
        self.assertTrue(has_propagate, f"update-context-branch.sh segment missing: {segs}")

    def test_bare_checkout_without_propagate(self) -> None:
        # The #1328 antipattern: standalone `git checkout -b` without
        # propagation.
        segs = decompose("git checkout -b feat/x")
        has_checkout = any(
            head == "git"
            and len(args) >= 2
            and args[0] == "checkout"
            and args[1] == "-b"
            for head, args in segs
        )
        has_propagate = any(
            head == "bash"
            and any("update-context-branch.sh" in a for a in args)
            for head, args in segs
        )
        self.assertTrue(has_checkout)
        self.assertFalse(has_propagate)

    def test_complex_chain_with_path_arg(self) -> None:
        # The exact #1339 shape.
        cmd = (
            'bash .claude/scripts/lib/write-gate-artifact.sh '
            '--path .runs/resolve-validation.json '
            '--payload "{}" --skill resolve '
            '&& bash .claude/scripts/advance-state.sh resolve 8'
        )
        segs = decompose(cmd)
        self.assertEqual(len(segs), 2)
        self.assertEqual(segs[0][0], "bash")
        # write-gate-artifact.sh is the first arg
        self.assertTrue(segs[0][1][0].endswith("write-gate-artifact.sh"))
        # --path .runs/resolve-validation.json is in args
        self.assertIn("--path", segs[0][1])
        idx = segs[0][1].index("--path")
        self.assertEqual(segs[0][1][idx + 1], ".runs/resolve-validation.json")
        # second segment is advance-state.sh
        self.assertEqual(segs[1][0], "bash")
        self.assertTrue(segs[1][1][0].endswith("advance-state.sh"))


if __name__ == "__main__":
    unittest.main()
