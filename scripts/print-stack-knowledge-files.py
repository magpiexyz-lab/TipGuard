#!/usr/bin/env python3
"""Print every path that may contain a `## Stack Knowledge` section, one per line.

Single-purpose CLI shim around `lib.stack_knowledge_parser.iter_stack_knowledge_files()`
so CI workflows can use a stable script path instead of inline `python3 -c`. The
inline form is fine functionally but trips the GitHub Actions inline-injection
warning class — having a real script makes the workflow trivially auditable.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

from stack_knowledge_parser import iter_stack_knowledge_files  # noqa: E402


def main() -> int:
    for p in iter_stack_knowledge_files():
        print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
