#!/usr/bin/env python3
"""Validate observer trace cites the expanded evidence-set sources (#1255).

Issue context: #1255 — observer's evidence collection was too narrow
(observer-diffs.txt + fix-log.md + agent traces only). 9/10 template-rooted
issues bypassed evaluation because hook-friction.jsonl, agent
template_recommendations[], and merged trace gaps were invisible.

This validator asserts that when those evidence sources EXIST in the run,
the observer trace shows it consulted them. The observer trace is at
.runs/agent-traces/observer.json; the evidence sources are at known paths.

Logic:
  for source in expanded_evidence_sources:
    if source exists AND has non-trivial content:
      assert source path appears in observer trace's `evidence_consulted[]`

`evidence_consulted[]` is a new agent contract field (added in observer.md
in this PR). Empty observer trace OR missing field = warning, not block,
because observer trace might be a degraded/recovery write.

MODE: OBSERVER_EVIDENCE_COVERAGE_MODE (default warn).
Schema: skip when run_id pre-cutoff.
"""

from __future__ import annotations

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.schema_version_gate import required_schema_version  # type: ignore

OBSERVER_TRACE = ".runs/agent-traces/observer.json"

# (path, predicate fn returning True iff source should be considered)
def _has_lines(path: str, n: int = 1) -> bool:
    if not os.path.isfile(path):
        return False
    try:
        with open(path) as f:
            return sum(1 for _ in f) >= n
    except Exception:
        return False


def _has_content(path: str, min_bytes: int = 10) -> bool:
    if not os.path.isfile(path):
        return False
    try:
        return os.path.getsize(path) >= min_bytes
    except Exception:
        return False


EVIDENCE_SOURCES: list[tuple[str, callable]] = [
    (".runs/hook-friction.jsonl", lambda p: _has_lines(p)),
    (".runs/hook-friction-summary.json", lambda p: _has_content(p, 50)),
]


def _scaffold_recommendations_present() -> bool:
    """Any scaffold-* trace with non-empty template_recommendations[]."""
    for tf in glob.glob(".runs/agent-traces/scaffold-*.json"):
        try:
            data = json.load(open(tf))
        except Exception:
            continue
        recs = data.get("template_recommendations") or []
        if isinstance(recs, list) and len(recs) > 0:
            return True
    return False


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
    return os.environ.get("OBSERVER_EVIDENCE_COVERAGE_MODE", "warn").lower()


def main() -> int:
    mode = _mode()
    rid = _active_run_id()

    required_v = required_schema_version(rid) if rid else 1
    if required_v < 2:
        print(
            f"validate-observer-evidence-coverage: SKIP "
            f"(run_id={rid!r} pre-cutoff; required schema_version={required_v})"
        )
        return 0

    if not os.path.isfile(OBSERVER_TRACE):
        print(f"validate-observer-evidence-coverage: SKIP (no {OBSERVER_TRACE})")
        return 0

    try:
        observer = json.load(open(OBSERVER_TRACE))
    except Exception as e:
        msg = f"BLOCK: cannot parse {OBSERVER_TRACE}: {e}"
        print(msg, file=sys.stderr)
        return 0 if mode == "warn" else 1

    consulted = observer.get("evidence_consulted") or []
    if not isinstance(consulted, list):
        consulted = []

    errors: list[str] = []

    for source_path, has_content in EVIDENCE_SOURCES:
        if has_content(source_path) and source_path not in consulted:
            errors.append(
                f"{source_path} has content but observer trace does not list "
                f"it in evidence_consulted[] (#1255 expanded evidence-set)"
            )

    # Scaffold recommendations are a derived signal — presence requires consultation
    if _scaffold_recommendations_present():
        marker = "scaffold-template-recommendations"
        if marker not in consulted:
            errors.append(
                f"scaffold-* traces have non-empty template_recommendations[] "
                f"but observer trace does not mark consultation "
                f"(expected {marker!r} in evidence_consulted[])"
            )

    if not errors:
        print(
            f"validate-observer-evidence-coverage: OK "
            f"({len(consulted)} sources consulted)"
        )
        return 0

    print(
        f"validate-observer-evidence-coverage: FAIL ({len(errors)} errors)",
        file=sys.stderr,
    )
    for e in errors:
        print(f"  {e}", file=sys.stderr)

    if mode == "warn":
        print("\n[MODE=warn] not blocking", file=sys.stderr)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
