#!/usr/bin/env python3
"""
resolve-tier-floors.py — File-class tripwire for /resolve STATE 5b.

Reads `.runs/solve-trace.json` (which files the fix plans to modify, per
solution_design) and `.claude/patterns/resolve-tier-floors.yaml` (file-class →
minimum reproduction tier mapping). For each touched file, computes the
required minimum reproduction tier. Cross-checks against `.runs/resolve-
reproduction.json` per-issue `reproduction.method` and reports violations.

Modes:
  - warn (default — M2 launch): prints violations to stderr, writes report
    artifact, ALWAYS exits 0. Halts no /resolve runs during the soak window.
  - deny (future follow-up commit): non-zero exit on any violation.

Override mode via `RESOLVE_TIER_FLOORS_MODE=deny` env var, OR pass `--mode deny`
on the command line.

Output artifact: `.runs/resolve-tier-floors.json`
  {
    "schema_version": 1,
    "mode": "warn" | "deny",
    "rules_consulted": <N>,
    "issues_evaluated": <N>,
    "violations": [
      {
        "issue": <int>,
        "files_touched": [...],
        "tier_floor": "<min tier required>",
        "tier_actual": "<lead's reproduction.method>",
        "matching_rules": [{"glob": "...", "rationale": "..."}],
      }
    ],
    "passes": [{"issue": ..., "tier_floor": ..., "tier_actual": ...}],
  }

Exit codes:
  0 — warn-mode (always) OR deny-mode with no violations
  1 — deny-mode with at least one violation
  2 — bootstrap failure (missing input artifact, malformed YAML, etc.)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SOLVE_TRACE = REPO_ROOT / ".runs" / "solve-trace.json"
REPRODUCTION = REPO_ROOT / ".runs" / "resolve-reproduction.json"
TIER_FLOORS_YAML = REPO_ROOT / ".claude" / "patterns" / "resolve-tier-floors.yaml"
OUTPUT = REPO_ROOT / ".runs" / "resolve-tier-floors.json"

# Tier ordering: lower index = lower tier
TIER_ORDER = ["cite", "grep", "validator-fed", "exec"]
LEGACY_TIER_MAP = {
    "validator-confirmed": "validator-fed",
    "simulation-only": "cite",  # treated as the lowest tier for floor comparison
}


def tier_index(tier: str) -> int:
    """Convert a tier string (incl. legacy) to an index in TIER_ORDER. -1 if unknown."""
    if tier in LEGACY_TIER_MAP:
        tier = LEGACY_TIER_MAP[tier]
    try:
        return TIER_ORDER.index(tier)
    except ValueError:
        return -1


def glob_to_regex(glob: str) -> re.Pattern[str]:
    """Convert a shell-style glob to a regex (supports **, *, ?, character classes,
    and brace expansion like {ts,tsx,js})."""
    # Brace expansion: a/b/{x,y}.z → a/b/(x|y).z
    def _expand_braces(s: str) -> str:
        out = []
        i = 0
        while i < len(s):
            if s[i] == "{":
                end = s.index("}", i)
                inner = s[i + 1 : end]
                opts = inner.split(",")
                out.append("(?:" + "|".join(re.escape(o) for o in opts) + ")")
                i = end + 1
            else:
                out.append(s[i])
                i += 1
        return "".join(out)

    g = _expand_braces(glob)
    # Now translate the rest. We can't use fnmatch.translate because it doesn't
    # handle ** correctly across path separators. Build it manually:
    pattern = []
    i = 0
    while i < len(g):
        c = g[i]
        if c == "*":
            if i + 1 < len(g) and g[i + 1] == "*":
                pattern.append(".*")
                i += 2
            else:
                pattern.append("[^/]*")
                i += 1
        elif c == "?":
            pattern.append("[^/]")
            i += 1
        elif c in ".+()^$|\\":
            pattern.append("\\" + c)
            i += 1
        elif c == "(" and i > 0 and g[i - 1] != "?":
            # Already handled by brace expansion as (?:...)  — leave literal otherwise
            pattern.append("\\(")
            i += 1
        else:
            pattern.append(c)
            i += 1
    return re.compile("^" + "".join(pattern) + "$")


def file_touches_code_block(file_path: str, languages: list[str]) -> bool:
    """For .md files, check if the diff of this file in the current branch
    touches a fenced code block in any of the given languages.

    Approximation: read the file and check if any fenced code block in the
    requested languages exists. (A more precise check would look at the diff
    hunks; that's an optimization for a future commit.)
    """
    p = Path(file_path)
    if not p.exists():
        return False
    try:
        content = p.read_text()
    except (OSError, UnicodeDecodeError):
        return False
    # Match ```<lang> ... ```  for any of the requested langs
    for lang in languages:
        if re.search(r"```" + re.escape(lang) + r"\b", content):
            return True
    return False


def derive_floor(file_path: str, rules: list[dict], default: str) -> tuple[str, list[dict]]:
    """Walk rules top-to-bottom; return (min_tier, [matched_rules])."""
    matched = []
    for rule in rules:
        glob = rule.get("glob", "")
        if not glob:
            continue
        regex = glob_to_regex(glob)
        if not regex.match(file_path):
            continue
        # Optional: code_block_languages constraint
        cbl = rule.get("code_block_languages")
        if cbl:
            if not file_touches_code_block(file_path, cbl):
                # Rule has language constraint but file doesn't have those code blocks; skip
                continue
        matched.append({"glob": glob, "rationale": rule.get("rationale", "")})
        return rule.get("min_tier", default), matched
    return default, [{"glob": "(default)", "rationale": "no rule matched"}]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["warn", "deny"],
        default=os.environ.get("RESOLVE_TIER_FLOORS_MODE", "warn"),
        help="warn (default) prints violations but exits 0; deny exits 1 on violations",
    )
    args = parser.parse_args(argv)

    # Bootstrap — load inputs
    if not SOLVE_TRACE.exists():
        print(f"FAIL: {SOLVE_TRACE} not found (M2 needs solve-trace.json from STATE 5)", file=sys.stderr)
        return 2

    if not REPRODUCTION.exists():
        print(
            f"FAIL: {REPRODUCTION} not found (M2 needs resolve-reproduction.json from STATE 3)",
            file=sys.stderr,
        )
        return 2

    if not TIER_FLOORS_YAML.exists():
        print(f"FAIL: {TIER_FLOORS_YAML} not found", file=sys.stderr)
        return 2

    try:
        cfg = yaml.safe_load(open(TIER_FLOORS_YAML))
    except yaml.YAMLError as e:
        print(f"FAIL: cannot parse {TIER_FLOORS_YAML}: {e}", file=sys.stderr)
        return 2

    rules = cfg.get("rules", [])
    default_tier = cfg.get("default_min_tier", "cite")

    try:
        solve_trace = json.load(open(SOLVE_TRACE))
        reproduction = json.load(open(REPRODUCTION))
    except (json.JSONDecodeError, OSError) as e:
        print(f"FAIL: cannot read input artifacts: {e}", file=sys.stderr)
        return 2

    # Extract per-issue files_touched from solve-trace.solution_design
    # solution_design is freeform prose in current schema; M2 needs a structured
    # files_touched per issue. For now, fall back to scanning blast_radius
    # entries from resolve-context.json (they're structured as
    # "<file>:<line>:<classification>" strings).
    issue_files: dict[int, list[str]] = {}
    repros: dict[int, dict] = {}
    for r in reproduction.get("reproductions", []):
        if not isinstance(r, dict):
            continue
        issue = r.get("issue")
        if not isinstance(issue, int):
            continue
        repros[issue] = r
        # Files from divergence_point are a starting set (one file per repro record)
        dp = r.get("divergence_point", "")
        if dp:
            file_part = dp.split(":")[0].strip()
            if file_part:
                issue_files.setdefault(issue, []).append(file_part)

    # Augment from blast_radius if context exists
    ctx_path = REPO_ROOT / ".runs" / "resolve-context.json"
    if ctx_path.exists():
        try:
            ctx = json.load(open(ctx_path))
            for entry in ctx.get("blast_radius", []) or []:
                # Format: "<file>:<line-or-range>:<classification>"
                parts = str(entry).split(":")
                if not parts:
                    continue
                f = parts[0].strip()
                if not f:
                    continue
                # Apply to all issues for this run (blast radius is run-level, not per-issue)
                for issue in issue_files.keys():
                    if f not in issue_files[issue]:
                        issue_files[issue].append(f)
        except (json.JSONDecodeError, OSError):
            pass  # Best-effort augmentation

    violations: list[dict] = []
    passes: list[dict] = []

    for issue, files in issue_files.items():
        repro = repros.get(issue, {})
        actual_tier = repro.get("reproduction") or "<missing>"
        actual_idx = tier_index(actual_tier) if actual_tier != "<missing>" else -1

        # Compute the highest required floor across all touched files
        max_floor = "cite"
        max_idx = tier_index("cite")
        all_matched_rules = []
        for f in files:
            floor, matched = derive_floor(f, rules, default_tier)
            all_matched_rules.extend([{"file": f, **m} for m in matched])
            fi = tier_index(floor)
            if fi > max_idx:
                max_idx = fi
                max_floor = floor

        record = {
            "issue": issue,
            "files_touched": files,
            "tier_floor": max_floor,
            "tier_actual": actual_tier,
            "matching_rules": all_matched_rules,
        }

        if actual_idx < max_idx:
            violations.append(record)
        else:
            passes.append(
                {
                    "issue": issue,
                    "tier_floor": max_floor,
                    "tier_actual": actual_tier,
                }
            )

    # Write the artifact
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": args.mode,
                "rules_consulted": len(rules),
                "issues_evaluated": len(issue_files),
                "violations": violations,
                "passes": passes,
            },
            indent=2,
        )
    )

    if violations:
        for v in violations:
            print(
                f"WARN: issue #{v['issue']} reproduction.method='{v['tier_actual']}' "
                f"is below required floor '{v['tier_floor']}' "
                f"(touched: {v['files_touched']})",
                file=sys.stderr,
            )
        if args.mode == "deny":
            print(
                f"FAIL: {len(violations)} tier-floor violation(s); deny-mode active",
                file=sys.stderr,
            )
            return 1
        print(
            f"warn-mode: {len(violations)} violation(s) would block under deny-mode "
            f"(set RESOLVE_TIER_FLOORS_MODE=deny to enforce)",
            file=sys.stderr,
        )

    print(
        f"resolve-tier-floors: mode={args.mode}, "
        f"{len(violations)} violation(s), {len(passes)} pass(es), "
        f"report at {OUTPUT.relative_to(REPO_ROOT)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
