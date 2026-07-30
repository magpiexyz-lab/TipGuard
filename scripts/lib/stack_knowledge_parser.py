"""Parser and hash utilities for the ## Stack Knowledge section in stack files.

Consumers:
  - scripts/validate-stack-knowledge.py  (per-file, pre-commit-style)
  - scripts/ci-check-stack-knowledge.py  (cross-file uniqueness)
  - scripts/ci-check-graduation-atomicity.py (PR-diff atomicity check)
  - .claude/skills/resolve/state-9-save-patterns.md  (producer)
  - .claude/skills/resolve/state-2-triage.md          (optional reader)
  - .claude/skills/change/state-2-read-context.md     (active-prevention reader)
  - .claude/skills/bootstrap/state-12-externals-decisions.md (active-prevention reader)
  - .claude/skills/bootstrap/state-14-wire-phase.md   (active-prevention reader)
  - .claude/scripts/stack-knowledge-audit.sh          (nightly audit)
  - .claude/patterns/solve-reasoning.md                (Agent 2 optional reader)

Public API:
  - parse_stack_knowledge(content) — pure string → entries
  - parse_stack_knowledge_file(path) — path → entries (handles archive + missing)
  - is_archive_path(path) — True if path is *.archive.md (skipped everywhere)
  - compute_hash(composite) — 12-char sha1 hash for dedup
  - canonicalize(s) — string normalization for stable hashing

HC3: all readers return [] when the section is absent or the file is archive.
"""

from __future__ import annotations

import glob as _glob
import hashlib
import json
import os
import re
from typing import Any

import yaml

REQUIRED_FIELDS = {
    "id",
    "maturity",
    "composite_identity",
    "composite_identity_hash",
    "symptom_keywords",
    "fix_template",
    "prevention_mechanism",
    "confidence_score",
    "occurrence_count",
    "linked_issues",
    "first_seen",
    "last_seen",
    "graduated_to",
}

OPTIONAL_FIELDS = {"anti_pattern", "verification_snippet"}
# verification_snippet — added M3 (PR #1397 retro): a project-agnostic bash
# command that empirically reproduces the root cause described by this entry.
# /resolve STATE 3 Step 0 runs the snippet first to check if the issue still
# exists post-package-upgrade. Trinary exit contract:
#   exit 0 → bug PRESENT (proceed with reproduction)
#   exit 1 → bug ABSENT (close issue as Stale; refresh SK entry)
#   exit 2 → preconditions not met (skip; e.g., package not in this stack)
#   exit other → snippet broken (treat as "unable to verify"; do NOT auto-fix)
# See .claude/stacks/TEMPLATE.md for the canonical schema documentation.

MATURITY_VALUES = {"raw", "stable", "canonical"}

COMPOSITE_KEYS = ("root_cause_class", "divergence_pattern", "stack_scope")


def canonicalize(s: str) -> str:
    """Normalize a string for stable hashing.

    Rules (applied in order): strip, lowercase, replace underscores with spaces,
    replace hyphens with spaces, collapse any run of whitespace to a single space.
    Unicode passes through unchanged.
    """
    if not isinstance(s, str):
        raise TypeError("canonicalize expects str, got %r" % (type(s).__name__,))
    t = s.strip().lower().replace("_", " ").replace("-", " ")
    t = re.sub(r"\s+", " ", t)
    return t


def compute_hash(composite: dict) -> str:
    """Return a 12-char sha1 hex digest over canonicalized composite_identity.

    Keys are sorted so order-independent; values are canonicalized so
    surface-different inputs that mean the same thing hash the same.
    """
    if not isinstance(composite, dict):
        raise TypeError("compute_hash expects dict, got %r" % (type(composite).__name__,))
    canon: dict[str, str] = {}
    for k in COMPOSITE_KEYS:
        v = composite.get(k, "")
        canon[k] = canonicalize(str(v))
    payload = json.dumps(canon, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


_HEADING_RE = re.compile(r"^##\s+Stack Knowledge\s*$", re.MULTILINE)
_NEXT_H2_RE = re.compile(r"^##\s+", re.MULTILINE)
_FENCE_RE = re.compile(r"```yaml\s*\n(.*?)\n```", re.DOTALL)


def parse_stack_knowledge(file_content: str) -> list[dict[str, Any]]:
    """Return all YAML entries under the ## Stack Knowledge heading.

    Empty list if the heading is absent (HC3 — section is optional).
    Malformed YAML fences are skipped; the rest still parse.
    """
    if not isinstance(file_content, str):
        raise TypeError("parse_stack_knowledge expects str")

    m = _HEADING_RE.search(file_content)
    if not m:
        return []

    start = m.end()
    tail = file_content[start:]
    next_h2 = _NEXT_H2_RE.search(tail)
    section = tail[: next_h2.start()] if next_h2 else tail

    entries: list[dict[str, Any]] = []
    for fence in _FENCE_RE.finditer(section):
        raw = fence.group(1)
        try:
            doc = yaml.safe_load(raw)
        except yaml.YAMLError:
            continue
        if isinstance(doc, dict):
            entries.append(doc)
    return entries


def is_archive_path(path: str) -> bool:
    """True if path ends with .archive.md — archive files are skipped by all readers.

    Archive files are historical Stack Knowledge entries preserved as documentation
    only. They live under .claude/stacks/ so /upgrade syncs them, but no skill,
    validator, or CI check reads their contents.
    """
    return isinstance(path, str) and path.endswith(".archive.md")


def parse_stack_knowledge_file(path: str) -> list[dict[str, Any]]:
    """Read a stack file and parse its Stack Knowledge section.

    Returns [] when:
      - path is archive (is_archive_path(path) is True)
      - file does not exist or cannot be read
      - section is absent

    This is the canonical consumer-facing reader. Skills and validators call
    this with a file path and get back the entry list (or [] on any failure).
    """
    if is_archive_path(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return parse_stack_knowledge(f.read())
    except (OSError, UnicodeDecodeError):
        return []


# Single source of truth for every consumer that needs to enumerate paths
# containing ## Stack Knowledge sections. Hardcoded globs scattered across
# CI scripts, skill state files, and validators were the root cause of #1285
# (lib/ helpers built by one /solve invisible to the next).
STACK_KNOWLEDGE_SCAN_PATHS = (
    ".claude/stacks/**/*.md",
    ".claude/scripts/lib/README.md",
)

EXCLUDE_BASENAMES = frozenset({"TEMPLATE.md"})


def iter_stack_knowledge_files(project_dir: str = ".") -> list[str]:
    """Enumerate every file path that may contain a ## Stack Knowledge section.

    Every consumer (CI uniqueness check, per-file validator workflow, /change
    state-2 hints writer, recurrence-detector, resolve-causal-analyzer,
    stack_knowledge_audit, /bootstrap state-12/14, /solve Phase 1 Agent 2)
    calls this instead of re-implementing the glob list. Preserves archive
    exclusion via is_archive_path() and excludes TEMPLATE.md.

    `project_dir` lets tests pass a fixture root; defaults to cwd.
    """
    out: list[str] = []
    for pat in STACK_KNOWLEDGE_SCAN_PATHS:
        full = pat if project_dir == "." else os.path.join(project_dir, pat)
        for p in _glob.glob(full, recursive=True):
            if os.path.basename(p) in EXCLUDE_BASENAMES:
                continue
            if is_archive_path(p):
                continue
            out.append(p)
    return sorted(set(out))
