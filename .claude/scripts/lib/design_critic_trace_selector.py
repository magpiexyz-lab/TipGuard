"""Shared selector for per-page design-critic traces.

A single function `select_latest_per_page_traces` owns the rules for
which design-critic-*.json files represent the *current* per-page
verdicts. Both `merge-design-critic-traces.py` (write-time aggregation)
and `evaluate-hard-gate-predicates.py:aggregate_ok` (gate-time sibling
acceptance) call this helper, so the two consumers cannot drift.

Why a shared helper exists (closes #1274 round-2 critic C12):

A post-fix design-critic re-spawn writes a NEW trace with the
`--epoch <N>` suffix in its filename (e.g.,
`design-critic-home--epoch1.json`). Both the original
`design-critic-home.json` and the post-fix epoch trace live on disk
(HC3 — traces are write-once). Without this helper, the merger would
sum unresolved counts from both, and `aggregate_ok` would require ALL
siblings to satisfy a pass-class predicate — a stale OLD trace fails
even after the re-spawn lands.

Six gotchas this helper handles:
1. Page-key fallback chain — `trace["page"]` → `trace["weakest_page"]`
   → filename strip — mirrors merger's pre-existing logic exactly.
2. Filename strip removes the `--epoch<N>` suffix BEFORE deriving the
   page key, so `design-critic-home--epoch2.json` keys as `home`.
3. Numeric epoch ordering — epoch10 sorts after epoch2.
4. Mtime tiebreak when two files claim the same epoch (defensive;
   the writer enforces unique filenames in practice).
5. Old traces stay on disk; this helper only filters in-memory.
6. The predicate `or`-chain inside `aggregate_ok` stays in place
   (F8 lint AST-asserts the enumeration), so this helper returns the
   filtered file list and lets the caller iterate predicates itself.
"""
from __future__ import annotations

import glob
import json
import os
import re
from typing import Optional

_EPOCH_SUFFIX_RE = re.compile(r"--epoch(\d+)$")


def _epoch_from_filename(path: str) -> int:
    """Extract the numeric epoch suffix from a trace filename.

    `design-critic-home--epoch3.json` → 3.
    `design-critic-home.json`         → 0.
    """
    base = os.path.basename(path)
    if base.endswith(".json"):
        base = base[:-5]
    m = _EPOCH_SUFFIX_RE.search(base)
    if m:
        try:
            return int(m.group(1))
        except (TypeError, ValueError):
            return 0
    return 0


def _strip_epoch_suffix(stem: str) -> str:
    """Remove a trailing `--epoch<N>` suffix from a basename stem."""
    return _EPOCH_SUFFIX_RE.sub("", stem)


def extract_page_key(trace_data: dict, trace_path: str, agent: str) -> str:
    """Return the page key for a per-page trace.

    Order:
    1. `trace["page"]` — the structured field design-critic emits
       (see `.claude/agents/design-critic.md` Trace Output).
    2. `trace["weakest_page"]` — preserved for legacy traces.
    3. Filename strip — `<agent>-<key>--epoch<N>.json` → `<key>`.
    """
    if isinstance(trace_data, dict):
        for k in ("page", "weakest_page"):
            v = trace_data.get(k)
            if isinstance(v, str) and v:
                return v
    base = os.path.basename(trace_path)
    if base.endswith(".json"):
        base = base[:-5]
    prefix = f"{agent}-"
    if base.startswith(prefix):
        base = base[len(prefix):]
    return _strip_epoch_suffix(base)


def _load_trace(path: str) -> Optional[dict]:
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _trace_epoch(data: Optional[dict], path: str) -> int:
    """Prefer the structured `epoch` field; fall back to filename suffix."""
    if isinstance(data, dict):
        v = data.get("epoch")
        if isinstance(v, int) and v >= 0:
            return v
    return _epoch_from_filename(path)


def _file_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def select_latest_per_page_traces(
    traces_dir: str,
    agent: str = "design-critic",
) -> list[str]:
    """Return absolute paths of the latest per-page trace per page key.

    Scans `<traces_dir>/<agent>-*.json`, excludes the `<agent>-shared.json`
    side trace and the merged `<agent>.json` aggregate, groups by page key,
    and keeps the highest-(epoch, mtime, filename) tuple per group.

    Returned list is sorted by absolute path for deterministic ordering
    across consumers.
    """
    if not traces_dir:
        return []
    pattern = os.path.join(traces_dir, f"{agent}-*.json")
    candidates = glob.glob(pattern)
    if not candidates:
        return []

    shared_basename = f"{agent}-shared.json"
    aggregate_basename = f"{agent}.json"

    by_page: dict[str, tuple[int, float, str, str]] = {}
    for path in candidates:
        bn = os.path.basename(path)
        if bn == shared_basename or bn == aggregate_basename:
            continue
        data = _load_trace(path)
        page_key = extract_page_key(data or {}, path, agent)
        if not page_key:
            continue
        epoch = _trace_epoch(data, path)
        mtime = _file_mtime(path)
        abspath = os.path.abspath(path)
        sort_key = (epoch, mtime, abspath)
        existing = by_page.get(page_key)
        if existing is None or sort_key > existing[:3]:
            by_page[page_key] = (epoch, mtime, abspath, path)

    return sorted(v[2] for v in by_page.values())
