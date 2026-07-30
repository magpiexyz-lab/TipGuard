#!/usr/bin/env python3
"""Tests for #1300 — `lib_helper_stack_knowledge_required` per-helper coverage.

Locks the contract:
- Multi-caller helper without README entry → finding.
- `# coherence-allow: not-reusable: <reason>` pragma at module top → suppresses.
- Module-precise `stack_scope: scripts/lib/<module>` README entry → covers.
- Directory-level `stack_scope: scripts/lib` does NOT grandfather (round-2
  caveat 3bf11d4b38d7).
- Substring-collision protection: `validate_evidence` vs
  `validate_evidence_coverage` resolved by exact match.
- Test-path exclusion: callers in `tests/` don't count.
- Agent-md `from <module> import` (no `.lib.` prefix) counted as caller.
- `severity=block` + `--warn-only --strict-aoc` → blocking exit code.

Closes the gap left by `lib-readme-stack-knowledge-required` (must_contain_section
guards heading presence only — not per-helper drift).
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest


REAL_REPO = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
LINTER = os.path.join(REAL_REPO, ".claude", "scripts", "verify-linter.sh")
LIB_DIR = os.path.join(REAL_REPO, ".claude", "scripts", "lib")


# Standard rule used across most tests (matches the production rule shape).
def _rule(severity="block"):
    return {
        "id": "lib-helper-stack-knowledge-required-test",
        "type": "lib_helper_stack_knowledge_required",
        "severity": severity,
        "description": "test fixture for #1300",
        "enumeration_glob": ".claude/scripts/lib/*.py",
        "excluded_basenames": ["__init__.py"],
        "consumption_patterns": [
            {
                "pattern_template": (
                    r"from\s+(?:\.?(?:lib|scripts\.lib)\.)?<module>\s+import\b"
                ),
                "excluded_paths": [
                    "**/tests/**",
                    "**/test_*.py",
                    "**/*_test.py",
                    ".claude/scripts/lib/<module>.py",
                ],
            },
            {
                "pattern_template": r"<module>\.[a-zA-Z_][\w_]*\(",
                "excluded_paths": [
                    "**/tests/**",
                    "**/test_*.py",
                    "**/*_test.py",
                    ".claude/scripts/lib/<module>.py",
                ],
            },
        ],
        "caller_threshold": 2,
        "authoritative_source": ".claude/scripts/lib/README.md",
        "allowed_extensions": [".py", ".md"],
        "pragma": {
            "comment_template": r"# coherence-allow: not-reusable: (.+)",
        },
    }


def _setup_repo(tmpdir, *, helpers, callers, readme_content="", rules=None):
    """Build a minimal repo for the linter:
    - linter binary + lib/ copied
    - empty state-registry.json
    - rules: list with the lib_helper_stack_knowledge_required rule
    - .claude/scripts/lib/<module>.py for each helper (with the helper content)
    - .claude/scripts/lib/README.md with the supplied content (Stack Knowledge entries)
    - additional caller files at the supplied paths
    """
    os.makedirs(os.path.join(tmpdir, ".claude/scripts"), exist_ok=True)
    os.makedirs(os.path.join(tmpdir, ".claude/scripts/lib"), exist_ok=True)
    os.makedirs(os.path.join(tmpdir, ".claude/patterns"), exist_ok=True)
    shutil.copy(LINTER, os.path.join(tmpdir, ".claude/scripts/verify-linter.sh"))
    shutil.copytree(
        LIB_DIR, os.path.join(tmpdir, ".claude/scripts/lib"), dirs_exist_ok=True
    )

    # Overwrite the lib/ directory with our test helpers (the copytree above
    # brings in the real lib/*.py files; we want a clean slate).
    real_lib = os.path.join(tmpdir, ".claude/scripts/lib")
    for fn in os.listdir(real_lib):
        full = os.path.join(real_lib, fn)
        # Keep linter package files; remove ALL real .py helpers to avoid noise.
        if fn in ("linter", "tests"):
            continue
        if os.path.isfile(full) and fn.endswith(".py"):
            os.remove(full)

    # Write our test helpers
    for module_name, content in helpers.items():
        path = os.path.join(tmpdir, ".claude/scripts/lib", f"{module_name}.py")
        with open(path, "w") as f:
            f.write(content)

    # Write the README
    with open(os.path.join(tmpdir, ".claude/scripts/lib/README.md"), "w") as f:
        f.write(readme_content)

    # Write caller files
    for caller_path, caller_content in callers.items():
        full = os.path.join(tmpdir, caller_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(caller_content)

    with open(os.path.join(tmpdir, ".claude/patterns/state-registry.json"), "w") as f:
        json.dump({}, f)
    with open(
        os.path.join(tmpdir, ".claude/patterns/template-coherence-rules.json"), "w"
    ) as f:
        json.dump({"rules": rules or [_rule()]}, f)


def _run(tmpdir, *flags):
    result = subprocess.run(
        ["bash", os.path.join(tmpdir, ".claude/scripts/verify-linter.sh"), *flags],
        capture_output=True,
        text=True,
        cwd=tmpdir,
    )
    return result.returncode, result.stdout, result.stderr


# Sample helper content with a public function.
def _helper(public_func_name="do_thing"):
    return f"def {public_func_name}(x):\n    return x + 1\n"


def _helper_with_pragma(reason="single-callsite by design", public_func_name="do_thing"):
    return (
        f"# coherence-allow: not-reusable: {reason}\n"
        f"def {public_func_name}(x):\n"
        f"    return x + 1\n"
    )


# Sample README content with a single Stack Knowledge entry covering a module.
def _readme_with_entry(module_name, *, entry_id="test-entry"):
    return (
        "# Reusable helpers\n\n"
        "## Stack Knowledge\n\n"
        f"### {entry_id}\n\n"
        f"```yaml\n"
        f"id: {entry_id}\n"
        f"composite_identity:\n"
        f"  root_cause_class: test\n"
        f"  divergence_pattern: test\n"
        f"  stack_scope: scripts/lib/{module_name}\n"
        f"composite_identity_hash: test-hash\n"
        f"fix_template: |\n"
        f"  Use the helper.\n"
        f"prevention_mechanism: test\n"
        f"```\n"
    )


def _readme_with_directory_level_entry(entry_id="legacy-entry"):
    return (
        "# Reusable helpers\n\n"
        "## Stack Knowledge\n\n"
        f"### {entry_id}\n\n"
        f"```yaml\n"
        f"id: {entry_id}\n"
        f"composite_identity:\n"
        f"  root_cause_class: test\n"
        f"  divergence_pattern: test\n"
        f"  stack_scope: scripts/lib\n"  # ← directory-level, must NOT grandfather
        f"composite_identity_hash: test-hash\n"
        f"fix_template: |\n"
        f"  Use the helper.\n"
        f"prevention_mechanism: test\n"
        f"```\n"
    )


class TestCoverage(unittest.TestCase):
    def test_multi_caller_no_entry_fires(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_repo(
                tmpdir,
                helpers={"my_helper": _helper("do_thing")},
                callers={
                    ".claude/skills/A/state.md": (
                        "```python\nfrom my_helper import do_thing\n```\n"
                    ),
                    ".claude/skills/B/state.md": (
                        "```python\nfrom my_helper import do_thing\n```\n"
                    ),
                },
                readme_content="# Reusable helpers\n\n## Stack Knowledge\n\n(no entries)\n",
            )
            rc, stdout, stderr = _run(tmpdir, "--strict-aoc")
        self.assertNotEqual(rc, 0, "Expected finding for uncovered multi-caller helper")
        combined = (stdout or "") + (stderr or "")
        self.assertIn("my_helper", combined)
        self.assertIn("stack_scope: scripts/lib/my_helper", combined)

    def test_pragma_suppresses(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_repo(
                tmpdir,
                helpers={"my_helper": _helper_with_pragma("single-use", "do_thing")},
                callers={
                    ".claude/skills/A/state.md": (
                        "```python\nfrom my_helper import do_thing\n```\n"
                    ),
                    ".claude/skills/B/state.md": (
                        "```python\nfrom my_helper import do_thing\n```\n"
                    ),
                },
                readme_content="# Reusable helpers\n\n## Stack Knowledge\n\n(no entries)\n",
            )
            rc, stdout, stderr = _run(tmpdir, "--strict-aoc")
        self.assertEqual(rc, 0, f"Pragma should suppress finding. stdout={stdout} stderr={stderr}")

    def test_module_precise_entry_covers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_repo(
                tmpdir,
                helpers={"my_helper": _helper("do_thing")},
                callers={
                    ".claude/skills/A/state.md": (
                        "```python\nfrom my_helper import do_thing\n```\n"
                    ),
                    ".claude/skills/B/state.md": (
                        "```python\nfrom my_helper import do_thing\n```\n"
                    ),
                },
                readme_content=_readme_with_entry("my_helper"),
            )
            rc, stdout, stderr = _run(tmpdir, "--strict-aoc")
        self.assertEqual(rc, 0, f"Module-precise entry should cover. stdout={stdout} stderr={stderr}")

    def test_directory_level_entry_does_not_grandfather(self):
        """Round-2 caveat 3bf11d4b38d7: bare `stack_scope: scripts/lib` must NOT
        cover all helpers. Otherwise the existing 3 directory-level entries
        nullify the new rule from day 1.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_repo(
                tmpdir,
                helpers={"my_helper": _helper("do_thing")},
                callers={
                    ".claude/skills/A/state.md": (
                        "```python\nfrom my_helper import do_thing\n```\n"
                    ),
                    ".claude/skills/B/state.md": (
                        "```python\nfrom my_helper import do_thing\n```\n"
                    ),
                },
                readme_content=_readme_with_directory_level_entry(),
            )
            rc, stdout, stderr = _run(tmpdir, "--strict-aoc")
        self.assertNotEqual(
            rc, 0,
            "Directory-level stack_scope: scripts/lib must NOT grandfather per-helper coverage",
        )
        combined = (stdout or "") + (stderr or "")
        self.assertIn("my_helper", combined)


class TestSubstringCollision(unittest.TestCase):
    """Round-1 caveat 4fadbc66277a: substring match is fuzzy. Exact match required."""

    def test_collision_only_exact_match_covers(self):
        """`validate_evidence` (covered) and `validate_evidence_coverage` (uncovered)
        — only the latter should fire even though their names share a prefix.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_repo(
                tmpdir,
                helpers={
                    "validate_evidence": _helper("check"),
                    "validate_evidence_coverage": _helper("check"),
                },
                callers={
                    ".claude/skills/A/state.md": (
                        "```python\n"
                        "from validate_evidence import check\n"
                        "from validate_evidence_coverage import check\n"
                        "```\n"
                    ),
                    ".claude/skills/B/state.md": (
                        "```python\n"
                        "from validate_evidence import check\n"
                        "from validate_evidence_coverage import check\n"
                        "```\n"
                    ),
                },
                # Only validate_evidence covered (module-precise)
                readme_content=_readme_with_entry("validate_evidence"),
            )
            rc, stdout, stderr = _run(tmpdir, "--strict-aoc")
        combined = (stdout or "") + (stderr or "")
        self.assertNotEqual(rc, 0, "Expected finding for validate_evidence_coverage")
        self.assertIn("validate_evidence_coverage", combined)
        # validate_evidence (the covered one) must NOT appear as the SUBJECT
        # of a finding. The finding line format starts with `helper <module>`.
        self.assertNotIn("helper validate_evidence (validate_evidence.py)", combined)


class TestPathExclusion(unittest.TestCase):
    def test_test_callers_dont_count(self):
        """A helper with 1 production caller + 1 test caller has only 1 real
        caller (below threshold=2) → no finding."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_repo(
                tmpdir,
                helpers={"my_helper": _helper("do_thing")},
                callers={
                    ".claude/skills/A/state.md": (
                        "```python\nfrom my_helper import do_thing\n```\n"
                    ),
                    # tests/ caller — must be excluded by `**/tests/**`
                    ".claude/scripts/tests/test_my_helper.py": (
                        "from my_helper import do_thing\n"
                        "def test_x():\n    pass\n"
                    ),
                },
                readme_content="# Reusable helpers\n\n## Stack Knowledge\n\n",
            )
            rc, stdout, stderr = _run(tmpdir, "--strict-aoc")
        self.assertEqual(
            rc, 0,
            f"tests/ caller should be excluded; only 1 production caller → no finding. stdout={stdout} stderr={stderr}",
        )


class TestAgentMdImport(unittest.TestCase):
    """Round-1 caveat 89fd338c6c40: agent-md fenced `from <module> import` (no
    `.lib.` prefix) MUST be counted as a caller."""

    def test_agent_md_fenced_from_import_counted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_repo(
                tmpdir,
                helpers={"concern_id": _helper("concern_id_for")},
                callers={
                    # 2 agent .md files using the bare `from <module> import`
                    # form that an agent's documentation would use.
                    ".claude/agents/foo.md": (
                        "# Agent foo\n\n"
                        "```python\n"
                        "from concern_id import concern_id_for\n"
                        "cid = concern_id_for(...)\n"
                        "```\n"
                    ),
                    ".claude/agents/bar.md": (
                        "# Agent bar\n\n"
                        "```python\n"
                        "from concern_id import concern_id_for\n"
                        "cid = concern_id_for(...)\n"
                        "```\n"
                    ),
                },
                readme_content="# Reusable helpers\n\n## Stack Knowledge\n\n",
            )
            rc, stdout, stderr = _run(tmpdir, "--strict-aoc")
        self.assertNotEqual(
            rc, 0,
            "Agent-md fenced `from concern_id import` should count toward caller threshold",
        )


class TestExcludedBasenamesGlob(unittest.TestCase):
    """Self-audit follow-up: `excluded_basenames` accepts both literal names
    and fnmatch globs so test fixtures inside lib/ (e.g.,
    `.claude/scripts/lib/test_decompose_bash_chain.py`) are filtered from
    enumeration without each being named explicitly."""

    def test_test_glob_excludes_test_fixture_in_lib(self):
        """A test fixture file in lib/ named `test_<name>.py` must be skipped
        even when it has public functions and would otherwise enumerate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_repo(
                tmpdir,
                helpers={
                    # Real helper — should fire if uncovered
                    "real_helper": _helper("do_thing"),
                    # Test fixture file — must be excluded by `test_*.py` glob
                    "test_real_helper": (
                        "def test_thing():\n"
                        "    from real_helper import do_thing\n"
                        "    assert do_thing(1) == 2\n"
                    ),
                },
                callers={
                    ".claude/skills/A/state.md": (
                        "```python\nfrom real_helper import do_thing\n```\n"
                    ),
                    ".claude/skills/B/state.md": (
                        "```python\nfrom real_helper import do_thing\n```\n"
                    ),
                },
                readme_content="# Reusable helpers\n\n## Stack Knowledge\n\n",
            )
            rc, stdout, stderr = _run(tmpdir, "--strict-aoc")
        combined = (stdout or "") + (stderr or "")
        # real_helper is uncovered → must fire
        self.assertNotEqual(rc, 0, "real_helper should fire")
        self.assertIn("real_helper", combined)
        # test_real_helper is excluded → must NOT appear as a finding subject
        self.assertNotIn(
            "helper test_real_helper (test_real_helper.py)", combined,
            "test_real_helper.py should be excluded by `test_*.py` glob",
        )


class TestStrictAocBlocking(unittest.TestCase):
    """Round-2 caveat 36b36a5501aa: severity=block + --warn-only --strict-aoc
    must produce a blocking exit code (i.e., is_strict_aoc=True is registered)."""

    def test_block_severity_under_warn_only_strict_aoc_blocks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_repo(
                tmpdir,
                helpers={"my_helper": _helper("do_thing")},
                callers={
                    ".claude/skills/A/state.md": (
                        "```python\nfrom my_helper import do_thing\n```\n"
                    ),
                    ".claude/skills/B/state.md": (
                        "```python\nfrom my_helper import do_thing\n```\n"
                    ),
                },
                readme_content="# Reusable helpers\n\n## Stack Knowledge\n\n",
                rules=[_rule("block")],
            )
            rc, stdout, stderr = _run(tmpdir, "--warn-only", "--strict-aoc")
        self.assertNotEqual(
            rc, 0,
            f"--warn-only --strict-aoc must block on severity=block findings. "
            f"This locks is_strict_aoc=True registration. stdout={stdout} stderr={stderr}",
        )


if __name__ == "__main__":
    unittest.main()
