#!/usr/bin/env python3
"""AOC v1.2 — Produce .runs/observation-evidence.json envelope.

Closes #1259: observer evidence-set was too narrow (only diffs + fix-log).
The envelope is the unified input contract observer reads — every present
canonical evidence family is referenced.

Single source of truth for the family list:
  .claude/scripts/lib/observer_evidence_families.py:CANONICAL_EVIDENCE_FAMILIES

The envelope is written via the canonical writer
.claude/scripts/lib/write-gate-artifact.sh (which stamps {skill, run_id,
written_at}). Direct file writes to .runs/observation-evidence.json are
blocked by .claude/hooks/gate-artifact-write-gate.sh.

Aggregator references (NOT re-aggregations): the envelope points at paths
produced by upstream aggregators. .runs/hook-friction-summary.json is
produced by aggregate-hook-friction.py; .runs/fix-ledger.jsonl by
write-fix-ledger.py; .runs/fix-log.md by render-fix-log.py.

Lead-skipped fixer traces (PR3) are surfaced separately in
`skipped_fixer_traces` for observer convenience (it can correlate them
with the audit-skip path without re-walking the agent-traces/ dir).

template_recommendations[] is flattened from agent traces per the AOC v1.2
schema bump (PR1 A1 added the optional field to verdict_agents_schema).

Usage:
  python3 .claude/scripts/write-observation-evidence.py
      [--runs-dir <dir>]   default: .runs
      [--source-run-id <ID> --source-skill <NAME>]   AOC v1.2 post-completion
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure local lib/ on sys.path.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "lib"))

from observer_evidence_families import (  # noqa: E402
    CANONICAL_EVIDENCE_FAMILIES,
    list_present_families,
)


def _git_branch(project_dir: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(project_dir),
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return out.strip()
    except Exception:
        return ""


def _flatten_template_recommendations(agent_trace_paths: list[str], runs_dir: Path) -> list[dict]:
    """Walk agent traces; for each that has `template_recommendations[]`,
    flatten into one list with `agent` field added per entry."""
    out: list[dict] = []
    for rel in agent_trace_paths:
        full = runs_dir / rel
        try:
            t = json.load(open(full))
        except Exception:
            continue
        recs = t.get("template_recommendations") or []
        if not isinstance(recs, list):
            continue
        agent = t.get("agent") or os.path.basename(full).replace(".json", "")
        for r in recs:
            if isinstance(r, dict):
                row = dict(r)
                row.setdefault("agent", agent)
                out.append(row)
    return out


def _find_skipped_fixer_traces(agent_trace_paths: list[str], runs_dir: Path) -> list[str]:
    """Return paths (relative to runs_dir) of any agent trace whose
    provenance == lead-skipped (PR3 audit-only sanctioned-skip)."""
    out: list[str] = []
    for rel in agent_trace_paths:
        full = runs_dir / rel
        try:
            t = json.load(open(full))
        except Exception:
            continue
        if t.get("provenance") == "lead-skipped":
            out.append(rel)
    return out


def _count_lead_fix_ledger_rows(fix_ledger_path: Path | None) -> int:
    if fix_ledger_path is None or not fix_ledger_path.is_file():
        return 0
    n = 0
    try:
        with fix_ledger_path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("provenance") == "lead":
                    n += 1
    except OSError:
        return 0
    return n


def build_envelope(runs_dir: Path) -> dict:
    """Construct the envelope dict; does NOT write it."""
    present = list_present_families(str(runs_dir))

    # Initialize all schema fields to typed defaults so the envelope shape
    # is consistent (the F3 lint asserts schema-field presence — we want
    # absent-on-disk families to surface as `null` / `[]`, not omitted keys).
    envelope: dict = {"schema_version": 1}
    for _pattern, field, kind in CANONICAL_EVIDENCE_FAMILIES:
        envelope[field] = None if kind == "single" else []

    agent_trace_paths: list[str] = []
    fix_ledger_rel: str | None = None

    for pattern, field, kind, matches in present:
        if kind == "single":
            envelope[field] = ".runs/" + matches[0]
            if pattern == "fix-ledger.jsonl":
                fix_ledger_rel = matches[0]
        else:
            envelope[field] = [".runs/" + m for m in matches]
            if pattern == "agent-traces/*.json":
                agent_trace_paths = matches

    # Derived signals.
    envelope["fix_ledger_lead_fix_count"] = _count_lead_fix_ledger_rows(
        runs_dir / fix_ledger_rel if fix_ledger_rel else None
    )
    envelope["template_recommendations"] = _flatten_template_recommendations(
        agent_trace_paths, runs_dir
    )
    envelope["skipped_fixer_traces"] = [
        ".runs/" + p
        for p in _find_skipped_fixer_traces(agent_trace_paths, runs_dir)
    ]

    return envelope


def write_envelope(
    envelope: dict,
    runs_dir: Path,
    project_dir: Path,
    source_run_id: str = "",
    source_skill: str = "",
) -> int:
    """Write the envelope via the canonical writer
    .claude/scripts/lib/write-gate-artifact.sh."""
    target = runs_dir / "observation-evidence.json"
    writer = project_dir / ".claude/scripts/lib/write-gate-artifact.sh"
    if not writer.is_file():
        print(f"ERROR: write-observation-evidence.py — canonical writer not found at {writer}", file=sys.stderr)
        return 1

    payload = json.dumps(envelope, indent=2)
    args = ["bash", str(writer), "--path", str(target.relative_to(project_dir)), "--payload", payload]
    if source_run_id:
        args += ["--source-run-id", source_run_id]
    if source_skill:
        args += ["--source-skill", source_skill]

    try:
        subprocess.check_call(args, cwd=str(project_dir))
    except subprocess.CalledProcessError as exc:
        print(f"ERROR: write-observation-evidence.py — canonical writer failed: {exc}", file=sys.stderr)
        return exc.returncode or 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else "")
    parser.add_argument("--runs-dir", default=".runs",
                        help="path to .runs/ (relative to project_dir or absolute)")
    parser.add_argument("--source-run-id", default="",
                        help="AOC v1.2 post-completion identity override (paired with --source-skill)")
    parser.add_argument("--source-skill", default="",
                        help="AOC v1.2 post-completion identity override (paired with --source-run-id)")
    parser.add_argument("--project-dir", default=os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    parser.add_argument("--print-only", action="store_true",
                        help="print the envelope to stdout instead of writing it (debug)")
    args = parser.parse_args(argv)

    project_dir = Path(args.project_dir).resolve()
    runs_dir = Path(args.runs_dir)
    if not runs_dir.is_absolute():
        runs_dir = project_dir / runs_dir
    if not runs_dir.is_dir():
        print(f"ERROR: write-observation-evidence.py — runs-dir {runs_dir} does not exist", file=sys.stderr)
        return 1

    envelope = build_envelope(runs_dir)
    # Stamp non-canonical-writer fields the writer would otherwise overwrite
    # (run_id/skill/written_at). The writer is authoritative for those.
    envelope["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    envelope["branch"] = _git_branch(project_dir)

    if args.print_only:
        print(json.dumps(envelope, indent=2))
        return 0

    return write_envelope(envelope, runs_dir, project_dir, args.source_run_id, args.source_skill)


if __name__ == "__main__":
    sys.exit(main())
