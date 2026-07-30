#!/usr/bin/env python3
"""test_codemod_canonical_writer.py — golden-fixture regression for PR-B codemod.

Each fixture under .claude/scripts/tests/fixtures/codemod-canonical-writer/<id>/
has an input.md and expected.md. The test asserts:
  1. codemod(input.md) == expected.md byte-for-byte.
  2. Idempotency: codemod(codemod(input.md)) == codemod(input.md).
  3. Section-guard: VERIFY-section writes are NEVER touched.
  4. Already-migrated state files are NEVER touched.
  5. Non-manifest paths are NEVER touched.

Run: python3 .claude/scripts/tests/test_codemod_canonical_writer.py
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / ".claude/scripts/codemod-canonical-writer.py"
FIXTURES = ROOT / ".claude/scripts/tests/fixtures/codemod-canonical-writer"
MANIFEST = ROOT / ".claude/patterns/gate-readable-artifacts-canonical.json"


def _load_codemod_module(repo_root: Path):
    """Import the codemod with a synthetic REPO_ROOT (so its `parents[2]`
    calculation lands on the temp tree)."""
    spec = importlib.util.spec_from_file_location(
        "codemod_canonical_writer",
        repo_root / ".claude/scripts/codemod-canonical-writer.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_temp_tree(fixture_dir: Path, target_skill: str) -> Path:
    """Copy the fixture into a temp .claude/skills/<target_skill>/state-X.md
    layout. Includes the manifest and the audit + codemod scripts so the
    codemod can import audit_mod via REPO_ROOT/parents[2]."""
    tmp = Path(tempfile.mkdtemp(prefix="codemod-test-"))
    # Manifest
    manifest_dst = tmp / ".claude/patterns/gate-readable-artifacts-canonical.json"
    manifest_dst.parent.mkdir(parents=True)
    shutil.copy(MANIFEST, manifest_dst)
    # Scripts
    scripts_dst = tmp / ".claude/scripts"
    scripts_dst.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / ".claude/scripts/codemod-canonical-writer-audit.py",
                scripts_dst / "codemod-canonical-writer-audit.py")
    shutil.copy(ROOT / ".claude/scripts/codemod-canonical-writer.py",
                scripts_dst / "codemod-canonical-writer.py")
    # Fixture state file
    state_dir = tmp / ".claude/skills" / target_skill
    state_dir.mkdir(parents=True)
    shutil.copy(fixture_dir / "input.md", state_dir / "state-0.md")
    return tmp


def _run_codemod_on_tree(tmp: Path) -> tuple[str, str, str]:
    """Run the codemod inside tmp; return (state_file_after_text,
    manual_queue_text, dry_run_diff)."""
    mod = _load_codemod_module(tmp)
    # Apply in place.
    rc = mod.main(["--scope", "skills"])
    state_files = list((tmp / ".claude/skills").rglob("state-*.md"))
    assert len(state_files) == 1
    after_text = state_files[0].read_text()
    queue_path = tmp / ".runs/canonical-writer-manual-queue.json"
    queue_text = queue_path.read_text() if queue_path.exists() else ""
    return after_text, queue_text, ""


def _run_codemod_dry(tmp: Path) -> str:
    """Run codemod --dry-run and return stdout (the unified diff)."""
    import io
    mod = _load_codemod_module(tmp)
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        mod.main(["--dry-run", "--scope", "skills"])
    finally:
        sys.stdout = old_stdout
    return buf.getvalue()


class GoldenFixtureBase(unittest.TestCase):
    """Run a single fixture and assert input → expected."""

    fixture_id: str = ""
    target_skill: str = "audit"

    def _run(self, fixture_id: str, skill: str = "audit"):
        fixture_dir = FIXTURES / fixture_id
        if not fixture_dir.exists():
            self.skipTest(f"fixture missing: {fixture_id}")
        expected = (fixture_dir / "expected.md").read_text()
        tmp = _make_temp_tree(fixture_dir, skill)
        try:
            after, _queue, _diff = _run_codemod_on_tree(tmp)
            self.assertEqual(
                after, expected,
                f"\nFixture {fixture_id} mismatch.\n"
                f"--- expected ---\n{expected}\n"
                f"--- actual ---\n{after}",
            )
            # Idempotency.
            after2, _queue2, _ = _run_codemod_on_tree(tmp)
            self.assertEqual(after, after2, f"fixture {fixture_id} not idempotent")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestS2Mechanical(GoldenFixtureBase):
    def test_s2_mechanical_rewrites(self):
        self._run("01-s2-mechanical")


class TestS1Mechanical(GoldenFixtureBase):
    def test_s1_mechanical_rewrites(self):
        self._run("02-s1-mechanical")


class TestBashInterpolatedRefused(GoldenFixtureBase):
    def test_bash_interpolated_unchanged(self):
        # expected.md == input.md — codemod refuses, file is untouched.
        self._run("03-bash-interpolated-refused")


class TestMultiWriteRefused(GoldenFixtureBase):
    def test_multi_write_unchanged(self):
        self._run("04-multi-write-refused")


class TestVerifySectionRefused(GoldenFixtureBase):
    def test_verify_section_unchanged(self):
        # Even though the dump call looks mechanical, the codemod refuses
        # because the surrounding section is **VERIFY:**.
        self._run("05-verify-section-refused")


class TestAlreadyMigrated(GoldenFixtureBase):
    def test_already_migrated_no_op(self):
        self._run("06-already-migrated")


class TestNonManifestPath(GoldenFixtureBase):
    def test_non_manifest_path_untouched(self):
        # Path .runs/some-non-manifest-path.json is not in the manifest,
        # so the codemod ignores it.
        self._run("07-non-manifest-path-untouched")


class TestMultilinePayloadWithFunctionCall(GoldenFixtureBase):
    """PR-FIX-S2 regression: previously, the audit's S2 regex
    `json\\.dump\\([^()]*?open\\(...)` could not span function calls in a
    multi-line dict payload (e.g. `datetime.now()`), silently missing
    9 in-scope sites including state-99-epilogue.md. The unified
    `(?<!with\\s)open\\(target,'w')` matcher closes that blind spot.
    This fixture pins the regression."""

    def test_multiline_payload_with_function_call(self):
        self._run("08-multiline-payload-with-function-call")


class TestDryRunMode(unittest.TestCase):
    """--dry-run prints diff but does not mutate files."""

    def test_dry_run_does_not_modify_files(self):
        fixture_dir = FIXTURES / "01-s2-mechanical"
        if not fixture_dir.exists():
            self.skipTest("fixture missing")
        tmp = _make_temp_tree(fixture_dir, "audit")
        try:
            before = (tmp / ".claude/skills/audit/state-0.md").read_text()
            diff = _run_codemod_dry(tmp)
            after = (tmp / ".claude/skills/audit/state-0.md").read_text()
            self.assertEqual(before, after, "dry-run mutated file")
            self.assertIn("--- a/.claude/skills/audit/state-0.md", diff)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestCheckMode(unittest.TestCase):
    """--check exits 1 when rewrites would be made, 0 otherwise."""

    def test_check_exits_one_when_rewrites_pending(self):
        fixture_dir = FIXTURES / "01-s2-mechanical"
        if not fixture_dir.exists():
            self.skipTest("fixture missing")
        tmp = _make_temp_tree(fixture_dir, "audit")
        try:
            mod = _load_codemod_module(tmp)
            rc = mod.main(["--check", "--scope", "skills"])
            self.assertEqual(rc, 1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_check_exits_zero_when_clean(self):
        fixture_dir = FIXTURES / "06-already-migrated"
        if not fixture_dir.exists():
            self.skipTest("fixture missing")
        tmp = _make_temp_tree(fixture_dir, "audit")
        try:
            mod = _load_codemod_module(tmp)
            rc = mod.main(["--check", "--scope", "skills"])
            self.assertEqual(rc, 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
