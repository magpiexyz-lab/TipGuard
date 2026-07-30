#!/usr/bin/env python3
"""
verify-resolve-reproduction.py — VERIFY for /resolve STATE 3 (REPRODUCE).

Reads .runs/resolve-reproduction.json and asserts:

1. Schema basics (legacy from registry pre-M1):
   - reproductions is non-empty list
   - reproductions[0] has divergence_point, expected, actual
   - pre_fix_baseline has frontmatter, semantics, consistency
   - divergence_point does NOT contain embedded multi-file separators (` and `, ` & `, etc.)

2. M1 root-cause empirical-verification (this script's main contribution):
   - For each reproduction record (excluding refine-mode `reproduction_method == "trace_analysis"`):
     - SOFT (M1.2): if `evidence` is a string, length >= 30 AND not in stoplist
     - SOFT (M1.2): if `reproduction` is set, must be in VALID 4-tier or LEGACY (with stderr deprecation)
     - HARD (M1.4 — set EVIDENCE_REQUIRED env var to opt in): every record must have evidence string

The mode flag is an env var (`RESOLVE_REPRO_VERIFY_MODE`) so M1.2 and M1.4 share one
script and the registry can flip behavior with a one-character change.

Exit codes:
  0 — all assertions passed
  1 — at least one assertion failed (full traceback to stderr)
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ARTIFACT = Path(".runs/resolve-reproduction.json")

VALID_TIERS = ("cite", "grep", "exec", "validator-fed")
LEGACY_TIERS = ("validator-confirmed", "simulation-only")
STOPLIST_PHRASES = (
    "N/A",
    "see above",
    "trace shows",
    "I traced",
    "I read the file",
    "as described",
    "obvious from",
)
SEPARATOR_RE = re.compile(r"\s+(?:and|&|vs|\+|;)\s+", re.IGNORECASE)


def main() -> int:
    if not ARTIFACT.exists():
        print(f"FAIL: {ARTIFACT} not found", file=sys.stderr)
        return 1

    try:
        d = json.load(open(ARTIFACT))
    except json.JSONDecodeError as e:
        print(f"FAIL: {ARTIFACT} not valid JSON: {e}", file=sys.stderr)
        return 1

    rs = d.get("reproductions", [])
    if not isinstance(rs, list) or len(rs) == 0:
        print("FAIL: reproductions empty or not a list", file=sys.stderr)
        return 1

    # Legacy schema basics (preserved from pre-M1 VERIFY)
    r = rs[0]
    for field in ("divergence_point", "expected", "actual"):
        if field not in r:
            print(f"FAIL: reproductions[0].{field} missing", file=sys.stderr)
            return 1

    b = d.get("pre_fix_baseline", {})
    for field in ("frontmatter", "semantics", "consistency"):
        if field not in b:
            print(
                "FAIL: pre_fix_baseline incomplete (missing %r)" % field,
                file=sys.stderr,
            )
            return 1

    offenders = [
        x.get("divergence_point", "")
        for x in rs
        if isinstance(x, dict) and SEPARATOR_RE.search(x.get("divergence_point", "") or "")
    ]
    if offenders:
        print(
            "FAIL: divergence_point contract violated - embedded separator: %r" % offenders,
            file=sys.stderr,
        )
        return 1

    # M1 — empirical-verification checks
    mode = os.environ.get("RESOLVE_REPRO_VERIFY_MODE", "soft")  # "soft" (M1.2) or "hard" (M1.4)

    failures: list[str] = []

    for i, x in enumerate(rs):
        if not isinstance(x, dict):
            continue

        # Refine-mode bypass: trace_analysis reproductions have their own structured evidence
        # (failure_rate, sample_size, team_members_affected) that is NOT a plain string.
        if x.get("reproduction_method") == "trace_analysis":
            continue

        ev = x.get("evidence")
        rep = x.get("reproduction")

        # Hard-mode: require evidence presence (M1.4)
        if mode == "hard":
            if ev is None or not isinstance(ev, str) or not ev.strip():
                failures.append(
                    f"reproductions[{i}].evidence missing or empty (M1.4 hard requirement)"
                )
                continue

        # Soft + hard: when evidence is a string, validate it
        if isinstance(ev, str):
            if len(ev) < 30:
                failures.append(
                    f"reproductions[{i}].evidence too short ({len(ev)} chars, need >=30)"
                )
            else:
                low = ev.lower()
                hits = [s for s in STOPLIST_PHRASES if s.lower() in low]
                if hits:
                    failures.append(
                        f"reproductions[{i}].evidence contains stoplist phrase {hits!r} - "
                        "not concrete evidence (cite a URL, command, file:line, or fixture path)"
                    )

        # Soft + hard: when reproduction tier is set, validate enum
        if rep is not None:
            if rep in LEGACY_TIERS:
                sys.stderr.write(
                    f"DEPRECATION: reproductions[{i}].reproduction={rep!r} is legacy; "
                    f"use one of {VALID_TIERS} (one release cycle remaining before hard-cut)\n"
                )
            elif rep not in VALID_TIERS:
                failures.append(
                    f"reproductions[{i}].reproduction={rep!r} invalid; "
                    f"expected one of {VALID_TIERS} or legacy {LEGACY_TIERS}"
                )

        # Hard-mode: also require reproduction tier presence
        if mode == "hard" and rep is None:
            failures.append(
                f"reproductions[{i}].reproduction missing — required tier "
                f"(one of {VALID_TIERS}) (M1.4 hard requirement)"
            )

    if failures:
        for f in failures:
            print("FAIL: " + f, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
