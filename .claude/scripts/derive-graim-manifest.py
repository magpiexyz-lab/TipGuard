#!/usr/bin/env python3
"""derive-graim-manifest.py — Mechanically derive GRAIM v2 gate-readable artifact manifests.

GRAIM v2 (Gate-Readable Artifact Identity Manifest, version 2) classifies every
`.runs/*.json` artifact the template references into three buckets:

1. **Canonical** — artifacts read by `state-registry.json` VERIFY blocks
   (`json.load(open('.runs/...json'))`). These MUST carry
   `{skill, run_id, written_at}` provenance and are the GRAIM-managed set.

2. **Pending review** — every other `.runs/*.json` path discovered in the
   tree, auto-classified into one of three sub-buckets:
   - `hook_read`   — read by `.claude/hooks/**/*.sh` → promote to canonical (Slice 3 migration)
   - `inline_md_read` — read inside skill/pattern .md files → human review needed
   - `no_reader`   — written but never read by any consumer → exempt (telemetry-only)

## `.jsonl` telemetry carve-out (#1393 r3 Item 2 — load-bearing pin)

**`.jsonl` telemetry is a known non-canonical class.** Append-only event logs
with extension `.jsonl` (hook-friction.jsonl, fix-ledger.jsonl, bootstrap-execution-trace.jsonl,
consistency-soak-telemetry.jsonl, etc.) are intentionally NOT registered as
gate-readable artifacts. The regex carve-out at `RE_RUNS_JSON` below (negative
lookahead `(?![a-zA-Z0-9])` prevents `.jsonl` from matching) is the single
enforcement point and is **load-bearing** — do NOT include `.jsonl` in the
regex character class.

New telemetry: pick the `.jsonl` extension, document the per-line schema in the
writer's docstring, and do NOT register in `gate-readable-artifacts-canonical.json`.

The recurrence guard `derive_graim_manifest_carveout_pin` (template-coherence-rules.json)
asserts this docstring declaration and the regex stay paired. If you remove the
carve-out from the regex, the rule will fail at lifecycle-finalize.

Outputs (Slice 0 deliverables):
- .claude/patterns/gate-readable-artifacts-canonical.json
- .claude/patterns/gate-readable-artifacts-pending-review.json

Stdlib-only, idempotent (modulo `generated_at` timestamp).
Run: `python3 .claude/scripts/derive-graim-manifest.py`
"""
from __future__ import annotations

import ast
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# Repo layout
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent  # .claude/scripts/X.py -> repo root
CLAUDE_DIR = REPO_ROOT / ".claude"
STATE_REGISTRY = CLAUDE_DIR / "patterns" / "state-registry.json"
OUTPUT_CANONICAL = CLAUDE_DIR / "patterns" / "gate-readable-artifacts-canonical.json"
OUTPUT_PENDING = CLAUDE_DIR / "patterns" / "gate-readable-artifacts-pending-review.json"

GENERATOR_REL = ".claude/scripts/derive-graim-manifest.py"

# ---------------------------------------------------------------------------
# Regexes
# ---------------------------------------------------------------------------
# Match `.runs/<some/path>.json` literals.
# Negative lookahead `(?![a-zA-Z0-9])` prevents the regex from chopping `.jsonl`
# (or `.json5`, `.jsonc`) tails into a phantom `.json` match.
RE_RUNS_JSON = re.compile(r"\.runs/[a-zA-Z0-9_./-]+\.json(?![a-zA-Z0-9])")

# Match a `json.load(open(...))` call (used to flag VERIFY blocks as "gate-reading").
RE_JSON_LOAD_OPEN = re.compile(r"json\.load\(\s*open\(")

# Variable-style references: `$RUNS_DIR/foo.json` or `${RUNS_DIR}/foo.json`.
RE_VAR_RUNS_DIR = re.compile(r"\$\{?RUNS_DIR\}?/([a-zA-Z0-9_./-]+\.json)(?![a-zA-Z0-9])")

# `glob.glob(...).runs...` — wildcard discovery of artifact families.
RE_GLOB_RUNS = re.compile(r"glob\.glob\([^)]*\.runs[^)]*\)")

# READ markers inside hooks/scripts/md: any of these tokens indicates a READ.
# Used as a hook-level signal — if a hook file contains the path AND any READ
# marker, the path is treated as read by that hook. This handles the common
# pattern of `SIGNAL="$PROJECT_DIR/.runs/pipeline-phase.json"` followed by
# `json.load(open('$SIGNAL'))` later in the file.
RE_READ_MARKER = re.compile(
    r"json\.load\(\s*open\(|\bcat\s+[^|;<>&]*\.runs|\bjq\b[^|;<>&\n]*\.runs"
    r"|\bread_json_field\b|python3\s+-c\s"
)

# Strict per-path READ patterns (used as a sharper, second-look heuristic).
RE_READ_CAT = re.compile(r"\bcat\s+(?:[-\w]+\s+)*[^|;<>&\s]*\.runs/[a-zA-Z0-9_./-]+\.json(?![a-zA-Z0-9])")
RE_READ_JQ = re.compile(r"\bjq\b[^|;<>&\n]*\.runs/[a-zA-Z0-9_./-]+\.json(?![a-zA-Z0-9])")
RE_READ_LOAD = re.compile(r"json\.load\(\s*open\([^)]*\.runs/[a-zA-Z0-9_./-]+\.json(?![a-zA-Z0-9])[^)]*\)")
RE_READ_FIELD = re.compile(r"read_json_field[^\n]*\.runs/[a-zA-Z0-9_./-]+\.json(?![a-zA-Z0-9])")

# WRITE patterns: `> <path>`, `>> <path>`, `json.dump(... , open(<path>, 'w'))`.
# A path is "no_reader" only if writers exist (we found it somewhere) but no readers exist.
# Writers = anywhere the path appears. We don't strictly distinguish W vs R; the
# absence of a READ-pattern match across all consumer surfaces is what matters.

# Discovery globs (relative to CLAUDE_DIR for clarity)
SHELL_GLOBS = ["scripts/**/*.sh", "hooks/**/*.sh"]
PYTHON_GLOBS = ["scripts/**/*.py", "scripts/lib/**/*.py"]
MD_GLOBS = [
    "agents/**/*.md",
    "patterns/**/*.md",
    "skills/**/*.md",
    "procedures/**/*.md",
]
HOOK_GLOBS = ["hooks/**/*.sh"]

# Files/dirs whose `.runs/...json` references are test fixtures, placeholders,
# or examples — never real production artifacts. Filtered from discovery.
EXCLUDE_PATH_PARTS = (
    "/scripts/tests/",       # unit/integration tests + their fixtures
    "/scripts/bakeoff/",     # local experiment harness
    "/templates/",           # documentation templates with placeholder paths
)

# Placeholder/test artifact names that show up in fixtures and docs but are not
# real artifacts. Filtered out of the candidate set.
PLACEHOLDER_NAMES = {
    ".runs/foo.json",
    ".runs/X.json",
    ".runs/...json",
    ".runs/something.json",
    ".runs/agent-traces/foo.json",
    ".runs/agent-traces/fake.json",
    ".runs/agent-traces/forge.json",
    ".runs/agent-traces/forged.json",
    ".runs/agent-traces/test-agent.json",
    ".runs/agent-traces/test.json",
    ".runs/does-not-exist.json",
    ".runs/lead-only-test.json",
    ".runs/not-cleaned.json",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _iter_files(globs: Iterable[str], base: Path) -> list[Path]:
    out: list[Path] = []
    for g in globs:
        out.extend(base.glob(g))
    files = {p for p in out if p.is_file()}
    # Strip out test fixtures, bakeoff harness, and templates (they reference
    # placeholder paths that are not real production artifacts).
    files = {
        p for p in files
        if not any(part in p.as_posix() for part in EXCLUDE_PATH_PARTS)
    }
    return sorted(files)


def _is_placeholder_path(runs_path: str) -> bool:
    """Filter out documentation placeholders and obvious test stubs."""
    if runs_path in PLACEHOLDER_NAMES:
        return True
    # Triple-dot ellipsis from prose/docs (e.g., `.runs/.../design-critic.json`).
    if "/..." in runs_path or runs_path.startswith(".runs/...") or runs_path.endswith("/...json"):
        return True
    return False


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _rel(path: Path) -> str:
    """Repo-relative POSIX path."""
    return path.relative_to(REPO_ROOT).as_posix()


def _utc_iso8601() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_value(node: ast.AST) -> str | None:
    """Resolve a simple AST node (Constant, JoinedStr without f-string vars) to a string, or None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
            else:
                return None
        return "".join(parts)
    return None


# ---------------------------------------------------------------------------
# Pass 1 — Canonical set from state-registry VERIFY blocks
# ---------------------------------------------------------------------------
def _walk_verify_strings(node) -> Iterable[tuple[str, str]]:
    """Walk state-registry, yielding (location_id, verify_string) pairs.

    location_id = "<skill>.<state>" (e.g. "verify.0", "bootstrap.11").
    """
    if not isinstance(node, dict):
        return
    for skill, states in node.items():
        if skill == "trace_schemas":
            continue
        if not isinstance(states, dict):
            continue
        for state_id, val in states.items():
            verify: str | None = None
            if isinstance(val, str):
                verify = val
            elif isinstance(val, dict):
                v = val.get("verify")
                if isinstance(v, str):
                    verify = v
            if verify:
                yield (f"{skill}.{state_id}", verify)


def derive_canonical(registry_path: Path) -> dict[str, dict]:
    """Return {path: {consumers: [...]}} for paths inside any VERIFY block that uses json.load(open(...)).

    Per Slice 0 spec: a VERIFY string is "gate-reading" iff it contains BOTH a
    `.runs/X.json` literal AND a `json.load(open(` call. When both conditions hold,
    EVERY `.runs/X.json` literal in that VERIFY is treated as a canonical
    gate-readable artifact (because VERIFY blocks routinely thread paths through
    intermediate variables like `('design-critic', '.runs/.../design-critic.json')`
    before passing them to `json.load(open(...))`).
    """
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for loc, verify in _walk_verify_strings(registry):
        if not RE_JSON_LOAD_OPEN.search(verify):
            continue
        if not RE_RUNS_JSON.search(verify):
            continue
        # Both conditions hold → every `.runs/X.json` literal in this VERIFY is canonical.
        for p in RE_RUNS_JSON.findall(verify):
            entry = out.setdefault(p, {"consumers": set()})
            entry["consumers"].add(f"state-registry:{loc}")
    return out


# ---------------------------------------------------------------------------
# Pass 2 — Path discovery across the tree (scripts, hooks, md, AST)
# ---------------------------------------------------------------------------
def _grep_paths_in_files(paths: list[Path]) -> dict[str, set[str]]:
    """Return {.runs/X.json: {file_rel, ...}} from literal regex matches."""
    found: dict[str, set[str]] = {}
    for p in paths:
        text = _read_text(p)
        if not text:
            continue
        for hit in RE_RUNS_JSON.findall(text):
            if _is_placeholder_path(hit):
                continue
            found.setdefault(hit, set()).add(_rel(p))
        # Variable-style: $RUNS_DIR/foo.json -> .runs/foo.json
        for tail in RE_VAR_RUNS_DIR.findall(text):
            if tail.endswith(".json"):
                key = f".runs/{tail}"
                if _is_placeholder_path(key):
                    continue
                found.setdefault(key, set()).add(_rel(p))
    return found


def _ast_discover_python(paths: list[Path]) -> dict[str, set[str]]:
    """AST walk: find `os.path.join('.runs', ...)` constructions with static literals."""
    found: dict[str, set[str]] = {}
    for p in paths:
        text = _read_text(p)
        if not text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # Match os.path.join(...) — by attribute name only, regardless of import alias.
            func = node.func
            is_join = False
            if isinstance(func, ast.Attribute) and func.attr == "join":
                value = func.value
                if (
                    isinstance(value, ast.Attribute)
                    and value.attr == "path"
                    and isinstance(value.value, ast.Name)
                    and value.value.id in {"os", "posixpath"}
                ):
                    is_join = True
            if not is_join:
                continue
            args = node.args
            if not args:
                continue
            # Resolve each positional arg to a string literal if possible.
            resolved: list[str | None] = [_resolve_value(a) for a in args]
            if all(r is not None for r in resolved):
                joined = os.path.join(*resolved)  # type: ignore[arg-type]
                if joined.endswith(".json") and ".runs/" in joined.replace(os.sep, "/"):
                    norm = joined.replace(os.sep, "/")
                    # Strip leading dirs up to and including `.runs/`
                    if ".runs/" in norm:
                        norm = ".runs/" + norm.split(".runs/", 1)[1]
                        if _is_placeholder_path(norm):
                            continue
                        found.setdefault(norm, set()).add(_rel(p))
            else:
                # Mixed literal + variable: at minimum, if the FIRST literal is `.runs`
                # AND the rest are static, we already caught it above. Anything else
                # is non-static — skip silently (Pass A grep often picks it up anyway).
                continue
    return found


def _glob_discover(paths: list[Path]) -> set[str]:
    """Pass D: capture glob.glob patterns over `.runs/...` (e.g. agent-traces/*.json)."""
    out: set[str] = set()
    for p in paths:
        text = _read_text(p)
        if not text:
            continue
        out.update(RE_GLOB_RUNS.findall(text))
    return out


# ---------------------------------------------------------------------------
# Pass 3 — Reader/writer classification
# ---------------------------------------------------------------------------
def _file_reads_path(text: str, runs_path: str, *, indirect: bool) -> bool:
    """Return True if `text` shows any READ pattern targeting `runs_path`.

    Two-tier check controlled by `indirect`:

    1. **Sharp** (always on): any of the per-path READ regexes
       (`cat`, `jq`, `json.load(open`, `read_json_field`) directly contains
       the literal `runs_path`. This is the strict, low-false-positive signal.

    2. **Indirect** (`indirect=True` only): the file references `runs_path`
       (literally, or via `$RUNS_DIR/<basename>`) AND the file contains any
       READ marker. This catches the shell pattern of `SIGNAL=".runs/foo.json"`
       followed by `json.load(open('$SIGNAL'))` later in the file.

    `indirect` should be True for shell hooks (where variable indirection is
    idiomatic) and False for `.md` files (where every state file embeds
    `python3 -c` examples and would otherwise false-positive on every path
    mentioned in the same file).
    """
    # Tier 1: sharp per-path reads (always on).
    for rx in (RE_READ_CAT, RE_READ_JQ, RE_READ_LOAD, RE_READ_FIELD):
        for hit in rx.findall(text):
            if runs_path in hit:
                return True
    if not indirect:
        return False
    # Tier 2: indirect — file mentions the path AND contains a read marker.
    if runs_path in text and RE_READ_MARKER.search(text):
        return True
    basename = runs_path[len(".runs/"):]
    if RE_VAR_RUNS_DIR.search(text) and basename in text and RE_READ_MARKER.search(text):
        return True
    return False


def classify_pending(
    candidates: dict[str, set[str]],
    canonical: set[str],
    hook_files: list[Path],
    md_files: list[Path],
) -> list[dict]:
    """Auto-classify every pending-review path into one of 3 buckets."""
    hook_texts = {_rel(p): _read_text(p) for p in hook_files}
    md_texts = {_rel(p): _read_text(p) for p in md_files}

    results: list[dict] = []
    for path in sorted(candidates):
        if path in canonical:
            continue
        writers = sorted(candidates[path])

        readers_in_hooks = sorted(
            f for f, t in hook_texts.items() if _file_reads_path(t, path, indirect=True)
        )
        # md files use sharp-only matching (indirect=False) — narrative prose +
        # adjacent `python3 -c` code blocks would otherwise false-positive on
        # every path mentioned in the same state file.
        readers_in_md = sorted(
            f for f, t in md_texts.items() if _file_reads_path(t, path, indirect=False)
        )

        if readers_in_hooks:
            classification = "hook_read"
            recommendation = "promote to canonical (Slice 3 migration)"
        elif readers_in_md:
            classification = "inline_md_read"
            recommendation = "human review needed"
        else:
            classification = "no_reader"
            recommendation = "exempt (telemetry-only)"

        entry: dict = {
            "path": path,
            "classification": classification,
            "writers": writers,
            "recommendation": recommendation,
        }
        if readers_in_hooks:
            entry["readers_in_hooks"] = readers_in_hooks
        if readers_in_md:
            entry["readers_in_md"] = readers_in_md
        results.append(entry)
    return results


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------
def _scope_for(path: str) -> str:
    """Default scope label. State-99 paths read across skills => transient-cross-skill.
    Heuristic: gate-verdicts and observation-enforcement live across skills; everything
    else read by VERIFY is also transient-cross-skill (verify runs at end of every skill).
    """
    return "transient-cross-skill"


def _rationale_for(path: str, consumers: list[str]) -> str:
    if path == ".runs/observation-enforcement.json":
        return "Read by state-99 VERIFY across all skills; carries gate verdict (#1198 smoking-gun)."
    if path.startswith(".runs/gate-verdicts/"):
        return "Gate verdict file consumed by VERIFY block; persisted across skills."
    if path.startswith(".runs/agent-traces/"):
        return "Agent trace consumed by VERIFY block; provenance must include {skill,run_id,written_at}."
    skills = sorted({c.split(":", 1)[1].split(".", 1)[0] for c in consumers})
    return f"Read by VERIFY blocks in skills: {', '.join(skills)}."


def write_canonical(canonical: dict[str, dict], all_writers: dict[str, set[str]]) -> int:
    artifacts = []
    for path in sorted(canonical):
        consumers = sorted(canonical[path]["consumers"])
        writers = sorted(all_writers.get(path, set()))
        artifacts.append(
            {
                "path": path,
                "consumers": consumers,
                "writers": writers,
                "scope": _scope_for(path),
                "rationale": _rationale_for(path, consumers),
            }
        )
    payload = {
        "$comment": (
            "GRAIM v2 — gate-readable artifacts that MUST carry "
            "{skill, run_id, written_at}. Auto-derived from state-registry.json "
            "VERIFY blocks. DO NOT EDIT MANUALLY — re-run derive-graim-manifest.py."
        ),
        "$jsonl_carveout": (
            "#1393 r3 Item 2 — `.jsonl` telemetry is a known non-canonical class. "
            "The regex carve-out at derive-graim-manifest.py:RE_RUNS_JSON "
            "(negative lookahead `(?![a-zA-Z0-9])`) is load-bearing — see that "
            "file's module docstring. New telemetry: pick `.jsonl` extension, "
            "document per-line schema in writer docstring, do NOT register here. "
            "Enforced by template-coherence-rules.json rule `derive-graim-manifest-carveout-pin`."
        ),
        "version": "1.0",
        "generated_at": _utc_iso8601(),
        "generator": GENERATOR_REL,
        "artifacts": artifacts,
    }
    OUTPUT_CANONICAL.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return len(artifacts)


def write_pending(pending: list[dict]) -> dict[str, int]:
    payload = {
        "$comment": (
            "GRAIM v2 — auto-classified candidates discovered outside state-registry "
            "VERIFY blocks. Each entry tagged with classification. hook_read entries "
            "should be promoted to canonical via Slice 3 migration. no_reader entries "
            "are exempt (telemetry-only). inline_md_read entries need human "
            "inclusion/exclusion decision."
        ),
        "version": "1.0",
        "generated_at": _utc_iso8601(),
        "generator": GENERATOR_REL,
        "artifacts": pending,
    }
    OUTPUT_PENDING.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    counts = {"hook_read": 0, "no_reader": 0, "inline_md_read": 0}
    for entry in pending:
        counts[entry["classification"]] += 1
    return counts


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    if not STATE_REGISTRY.is_file():
        raise SystemExit(f"state-registry.json not found at {STATE_REGISTRY}")

    # Pass 1: canonical set from VERIFY blocks
    canonical_raw = derive_canonical(STATE_REGISTRY)
    # Convert sets to lists for stability later; keep dict for lookup.
    canonical = {p: {"consumers": sorted(d["consumers"])} for p, d in canonical_raw.items()}

    # Pass 2-A: literal grep across shells / hooks / Python / MD
    shell_files = _iter_files(SHELL_GLOBS, CLAUDE_DIR)
    py_files = _iter_files(PYTHON_GLOBS, CLAUDE_DIR)
    md_files = _iter_files(MD_GLOBS, CLAUDE_DIR)
    hook_files = _iter_files(HOOK_GLOBS, CLAUDE_DIR)

    candidates: dict[str, set[str]] = {}
    for p_path, files in _grep_paths_in_files(shell_files + py_files + md_files).items():
        candidates.setdefault(p_path, set()).update(files)

    # Pass 2-B: AST discovery (Python os.path.join)
    for p_path, files in _ast_discover_python(py_files).items():
        candidates.setdefault(p_path, set()).update(files)

    # Pass 2-D: glob.glob patterns -> register the wildcard family as a synthetic path.
    # We capture glob *targets* (e.g., `.runs/agent-traces/*.json`) by scanning for the
    # `.runs/...` literal inside each glob.glob match.
    for hit in _glob_discover(py_files):
        for p_path in RE_RUNS_JSON.findall(hit):
            # Won't match a literal *.json (no `*` in RE_RUNS_JSON) — fall back to
            # a sanitized synthetic key when the pattern uses a wildcard.
            candidates.setdefault(p_path, set())
        # Also try to extract `.runs/<dir>/*.json` style patterns explicitly.
        m = re.search(r"\.runs/([a-zA-Z0-9_./-]+/)?\*+\.json", hit)
        if m:
            wildcard_key = ".runs/" + (m.group(1) or "") + "*.json"
            candidates.setdefault(wildcard_key, set())

    # Pass 3: classify pending
    canonical_set = set(canonical.keys())
    pending = classify_pending(candidates, canonical_set, hook_files, md_files)

    # Build full writer index (any file mentioning the path) for canonical entries too.
    all_writers: dict[str, set[str]] = {}
    for p_path, files in _grep_paths_in_files(shell_files + py_files).items():
        all_writers.setdefault(p_path, set()).update(files)
    for p_path, files in _ast_discover_python(py_files).items():
        all_writers.setdefault(p_path, set()).update(files)

    canonical_count = write_canonical(canonical, all_writers)
    counts = write_pending(pending)

    # Self-test summary
    print(f"Canonical: {canonical_count} artifacts")
    print("Pending-review:")
    print(f"  hook_read: {counts['hook_read']} (auto-promote candidates)")
    print(f"  no_reader: {counts['no_reader']} (exempt)")
    print(f"  inline_md_read: {counts['inline_md_read']} (human review needed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
