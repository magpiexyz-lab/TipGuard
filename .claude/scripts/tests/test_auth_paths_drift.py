#!/usr/bin/env python3
"""test_auth_paths_drift.py — enforce AUTH_PATHS single-source invariant.

`.claude/patterns/render-review-detection.md` and
`.claude/patterns/review-verdict-gate.md` both carry a `// SHARED:AUTH_PATHS`
anchor marking the canonical AUTH_PATHS Set. The anchor comment promises
that the two Sets are equal; this test enforces it.

Failure mode we prevent: adding `/reset-password` to one file but not the
other — the `review-verdict-gate.md` gate would classify a legitimate
auth-redirect as "non-auth" (product redirect → DEGRADED), when it should
be "auth" (session expired → FAIL).

Exit 0 on all-pass, 1 on any failure.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PATTERN_FILES = [
    ROOT / ".claude/patterns/render-review-detection.md",
    ROOT / ".claude/patterns/review-verdict-gate.md",
]

ANCHOR = "// SHARED:AUTH_PATHS"


def extract_auth_paths_sets(file_path: Path) -> list[set[str]]:
    """Return all AUTH_PATHS Set literals following the anchor, per file.

    The anchor is a single-line comment. Immediately after (within 20 lines)
    we expect either a JS `new Set([...])` or a Python `{...}` literal
    containing string paths. Return the set of paths per occurrence.
    """
    content = file_path.read_text()
    sets: list[set[str]] = []

    for idx, line in enumerate(content.splitlines()):
        if ANCHOR not in line:
            continue
        # Look ahead up to 20 lines for a Set literal
        window = "\n".join(content.splitlines()[idx : idx + 20])

        # Try JS form: new Set([...])
        js_match = re.search(r"new Set\(\[([^\]]*)\]\)", window)
        # Try Python form: {"...", "..."}
        py_match = re.search(r"AUTH_PATHS\s*=\s*\{([^}]*)\}", window)

        raw = None
        if js_match:
            raw = js_match.group(1)
        elif py_match:
            raw = py_match.group(1)

        if raw is None:
            continue

        # Extract quoted strings
        paths = set(re.findall(r'"([^"]+)"', raw))
        sets.append(paths)

    return sets


class TestAuthPathsDrift(unittest.TestCase):
    def test_both_files_contain_the_anchor(self):
        for fp in PATTERN_FILES:
            with self.subTest(file=str(fp)):
                content = fp.read_text()
                occurrences = content.count(ANCHOR)
                self.assertGreaterEqual(
                    occurrences,
                    1,
                    f"{fp} must contain the '// SHARED:AUTH_PATHS' anchor at least once",
                )

    def test_all_extracted_sets_are_equal(self):
        all_sets: list[tuple[Path, set[str]]] = []
        for fp in PATTERN_FILES:
            sets = extract_auth_paths_sets(fp)
            self.assertGreater(
                len(sets),
                0,
                f"no AUTH_PATHS Set literal found after anchor in {fp}",
            )
            for s in sets:
                all_sets.append((fp, s))

        # Compare every pair
        first_path, first_set = all_sets[0]
        for fp, s in all_sets[1:]:
            self.assertEqual(
                first_set,
                s,
                f"AUTH_PATHS drifted between:\n"
                f"  {first_path}: {sorted(first_set)}\n"
                f"  {fp}: {sorted(s)}",
            )

    def test_no_inline_auth_paths_set_literal_outside_anchors(self):
        """Any file outside the canonical patterns + tests that DECLARES
        a new AUTH_PATHS set literal is a drift regression.

        We distinguish DECLARATIONS (which drift) from REFERENCES (which
        don't):
          - Declaration: `const AUTH_PATHS = new Set([...])` (JS) or
            `AUTH_PATHS = {"...", "..."}` (Python set literal). These
            redeclare the set and can drift from the canonical source.
          - Reference: `final_url ∈ AUTH_PATHS` in prose, or a markdown
            table cell mentioning AUTH_PATHS. These are doc references,
            don't drift, and are fine.

        Pattern-match for declarations, ignore mere references.
        """
        import subprocess

        # Look for set literal declarations: JS `new Set([...])` or
        # Python `AUTH_PATHS = {`/`AUTH_PATHS = set([` assigned to
        # AUTH_PATHS specifically.
        declaration_patterns = [
            # JS: AUTH_PATHS = new Set([...])  — the redeclaration shape
            r"\bAUTH_PATHS\s*=\s*new\s+Set\s*\(",
            # Python: AUTH_PATHS = {  (note: only when followed by string
            # to disambiguate from a generic dict)
            r'\bAUTH_PATHS\s*=\s*\{\s*[\'"]',
            # Python: AUTH_PATHS = set( ...
            r"\bAUTH_PATHS\s*=\s*set\s*\(",
        ]

        result = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", ".claude/"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            self.skipTest(f"git ls-files failed: {result.stderr}")
            return

        violations: list[tuple[str, str]] = []
        for line in result.stdout.strip().splitlines():
            path = ROOT / line.strip()
            if not path.is_file():
                continue
            # Skip test files (they may declare fixtures)
            if "scripts/tests/" in str(path):
                continue
            # Skip canonical patterns themselves
            if path in PATTERN_FILES:
                continue
            # Skip the gate script (it's the executable extraction; carries
            # the anchor)
            if str(path).endswith("run-review-verdict-gate.py"):
                continue

            try:
                content = path.read_text()
            except (UnicodeDecodeError, IsADirectoryError):
                continue

            for pat in declaration_patterns:
                m = re.search(pat, content)
                if m:
                    if ANCHOR not in content:
                        violations.append((line.strip(), m.group(0)))

        if violations:
            msg = (
                "AUTH_PATHS set declarations found outside canonical anchors:\n"
                + "\n".join(f"  {p} — declares: {decl}" for p, decl in violations)
                + f"\n\nEither add the '{ANCHOR}' anchor comment (if this is a "
                "shared canonical source), or use one of the canonical pattern "
                "files (render-review-detection.md, review-verdict-gate.md, or "
                "run-review-verdict-gate.py) instead of redeclaring."
            )
            self.fail(msg)


if __name__ == "__main__":
    unittest.main()
