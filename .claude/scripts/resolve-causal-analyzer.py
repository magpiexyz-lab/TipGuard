#!/usr/bin/env python3
"""Headless causal analyzer for /resolve STATE 3b.

Purpose
-------
Before /resolve proposes fixes, inspect recent git history at each divergence
point from `.runs/resolve-reproduction.json`. Detect oscillation (flip pairs in
a rolling 90-day window) and anti-pattern matches (entries in
`## Stack Knowledge` sections with `anti_pattern: true`). Write findings to
`.runs/resolve-causal-analysis.json` with `halt_required: true` when an
oscillation threshold is met or an anti-pattern matches.

Non-goals
---------
This script never halts, never prompts, never exits non-zero on a policy
decision. It writes a structured artifact and returns exit 0; the STATE 3b
state file reads the artifact and drives the user-facing three-option UX.

On capability gaps (shallow clone, empty history at line, timeout) the artifact
is written with `causal_unavailable: true` so /resolve advances cleanly.

Usage
-----
  python3 .claude/scripts/resolve-causal-analyzer.py [--dry-run]

Reads
-----
  .runs/resolve-reproduction.json   (divergence points — written by STATE 3)
  .runs/resolve-context.json        (run_id)
  .claude/patterns/convergence-config.json   (thresholds/timeout)
  iter_stack_knowledge_files()       (anti-pattern entries; .claude/stacks/**/*.md
                                       plus .claude/scripts/lib/README.md)

Writes
------
  .runs/resolve-causal-analysis.json
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
from lib.stack_knowledge_parser import (  # noqa: E402
    iter_stack_knowledge_files,
    canonicalize,
    parse_stack_knowledge,
)

REPRO_PATH = os.path.join(REPO_ROOT, ".runs", "resolve-reproduction.json")
CTX_PATH = os.path.join(REPO_ROOT, ".runs", "resolve-context.json")
CONFIG_PATH = os.path.join(REPO_ROOT, ".claude", "patterns", "convergence-config.json")
OUTPUT_PATH = os.path.join(REPO_ROOT, ".runs", "resolve-causal-analysis.json")
STACKS_DIR = os.path.join(REPO_ROOT, ".claude", "stacks")

ISSUE_NUM_RE = re.compile(r"#(\d+)")
LINE_PART_INT_RE = re.compile(r"\d+")

# Set by main() to the config-driven budget; each subprocess call must return
# within this budget, otherwise the whole analysis is abandoned and the
# artifact is written with `causal_unavailable=true`.
_SUBPROCESS_TIMEOUT = 30.0


class AnalyzerTimeout(Exception):
    """Raised when the wall-clock timeout elapses."""


def _timeout_handler(signum, frame):  # noqa: ARG001
    raise AnalyzerTimeout()


def _run(cmd: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=cwd or REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=_SUBPROCESS_TIMEOUT,
    )


def _load_json(path: str, default: Any = None) -> Any:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def is_shallow_repo() -> bool:
    r = _run(["git", "rev-parse", "--is-shallow-repository"])
    return r.returncode == 0 and r.stdout.strip() == "true"


def git_log_at_line(file: str, line: int, max_commits: int = 10) -> list[dict]:
    """Return list of {hash, date (ISO), subject, issue_nums}."""
    rng = f"{line},{line}:{file}"
    cmd = [
        "git",
        "log",
        f"-L{rng}",
        "--no-patch",
        f"--max-count={max_commits}",
        "--format=%H|%cI|%s",
    ]
    r = _run(cmd)
    if r.returncode != 0:
        return []
    out: list[dict] = []
    for raw_line in r.stdout.splitlines():
        if not raw_line or raw_line.startswith("diff ") or raw_line.startswith("@@"):
            continue
        parts = raw_line.split("|", 2)
        if len(parts) != 3:
            continue
        h, date, subject = parts
        if len(h) < 7 or not re.match(r"^[0-9a-f]+$", h):
            continue
        issue_nums = [int(n) for n in ISSUE_NUM_RE.findall(subject)]
        out.append({
            "hash": h,
            "date": date,
            "subject": subject,
            "issue_nums": issue_nums,
        })
    return out


def git_log_at_line_with_patches(file: str, line: int, max_commits: int = 10) -> list[dict]:
    """Return commits with raw patch text for flip-pair analysis."""
    rng = f"{line},{line}:{file}"
    cmd = [
        "git",
        "log",
        f"-L{rng}",
        f"--max-count={max_commits}",
        "--format=---COMMIT---%n%H|%cI|%s",
    ]
    r = _run(cmd)
    if r.returncode != 0:
        return []
    commits: list[dict] = []
    current: dict | None = None
    for raw in r.stdout.splitlines():
        if raw == "---COMMIT---":
            if current is not None:
                commits.append(current)
            current = {"header": None, "added": [], "removed": []}
            continue
        if current is None:
            continue
        if current["header"] is None:
            parts = raw.split("|", 2)
            if len(parts) == 3:
                current["header"] = {
                    "hash": parts[0],
                    "date": parts[1],
                    "subject": parts[2],
                    "issue_nums": [int(n) for n in ISSUE_NUM_RE.findall(parts[2])],
                }
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            current["added"].append(raw[1:])
        elif raw.startswith("-") and not raw.startswith("---"):
            current["removed"].append(raw[1:])
    if current is not None:
        commits.append(current)
    return [c for c in commits if c.get("header")]


def _norm_line(s: str) -> str:
    return canonicalize(s)


def _lines_match(added_a: list[str], removed_b: list[str]) -> bool:
    """True when set of added_a equals set of removed_b after normalization.

    Ignores blank-after-normalization lines.
    """
    a = {_norm_line(x) for x in added_a if _norm_line(x)}
    b = {_norm_line(x) for x in removed_b if _norm_line(x)}
    return bool(a) and a == b


def count_flip_pairs(commits: list[dict], window_days: int = 90) -> int:
    """Count adjacent pairs in commits where commit N's removed lines ≈ commit N-1's
    added lines, and the older commit's date is within `window_days` of today.

    Input: commits in newer→older order with `added`, `removed`, and
    `header.date` populated (as returned by git_log_at_line_with_patches).
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)
    flips = 0
    for i in range(len(commits) - 1):
        newer, older = commits[i], commits[i + 1]
        try:
            older_date = datetime.fromisoformat(older["header"]["date"])
        except (KeyError, ValueError):
            continue
        if older_date < cutoff:
            continue
        if _lines_match(older["added"], newer["removed"]) and _lines_match(
            newer["added"], older["removed"]
        ):
            flips += 1
    return flips


def recent_resolve_commit(commits: list[dict]) -> dict | None:
    """Return the most recent commit whose subject contains 'resolve' or whose
    linked issue looks like a /resolve PR (best-effort without gh API).

    Heuristic only — matches messages like 'Fix #N: ...', '/resolve', 'Resolve
    #N', etc. The unambiguous signal is a linked issue number, but this function
    avoids a gh round-trip by flagging subject-text resolution verbs.
    """
    for c in commits:
        h = c.get("header") or c
        subject = (h.get("subject") or "").lower()
        if "resolve" in subject or subject.startswith("fix #"):
            return h
    return None


def load_anti_patterns(stacks_dir: str = STACKS_DIR) -> list[dict]:
    """Return all `anti_pattern: true` entries across every Stack Knowledge file.

    Uses `iter_stack_knowledge_files()` (single source of truth — currently
    `.claude/stacks/**/*.md` plus `.claude/scripts/lib/README.md`). The
    `stacks_dir` parameter is retained for backwards compatibility but only
    consulted when the helper returns no paths (test fixture path).
    """
    result: list[dict] = []
    paths = iter_stack_knowledge_files(REPO_ROOT)
    if not paths and os.path.isdir(stacks_dir):
        # Fallback for fixture-only test setups where REPO_ROOT differs.
        for root, _dirs, files in os.walk(stacks_dir):
            for name in files:
                if name.endswith(".md") and not name.endswith(".archive.md") and name != "TEMPLATE.md":
                    paths.append(os.path.join(root, name))
    for path in paths:
        try:
            content = open(path).read()
        except (OSError, UnicodeDecodeError):
            continue
        for entry in parse_stack_knowledge(content):
            if entry.get("anti_pattern") is True:
                entry["_source_file"] = os.path.relpath(path, REPO_ROOT)
                result.append(entry)
    return result


def infer_stack_scope(file_path: str) -> str:
    """Best-effort mapping: src/app/... → framework/<name>, .claude/stacks/<cat>/<val>.md
    → <cat>/<val>, fallback '' when unknown.
    """
    parts = file_path.replace("\\", "/").split("/")
    if len(parts) >= 3 and parts[0] == ".claude" and parts[1] == "stacks":
        slug = parts[2]
        val = os.path.splitext(parts[3])[0] if len(parts) >= 4 else ""
        return f"{slug}/{val}" if val else slug
    return ""


def anti_pattern_match_for(
    divergence_point: str,
    anti_patterns: list[dict],
    reproduction_text: str = "",
) -> dict | None:
    """Match anti-pattern entries against the current divergence.

    Requires BOTH signals to reduce false-positives at STATE 3b time (where
    we don't yet have a solve-trace with structured root_cause_class):

      1. `stack_scope` of the anti-pattern matches the divergence file's
         inferred stack scope (substring, canonicalized).
      2. At least one of the anti-pattern's `symptom_keywords` appears
         (canonicalized substring) in the reproduction text
         (`expected` + `actual` concatenated).

    A plain stack-scope match alone would be too broad (every fix in a stack
    would trigger). Requiring keyword overlap catches the cases where the
    current reproduction symptomatically resembles the known-bad pattern.
    """
    file_path = divergence_point.split(":", 1)[0]
    scope = canonicalize(infer_stack_scope(file_path))
    if not scope:
        return None
    repro = canonicalize(reproduction_text) if reproduction_text else ""
    for ap in anti_patterns:
        ap_scope = canonicalize(str(ap.get("composite_identity", {}).get("stack_scope", "")))
        if not ap_scope or ap_scope not in scope:
            continue
        keywords = ap.get("symptom_keywords") or []
        # Require at least one keyword match when the reproduction text is
        # available; fall back to stack-scope-only only when reproduction
        # text is absent (caller responsibility to provide it).
        if repro and keywords:
            if not any(canonicalize(str(kw)) in repro for kw in keywords if kw):
                continue
        return {
            "id": ap.get("id"),
            "composite_identity_hash": ap.get("composite_identity_hash"),
            "source_file": ap.get("_source_file"),
            "matched_keywords": [
                kw for kw in keywords
                if kw and canonicalize(str(kw)) in repro
            ] if repro else [],
        }
    return None


def parse_line_part(s: str) -> tuple[int | None, str]:
    """Extract a 1-based integer line number from a divergence_point line-part token.

    Accepts the following forms (per state-3-reproduce.md producer contract):

    - ``"34"``            → (34, "integer")
    - ``"34-55"``         → (34, "range: start of 34-55")
    - ``"180,217,261"``   → (180, "csv: first of 180,217,261")
    - ``"144 (G6)"``      → (144, "integer")   # parenthesized annotation ignored
    - ``"34-55 and …"``   → (34, "bundled_fragment: start of 34-55")
                             (the ' and ' form is forbidden by the state-3 contract,
                              but the analyzer degrades gracefully if a legacy
                              record slips through — extracts the first integer)

    Returns ``(None, "no-digits")`` when no integer can be extracted, so the
    caller keeps the ``skipped_reason`` flow from the pre-fix behavior.

    Values less than 1 are clamped to 1 (git log -L requires 1-based lines).
    """
    stripped = s.strip()
    if not stripped:
        return None, "no-digits"
    match = LINE_PART_INT_RE.search(stripped)
    if not match:
        return None, "no-digits"
    first = int(match.group(0))
    if first < 1:
        first = 1
    has_dash_between_digits = "-" in stripped and re.search(r"\d\s*-\s*\d", stripped)
    has_comma = "," in stripped
    # Detect legacy bundled-fragment separators. Whitespace required around
    # word-like separators (and/vs/&/+) to avoid matching legitimate '&' or
    # '+' inside file paths. ';' is detected with only trailing whitespace
    # since producers commonly write 'file1:10; file2:20' with no leading
    # space before the semicolon. The state-3-reproduce.md contract forbids
    # all of these forms in divergence_point; this heuristic is graceful
    # degradation only so legacy records before the contract still get
    # first-integer extraction.
    has_bundled_sep = re.search(
        r"(?:\s+(?:and|&|vs|\+)\s+|\s*;\s+)", stripped, re.IGNORECASE
    )
    if has_bundled_sep:
        note = f"bundled_fragment: start of {stripped.split()[0]}"
    elif has_dash_between_digits:
        note = f"range: start of {stripped}"
    elif has_comma:
        note = f"csv: first of {stripped}"
    else:
        note = "integer"
    return first, note


def analyze_divergence_point(
    divergence_point: str,
    anti_patterns: list[dict],
    window_days: int,
    reproduction_text: str = "",
) -> dict:
    ap_match = lambda: anti_pattern_match_for(  # noqa: E731
        divergence_point, anti_patterns, reproduction_text
    )
    if ":" not in divergence_point:
        return {
            "divergence_point": divergence_point,
            "touching_commits": [],
            "reversal_detected": False,
            "oscillation_count": 0,
            "anti_pattern_match": None,
            "skipped_reason": "malformed divergence_point (no colon)",
        }
    file_part, line_part = divergence_point.split(":", 1)
    line_num, line_parse_note = parse_line_part(line_part)
    if line_num is None:
        return {
            "divergence_point": divergence_point,
            "touching_commits": [],
            "reversal_detected": False,
            "oscillation_count": 0,
            "anti_pattern_match": None,
            "skipped_reason": f"no-digits line_part {line_part!r}",
            "line_parse_note": line_parse_note,
        }

    if not os.path.exists(os.path.join(REPO_ROOT, file_part)):
        return {
            "divergence_point": divergence_point,
            "touching_commits": [],
            "reversal_detected": False,
            "oscillation_count": 0,
            "anti_pattern_match": ap_match(),
            "skipped_reason": "file not found at HEAD",
            "line_parse_note": line_parse_note,
        }

    commits = git_log_at_line_with_patches(file_part, line_num, max_commits=10)
    headers = [c["header"] for c in commits if c.get("header")]

    if not commits:
        return {
            "divergence_point": divergence_point,
            "touching_commits": [],
            "reversal_detected": False,
            "oscillation_count": 0,
            "anti_pattern_match": ap_match(),
            "skipped_reason": "no git history at line",
            "line_parse_note": line_parse_note,
        }

    flips = count_flip_pairs(commits, window_days=window_days)
    resolve_c = recent_resolve_commit(commits)

    return {
        "divergence_point": divergence_point,
        "touching_commits": headers,
        "reversal_detected": resolve_c is not None and flips >= 1,
        "oscillation_count": flips,
        "anti_pattern_match": ap_match(),
        "line_parse_note": line_parse_note,
    }


def _write_artifact(payload: dict) -> None:
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(payload, f, indent=2)


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv[1:]

    config = _load_json(CONFIG_PATH, default={}) or {}
    timeout_secs = int(config.get("causal_analysis_timeout_seconds", 30))
    halt_threshold = int(config.get("oscillation_halt_threshold", 2))

    global _SUBPROCESS_TIMEOUT
    _SUBPROCESS_TIMEOUT = float(timeout_secs)

    ctx = _load_json(CTX_PATH, default={}) or {}
    run_id = ctx.get("run_id", "")

    repro = _load_json(REPRO_PATH, default=None)
    if repro is None:
        _write_artifact({
            "run_id": run_id,
            "divergence_points_analyzed": [],
            "halt_required": False,
            "halted": False,
            "halt_override_reason": None,
            "causal_unavailable": True,
            "analysis_complete": True,
            "skipped_reason": f"{REPRO_PATH} missing or unreadable",
        })
        return 0

    reproductions = repro.get("reproductions", []) if isinstance(repro, dict) else []
    divergence_records = [
        r for r in reproductions
        if isinstance(r, dict) and r.get("divergence_point")
    ]
    divergence_points = [r["divergence_point"] for r in divergence_records]
    repro_texts = {
        r["divergence_point"]: f"{r.get('expected','')}\n{r.get('actual','')}"
        for r in divergence_records
    }

    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(timeout_secs)
    try:
        if is_shallow_repo():
            _write_artifact({
                "run_id": run_id,
                "divergence_points_analyzed": [],
                "halt_required": False,
                "halted": False,
                "halt_override_reason": None,
                "causal_unavailable": True,
                "analysis_complete": True,
                "skipped_reason": "shallow git clone (history unavailable)",
            })
            return 0

        anti_patterns = load_anti_patterns()
        analyzed = [
            analyze_divergence_point(
                dp,
                anti_patterns,
                window_days=90,
                reproduction_text=repro_texts.get(dp, ""),
            )
            for dp in divergence_points
        ]
    except (AnalyzerTimeout, subprocess.TimeoutExpired):
        _write_artifact({
            "run_id": run_id,
            "divergence_points_analyzed": [],
            "halt_required": False,
            "halted": False,
            "halt_override_reason": None,
            "causal_unavailable": True,
            "analysis_complete": True,
            "skipped_reason": f"analysis exceeded {timeout_secs}s timeout",
        })
        return 0
    finally:
        signal.alarm(0)

    halt_required = any(
        (a.get("oscillation_count") or 0) >= halt_threshold
        or a.get("anti_pattern_match") is not None
        for a in analyzed
    )

    artifact = {
        "run_id": run_id,
        "divergence_points_analyzed": analyzed,
        "halt_required": halt_required,
        "halted": False,
        "halt_override_reason": None,
        "causal_unavailable": False,
        "analysis_complete": True,
    }

    if dry_run:
        json.dump(artifact, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        _write_artifact(artifact)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
