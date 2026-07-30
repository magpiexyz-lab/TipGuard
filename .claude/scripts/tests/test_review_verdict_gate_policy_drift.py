#!/usr/bin/env python3
"""test_review_verdict_gate_policy_drift.py — enforce single-source rule
for the review-verdict-gate POLICY.

Background
----------
The R2-A1 critic concern was: AUTH_PATHS could drift between
render-review-detection.md and review-verdict-gate.md. Solved in PR 1
by extracting AUTH_PATHS to a // SHARED anchor + drift test.

Same drift class applies to the verdict POLICY itself — if both
review-verdict-gate.md (markdown spec) and run-review-verdict-gate.py
(executable script) embed parallel POLICY dicts, adding a row to one
and forgetting the other silently desyncs the spec from runtime.

This test enforces the single-source resolution: the SCRIPT carries
the canonical POLICY dict; the MARKDOWN carries policy TABLES (one per
agent in dedicated `### <agent-name>` sections). Both must agree.

Coverage
--------
  T1 The markdown does NOT embed a parallel `POLICY = {` Python dict
     (only the script may carry it).
  T2 Every (agent, review_method, bucket) → required-verdict row in
     the markdown's policy tables matches the script's POLICY dict.
  T3 Every entry in the script's POLICY dict has a corresponding row
     in the markdown spec table for that agent.

Exit 0 on all-pass, 1 on any failure.
"""
from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SPEC_FILE = ROOT / ".claude/patterns/review-verdict-gate.md"
SCRIPT_FILE = ROOT / ".claude/scripts/run-review-verdict-gate.py"


def load_script_policy() -> dict:
    """Import POLICY from the executable script."""
    spec = importlib.util.spec_from_file_location("rvg", SCRIPT_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.POLICY


def parse_spec_policy_tables() -> dict:
    """Extract policy rows from the markdown's per-agent tables.

    The markdown structure is:
      ## Policy tables
      ### <agent-name>
      | review_method | <bucket-column> | required <field> |
      |---|---|---|
      | <method>      | <bucket-or-em-dash> | <literal-keyword>... |
      ...

    Spec verdict cells must be LITERAL keywords (matching the script's
    POLICY dict values byte-for-byte). The parser extracts the first
    backticked or alphanum token from the verdict cell.

    Returns: dict[(agent, review_method, bucket)] -> dict like
      {"per_item_verdict": "PASS"} or {"per_step_status": "pass", "top_level_verdict": "blocked"}
    """
    content = SPEC_FILE.read_text()
    m = re.search(
        r"## Policy tables(.*?)(?=^## )",
        content,
        re.DOTALL | re.MULTILINE,
    )
    assert m, "Markdown missing '## Policy tables' section"
    policy_section = m.group(1)

    parsed: dict = {}
    agent_blocks = re.split(r"^### (\S+)", policy_section, flags=re.MULTILINE)
    for i in range(1, len(agent_blocks), 2):
        agent = agent_blocks[i].strip()
        body = agent_blocks[i + 1]
        table_m = re.search(
            r"\| review_method.*?\n\|[-\s|]+\n((?:\|.*\n)+)",
            body,
        )
        if not table_m:
            continue

        # Determine which field this agent's table populates by reading the
        # header row. Header lists "Required `per_step_status`" or
        # "Required `per_item_verdict`".
        header_m = re.search(r"\| review_method.*?\| Required `(\w+)`", body)
        if not header_m:
            continue
        field = header_m.group(1)  # per_step_status | per_item_verdict | ...

        rows = table_m.group(1).strip().splitlines()
        for row in rows:
            cells = [c.strip() for c in row.split("|")[1:-1]]
            if len(cells) < 3:
                continue
            method_cell, bucket_cell, verdict_cell = cells[0], cells[1], cells[2]

            # Split multi-method rows like `a / b`
            methods = [m.strip().strip("`") for m in re.split(r"\s*/\s*", method_cell) if m.strip()]

            # Bucket parsing
            if bucket_cell in ("—", "-", "", "`—`"):
                bucket = "any"
            elif "∉" in bucket_cell:
                bucket = "non-auth"
            elif "∈" in bucket_cell or "AUTH_PATHS" in bucket_cell:
                bucket = "auth"
            else:
                bucket = "any"

            # Verdict cell parsing — extract first backticked literal
            backtick_m = re.search(r"`([^`]+)`", verdict_cell)
            if not backtick_m:
                # Skip rows without a literal keyword (informational rows)
                continue
            literal = backtick_m.group(1)

            # Detect top-level forcing parenthetical: "(also forces top-level `verdict="blocked"`)"
            extras = {}
            top_m = re.search(r'top-level\s*`verdict="(\w+)"', verdict_cell)
            if top_m:
                extras["top_level_verdict"] = top_m.group(1)

            for method in methods:
                parsed[(agent, method, bucket)] = {field: literal, **extras}

    return parsed


class TestReviewVerdictGatePolicyDrift(unittest.TestCase):
    def test_T1_markdown_does_not_embed_parallel_POLICY_dict(self):
        """The markdown spec must NOT carry its own `POLICY = {` Python
        dict — that's drift waiting to happen. The single-source rule
        is: script owns POLICY, markdown owns tables."""
        content = SPEC_FILE.read_text()
        # Look for parallel POLICY assignments (Python or otherwise)
        # Note: the markdown CAN reference POLICY in prose (e.g., "POLICY dict")
        # — we only flag actual assignment statements
        m = re.search(r"^POLICY\s*=\s*\{", content, re.MULTILINE)
        if m:
            self.fail(
                f"Markdown spec contains parallel POLICY dict at offset {m.start()}. "
                "Single-source rule violated — POLICY belongs ONLY in "
                ".claude/scripts/run-review-verdict-gate.py."
            )

    def test_T2_every_spec_row_has_matching_script_entry(self):
        spec = parse_spec_policy_tables()
        script = load_script_policy()
        missing = []
        for key, expected in spec.items():
            if key not in script:
                missing.append(f"  spec row {key} -> {expected} has no entry in script POLICY")
                continue
            got = script[key]
            for k, v in expected.items():
                if got.get(k) != v:
                    missing.append(
                        f"  spec row {key}: expected {k}={v!r}, script has {k}={got.get(k)!r}"
                    )
        if missing:
            self.fail(
                "Spec policy tables drifted from script POLICY:\n" + "\n".join(missing)
            )

    def test_T3_every_script_entry_has_matching_spec_row(self):
        spec = parse_spec_policy_tables()
        script = load_script_policy()
        missing = []
        for key, value in script.items():
            if key not in spec:
                missing.append(f"  script POLICY has {key} -> {value} but spec table has no row")
                continue
            spec_value = spec[key]
            for k, v in value.items():
                if spec_value.get(k) != v:
                    missing.append(
                        f"  script POLICY {key}: has {k}={v!r}, spec has {k}={spec_value.get(k)!r}"
                    )
        if missing:
            self.fail(
                "Script POLICY drifted from spec policy tables:\n" + "\n".join(missing)
            )


if __name__ == "__main__":
    unittest.main()
