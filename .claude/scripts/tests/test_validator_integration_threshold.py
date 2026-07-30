#!/usr/bin/env python3
"""Tests for #1307 — `minimum_integration_count` cardinality threshold on
`validator_integration_required` rule.

Locks the contract:
- Default behavior (field absent) preserves the original "≥1 reference" check.
- `minimum_integration_count: 2` rejects validators referenced in <2 distinct
  integration_point files.
- Cross-file cardinality is enforced: 2 references in the SAME file count as 1
  integration_point (not 2). Per `referenced_in[]` semantics in
  check_validator_integration_required.

These tests guard against the prior-failure shape from
resolve-2026-04-28T03:22:54Z (verify[3a] sampled fs[0] only — partial-coverage
VERIFY shape on per-page traces): the rule now requires distinct-file
cardinality, not just any-found.
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


def _setup_repo(tmpdir, rules, *, integration_files=None, validator_paths=None):
    """Build a minimal repo for the linter:
    - Copies linter binary + lib/
    - Empty state-registry.json (rule references its own integration_points)
    - Writes the given rules JSON
    - Creates each declared validator_path as an empty file
    - Writes each integration file with the supplied content
    """
    os.makedirs(os.path.join(tmpdir, ".claude/scripts"), exist_ok=True)
    os.makedirs(os.path.join(tmpdir, ".claude/patterns"), exist_ok=True)
    shutil.copy(LINTER, os.path.join(tmpdir, ".claude/scripts/verify-linter.sh"))
    shutil.copytree(
        LIB_DIR, os.path.join(tmpdir, ".claude/scripts/lib"), dirs_exist_ok=True
    )
    with open(os.path.join(tmpdir, ".claude/patterns/state-registry.json"), "w") as f:
        json.dump({}, f)
    with open(
        os.path.join(tmpdir, ".claude/patterns/template-coherence-rules.json"), "w"
    ) as f:
        json.dump(rules, f)

    for vpath in validator_paths or []:
        full = os.path.join(tmpdir, vpath)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write("# test fixture validator\n")

    for ipath, content in (integration_files or {}).items():
        full = os.path.join(tmpdir, ipath)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(content)


def _run(tmpdir, *flags):
    result = subprocess.run(
        ["bash", os.path.join(tmpdir, ".claude/scripts/verify-linter.sh"), *flags],
        capture_output=True,
        text=True,
        cwd=tmpdir,
    )
    return result.returncode, result.stdout, result.stderr


# A bash file with the validator basename inside an executable line.
def _bash_fixture(validator_basename):
    return f"#!/bin/bash\nset -e\npython3 .claude/scripts/{validator_basename}\n"


# A markdown file with the validator basename inside a fenced bash block.
def _md_fixture(validator_basename):
    return (
        "# Doc\n\nDescription.\n\n"
        "```bash\n"
        f"python3 .claude/scripts/{validator_basename}\n"
        "```\n"
    )


# A state-registry-shaped JSON with the validator basename inside the "verify"
# key — the rule treats this as executable context.
def _state_registry_fixture(validator_basename):
    return json.dumps(
        {
            "by_skill": {
                "test_skill": {
                    "states": {
                        "1": {
                            "verify": (
                                f'python3 -c "print(1)" && '
                                f"python3 .claude/scripts/{validator_basename}"
                            )
                        }
                    }
                }
            }
        }
    )


class TestThresholdEnforcement(unittest.TestCase):
    """Direct cardinality assertions on `minimum_integration_count`."""

    def test_default_threshold_is_1_backwards_compat(self):
        """Rule WITHOUT minimum_integration_count behaves as count >= 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_repo(
                tmpdir,
                {
                    "rules": [
                        {
                            "id": "compat-test",
                            "type": "validator_integration_required",
                            "severity": "block",
                            "description": "default threshold = 1",
                            "validators": [".claude/scripts/v1.py"],
                            "integration_points": [
                                ".claude/scripts/single.sh",
                            ],
                        }
                    ]
                },
                validator_paths=[".claude/scripts/v1.py"],
                integration_files={
                    ".claude/scripts/single.sh": _bash_fixture("v1.py"),
                },
            )
            rc, stdout, stderr = _run(tmpdir, "--strict-aoc")
        self.assertEqual(rc, 0, f"Expected pass with 1 ref + default threshold. stdout={stdout} stderr={stderr}")

    def test_threshold_2_one_reference_fires(self):
        """minimum_integration_count: 2 with 1 reference → finding."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_repo(
                tmpdir,
                {
                    "rules": [
                        {
                            "id": "threshold-fire",
                            "type": "validator_integration_required",
                            "severity": "block",
                            "description": "threshold=2 fires on 1 ref",
                            "minimum_integration_count": 2,
                            "validators": [".claude/scripts/v1.py"],
                            "integration_points": [
                                ".claude/scripts/site_a.sh",
                                ".claude/patterns/site_b.md",
                            ],
                        }
                    ]
                },
                validator_paths=[".claude/scripts/v1.py"],
                integration_files={
                    ".claude/scripts/site_a.sh": _bash_fixture("v1.py"),
                    ".claude/patterns/site_b.md": "# Doc — no validator reference\n",
                },
            )
            rc, stdout, stderr = _run(tmpdir, "--strict-aoc")
        self.assertNotEqual(rc, 0, "Expected finding when threshold=2 and only 1 site has the validator")
        # Combined output for assertion (linter prints to either stdout or stderr depending on mode)
        combined = (stdout or "") + (stderr or "")
        self.assertIn("v1.py", combined)
        self.assertIn("minimum_integration_count=2", combined)

    def test_threshold_2_two_distinct_files_passes(self):
        """minimum_integration_count: 2 with 2 distinct integration_point files → pass."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_repo(
                tmpdir,
                {
                    "rules": [
                        {
                            "id": "threshold-pass",
                            "type": "validator_integration_required",
                            "severity": "block",
                            "description": "threshold=2 passes on 2 distinct files",
                            "minimum_integration_count": 2,
                            "validators": [".claude/scripts/v1.py"],
                            "integration_points": [
                                ".claude/scripts/site_a.sh",
                                ".claude/patterns/site_b.md",
                            ],
                        }
                    ]
                },
                validator_paths=[".claude/scripts/v1.py"],
                integration_files={
                    ".claude/scripts/site_a.sh": _bash_fixture("v1.py"),
                    ".claude/patterns/site_b.md": _md_fixture("v1.py"),
                },
            )
            rc, stdout, stderr = _run(tmpdir, "--strict-aoc")
        self.assertEqual(
            rc, 0,
            f"Expected pass with 2 distinct refs. stdout={stdout} stderr={stderr}",
        )

    def test_threshold_2_multiple_refs_in_same_file_still_one_count(self):
        """Two references in the SAME integration_point file count as 1, not 2.

        Locks the per-`referenced_in[]` semantics: each integration_point file
        contributes at most 1 to the cardinality, regardless of how many lines
        within it match the validator basename. Defends against the original
        #1307 failure mode (state-registry.json line 11b chaining 2 validators
        on one line — single-line edit could dereference both).
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            same_file_double_ref = (
                "#!/bin/bash\nset -e\n"
                "python3 .claude/scripts/v1.py\n"
                "python3 .claude/scripts/v1.py  # second invocation, same file\n"
            )
            _setup_repo(
                tmpdir,
                {
                    "rules": [
                        {
                            "id": "single-file-double-ref",
                            "type": "validator_integration_required",
                            "severity": "block",
                            "description": "two refs in same file → still 1",
                            "minimum_integration_count": 2,
                            "validators": [".claude/scripts/v1.py"],
                            "integration_points": [
                                ".claude/scripts/site_a.sh",
                                ".claude/patterns/site_b.md",
                            ],
                        }
                    ]
                },
                validator_paths=[".claude/scripts/v1.py"],
                integration_files={
                    ".claude/scripts/site_a.sh": same_file_double_ref,
                    ".claude/patterns/site_b.md": "# Doc — no validator reference\n",
                },
            )
            rc, stdout, stderr = _run(tmpdir, "--strict-aoc")
        self.assertNotEqual(
            rc, 0,
            "Expected finding when 2 refs exist in 1 file (cardinality should still be 1, below threshold 2)",
        )


class TestErrorMessageGuidance(unittest.TestCase):
    """The threshold error message must guide implementers toward the fix."""

    def test_message_names_the_threshold_and_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_repo(
                tmpdir,
                {
                    "rules": [
                        {
                            "id": "err-msg-test",
                            "type": "validator_integration_required",
                            "severity": "block",
                            "description": "msg test",
                            "minimum_integration_count": 2,
                            "validators": [".claude/scripts/v1.py"],
                            "integration_points": [
                                ".claude/scripts/site_a.sh",
                                ".claude/patterns/site_b.md",
                            ],
                        }
                    ]
                },
                validator_paths=[".claude/scripts/v1.py"],
                integration_files={
                    ".claude/scripts/site_a.sh": _bash_fixture("v1.py"),
                    ".claude/patterns/site_b.md": "# No reference\n",
                },
            )
            rc, stdout, stderr = _run(tmpdir, "--strict-aoc")
        combined = (stdout or "") + (stderr or "")
        self.assertNotEqual(rc, 0)
        # Must guide to the threshold and current coverage
        self.assertIn("only 1 of", combined)
        self.assertIn("Wire the validator in 1 additional integration_point file", combined)


if __name__ == "__main__":
    unittest.main()
