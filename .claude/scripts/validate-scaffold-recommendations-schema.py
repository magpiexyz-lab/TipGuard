#!/usr/bin/env python3
"""Validate scaffold-* agent traces declare template_recommendations[].

Issue context: #1252 — scaffold-setup (and likely other scaffold-* agents)
returns template-rooted recommendations as prose in the agent's reply
message. The observer reads structured trace fields, not prose. Result:
recommendations get lost.

Round-2 critic Concern 7: do NOT grep prose for "consider updating" etc.
LLMs vary phrasing; pattern lists lag agent vocabulary. Instead enforce
SCHEMA COMPLETENESS — require either non-empty `template_recommendations[]`
OR explicit `template_recommendations_explicit_none=true`.

This validator scans .runs/agent-traces/scaffold-*.json (and merge traces)
and asserts the contract. Missing field → fail. Empty array without
explicit-none flag → fail. Non-empty array with malformed entries → fail.

Each entry in template_recommendations[] must have:
  - file: stack file path (must exist on disk)
  - section: section name within the stack file
  - recommendation: imperative one-line description
  - fix_template: concrete change (markdown allowed)

Stub-skip: per-page traces from `init-trace.py` (#1190 contract) write a
stub with `status='started'` when scaffold-* spawns rate-limit or crash.
Stubs lack template_recommendations by design. The aggregate merger
(merge-scaffold-pages-traces.py) partitions stubs from real traces; this
validator mirrors that partition (see _validate_trace) so wiring at
bootstrap.11c does not spuriously fail rate-limited pipelines.

MODE: SCAFFOLD_RECOMMENDATIONS_SCHEMA_MODE (default warn).
Schema: skip when run_id pre-cutoff.
"""

from __future__ import annotations

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.schema_version_gate import required_schema_version  # type: ignore

REQUIRED_FIELDS = {"file", "section", "recommendation", "fix_template"}


def _active_run_id() -> str:
    best = None
    best_ts = ""
    for f in glob.glob(".runs/*-context.json"):
        if "epilogue" in f:
            continue
        try:
            d = json.load(open(f))
        except Exception:
            continue
        if d.get("completed") is True:
            continue
        ts = d.get("timestamp") or ""
        if ts >= best_ts:
            best = d
            best_ts = ts
    return (best or {}).get("run_id", "")


def _mode() -> str:
    return os.environ.get("SCAFFOLD_RECOMMENDATIONS_SCHEMA_MODE", "warn").lower()


def _validate_trace(path: str) -> list[str]:
    try:
        data = json.load(open(path))
    except Exception as e:
        return [f"{path}: parse error ({e})"]

    # #1190 contract: rate-limited / crashed agents leave init-trace stubs
    # with status='started' and no verdict. Aggregate merger
    # (merge-scaffold-pages-traces.py:65-79) partitions them; mirror that
    # here so wiring at bootstrap.11c does not spuriously fail rate-limited
    # pipelines.
    if data.get("status") == "started" and not data.get("verdict"):
        return []

    errors: list[str] = []
    field = data.get("template_recommendations")
    explicit_none = data.get("template_recommendations_explicit_none")

    if field is None and explicit_none is None:
        errors.append(
            f"{path}: missing both 'template_recommendations' and "
            f"'template_recommendations_explicit_none' (#1252 schema completeness)"
        )
        return errors

    if field is None:
        # explicit_none must be True
        if explicit_none is not True:
            errors.append(
                f"{path}: template_recommendations missing AND "
                f"template_recommendations_explicit_none={explicit_none!r} "
                f"(must be True when no recommendations)"
            )
        return errors

    if not isinstance(field, list):
        errors.append(
            f"{path}: template_recommendations must be a list, got {type(field).__name__}"
        )
        return errors

    if not field:
        # Empty array — explicit_none should be True
        if explicit_none is not True:
            errors.append(
                f"{path}: template_recommendations=[] requires "
                f"template_recommendations_explicit_none=True"
            )
        return errors

    # Non-empty: validate each entry
    for idx, entry in enumerate(field):
        if not isinstance(entry, dict):
            errors.append(
                f"{path}: template_recommendations[{idx}] not a dict"
            )
            continue
        missing = REQUIRED_FIELDS - set(entry.keys())
        if missing:
            errors.append(
                f"{path}: template_recommendations[{idx}] missing fields {sorted(missing)}"
            )
            continue
        # File must exist (template-rooted check)
        target = entry.get("file") or ""
        if not target.startswith(".claude/") and not target.startswith("scripts/"):
            errors.append(
                f"{path}: template_recommendations[{idx}].file={target!r} "
                f"is not under .claude/ or scripts/ (not template-rooted)"
            )
            continue
        if not os.path.isfile(target):
            errors.append(
                f"{path}: template_recommendations[{idx}].file={target!r} does not exist"
            )

    return errors


def main() -> int:
    mode = _mode()
    rid = _active_run_id()

    required_v = required_schema_version(rid) if rid else 1
    if required_v < 2:
        print(
            f"validate-scaffold-recommendations-schema: SKIP "
            f"(run_id={rid!r} pre-cutoff; required schema_version={required_v})"
        )
        return 0

    # All scaffold-* and scaffold-images merged trace
    traces = sorted(set(
        glob.glob(".runs/agent-traces/scaffold-*.json")
    ))
    if not traces:
        print("validate-scaffold-recommendations-schema: SKIP (no scaffold-* traces)")
        return 0

    all_errors: list[str] = []
    for tf in traces:
        all_errors.extend(_validate_trace(tf))

    if not all_errors:
        print(
            f"validate-scaffold-recommendations-schema: OK ({len(traces)} traces checked)"
        )
        return 0

    print(
        f"validate-scaffold-recommendations-schema: FAIL ({len(all_errors)} errors)",
        file=sys.stderr,
    )
    for e in all_errors:
        print(f"  {e}", file=sys.stderr)

    if mode == "warn":
        print("\n[MODE=warn] not blocking", file=sys.stderr)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
