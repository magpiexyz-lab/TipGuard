#!/usr/bin/env python3
"""Codemod: scan state files for caps imperatives near toolchain refs and
emit a worksheet for human review (NOT auto-apply).

Closes prose-gate `prose_gate_annotation` lint rule's annotation burden by
producing a per-file table that reviewers classify as:
  - gate-intent → annotate with <!-- prose-gate:<gate_id> -->
  - narrative-emphasis → reword imperative or move >8 lines from toolchain ref
  - already-handled → no action

Two-stage workflow:

  Stage 1 (this script, default):
    python3 .claude/scripts/lib/add-prose-gate-anchor.py
    → writes .runs/prose-gate-annotation-worksheet.md with one row per
      candidate (file, line, snippet, suggested_gate_id, action="REVIEW").

  Stage 2 (human review):
    Editor fills in the action column for each row: "annotate:<gate_id>",
    "reword", "waiver:<rationale ≥80 chars>", or "skip".

  Stage 3 (apply, --apply):
    python3 .claude/scripts/lib/add-prose-gate-anchor.py --apply \\
        --worksheet .runs/prose-gate-annotation-worksheet.md
    → reads worksheet, applies approved annotations as a diff bundle.

Inputs read at scan time:
  - .claude/patterns/prose-gates.json (gate_id enum)
  - .claude/patterns/template-coherence-rules.json (regex patterns)
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path

REGISTRY_PATH = ".claude/patterns/prose-gates.json"
RULES_PATH = ".claude/patterns/template-coherence-rules.json"
WORKSHEET_PATH = ".runs/prose-gate-annotation-worksheet.md"


def _load_rule_config() -> dict:
    """Read the `prose_gate_annotation` rule entry from coherence-rules JSON."""
    rules = json.load(open(RULES_PATH))
    for r in rules.get("rules", []):
        if r.get("id") == "prose-gate-annotation":
            return r
    raise SystemExit(f"rule prose-gate-annotation not found in {RULES_PATH}")


def _load_gate_ids() -> list[str]:
    if not os.path.isfile(REGISTRY_PATH):
        return []
    reg = json.load(open(REGISTRY_PATH))
    return [g["gate_id"] for g in reg.get("gates", []) if g.get("gate_id")]


def _suggest_gate_id(file_path: str, line_text: str, gate_ids: list[str]) -> str:
    """Heuristic mapping from file path + line text to a gate_id.

    Conservative: only suggests when file path strongly signals one specific
    gate. Otherwise returns "?" so the reviewer makes the call.
    """
    fp = file_path.lower()
    if "verify/state-3a" in fp and "stage 0" in line_text.lower():
        return "verify-state-3a-stage0-design-critic"
    if "bootstrap/state-6" in fp and "approval" in line_text.lower():
        return "bootstrap-state-6-user-approval"
    if "verify/state-2" in fp and ("background" in line_text.lower() or "spawn" in line_text.lower()):
        return "verify-state-2-phase1-spawn-no-background"
    if "observation-phase" in fp and ("audit" in line_text.lower() or "anomaly" in line_text.lower()):
        return "observation-phase-step5c-anomaly-audit"
    if "retro" in fp and ("suppress" in line_text.lower() or "finding" in line_text.lower()):
        return "retro-suppressions-confirmation"
    if "lead-synthesized" in line_text.lower() or "coverage_provider" in line_text.lower():
        return "lead-synthesized-numerical-bounds"
    return "?"


def scan() -> list[dict]:
    rule = _load_rule_config()
    gate_ids = _load_gate_ids()
    try:
        imperative_re = re.compile(rule["imperative_pattern"])
        toolchain_re = re.compile(rule["toolchain_pattern"])
        annotation_re = re.compile(rule["annotation_pattern"])
        waiver_re = re.compile(rule["waiver_pattern"])
    except (KeyError, re.error) as e:
        raise SystemExit(f"rule config error: {e}")
    proximity = int(rule.get("proximity_lines", 8))
    findings: list[dict] = []
    for glob_pat in rule.get("scan_globs", []):
        for path in sorted(glob.glob(glob_pat, recursive=True)):
            try:
                lines = open(path, encoding="utf-8").read().splitlines()
            except OSError:
                continue
            for i, line in enumerate(lines):
                if not imperative_re.search(line):
                    continue
                start = max(0, i - proximity)
                end = min(len(lines), i + proximity + 1)
                window = "\n".join(lines[start:end])
                if not toolchain_re.search(window):
                    continue
                if annotation_re.search(window) or waiver_re.search(window):
                    continue
                snippet = line.strip()
                if len(snippet) > 90:
                    snippet = snippet[:87] + "..."
                findings.append({
                    "file": path,
                    "line": i + 1,
                    "snippet": snippet,
                    "suggested_gate_id": _suggest_gate_id(path, line, gate_ids),
                    "action": "REVIEW",
                })
    return findings


def write_worksheet(findings: list[dict]) -> None:
    os.makedirs(os.path.dirname(WORKSHEET_PATH) or ".", exist_ok=True)
    with open(WORKSHEET_PATH, "w") as f:
        f.write("# Prose-Gate Annotation Worksheet\n\n")
        f.write(f"Generated by `.claude/scripts/lib/add-prose-gate-anchor.py`.\n")
        f.write(f"{len(findings)} candidates found.\n\n")
        f.write("## Instructions for reviewer\n\n")
        f.write("For each row, replace `REVIEW` in the Action column with one of:\n\n")
        f.write("- `annotate:<gate_id>` — insert `<!-- prose-gate:<gate_id> -->` "
                "above the line; the gate_id must exist in prose-gates.json\n")
        f.write("- `waiver:<rationale ≥80 chars>` — insert "
                "`<!-- prose-only-OK: <rationale> -->` above the line\n")
        f.write("- `reword` — change the imperative to lowercase OR move "
                "it >8 lines from the toolchain reference\n")
        f.write("- `skip` — false positive; lint rule should be tuned\n\n")
        f.write("Then run: `python3 .claude/scripts/lib/add-prose-gate-anchor.py --apply`\n\n")
        f.write("## Candidates\n\n")
        f.write("| # | File | Line | Snippet | Suggested gate_id | Action |\n")
        f.write("|---|------|------|---------|-------------------|--------|\n")
        for idx, ff in enumerate(findings, 1):
            snippet_escaped = ff["snippet"].replace("|", "\\|")
            f.write(
                f"| {idx} | `{ff['file']}` | {ff['line']} | `{snippet_escaped}` | "
                f"`{ff['suggested_gate_id']}` | `{ff['action']}` |\n"
            )


def apply(worksheet_path: str) -> int:
    """Stage 3: read worksheet, apply annotations. Idempotent."""
    if not os.path.isfile(worksheet_path):
        print(f"ERROR: worksheet not found: {worksheet_path}", file=sys.stderr)
        return 2
    text = open(worksheet_path).read()
    # Parse markdown table rows starting with `| <n> |`.
    row_re = re.compile(
        r"^\|\s*(\d+)\s*\|\s*`([^`]+)`\s*\|\s*(\d+)\s*\|\s*`([^`]+)`\s*\|"
        r"\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|$", re.MULTILINE
    )
    applied = 0
    skipped = 0
    errors = 0
    files_to_modify: dict[str, list[tuple[int, str]]] = {}
    for m in row_re.finditer(text):
        _idx, file_path, line_s, _snippet, suggested, action = m.groups()
        line_no = int(line_s)
        if action.lower() == "review":
            print(f"SKIP: row #{_idx} still marked REVIEW", file=sys.stderr)
            skipped += 1
            continue
        if action.lower() == "skip":
            skipped += 1
            continue
        if action.lower() == "reword":
            print(f"NOTE: row #{_idx} ({file_path}:{line_no}) needs manual rewording",
                  file=sys.stderr)
            skipped += 1
            continue
        if action.startswith("annotate:"):
            gate_id = action.split(":", 1)[1].strip()
            comment = f"<!-- prose-gate:{gate_id} -->"
        elif action.startswith("waiver:"):
            rationale = action.split(":", 1)[1].strip()
            if len(rationale) < 80:
                print(f"ERROR: row #{_idx} waiver rationale <80 chars: {rationale!r}",
                      file=sys.stderr)
                errors += 1
                continue
            comment = f"<!-- prose-only-OK: {rationale} -->"
        else:
            print(f"ERROR: row #{_idx} unknown action: {action!r}", file=sys.stderr)
            errors += 1
            continue
        files_to_modify.setdefault(file_path, []).append((line_no, comment))
    # Apply each file's modifications top-to-bottom in reverse (so line
    # numbers stay valid) — insert comment ABOVE the imperative line.
    for fp, ops in files_to_modify.items():
        try:
            lines = open(fp, encoding="utf-8").read().splitlines()
        except OSError as e:
            print(f"ERROR: cannot read {fp}: {e}", file=sys.stderr)
            errors += 1
            continue
        # Sort descending by line so earlier inserts don't shift later ones.
        for line_no, comment in sorted(ops, key=lambda t: -t[0]):
            idx = line_no - 1
            if idx < 0 or idx > len(lines):
                print(f"WARN: {fp}:{line_no} out of range", file=sys.stderr)
                continue
            # Idempotency: skip if the same comment is on the prior line.
            if idx > 0 and lines[idx - 1].strip() == comment:
                skipped += 1
                continue
            lines.insert(idx, comment)
            applied += 1
        with open(fp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    print(f"add-prose-gate-anchor: applied={applied} skipped={skipped} errors={errors}")
    return 0 if errors == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="Apply approved annotations from the worksheet")
    ap.add_argument("--worksheet", default=WORKSHEET_PATH,
                    help=f"Path to worksheet (default: {WORKSHEET_PATH})")
    args = ap.parse_args()
    if args.apply:
        return apply(args.worksheet)
    findings = scan()
    write_worksheet(findings)
    print(f"add-prose-gate-anchor: {len(findings)} candidates → {WORKSHEET_PATH}")
    print("Edit the worksheet, then re-run with --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
