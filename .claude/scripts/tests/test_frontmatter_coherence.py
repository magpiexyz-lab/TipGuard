#!/usr/bin/env python3
"""test_frontmatter_coherence.py — exercise the AOC v1.1 R4 rule (closes #1056).

Validates check_frontmatter_artifact_consistency in verify-linter.sh:
  * Schema declares fields → writer must emit each
  * Schema lists consumers → each consumer must reference at least one
    declared field; consumers that don't are flagged stale
  * Stale-name typo detection: multi-word snake_case tokens close to a
    declared name but not exactly matching are flagged

Approach: build an isolated temp .claude/ tree, write a minimal schema +
template-coherence-rules with a single R4 entry, run the linter, parse
output for findings.
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
LINTER = ROOT / ".claude/scripts/verify-linter.sh"


def _setup_repo() -> Path:
    """Create a minimal repo: copy .claude/scripts/verify-linter.sh and its
    deps, plus a synthetic schema + rules + writer + consumer."""
    tmp = Path(tempfile.mkdtemp(prefix="test-frontmatter-r4-"))
    # Copy entire .claude tree (linter pulls helpers from many places).
    shutil.copytree(ROOT / ".claude", tmp / ".claude", dirs_exist_ok=True)
    # We override the rules and schema files for the test.
    return tmp


def _run_linter(repo: Path, *args) -> tuple[int, str, str]:
    """Run the linter COPIED INTO the test repo. The linter resolves
    REPO_ROOT from its own location ($(dirname $0)/../..), so invoking the
    original ROOT linter would target the original repo. Use the copy."""
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    repo_linter = repo / ".claude/scripts/verify-linter.sh"
    proc = subprocess.run(
        ["bash", str(repo_linter), *args],
        capture_output=True, text=True, env=env, cwd=str(repo), timeout=60,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _set_rule(repo: Path, rule: dict) -> None:
    """Replace template-coherence-rules.json with a single-rule file for testing."""
    p = repo / ".claude/patterns/template-coherence-rules.json"
    p.write_text(json.dumps({"rules": [rule]}, indent=2))


def _set_schema(repo: Path, schema: dict) -> None:
    p = repo / ".claude/patterns/test-frontmatter.json"
    p.write_text(json.dumps(schema, indent=2))


class TestFrontmatterCoherence(unittest.TestCase):
    def setUp(self):
        self.repo = _setup_repo()

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def _make_writer(self, fields_emitted: list[str]) -> Path:
        """Synthetic writer that emits the listed YAML keys."""
        p = self.repo / ".claude/skills/_test/state-writer.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        body = "# test writer\n\n```\n"
        for f in fields_emitted:
            body += f"{f}: <value>\n"
        body += "```\n"
        p.write_text(body)
        return p.relative_to(self.repo)

    def _make_consumer(self, refs: list[str], extras: str = "") -> Path:
        p = self.repo / ".claude/scripts/_test_consumer.py"
        body = "# synthetic consumer\n"
        for r in refs:
            body += f"# reads {r} from frontmatter\n"
        body += extras
        p.write_text(body)
        return p.relative_to(self.repo)

    def _r4_finding(self, output: str, needle: str) -> bool:
        return "(frontmatter_artifact_consistency/" in output and needle in output

    def test_writer_must_emit_every_declared_field(self):
        writer_path = self._make_writer(["timestamp", "build_attempts"])  # missing fix_log_entries
        consumer_path = self._make_consumer(["build_attempts"])
        _set_schema(self.repo, {
            "writer": str(writer_path),
            "fields": {
                "timestamp": {"type": "string", "required": True, "description": "x"},
                "build_attempts": {"type": "integer", "required": True, "description": "x"},
                "fix_log_entries": {"type": "integer", "required": True, "description": "x"},
            },
            "consumers": [str(consumer_path)],
        })
        _set_rule(self.repo, {
            "id": "test-r4",
            "type": "frontmatter_artifact_consistency",
            "severity": "block",
            "schema_path": ".claude/patterns/test-frontmatter.json",
            "writer": str(writer_path),
            "consumers": [str(consumer_path)],
        })
        rc, out, err = _run_linter(self.repo, "--strict-aoc")
        self.assertTrue(self._r4_finding(out, "fix_log_entries"),
                        f"expected R4 finding for missing fix_log_entries, got: {out}")

    def test_consumer_with_no_declared_field_is_flagged_stale(self):
        writer_path = self._make_writer(["timestamp", "build_attempts", "fix_log_entries"])
        # Consumer doesn't reference any declared field
        empty_consumer = self.repo / ".claude/scripts/_test_empty.py"
        empty_consumer.write_text("# unrelated content\n")
        _set_schema(self.repo, {
            "writer": str(writer_path),
            "fields": {
                "timestamp": {"type": "string", "required": True, "description": "x"},
                "build_attempts": {"type": "integer", "required": True, "description": "x"},
                "fix_log_entries": {"type": "integer", "required": True, "description": "x"},
            },
            "consumers": [str(empty_consumer.relative_to(self.repo))],
        })
        _set_rule(self.repo, {
            "id": "test-r4",
            "type": "frontmatter_artifact_consistency",
            "severity": "block",
            "schema_path": ".claude/patterns/test-frontmatter.json",
            "writer": str(writer_path),
            "consumers": [str(empty_consumer.relative_to(self.repo))],
        })
        rc, out, err = _run_linter(self.repo, "--strict-aoc")
        self.assertTrue(
            self._r4_finding(out, "does not reference any declared frontmatter field"),
            f"expected stale-consumer finding, got: {out}",
        )

    def test_typo_in_consumer_is_flagged(self):
        writer_path = self._make_writer(["build_attempts", "fix_log_entries", "hard_gate_failure"])
        # Consumer references the proper field PLUS a typo'd variant
        consumer_path = self._make_consumer(
            ["build_attempts"],
            extras="\n# stale ref: build_attempt: <int>\n",
        )
        _set_schema(self.repo, {
            "writer": str(writer_path),
            "fields": {
                "build_attempts": {"type": "integer", "required": True, "description": "x"},
                "fix_log_entries": {"type": "integer", "required": True, "description": "x"},
                "hard_gate_failure": {"type": "boolean", "required": True, "description": "x"},
            },
            "consumers": [str(consumer_path)],
        })
        _set_rule(self.repo, {
            "id": "test-r4",
            "type": "frontmatter_artifact_consistency",
            "severity": "block",
            "schema_path": ".claude/patterns/test-frontmatter.json",
            "writer": str(writer_path),
            "consumers": [str(consumer_path)],
        })
        rc, out, err = _run_linter(self.repo, "--strict-aoc")
        # 'build_attempt' (singular) is 1 edit away from 'build_attempts'
        self.assertTrue(
            self._r4_finding(out, "build_attempt"),
            f"expected typo finding for build_attempt, got: {out}",
        )

    def test_correctly_aligned_writer_and_consumer_passes(self):
        writer_path = self._make_writer(["build_attempts", "fix_log_entries", "hard_gate_failure"])
        consumer_path = self._make_consumer(["build_attempts", "fix_log_entries", "hard_gate_failure"])
        _set_schema(self.repo, {
            "writer": str(writer_path),
            "fields": {
                "build_attempts": {"type": "integer", "required": True, "description": "x"},
                "fix_log_entries": {"type": "integer", "required": True, "description": "x"},
                "hard_gate_failure": {"type": "boolean", "required": True, "description": "x"},
            },
            "consumers": [str(consumer_path)],
        })
        _set_rule(self.repo, {
            "id": "test-r4",
            "type": "frontmatter_artifact_consistency",
            "severity": "block",
            "schema_path": ".claude/patterns/test-frontmatter.json",
            "writer": str(writer_path),
            "consumers": [str(consumer_path)],
        })
        rc, out, err = _run_linter(self.repo, "--strict-aoc")
        self.assertNotIn(
            "(frontmatter_artifact_consistency/", out,
            f"expected no R4 findings for aligned writer+consumer, got: {out}",
        )

    def test_canonical_repo_passes_r4(self):
        """The real .claude/patterns/template-coherence-rules.json (not the
        synthetic one this test injects) ships with the canonical R4 entry.
        Sanity check by running the linter against the unmodified worktree
        once at the end."""
        # Reset rules to the canonical version copied during _setup_repo
        # (we don't override here — the original template-coherence-rules.json
        # was preserved by shutil.copytree).
        canonical = ROOT / ".claude/patterns/template-coherence-rules.json"
        shutil.copy(canonical, self.repo / ".claude/patterns/template-coherence-rules.json")
        # Reset any synthetic schema we created.
        synth = self.repo / ".claude/patterns/test-frontmatter.json"
        if synth.exists():
            synth.unlink()
        rc, out, err = _run_linter(self.repo, "--strict-aoc")
        self.assertEqual(rc, 0, f"canonical repo should pass R4 strict; out={out} err={err}")


def main():
    if not LINTER.is_file():
        print(f"ERROR: linter not found at {LINTER}", file=sys.stderr)
        return 2
    result = unittest.main(exit=False, verbosity=2).result
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
