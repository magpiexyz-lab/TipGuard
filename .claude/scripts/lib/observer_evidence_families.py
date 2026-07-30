"""AOC v1.2 — Single source of truth for canonical .runs/* evidence-family
glob patterns consumed by the observer.

Imported by:
  - .claude/scripts/write-observation-evidence.py (E2 producer)
  - .claude/scripts/tests/test_observation_evidence_envelope.sh (F3 lint)
  - any future consumer that needs to enumerate "what evidence families
    the observer is allowed to see"

Adding a new evidence family requires editing this constant; the F3 test
then automatically requires the envelope schema in
write-observation-evidence.py to reference it. No exclusion mechanism —
every present family on disk MUST be referenced (closes design caveat C4
re: silenceable exclusion drift).

Each entry is a (glob_pattern, schema_field, kind) triple:
  - glob_pattern: pattern relative to .runs/ used to detect presence
  - schema_field: field name in the envelope JSON that references the
    family. For singleton files, this is a *_path string field. For
    multi-file globs (agent-traces/*.json), it is a *_paths list field.
  - kind: "single" (one file -> string field) or "multi" (glob -> list)

The F3 test asserts: for every (glob, schema_field, kind) where the glob
matches at least one file, the schema_field appears in the envelope JSON
written by write-observation-evidence.py.
"""

from __future__ import annotations

# ORDER MATTERS for deterministic envelope output. Add new entries here
# and the F3 test + envelope writer pick them up automatically.
CANONICAL_EVIDENCE_FAMILIES: list[tuple[str, str, str]] = [
    # Diff (always written by lifecycle-finalize.sh Step 4 pre-merge).
    ("observer-diffs.txt", "diffs_path", "single"),
    # Fix log (rendered from fix-ledger.jsonl by render-fix-log.py).
    ("fix-log.md", "fix_log_path", "single"),
    # Fix ledger (canonical FLS v1 ledger).
    ("fix-ledger.jsonl", "fix_ledger_path", "single"),
    # Hook-friction raw + summary.
    ("hook-friction.jsonl", "hook_friction_jsonl_path", "single"),
    ("hook-friction-summary.json", "hook_friction_summary_path", "single"),
    # Build / e2e results.
    ("build-result.json", "build_result_path", "single"),
    ("e2e-result.json", "e2e_result_path", "single"),
    # All agent traces (multi).
    ("agent-traces/*.json", "agent_traces_paths", "multi"),
    # All summary / merge / evidence / result artifacts (catch-all multi
    # globs — explicit so observer envelope contract is unambiguous).
    ("*-summary.json", "summary_artifacts_paths", "multi"),
    ("*-merge.json", "merge_artifacts_paths", "multi"),
    ("*-evidence*.json", "evidence_artifacts_paths", "multi"),
    ("*-result.json", "result_artifacts_paths", "multi"),
]

# Files that match a multi-glob above but should NOT appear in their list:
#   - observation-evidence.json IS the envelope; self-reference is meaningless
#     and creates an infinite-recursion temptation if a consumer follows it.
#   - observe-evidence-check.json is a small telemetry artifact written by
#     observation-phase.md Step 2.5, not evidence content. Excluding it
#     reduces envelope noise without losing information.
SELF_EXCLUDE_FILENAMES: frozenset[str] = frozenset({
    "observation-evidence.json",
    "observe-evidence-check.json",
})


def list_present_families(runs_dir: str) -> list[tuple[str, str, str, list[str]]]:
    """Return the subset of CANONICAL_EVIDENCE_FAMILIES that have ≥1 match
    on disk under `runs_dir`. Each entry adds the matched paths.

    Result tuple: (glob, schema_field, kind, [matched_paths_relative_to_runs_dir]).
    """
    import glob as _glob
    import os

    out: list[tuple[str, str, str, list[str]]] = []
    for pattern, field, kind in CANONICAL_EVIDENCE_FAMILIES:
        full = os.path.join(runs_dir, pattern)
        matches = sorted(_glob.glob(full))
        # Exclude self-reference noise (envelope itself + telemetry sibling).
        matches = [m for m in matches if os.path.basename(m) not in SELF_EXCLUDE_FILENAMES]
        if not matches:
            continue
        rel = [os.path.relpath(m, runs_dir) for m in matches]
        out.append((pattern, field, kind, rel))
    return out


__all__ = ["CANONICAL_EVIDENCE_FAMILIES", "list_present_families"]
