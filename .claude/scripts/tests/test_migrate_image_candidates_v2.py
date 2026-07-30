"""Unit tests for .claude/scripts/migrate-image-candidates-v2.py.

Locks the migration contract for legacy sidecars produced before PR #1309
landed the schema_version stamp on scaffold-images Step 5b.

Behavior matrix:
  - No sidecar       → SKIP, exit 0
  - Missing field    → stamp v2, exit 0
  - Explicit v=1     → stamp v2, exit 0
  - Already v=2      → already v2, exit 0 (idempotent)
  - Future v=3       → SKIP (forward compat), exit 0
  - Malformed JSON   → ERROR, exit 1
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATE = REPO_ROOT / ".claude" / "scripts" / "migrate-image-candidates-v2.py"


def _run(tmpdir: Path) -> subprocess.CompletedProcess:
    """Invoke the migration script in tmpdir's cwd."""
    return subprocess.run(
        ["python3", str(MIGRATE)],
        cwd=str(tmpdir), capture_output=True, text=True, timeout=15,
    )


def _write_sidecar(tmpdir: Path, content: str) -> None:
    runs = tmpdir / ".runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "image-candidates.json").write_text(content)


def _read_sidecar(tmpdir: Path) -> dict:
    return json.loads((tmpdir / ".runs" / "image-candidates.json").read_text())


class TestMigrateImageCandidatesV2(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="test_migrate_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_no_sidecar_skips_cleanly(self):
        r = _run(self.tmpdir)
        self.assertEqual(r.returncode, 0)
        self.assertIn("SKIP (no .runs/image-candidates.json)", r.stdout)

    def test_legacy_missing_field_stamps_v2(self):
        _write_sidecar(self.tmpdir, json.dumps({
            "generated_at": "2026-05-05",
            "slots": {"hero": {"candidates": [{"path": "a.webp"}]}},
        }))
        r = _run(self.tmpdir)
        self.assertEqual(r.returncode, 0)
        self.assertIn("stamped v2", r.stdout)
        self.assertIn("was: missing field", r.stdout)
        sidecar = _read_sidecar(self.tmpdir)
        self.assertEqual(sidecar["schema_version"], 2)
        # Existing fields preserved
        self.assertEqual(sidecar["generated_at"], "2026-05-05")
        self.assertIn("hero", sidecar["slots"])

    def test_legacy_field_first_in_serialized_form(self):
        """Migrated sidecar should have schema_version as the FIRST key
        when re-serialized (contractual ordering: matches the
        scaffold-images Step 5b template that stamps it as the first key)."""
        _write_sidecar(self.tmpdir, json.dumps({
            "generated_at": "2026-05-05",
            "slots": {},
        }))
        _run(self.tmpdir)
        raw = (self.tmpdir / ".runs" / "image-candidates.json").read_text()
        # First non-brace line should mention schema_version
        first_field_line = next(ln for ln in raw.splitlines()
                                if ":" in ln and not ln.startswith("{"))
        self.assertIn("schema_version", first_field_line)

    def test_explicit_v1_stamps_v2(self):
        _write_sidecar(self.tmpdir, json.dumps({
            "schema_version": 1,
            "slots": {},
        }))
        r = _run(self.tmpdir)
        self.assertEqual(r.returncode, 0)
        self.assertIn("stamped v2", r.stdout)
        self.assertIn("was: schema_version=1", r.stdout)
        self.assertEqual(_read_sidecar(self.tmpdir)["schema_version"], 2)

    def test_already_v2_is_idempotent(self):
        original = {"schema_version": 2, "slots": {"hero": {}}}
        _write_sidecar(self.tmpdir, json.dumps(original))
        r = _run(self.tmpdir)
        self.assertEqual(r.returncode, 0)
        self.assertIn("already v2", r.stdout)
        # Sidecar untouched
        self.assertEqual(_read_sidecar(self.tmpdir), original)

    def test_running_twice_is_safe(self):
        """Running the migration twice must not corrupt the sidecar."""
        _write_sidecar(self.tmpdir, json.dumps({
            "generated_at": "2026-05-05", "slots": {},
        }))
        r1 = _run(self.tmpdir)
        self.assertIn("stamped v2", r1.stdout)
        first_pass = _read_sidecar(self.tmpdir)
        r2 = _run(self.tmpdir)
        self.assertIn("already v2", r2.stdout)
        self.assertEqual(_read_sidecar(self.tmpdir), first_pass)

    def test_future_version_is_skipped(self):
        """Forward compatibility: schema_version > 2 is left alone in case
        a future PR introduces v3 with stricter semantics."""
        _write_sidecar(self.tmpdir, json.dumps({
            "schema_version": 3, "slots": {},
        }))
        r = _run(self.tmpdir)
        self.assertEqual(r.returncode, 0)
        self.assertIn("SKIP", r.stdout)
        self.assertIn("schema_version=3", r.stdout)
        self.assertEqual(_read_sidecar(self.tmpdir)["schema_version"], 3)

    def test_malformed_json_errors(self):
        _write_sidecar(self.tmpdir, "{ not valid json")
        r = _run(self.tmpdir)
        self.assertEqual(r.returncode, 1)
        self.assertIn("cannot parse", r.stderr)


if __name__ == "__main__":
    unittest.main()
