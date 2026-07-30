#!/usr/bin/env python3
"""RMG v2 Phase E — Verify typed recurrence_guard artifact at finalize time.

Reads `.runs/solve-trace.json`, parses `prevention_analysis.recurrence_guard`
through the RMG v2 parser (Phase A), and:

  * For `kind in {test, lint, hook, invariant}`: asserts the `artifact` path
    is either modified in the PR diff (`git diff <merge_base>...HEAD --name-only`)
    or present in the working tree on disk. If neither, fails. Skipped under
    `--analysis-only` because analysis-only skills (e.g. /solve --defect)
    emit forward-looking guards whose artifact is materialized by the next
    /resolve cycle (#1356).
  * For `kind == "none"`: asserts `unguardability_rationale` is present and
    answers BOTH (a) why no executable check expresses the invariant, AND
    (b) which observation/human-review/monitoring process catches the next
    instance. (Heuristic: hint A and hint B regexes both match.) ALWAYS
    enforced — the rationale check is independent of SKILL_TYPE and must
    not be bypassed for analysis-only skills.
  * For `kind == "legacy_freetext"`: only reachable when the emergency
    escape hatch `RMG_V2_TOLERANT=1` is set. Logs a warning and exits 0.
    Default (escape hatch off) makes free-text fail at parse time (exit 1).

Invoked by `.claude/scripts/lifecycle-finalize.sh` Step 4.6.

This script lives at finalize time, post-build pre-PR, NOT in
`adversarial-merge-gate.sh` (PreToolUse hook fires before the PR exists, so
`gh pr diff` is unavailable). Plan note R2-A7.

CLI:
  --trace PATH         path to solve-trace.json (default: .runs/solve-trace.json)
  --merge-base REF     git ref to compare HEAD against (default: origin/main)
  --analysis-only      skip the artifact-in-diff/disk check for kinds
                       test/lint/hook/invariant (issue #1356). The
                       kind=none rationale check still runs unconditionally.

Exit codes:
  0  pass (also: kind=legacy_freetext under RMG_V2_TOLERANT=1 escape hatch;
     also: analysis-only skip for typed-artifact kinds)
  1  parse failure (default for legacy free-text post-cutover)
  2  artifact missing from PR diff and working tree
  3  unguardability_rationale missing or insufficient (kind=none)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Re-use the RMG v2 parser from Phase A.
sys.path.insert(0, str(HERE / "lib"))
from recurrence_guard_parser import RecurrenceGuardParseError, parse  # noqa: E402

_HINT_A = re.compile(r"\b(no|cannot|can\s*not|cant)\b", re.IGNORECASE)
_HINT_B = re.compile(r"\b(review|observ|monitor|audit)", re.IGNORECASE)


def _read_trace(path: Path) -> dict:
    with path.open() as fh:
        return json.load(fh)


def _git_diff_files(merge_base: str, project_dir: Path) -> set[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(project_dir), "diff", f"{merge_base}...HEAD", "--name-only"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return set()
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _artifact_present(artifact: str, diff_files: set[str], project_dir: Path) -> bool:
    if not artifact:
        return False
    if artifact in diff_files:
        return True
    candidate = project_dir / artifact
    return candidate.exists()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", default=".runs/solve-trace.json")
    parser.add_argument("--merge-base", default="origin/main")
    parser.add_argument(
        "--analysis-only",
        action="store_true",
        help=(
            "Skip the artifact-in-diff/disk check for typed kinds "
            "(test/lint/hook/invariant). kind=none rationale check is "
            "preserved. Used by lifecycle-finalize.sh Step 4.6 when "
            "SKILL_TYPE=analysis-only (issue #1356)."
        ),
    )
    args = parser.parse_args(argv)

    project_dir = Path(os.environ.get("PROJECT_DIR") or os.getcwd()).resolve()
    trace_path = Path(args.trace)
    if not trace_path.is_absolute():
        trace_path = (project_dir / trace_path).resolve()

    if not trace_path.exists():
        print(f"FAIL: trace file {trace_path} not found", file=sys.stderr)
        return 1

    trace = _read_trace(trace_path)
    pa = trace.get("prevention_analysis") or {}
    risk = pa.get("recurrence_risk")
    guard = pa.get("recurrence_guard")

    if risk == "none":
        # No guard required when the designer asserts there is no recurrence risk.
        print("PASS: recurrence_risk=none; no guard required")
        return 0

    if guard is None:
        print(
            "FAIL: recurrence_guard is null but recurrence_risk != none",
            file=sys.stderr,
        )
        return 1

    try:
        canonical = parse(guard)
    except RecurrenceGuardParseError as exc:
        print(f"FAIL: recurrence_guard does not parse: {exc}", file=sys.stderr)
        return 1

    kind = canonical["kind"]

    if kind == "legacy_freetext":
        print(
            "WARN: legacy free-text recurrence_guard accepted via the "
            "RMG_V2_TOLERANT=1 emergency escape hatch. Default behavior "
            "blocks free-text at parse time. Restore typed schema to "
            "drop the warning.",
            file=sys.stderr,
        )
        return 0

    if kind == "none":
        unguard = canonical.get("unguardability_rationale") or ""
        if not unguard:
            print(
                "FAIL: kind=none requires unguardability_rationale",
                file=sys.stderr,
            )
            return 3
        if not _HINT_A.search(unguard):
            print(
                "FAIL: unguardability_rationale must explain WHY no executable "
                "check expresses the invariant (use 'no'/'cannot'/'can not')",
                file=sys.stderr,
            )
            return 3
        if not _HINT_B.search(unguard):
            print(
                "FAIL: unguardability_rationale must name the human/observability "
                "process that catches the next instance "
                "(mention review/observ/monitor/audit)",
                file=sys.stderr,
            )
            return 3
        print("PASS: kind=none with adequate unguardability_rationale")
        return 0

    artifact = canonical.get("artifact")
    if not artifact:
        print(
            f"FAIL: kind={kind} requires non-null artifact path/rule-id",
            file=sys.stderr,
        )
        return 2

    if args.analysis_only:
        # Analysis-only skills (e.g. /solve --defect) emit forward-looking
        # guards: the artifact is materialized by the next /resolve cycle,
        # not the current cycle. Skip the artifact presence check (path 1)
        # while preserving the kind=none rationale check above (path 2).
        # Issue #1356.
        print(
            f"PASS: kind={kind} artifact={artifact!r} accepted under "
            f"--analysis-only (forward-looking guard; next /resolve "
            f"materializes the artifact)"
        )
        return 0

    diff_files = _git_diff_files(args.merge_base, project_dir)
    if _artifact_present(artifact, diff_files, project_dir):
        print(f"PASS: kind={kind} artifact={artifact} present in diff or repo")
        return 0

    print(
        f"FAIL: kind={kind} artifact={artifact!r} is not in the PR diff "
        f"(git diff {args.merge_base}...HEAD --name-only) and does not exist "
        f"on disk under {project_dir}",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
