#!/usr/bin/env python3
"""verify-design-critic-post-fix-respawn.py — lifecycle-finalize Step 4.7
gate that enforces the #1274 per-page re-evaluation contract.

When the lead applies a shared-component fix during state-3a Stage 1b
OR ux-journeyer modifies a UI file in state-3c, the per-page
design-critic-<page>.json trace becomes stale. The verify pipeline
protocol requires the lead to re-spawn design-critic for every affected
page (writing design-critic-<page>--epoch<N>.json with verdict pass or
fixed). This gate cross-checks that requirement:

For each per-page design-critic trace whose `shared_issues[*].file`
intersects fix-ledger lead-fix entries, OR whose `reviewed_files`
intersect ux-journeyer's `fixes_applied[*].file`, assert that at least
one matching `design-critic-<page>--epoch<N>.json` (N >= 1) exists with
status=completed AND verdict in {pass, fixed}.

Exits 0 when no re-spawn obligation exists OR all obligations met.
Exits 1 when any obligation is unmet, with a diagnostic message
listing each missing page.

Wired from .claude/scripts/lifecycle-finalize.sh as Step 4.7.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path

EPOCH_RE = re.compile(r"--epoch(\d+)\.json$")


def _load_json(path: str) -> dict | None:
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _is_per_page_base_trace(basename: str) -> bool:
    """True for the original per-page trace (no --epoch suffix)."""
    if not basename.startswith("design-critic-"):
        return False
    if basename in ("design-critic.json", "design-critic-shared.json"):
        return False
    return EPOCH_RE.search(basename) is None


def _page_key(data: dict | None, path: str) -> str:
    if isinstance(data, dict):
        for k in ("page", "weakest_page"):
            v = data.get(k)
            if isinstance(v, str) and v:
                return v
    base = os.path.basename(path)
    if base.endswith(".json"):
        base = base[:-5]
    if base.startswith("design-critic-"):
        base = base[len("design-critic-"):]
    return EPOCH_RE.sub("", base)


def _post_fix_traces_for_page(traces_dir: str, page: str) -> list[dict]:
    """Return parsed --epoch>=1 traces matching this page key."""
    out: list[dict] = []
    for path in glob.glob(os.path.join(traces_dir, "design-critic-*.json")):
        bn = os.path.basename(path)
        m = EPOCH_RE.search(bn)
        if not m:
            continue
        try:
            epoch = int(m.group(1))
        except (TypeError, ValueError):
            continue
        if epoch < 1:
            continue
        data = _load_json(path)
        if data is None:
            continue
        if _page_key(data, path) != page:
            continue
        out.append(data)
    return out


def _ledger_lead_fix_files(ledger_path: str, run_id: str) -> set[str]:
    if not os.path.isfile(ledger_path):
        return set()
    fixed: set[str] = set()
    with open(ledger_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if run_id and e.get("run_id") != run_id:
                continue
            if e.get("provenance") in ("lead", "lead-on-behalf"):
                fp = e.get("file")
                if fp:
                    fixed.add(fp)
    return fixed


def _ux_journeyer_ui_files(traces_dir: str) -> set[str]:
    """Return .tsx/.jsx files ux-journeyer modified.

    #1379 G2: only iterate `fixes` (list[dict] of fix records). The legacy
    `fixes_applied` iteration was a schema drift — ux-journeyer.md documents
    `fixes_applied` as an integer count, not a list. Crash when an agent
    obeyed the documented schema: `'int' object is not iterable`. The `fixes`
    field already enumerates file paths; the `fixes_applied` iteration was
    redundant.
    """
    path = os.path.join(traces_dir, "ux-journeyer.json")
    data = _load_json(path)
    if not data:
        return set()
    out: set[str] = set()
    for fix in data.get("fixes", []) or []:
        fp = fix.get("file") if isinstance(fix, dict) else None
        if isinstance(fp, str) and (fp.endswith(".tsx") or fp.endswith(".jsx")):
            out.add(fp)
    return out


def _trace_reviewed_files(data: dict) -> set[str]:
    out: set[str] = set()
    for ev in data.get("per_page_review_evidence", []) or []:
        if isinstance(ev, dict):
            for k in ("reviewed_file", "file"):
                v = ev.get(k)
                if isinstance(v, str):
                    out.add(v)
    for v in data.get("reviewed_files", []) or []:
        if isinstance(v, str):
            out.add(v)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Step 4.7 gate — verify per-page design-critic re-spawn obligations."
    )
    parser.add_argument(
        "--project-dir",
        default=os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()),
    )
    args = parser.parse_args(argv)
    project_dir = Path(args.project_dir).resolve()
    traces_dir = str(project_dir / ".runs" / "agent-traces")
    ledger_path = str(project_dir / ".runs" / "fix-ledger.jsonl")

    # Read run_id from verify-context (the skill that owns this gate path).
    run_id = ""
    ctx_path = project_dir / ".runs" / "verify-context.json"
    if ctx_path.is_file():
        try:
            run_id = (json.loads(ctx_path.read_text()) or {}).get("run_id", "") or ""
        except Exception:
            pass

    fixed_files = _ledger_lead_fix_files(ledger_path, run_id)
    ux_ui_files = _ux_journeyer_ui_files(traces_dir)

    # Build the set of pages whose latest base trace is stale because:
    # (a) shared_issues[*].file ∈ fixed_files, OR
    # (b) reviewed_files ∩ ux_ui_files non-empty.
    obligations: dict[str, list[str]] = {}
    if not (fixed_files or ux_ui_files):
        # Nothing to gate.
        return 0

    for path in glob.glob(os.path.join(traces_dir, "design-critic-*.json")):
        bn = os.path.basename(path)
        if not _is_per_page_base_trace(bn):
            continue
        data = _load_json(path)
        if not data:
            continue
        page = _page_key(data, path)
        reasons: list[str] = []
        if fixed_files:
            for si in data.get("shared_issues", []) or []:
                if isinstance(si, dict) and si.get("file") in fixed_files:
                    reasons.append(f"shared_issues[file={si.get('file')!r}] matches fix-ledger lead-fix")
                    break
        if ux_ui_files:
            reviewed = _trace_reviewed_files(data)
            overlap = reviewed & ux_ui_files
            if overlap:
                reasons.append(
                    f"reviewed_files {sorted(overlap)} overlap ux-journeyer fixes_applied"
                )
        if reasons:
            obligations[page] = reasons

    if not obligations:
        return 0

    # For each obligation, look for at least one --epoch>=1 trace with
    # status=completed AND verdict in {pass, fixed}.
    missing: list[str] = []
    for page, reasons in sorted(obligations.items()):
        post_fix = _post_fix_traces_for_page(traces_dir, page)
        ok = any(
            (t.get("status") == "completed"
             and t.get("verdict") in ("pass", "fixed"))
            for t in post_fix
        )
        if not ok:
            missing.append(
                f"  - page={page!r}: {'; '.join(reasons)}; "
                f"no design-critic-{page}--epoch<N>.json with verdict in (pass, fixed) and status=completed"
            )

    if not missing:
        return 0

    sys.stderr.write(
        "BLOCK: Step 4.7 — design-critic post-fix re-spawn obligations unmet.\n"
        "After lead-applied shared-component fixes (state-3a Stage 1b) or\n"
        "ux-journeyer UI fixes (state-3c), every affected per-page design-critic\n"
        "trace must be superseded by a re-evaluation epoch trace with verdict\n"
        "pass or fixed. Missing:\n"
    )
    sys.stderr.write("\n".join(missing) + "\n")
    sys.stderr.write(
        "Re-run the affected design-critic agents per state-3a Stage 1b step 5\n"
        "(or state-3c step 7), then re-run merge-design-critic-traces.py.\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
