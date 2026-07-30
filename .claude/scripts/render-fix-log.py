#!/usr/bin/env python3
"""Render .runs/fix-log.md from .runs/fix-ledger.jsonl.

AOC v1 FLS v1 renderer. fix-log.md is the human-readable diary;
fix-ledger.jsonl is authoritative. This renderer is the only writer to
fix-log.md in AOC v1 — gated at runtime by fix-ledger-write-guard.sh.

Deterministic ordering: by (batch_id, fix_index-from-fix_id).

Output format preserved for backward compat with regex consumers during
the transitional dual-check period:
    Fix (<agent>): `<file>` — Symptom: <symptom> — Fix: <action>

Usage:
    python3 .claude/scripts/render-fix-log.py [--dry-run]

Exit 0 on success; exit non-zero on fatal error.
"""
import argparse
import json
import os
import sys
import tempfile


LEDGER_PATH = ".runs/fix-ledger.jsonl"
FIX_LOG_PATH = ".runs/fix-log.md"


def parse_ledger(path=LEDGER_PATH):
    if not os.path.isfile(path):
        return []
    rows = []
    with open(path) as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError:
                continue
    return rows


def fix_index_from_id(fix_id):
    try:
        return int(str(fix_id).rsplit(":", 1)[-1])
    except (ValueError, TypeError):
        return 0


def render_row(row):
    agent = row.get("agent", "<unknown-agent>")
    file_ = row.get("file") or "<unknown-file>"
    if row.get("entry_type") == "template-edit":
        before = (row.get("before_hash") or "?")[:8]
        after = (row.get("after_hash") or "?")[:8]
        return f"⚠️ Template patch ({agent}): `{file_}` ({before} → {after})"
    symptom = row.get("symptom") or "<no symptom>"
    fix = row.get("fix") or "<no fix>"
    # EARC slice 1: distinguish lead-transcribed-fix rows. These were
    # written by the lead via write-recovery-trace.sh --fixes-json after
    # an agent crashed; the lead anchored them to external evidence
    # (build-result.json) and validate-recovery.sh stamped recovery_validated.
    if row.get("lead_transcribed") is True:
        return (
            f"📝 Lead-transcribed ({agent}, recovery): `{file_}` "
            f"— Symptom: {symptom} — Fix: {fix}"
        )
    return f"Fix ({agent}): `{file_}` — Symptom: {symptom} — Fix: {fix}"


def render(rows):
    rows_sorted = sorted(
        rows, key=lambda r: (str(r.get("batch_id", "")), fix_index_from_id(r.get("fix_id")))
    )
    lines = ["# Fix Log", ""]
    for r in rows_sorted:
        lines.append(render_row(r))
    return "\n".join(lines) + "\n"


def atomic_write(content, path=FIX_LOG_PATH):
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=".fix-log-", suffix=".md.tmp", dir=parent
    )
    try:
        with os.fdopen(tmp_fd, "w") as f:
            f.write(content)
        os.rename(tmp_path, path)
    except Exception:
        if os.path.isfile(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise


def main():
    ap = argparse.ArgumentParser(
        description="Render fix-log.md from fix-ledger.jsonl (AOC v1 FLS v1)"
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="Print rendered output to stdout without writing")
    args = ap.parse_args()

    rows = parse_ledger()
    content = render(rows)

    if args.dry_run:
        sys.stdout.write(content)
        return 0

    atomic_write(content)
    print(f"render-fix-log: wrote {len(rows)} entries to {FIX_LOG_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
