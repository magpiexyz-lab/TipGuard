#!/usr/bin/env python3
"""Validate scaffold-pages agent traces declare self_check_score.

Issue #1387 FM3: scaffold-pages traces lacked a standardized
self_check_score field. Agents wrote self-rated scores in conversational
text but no structured JSON field existed; design-critic's Stage 0
fast-path could not consume the prose-only data.

This validator mirrors validate-scaffold-recommendations-schema.py
(#1252 precedent) and AOC v1.2 backward-compat invariants. Each
.runs/agent-traces/scaffold-pages-*.json trace must declare EITHER:

  - A typed `self_check_score` sub-object:
      {
        "visual_coherence": int (0-10),
        "information_hierarchy": int (0-10),
        "interaction_completeness": int (0-10),
        "layout_purpose": int (0-10),
        "component_quality": int (0-10),
        "functional_animation": int (0-10),
      }

  - OR the explicit-none escape with a reason:
      self_check_score_explicit_none: true
      self_check_score_explicit_none_reason: <enum>

Enum values for the reason:
  - "agent-skipped-self-check"  — agent ran but did not self-rate
  - "phase-a-authored"          — page authored by Phase A (sentinel)
  - "rerun-recovery"            — recovery / re-spawn path
  - "other"

Stub-skip: per-page traces from init-trace.py (#1190 contract) write a
stub with status='started' when scaffold-pages spawns rate-limit or
crash. Stubs lack self_check_score by design. The aggregate merger
partitions stubs from real traces; this validator mirrors that.

Pre-cutoff skip: run_id with timestamp < MIGRATION_CUTOFF_ISO
(2026-05-04T05:25:30Z per schema_version_gate.py) skips entirely.
migrate-legacy-traces.py is the canonical self-heal path for those.

MODE: SELF_CHECK_SCORE_SCHEMA_MODE (default warn).
"""
from __future__ import annotations

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.schema_version_gate import required_schema_version  # type: ignore

REQUIRED_DIMENSIONS = frozenset({
    "visual_coherence",
    "information_hierarchy",
    "interaction_completeness",
    "layout_purpose",
    "component_quality",
    "functional_animation",
})

VALID_EXPLICIT_NONE_REASONS = frozenset({
    "agent-skipped-self-check",
    "phase-a-authored",
    "rerun-recovery",
    "other",
})


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
    return os.environ.get("SELF_CHECK_SCORE_SCHEMA_MODE", "warn").lower()


def _validate_score_dict(path: str, score: dict) -> list[str]:
    errors: list[str] = []
    missing = REQUIRED_DIMENSIONS - set(score.keys())
    if missing:
        errors.append(
            f"{path}: self_check_score missing dimensions: {sorted(missing)}"
        )
        return errors
    for dim in REQUIRED_DIMENSIONS:
        v = score.get(dim)
        if not isinstance(v, int):
            errors.append(
                f"{path}: self_check_score.{dim}={v!r} must be int (got {type(v).__name__})"
            )
            continue
        if v < 0 or v > 10:
            errors.append(
                f"{path}: self_check_score.{dim}={v} out of range 0-10"
            )
    return errors


def _validate_trace(path: str) -> list[str]:
    try:
        data = json.load(open(path))
    except Exception as e:
        return [f"{path}: parse error ({e})"]

    # #1190 init-trace stubs: skip
    if data.get("status") == "started" and not data.get("verdict"):
        return []

    score = data.get("self_check_score")
    explicit_none = data.get("self_check_score_explicit_none")
    explicit_none_reason = data.get("self_check_score_explicit_none_reason")

    if score is None and explicit_none is None:
        return [
            f"{path}: missing both 'self_check_score' and "
            f"'self_check_score_explicit_none' "
            f"(#1387 schema completeness — set explicit_none=True with reason if no scoring)"
        ]

    if score is None:
        if explicit_none is not True:
            return [
                f"{path}: self_check_score missing AND "
                f"self_check_score_explicit_none={explicit_none!r} "
                f"(must be True when no scores)"
            ]
        # Reason is required when _explicit_none is True
        if explicit_none_reason is None:
            return [
                f"{path}: self_check_score_explicit_none=True requires "
                f"self_check_score_explicit_none_reason (one of {sorted(VALID_EXPLICIT_NONE_REASONS)})"
            ]
        if explicit_none_reason not in VALID_EXPLICIT_NONE_REASONS:
            return [
                f"{path}: self_check_score_explicit_none_reason={explicit_none_reason!r} "
                f"not in {sorted(VALID_EXPLICIT_NONE_REASONS)}"
            ]
        return []

    # Score is present
    if not isinstance(score, dict):
        return [
            f"{path}: self_check_score must be a dict, got {type(score).__name__}"
        ]
    return _validate_score_dict(path, score)


def main() -> int:
    mode = _mode()
    rid = _active_run_id()

    required_v = required_schema_version(rid) if rid else 1
    if required_v < 2:
        print(
            f"validate-self-check-score-schema: SKIP "
            f"(run_id={rid!r} pre-cutoff; required schema_version={required_v})"
        )
        return 0

    traces = sorted(set(
        glob.glob(".runs/agent-traces/scaffold-pages-*.json")
    ))
    if not traces:
        print("validate-self-check-score-schema: SKIP (no scaffold-pages-*.json traces)")
        return 0

    all_errors: list[str] = []
    for tf in traces:
        all_errors.extend(_validate_trace(tf))

    if not all_errors:
        print(
            f"validate-self-check-score-schema: OK ({len(traces)} traces checked)"
        )
        return 0

    print(
        f"validate-self-check-score-schema: FAIL ({len(all_errors)} errors)",
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
