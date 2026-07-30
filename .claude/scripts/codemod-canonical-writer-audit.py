#!/usr/bin/env python3
"""codemod-canonical-writer-audit.py — Step-0 of Issue #1299 migration.

Walks template files and reports every direct write to a gate-readable
.runs/*.json artifact (paths declared in
.claude/patterns/gate-readable-artifacts-canonical.json). Output is the
precise migration manifest that PR-B's codemod consumes as a checklist.

This is read-only: emits .runs/canonical-writer-migration-manifest.json
plus a stdout summary. No state-file edits.

Usage:
    python3 .claude/scripts/codemod-canonical-writer-audit.py
    python3 .claude/scripts/codemod-canonical-writer-audit.py --json   # quiet, JSON-only
    python3 .claude/scripts/codemod-canonical-writer-audit.py --check  # exit 1 if violations
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / ".claude/patterns/gate-readable-artifacts-canonical.json"

# Corpora to walk.
CORPUS_GLOBS = [
    ".claude/skills/*/state-*.md",
    ".claude/agents/*.md",
    ".claude/patterns/*.md",
    ".claude/procedures/*.md",
    ".claude/scripts/*.sh",
    ".claude/scripts/*.py",
    ".claude/scripts/lib/*.sh",
    ".claude/scripts/lib/*.py",
    ".claude/hooks/*.sh",
]

# Files to exclude — they ARE the canonical infrastructure.
EXCLUDE_FILES = {
    ".claude/scripts/codemod-canonical-writer-audit.py",
    ".claude/scripts/codemod-canonical-writer.py",
    ".claude/scripts/lib/write-gate-artifact.sh",
    ".claude/scripts/append-hook-friction.py",
    ".claude/scripts/derive-graim-manifest.py",
    ".claude/hooks/gate-artifact-write-gate.sh",
    ".claude/hooks/gate-artifact-bash-write-guard.sh",
    ".claude/patterns/gate-readable-artifacts-canonical.json",
    ".claude/patterns/template-coherence-rules.json",
    ".claude/patterns/agent-output-contract.md",
    ".claude/scripts/verify-linter.sh",
}
EXCLUDE_PREFIXES = (
    ".claude/scripts/tests/",
    ".claude/scripts/lib/linter/",
)

# Bold-markdown section markers used by every state file.
SECTION_MARKERS = (
    "**PRECONDITIONS:**",
    "**ACTIONS:**",
    "**POSTCONDITIONS:**",
    "**VERIFY:**",
    "**STATE TRACKING:**",
    "**NEXT:",
)

# Write-syntax tokens (R2-C1: write-only, no read syntax).
#
# PR-FIX-S2: the previous S2 regex `json\.dump\([^()]*?open\(...)` could not
# span function calls in the dict payload (e.g. `datetime.now()`), missing
# multi-line dict payloads. The unified S2 pattern below matches ANY
# `open(target, 'w'|'a')` regardless of wrapping context — semantically that
# IS a write to the target. The negative lookbehind `(?<!with\s)` excludes
# the S1 form so each site reports under exactly one shape.
WRITE_PATTERNS = [
    # S1 multi-line: with open('.runs/X.json', 'w')   (also matches 'a' mode)
    ("S1", re.compile(r"""with\s+open\(\s*['"](?P<path>\.runs/[^'"\s]+)['"]\s*,\s*['"](?P<mode>[wa])""")),
    # S2 generic: any open(target, 'w'|'a') NOT preceded by `with ` —
    # covers json.dump(payload, open(target,'w'), ...), payload-with-function-
    # calls, payload-spanning-newlines, etc.
    ("S2", re.compile(r"""(?<!with\s)open\(\s*['"](?P<path>\.runs/[^'"\s]+)['"]\s*,\s*['"](?P<mode>[wa])""")),
    # S3 heredoc: cat > .runs/X.json << EOF
    ("S3", re.compile(r"""(?:^|\s)cat\s*>\s*(?P<path>\.runs/[^\s<]+)\s*<<""")),
    # S4 echo redirect: echo '...' > .runs/X.json   (or printf)
    ("S4", re.compile(r"""(?:^|\s)(?:echo|printf)\b[^|;&]*?>\s*(?P<path>\.runs/[^\s'"|;&]+)""")),
    # Tee: tee .runs/X.json
    ("TEE", re.compile(r"""(?:^|\s)tee\s+(?:-a\s+)?(?P<path>\.runs/[^\s'"|;&]+)""")),
]

# Read-syntax suppressors — if any matches on a line BEFORE a write match,
# suppress that line. Avoids the 455 false-positive baseline (R2-C1).
READ_SYNTAX_SUPPRESSORS = [
    re.compile(r"""open\([^)]*,\s*['"]r['"]"""),
    re.compile(r"""\bjson\.load\b"""),
    re.compile(r"""\bos\.path\.exists\b"""),
    re.compile(r"""\[\s*-[fe]\s+"""),
    re.compile(r"""\bif\s+\[\s*!\s*-"""),
]

# Bash-variable interpolation signal (only $VAR / ${VAR}, not English "If").
BASH_VAR_PATTERN = re.compile(r"""\$(?:[A-Z_][A-Z0-9_]*|\{[A-Z_][A-Z0-9_]*\})""")
# Python conditional control-flow tokens. Tight set — only patterns that
# indicate the payload itself is built conditionally.
PY_CONDITIONAL_PATTERN = re.compile(
    r"""(?:^|\s)(?:if\s+[^=]*?:|elif\s+|else:\s*$|os\.path\.exists\(|\bif\s+os\.path\.|\.get\([^)]+\)\s*if\s)"""
)
# Markers that bound a python-heredoc scope around a write.
PY_BLOCK_START = re.compile(
    r"""(?:python3?\s+-c\s*['"]|python3?\s+-\s*<<\s*['"]?PYEOF|python3?\s+<<\s*['"]?PYEOF|python3?\s*<<\s*['"]?[A-Z_]+EOF)"""
)
PY_BLOCK_END = re.compile(r"""(?:^|\s)(?:PYEOF|[A-Z_]+EOF)\s*$|['"]\s*\)""")
# Markdown / bash boundaries that DEFINITELY end a python scope.
HARD_BOUNDARIES = (
    re.compile(r"^\s*```\s*$"),
    re.compile(r"^\s*\*\*[A-Z][A-Z\s]+:\*\*"),
)


def _section_for_line(lines: list[str], line_idx: int) -> str:
    """Return the bold-markdown section containing the given 0-based line."""
    section = "<header>"
    for i in range(line_idx, -1, -1):
        line = lines[i].lstrip()
        for marker in SECTION_MARKERS:
            if line.startswith(marker):
                return marker.strip("*").strip(":").strip()
    return section


def _find_payload_scope(lines: list[str], line_idx: int) -> tuple[int, int]:
    """Locate the bounded scope to inspect for payload complexity.

    For python heredoc cases (python3 -c "..." or <<'PYEOF'...PYEOF), this
    returns the heredoc body's bounds. For bash-only writes (S3/S4/TEE), it
    returns a tight 2-line window. Hard boundaries (markdown headers, bash
    fences) always end the scope to avoid leaking prose into the inspection.
    """
    # Walk backward to find a python block start, stopping at hard boundaries.
    start = line_idx
    for i in range(line_idx, max(-1, line_idx - 30), -1):
        line = lines[i]
        if any(b.match(line) for b in HARD_BOUNDARIES) and i != line_idx:
            start = i + 1
            break
        if PY_BLOCK_START.search(line):
            start = i
            break
    else:
        start = max(0, line_idx - 2)

    # Walk forward to find a python block end or hard boundary.
    end = line_idx
    for i in range(line_idx, min(len(lines), line_idx + 30)):
        line = lines[i]
        if any(b.match(line) for b in HARD_BOUNDARIES) and i != line_idx:
            end = i - 1
            break
        if i > line_idx and PY_BLOCK_END.search(line):
            end = i
            break
    else:
        end = min(len(lines) - 1, line_idx + 2)

    return start, end


def _classify_payload_complexity(
    lines: list[str],
    line_idx: int,
    section: str,
) -> str:
    """Classify payload as mechanical / bash_interpolated / conditional /
    mixed / verify_misplacement.

    Inspects ONLY the bounded payload scope (python heredoc body or tight
    window for bash-only writes), not arbitrary surrounding prose.
    """
    if section == "VERIFY":
        return "verify_misplacement"

    start, end = _find_payload_scope(lines, line_idx)
    # Strip Python-style end-of-line comments before classification — the
    # comment text often contains prose like "# set to X if Y" that
    # spuriously triggers the conditional regex.
    cleaned = []
    for src_line in lines[start : end + 1]:
        stripped = src_line.lstrip()
        if stripped.startswith("#"):
            continue
        # Strip inline `# ...` comments. Conservative: only strip when the
        # `#` is preceded by whitespace (to avoid mangling `# inside a
        # string` cases — close enough for the heuristic).
        cleaned.append(re.sub(r"\s+#.*$", "", src_line))
    snippet = "\n".join(cleaned)

    has_var = bool(BASH_VAR_PATTERN.search(snippet))
    has_conditional = bool(PY_CONDITIONAL_PATTERN.search(snippet))

    if has_var and has_conditional:
        return "mixed"
    if has_var:
        return "bash_interpolated"
    if has_conditional:
        return "conditional"
    return "mechanical"


def _line_is_suppressed(line: str) -> bool:
    """True if the line contains read syntax that should suppress write-token
    matches on the same line."""
    return any(p.search(line) for p in READ_SYNTAX_SUPPRESSORS)


def _enumerate_files() -> list[Path]:
    """Return every file in the configured corpora, excluding the
    infrastructure allowlist."""
    paths: set[Path] = set()
    for pattern in CORPUS_GLOBS:
        for p in REPO_ROOT.glob(pattern):
            rel = p.relative_to(REPO_ROOT).as_posix()
            if rel in EXCLUDE_FILES:
                continue
            if any(rel.startswith(prefix) for prefix in EXCLUDE_PREFIXES):
                continue
            if p.is_file():
                paths.add(p)
    return sorted(paths)


def _scan_file(path: Path, manifest_paths: set[str]) -> list[dict]:
    """Scan a single file for write-token matches."""
    findings = []
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return findings
    lines = text.splitlines()

    for line_idx, line in enumerate(lines):
        if _line_is_suppressed(line):
            continue
        for shape, pattern in WRITE_PATTERNS:
            for match in pattern.finditer(line):
                target = match.group("path")
                mode = match.groupdict().get("mode", "w")
                section = _section_for_line(lines, line_idx)
                in_scope = target in manifest_paths and mode == "w"
                # Append-mode 'a' is out-of-scope per plan (S6 — separate
                # canonical appender is future work).
                complexity = _classify_payload_complexity(lines, line_idx, section)
                # If write isn't in scope (out-of-manifest or append), skip
                # complexity refinement.
                findings.append({
                    "file": path.relative_to(REPO_ROOT).as_posix(),
                    "line": line_idx + 1,
                    "section": section,
                    "target_path": target,
                    "writer_shape": shape,
                    "mode": mode,
                    "payload_complexity": complexity,
                    "in_scope": in_scope,
                })
    return findings


def _summary(findings: list[dict]) -> dict:
    in_scope = [f for f in findings if f["in_scope"]]
    out_of_scope = len(findings) - len(in_scope)
    by_shape: dict[str, int] = {}
    by_complexity: dict[str, int] = {}
    by_section: dict[str, int] = {}
    by_skill: dict[str, int] = {}
    for f in in_scope:
        by_shape[f["writer_shape"]] = by_shape.get(f["writer_shape"], 0) + 1
        by_complexity[f["payload_complexity"]] = by_complexity.get(f["payload_complexity"], 0) + 1
        by_section[f["section"]] = by_section.get(f["section"], 0) + 1
        # Derive skill from path: .claude/skills/<skill>/state-*.md
        m = re.match(r"\.claude/skills/([^/]+)/", f["file"])
        if m:
            by_skill[m.group(1)] = by_skill.get(m.group(1), 0) + 1
    mechanical = by_complexity.get("mechanical", 0)
    manual_review = (
        by_complexity.get("bash_interpolated", 0)
        + by_complexity.get("conditional", 0)
        + by_complexity.get("mixed", 0)
        + by_complexity.get("verify_misplacement", 0)
    )
    return {
        "total_findings": len(findings),
        "in_scope": len(in_scope),
        "out_of_scope": out_of_scope,
        "mechanical": mechanical,
        "manual_review": manual_review,
        "by_shape": by_shape,
        "by_complexity": by_complexity,
        "by_section": by_section,
        "by_skill": by_skill,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json", action="store_true",
        help="JSON-only output (quiet stdout)",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Exit 1 if any in-scope findings exist (CI gate after migration completes)",
    )
    parser.add_argument(
        "--out", default=".runs/canonical-writer-migration-manifest.json",
        help="Output manifest path (default: .runs/canonical-writer-migration-manifest.json)",
    )
    args = parser.parse_args(argv)

    if not MANIFEST_PATH.is_file():
        print(f"ERROR: manifest not found: {MANIFEST_PATH}", file=sys.stderr)
        return 2
    manifest = json.loads(MANIFEST_PATH.read_text())
    manifest_paths = {a["path"] for a in manifest.get("artifacts", [])}

    findings: list[dict] = []
    files = _enumerate_files()
    for path in files:
        findings.extend(_scan_file(path, manifest_paths))

    summary = _summary(findings)

    out = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "manifest_size": len(manifest_paths),
        "files_scanned": len(files),
        "summary": summary,
        "entries": findings,
    }

    out_path = REPO_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
        f.write("\n")

    if not args.json:
        print(f"Manifest paths: {len(manifest_paths)}")
        print(f"Files scanned: {len(files)}")
        print(f"Total findings: {summary['total_findings']}")
        print(f"In scope (manifest path + write mode): {summary['in_scope']}")
        print(f"  Mechanical (auto-rewritable):  {summary['mechanical']}")
        print(f"  Manual review needed:          {summary['manual_review']}")
        print(f"Out of scope (non-manifest or append): {summary['out_of_scope']}")
        print()
        print("By shape:")
        for shape, n in sorted(summary["by_shape"].items()):
            print(f"  {shape:5} {n}")
        print("By complexity:")
        for comp, n in sorted(summary["by_complexity"].items()):
            print(f"  {comp:25} {n}")
        print("By section:")
        for sec, n in sorted(summary["by_section"].items()):
            print(f"  {sec:20} {n}")
        print("By skill:")
        for skill, n in sorted(summary["by_skill"].items(), key=lambda x: -x[1]):
            print(f"  {skill:15} {n}")
        print()
        print(f"Manifest written to: {args.out}")

    if args.check and summary["in_scope"] > 0:
        print(
            f"FAIL: {summary['in_scope']} direct writes to gate-readable paths still in tree",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
