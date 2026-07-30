"""Tests for .claude/scripts/resolve-causal-analyzer.py::parse_line_part.

Regression coverage for issue #985 — parse_line_part must extract a usable
1-based integer line number from every divergence_point line-part form that
appears in practice (integer, range, csv, parenthesized annotation, and the
legacy-bundled form the state-3 producer contract now forbids).
"""

import importlib.util
import os
import sys

import pytest

HERE = os.path.dirname(__file__)
REPO_ROOT = os.path.abspath(os.path.join(HERE, ".."))
ANALYZER_PATH = os.path.join(REPO_ROOT, ".claude", "scripts", "resolve-causal-analyzer.py")

# The analyzer filename contains a dash, which blocks a plain `import`.
# Load it as a module via importlib so the tests can call `parse_line_part`.
spec = importlib.util.spec_from_file_location("resolve_causal_analyzer", ANALYZER_PATH)
assert spec is not None, f"cannot load {ANALYZER_PATH}"
analyzer = importlib.util.module_from_spec(spec)
sys.modules["resolve_causal_analyzer"] = analyzer
spec.loader.exec_module(analyzer)

parse_line_part = analyzer.parse_line_part


class TestParseLinePart:
    def test_single_integer(self):
        assert parse_line_part("34") == (34, "integer")

    def test_single_integer_with_whitespace(self):
        assert parse_line_part("  42  ") == (42, "integer")

    def test_range(self):
        line, note = parse_line_part("34-55")
        assert line == 34
        assert note.startswith("range")

    def test_range_with_spaces(self):
        line, note = parse_line_part("34 - 55")
        assert line == 34
        assert note.startswith("range")

    def test_csv(self):
        line, note = parse_line_part("180,217,261")
        assert line == 180
        assert note.startswith("csv")

    def test_csv_with_spaces(self):
        line, note = parse_line_part("180, 217, 261")
        assert line == 180
        assert note.startswith("csv")

    def test_parenthesized_annotation(self):
        assert parse_line_part("144 (G6)") == (144, "integer")

    def test_bundled_fragment_and(self):
        line, note = parse_line_part("34-55 and .claude/x:10")
        assert line == 34
        assert note.startswith("bundled_fragment")

    def test_bundled_fragment_ampersand(self):
        line, note = parse_line_part("34 & 55")
        assert line == 34
        assert note.startswith("bundled_fragment")

    def test_bundled_fragment_semicolon(self):
        line, note = parse_line_part("34; 55")
        assert line == 34
        assert note.startswith("bundled_fragment")

    def test_zero_clamped_to_one(self):
        # Regex captures "0" as first unsigned integer → clamped to 1.
        line, _ = parse_line_part("0")
        assert line == 1

    def test_negative_captures_unsigned(self):
        # Regex captures the unsigned digits; minus sign is ignored.
        line, _ = parse_line_part("-5")
        assert line == 5

    def test_no_digits_returns_none(self):
        assert parse_line_part("no-digits-here") == (None, "no-digits")

    def test_empty_string_returns_none(self):
        assert parse_line_part("") == (None, "no-digits")

    def test_whitespace_only_returns_none(self):
        assert parse_line_part("   ") == (None, "no-digits")

    def test_alpha_suffix(self):
        # "123abc" should still extract 123.
        assert parse_line_part("123abc") == (123, "integer")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
