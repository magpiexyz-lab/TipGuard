#!/usr/bin/env python3
"""Discover and classify transient artifacts in state-registry.json.

For each entry whose VERIFY command references a `.runs/<path>` artifact, classify:
  - transient-cross-skill: path is in lifecycle-init.sh STALE_ARTIFACTS or DELIVERY_ARTIFACTS
                           (deleted at the start of any new skill run).
  - transient-intra-skill: path appears as `rm -f` / `Delete` target in some state-*.md
                           ACTIONS section (deleted by a later state of the same skill).
  - durable: not deleted by any known mechanism — VERIFY can safely rerun on resume.

Usage:
    python3 .claude/scripts/migrate-state-registry-lifecycle.py [--apply]

Without --apply: prints a unified-diff-style preview to stdout.
With --apply: rewrites .claude/patterns/state-registry.json in place. Author should
review `git diff` before committing.

This is a one-shot classification, not a runtime check. The runtime check is
verify-linter rule_artifact_transience (see .claude/scripts/lib/linter/runner.py).

Closes #1162 root cause: VERIFY commands assume artifact permanence.
"""

import argparse
import glob
import json
import os
import re
import sys
from collections import OrderedDict


REGISTRY_PATH = ".claude/patterns/state-registry.json"
INIT_SCRIPT = ".claude/scripts/lifecycle-init.sh"
STATE_FILES_GLOB = ".claude/skills/*/state-*.md"
PATTERN_FILES = [".claude/patterns/state-99-epilogue.md"]

ARTIFACT_RE = re.compile(r"\.runs/[A-Za-z0-9_./-]+(?:\.json|\.md|\.jsonl|\.txt|\.flag)?")


def read_init_script_paths():
    """Extract STALE_ARTIFACTS + DELIVERY_ARTIFACTS paths from lifecycle-init.sh."""
    text = open(INIT_SCRIPT).read()
    # Lines like: "$PROJECT_DIR/.runs/observe-result.json"
    paths = set(re.findall(r'"\$PROJECT_DIR(/\.runs/[^"]+)"', text))
    # Strip leading slash so it matches what VERIFY commands write
    return {p.lstrip("/") for p in paths}


def collect_intra_skill_deletions():
    """Scan state-*.md files for `rm -f`/`rm -rf` actions on .runs/ paths.

    Only counts deletions inside ```bash code fences``` (real script actions).
    Prose mentions like "Delete `.runs/foo.md`" are explicitly ignored.

    Returns dict: artifact_path -> set of (skill, state_id) tuples that delete it.
    """
    deletions = {}
    files = glob.glob(STATE_FILES_GLOB) + PATTERN_FILES
    for f in files:
        if not os.path.isfile(f):
            continue
        try:
            text = open(f).read()
        except Exception:
            continue
        m = re.search(r"\.claude/skills/([^/]+)/state-([^.]+)\.md", f)
        if m:
            skill, state_id = m.group(1), m.group(2)
        else:
            skill, state_id = "_pattern", os.path.basename(f)

        # Pass A: extract bash/python code fences — actual scripted deletions
        bash_blocks = re.findall(r"```bash\s*\n(.*?)```", text, re.DOTALL)
        py_blocks = re.findall(r"```python\s*\n(.*?)```", text, re.DOTALL)
        all_code = "\n".join(bash_blocks + py_blocks)
        for m2 in re.finditer(
            r"(?:rm\s+-[rfRF]+\s+|os\.remove\(['\"]|os\.unlink\(['\"])"
            r"([^\s'\")]*\.runs/[A-Za-z0-9_./-]+)",
            all_code,
        ):
            artifact = m2.group(1).rstrip("'\")").lstrip("'\"")
            if artifact.startswith("$PROJECT_DIR/"):
                artifact = artifact[len("$PROJECT_DIR/"):]
            if not artifact.startswith(".runs/"):
                continue
            deletions.setdefault(artifact, set()).add((skill, state_id))

        # Pass B: imperative prose directives at bullet start — `- Delete ` followed
        # by `.runs/<path>` in backticks. The lead executes these as Bash actions
        # even though they're not in code fences.
        for m3 in re.finditer(
            r"(?m)^\s*[-*]\s+Delete\s+`(\.runs/[A-Za-z0-9_./-]+)`",
            text,
        ):
            artifact = m3.group(1)
            deletions.setdefault(artifact, set()).add((skill, state_id))
    return deletions


def extract_verify_cmd(value):
    """Return the verify command string from a registry entry (string or dict)."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("verify", "")
    return ""


def extract_artifact_paths(verify_cmd):
    """Find .runs/<path> references inside a verify command.

    Returns a sorted list — deterministic order ensures the migration is
    idempotent (re-running --apply produces the same artifact selection).
    """
    if not verify_cmd or verify_cmd.strip() == "true":
        return []
    return sorted(set(ARTIFACT_RE.findall(verify_cmd)))


def classify(artifact_path, cross_skill_paths, intra_paths_map, current_skill):
    """Return (lifecycle, justification).

    Decision rules (in order):
      1. Path is in lifecycle-init.sh STALE_ARTIFACTS/DELIVERY_ARTIFACTS → transient-cross-skill.
      2. Path is under a cleaned directory (e.g., .runs/agent-traces/) → transient-cross-skill.
      3. Path is deleted by a state of THIS skill (or shared patterns) → transient-intra-skill.
      4. Path is deleted by another skill's state ONLY → durable (this skill's run never deletes
         it; cross-skill deletion is informational, not a lifecycle determinant).
      5. Otherwise → durable.

    Rule 4 prevents over-classification: e.g., /bootstrap doesn't delete current-plan.md;
    /change.12 does. From /bootstrap's perspective, current-plan.md is durable through the run.
    """
    if artifact_path in cross_skill_paths:
        return ("transient-cross-skill", "in lifecycle-init.sh STALE_ARTIFACTS/DELIVERY_ARTIFACTS")
    for csp in cross_skill_paths:
        if csp.endswith("/") and artifact_path.startswith(csp):
            return ("transient-cross-skill", f"under cleaned directory {csp}")
    deleters = intra_paths_map.get(artifact_path, set())
    same_skill_deleters = {(s, sid) for (s, sid) in deleters if s in (current_skill, "_pattern")}
    if same_skill_deleters:
        return ("transient-intra-skill", f"deleted by {sorted(same_skill_deleters)}")
    return ("durable", "no deletion source found")


def main():
    ap = argparse.ArgumentParser(description="Migrate state-registry.json with lifecycle metadata")
    ap.add_argument("--apply", action="store_true", help="Apply changes in place; default = dry-run preview")
    ap.add_argument("--show-durable", action="store_true", help="Also report durable entries (default: only show changes)")
    args = ap.parse_args()

    cross_skill_paths = read_init_script_paths()
    intra_paths_map = collect_intra_skill_deletions()

    print(f"Cross-skill cleaned paths ({len(cross_skill_paths)}):", file=sys.stderr)
    for p in sorted(cross_skill_paths):
        print(f"  {p}", file=sys.stderr)
    print(f"Intra-skill deletion sites ({len(intra_paths_map)}):", file=sys.stderr)
    for k, v in sorted(intra_paths_map.items()):
        print(f"  {k} ← {sorted(v)}", file=sys.stderr)
    print("", file=sys.stderr)

    registry = json.load(open(REGISTRY_PATH), object_pairs_hook=OrderedDict)
    proposals = []  # list of (skill, sid, current_value, proposed_value, justification)

    for skill, states in registry.items():
        if not isinstance(states, dict):
            continue
        for sid, val in states.items():
            if sid.startswith("_"):
                continue
            verify_cmd = extract_verify_cmd(val)
            artifacts = extract_artifact_paths(verify_cmd)
            if not artifacts:
                continue
            # Pick the FIRST artifact that's transient. If none transient, leave durable.
            best = None
            for a in artifacts:
                lc, why = classify(a, cross_skill_paths, intra_paths_map, skill)
                if lc != "durable":
                    best = (a, lc, why)
                    break
            if best is None:
                # All artifacts are durable
                if args.show_durable:
                    print(f"  durable: {skill}.{sid} → {artifacts}", file=sys.stderr)
                continue

            artifact, lifecycle, why = best
            # Build proposed value preserving any existing dict shape
            if isinstance(val, str):
                proposed = OrderedDict([
                    ("verify", val),
                    ("artifact", artifact),
                    ("lifecycle", lifecycle),
                ])
            else:
                proposed = OrderedDict(val)
                proposed["artifact"] = artifact
                proposed["lifecycle"] = lifecycle
            if val != proposed:
                proposals.append((skill, sid, val, proposed, why))

    print(f"\n=== {len(proposals)} proposals ===\n")
    for skill, sid, cur, prop, why in proposals:
        print(f"[{skill}.{sid}] {prop['lifecycle']} ({why})")
        print(f"  artifact: {prop['artifact']}")
        if isinstance(cur, str):
            print(f"  current : <string verify command>")
        else:
            print(f"  current : keys={list(cur.keys())}")
        print()

    if args.apply:
        # Apply in place — substitute proposals into registry
        for skill, sid, _cur, prop, _why in proposals:
            registry[skill][sid] = prop
        json.dump(registry, open(REGISTRY_PATH, "w"), indent=2)
        # state-registry.json doesn't end with newline by convention; keep it minimal
        print(f"\nApplied {len(proposals)} changes to {REGISTRY_PATH}", file=sys.stderr)
    else:
        print("\n(dry-run; pass --apply to write changes)", file=sys.stderr)


if __name__ == "__main__":
    main()
