#!/usr/bin/env python3
"""
resolve-snippet-precheck.py — STATE 3 Step 0 verification_snippet pre-check.

For a given (issue_number, cited_file) pair, scan all Stack Knowledge entries
that live in the cited file (or files under the same stack-scope path), and
for each entry with a `verification_snippet`, run the snippet and branch on
the trinary exit code.

This is the M5 (post-PR #1399 retro) implementation that replaces the
hand-wave hash-derivation pseudo-code with a deterministic file-path-scoped
scan. The original Step 0 prose used unspecified `composite_identity_hash`
derivation that LLM paraphrasing would never reproduce reliably.

First-principles design: stack_scope (file path) is deterministic from the
issue's cited file; root_cause_class and divergence_pattern are not. So we
scope by file path and let the SNIPPET'S EXIT CODE be the answer — no hash
matching needed.

Trinary contract (per SK entry's verification_snippet):
  exit 0 → bug present (proceed with reproduction)
  exit 1 → bug ABSENT (close issue as Stale)
  exit 2 → preconditions not met (skip this snippet, try next)
  exit other → snippet broken (warn, skip)

Snippet execution is sandboxed by:
  - Timeout: 60 seconds (configurable via env)
  - Working dir: ephemeral mktemp (snippets must use $(mktemp -d) for any
    package installs; the linter at scripts/lint-verification-snippets.py
    rejects user-specific paths but does NOT enforce mktemp usage)

Usage (called by lead at STATE 3 Step 0):
  python3 .claude/scripts/resolve-snippet-precheck.py \
    --issue 1389 \
    --cited-file .claude/stacks/analytics/posthog.md

Output:
  - Writes .runs/resolve-snippet-precheck-<issue>.json with per-entry results
  - Exits 0 always (the lead branches on the artifact contents)

Artifact schema:
  {
    "issue": <int>,
    "cited_file": "<path>",
    "stack_scope_searched": "<scope>",
    "entries_scanned": <int>,
    "snippets_run": <int>,
    "results": [
      {"entry_id": "...", "exit_code": <int>, "verdict": "present|absent|preconditions_not_met|broken", "stdout_excerpt": "...", "stderr_excerpt": "..."}
    ],
    "verdict": "proceed|close_as_stale|inconclusive"
  }

Verdicts:
  - "proceed" — at least one snippet returned exit 0 (bug present)
  - "close_as_stale" — at least one snippet returned exit 1 AND zero exit 0 (bug absent)
  - "inconclusive" — no matching snippets, or all returned exit 2/other (proceed normally)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

DEFAULT_TIMEOUT_SEC = 60
OUTPUT_DIR = REPO_ROOT / ".runs"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue", type=int, required=True, help="Issue number to evaluate")
    parser.add_argument(
        "--cited-file",
        required=True,
        help="Repo-relative path to the file cited in the issue (used to scope SK search)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.environ.get("RESOLVE_SNIPPET_TIMEOUT", DEFAULT_TIMEOUT_SEC)),
        help=f"Per-snippet timeout in seconds (default {DEFAULT_TIMEOUT_SEC})",
    )
    args = parser.parse_args(argv)

    try:
        from stack_knowledge_parser import (
            iter_stack_knowledge_files,
            parse_stack_knowledge_file,
        )
    except ImportError as e:
        print(f"FAIL: cannot import stack_knowledge_parser: {e}", file=sys.stderr)
        return 2

    # Derive stack_scope from cited_file. Examples:
    #   .claude/stacks/analytics/posthog.md → "analytics/posthog"
    #   .claude/skills/bootstrap/state-8.md → "skills/bootstrap" (no SK entries here typically)
    # We scope the search to SK entries whose own file path matches the cited file
    # (most common case) OR whose stack_scope field matches the derived scope.
    #
    # Path normalization: strip leading "./" only (not all dots — the canonical
    # SK file paths start with ".claude/", which we must preserve for matching).
    def _norm(p: str) -> str:
        return p[2:] if p.startswith("./") else p

    cited_file_normalized = _norm(args.cited_file)

    # Derive a stack_scope candidate from the cited file path
    stack_scope_candidate = ""
    parts = cited_file_normalized.split("/")
    if len(parts) >= 4 and parts[0] == ".claude" and parts[1] == "stacks":
        # .claude/stacks/<category>/<file>.md → "<category>/<file_without_ext>"
        stack_scope_candidate = f"{parts[2]}/{Path(parts[3]).stem}"

    results = []
    entries_scanned = 0
    snippets_run = 0

    for sf_path in iter_stack_knowledge_files():
        # Match scope: either the cited file IS the SK file, or stack_scope matches
        sf_normalized = _norm(sf_path)
        scope_match = sf_normalized == cited_file_normalized

        try:
            entries = parse_stack_knowledge_file(sf_path)
        except Exception:
            continue

        for entry in entries:
            entries_scanned += 1
            entry_scope = entry.get("composite_identity", {}).get("stack_scope", "")
            if not scope_match and stack_scope_candidate and entry_scope != stack_scope_candidate:
                continue
            if not scope_match and not stack_scope_candidate:
                continue  # No way to scope; skip

            snippet = entry.get("verification_snippet")
            if not snippet or not isinstance(snippet, str):
                continue

            entry_id = entry.get("id", "<unknown>")

            # Sandbox: ephemeral working dir
            try:
                proc = subprocess.run(
                    ["bash", "-c", snippet],
                    capture_output=True,
                    text=True,
                    timeout=args.timeout,
                    cwd=str(REPO_ROOT),
                )
                exit_code = proc.returncode
                stdout_excerpt = (proc.stdout or "")[:500]
                stderr_excerpt = (proc.stderr or "")[:500]
            except subprocess.TimeoutExpired:
                exit_code = -1
                stdout_excerpt = ""
                stderr_excerpt = f"TIMEOUT after {args.timeout}s"

            verdict_map = {0: "present", 1: "absent", 2: "preconditions_not_met"}
            verdict = verdict_map.get(exit_code, "broken")

            snippets_run += 1
            results.append(
                {
                    "entry_id": entry_id,
                    "exit_code": exit_code,
                    "verdict": verdict,
                    "stdout_excerpt": stdout_excerpt,
                    "stderr_excerpt": stderr_excerpt,
                }
            )

    # Aggregate verdict
    has_present = any(r["verdict"] == "present" for r in results)
    has_absent = any(r["verdict"] == "absent" for r in results)

    if has_present:
        aggregate = "proceed"  # At least one snippet confirms the bug
    elif has_absent and not has_present:
        aggregate = "close_as_stale"  # Some snippet says fixed; none disagree
    else:
        aggregate = "inconclusive"  # No matching snippets, or all preconditions_not_met / broken

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"resolve-snippet-precheck-{args.issue}.json"
    output_path.write_text(
        json.dumps(
            {
                "issue": args.issue,
                "cited_file": cited_file_normalized,
                "stack_scope_searched": stack_scope_candidate or "<file-only>",
                "entries_scanned": entries_scanned,
                "snippets_run": snippets_run,
                "results": results,
                "verdict": aggregate,
            },
            indent=2,
        )
    )

    print(
        f"resolve-snippet-precheck: issue=#{args.issue} cited={cited_file_normalized} "
        f"snippets_run={snippets_run} verdict={aggregate} "
        f"report={output_path.relative_to(REPO_ROOT)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
