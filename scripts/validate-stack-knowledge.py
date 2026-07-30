#!/usr/bin/env python3
"""Per-file Stack Knowledge validator.

Usage:
    python3 scripts/validate-stack-knowledge.py <file1> [<file2> ...]

Accepts stack file paths as CLI args and validates each independently. Designed to be
invoked from CI (with a glob of all stack files), from a pre-commit-style wrapper,
or directly by a developer while iterating on a stack file.

Checks per file:
  1. Schema:     each YAML entry contains REQUIRED_FIELDS with valid types/values.
  2. Hash recompute: composite_identity_hash matches compute_hash(composite_identity).
  3. Forbidden heading lint: any `^#{2,6}\\s+Known\\s+Issue(s?)\\b` match fails the file.
  4. Within-file uniqueness: no duplicate composite_identity_hash in the same file.

Exits 0 clean / 1 on any failure.
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.stack_knowledge_parser import (  # noqa: E402
    REQUIRED_FIELDS,
    MATURITY_VALUES,
    compute_hash,
    is_archive_path,
    parse_stack_knowledge,
)

FORBIDDEN_HEADING_RE = re.compile(r"^#{2,6}\s+Known\s+Issue(s?)\b[^\n]*$", re.IGNORECASE | re.MULTILINE)


def _validate_entry(entry: dict, index: int) -> list[str]:
    errs: list[str] = []
    prefix = f"entry[{index}]"

    missing = REQUIRED_FIELDS - entry.keys()
    if missing:
        errs.append(f"{prefix} missing required fields: {sorted(missing)}")

    maturity = entry.get("maturity")
    if maturity not in MATURITY_VALUES:
        errs.append(f"{prefix} maturity={maturity!r} not in {sorted(MATURITY_VALUES)}")

    conf = entry.get("confidence_score")
    if not isinstance(conf, (int, float)) or not (0.0 <= float(conf) <= 1.0):
        errs.append(f"{prefix} confidence_score={conf!r} must be a float in [0.0, 1.0]")

    occ = entry.get("occurrence_count")
    if not isinstance(occ, int) or occ < 1:
        errs.append(f"{prefix} occurrence_count={occ!r} must be int >= 1")

    composite = entry.get("composite_identity")
    claimed_hash = entry.get("composite_identity_hash")
    if isinstance(composite, dict) and isinstance(claimed_hash, str):
        recomputed = compute_hash(composite)
        if recomputed != claimed_hash:
            errs.append(
                f"{prefix} composite_identity_hash={claimed_hash!r} does not match "
                f"recomputed {recomputed!r}"
            )

    linked = entry.get("linked_issues")
    if not isinstance(linked, list):
        errs.append(f"{prefix} linked_issues must be a list")

    symptoms = entry.get("symptom_keywords")
    if not isinstance(symptoms, list):
        errs.append(f"{prefix} symptom_keywords must be a list")

    if entry.get("anti_pattern") is True:
        prev = entry.get("prevention_mechanism")
        if not isinstance(prev, str) or not prev.strip():
            errs.append(
                f"{prefix} anti_pattern=true requires non-empty prevention_mechanism"
            )
        if maturity != "canonical":
            errs.append(
                f"{prefix} anti_pattern=true requires maturity='canonical' "
                f"(got {maturity!r})"
            )

    return errs


def validate_file(path: str) -> list[str]:
    errs: list[str] = []
    if not os.path.exists(path):
        return [f"{path}: file not found"]
    try:
        content = open(path).read()
    except (OSError, UnicodeDecodeError) as e:
        return [f"{path}: cannot read ({e})"]

    if FORBIDDEN_HEADING_RE.search(content):
        errs.append(
            f"{path}: forbidden '## Known Issues' heading detected — migrate to "
            "'## Stack Knowledge' (see .claude/stacks/TEMPLATE.md)"
        )

    entries = parse_stack_knowledge(content)
    seen_hashes: dict[str, int] = {}
    for i, entry in enumerate(entries):
        errs.extend(f"{path}: {e}" for e in _validate_entry(entry, i))
        h = entry.get("composite_identity_hash")
        if isinstance(h, str):
            if h in seen_hashes:
                errs.append(
                    f"{path}: entry[{i}] duplicate composite_identity_hash={h!r} "
                    f"(also in entry[{seen_hashes[h]}])"
                )
            else:
                seen_hashes[h] = i

    return errs


def main(argv: list[str]) -> int:
    paths = [p for p in argv[1:] if p and not is_archive_path(p)]
    if not paths:
        return 0

    all_errs: list[str] = []
    for p in paths:
        all_errs.extend(validate_file(p))

    if all_errs:
        print("Stack Knowledge validation failed:", file=sys.stderr)
        for e in all_errs:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print(f"Stack Knowledge validation passed ({len(paths)} file(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
