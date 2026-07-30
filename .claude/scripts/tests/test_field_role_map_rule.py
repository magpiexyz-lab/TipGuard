#!/usr/bin/env python3
"""Behavioral tests for verify-linter.sh check_field_role_map().

Validates that the cross-file coherence rule catches the regressions it's
designed for (#1024 prevention class) and doesn't false-positive.

Tests construct a temporary repo skeleton with:
  - .claude/scripts/verify-linter.sh (symlink or copy from real one)
  - .claude/patterns/state-registry.json (minimal valid)
  - .claude/patterns/template-coherence-rules.json (configurable per test)
  - .claude/scripts/lib/derive_pages.py (real one)
  - test consumer files (varied per test)

Then runs verify-linter and asserts CROSS_FILE_CONTRADICTION findings match
expectations.

Run via: python3 .claude/scripts/tests/test_field_role_map_rule.py
Or via:  bash .claude/scripts/tests/run-all.sh
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


REAL_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
LINTER = os.path.join(REAL_REPO, ".claude", "scripts", "verify-linter.sh")
LIB_DIR = os.path.join(REAL_REPO, ".claude", "scripts", "lib")


def _setup_minimal_repo(tmpdir: str, rules: dict, consumers: dict[str, str]):
    """Create a minimal repo skeleton for the linter to scan.

    rules: dict to write as template-coherence-rules.json
    consumers: dict of {relative_path: content} for files in the rule
    """
    # Mirror the linter and lib into tmpdir so it has the same path layout
    os.makedirs(os.path.join(tmpdir, ".claude/scripts/lib"), exist_ok=True)
    os.makedirs(os.path.join(tmpdir, ".claude/patterns"), exist_ok=True)
    os.makedirs(os.path.join(tmpdir, ".claude/skills"), exist_ok=True)

    # Copy the real linter script (it computes REPO_ROOT from its own location)
    shutil.copy(LINTER, os.path.join(tmpdir, ".claude/scripts/verify-linter.sh"))
    # Copy lib/ alongside the linter so the upcoming Python-package refactor
    # (which puts business logic under .claude/scripts/lib/linter/) doesn't
    # break this fixture. Idempotent today: linter is still self-contained.
    if os.path.isdir(LIB_DIR):
        shutil.copytree(
            LIB_DIR,
            os.path.join(tmpdir, ".claude/scripts/lib"),
            dirs_exist_ok=True,
        )
    # Empty registry (no skills) — lint won't find any state files; that's fine
    with open(os.path.join(tmpdir, ".claude/patterns/state-registry.json"), "w") as f:
        json.dump({}, f)
    # Rules file
    with open(os.path.join(tmpdir, ".claude/patterns/template-coherence-rules.json"), "w") as f:
        json.dump(rules, f)
    # Consumer files
    for rel_path, content in consumers.items():
        full = os.path.join(tmpdir, rel_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(content)


def _run_linter(tmpdir: str) -> tuple[int, str]:
    """Run linter in tmpdir; return (exit_code, stdout)."""
    result = subprocess.run(
        ["bash", os.path.join(tmpdir, ".claude/scripts/verify-linter.sh")],
        capture_output=True,
        text=True,
        cwd=tmpdir,
    )
    return result.returncode, result.stdout


class TestFieldRoleMapRule(unittest.TestCase):
    """Validate check_field_role_map() catches drift and accepts compliant code."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_consumer_with_canonical_function_passes(self):
        """Consumer that calls derive_scope_pages() has no findings."""
        rules = {"rules": [{
            "id": "test-rule",
            "type": "field_role_map",
            "field": "golden_path",
            "canonical_function": "derive_scope_pages",
            "consumers": [".claude/agents/test-consumer.md"],
        }]}
        consumers = {
            ".claude/agents/test-consumer.md": "# Test\n\nCall `derive_scope_pages(experiment)` to get pages.\n"
        }
        _setup_minimal_repo(self.tmpdir, rules, consumers)
        rc, out = _run_linter(self.tmpdir)
        self.assertEqual(rc, 0, f"linter should pass, got: {out}")
        self.assertNotIn("CROSS_FILE_CONTRADICTION", out)

    def test_consumer_with_scoped_pragma_passes(self):
        """Consumer with heading-scoped coherence-allow pragma is accepted."""
        rules = {"rules": [{
            "id": "test-rule",
            "type": "field_role_map",
            "field": "golden_path",
            "canonical_function": "derive_scope_pages",
            "consumers": [".claude/agents/test-consumer.md"],
        }]}
        consumers = {
            ".claude/agents/test-consumer.md": (
                "<!-- coherence-allow: raw-golden_path (sequence-step) "
                "scope=[\"## Order\"] -->\n"
                "# Test\n\n## Order\n\nIterate over golden_path in order.\n"
            )
        }
        _setup_minimal_repo(self.tmpdir, rules, consumers)
        rc, out = _run_linter(self.tmpdir)
        self.assertEqual(rc, 0, f"linter should pass, got: {out}")

    def test_consumer_with_legacy_file_scope_pragma_warns(self):
        """File-scope pragma (no scope=[...]) is DEPRECATED — emits WARN
        finding but still allows the raw access. Future versions will block."""
        rules = {"rules": [{
            "id": "test-rule",
            "type": "field_role_map",
            "field": "golden_path",
            "canonical_function": "derive_scope_pages",
            "consumers": [".claude/agents/test-consumer.md"],
        }]}
        consumers = {
            ".claude/agents/test-consumer.md": (
                "<!-- coherence-allow: raw-golden_path (sequence-step) -->\n"
                "# Test\n\n## Order\n\nIterate over golden_path in order.\n"
            )
        }
        _setup_minimal_repo(self.tmpdir, rules, consumers)
        rc, out = _run_linter(self.tmpdir)
        self.assertNotEqual(rc, 0, "legacy pragma should WARN (non-zero exit)")
        self.assertIn("legacy file-scope pragma", out)

    def test_consumer_without_canonical_or_pragma_fails(self):
        """Consumer that mentions neither canonical nor pragma triggers finding."""
        rules = {"rules": [{
            "id": "test-rule",
            "type": "field_role_map",
            "field": "golden_path",
            "canonical_function": "derive_scope_pages",
            "consumers": [".claude/agents/test-consumer.md"],
        }]}
        consumers = {
            ".claude/agents/test-consumer.md": "# Test\n\nReads golden_path[0] from experiment.yaml.\n"
        }
        _setup_minimal_repo(self.tmpdir, rules, consumers)
        rc, out = _run_linter(self.tmpdir)
        self.assertNotEqual(rc, 0, "linter should fail (missing canonical and pragma)")
        self.assertIn("CROSS_FILE_CONTRADICTION", out)
        self.assertIn("test-consumer.md", out)

    def test_forbidden_len_pattern_fails_even_with_pragma(self):
        """len(golden_path) is forbidden UNCONDITIONALLY — pragma cannot whitelist it.

        This is the #1024 prevention guarantee: count-based access defeats
        the centralization purpose, so it's blocked regardless of pragma.
        """
        rules = {"rules": [{
            "id": "test-rule",
            "type": "field_role_map",
            "field": "golden_path",
            "canonical_function": "derive_scope_pages",
            "consumers": [".claude/agents/test-consumer.md"],
        }]}
        consumers = {
            ".claude/agents/test-consumer.md": (
                "<!-- coherence-allow: raw-golden_path (sequence-step) -->\n"
                "# Test\n\n"
                "Also calls derive_scope_pages(experiment) for some things.\n"
                "Then: count = len(golden_path)\n"  # Forbidden!
            )
        }
        _setup_minimal_repo(self.tmpdir, rules, consumers)
        rc, out = _run_linter(self.tmpdir)
        self.assertNotEqual(rc, 0, "linter should fail on len(golden_path)")
        self.assertIn("forbidden count-based access", out)
        self.assertIn("len(golden_path", out)

    def test_forbidden_set_pattern_fails(self):
        """set(golden_path) is also forbidden unconditionally."""
        rules = {"rules": [{
            "id": "test-rule",
            "type": "field_role_map",
            "field": "golden_path",
            "canonical_function": "derive_scope_pages",
            "consumers": [".claude/agents/test-consumer.md"],
        }]}
        consumers = {
            ".claude/agents/test-consumer.md": (
                "# Test\n\n"
                "Has derive_scope_pages mention.\n"
                "But also: pages = set(golden_path)\n"
            )
        }
        _setup_minimal_repo(self.tmpdir, rules, consumers)
        rc, out = _run_linter(self.tmpdir)
        self.assertNotEqual(rc, 0, "linter should fail on set(golden_path)")
        self.assertIn("forbidden count-based access", out)

    def test_missing_consumer_file_fails(self):
        """Consumer listed in rule but not present on disk → finding."""
        rules = {"rules": [{
            "id": "test-rule",
            "type": "field_role_map",
            "field": "golden_path",
            "canonical_function": "derive_scope_pages",
            "consumers": [".claude/nonexistent/missing-file.md"],
        }]}
        _setup_minimal_repo(self.tmpdir, rules, consumers={})
        rc, out = _run_linter(self.tmpdir)
        self.assertNotEqual(rc, 0)
        self.assertIn("not found on disk", out)

    def test_warn_only_flag_returns_zero_even_with_findings(self):
        """--warn-only suppresses non-zero exit code."""
        rules = {"rules": [{
            "id": "test-rule",
            "type": "field_role_map",
            "field": "golden_path",
            "canonical_function": "derive_scope_pages",
            "consumers": [".claude/agents/test-consumer.md"],
        }]}
        consumers = {
            ".claude/agents/test-consumer.md": "# Test\n\nReads golden_path raw.\n"
        }
        _setup_minimal_repo(self.tmpdir, rules, consumers)
        result = subprocess.run(
            ["bash", os.path.join(self.tmpdir, ".claude/scripts/verify-linter.sh"), "--warn-only"],
            capture_output=True,
            text=True,
            cwd=self.tmpdir,
        )
        self.assertEqual(result.returncode, 0, "--warn-only should exit 0")
        self.assertIn("CROSS_FILE_CONTRADICTION", result.stdout)

    def test_json_flag_emits_valid_json(self):
        """--json produces parseable JSON with summary counts."""
        rules = {"rules": []}
        _setup_minimal_repo(self.tmpdir, rules, consumers={})
        result = subprocess.run(
            ["bash", os.path.join(self.tmpdir, ".claude/scripts/verify-linter.sh"), "--json"],
            capture_output=True,
            text=True,
            cwd=self.tmpdir,
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertIn("summary", data)
        self.assertIn("cross_file_contradiction", data["summary"])
        self.assertEqual(data["summary"]["cross_file_contradiction"], 0)


class TestPerSectionFieldRoleMap(unittest.TestCase):
    """#1024 follow-up: heading-scoped pragma check catches mixed-semantic files."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _rules(self):
        return {"rules": [{
            "id": "scope-rule",
            "type": "field_role_map",
            "field": "golden_path",
            "canonical_function": "derive_scope_pages",
            "consumers": [".claude/agents/test-consumer.md"],
        }]}

    def test_mixed_file_canonical_in_one_section_raw_in_another_fails(self):
        """Pre-#1024 bug: file had derive_scope_pages in sitemap section but
        raw golden_path in page-generation section. Per-file mention check
        silently passed. Per-section check must block."""
        rules = self._rules()
        consumers = {
            ".claude/agents/test-consumer.md": (
                "# Title\n\n"
                "## Sitemap\n\n"
                "Call derive_scope_pages(experiment) to build sitemap.\n\n"
                "## Pages\n\n"
                "For each page in golden_path: create page.tsx\n"
            )
        }
        _setup_minimal_repo(self.tmpdir, rules, consumers)
        rc, out = _run_linter(self.tmpdir)
        self.assertNotEqual(rc, 0, f"expected failure, got: {out}")
        self.assertIn("Pages", out)

    def test_scope_pragma_covers_named_heading(self):
        """Pragma with scope=[H2] covers that block only."""
        rules = self._rules()
        consumers = {
            ".claude/agents/test-consumer.md": (
                "<!-- coherence-allow: raw-golden_path (sequence-step) "
                "scope=[\"## Walk Steps\"] -->\n"
                "# Title\n\n"
                "## Walk Steps\n\n"
                "For each golden_path step in order.\n"
            )
        }
        _setup_minimal_repo(self.tmpdir, rules, consumers)
        rc, out = _run_linter(self.tmpdir)
        self.assertEqual(rc, 0, f"expected pass, got: {out}")

    def test_scope_pragma_does_not_cover_other_headings(self):
        """Pragma scoped to H2-A does not cover H2-B — raw in H2-B fails."""
        rules = self._rules()
        consumers = {
            ".claude/agents/test-consumer.md": (
                "<!-- coherence-allow: raw-golden_path (sequence-step) "
                "scope=[\"## Covered\"] -->\n"
                "# Title\n\n"
                "## Covered\n\n"
                "Walk golden_path in order.\n\n"
                "## Not Covered\n\n"
                "For each golden_path page: do thing.\n"
            )
        }
        _setup_minimal_repo(self.tmpdir, rules, consumers)
        rc, out = _run_linter(self.tmpdir)
        self.assertNotEqual(rc, 0, f"expected failure, got: {out}")
        self.assertIn("Not Covered", out)

    def test_scope_pragma_references_missing_heading_fails(self):
        """Pragma scope=[H] where H doesn't exist must be flagged (rename guard)."""
        rules = self._rules()
        consumers = {
            ".claude/agents/test-consumer.md": (
                "<!-- coherence-allow: raw-golden_path (sequence-step) "
                "scope=[\"## Ghost\"] -->\n"
                "# Title\n\n"
                "## Renamed\n\n"
                "Walk golden_path steps.\n"
            )
        }
        _setup_minimal_repo(self.tmpdir, rules, consumers)
        rc, out = _run_linter(self.tmpdir)
        self.assertNotEqual(rc, 0, f"expected failure, got: {out}")
        self.assertIn("references heading not found", out)

    def test_canonical_in_same_section_passes(self):
        """derive_scope_pages in same H2 block as raw golden_path passes."""
        rules = self._rules()
        consumers = {
            ".claude/agents/test-consumer.md": (
                "# Title\n\n"
                "## Section\n\n"
                "Call derive_scope_pages(experiment) first.\n"
                "Then iterate golden_path for funnel test ordering.\n"
            )
        }
        _setup_minimal_repo(self.tmpdir, rules, consumers)
        rc, out = _run_linter(self.tmpdir)
        self.assertEqual(rc, 0, f"expected pass, got: {out}")

    def test_occurrences_inside_pragma_are_ignored(self):
        """Raw `golden_path` word appearing inside pragma itself is not a
        consumption point."""
        rules = self._rules()
        consumers = {
            ".claude/agents/test-consumer.md": (
                "<!-- coherence-allow: raw-golden_path (sequence-step) "
                "scope=[\"## Use It\"] — mentions golden_path in rationale. -->\n"
                "# Title\n\n"
                "## Use It\n\n"
                "Walk golden_path steps.\n"
            )
        }
        _setup_minimal_repo(self.tmpdir, rules, consumers)
        rc, out = _run_linter(self.tmpdir)
        self.assertEqual(rc, 0, f"expected pass, got: {out}")

    def test_legacy_file_scope_pragma_emits_warn_not_block(self):
        """Legacy pragma without scope=[...] is allowed but WARNs once."""
        rules = self._rules()
        consumers = {
            ".claude/agents/test-consumer.md": (
                "<!-- coherence-allow: raw-golden_path (sequence-step) -->\n"
                "# Title\n\n"
                "## Section\n\n"
                "Walk golden_path steps.\n"
            )
        }
        _setup_minimal_repo(self.tmpdir, rules, consumers)
        rc, out = _run_linter(self.tmpdir)
        self.assertNotEqual(rc, 0,
            "WARN still counts as CROSS_FILE_CONTRADICTION finding → non-zero exit")
        self.assertIn("legacy file-scope pragma", out)

    def test_h3_under_scoped_h2_is_covered(self):
        """Scope=[H2] cascades to H3 children inside that H2."""
        rules = self._rules()
        consumers = {
            ".claude/agents/test-consumer.md": (
                "<!-- coherence-allow: raw-golden_path (sequence-step) "
                "scope=[\"## Parent\"] -->\n"
                "# Title\n\n"
                "## Parent\n\n"
                "### Child\n\n"
                "Walk golden_path steps.\n"
            )
        }
        _setup_minimal_repo(self.tmpdir, rules, consumers)
        rc, out = _run_linter(self.tmpdir)
        self.assertEqual(rc, 0, f"expected pass, got: {out}")


class TestDiscoverConsumersRule(unittest.TestCase):
    """#1024 follow-up: discover_consumers flags grep-drift vs authoritative list."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _rules(self, authoritative, excludes=None):
        return {"rules": [
            {
                "id": "role-map",
                "type": "field_role_map",
                "field": "golden_path",
                "canonical_function": "derive_scope_pages",
                "consumers": authoritative,
            },
            {
                "id": "discover",
                "type": "discover_consumers",
                "field": "golden_path",
                "against_rule": "role-map",
                "severity": "warn",
                "path_excludes": excludes or [],
                "consumption_patterns": [
                    r"\.get\(['\"]golden_path",
                    r"for\s+\w+\s+in\s+[^\n]{0,100}golden_path",
                    r"\bgolden_path\s+step",
                ],
            },
        ]}

    def test_unlisted_consumer_flagged_as_drift(self):
        """File that matches consumption-pattern but isn't listed → WARN."""
        rules = self._rules(authoritative=[])
        consumers = {
            ".claude/agents/unlisted.md": "# Foo\nfor step in golden_path: do\n"
        }
        _setup_minimal_repo(self.tmpdir, rules, consumers)
        rc, out = _run_linter(self.tmpdir)
        self.assertIn("unlisted.md", out)
        self.assertIn("not listed", out)

    def test_excluded_path_not_flagged(self):
        """path_excludes entries are silently skipped."""
        rules = self._rules(
            authoritative=[],
            excludes=[".claude/templates/"],
        )
        consumers = {
            ".claude/templates/schema.md": "# Schema\nfor step in golden_path: do\n"
        }
        _setup_minimal_repo(self.tmpdir, rules, consumers)
        rc, out = _run_linter(self.tmpdir)
        self.assertNotIn("schema.md", out)

    def test_successfully_migrated_consumer_not_flagged_as_stale(self):
        """File in consumers list that uses only canonical (no raw refs) is
        NOT flagged stale — it's a successfully migrated consumer."""
        rules = self._rules(authoritative=[".claude/agents/migrated.md"])
        consumers = {
            ".claude/agents/migrated.md":
                "# Migrated\nCall derive_scope_pages(experiment) directly.\n"
        }
        _setup_minimal_repo(self.tmpdir, rules, consumers)
        rc, out = _run_linter(self.tmpdir)
        self.assertNotIn("Remove from consumers list", out,
                         "migrated consumer should not be flagged stale")


if __name__ == "__main__":
    unittest.main(verbosity=2)
