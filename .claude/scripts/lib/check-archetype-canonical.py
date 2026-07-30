#!/usr/bin/env python3
"""check-archetype-canonical.py — Check 23h validator.

Verifies that files citing Quick-Reference Table rows via `row "X"` syntax
embed the verbatim canonical labeled line from
`.claude/patterns/archetype-behavior-check.md` `## Canonical Summary Lines`.

Sub-rules:
  1. Slug-existence — every cited row name must have a `#### <Row>` subsection
  2. Multi-row count — N cited rows require N matching `> [<slug>] ...` lines
  3. Verbatim match — embedded lines must equal canonical (whitespace-collapsed)
  4. Slug uniqueness — canonical Summary Lines must not have duplicate slugs

Scope: BRANCHING + REFERENCE_ONLY files (from `scripts/consistency-check.sh`)
whose REF cites `row "X"` or `rows "X", "Y"` syntax, EXCLUDING REFs containing
`Compound Dimensions` substring.

Exit 0 on success, 1 on any failure (with stderr enumeration).
"""
import os
import re
import sys

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, os.pardir)
)
CANONICAL = os.path.join(REPO_ROOT, ".claude/patterns/archetype-behavior-check.md")
CONSISTENCY_SCRIPT = os.path.join(REPO_ROOT, "scripts/consistency-check.sh")


def parse_canonical(path):
    """Parse `## Canonical Summary Lines` section into {row_name: (slug, line)}.

    Fails (exit 1) on missing section, duplicate slugs, or zero subsections.
    """
    if not os.path.isfile(path):
        sys.stderr.write(f"FAIL: canonical file not found: {path}\n")
        sys.exit(1)
    text = open(path).read()
    section_match = re.search(
        r"^## Canonical Summary Lines\b.*?(?=^## )",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if not section_match:
        sys.stderr.write(
            "FAIL: archetype-behavior-check.md — missing "
            "'## Canonical Summary Lines' section\n"
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
                f"FAIL: archetype-behavior-check.md — duplicate slug '{slug}' "
                f"(rows: '{seen_slugs[slug]}' and '{row_name}')\n"
            )
            sys.exit(1)
        seen_slugs[slug] = row_name
        rows[row_name] = (slug, line)

    if not rows:
        sys.stderr.write(
            "FAIL: archetype-behavior-check.md — '## Canonical Summary Lines' "
            "has zero `#### <Row>` subsections\n"
        )
        sys.exit(1)

    return rows


def parse_archetype_files(consistency_path):
    """Extract ARCHETYPE_BRANCHING_FILES + ARCHETYPE_REFERENCE_ONLY_FILES.

    Reads the bash arrays from consistency-check.sh. Array literals end at
    a line whose only content is `)` (column-0 close paren); inline `)`
    inside comments is tolerated.
    """
    if not os.path.isfile(consistency_path):
        sys.stderr.write(f"FAIL: consistency-check.sh not found: {consistency_path}\n")
        sys.exit(1)
    files = []
    for array_name in ("ARCHETYPE_BRANCHING_FILES", "ARCHETYPE_REFERENCE_ONLY_FILES"):
        in_array = False
        found = False
        with open(consistency_path) as fh:
            for line in fh:
                if not in_array:
                    if line.startswith(f"{array_name}=("):
                        in_array = True
                        found = True
                    continue
                # Array end: line whose first non-space char is `)` and no other content
                if re.match(r"^\s*\)\s*$", line):
                    in_array = False
                    continue
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                quoted = re.match(r'"([^"]+)"', stripped)
                if quoted:
                    files.append(quoted.group(1))
        if not found:
            sys.stderr.write(
                f"FAIL: {os.path.basename(consistency_path)} — array "
                f"{array_name} not found\n"
            )
            sys.exit(1)
    return files


REF_RE = re.compile(
    r"^>\s*REF.*archetype-behavior-check\.md.*Quick-Reference Table",
    re.MULTILINE,
)
ROW_LIST_RE = re.compile(r'rows?\s+("[^"]+"(?:\s*,\s*"[^"]+")*)')
QUOTED_RE = re.compile(r'"([^"]+)"')
SLUG_LINE_RE = re.compile(r"^>\s*\[([a-z0-9-]+)\]\s*[^\n]*", re.MULTILINE)


def find_row_citing_refs(text):
    """Yield (ref_match, [cited_rows]) for non-Compound row-citing REFs."""
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
            yield (m, cited)


def normalize(s):
    """Whitespace-collapsed comparison normalizer."""
    return re.sub(r"\s+", " ", s.strip())


def check_file(path, canonical):
    """Run sub-rules on one file. Returns list of error strings."""
    errors = []
    rel = os.path.relpath(path, REPO_ROOT)
    if not os.path.isfile(path):
        return errors  # 23e/23f handles file-not-found
    text = open(path).read()

    for ref_match, cited_rows in find_row_citing_refs(text):
        # Sub-rule 1: slug-existence
        missing = [r for r in cited_rows if r not in canonical]
        if missing:
            for r in missing:
                errors.append(
                    f"FAIL: {rel} — REF cites row \"{r}\" but no '#### {r}' "
                    f"subsection in '## Canonical Summary Lines'"
                )
            continue  # cannot validate further without canonical entries

        # Find contiguous blockquote group following REF
        scan_start = text.find("\n", ref_match.start()) + 1
        block_end = scan_start
        for line_match in re.finditer(
            r"^[^\n]*(\n|$)", text[scan_start:], re.MULTILINE
        ):
            line = line_match.group(0)
            if not line.startswith(">"):
                break
            block_end = scan_start + line_match.end()
        block = text[scan_start:block_end]

        # Find embedded slug-bracketed lines
        embedded = {}
        for m in SLUG_LINE_RE.finditer(block):
            slug = m.group(1)
            line = m.group(0).strip()
            embedded[slug] = line

        # Sub-rule 2 (multi-row count) + Sub-rule 3 (verbatim match)
        for row in cited_rows:
            slug, canon_line = canonical[row]
            if slug not in embedded:
                errors.append(
                    f"FAIL: {rel} — REF cites row \"{row}\" but missing "
                    f"embedded canonical line `> [{slug}] ...` in blockquote "
                    f"following REF"
                )
                continue
            if normalize(embedded[slug]) != normalize(canon_line):
                errors.append(
                    f"FAIL: {rel} — embedded line for row \"{row}\" drifted "
                    f"from canonical:\n  expected: {canon_line}\n  actual:   "
                    f"{embedded[slug]}"
                )

    return errors


def main():
    canonical = parse_canonical(CANONICAL)
    files = parse_archetype_files(CONSISTENCY_SCRIPT)

    all_errors = []
    for f in files:
        full = os.path.join(REPO_ROOT, f)
        all_errors.extend(check_file(full, canonical))

    if all_errors:
        for e in all_errors:
            sys.stderr.write(e + "\n")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
