"""Tests for scripts/lib/stack_knowledge_parser.py."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from lib.stack_knowledge_parser import (
    canonicalize,
    compute_hash,
    is_archive_path,
    iter_stack_knowledge_files,
    parse_stack_knowledge,
    parse_stack_knowledge_file,
    REQUIRED_FIELDS,
    MATURITY_VALUES,
    COMPOSITE_KEYS,
    STACK_KNOWLEDGE_SCAN_PATHS,
    EXCLUDE_BASENAMES,
)


class TestCanonicalize:
    def test_trailing_space(self):
        assert canonicalize("foo ") == "foo"

    def test_leading_space(self):
        assert canonicalize(" foo") == "foo"

    def test_case(self):
        assert canonicalize("FOO") == "foo"
        assert canonicalize("Foo Bar") == "foo bar"

    def test_hyphen_underscore_equivalence(self):
        assert canonicalize("foo-bar") == canonicalize("foo_bar") == canonicalize("foo bar") == "foo bar"

    def test_collapses_internal_whitespace(self):
        assert canonicalize("a    b\t\tc") == "a b c"

    def test_unicode_passthrough(self):
        assert canonicalize("Café") == "café"

    def test_empty_string(self):
        assert canonicalize("") == ""

    def test_raises_on_non_string(self):
        with pytest.raises(TypeError):
            canonicalize(42)  # type: ignore[arg-type]


class TestComputeHash:
    def _base(self):
        return {
            "root_cause_class": "missing-archetype-guard",
            "divergence_pattern": "skill-branches-only-two-archetypes",
            "stack_scope": "archetypes/cli",
        }

    def test_length_is_12(self):
        h = compute_hash(self._base())
        assert len(h) == 12
        assert all(c in "0123456789abcdef" for c in h)

    def test_canonicalization_invariance(self):
        """Surface-different composites that canonicalize identically must hash identically."""
        a = {
            "root_cause_class": "Missing-Archetype-Guard",
            "divergence_pattern": "skill-branches-only-two-archetypes ",
            "stack_scope": "Archetypes/Cli",
        }
        b = {
            "root_cause_class": "missing_archetype guard",
            "divergence_pattern": "  SKILL_BRANCHES only two archetypes",
            "stack_scope": "archetypes/cli",
        }
        c = {
            "root_cause_class": "missing archetype guard",
            "divergence_pattern": "skill branches only two archetypes",
            "stack_scope": "archetypes/CLI",
        }
        assert compute_hash(a) == compute_hash(b) == compute_hash(c)

    def test_slash_preserved(self):
        """Slashes (common in stack_scope paths) are not whitespace-equivalent."""
        with_slash = {"root_cause_class": "x", "divergence_pattern": "y", "stack_scope": "framework/nextjs"}
        with_space = {"root_cause_class": "x", "divergence_pattern": "y", "stack_scope": "framework nextjs"}
        assert compute_hash(with_slash) != compute_hash(with_space)

    def test_stable_under_key_reordering(self):
        a = {
            "root_cause_class": "x",
            "divergence_pattern": "y",
            "stack_scope": "z",
        }
        b = {
            "stack_scope": "z",
            "divergence_pattern": "y",
            "root_cause_class": "x",
        }
        assert compute_hash(a) == compute_hash(b)

    def test_different_composite_hashes_differently(self):
        a = {"root_cause_class": "a", "divergence_pattern": "b", "stack_scope": "c"}
        d = {"root_cause_class": "a", "divergence_pattern": "b", "stack_scope": "different"}
        assert compute_hash(a) != compute_hash(d)

    def test_missing_keys_default_empty(self):
        """A composite with missing keys still hashes (empty string slot), doesn't crash."""
        assert len(compute_hash({"root_cause_class": "foo"})) == 12

    def test_raises_on_non_dict(self):
        with pytest.raises(TypeError):
            compute_hash("not a dict")  # type: ignore[arg-type]


class TestParseStackKnowledge:
    def test_empty_file(self):
        assert parse_stack_knowledge("") == []

    def test_missing_section(self):
        content = "# Framework: Next.js\n\nSome prose.\n\n## Patterns\nfoo"
        assert parse_stack_knowledge(content) == []

    def test_single_entry(self):
        content = """# Framework

## Stack Knowledge

```yaml
id: nextjs-demo-guard
maturity: canonical
composite_identity:
  root_cause_class: demo-mode-leak
  divergence_pattern: env-var-check-missing
  stack_scope: framework/nextjs
composite_identity_hash: abcdef012345
symptom_keywords: [demo, production]
fix_template: Add VERCEL guard before DEMO_MODE check
prevention_mechanism: validator
confidence_score: 1.0
occurrence_count: 1
linked_issues: []
first_seen: 2026-01-01
last_seen: 2026-01-01
graduated_to: null
```

Prose follows the fence.
"""
        entries = parse_stack_knowledge(content)
        assert len(entries) == 1
        assert entries[0]["id"] == "nextjs-demo-guard"
        assert entries[0]["maturity"] == "canonical"

    def test_multiple_entries(self):
        content = """## Stack Knowledge

```yaml
id: one
maturity: raw
```

Some prose.

```yaml
id: two
maturity: stable
```
"""
        entries = parse_stack_knowledge(content)
        assert [e["id"] for e in entries] == ["one", "two"]

    def test_stops_at_next_h2(self):
        content = """## Stack Knowledge

```yaml
id: kept
```

## Other Section

```yaml
id: skipped
```
"""
        entries = parse_stack_knowledge(content)
        assert [e["id"] for e in entries] == ["kept"]

    def test_malformed_yaml_skipped(self):
        content = """## Stack Knowledge

```yaml
id: good
maturity: raw
```

```yaml
this: is:: not: valid: yaml: ::
  - broken
```

```yaml
id: also-good
```
"""
        entries = parse_stack_knowledge(content)
        ids = [e.get("id") for e in entries]
        assert "good" in ids
        assert "also-good" in ids

    def test_non_yaml_fence_ignored(self):
        content = """## Stack Knowledge

```bash
echo "not a yaml entry"
```

```yaml
id: real
```
"""
        entries = parse_stack_knowledge(content)
        assert len(entries) == 1
        assert entries[0]["id"] == "real"


class TestConstants:
    def test_required_fields_contains_identity_hash(self):
        assert "composite_identity_hash" in REQUIRED_FIELDS
        assert "composite_identity" in REQUIRED_FIELDS

    def test_maturity_values(self):
        assert MATURITY_VALUES == {"raw", "stable", "canonical"}

    def test_composite_keys(self):
        assert COMPOSITE_KEYS == ("root_cause_class", "divergence_pattern", "stack_scope")


class TestIsArchivePath:
    def test_archive_suffix_true(self):
        assert is_archive_path(".claude/stacks/framework/nextjs.archive.md") is True
        assert is_archive_path("nextjs.archive.md") is True

    def test_non_archive_false(self):
        assert is_archive_path(".claude/stacks/framework/nextjs.md") is False
        assert is_archive_path(".claude/stacks/framework/archive.md") is False

    def test_substring_false_positive_rejected(self):
        """Directory named archive.md.* must not match — we require the exact .archive.md suffix."""
        assert is_archive_path(".claude/stacks/archive.md.stale/foo.md") is False
        assert is_archive_path("some/archive.md/inner.md") is False

    def test_non_string_returns_false(self):
        assert is_archive_path(None) is False  # type: ignore[arg-type]
        assert is_archive_path(42) is False  # type: ignore[arg-type]


class TestParseStackKnowledgeFile:
    def test_archive_path_returns_empty(self, tmp_path):
        """Even if the archive file contains valid Stack Knowledge YAML, reader returns []."""
        p = tmp_path / "nextjs.archive.md"
        p.write_text(
            "## Stack Knowledge\n\n```yaml\nid: archived-entry\nmaturity: canonical\n```\n"
        )
        assert parse_stack_knowledge_file(str(p)) == []

    def test_missing_file_returns_empty(self):
        assert parse_stack_knowledge_file("/nonexistent/path/to/file.md") == []

    def test_real_file_parses(self, tmp_path):
        p = tmp_path / "nextjs.md"
        p.write_text(
            "## Stack Knowledge\n\n```yaml\nid: live-entry\nmaturity: stable\n```\n"
        )
        entries = parse_stack_knowledge_file(str(p))
        assert len(entries) == 1
        assert entries[0]["id"] == "live-entry"

    def test_absent_section_returns_empty(self, tmp_path):
        p = tmp_path / "nextjs.md"
        p.write_text("# Framework: Next.js\n\nNo stack knowledge section here.\n")
        assert parse_stack_knowledge_file(str(p)) == []


class TestIterStackKnowledgeFiles:
    """#1285: single source of truth for cross-directory Stack Knowledge discovery.

    iter_stack_knowledge_files() must enumerate the same scan surface every
    consumer (CI, validators, skill states) sees. Regressions here would let
    one consumer drift from the others — exactly the failure mode #1285 fixed.
    """

    def test_paths_constant_includes_lib_readme(self):
        """The lib/README.md surface must remain in STACK_KNOWLEDGE_SCAN_PATHS.

        Removing it would silently break /solve Phase 1 Agent 2's auto-discovery
        of reusable lib helpers — the regression #1285 was filed to prevent.
        """
        assert ".claude/scripts/lib/README.md" in STACK_KNOWLEDGE_SCAN_PATHS
        assert ".claude/stacks/**/*.md" in STACK_KNOWLEDGE_SCAN_PATHS

    def test_paths_constant_is_immutable(self):
        """Tuple shape prevents callers from mutating the source of truth."""
        assert isinstance(STACK_KNOWLEDGE_SCAN_PATHS, tuple)

    def test_excludes_template_md(self, tmp_path):
        stacks = tmp_path / ".claude" / "stacks"
        stacks.mkdir(parents=True)
        (stacks / "TEMPLATE.md").write_text("# Template\n")
        (stacks / "live.md").write_text("# Live stack\n")
        files = iter_stack_knowledge_files(str(tmp_path))
        assert any("live.md" in f for f in files)
        assert not any("TEMPLATE.md" in f for f in files)

    def test_excludes_archive_files(self, tmp_path):
        stacks = tmp_path / ".claude" / "stacks"
        stacks.mkdir(parents=True)
        (stacks / "live.md").write_text("# Live\n")
        (stacks / "old.archive.md").write_text("# Archive\n")
        files = iter_stack_knowledge_files(str(tmp_path))
        assert any("live.md" in f for f in files)
        assert not any(".archive.md" in f for f in files)

    def test_includes_lib_readme_when_present(self, tmp_path):
        lib = tmp_path / ".claude" / "scripts" / "lib"
        lib.mkdir(parents=True)
        (lib / "README.md").write_text("# `.claude/scripts/lib/`\n## Stack Knowledge\n")
        files = iter_stack_knowledge_files(str(tmp_path))
        assert any(f.endswith(".claude/scripts/lib/README.md") for f in files)

    def test_returns_sorted_unique(self, tmp_path):
        stacks = tmp_path / ".claude" / "stacks" / "framework"
        stacks.mkdir(parents=True)
        (stacks / "b.md").write_text("# B\n")
        (stacks / "a.md").write_text("# A\n")
        files = iter_stack_knowledge_files(str(tmp_path))
        assert files == sorted(set(files))

    def test_empty_when_no_paths_match(self, tmp_path):
        # No .claude/ tree at all — every glob returns nothing.
        assert iter_stack_knowledge_files(str(tmp_path)) == []

    def test_template_basename_constant(self):
        """EXCLUDE_BASENAMES is the canonical exclusion set — keep frozen."""
        assert isinstance(EXCLUDE_BASENAMES, frozenset)
        assert "TEMPLATE.md" in EXCLUDE_BASENAMES
