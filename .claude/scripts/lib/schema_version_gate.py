"""Schema-version + run_id timestamp binding (round-2 critic Concern 5).

Issue context: Adding required JSON fields to .runs/ artifacts retroactively
fails old runs (audit/iterate/retro paths). Solution: schema_version stamping
with backwards-compatible bypass for pre-cutoff runs.

Naive implementation problem: if the LLM agent itself writes schema_version,
it can stamp 1 on a freshly authored artifact to dodge new validators.

This module enforces the binding at the HOOK level — derive the artifact's
"effective schema version" from the run_id timestamp (set by init-context.sh
BEFORE any LLM action via `date -u`, therefore unfakeable):

    if run_id_timestamp >= MIGRATION_CUTOFF:
        required_schema_version = 2  # post-cutoff runs MUST stamp 2
    else:
        required_schema_version = 1  # pre-cutoff runs are grandfathered

Then the validator's gate becomes:
    1. Read artifact's stamped schema_version (default 1 if missing)
    2. Compute required version from run_id
    3. If stamped < required: BLOCK ("downward stamp attempt")
    4. If stamped >= required AND stamped >= 2: enforce v2 fields
    5. Otherwise: skip new gates with WARN

run_id format from init-context.sh:
    "{skill_or_skill-mode}-YYYY-MM-DDTHH:MM:SSZ"

Examples:
    "solve-2026-05-04T03:12:26Z"
    "iterate-cross-2026-04-13T07:07:04Z"

The trailing ISO timestamp regex anchor handles compound skill names.

MIGRATION_CUTOFF placeholder: replaced by post-merge sed to the actual
PR-merge commit timestamp (per user-confirmed approach #3 in plan).
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Optional

# Activated 2026-05-04 by post-merge follow-up to PR #1291.
# Pre-merge value was placeholder __MERGE_COMMIT_TIMESTAMP__; sed replaced
# with the merge commit's ISO timestamp. After this point, run_ids whose
# timestamp >= MIGRATION_CUTOFF_ISO must comply with schema_version=2.
MIGRATION_CUTOFF_ISO = "2026-05-04T05:25:30Z"

# Regex: trailing ISO 8601 UTC timestamp at end of run_id
RUN_ID_TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)$")


def extract_run_id_timestamp(run_id: str) -> Optional[str]:
    """Extract the ISO 8601 timestamp suffix from a run_id. None on failure."""
    if not run_id:
        return None
    m = RUN_ID_TS_RE.search(run_id)
    return m.group(1) if m else None


def required_schema_version(run_id: str) -> int:
    """Return required schema_version for a given run_id.

    Returns 2 when run_id timestamp >= MIGRATION_CUTOFF, else 1.
    Returns 1 (grandfathered) on any parse failure (defense: never falsely
    fail; the rest of the pipeline already guards against missing run_id).
    """
    ts = extract_run_id_timestamp(run_id)
    if ts is None:
        return 1
    return 2 if ts >= MIGRATION_CUTOFF_ISO else 1


def check_artifact_schema_version(
    artifact_path: str,
    run_id: str,
) -> tuple[bool, str, int]:
    """Validate an artifact's schema_version against its run_id-derived requirement.

    Returns (ok, message, effective_version):
        ok=True  → artifact may be processed at the effective_version level
        ok=False → BLOCK: downward-stamp attempt or other integrity issue

    Caller pattern (typical validator):
        ok, msg, ver = check_artifact_schema_version(path, run_id)
        if not ok:
            print(f"BLOCK: {msg}", file=sys.stderr)
            sys.exit(1)
        if ver < 2:
            sys.exit(0)  # grandfathered — skip new gates
        # ... enforce v2-required fields
    """
    if not os.path.isfile(artifact_path):
        return False, f"{artifact_path}: not found", 0

    try:
        with open(artifact_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return False, f"{artifact_path}: parse error ({e})", 0

    stamped = data.get("schema_version", 1)
    if not isinstance(stamped, int):
        return False, f"{artifact_path}: schema_version not int", 0

    required = required_schema_version(run_id)

    if stamped < required:
        return (
            False,
            f"{artifact_path}: schema_version={stamped} below required={required} "
            f"for run_id={run_id!r} (downward-stamp attempt blocked)",
            stamped,
        )

    return True, "ok", stamped


def is_v2_active() -> bool:
    """True iff MIGRATION_CUTOFF is a valid ISO timestamp (gate is live).

    Detects the placeholder by checking it matches the ISO format; when it
    does, the gate is active. Pre-merge the placeholder __MERGE_COMMIT_TIMESTAMP__
    fails this check, so the gate is INERT until activated.
    """
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", MIGRATION_CUTOFF_ISO))


# CLI for ad-hoc checks: `python3 schema_version_gate.py <artifact> <run_id>`
if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        print("usage: schema_version_gate.py <artifact_path> <run_id>", file=sys.stderr)
        sys.exit(2)
    ok, msg, ver = check_artifact_schema_version(sys.argv[1], sys.argv[2])
    print(f"effective_version={ver} ok={ok} msg={msg}")
    sys.exit(0 if ok else 1)
