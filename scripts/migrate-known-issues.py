#!/usr/bin/env python3
"""One-shot migration: rename `## Known Issues` → `## Stack Knowledge` in stack files.

Purpose (scoped narrowly on purpose):
  The forbidden-heading lint in scripts/validate-stack-knowledge.py rejects
  `^#{2,6}\\s+Known\\s+Issue(s?)\\b` headings. This script renames them to
  `## Stack Knowledge` and leaves the original ### subsections + prose
  untouched, so every word of existing human-readable knowledge is preserved.

What this script deliberately does NOT do:
  - It does NOT fabricate fenced YAML `## Stack Knowledge` entries from prose.
    Mechanically-derived composite_identity values are semantically thin:
    root_cause_class and divergence_pattern both collapse to the subsection
    title, producing degenerate single-axis hashes that /resolve-sedimented
    entries (which derive two genuinely distinct axes from solve-trace +
    reproduction) would never match. An entry that cannot be matched is dead
    weight in the namespace. Leave real YAML entry creation to STATE 9 of
    /resolve runs, where composite_identity is grounded in the run's trace.

Two-phase, approval-gated:

  Phase A (default, idempotent): scan every stack file, report what WILL be
  renamed into .runs/migration-draft/REPORT.md. No file mutation.

  Phase B (--execute): requires .runs/migration-approved.flag (containing the
  word 'approved' on any line). Renames the heading in-place, preserving
  body content and position.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys

STACK_GLOB = ".claude/stacks/**/*.md"
EXCLUDE_BASENAMES = {"TEMPLATE.md"}
DRAFT_DIR = ".runs/migration-draft"
APPROVAL_FLAG = ".runs/migration-approved.flag"

KNOWN_ISSUES_HEADER_RE = re.compile(r"^(?P<prefix>#{2,6})[ \t]+Known[ \t]+Issue[s]?[ \t]*$", re.IGNORECASE | re.MULTILINE)


def find_targets() -> list[tuple[str, int]]:
    """Return list of (path, line_no) for every Known Issues heading in scope."""
    targets: list[tuple[str, int]] = []
    for path in sorted(glob.glob(STACK_GLOB, recursive=True)):
        if os.path.basename(path) in EXCLUDE_BASENAMES:
            continue
        content = open(path).read()
        for m in KNOWN_ISSUES_HEADER_RE.finditer(content):
            line_no = content[: m.start()].count("\n") + 1
            targets.append((path, line_no))
    return targets


def phase_a(targets: list[tuple[str, int]]) -> None:
    os.makedirs(DRAFT_DIR, exist_ok=True)
    lines = ["# Known Issues → Stack Knowledge rename plan", "",
             "This migration renames the heading only. Body prose is preserved verbatim.",
             ""]
    for path, line_no in targets:
        lines.append(f"- `{path}:{line_no}` — rename heading to `## Stack Knowledge`")
    if not targets:
        lines.append("(No Known Issues headings found — nothing to do.)")
    with open(os.path.join(DRAFT_DIR, "REPORT.md"), "w") as f:
        f.write("\n".join(lines).rstrip() + "\n")
    print(f"Phase A complete. {len(targets)} heading(s) to rename → {DRAFT_DIR}/REPORT.md")
    print(f"Review the report, then `echo approved > {APPROVAL_FLAG}` and re-run with --execute.")


def _approved() -> bool:
    if not os.path.isfile(APPROVAL_FLAG):
        return False
    return any(ln.strip() == "approved" for ln in open(APPROVAL_FLAG).read().splitlines())


def phase_b(targets: list[tuple[str, int]]) -> int:
    if not _approved():
        print(f"ERROR: {APPROVAL_FLAG} missing or does not contain 'approved'. "
              "Run Phase A, review the report, then write 'approved' to the flag file.",
              file=sys.stderr)
        return 1

    seen_paths: set[str] = set()
    for path, _ in targets:
        seen_paths.add(path)

    rewritten = 0
    for path in sorted(seen_paths):
        content = open(path).read()
        new_content, n = KNOWN_ISSUES_HEADER_RE.subn(
            lambda m: f"{m.group('prefix')} Stack Knowledge",
            content,
        )
        if n > 0:
            with open(path, "w") as f:
                f.write(new_content)
            rewritten += 1
            print(f"  rewrote {path} ({n} heading(s))")
    print(f"Phase B complete. {rewritten} file(s) updated.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--execute", action="store_true",
                    help="Execute Phase B (requires .runs/migration-approved.flag).")
    args = ap.parse_args()

    targets = find_targets()
    phase_a(targets)
    if args.execute:
        return phase_b(targets)
    return 0


if __name__ == "__main__":
    sys.exit(main())
