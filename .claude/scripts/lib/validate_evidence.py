"""validate_evidence — reusable evidence-validation primitives for EARC.

Extracted from validate-recovery.sh's inline Python in commit c05d637^.
Used by:
  - validate-recovery.sh (existing): post-write recovery_validated stamping
  - write-recovery-trace.sh (slice 1): pre-write evidence-anchored fixes
  - write-phase-a-repair.sh (slice 3): pre-write Phase A repair attestation

Three primitives:
  - validate_build_evidence: build-result.json freshness + exit_code check
  - validate_diff_evidence: per-fix file ↔ git diff correlation
  - validate_manifest_evidence: presence of expected entries in a manifest

Path discipline: all callers should pass `project_dir` resolved via
`get_project_dir()` from .claude/hooks/lib-core.sh (CLAUDE_WORKTREE-aware).
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from typing import Iterable


DEFAULT_MAX_AGE_SECONDS = 300  # 5 minutes — round-2 critic Concern 4


class EvidenceError(Exception):
    """Raised when an evidence check returns a structured failure.

    Library callers should catch this and emit the message to the user;
    one error message per failure dimension (do not concatenate)."""


def _parse_iso8601(ts: str) -> float | None:
    """Best-effort parse; returns epoch seconds or None on failure.

    Accepts: ``2026-04-30T05:23:32Z``, ``2026-04-30T05:23:32.123456+00:00``,
    ``2026-04-30T05:23:32+00:00``."""
    if not ts:
        return None
    s = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


def validate_build_evidence(
    build_path: str,
    trace_timestamp: str | None = None,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    project_dir: str | None = None,
) -> tuple[bool, list[str]]:
    """Validate build-result.json shows passing build, fresh, on current HEAD.

    Returns (ok, errors). Empty errors when ok is True. Caller decides how to
    surface the errors — typically appended to a per-trace error list.

    Freshness check (round-2 critic Concern 4):
      - file mtime must be within `max_age_seconds` of `trace_timestamp` (when
        timestamp provided); a stale build artifact from a prior fixer attempt
        will satisfy a naïve exit_code check while the current tree is broken.
      - if `commit_sha` is recorded in the JSON, it must equal the current
        HEAD; otherwise the evidence is from a different commit.

    Memory: feedback_stale_runs_artifacts.md, feedback_before_after_diff_traps.md
    """
    errors: list[str] = []

    if not os.path.isfile(build_path):
        return False, ["build-result.json missing — run the build before validating"]

    try:
        st = os.stat(build_path)
    except OSError as exc:
        return False, [f"build-result.json stat failed: {exc}"]

    try:
        br = json.load(open(build_path))
    except Exception as exc:
        return False, [f"build-result.json malformed: {exc}"]

    ec = br.get("exit_code")
    if ec != 0:
        errors.append(f"build-result.json exit_code={ec} (need 0)")

    if trace_timestamp:
        trace_epoch = _parse_iso8601(trace_timestamp)
        if trace_epoch is not None:
            age = trace_epoch - st.st_mtime
            if age > max_age_seconds:
                errors.append(
                    f"build-result.json is stale: mtime {int(age)}s before trace timestamp "
                    f"(max {max_age_seconds}s)"
                )

    recorded_sha = br.get("commit_sha", "")
    if recorded_sha:
        head_sha = ""
        if project_dir is None:
            project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")
        try:
            head_sha = subprocess.check_output(
                ["git", "-C", project_dir, "rev-parse", "HEAD"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except subprocess.CalledProcessError:
            pass
        if head_sha and recorded_sha != head_sha:
            errors.append(
                f"build-result.json commit_sha={recorded_sha[:8]} != HEAD={head_sha[:8]} "
                f"(stale evidence from a different commit)"
            )

    return (len(errors) == 0), errors


def validate_diff_evidence(
    fixes: list[dict],
    spawn_sha: str | None,
    project_dir: str | None = None,
) -> tuple[bool, list[str]]:
    """Validate every ``fixes[].file`` appears in the git diff.

    Diff set: ``git diff --name-only <spawn_sha>..HEAD`` UNION
    ``git status --porcelain --untracked-files=all``. Falls back to
    ``HEAD~..HEAD`` when ``spawn_sha`` isn't reachable (shallow clone).

    Returns (ok, errors). ``ok=True`` means every fix's file is present.
    """
    if not fixes:
        return True, []

    if project_dir is None:
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")

    diff_files = _collect_diff_files(spawn_sha, project_dir)

    missing: list[str] = []
    for fix in fixes:
        if not isinstance(fix, dict):
            continue
        f = fix.get("file")
        if not f:
            continue
        if f in diff_files:
            continue
        if any(
            d == f or d.endswith("/" + f) or f.endswith("/" + d)
            for d in diff_files
        ):
            continue
        missing.append(f)

    if missing:
        return False, [f"fixes[].file not present in diff: {missing}"]
    return True, []


def _collect_diff_files(spawn_sha: str | None, project_dir: str) -> set[str]:
    """Compute the set of files modified since spawn (best-effort)."""
    diff_files: set[str] = set()
    if spawn_sha:
        try:
            out = subprocess.check_output(
                ["git", "-C", project_dir, "diff", "--name-only", f"{spawn_sha}..HEAD"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            diff_files.update(f for f in out.splitlines() if f)
        except subprocess.CalledProcessError:
            try:
                out = subprocess.check_output(
                    ["git", "-C", project_dir, "diff", "--name-only", "HEAD~..HEAD"],
                    text=True,
                    stderr=subprocess.DEVNULL,
                )
                diff_files.update(f for f in out.splitlines() if f)
            except subprocess.CalledProcessError:
                pass
    try:
        out = subprocess.check_output(
            ["git", "-C", project_dir, "status", "--porcelain", "--untracked-files=all"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        for line in out.splitlines():
            if len(line) > 3:
                diff_files.add(line[3:].strip().strip('"'))
    except subprocess.CalledProcessError:
        pass
    return diff_files


def validate_manifest_evidence(
    manifest_path: str,
    expected_entries: Iterable[str],
    entries_field: str = "entries",
) -> tuple[bool, list[str]]:
    """Validate ``manifest_path`` contains every expected entry.

    Args:
        manifest_path: path to JSON file with a top-level array under
            ``entries_field`` (default: ``entries``).
        expected_entries: iterable of strings the manifest must contain.
        entries_field: JSON top-level key to read the array from.

    Returns (ok, errors).
    """
    if not os.path.isfile(manifest_path):
        return False, [f"manifest missing: {manifest_path}"]
    try:
        m = json.load(open(manifest_path))
    except Exception as exc:
        return False, [f"manifest malformed: {exc}"]
    have = set(m.get(entries_field, []) or [])
    want = set(expected_entries)
    missing = sorted(want - have)
    if missing:
        return False, [f"manifest missing entries ({entries_field}): {missing}"]
    return True, []


def resolve_project_dir() -> str:
    """Worktree-aware project root. Prefer ``CLAUDE_PROJECT_DIR`` (set by
    lib-core.sh); fall back to ``git rev-parse --show-toplevel``; final
    fallback is ``.``.

    All callers in this library should pass the result of this function as
    ``project_dir`` to keep path resolution consistent across worktrees.
    Round-2 critic Concern 5.
    """
    pd = os.environ.get("CLAUDE_PROJECT_DIR")
    if pd:
        return pd
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip() or "."
    except subprocess.CalledProcessError:
        return "."
