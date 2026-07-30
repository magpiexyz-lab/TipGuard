#!/usr/bin/env python3
"""Graduation atomicity check — enforce that canonical->graduated is atomic.

When a Stack Knowledge entry leaves the knowledge base (canonical -> graduated),
the structural prevention it graduates TO (a validator / hook / pattern file /
CLAUDE.md rule) must land in the SAME pull request. Otherwise the knowledge
is lost and the divergence regresses.

Two trigger conditions per PR diff:

  Trigger A (new graduation pointer)
    An entry's `graduated_to:` field transitions from null -> "<path>".
    Requirement: <path> appears in `git diff --name-only base..head`.

  Trigger B (canonical entry removed)
    A canonical entry is removed in the diff.
    Requirement: either
      (a) the prior version already had `graduated_to: <path>` and <path>
          is modified in this PR, OR
      (b) the PR has label `graduation-atomicity-override` (human attest).

Uses three-dot diff (`base...head`) so multi-commit PRs work correctly:
commits in the PR that add the graduated_to pointer and commits that add
the validator file are both within the aggregate diff.

Exits 0 clean / 1 on any violation.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

from lib.stack_knowledge_parser import (  # noqa: E402
    is_archive_path,
    parse_stack_knowledge,
)

OVERRIDE_LABEL = "graduation-atomicity-override"


def _git(*args: str, check: bool = True, text: bool = True) -> str:
    r = subprocess.run(["git", *args], capture_output=True, text=text, timeout=30)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr}")
    return r.stdout


def _get_file_at(ref: str, path: str) -> str:
    """Return file content at a given git ref. Empty string if path did not exist."""
    try:
        r = subprocess.run(
            ["git", "show", f"{ref}:{path}"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return ""
        return r.stdout
    except (subprocess.SubprocessError, OSError):
        return ""


def _changed_files(base: str, head: str) -> list[str]:
    """All files changed in base..head (three-dot semantics for multi-commit PRs)."""
    out = _git("diff", "--name-only", f"{base}...{head}", check=True)
    return [line for line in out.splitlines() if line.strip()]


def _modified_stack_files(base: str, head: str) -> list[str]:
    """Stack files touched by the PR (excluding archive and TEMPLATE)."""
    return [
        p for p in _changed_files(base, head)
        if p.startswith(".claude/stacks/")
        and p.endswith(".md")
        and not is_archive_path(p)
        and os.path.basename(p) != "TEMPLATE.md"
    ]


def _entries_by_hash(content: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for entry in parse_stack_knowledge(content):
        h = entry.get("composite_identity_hash")
        if isinstance(h, str):
            out[h] = entry
    return out


def _pr_has_override_label(labels: list[str]) -> bool:
    return OVERRIDE_LABEL in labels


def _load_pr_labels_from_env() -> list[str]:
    """Read PR labels from GITHUB_EVENT_PATH if present (GitHub Actions)."""
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path or not os.path.exists(event_path):
        return []
    try:
        with open(event_path) as f:
            event = json.load(f)
        labels = event.get("pull_request", {}).get("labels", []) or []
        return [l.get("name", "") for l in labels if isinstance(l, dict)]
    except (OSError, json.JSONDecodeError):
        return []


def check(base: str, head: str) -> list[str]:
    """Return a list of violation messages. Empty list = clean."""
    violations: list[str] = []
    changed = set(_changed_files(base, head))
    stack_files = _modified_stack_files(base, head)

    override = _pr_has_override_label(_load_pr_labels_from_env())

    for path in stack_files:
        before_content = _get_file_at(base, path)
        after_content = _get_file_at(head, path)
        before_by_hash = _entries_by_hash(before_content)
        after_by_hash = _entries_by_hash(after_content)

        before_hashes = set(before_by_hash.keys())
        after_hashes = set(after_by_hash.keys())

        # Trigger A — new graduated_to pointer
        for h, entry_after in after_by_hash.items():
            target = entry_after.get("graduated_to")
            if not isinstance(target, str) or not target.strip():
                continue
            entry_before = before_by_hash.get(h)
            had_target_before = (
                entry_before is not None
                and isinstance(entry_before.get("graduated_to"), str)
                and entry_before.get("graduated_to").strip()
            )
            if had_target_before:
                continue  # pointer was already set; not a transition

            if target not in changed:
                violations.append(
                    f"graduation-atomicity: {path} entry id={entry_after.get('id')!r} "
                    f"(hash={h}) added graduated_to={target!r} but that path is not "
                    f"modified in this PR (changed files: {sorted(changed)[:10]}{'...' if len(changed) > 10 else ''})"
                )

        # Trigger B — canonical entry removed
        removed_hashes = before_hashes - after_hashes
        for h in removed_hashes:
            entry_before = before_by_hash[h]
            if entry_before.get("maturity") != "canonical":
                continue
            if override:
                continue
            prior_target = entry_before.get("graduated_to")
            if isinstance(prior_target, str) and prior_target.strip():
                if prior_target in changed:
                    continue
                violations.append(
                    f"graduation-atomicity: {path} entry id={entry_before.get('id')!r} "
                    f"(hash={h}) removed a canonical entry whose graduated_to={prior_target!r} "
                    f"is not modified in this PR. Add the validator/hook/rule change "
                    f"to this PR or apply the {OVERRIDE_LABEL!r} label."
                )
            else:
                violations.append(
                    f"graduation-atomicity: {path} removed a canonical entry "
                    f"(id={entry_before.get('id')!r}, hash={h}) but graduated_to was null "
                    f"and no {OVERRIDE_LABEL!r} label is present. Either populate "
                    f"graduated_to and add the structural prevention in this PR, or "
                    f"apply the override label with explicit justification in the PR body."
                )

    return violations


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    p.add_argument("--base", required=True, help="Base SHA or ref")
    p.add_argument("--head", required=True, help="Head SHA or ref")
    args = p.parse_args(argv[1:])

    try:
        violations = check(args.base, args.head)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if not violations:
        print("graduation-atomicity: OK (no canonical entries graduated in this PR)")
        return 0

    print("graduation-atomicity: VIOLATION(S) DETECTED", file=sys.stderr)
    for v in violations:
        print(f"  - {v}", file=sys.stderr)
    print(
        "\nTo resolve: either add the structural prevention (validator / hook / "
        "pattern file / CLAUDE.md rule) to this PR, or apply the "
        f"{OVERRIDE_LABEL!r} label with a justification comment.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
