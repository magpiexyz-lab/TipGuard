"""Provenance-aware reader for .runs/ artifacts.

Forces every read site to declare a scope so that per-run vs cross-run state
cannot be silently confused (defect class #1437 / #1417). See companion
registry `.claude/patterns/cross-run-channels.json` for the
`cross-run-by-design` channel allowlist.

## Stack Knowledge

stack_scope: scripts/lib
canonical_function: runs_reader
composite_identity: provenance-blind-runs-read
maturity: canonical
graduated_to: null
fix_template: |
  from runs_reader import discover_current_run_id, read_jsonl
  identity = discover_current_run_id()
  if identity:
      r = read_jsonl(path, scope='current-run', current_run_id=identity.run_id)
  else:
      # HC5: manual gh pr create (no in-flight skill) — pass through
      return

## Read-side scopes

- `current-run`  — filter rows by run_id == current. Returns empty + no_current_run=True when run_id is unknown.
- `cross-run-by-design` — read all rows; caller must pre-register the channel.
- `git-history-augmented` — implicit on `read_git_log`; consults git log, not .runs/.
- `identity-resolution` — implicit on `discover_current_run_id` and `read_context_files`; bootstrap to compute who's running.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, NamedTuple, Optional

Scope = Literal["current-run", "cross-run-by-design"]
STALENESS_HOURS = 48


class Identity(NamedTuple):
    """Active execution identity. Mirrors lib-state.sh::resolve_active_identity output."""
    skill: str
    run_id: str
    attributed_to: str
    ancestors: list


class ReadResult(NamedTuple):
    """Typed result of read_jsonl. `no_current_run` signals HC5 pass-through;
    `skipped_missing_runid` counts legacy rows tolerated under HC2."""
    rows: list
    scope: str
    source: str
    no_current_run: bool = False
    skipped_missing_runid: int = 0


def _project_dir(p) -> Path:
    return Path(p or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()


def _git_branch(project_dir: Path) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", str(project_dir), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _head_commit_ts(project_dir: Path) -> Optional[datetime]:
    """HEAD commit timestamp; None if not in a git repo or no commits."""
    try:
        r = subprocess.run(
            ["git", "-C", str(project_dir), "log", "-1", "--format=%cI"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return None
        text = r.stdout.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _parse_ts(s) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    try:
        text = path.read_text()
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _to_identity(d) -> Optional[Identity]:
    if not d:
        return None
    return Identity(
        d.get("skill", ""),
        d.get("run_id", ""),
        d.get("attributed_to") or d.get("skill", ""),
        d.get("ancestors") or [],
    )


def discover_current_run_id(
    branch: Optional[str] = None,
    project_dir=None,
    include_completed: bool = False,
    head_commit_timestamp: Optional[datetime] = None,
) -> Optional[Identity]:
    """Identity-resolution. Two execution paths:

    Active-only path (include_completed=False) — used by skill-write-gate,
    skill-commit-gate, observe-commit-gate:
      - Returns the newest in-flight context (any parent state) within 48h.
      - Preserves child-preference during in-flight embed so write/commit
        gates dispatch to the actual writer skill's per-skill gates (#1347).

    PR-gate path (include_completed=True) — used by detect_skill_for_branch:
      Pass 1 — active top-level (completed=False, parent=None), 48h cap.
      Pass 2 — completed top-level, with context.ts >= HEAD commit timestamp.
              Rejects stale completed contexts that predate the PR's HEAD
              (#1417 fix). When HEAD timestamp is unavailable (non-git or
              empty repo), the 48h staleness cap applies instead.
      Pass 3 — orphan-child fallback (parent != None, within 48h).
              Top-level contexts rejected by Pass 1 or Pass 2 cannot sneak
              through here.

    Returns None on no match (manual gh pr create — HC5).
    """
    proj = _project_dir(project_dir)
    branch = branch or _git_branch(proj)
    now = datetime.now(timezone.utc)

    runs_dir = proj / ".runs"
    if not runs_dir.is_dir():
        return None

    def _candidates():
        for f in runs_dir.glob("*-context.json"):
            if f.name == "epilogue-context.json":
                continue
            try:
                with open(f) as fh:
                    d = json.load(fh)
            except Exception:
                continue
            if branch and d.get("branch") and d.get("branch") != branch:
                continue
            yield d

    if not include_completed:
        # Active-only variant: newest active context, no parent filter.
        best = None
        best_ts = ""
        for d in _candidates():
            if d.get("completed"):
                continue
            ts_dt = _parse_ts(d.get("timestamp"))
            if ts_dt and (now - ts_dt).total_seconds() > STALENESS_HOURS * 3600:
                continue
            ts = d.get("timestamp", "") or ""
            if ts > best_ts:
                best, best_ts = d, ts
        return _to_identity(best)

    # include_completed=True path
    if head_commit_timestamp is None:
        head_commit_timestamp = _head_commit_ts(proj)

    # Pass 1: active top-level
    best = None
    best_ts = ""
    for d in _candidates():
        if d.get("completed"):
            continue
        if d.get("parent"):
            continue
        ts_dt = _parse_ts(d.get("timestamp"))
        if ts_dt and (now - ts_dt).total_seconds() > STALENESS_HOURS * 3600:
            continue
        ts = d.get("timestamp", "") or ""
        if ts > best_ts:
            best, best_ts = d, ts
    if best:
        return _to_identity(best)

    # Pass 2: completed top-level. HEAD-recency check when available;
    # 48h staleness cap otherwise.
    best = None
    best_ts = ""
    for d in _candidates():
        if not d.get("completed"):
            continue
        if d.get("parent"):
            continue
        ts_dt = _parse_ts(d.get("timestamp"))
        if head_commit_timestamp is not None:
            if not ts_dt or ts_dt < head_commit_timestamp:
                continue
        else:
            if ts_dt and (now - ts_dt).total_seconds() > STALENESS_HOURS * 3600:
                continue
        ts = d.get("timestamp", "") or ""
        if ts > best_ts:
            best, best_ts = d, ts
    if best:
        return _to_identity(best)

    # Pass 3: orphan-child fallback (parent != None).
    best = None
    best_ts = ""
    for d in _candidates():
        if d.get("parent") is None:
            continue
        ts_dt = _parse_ts(d.get("timestamp"))
        if ts_dt and (now - ts_dt).total_seconds() > STALENESS_HOURS * 3600:
            continue
        ts = d.get("timestamp", "") or ""
        if ts > best_ts:
            best, best_ts = d, ts
    return _to_identity(best)


_CHANNELS_CACHE: Optional[dict] = None
_CHANNELS_CACHE_KEY: Optional[str] = None


def _channels(project_dir: Path) -> dict:
    global _CHANNELS_CACHE, _CHANNELS_CACHE_KEY
    key = str(project_dir)
    if _CHANNELS_CACHE is not None and _CHANNELS_CACHE_KEY == key:
        return _CHANNELS_CACHE
    p = project_dir / ".claude/patterns/cross-run-channels.json"
    try:
        with open(p) as fh:
            _CHANNELS_CACHE = json.load(fh).get("channels", {})
    except Exception:
        _CHANNELS_CACHE = {}
    _CHANNELS_CACHE_KEY = key
    return _CHANNELS_CACHE


def read_jsonl(
    path,
    *,
    scope: Scope,
    current_run_id: Optional[str] = None,
    cross_run_channel: Optional[str] = None,
    project_dir=None,
) -> ReadResult:
    """Read a JSONL file under a declared scope.

    scope='current-run' + current_run_id=None  → empty result + no_current_run=True (HC5)
    scope='current-run' + current_run_id=str   → rows where row['run_id'] == current_run_id;
                                                  rows missing run_id are skipped (HC2) and counted.
    scope='cross-run-by-design' + cross_run_channel=str → all rows (channel must be pre-registered).
    """
    proj = _project_dir(project_dir)
    p = Path(path)
    if not p.is_absolute():
        p = proj / p

    if scope == "current-run":
        if current_run_id is None:
            return ReadResult([], scope, str(p), no_current_run=True)
        rows = []
        skipped = 0
        for r in _read_jsonl(p):
            rid = r.get("run_id")
            if not rid:
                skipped += 1
                continue
            if rid == current_run_id:
                rows.append(r)
        return ReadResult(rows, scope, str(p), skipped_missing_runid=skipped)

    if scope == "cross-run-by-design":
        if not cross_run_channel:
            raise ValueError(
                "cross-run-by-design scope requires cross_run_channel= argument"
            )
        chans = _channels(proj)
        entry = chans.get(cross_run_channel)
        if not entry:
            raise ValueError(
                f"channel {cross_run_channel!r} not registered in cross-run-channels.json"
            )
        try:
            rel = str(p.relative_to(proj))
        except ValueError:
            rel = str(p)
        if rel not in entry.get("paths", []):
            raise ValueError(
                f"path {rel!r} not declared under channel {cross_run_channel!r}"
            )
        return ReadResult(_read_jsonl(p), scope, str(p))

    raise ValueError(f"unknown scope: {scope!r}")


def read_context_files(
    branch: Optional[str] = None,
    *,
    include_completed: bool = False,
    project_dir=None,
) -> list:
    """Read .runs/*-context.json files matching branch.

    Returns the list of matching context dicts sorted by timestamp descending.
    Callers wanting single-Identity precedence use discover_current_run_id().
    """
    proj = _project_dir(project_dir)
    branch = branch or _git_branch(proj)
    out = []
    runs_dir = proj / ".runs"
    if not runs_dir.is_dir():
        return out
    for f in runs_dir.glob("*-context.json"):
        if f.name == "epilogue-context.json":
            continue
        try:
            with open(f) as fh:
                d = json.load(fh)
        except Exception:
            continue
        if branch and d.get("branch") and d.get("branch") != branch:
            continue
        if not include_completed and d.get("completed"):
            continue
        out.append(d)
    return sorted(out, key=lambda d: d.get("timestamp", "") or "", reverse=True)


def read_git_log(
    files,
    *,
    since_days: int = 60,
    max_per_file: int = 5,
    project_dir=None,
) -> list:
    """git-history-augmented: per-file commit lists, capped at max_per_file most-recent.

    Returns [{"sha": str, "subject": str, "timestamp": ISO, "files": [str]}, ...].
    One subprocess call per file; non-git directories return []. Failures per
    file are silent (consistent with HC5 — best-effort augmentation).
    """
    proj = _project_dir(project_dir)
    files = list(files or [])
    if not files:
        return []
    since = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%Y-%m-%d")
    out = []
    for f in files:
        try:
            r = subprocess.run(
                [
                    "git", "-C", str(proj), "log",
                    f"--since={since}",
                    "--max-count", str(max_per_file),
                    "--pretty=format:%H%x09%s%x09%cI",
                    "--", f,
                ],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode != 0:
                continue
            for line in r.stdout.splitlines():
                parts = line.split("\t", 2)
                if len(parts) < 3:
                    continue
                sha, subject, ts = parts
                if not sha:
                    continue
                out.append({"sha": sha, "subject": subject, "timestamp": ts, "files": [f]})
        except Exception:
            continue
    return out


__all__ = [
    "Identity",
    "ReadResult",
    "Scope",
    "STALENESS_HOURS",
    "discover_current_run_id",
    "read_jsonl",
    "read_context_files",
    "read_git_log",
]
