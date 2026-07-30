#!/usr/bin/env python3
"""Validate experiment.yaml web-app + actor:user behaviors have `pages:[]`.

Two modes:
  --all
      Validate EVERY web-app actor:user behavior. Used by spec/3 VERIFY
      (new experiments) and gate-keeper BG2 3c-1 (bootstrap gate).
      Exit 0 if all good; exit 1 with diagnostic on violation.

  --diff-vs-main
      Validate only behaviors ADDED or MODIFIED in the current branch's
      diff vs merge-base with `main`. Used by change/9 VERIFY — avoids
      blocking unrelated changes on pre-#1024 experiments that still have
      legacy behaviors lacking `pages:`. Exit 0 if all added/modified
      behaviors have `pages:`, or if no behavior changes in diff.

Exit codes:
  0  all good (or mode=not-applicable)
  1  violation — one or more behaviors lack `pages:`
  2  setup error (missing yaml lib, malformed file)

Error messages include remediation hints — specifically for legacy
experiments, the --all path points users to /upgrade +
migrate-experiment-yaml.py. The diff-vs-main path does NOT print legacy
hint because a change-authored violation is a current authoring bug,
not a migration issue.

See .claude/templates/experiment-yaml.md for the schema (#1024).
"""
import argparse
import os
import subprocess
import sys


def _load_yaml(path):
    try:
        import yaml
    except ImportError:
        sys.stderr.write("ERROR: PyYAML required (pip install pyyaml)\n")
        sys.exit(2)
    with open(path) as f:
        return yaml.safe_load(f)


def _is_user_behavior(b) -> bool:
    """True iff behavior's actor is 'user' (or absent — user is default)."""
    if not isinstance(b, dict):
        return False
    return b.get("actor", "user") not in ("system", "cron")


def _violating_behaviors(behaviors):
    """Return ids of actor:user behaviors with missing/empty pages."""
    bad = []
    for b in behaviors or []:
        if not _is_user_behavior(b):
            continue
        pages = b.get("pages")
        if not isinstance(pages, list) or len(pages) == 0:
            bad.append(b.get("id") or "<unnamed>")
    return bad


def _fail(msg, legacy_hint=False):
    sys.stderr.write(msg + "\n")
    if legacy_hint:
        sys.stderr.write(
            "\nHINT: If this experiment was bootstrapped before template "
            "issue #1024 was fixed, run `/upgrade` first. The upgrade "
            "skill runs .claude/scripts/migrate-experiment-yaml.py which "
            "will suggest `pages: [...]` entries for each behavior by "
            "scanning existing page directories on disk. Review and "
            "apply the suggestions, then re-run this command. See "
            ".claude/templates/experiment-yaml.md for the schema.\n"
        )
    sys.exit(1)


def _changed_behavior_ids_via_diff():
    """Return set of behavior ids whose block changed in the diff vs main.

    Strategy: parse experiment.yaml behaviors at HEAD and at merge-base,
    key each list by behavior id, compare. An id is "changed" if it's new
    or its dict differs from the merge-base version.

    Returns None when diff infrastructure is unavailable (detached HEAD,
    no merge-base, experiment.yaml absent at merge-base) — the caller
    falls back to --all semantics.
    """
    try:
        base = subprocess.run(
            ["git", "merge-base", "HEAD", "main"],
            capture_output=True, text=True, check=False,
        )
        if base.returncode != 0:
            base = subprocess.run(
                ["git", "merge-base", "HEAD", "origin/main"],
                capture_output=True, text=True, check=False,
            )
        if base.returncode != 0:
            return None
        merge_base_sha = base.stdout.strip()
        if not merge_base_sha:
            return None
        old = subprocess.run(
            ["git", "show",
             f"{merge_base_sha}:experiment/experiment.yaml"],
            capture_output=True, text=True, check=False,
        )
        if old.returncode != 0:
            return None
        import yaml
        old_data = yaml.safe_load(old.stdout) or {}
        new_data = _load_yaml("experiment/experiment.yaml")
        old_map = {
            b.get("id"): b
            for b in (old_data.get("behaviors") or [])
            if isinstance(b, dict) and b.get("id")
        }
        new_map = {
            b.get("id"): b
            for b in (new_data.get("behaviors") or [])
            if isinstance(b, dict) and b.get("id")
        }
        changed = set()
        for bid, b in new_map.items():
            if bid not in old_map or old_map[bid] != b:
                changed.add(bid)
        return changed
    except Exception:
        return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--all", action="store_true", dest="all_mode",
                   help="validate every actor:user behavior")
    p.add_argument("--diff-vs-main", action="store_true", dest="diff_mode",
                   help="validate only behaviors added/modified vs main")
    args = p.parse_args()

    if args.all_mode == args.diff_mode:
        sys.stderr.write(
            "ERROR: exactly one of --all or --diff-vs-main required\n"
        )
        sys.exit(2)

    exp_path = "experiment/experiment.yaml"
    if not os.path.isfile(exp_path):
        sys.stderr.write(
            f"ERROR: {exp_path} not found — run from project root\n"
        )
        sys.exit(2)

    data = _load_yaml(exp_path)
    archetype = (data.get("type") or "web-app").lower()
    if archetype != "web-app":
        sys.exit(0)

    behaviors = data.get("behaviors") or []

    if args.all_mode:
        bad = _violating_behaviors(behaviors)
        if bad:
            _fail(
                "ERROR: validate-behavior-pages --all: "
                f"{len(bad)} actor:user behavior(s) missing required "
                f"`pages: [...]` field: {', '.join(bad)}. Every "
                "behavior with `actor: user` must declare the pages it "
                "touches — this is the #1024 404-trap guard. Add "
                "`pages: [<page-name>, ...]` to each behavior. See "
                ".claude/templates/experiment-yaml.md.",
                legacy_hint=True,
            )
        sys.exit(0)

    changed = _changed_behavior_ids_via_diff()
    if changed is None:
        sys.stderr.write(
            "NOTICE: validate-behavior-pages --diff-vs-main: cannot "
            "compute diff vs main (no merge-base or experiment.yaml "
            "absent at merge-base) — falling back to --all semantics\n"
        )
        bad = _violating_behaviors(behaviors)
        if bad:
            _fail(
                "ERROR: validate-behavior-pages (--diff fallback to "
                f"--all): {len(bad)} actor:user behavior(s) missing "
                f"`pages: [...]`: {', '.join(bad)}.",
                legacy_hint=True,
            )
        sys.exit(0)

    subset = [
        b for b in behaviors
        if isinstance(b, dict) and b.get("id") in changed
    ]
    bad = _violating_behaviors(subset)
    if bad:
        _fail(
            "ERROR: validate-behavior-pages --diff-vs-main: "
            f"{len(bad)} behavior(s) modified or added in this branch "
            f"lack required `pages: [...]` field: {', '.join(bad)}. "
            "For every new/modified behavior with `actor: user` "
            "(or actor omitted), declare the pages it touches so "
            "bootstrap scaffolds a reachable frontend. See "
            ".claude/templates/experiment-yaml.md.",
            legacy_hint=False,
        )
    sys.exit(0)


if __name__ == "__main__":
    main()
