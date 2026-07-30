"""Shared atomic appender for .runs/lead-deviation-log.jsonl.

Closes #1431 reliability gap: the prior `_log_deviation()` callers in
bound-by-coverage-provider.py / anomaly-audit-evidence.py /
user-approval-evidence-validator.py used direct `open(path, "a")` with
silent exception-swallowing. This module:

  - centralizes the appender so the writer contract is in one place
  - uses POSIX O_APPEND (atomic for writes < PIPE_BUF; our entries ~500B)
  - fsyncs before close so writes survive process crash
  - on exception → logs to .runs/lead-deviation-log.write-failures.jsonl
    so silent failures become observer-visible (consumed by
    enumerate-pending-retrospective-findings.py 7th candidate source)
  - stamps every entry with `_meta.schema_version = "prose-gates-v1.0"`

Public API:

    append(payload: dict) -> bool
        Returns True on success; False on failure (failure path also wrote
        to write-failures.jsonl when possible).
"""

from __future__ import annotations

import datetime
import json
import os
import sys

__all__ = ["append"]

DEVIATION_LOG_PATH = ".runs/lead-deviation-log.jsonl"
WRITE_FAILURES_PATH = ".runs/lead-deviation-log.write-failures.jsonl"
SCHEMA_VERSION = "prose-gates-v1.0"


def _ensure_dir(path: str) -> None:
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)


def _stamp_meta(payload: dict) -> dict:
    """Add _meta.schema_version. Caller's existing _meta keys preserved."""
    meta = payload.setdefault("_meta", {})
    if isinstance(meta, dict):
        meta.setdefault("schema_version", SCHEMA_VERSION)
    return payload


def _log_failure(original: dict, exc: Exception) -> None:
    """Best-effort write to write-failures.jsonl. If even this fails, print
    to stderr so at least the operator sees the failure."""
    try:
        _ensure_dir(WRITE_FAILURES_PATH)
        entry = {
            "original_payload": original,
            "exception": f"{type(exc).__name__}: {exc}",
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        with open(WRITE_FAILURES_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
            try:
                f.flush()
                os.fsync(f.fileno())
            except OSError:
                pass
    except Exception as e2:
        print(
            f"FATAL: append_deviation_log: primary write failed AND "
            f"write-failures log also failed. Primary: {exc}. Failures-log: {e2}",
            file=sys.stderr,
        )


def append(payload: dict) -> bool:
    """Append one JSONL line to .runs/lead-deviation-log.jsonl atomically.

    POSIX O_APPEND is atomic for single writes < PIPE_BUF (~4KB on
    macOS/Linux). Our deviation entries are ~500B so atomicity holds
    across concurrent appenders.

    Adds payload['_meta']['schema_version'] = "prose-gates-v1.0" if not set.

    Returns True on success, False on failure (failure path writes to
    write-failures.jsonl).
    """
    if not isinstance(payload, dict):
        _log_failure(
            {"raw": repr(payload)},
            TypeError(f"payload must be dict, got {type(payload).__name__}"),
        )
        return False

    stamped = _stamp_meta(dict(payload))  # shallow copy so caller's dict isn't mutated

    try:
        _ensure_dir(DEVIATION_LOG_PATH)
        with open(DEVIATION_LOG_PATH, "a") as f:
            f.write(json.dumps(stamped) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return True
    except Exception as e:
        _log_failure(stamped, e)
        return False
