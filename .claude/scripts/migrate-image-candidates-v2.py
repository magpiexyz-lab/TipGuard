#!/usr/bin/env python3
"""Idempotently migrate .runs/image-candidates.json to schema_version=2.

Issue context: PR #1309 made `scaffold-images` Step 5b stamp
`"schema_version": 2` on first sidecar write. Sidecars produced BEFORE
that PR (any /bootstrap or /change run between MIGRATION_CUTOFF_ISO
2026-05-04 and PR #1309 merge on 2026-05-06) lack the field. Without
the stamp, validate-step55-evidence.py at state-3b VERIFY treats
post-cutoff runs on these legacy sidecars as producer-side drift and
emits a violation in telemetry. The deny-mode flip follow-up PR is
soak-gated, and the soak query counts CLEAN warn-mode runs — legacy
sidecars therefore prevent the soak from passing.

This script closes that gap. Run once per project that has a sidecar
predating PR #1309:

    python3 .claude/scripts/migrate-image-candidates-v2.py

Behavior:
  - exit 0, "already v2" message      → sidecar has schema_version >= 2
  - exit 0, "stamped v2" message      → field was missing or v=1; stamped
  - exit 0, "no sidecar"              → .runs/image-candidates.json absent
  - exit 1, parse error               → sidecar JSON is malformed

Idempotent: running multiple times is safe — second run is a no-op.

Operator notes (from .claude/patterns/step55-evidence-rollout.md):
  1. Run this script in each affected project
  2. Re-run /verify; the validator should now produce a clean telemetry
     record (verdict=pass or skip, no violation_categories)
  3. After 10 such clean records accumulate, the deny-mode flip is
     sanctioned per the soak query
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SIDECAR_PATH = Path(".runs/image-candidates.json")


def main() -> int:
    if not SIDECAR_PATH.is_file():
        print(f"migrate-image-candidates-v2: SKIP (no {SIDECAR_PATH})")
        return 0

    try:
        sidecar = json.loads(SIDECAR_PATH.read_text())
    except json.JSONDecodeError as e:
        print(f"migrate-image-candidates-v2: ERROR — cannot parse {SIDECAR_PATH}: {e}",
              file=sys.stderr)
        return 1

    current = sidecar.get("schema_version")
    if current == 2:
        print(f"migrate-image-candidates-v2: already v2 ({SIDECAR_PATH})")
        return 0
    if isinstance(current, int) and current > 2:
        # Future-format sidecar — leave alone (forward compatibility for
        # potential schema_version=3 work).
        print(f"migrate-image-candidates-v2: SKIP ({SIDECAR_PATH} schema_version={current} > 2)")
        return 0

    # Stamp v2. We preserve all existing fields and add schema_version
    # at the top of the dict (Python 3.7+ preserves insertion order; we
    # rebuild the dict so the new field appears first when re-serialized).
    new_sidecar = {"schema_version": 2}
    new_sidecar.update({k: v for k, v in sidecar.items() if k != "schema_version"})

    # Atomic write via temp + rename. Avoids partial writes if interrupted.
    tmp_path = SIDECAR_PATH.with_suffix(SIDECAR_PATH.suffix + ".tmp")
    try:
        tmp_path.write_text(json.dumps(new_sidecar, indent=2) + "\n")
        os.replace(tmp_path, SIDECAR_PATH)
    except OSError as e:
        print(f"migrate-image-candidates-v2: ERROR — cannot write {SIDECAR_PATH}: {e}",
              file=sys.stderr)
        if tmp_path.exists():
            tmp_path.unlink()
        return 1

    prior = "missing field" if current is None else f"schema_version={current}"
    print(f"migrate-image-candidates-v2: stamped v2 on {SIDECAR_PATH} (was: {prior})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
