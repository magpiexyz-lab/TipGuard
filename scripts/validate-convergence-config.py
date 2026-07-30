#!/usr/bin/env python3
"""Validator for .claude/patterns/convergence-config.json.

Enforces a strict whitelist of keys so typos cannot silently fall back to
defaults. Range-checks rates to [0.0, 1.0] and counts/seconds to positive ints.

Exits 0 clean / 1 on any violation.

Usage:
    python3 scripts/validate-convergence-config.py [path]

Path defaults to .claude/patterns/convergence-config.json relative to the
repo root (this file's parent/..).
"""

from __future__ import annotations

import json
import os
import sys

REQUIRED_KEYS = {
    "flip_rate_threshold",
    "min_sample_size",
    "window_size",
    "consecutive_over_threshold_required",
    "oscillation_halt_threshold",
    "causal_analysis_timeout_seconds",
}

RATE_KEYS = {"flip_rate_threshold"}

POSITIVE_INT_KEYS = {
    "min_sample_size",
    "window_size",
    "consecutive_over_threshold_required",
    "oscillation_halt_threshold",
    "causal_analysis_timeout_seconds",
}


def _default_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", ".claude", "patterns", "convergence-config.json")


def validate(path: str) -> list[str]:
    errs: list[str] = []
    if not os.path.exists(path):
        return [f"{path}: file not found"]
    try:
        data = json.load(open(path))
    except (OSError, json.JSONDecodeError) as e:
        return [f"{path}: cannot parse ({e})"]

    if not isinstance(data, dict):
        return [f"{path}: root must be a JSON object, got {type(data).__name__}"]

    keys = set(data.keys())
    missing = REQUIRED_KEYS - keys
    if missing:
        errs.append(f"{path}: missing required keys: {sorted(missing)}")
    extra = keys - REQUIRED_KEYS
    if extra:
        errs.append(f"{path}: unknown keys (typos?): {sorted(extra)}")

    for k in RATE_KEYS & keys:
        v = data[k]
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            errs.append(f"{path}: {k}={v!r} must be a number")
        elif not (0.0 <= float(v) <= 1.0):
            errs.append(f"{path}: {k}={v!r} must be in [0.0, 1.0]")

    for k in POSITIVE_INT_KEYS & keys:
        v = data[k]
        if not isinstance(v, int) or isinstance(v, bool) or v < 1:
            errs.append(f"{path}: {k}={v!r} must be a positive int (>=1)")

    return errs


def main(argv: list[str]) -> int:
    path = argv[1] if len(argv) > 1 else _default_path()
    errs = validate(path)
    if errs:
        print("Convergence config validation failed:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(f"Convergence config validation passed: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
