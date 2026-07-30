#!/usr/bin/env python3
"""codemod-canonical-writer.py — apply mechanical rewrites for Issue #1299.

Walks the migration scope (recomputed from gate-readable-artifacts-canonical.json
on every invocation — does NOT trust a stale audit manifest) and rewrites
mechanically-extractable writes to the canonical writer pattern from
`.claude/skills/deploy/state-3b-provision-host.md:64-97`:

    PAYLOAD=$(python3 -c "
    import json
    <existing python source, with json.dump replaced by print(json.dumps(...))>
    ")
    bash .claude/scripts/lib/write-gate-artifact.sh \\
      --path <target-path> \\
      --payload "$PAYLOAD" \\
      --skill <skill>

Mode A: rewrites payload_complexity=mechanical S1+S2 sites whose surrounding
python heredoc has exactly one in-scope write call.

Mode B: refuses (emits to .runs/canonical-writer-manual-queue.json) for
bash_interpolated, conditional, mixed, verify_misplacement, multi-write
heredocs, S3 heredocs, S4 echo redirects, and anything where the first
argument to json.dump cannot be cleanly extracted by balanced-paren walking.

The codemod is idempotent — re-running on already-migrated files is a no-op
(detected by the presence of `bash .claude/scripts/lib/write-gate-artifact.sh
--path <target-path>` in the same scope).

Section guard: only rewrites inside **ACTIONS:**, **POSTCONDITIONS:**, and
**STATE TRACKING:** sections. Never edits **VERIFY:** (R1-C3, R1-C7) so it
cannot collide with sync-verify-to-state-files.sh.

Usage:
    python3 .claude/scripts/codemod-canonical-writer.py             # apply in place
    python3 .claude/scripts/codemod-canonical-writer.py --dry-run   # print diff, no writes
    python3 .claude/scripts/codemod-canonical-writer.py --check     # exit 1 if rewrites needed
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT_SCRIPT = REPO_ROOT / ".claude/scripts/codemod-canonical-writer-audit.py"
MANIFEST_PATH = REPO_ROOT / ".claude/patterns/gate-readable-artifacts-canonical.json"
MANUAL_QUEUE_PATH = REPO_ROOT / ".runs/canonical-writer-manual-queue.json"

# Re-use the audit script's detection module by importing it.
sys.path.insert(0, str(AUDIT_SCRIPT.parent))
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "audit_mod", AUDIT_SCRIPT,
)
_audit_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_audit_mod)

WRITE_PATTERNS = _audit_mod.WRITE_PATTERNS
SECTION_MARKERS = _audit_mod.SECTION_MARKERS
_section_for_line = _audit_mod._section_for_line
_classify_payload_complexity = _audit_mod._classify_payload_complexity
_find_payload_scope = _audit_mod._find_payload_scope
_line_is_suppressed = _audit_mod._line_is_suppressed
_enumerate_files = _audit_mod._enumerate_files

# Identity fields that the canonical writer auto-stamps. Caller payloads must
# NOT include them; the codemod strips them from the payload-construction
# python source. NOTE: `timestamp` is intentionally NOT in this set — it is a
# domain-meaningful field (e.g., when a teardown ran, when an experiment was
# validated) and must not be conflated with `written_at` (when the artifact
# was written by the canonical writer).
STAMPED_KEYS = ("skill", "run_id", "written_at")
# Idempotency signal: the canonical-writer invocation pattern. If found in
# the same scope, that scope is already migrated — skip.
CANONICAL_WRITER_RE = re.compile(
    r"""bash\s+\.claude/scripts/lib/write-gate-artifact\.sh\s+--path\s+(?P<path>\.runs/[^\s'"]+)"""
)
# Section markers we may rewrite within. NEVER **VERIFY:** (sync-verify owns it).
REWRITABLE_SECTIONS = {"ACTIONS", "POSTCONDITIONS", "STATE TRACKING"}


# ----- balanced-paren extraction ------------------------------------------

def _extract_first_arg(call_text: str, open_paren_idx: int) -> tuple[str, int] | None:
    """Given a call like 'json.dump(arg1, arg2, ...)' starting at the index
    of the opening paren, return (arg1_text, idx_of_first_comma_at_depth_1).

    Tracks parens, brackets, and braces (so commas inside dict/list literals
    are NOT mistaken for argument separators) and respects string literals.
    Returns None if balanced-bracket walking fails.
    """
    if open_paren_idx >= len(call_text) or call_text[open_paren_idx] != "(":
        return None
    paren = bracket = brace = 0
    in_str: str | None = None
    arg_start = open_paren_idx + 1
    i = arg_start
    while i < len(call_text):
        ch = call_text[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
        else:
            if ch in ("'", '"'):
                in_str = ch
            elif ch == "(":
                paren += 1
            elif ch == ")":
                if paren == 0 and bracket == 0 and brace == 0:
                    return call_text[arg_start:i].strip(), i
                paren -= 1
            elif ch == "[":
                bracket += 1
            elif ch == "]":
                bracket -= 1
            elif ch == "{":
                brace += 1
            elif ch == "}":
                brace -= 1
            elif ch == "," and paren == 0 and bracket == 0 and brace == 0:
                return call_text[arg_start:i].strip(), i
        i += 1
    return None


# ----- python heredoc scope detection -------------------------------------

PY_HEREDOC_DASH_C_OPEN = re.compile(r"""python3?\s+-c\s*(?P<q>['"])""")
PY_HEREDOC_END_DOUBLE = re.compile(r'^"\s*\)?$')
PY_HEREDOC_END_SINGLE = re.compile(r"^'\s*\)?$")


def _find_python_dash_c_scope(lines: list[str], match_line_idx: int) -> tuple[int, int, str] | None:
    """Find the bounds of the python3 -c "..." heredoc enclosing match_line_idx.

    Returns (start_line, end_line, quote_char). Returns None if not found.
    The start_line is the line containing `python3 -c "` (the body starts on
    the NEXT line for multi-line heredocs); end_line is the line whose first
    non-whitespace char is the matching close quote.

    The walker bounds upward search by hard boundaries (markdown headers,
    closing bash fences) so the heredoc-opening detection cannot match a
    different code block above the current section.
    """
    quote = None
    start = None
    # Walk back to file start; stop at hard boundaries to avoid leaking
    # into a previous code block.
    for i in range(match_line_idx, -1, -1):
        line = lines[i]
        if i != match_line_idx and any(b.match(line) for b in HARD_BOUNDARIES):
            return None
        m = PY_HEREDOC_DASH_C_OPEN.search(line)
        if m:
            # Verify this is a multi-line heredoc — the open quote isn't
            # closed on the same line.
            after_open = line[m.end():]
            if m.group("q") not in after_open:
                start = i
                quote = m.group("q")
                break
            # Single-line python -c — we'll handle by matching on the same line.
            start = i
            quote = m.group("q")
            break
    if start is None:
        return None

    # Walk forward to find the matching close quote on its own line OR on the
    # match line. For multi-line, we expect a line like '"' or "'" or '")' etc.
    end = match_line_idx
    end_re = PY_HEREDOC_END_DOUBLE if quote == '"' else PY_HEREDOC_END_SINGLE
    for j in range(match_line_idx, len(lines)):
        line = lines[j]
        if j != match_line_idx and any(b.match(line) for b in HARD_BOUNDARIES):
            return None
        stripped = line.strip()
        if end_re.match(stripped):
            end = j
            break
    else:
        return None

    return start, end, quote


# HARD_BOUNDARIES from the audit module — markdown section markers and bash
# fences that definitively close a python heredoc scope.
HARD_BOUNDARIES = _audit_mod.HARD_BOUNDARIES


# ----- payload key scrubbing ---------------------------------------------

def _strip_stamped_keys(py_source_lines: list[str]) -> list[str]:
    """Best-effort: remove dict entries whose key is in STAMPED_KEYS from the
    payload python source. Lines like `'skill': 'foo',` or `'run_id': RID,`
    are dropped wholesale. This is conservative — only matches single-line
    dict-entry shapes.
    """
    out = []
    key_re = re.compile(
        r"""^(\s*)['"](?:""" + "|".join(STAMPED_KEYS) + r""")['"]\s*:\s*[^,}]+,?\s*(?:#.*)?$"""
    )
    for line in py_source_lines:
        if key_re.match(line):
            continue
        out.append(line)
    return out


# ----- json.dump rewrite -------------------------------------------------

JSON_DUMP_PREFIX_RE = re.compile(r"""\bjson\.dump\s*\(""")


def _find_balanced_close(call_text: str, after_open_idx: int) -> int | None:
    """Given an index right AFTER an open paren, return the index of the
    matching close paren (tracks parens, brackets, braces, strings). None
    if unbalanced."""
    paren = 0  # depth INSIDE the outer paren
    bracket = brace = 0
    in_str = None
    i = after_open_idx
    while i < len(call_text):
        ch = call_text[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
        else:
            if ch in ("'", '"'):
                in_str = ch
            elif ch == "(":
                paren += 1
            elif ch == ")":
                if paren == 0 and bracket == 0 and brace == 0:
                    return i
                paren -= 1
            elif ch == "[":
                bracket += 1
            elif ch == "]":
                bracket -= 1
            elif ch == "{":
                brace += 1
            elif ch == "}":
                brace -= 1
        i += 1
    return None


def _rewrite_s1_pattern(py_source: str, target_path: str) -> tuple[str, str] | None:
    """Handle S1 shape: `with open(target, 'w') as <var>:` followed by
    `json.dump(<arg>, <var>, ...)` indented inside.

    Replaces the entire 2-line block (with-line + dump-line) with a single
    `print(json.dumps(<arg>))` line at the with-line's indent. Refuses if the
    with-block has more content than just the dump call.

    Returns (rewritten_source, extracted_arg) or None.
    """
    pattern = re.compile(
        r"""(?m)^(?P<lead>[ \t]*)with\s+open\(\s*['"]"""
        + re.escape(target_path)
        + r"""['"]\s*,\s*['"]w['"][^)]*\)\s+as\s+(?P<var>\w+)\s*:[ \t]*(?:#[^\n]*)?\n"""
        r"""(?P<body_indent>[ \t]+)json\.dump\("""
    )
    m = pattern.search(py_source)
    if m is None:
        return None
    lead = m.group("lead")
    var = m.group("var")
    body_indent = m.group("body_indent")
    if len(body_indent) <= len(lead):
        return None

    # The position right after the `(` of json.dump.
    after_open_idx = m.end()
    # Extract first arg.
    first = _extract_first_arg(py_source, after_open_idx - 1)
    if first is None:
        return None
    arg, comma_idx = first
    # Find close of dump call.
    close_idx = _find_balanced_close(py_source, comma_idx + 1)
    if close_idx is None:
        return None
    # Verify second arg references the bound var (allow whitespace, optional
    # trailing kwargs like `indent=2`).
    rest_text = py_source[comma_idx + 1 : close_idx]
    if not re.match(r"""\s*""" + re.escape(var) + r"""\s*(?:,|$)""", rest_text):
        return None

    # Verify the with-block contains ONLY the dump call (i.e., no other
    # statements at body_indent before or after). The dump statement starts
    # at body_indent + "json.dump" position and ends at close_idx + 1.
    # Check: line containing the dump close should be the last line of the
    # with-block. We approximate by requiring that the next non-whitespace
    # line after the dump's closing `)` is either dedented or end-of-source.
    after_dump = py_source[close_idx + 1 :]
    # First non-whitespace line.
    next_line_match = re.match(r"""\s*\n([ \t]*)\S""", after_dump)
    if next_line_match is not None:
        next_indent = next_line_match.group(1)
        if len(next_indent) >= len(body_indent):
            # Another statement inside the with-block — refuse.
            return None

    # Build replacement: drop the `with open ... as var:` line entirely;
    # replace the dump call with `print(json.dumps(<arg>))`, dedented to
    # the lead indent.
    new_block = f"{lead}print(json.dumps({arg}))"
    return py_source[: m.start()] + new_block + py_source[close_idx + 1 :], arg


def _rewrite_dump_to_dumps(py_source: str, target_path: str) -> tuple[str, str] | None:
    """Find `json.dump(<expr>, open(target_path, 'w'), ...)` in py_source,
    rewrite as `print(json.dumps(<expr>))`. Return (rewritten_source,
    extracted_expr). If no clean match, return None.
    """
    matches = list(JSON_DUMP_PREFIX_RE.finditer(py_source))
    chosen = None
    for m in matches:
        # After `json.dump(`, walk to extract first arg.
        first = _extract_first_arg(py_source, m.end() - 1)
        if first is None:
            continue
        first_arg, comma_idx = first
        # The remaining args (from comma_idx onward) should reference the
        # target path. If not, this dump isn't ours.
        rest = py_source[comma_idx + 1:]
        # End of the dump call.
        depth = 1
        end_idx = None
        in_str = None
        i = 0
        while i < len(rest):
            ch = rest[i]
            if in_str:
                if ch == "\\":
                    i += 2
                    continue
                if ch == in_str:
                    in_str = None
            else:
                if ch in ("'", '"'):
                    in_str = ch
                elif ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        end_idx = i
                        break
            i += 1
        if end_idx is None:
            continue
        rest_call_text = rest[:end_idx]
        if target_path not in rest_call_text:
            continue
        # Verify open(...,'w') in the rest.
        if not re.search(r"""open\s*\(\s*['"]""" + re.escape(target_path) + r"""['"]\s*,\s*['"][w]""", rest_call_text):
            continue
        # Found the matching dump call.
        full_call_start = m.start()
        full_call_end = comma_idx + 1 + end_idx + 1  # +1 for closing ')'
        chosen = (full_call_start, full_call_end, first_arg)
        break

    if chosen is None:
        return None
    start, end, arg = chosen
    new_call = f"print(json.dumps({arg}))"
    rewritten = py_source[:start] + new_call + py_source[end:]
    return rewritten, arg


# ----- skill name from file path -----------------------------------------

def _skill_from_file(rel_path: str) -> str | None:
    m = re.match(r"\.claude/skills/([^/]+)/", rel_path)
    if m:
        return m.group(1)
    return None


# ----- per-file rewrite ---------------------------------------------------

def _candidate_writes(text: str, manifest_paths: set[str]) -> list[dict]:
    """Return all in-scope mechanical writes in `text` (file content)."""
    lines = text.splitlines()
    out = []
    for line_idx, line in enumerate(lines):
        if _line_is_suppressed(line):
            continue
        for shape, pattern in WRITE_PATTERNS:
            for match in pattern.finditer(line):
                target = match.group("path")
                mode = match.groupdict().get("mode", "w")
                if target not in manifest_paths or mode != "w":
                    continue
                section = _section_for_line(lines, line_idx)
                complexity = _classify_payload_complexity(lines, line_idx, section)
                if complexity != "mechanical":
                    continue
                if section not in REWRITABLE_SECTIONS:
                    continue
                # Only S1 and S2 are auto-rewritable. S3/S4/TEE go to manual
                # queue.
                if shape not in ("S1", "S2"):
                    continue
                out.append({
                    "line_idx": line_idx,
                    "target": target,
                    "shape": shape,
                    "section": section,
                })
    return out


def _is_already_migrated(lines: list[str], target: str) -> bool:
    """True if the canonical-writer call for target already exists somewhere
    in the file."""
    for line in lines:
        m = CANONICAL_WRITER_RE.search(line)
        if m and m.group("path") == target:
            return True
    return False


def _rewrite_one_site(
    lines: list[str],
    site: dict,
    skill: str,
) -> tuple[int, int, list[str]] | None:
    """Build the replacement for a single mechanical site. Returns
    (start_line, end_line, replacement_lines) for in-place substitution.

    Returns None if the rewrite cannot be cleanly constructed.
    """
    line_idx = site["line_idx"]
    target = site["target"]

    scope = _find_python_dash_c_scope(lines, line_idx)
    if scope is None:
        return None
    py_start, py_end, quote = scope

    # Extract py source (lines between py_start+1 and py_end-1, exclusive of
    # the wrapping bash command).
    if py_end - py_start < 2:
        return None  # not a multi-line heredoc

    # Pull the body lines (between the open-quote line and the close-quote line).
    body_lines = lines[py_start + 1 : py_end]
    py_source = "\n".join(body_lines)

    # Make sure the heredoc contains exactly ONE dump call to a manifest path.
    dump_count = sum(
        1 for m in JSON_DUMP_PREFIX_RE.finditer(py_source)
    )
    if dump_count != 1:
        return None

    # Refuse if the heredoc contains any other `print()` call. The codemod
    # captures stdout into $PAYLOAD; an extra diagnostic print would
    # corrupt the JSON payload. Common diagnostic shape: print('Wrote ...').
    # PR-C handles these by hand (route diagnostics to stderr, then migrate).
    if re.search(r"""(?m)^\s*print\(""", py_source):
        return None

    # Try S1 (with open as f: dump) first; fall through to S2 (single-call).
    result = _rewrite_s1_pattern(py_source, target)
    if result is None:
        result = _rewrite_dump_to_dumps(py_source, target)
    if result is None:
        return None
    new_py_source, _expr = result
    new_body_lines = new_py_source.split("\n")

    # Strip stamped keys from payload literal.
    new_body_lines = _strip_stamped_keys(new_body_lines)

    # Detect the leading whitespace on the original heredoc-open line so we
    # can match indentation in the replacement.
    open_line = lines[py_start]
    indent = re.match(r"\s*", open_line).group(0)

    # Build the canonical-writer block. Use the same outer indent.
    # Format:
    #   PAYLOAD=$(python3 -c "
    #   <body>
    #   ")
    #   bash .claude/scripts/lib/write-gate-artifact.sh \
    #     --path <target> \
    #     --payload "$PAYLOAD" \
    #     --skill <skill>
    new_block: list[str] = []
    new_block.append(f"{indent}PAYLOAD=$(python3 -c \"")
    for body_line in new_body_lines:
        new_block.append(body_line)
    new_block.append(f"{indent}\")")
    new_block.append(f"{indent}bash .claude/scripts/lib/write-gate-artifact.sh \\")
    new_block.append(f"{indent}  --path {target} \\")
    new_block.append(f'{indent}  --payload "$PAYLOAD" \\')
    new_block.append(f"{indent}  --skill {skill}")

    return py_start, py_end, new_block


def codemod_text(text: str, file_rel_path: str, manifest_paths: set[str]) -> tuple[str, list[dict], list[dict]]:
    """Rewrite mechanical sites in text. Return (new_text, applied, skipped)
    where applied/skipped are lists of site dicts."""
    skill = _skill_from_file(file_rel_path)
    sites = _candidate_writes(text, manifest_paths)
    if not sites:
        return text, [], []
    if skill is None:
        # Non-skill files (agents, patterns, procedures, scripts) — defer to
        # PR-C manual queue. The codemod targets `.claude/skills/*/` only in
        # PR-B per the plan.
        return text, [], [
            {**s, "file": file_rel_path, "reason": "non-skill-corpus-deferred-to-PR-C"}
            for s in sites
        ]
    lines = text.splitlines(keepends=False)

    # Reverse order so line indices remain valid as we splice.
    edits: list[tuple[int, int, list[str]]] = []
    applied: list[dict] = []
    skipped: list[dict] = []

    for site in sorted(sites, key=lambda s: s["line_idx"], reverse=True):
        # Idempotency: if a canonical-writer call for this target already
        # exists in the file, skip.
        if _is_already_migrated(lines, site["target"]):
            skipped.append({**site, "file": file_rel_path, "reason": "already-migrated"})
            continue
        edit = _rewrite_one_site(lines, site, skill)
        if edit is None:
            skipped.append({**site, "file": file_rel_path, "reason": "extraction-failed"})
            continue
        edits.append(edit)
        applied.append({**site, "file": file_rel_path})

    if not edits:
        return text, applied, skipped

    # Apply edits in reverse order (already sorted).
    for start, end, replacement in edits:
        lines[start : end + 1] = replacement

    return "\n".join(lines) + ("\n" if text.endswith("\n") else ""), applied, skipped


# ----- main ---------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="print diff, no writes")
    parser.add_argument("--check", action="store_true", help="exit 1 if any rewrites would be applied")
    parser.add_argument("--scope", default="skills",
                        choices=("skills", "all"),
                        help="skills = .claude/skills/*/state-*.md only (PR-B); all = entire corpus (future)")
    args = parser.parse_args(argv)

    if not MANIFEST_PATH.is_file():
        print(f"ERROR: manifest not found: {MANIFEST_PATH}", file=sys.stderr)
        return 2
    manifest = json.loads(MANIFEST_PATH.read_text())
    manifest_paths = {a["path"] for a in manifest.get("artifacts", [])}

    files = _enumerate_files()
    if args.scope == "skills":
        files = [p for p in files if p.relative_to(REPO_ROOT).as_posix().startswith(".claude/skills/")]

    total_applied: list[dict] = []
    total_skipped: list[dict] = []
    files_changed = 0

    for path in files:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(REPO_ROOT).as_posix()
        new_text, applied, skipped = codemod_text(text, rel, manifest_paths)
        total_applied.extend(applied)
        total_skipped.extend(skipped)
        if new_text != text:
            files_changed += 1
            if args.dry_run:
                diff = difflib.unified_diff(
                    text.splitlines(keepends=True),
                    new_text.splitlines(keepends=True),
                    fromfile=f"a/{rel}",
                    tofile=f"b/{rel}",
                )
                sys.stdout.writelines(diff)
            elif not args.check:
                path.write_text(new_text, encoding="utf-8")

    print(f"Files changed: {files_changed}", file=sys.stderr)
    print(f"Sites rewritten: {len(total_applied)}", file=sys.stderr)
    print(f"Sites skipped (refused or already migrated): {len(total_skipped)}", file=sys.stderr)

    # Emit manual queue.
    MANUAL_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MANUAL_QUEUE_PATH, "w") as f:
        json.dump({
            "applied": total_applied,
            "skipped": total_skipped,
        }, f, indent=2)
        f.write("\n")
    print(f"Manual queue: {MANUAL_QUEUE_PATH.relative_to(REPO_ROOT).as_posix()}", file=sys.stderr)

    if args.check and (files_changed > 0):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
