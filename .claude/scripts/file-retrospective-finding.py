#!/usr/bin/env python3
"""Sole sanctioned writer for retrospective-driven [observe] issue filing.

Issue context: #1276 — retrospective filings have failed 5 times because
the lead either skipped the filing prose entirely OR fabricated JSON
fields. This script is the only allowed path for converting a candidate
from .runs/retrospective-pending-findings.json into a real GitHub issue:
  1. Validates the candidate_id matches a pending finding
  2. Calls `gh issue create --label observation`
  3. Appends to .runs/retrospective-filed-findings.json

Why a separate script: a coherence rule pins the writer set
(template-coherence-rules.json), so future PRs that try to file via prose
prompts (the failure mode of #1066/#1226/#1258/#1270) get caught by the
linter. Lead invokes this script via Bash; provenance is captured in
.runs/agent-spawn-log.jsonl with hook=retrospective-filing-script.

Dedup: before filing, search the template repo for an open observation
with same (kind, key) — if found, COMMENT on it instead of creating.

Usage:
    python3 .claude/scripts/file-retrospective-finding.py \
        --candidate-id <12-char hash> \
        --title "<imperative title>" \
        --body-file <path>

Or interactive (lead-friendly):
    python3 .claude/scripts/file-retrospective-finding.py \
        --candidate-id <hash> \
        --title "<title>" \
        --body "<inline body>"

Exit 0 on success, 1 on validation/filing failure.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
from typing import Optional

TEMPLATE_REPO = "magpiexyz-lab/mvp-template"
PENDING_PATH = ".runs/retrospective-pending-findings.json"
FILED_PATH = ".runs/retrospective-filed-findings.json"


def _load_pending() -> list[dict]:
    if not os.path.isfile(PENDING_PATH):
        print(
            f"ERROR: {PENDING_PATH} not found — run "
            f"enumerate-pending-retrospective-findings.py first",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        return json.load(open(PENDING_PATH)).get("candidates") or []
    except Exception as e:
        print(f"ERROR: cannot parse {PENDING_PATH}: {e}", file=sys.stderr)
        sys.exit(1)


def _load_filed() -> dict:
    if not os.path.isfile(FILED_PATH):
        return {"schema_version": 2, "filed": []}
    try:
        return json.load(open(FILED_PATH))
    except Exception:
        return {"schema_version": 2, "filed": []}


def _save_filed(d: dict) -> None:
    os.makedirs(".runs", exist_ok=True)
    with open(FILED_PATH, "w") as f:
        json.dump(d, f, indent=2)


def _gh_dedup_check(title_basename: str) -> Optional[str]:
    """Return existing issue URL if a duplicate observation exists."""
    try:
        r = subprocess.run(
            [
                "gh", "issue", "list",
                "--repo", TEMPLATE_REPO,
                "--label", "observation",
                "--search", f"[observe] {title_basename}",
                "--state", "open",
                "--limit", "5",
                "--json", "url,title,number",
            ],
            capture_output=True, text=True, timeout=20,
        )
        if r.returncode != 0:
            return None
        items = json.loads(r.stdout or "[]")
        for it in items:
            if title_basename.lower() in (it.get("title") or "").lower():
                return it.get("url")
    except Exception:
        pass
    return None


def _gh_create_issue(title: str, body: str) -> Optional[str]:
    try:
        r = subprocess.run(
            [
                "gh", "issue", "create",
                "--repo", TEMPLATE_REPO,
                "--title", title,
                "--label", "observation",
                "--body", body,
            ],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            print(f"ERROR: gh issue create failed: {r.stderr}", file=sys.stderr)
            return None
        url = (r.stdout or "").strip()
        return url if url.startswith("https://") else None
    except Exception as e:
        print(f"ERROR: gh issue create exception: {e}", file=sys.stderr)
        return None


def _gh_comment(issue_url: str, body: str) -> bool:
    try:
        # Extract issue number from URL: .../issues/<num>
        num = issue_url.rstrip("/").rsplit("/", 1)[-1]
        r = subprocess.run(
            [
                "gh", "issue", "comment", num,
                "--repo", TEMPLATE_REPO,
                "--body", body,
            ],
            capture_output=True, text=True, timeout=20,
        )
        return r.returncode == 0
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="File a retrospective finding as a GitHub issue")
    ap.add_argument("--candidate-id", required=True, help="12-char candidate_id from retrospective-pending-findings.json")
    ap.add_argument("--title", required=True, help="Issue title (imperative form)")
    body_group = ap.add_mutually_exclusive_group(required=True)
    body_group.add_argument("--body", help="Inline issue body")
    body_group.add_argument("--body-file", help="Path to file containing issue body")
    ap.add_argument("--auto-filed", action="store_true",
                    help="Mark this filing as auto-generated (no LLM evaluation)")
    args = ap.parse_args()

    # Validate candidate exists in pending
    pending = _load_pending()
    candidate = next((c for c in pending if c.get("candidate_id") == args.candidate_id), None)
    if candidate is None:
        print(
            f"ERROR: candidate_id {args.candidate_id!r} not in {PENDING_PATH}. "
            f"Available: {[c.get('candidate_id') for c in pending][:5]}{'...' if len(pending)>5 else ''}",
            file=sys.stderr,
        )
        return 1

    # Check already filed (idempotency)
    filed = _load_filed()
    for entry in filed.get("filed") or []:
        if entry.get("candidate_id") == args.candidate_id:
            print(f"OK: candidate {args.candidate_id} already filed at {entry.get('issue_url')} (idempotent)")
            return 0

    # Read body
    if args.body_file:
        if not os.path.isfile(args.body_file):
            print(f"ERROR: --body-file {args.body_file!r} not found", file=sys.stderr)
            return 1
        with open(args.body_file) as f:
            body = f.read()
    else:
        body = args.body

    # Build title — auto-prefix if missing
    title = args.title
    if not title.startswith("[observe]"):
        title = f"[observe] {title}"

    # Dedup
    title_basename = title.replace("[observe]", "").strip()[:60]
    dup_url = _gh_dedup_check(title_basename)
    if dup_url:
        comment_body = (
            f"Re-observed in run via retrospective candidate {args.candidate_id}.\n\n"
            f"---\n{body}"
        )
        if _gh_comment(dup_url, comment_body):
            print(f"OK: candidate {args.candidate_id} → commented on existing {dup_url}")
            filed.setdefault("filed", []).append({
                "candidate_id": args.candidate_id,
                "issue_url": dup_url,
                "action": "commented-on-duplicate",
                "filed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "auto_filed": args.auto_filed,
            })
            _save_filed(filed)
            return 0
        else:
            print(f"WARN: dedup found {dup_url} but comment failed; proceeding to create new", file=sys.stderr)

    # Create new issue
    url = _gh_create_issue(title, body)
    if url is None:
        return 1

    filed.setdefault("filed", []).append({
        "candidate_id": args.candidate_id,
        "issue_url": url,
        "action": "created-new",
        "filed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "auto_filed": args.auto_filed,
    })
    _save_filed(filed)
    print(f"OK: candidate {args.candidate_id} → filed at {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
