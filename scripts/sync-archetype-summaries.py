#!/usr/bin/env python3
"""sync-archetype-summaries.py — One-directional sync: canonical -> embedding files.

Reads `## Canonical Summary Lines` from `.claude/patterns/archetype-behavior-check.md`
and overwrites `> [<slug>] ...` lines in files whose REF cites
`row "<X>"` or `rows "<X>", "<Y>"` syntax.

Usage:
    python3 scripts/sync-archetype-summaries.py --dry-run
    python3 scripts/sync-archetype-summaries.py --apply

Mirrors `.claude/scripts/sync-verify-to-state-files.sh` (Rule 13 sync pattern).
"""
import glob
import os
import re
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
CANONICAL = os.path.join(REPO_ROOT, ".claude/patterns/archetype-behavior-check.md")
SCAN_GLOBS = [
    ".claude/skills/**/*.md",
    ".claude/procedures/**/*.md",
    ".claude/agents/**/*.md",
    ".claude/patterns/**/*.md",
]


def parse_canonical(path):
    """Parse `## Canonical Summary Lines` section into {row_name: (slug, line)}."""
    text = open(path).read()
    section_match = re.search(
        r"^## Canonical Summary Lines\b.*?(?=^## )",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if not section_match:
        sys.stderr.write(
            "ERROR: '## Canonical Summary Lines' section not found in "
            f"{os.path.relpath(path, REPO_ROOT)}\n"
        )
        sys.exit(1)
    section = section_match.group(0)

    rows = {}
    seen_slugs = {}
    for sub in re.finditer(
        r"^####\s+(.+?)\s*\n"
        r"slug:\s*`([^`]+)`\s*\n"
        r"(>\s*\[[^\]]+\][^\n]*)",
        section,
        re.MULTILINE,
    ):
        row_name = sub.group(1).strip()
        slug = sub.group(2).strip()
        line = sub.group(3).strip()
        if slug in seen_slugs:
            sys.stderr.write(
                f"ERROR: duplicate slug '{slug}' in canonical Summary Lines "
                f"(rows: '{seen_slugs[slug]}' and '{row_name}')\n"
            )
            sys.exit(1)
        seen_slugs[slug] = row_name
        rows[row_name] = (slug, line)

    if not rows:
        sys.stderr.write(
            "ERROR: '## Canonical Summary Lines' section has zero "
            "`#### <Row>` subsections\n"
        )
        sys.exit(1)

    return rows


def discover_files():
    """Auto-discover files whose REF cites Quick-Reference Table rows."""
    candidates = set()
    for pattern in SCAN_GLOBS:
        full = os.path.join(REPO_ROOT, pattern)
        for path in glob.glob(full, recursive=True):
            if os.path.basename(path) == "archetype-behavior-check.md":
                continue
            try:
                text = open(path).read()
            except (IOError, UnicodeDecodeError):
                continue
            if find_row_citing_ref(text):
                candidates.add(path)
    return sorted(candidates)


REF_RE = re.compile(
    r"^>\s*REF.*archetype-behavior-check\.md.*Quick-Reference Table",
    re.MULTILINE,
)
ROW_LIST_RE = re.compile(r'rows?\s+("[^"]+"(?:\s*,\s*"[^"]+")*)')
QUOTED_RE = re.compile(r'"([^"]+)"')


def find_row_citing_ref(text):
    """Return list of (ref_line_match, [cited_rows]) for non-Compound REFs.

    Handles both `row "X"` (single) and `rows "X", "Y", "Z"` (multi).
    """
    found = []
    for m in REF_RE.finditer(text):
        eol = text.find("\n", m.start())
        line = text[m.start():eol if eol != -1 else len(text)]
        if "Compound Dimensions" in line:
            continue
        rows_match = ROW_LIST_RE.search(line)
        if not rows_match:
            continue
        cited = QUOTED_RE.findall(rows_match.group(1))
        if cited:
            found.append((m, cited))
    return found


SLUG_LINE_RE = re.compile(r"^>\s*\[[a-z0-9-]+\][^\n]*", re.MULTILINE)


def sync_file(path, canonical, dry_run):
    """Sync one file's canonical summary lines.

    Returns one of: 'updated', 'already-synced', 'skipped-missing-row',
    'skipped-no-block', 'error'.
    """
    text = open(path).read()
    refs = find_row_citing_ref(text)
    if not refs:
        return "skipped-no-ref"

    new_text = text
    file_dirty = False
    skipped_row = False

    for ref_match, cited_rows in refs:
        # Validate all cited rows exist in canonical
        missing = [r for r in cited_rows if r not in canonical]
        if missing:
            sys.stderr.write(
                f"WARNING: {os.path.relpath(path, REPO_ROOT)}: "
                f"REF cites row(s) absent from canonical: {missing}; skipping\n"
            )
            skipped_row = True
            continue

        # Locate REF line position in the (possibly already-mutated) new_text.
        # Re-find by exact line content to survive prior iterations.
        ref_line_text = text[ref_match.start():text.find("\n", ref_match.start())]
        ref_pos = new_text.find(ref_line_text)
        if ref_pos == -1:
            continue

        # Find the contiguous blockquote group following REF.
        # Group = consecutive lines starting with `>` (including empty `>` lines).
        # Stop at first non-blockquote line.
        scan_start = new_text.find("\n", ref_pos) + 1
        block_end = scan_start
        for line_match in re.finditer(r"^[^\n]*(\n|$)", new_text[scan_start:], re.MULTILINE):
            line = line_match.group(0)
            if not line.startswith(">"):
                break
            block_end = scan_start + line_match.end()
        block = new_text[scan_start:block_end]

        # Build canonical lines for this REF's cited rows
        canonical_lines = [canonical[r][1] for r in cited_rows]
        canonical_slugs = {canonical[r][0] for r in cited_rows}

        # Replace existing slug-bracketed lines OR insert if missing
        existing_slug_lines = list(SLUG_LINE_RE.finditer(block))
        existing_slugs = set()
        for m in existing_slug_lines:
            sm = re.match(r">\s*\[([a-z0-9-]+)\]", m.group(0))
            if sm:
                existing_slugs.add(sm.group(1))

        if existing_slug_lines and existing_slugs == canonical_slugs:
            # Replace each existing slug line with its canonical counterpart
            new_block = block
            offset = 0
            for m in existing_slug_lines:
                sm = re.match(r">\s*\[([a-z0-9-]+)\]", m.group(0))
                if not sm:
                    continue
                slug = sm.group(1)
                canon_line = next(
                    canonical[r][1] for r in cited_rows if canonical[r][0] == slug
                )
                start = m.start() + offset
                end = m.end() + offset
                new_block = new_block[:start] + canon_line + new_block[end:]
                offset += len(canon_line) - (m.end() - m.start())
        else:
            # Either no slug lines yet, or set mismatch — replace the entire
            # blockquote group with REF + empty divider + canonical lines + preserved prose
            preserved_lines = []
            for line in block.splitlines():
                if not line.startswith(">"):
                    continue
                stripped = line.lstrip(">").strip()
                if not stripped:
                    continue
                # Skip slug-bracketed lines (canonical replaces them)
                if re.match(r"\[[a-z0-9-]+\]", stripped):
                    continue
                # Skip generic "web-app: ... | service: ... | cli: ..." summary lines
                # (heuristic: contains both 'web-app' and 'service' and 'cli' separated by '|')
                if "web-app" in stripped and "service" in stripped and "cli" in stripped \
                   and stripped.count("|") >= 2:
                    continue
                preserved_lines.append(line)

            new_block_parts = [">"]
            new_block_parts.extend(canonical_lines)
            if preserved_lines:
                new_block_parts.append(">")
                new_block_parts.extend(preserved_lines)
            new_block = "\n".join(new_block_parts) + "\n"

        if new_block != block:
            new_text = new_text[:scan_start] + new_block + new_text[block_end:]
            file_dirty = True

    if not file_dirty:
        return "already-synced" if not skipped_row else "skipped-missing-row"

    rel = os.path.relpath(path, REPO_ROOT)
    if dry_run:
        print(f"WOULD UPDATE: {rel}")
    else:
        try:
            with open(path, "w") as f:
                f.write(new_text)
        except IOError as e:
            sys.stderr.write(f"ERROR: cannot write {rel}: {e}\n")
            return "error"
        print(f"UPDATED: {rel}")
    return "updated"


def main():
    args = sys.argv[1:]
    if not args or args[0] not in ("--dry-run", "--apply"):
        sys.stderr.write(
            "Usage: python3 scripts/sync-archetype-summaries.py "
            "(--dry-run|--apply)\n"
        )
        sys.exit(2)
    dry_run = args[0] == "--dry-run"

    if not os.path.isfile(CANONICAL):
        sys.stderr.write(
            f"ERROR: canonical file not found: "
            f"{os.path.relpath(CANONICAL, REPO_ROOT)}\n"
        )
        sys.exit(1)

    canonical = parse_canonical(CANONICAL)

    files = discover_files()
    counts = {
        "updated": 0,
        "already-synced": 0,
        "skipped-no-ref": 0,
        "skipped-missing-row": 0,
        "skipped-no-block": 0,
        "error": 0,
    }
    aborted = False
    for path in files:
        try:
            result = sync_file(path, canonical, dry_run)
        except Exception as e:
            sys.stderr.write(
                f"ERROR: {os.path.relpath(path, REPO_ROOT)}: {e}\n"
            )
            counts["error"] += 1
            aborted = True
            break
        counts[result] = counts.get(result, 0) + 1

    print(
        "\nSync complete: "
        f"{counts['updated']} updated, "
        f"{counts['already-synced']} already synced, "
        f"{counts['skipped-missing-row']} skipped (missing row), "
        f"{counts['error']} errors"
    )
    if aborted:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
