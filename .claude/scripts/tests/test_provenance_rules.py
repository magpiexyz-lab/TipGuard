#!/usr/bin/env python3
"""Behavioral tests for provenance-schema coherence rules.

Validates that verify-linter.sh dispatches correctly to the two new rule
types introduced by the collocated provenance schema (closes #1162 #1152):

- artifact_transience — for each state-registry entry with lifecycle != durable,
  the artifact path must match a real deletion source (lifecycle-init.sh
  STALE_ARTIFACTS / DELIVERY_ARTIFACTS for cross-skill, or a state-*.md
  rm -f / Delete prose for intra-skill). Also the inverse: durable entries
  must NOT reference paths that are known transient.
- executor_enforcement — three-way mapping per artifact in
  lead-only-artifacts.json: hook coverage + schema declares executor field +
  no .claude/agents/*.md lists artifact as deliverable.

Run via: python3 .claude/scripts/tests/test_provenance_rules.py
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


def _setup_repo(tmpdir, rules, registry, files):
    """Create a minimal repo skeleton scanned by verify-linter.sh."""
    os.makedirs(os.path.join(tmpdir, ".claude/scripts"), exist_ok=True)
    os.makedirs(os.path.join(tmpdir, ".claude/patterns"), exist_ok=True)
    os.makedirs(os.path.join(tmpdir, ".claude/skills/demo"), exist_ok=True)
    os.makedirs(os.path.join(tmpdir, ".claude/agents"), exist_ok=True)
    os.makedirs(os.path.join(tmpdir, ".claude/hooks"), exist_ok=True)
    shutil.copy(LINTER, os.path.join(tmpdir, ".claude/scripts/verify-linter.sh"))
    if os.path.isdir(LIB_DIR):
        shutil.copytree(LIB_DIR, os.path.join(tmpdir, ".claude/scripts/lib"), dirs_exist_ok=True)
    with open(os.path.join(tmpdir, ".claude/patterns/state-registry.json"), "w") as f:
        json.dump(registry, f)
    with open(os.path.join(tmpdir, ".claude/patterns/template-coherence-rules.json"), "w") as f:
        json.dump(rules, f)
    for rel, content in files.items():
        full = os.path.join(tmpdir, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as fh:
            fh.write(content)


def _run_linter(tmpdir, *extra_args):
    result = subprocess.run(
        ["bash", os.path.join(tmpdir, ".claude/scripts/verify-linter.sh"), *extra_args],
        capture_output=True, text=True, cwd=tmpdir,
    )
    return result.returncode, result.stdout, result.stderr


# Minimal lifecycle-init.sh fixture with a STALE_ARTIFACTS array
INIT_SH = """\
#!/usr/bin/env bash
# Minimal lifecycle-init.sh fixture for tests.
DELIVERY_ARTIFACTS=(
  "$PROJECT_DIR/.runs/pr-body.md"
)
STALE_ARTIFACTS=(
  "$PROJECT_DIR/.runs/observe-result.json"
  "$PROJECT_DIR/.runs/agent-traces/"
)
"""


class TestArtifactTransience(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_transient_cross_skill_match_passes(self):
        """A transient-cross-skill entry whose path is in STALE_ARTIFACTS passes."""
        registry = {"demo": {"1": {
            "verify": "test -f .runs/observe-result.json",
            "artifact": ".runs/observe-result.json",
            "lifecycle": "transient-cross-skill",
        }}}
        _setup_repo(self.tmpdir, {"rules": [
            {"id": "r1", "type": "artifact_transience", "severity": "block", "skill": "demo"}
        ]}, registry, {".claude/scripts/lifecycle-init.sh": INIT_SH})
        rc, _out, err = _run_linter(self.tmpdir)
        self.assertNotIn("artifact_transience/block", err + _out,
                         f"unexpected violation:\n{_out}\n{err}")

    def test_transient_cross_skill_path_not_in_stale_array_fails(self):
        """A transient-cross-skill entry whose path is NOT in STALE_ARTIFACTS fails."""
        registry = {"demo": {"1": {
            "verify": "test -f .runs/not-cleaned.json",
            "artifact": ".runs/not-cleaned.json",
            "lifecycle": "transient-cross-skill",
        }}}
        _setup_repo(self.tmpdir, {"rules": [
            {"id": "r1", "type": "artifact_transience", "severity": "block", "skill": "demo"}
        ]}, registry, {".claude/scripts/lifecycle-init.sh": INIT_SH})
        rc, _out, err = _run_linter(self.tmpdir)
        self.assertIn("transient-cross-skill but .runs/not-cleaned.json is not in", _out,
                      f"expected violation missing:\n{_out}\n{err}")

    def test_transient_intra_skill_with_real_deletion_passes(self):
        """A transient-intra-skill entry whose path is deleted in a same-skill state file passes."""
        registry = {"demo": {"1": {
            "verify": "test -f .runs/intra.md",
            "artifact": ".runs/intra.md",
            "lifecycle": "transient-intra-skill",
        }}}
        state_file = """## State
**ACTIONS:**
```bash
rm -f .runs/intra.md
```
"""
        _setup_repo(self.tmpdir, {"rules": [
            {"id": "r1", "type": "artifact_transience", "severity": "block", "skill": "demo"}
        ]}, registry, {
            ".claude/scripts/lifecycle-init.sh": INIT_SH,
            ".claude/skills/demo/state-2-cleanup.md": state_file,
        })
        rc, _out, err = _run_linter(self.tmpdir)
        self.assertNotIn("artifact_transience/block", err + _out,
                         f"unexpected violation:\n{_out}\n{err}")

    def test_transient_intra_skill_no_deletion_fails(self):
        """A transient-intra-skill entry with no real deletion source fails."""
        registry = {"demo": {"1": {
            "verify": "test -f .runs/never-deleted.md",
            "artifact": ".runs/never-deleted.md",
            "lifecycle": "transient-intra-skill",
        }}}
        _setup_repo(self.tmpdir, {"rules": [
            {"id": "r1", "type": "artifact_transience", "severity": "block", "skill": "demo"}
        ]}, registry, {".claude/scripts/lifecycle-init.sh": INIT_SH})
        rc, _out, err = _run_linter(self.tmpdir)
        self.assertIn("transient-intra-skill but no state-*.md", _out,
                      f"expected violation missing:\n{_out}\n{err}")

    def test_transient_no_artifact_field_fails(self):
        """A transient entry without an `artifact` field fails."""
        registry = {"demo": {"1": {
            "verify": "test -f x",
            "lifecycle": "transient-cross-skill",
        }}}
        _setup_repo(self.tmpdir, {"rules": [
            {"id": "r1", "type": "artifact_transience", "severity": "block", "skill": "demo"}
        ]}, registry, {".claude/scripts/lifecycle-init.sh": INIT_SH})
        rc, _out, err = _run_linter(self.tmpdir)
        self.assertIn("but no `artifact` declared", _out,
                      f"expected violation missing:\n{_out}\n{err}")

    def test_inverse_check_durable_entry_referencing_transient_path_fails(self):
        """A durable entry whose VERIFY references a known-transient path fails (inverse check)."""
        registry = {"demo": {"1": "test -f .runs/observe-result.json"}}  # legacy string = durable
        _setup_repo(self.tmpdir, {"rules": [
            {"id": "r1", "type": "artifact_transience", "severity": "block", "skill": "demo"}
        ]}, registry, {".claude/scripts/lifecycle-init.sh": INIT_SH})
        rc, _out, err = _run_linter(self.tmpdir)
        self.assertIn("declared durable but its VERIFY references", _out,
                      f"expected inverse-check violation missing:\n{_out}\n{err}")


# Minimal manifest + observation-phase fixture for executor_enforcement
MANIFEST = {
    "artifacts": [
        {
            "path": ".runs/lead-only-test.json",
            "executor_field": "executor",
            "schema_source": ".claude/patterns/test-schema.md",
            "writers": ["lead"],
        }
    ]
}
SCHEMA_GOOD = "Schema declares the executor field for .runs/lead-only-test.json"
SCHEMA_BAD = "Schema does NOT declare the field for .runs/lead-only-test.json"
HOOK_REFERENCING_MANIFEST = """\
#!/usr/bin/env bash
# Test hook that references the manifest
MANIFEST=".claude/patterns/lead-only-artifacts.json"
"""
AGENT_GOOD = "An agent description (no mention of the lead-only path)."
AGENT_BAD_DELEGATING = "Spawn observer with deliverable .runs/lead-only-test.json please."
AGENT_BAD_BUT_DOCUMENTED = "Reads .runs/lead-only-test.json. Evidence collection only — does not write it."


class TestExecutorEnforcement(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _setup(self, hook_text, schema_text, agent_files=None):
        files = {
            ".claude/patterns/lead-only-artifacts.json": json.dumps(MANIFEST),
            ".claude/patterns/test-schema.md": schema_text,
            ".claude/hooks/lead-deliverable-gate.sh": hook_text,
        }
        for name, content in (agent_files or {}).items():
            files[f".claude/agents/{name}"] = content
        _setup_repo(self.tmpdir, {"rules": [
            {"id": "r1", "type": "executor_enforcement", "severity": "block",
             "manifest_path": ".claude/patterns/lead-only-artifacts.json"}
        ]}, {}, files)

    def test_all_three_layers_satisfied_passes(self):
        """Hook references manifest + schema declares field + no agent mentions → pass."""
        self._setup(HOOK_REFERENCING_MANIFEST, SCHEMA_GOOD, {"observer.md": AGENT_GOOD})
        rc, _out, err = _run_linter(self.tmpdir)
        self.assertNotIn("executor_enforcement/block", err + _out,
                         f"unexpected violation:\n{_out}\n{err}")

    def test_no_hook_coverage_fails(self):
        """Hook does not reference manifest → block."""
        self._setup("#!/usr/bin/env bash\n# unrelated hook\n", SCHEMA_GOOD,
                    {"observer.md": AGENT_GOOD})
        rc, _out, err = _run_linter(self.tmpdir)
        self.assertIn("no PreToolUse hook references the manifest", _out)

    def test_schema_lacks_executor_field_fails(self):
        """Schema source does not contain executor field name → block."""
        self._setup(HOOK_REFERENCING_MANIFEST, SCHEMA_BAD, {"observer.md": AGENT_GOOD})
        rc, _out, err = _run_linter(self.tmpdir)
        self.assertIn("does not declare executor_field", _out)

    def test_agent_lists_artifact_as_deliverable_fails(self):
        """An agent .md mentions the artifact without an 'Evidence collection only' caveat → block."""
        self._setup(HOOK_REFERENCING_MANIFEST, SCHEMA_GOOD,
                    {"observer.md": AGENT_BAD_DELEGATING})
        rc, _out, err = _run_linter(self.tmpdir)
        self.assertIn("negative-deliverable violation", _out)

    def test_agent_mentions_with_caveat_passes(self):
        """An agent .md may mention the artifact if it documents the constraint."""
        self._setup(HOOK_REFERENCING_MANIFEST, SCHEMA_GOOD,
                    {"observer.md": AGENT_BAD_BUT_DOCUMENTED})
        rc, _out, err = _run_linter(self.tmpdir)
        self.assertNotIn("negative-deliverable violation", _out)


# --- Migration script idempotency -----------------------------------------


class TestMigrationIdempotency(unittest.TestCase):
    """The classification helper picks the FIRST sorted transient artifact;
    sorted() ensures the migration is idempotent across runs.
    """

    def test_artifact_path_extraction_is_sorted(self):
        sys.path.insert(0, os.path.join(REAL_REPO, ".claude/scripts"))
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "migrate_state_registry_lifecycle",
                os.path.join(REAL_REPO, ".claude/scripts/migrate-state-registry-lifecycle.py"),
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            cmd = "test -f .runs/zzz.md && test -f .runs/aaa.md && test -f .runs/mmm.md"
            paths = mod.extract_artifact_paths(cmd)
            self.assertEqual(paths, sorted(paths),
                             "extract_artifact_paths must return sorted output for idempotency")
            self.assertEqual(paths, [".runs/aaa.md", ".runs/mmm.md", ".runs/zzz.md"])
        finally:
            sys.path.pop(0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
