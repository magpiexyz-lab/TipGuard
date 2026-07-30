#!/usr/bin/env python3
"""Cross-file CI-only Stack Knowledge check.

Runs AFTER scripts/validate-stack-knowledge.py. Walks every path returned by
`iter_stack_knowledge_files()` (single source of truth — currently
`.claude/stacks/**/*.md` plus `.claude/scripts/lib/README.md`, with TEMPLATE.md
and *.archive.md excluded), parses all Stack Knowledge entries, and enforces
global composite_identity_hash uniqueness.

Exits 0 clean / 1 on any failure.
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.stack_knowledge_parser import (  # noqa: E402
    iter_stack_knowledge_files,
    parse_stack_knowledge,
)


def main() -> int:
    start = time.perf_counter()
    paths = iter_stack_knowledge_files()

    index: dict[str, list[tuple[str, int]]] = {}
    total_entries = 0
    for path in paths:
        try:
            content = open(path).read()
        except (OSError, UnicodeDecodeError):
            continue
        for i, entry in enumerate(parse_stack_knowledge(content)):
            h = entry.get("composite_identity_hash")
            if isinstance(h, str):
                index.setdefault(h, []).append((path, i))
                total_entries += 1

    duplicates = {h: locs for h, locs in index.items() if len(locs) > 1}
    elapsed = time.perf_counter() - start
    print(
        f"ci-check-stack-knowledge: scanned {len(paths)} file(s), "
        f"{total_entries} entries in {elapsed:.3f}s"
    )

    if duplicates:
        print("Cross-file duplicate composite_identity_hash(es) detected:", file=sys.stderr)
        for h, locs in sorted(duplicates.items()):
            print(f"  - {h}:", file=sys.stderr)
            for path, idx in locs:
                print(f"      {path}  (entry[{idx}])", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
