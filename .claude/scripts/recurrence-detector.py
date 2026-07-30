#!/usr/bin/env python3
"""RMG v2 Layer 4 — Recurrence detector (advisory + promotion tiers).

Read-side scope: **cross-run-by-design**. Groups rows by `composite_identity`
across run_id boundaries to surface recurring failure shapes — the whole
point of the detector is to see patterns that span multiple skill runs.
The scope is declared at the call site via `# scope: cross-run-by-design`
on the `load_fix_ledger` invocation. See `.claude/patterns/cross-run-channels.json`
channel `fix-ledger`. The strict-parse helper here is preserved (raises
`SchemaError` on JSON decode failure) instead of using `runs_reader.read_jsonl`
which silently skips malformed lines — recurrence-detector's exit-code-3
contract (CLI exit 3 on ledger schema error) must remain authoritative.

Reads `.runs/fix-ledger.jsonl`, groups rows by composite_identity (joining to
the existing Stack Knowledge composite via `stack_knowledge_parser.compute_hash`
on `(root_cause_class, divergence_pattern, stack_scope)`), dedupes per day,
and writes:

  * `.runs/recurrence-candidates.jsonl` — advisory artifact (`priority:high`
    when ≥2 distinct run_ids hit the same composite_identity within 60 days).
    Future /resolve, /solve, /change runs with `problem_type=defect` consume
    this file via solve-reasoning Phase 1a (Phase C).
  * Optionally a `pattern-graduation-stable` GitHub issue when the canonical
    promotion threshold from `stack_knowledge_audit.py`
    (`occurrence_count ≥ 5`, `confidence > 0.8`, no oscillation in 90d) is
    met. The issue is filed via `gh issue create`; idempotency is enforced
    by checking for an open issue whose title contains the composite_identity.

NEVER mutates `.claude/stacks/**` or `template-coherence-rules.json`
(TEMPLATE.md:223 — auto-mutation of maturity is forbidden).

Concurrency safety: writes are protected by a `python3 fcntl.flock(LOCK_EX)`
on a sidecar `.runs/recurrence-candidates.jsonl.lock` file, so concurrent
lifecycle-finalize.sh runs cannot interleave rows. Append-only.

CLI:
  --advisory-only        emit candidates JSONL only (default)
  --promotion-only       skip advisory; only file promotion issues
  --dry-run              read + classify + log decisions; do not write
  --since-days N         override 60d advisory window (default 60)
  --project-dir PATH     repo root (default: env PROJECT_DIR or CWD)

Exit codes:
  0  success (or no candidates emitted)
  2  lock contention (caller treats as warning; non-blocking)
  3  schema error in fix-ledger.jsonl
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import fcntl
import glob
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

# --- Path setup -------------------------------------------------------------

HERE = Path(__file__).resolve().parent
REPO_ROOT_DEFAULT = HERE.parent.parent

sys.path.insert(0, str(REPO_ROOT_DEFAULT / "scripts" / "lib"))
from stack_knowledge_parser import compute_hash, parse_stack_knowledge_file  # noqa: E402

# Symptom canonicalizer is sibling
sys.path.insert(0, str(HERE / "lib"))
from symptom_canonicalizer import canonicalize_symptom, symptom_signature_hash  # noqa: E402

# Promotion-tier thresholds. SOURCE OF TRUTH:
#   .claude/scripts/lib/stack_knowledge_audit.py — RAW_TO_STABLE_MIN_OCCURRENCE,
#   RAW_TO_STABLE_MIN_CONFIDENCE, OSCILLATION_WINDOW_DAYS.
# Mirrored here (not imported) because stack_knowledge_audit.py uses
# `from lib.stack_knowledge_parser import ...`, a relative import that fails
# under pytest collection when this module is imported by tests.
# `tests/test_recurrence_detector.py::ConstantsParityTests` asserts the
# values stay in sync — drift is caught at CI, not at runtime.
RAW_TO_STABLE_MIN_OCCURRENCE = 5
RAW_TO_STABLE_MIN_CONFIDENCE = 0.8
OSCILLATION_WINDOW_DAYS = 90

ADVISORY_WINDOW_DAYS_DEFAULT = 60
ADVISORY_MIN_OCCURRENCES = 2

# --- Locking ---------------------------------------------------------------


@contextlib.contextmanager
def _exclusive_lock(lock_path: Path):
    """Acquire an exclusive flock on lock_path (creating it if needed).

    Times out fast — recurrence-detector is non-blocking; if another process
    is already holding the lock we give up and let the caller log a warning.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                raise _LockContention(str(lock_path)) from exc
            raise
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


class _LockContention(Exception):
    pass


# --- Ledger loading --------------------------------------------------------


def load_fix_ledger(path: Path) -> Iterator[dict]:
    """Yield rows from fix-ledger.jsonl. Skips template-edit rows (no symptom)."""
    if not path.exists():
        return
    with path.open() as fh:
        for line_no, raw in enumerate(fh, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise SchemaError(f"line {line_no}: {exc}") from exc
            if not isinstance(row, dict):
                raise SchemaError(f"line {line_no}: row is not a dict")
            if row.get("entry_type") == "template-edit":
                continue
            yield row


class SchemaError(Exception):
    pass


# --- Composite resolution --------------------------------------------------


def _stack_scope_for_file(file_path: str) -> str:
    """Coarse heuristic: top directory of the affected file."""
    if not file_path:
        return "unknown"
    parts = Path(file_path).parts
    if len(parts) <= 1:
        return parts[0] if parts else "unknown"
    return "/".join(parts[:2])


def derive_composite_for_row(row: dict) -> dict:
    """Synthesize a 3-key composite_identity from a fix-ledger row.

    Joins to Stack Knowledge entries are not yet available (those live in stack
    files keyed by canonical composite_identity). The detector mirrors the
    canonicalization rules of `stack_knowledge_parser.compute_hash` so a row
    and an existing Stack Knowledge entry hash to the same value when their
    underlying root_cause / divergence / scope describe the same problem.
    """
    symptom = row.get("symptom") or row.get("desc") or row.get("description") or ""
    file_path = row.get("file") or ""
    severity = row.get("severity") or "warn"
    return {
        "root_cause_class": severity,
        "divergence_pattern": canonicalize_symptom(symptom),
        "stack_scope": _stack_scope_for_file(file_path),
    }


# --- Grouping --------------------------------------------------------------


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    text = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def group_by_composite(
    rows: Iterator[dict],
    *,
    since_days: int,
    now: datetime | None = None,
) -> dict[str, dict]:
    """Group rows by composite_identity_hash, dedup per (composite, day, run_id).

    Returns mapping of hash → {composite, occurrences:[row_summary], run_ids:set}.
    Only rows within the `since_days` window are retained (per-row).
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=since_days)
    groups: dict[str, dict] = {}
    seen_keys: set[tuple[str, str, str]] = set()

    for row in rows:
        ts = _parse_timestamp(row.get("timestamp"))
        if ts is not None and ts < cutoff:
            continue
        composite = derive_composite_for_row(row)
        chash = compute_hash(composite)
        run_id = row.get("run_id") or "<unknown>"
        day = (ts or now).date().isoformat()
        dedup_key = (chash, day, run_id)
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        bucket = groups.setdefault(
            chash,
            {
                "composite_identity": composite,
                "composite_identity_hash": chash,
                "run_ids": set(),
                "files": set(),
                "samples": [],
                "first_seen": ts,
                "last_seen": ts,
            },
        )
        bucket["run_ids"].add(run_id)
        if row.get("file"):
            bucket["files"].add(row["file"])
        bucket["samples"].append(
            {
                "run_id": run_id,
                "file": row.get("file"),
                "symptom": row.get("symptom"),
                "timestamp": row.get("timestamp"),
                "fix_id": row.get("fix_id"),
            }
        )
        if ts is not None:
            if bucket["first_seen"] is None or ts < bucket["first_seen"]:
                bucket["first_seen"] = ts
            if bucket["last_seen"] is None or ts > bucket["last_seen"]:
                bucket["last_seen"] = ts

    return groups


# --- Tier classification --------------------------------------------------


def is_advisory(group: dict) -> bool:
    return len(group["run_ids"]) >= ADVISORY_MIN_OCCURRENCES


def is_promotion_candidate(group: dict, *, now: datetime | None = None) -> bool:
    """Mirror stack_knowledge_audit.py raw→stable rule on ledger groups.

    Confidence proxy: count distinct run_ids divided by max(1, total samples).
    Oscillation proxy: not implemented here — the detector defers to the
    nightly audit for that signal. We over-file (issue is idempotent) rather
    than under-file.
    """
    occurrences = len(group["run_ids"])
    if occurrences < RAW_TO_STABLE_MIN_OCCURRENCE:
        return False
    samples = max(1, len(group["samples"]))
    confidence = occurrences / samples
    if confidence < RAW_TO_STABLE_MIN_CONFIDENCE:
        return False
    last = group.get("last_seen")
    first = group.get("first_seen")
    if last and first:
        span = last - first
        if span < timedelta(days=0):
            return False
        if span > timedelta(days=OSCILLATION_WINDOW_DAYS * 2):
            # The window is enormous; nightly audit handles the ≥90d lookback
            # and can correlate with `convergence-history.jsonl`. Defer.
            return False
    return True


# --- Output writers --------------------------------------------------------


def _serialize_group(group: dict, *, priority: str, reason: str) -> dict:
    first = group["first_seen"].isoformat() if group["first_seen"] else None
    last = group["last_seen"].isoformat() if group["last_seen"] else None
    return {
        "composite_identity": group["composite_identity"],
        "composite_identity_hash": group["composite_identity_hash"],
        "occurrences": len(group["run_ids"]),
        "sample_run_ids": sorted(group["run_ids"])[:10],
        "files_touched_union": sorted(group["files"])[:20],
        "first_seen": first,
        "last_seen": last,
        "priority": priority,
        "reason": reason,
    }


def write_advisory(
    group: dict, candidates_path: Path, *, since_days: int, dry_run: bool
) -> dict:
    record = _serialize_group(
        group,
        priority="high",
        reason=f"recurrence-detector:>={ADVISORY_MIN_OCCURRENCES}/{since_days}d",
    )
    record["written_at"] = datetime.now(timezone.utc).isoformat()
    if dry_run:
        return record
    line = json.dumps(record, ensure_ascii=False) + "\n"
    candidates_path.parent.mkdir(parents=True, exist_ok=True)
    with candidates_path.open("a", encoding="utf-8") as fh:
        fh.write(line)
    return record


# --- GitHub issue filing ---------------------------------------------------


def _gh_available() -> bool:
    try:
        result = subprocess.run(
            ["gh", "--version"], capture_output=True, text=True, timeout=10
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _existing_issue_for(composite_hash: str) -> bool:
    try:
        result = subprocess.run(
            [
                "gh",
                "issue",
                "list",
                "--label",
                "pattern-graduation-stable",
                "--state",
                "open",
                "--search",
                composite_hash,
                "--json",
                "number",
                "--limit",
                "5",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    try:
        issues = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return False
    return bool(issues)


def file_promotion_issue(group: dict, *, dry_run: bool) -> dict:
    chash = group["composite_identity_hash"]
    if _existing_issue_for(chash):
        return {"filed": False, "reason": "existing-open-issue", "composite_hash": chash}
    files = sorted(group["files"])[:5]
    title = (
        f"[pattern-graduation-stable] {chash} recurring: "
        f"{', '.join(files) if files else '(no files)'}"
    )
    body_lines = [
        "Recurrence detector (RMG v2 Layer 4) reached the canonical promotion "
        "threshold for this composite_identity.",
        "",
        f"composite_identity_hash: {chash}",
        f"composite_identity: `{json.dumps(group['composite_identity'], ensure_ascii=False)}`",
        f"distinct run_ids: {len(group['run_ids'])}",
        f"sample run_ids: {sorted(group['run_ids'])[:10]}",
        f"files touched (union): {sorted(group['files'])[:20]}",
        "",
        "Maintainer action: review the linked Stack Knowledge entry and decide "
        "whether to promote `maturity: raw` → `maturity: stable` per "
        "TEMPLATE.md. The detector itself never mutates stack knowledge.",
    ]
    body = "\n".join(body_lines)
    if dry_run:
        return {"filed": False, "reason": "dry-run", "title": title}
    if not _gh_available():
        return {"filed": False, "reason": "gh-unavailable"}
    try:
        result = subprocess.run(
            [
                "gh",
                "issue",
                "create",
                "--label",
                "pattern-graduation-stable",
                "--title",
                title,
                "--body",
                body,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return {"filed": False, "reason": "gh-timeout"}
    if result.returncode != 0:
        return {"filed": False, "reason": f"gh-error: {result.stderr.strip()}"}
    return {"filed": True, "url": result.stdout.strip(), "title": title}


# --- Main ------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--advisory-only", action="store_true")
    parser.add_argument("--promotion-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--since-days", type=int, default=ADVISORY_WINDOW_DAYS_DEFAULT)
    parser.add_argument("--project-dir", default=os.environ.get("PROJECT_DIR"))
    args = parser.parse_args(argv)

    if args.advisory_only and args.promotion_only:
        print("FAIL: --advisory-only and --promotion-only are mutually exclusive", file=sys.stderr)
        return 3

    project_dir = Path(args.project_dir or os.getcwd()).resolve()
    ledger_path = project_dir / ".runs" / "fix-ledger.jsonl"
    candidates_path = project_dir / ".runs" / "recurrence-candidates.jsonl"
    lock_path = project_dir / ".runs" / "recurrence-candidates.jsonl.lock"

    try:
        # scope: cross-run-by-design — recurrence detection groups across run_ids by design
        rows = list(load_fix_ledger(ledger_path))
    except SchemaError as exc:
        print(f"FAIL: fix-ledger.jsonl schema error: {exc}", file=sys.stderr)
        return 3

    if not rows:
        return 0

    groups = group_by_composite(rows, since_days=args.since_days)

    advisory_records: list[dict] = []
    promotion_records: list[dict] = []
    do_advisory = not args.promotion_only
    do_promotion = not args.advisory_only

    try:
        with _exclusive_lock(lock_path):
            for chash, group in groups.items():
                if do_advisory and is_advisory(group):
                    advisory_records.append(
                        write_advisory(
                            group,
                            candidates_path,
                            since_days=args.since_days,
                            dry_run=args.dry_run,
                        )
                    )
                if do_promotion and is_promotion_candidate(group):
                    promotion_records.append(
                        file_promotion_issue(group, dry_run=args.dry_run)
                    )
    except _LockContention as exc:
        print(f"WARN: recurrence-detector lock contention on {exc}", file=sys.stderr)
        return 2

    summary = {
        "advisory_emitted": len(advisory_records),
        "promotion_attempted": len(promotion_records),
        "promotion_filed": sum(1 for r in promotion_records if r.get("filed")),
        "groups_total": len(groups),
        "rows_total": len(rows),
        "since_days": args.since_days,
        "dry_run": args.dry_run,
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
