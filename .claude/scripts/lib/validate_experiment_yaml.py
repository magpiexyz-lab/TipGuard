#!/usr/bin/env python3
"""validate_experiment_yaml.py — Programmatic schema validation for /bootstrap state-3.

Replaces the agent-behavior "verify name is lowercase with hyphens" check
(state-3-validate-experiment.md line 19) with a deterministic Python check
that fails loudly with a kebab-case suggestion.

The canonical check it enforces: `experiment.yaml.name` must match
`^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$`. The bootstrap step then substitutes this value verbatim
into `src/lib/analytics.ts` / `analytics-server.ts` as the PostHog
`project_name` super property — so any non-canonical form (case, spaces,
underscores, slashes) produces a PostHog identity that's incompatible with
the iterate-cross dedup design.

Why a script (vs. inline state-file Python):
- The state-3 ACTIONS block lists ~20 validation rules — most are still
  agent-driven. This script handles the regex-checkable subset
  (name format) deterministically, leaving the more semantic rules
  (archetype excludes, stack dependencies) to the agent.
- The trace file (.runs/bootstrap-validation-trace.json) is the gate-readable
  artifact; this script owns its experiment_valid flag for the regex-checkable
  rules so VERIFY can audit a real outcome instead of "agent said so".

Exit codes:
  0 — name is valid; trace written with experiment_valid: True
  1 — name is invalid; trace written with experiment_valid: False with a
      checks_failed list; stderr has human-readable error + kebab-case
      suggestion
  2 — environmental error (no experiment.yaml, no PyYAML); stderr has the
      cause; trace not written

Usage:
  python3 .claude/scripts/lib/validate_experiment_yaml.py

  # Override the experiment.yaml path (tests):
  python3 .claude/scripts/lib/validate_experiment_yaml.py --yaml path/to/test.yaml

  # Override the trace path (tests):
  python3 .claude/scripts/lib/validate_experiment_yaml.py --trace path/to/trace.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


def kebab_suggest(raw: str) -> str:
    """Derive a kebab-case suggestion from an arbitrary input string.

    Lowercase, collapse runs of non-[a-z0-9] to a single `-`, strip leading
    and trailing `-`. If the result starts with a digit (NAME_PATTERN
    requires a letter prefix), no auto-fix is attempted — the caller must
    pick a manual prefix. Empty result means the input had no alphanumeric
    characters at all; suggestion is left empty (caller should treat as
    "rename required").
    """
    if not isinstance(raw, str):
        return ""
    lowered = raw.lower()
    collapsed = re.sub(r"[^a-z0-9]+", "-", lowered)
    trimmed = collapsed.strip("-")
    return trimmed


def validate(yaml_path: str) -> tuple[bool, list[str], dict]:
    """Run the regex-checkable validations.

    Returns (is_valid, checks_failed, parsed_yaml). `checks_failed` is a list
    of short failure tokens (e.g., "name_not_kebab", "name_missing") suitable
    for the trace file. The parsed YAML is returned so the caller can render
    a contextual error message without re-reading.
    """
    try:
        import yaml
    except ImportError:
        print(
            "ERROR: PyYAML is required (pip install pyyaml) to validate experiment.yaml",
            file=sys.stderr,
        )
        sys.exit(2)

    if not os.path.exists(yaml_path):
        print(f"ERROR: {yaml_path} not found", file=sys.stderr)
        sys.exit(2)

    try:
        with open(yaml_path) as fh:
            data = yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:
        print(f"ERROR: {yaml_path} is not valid YAML: {exc}", file=sys.stderr)
        sys.exit(2)

    failures: list[str] = []

    name = data.get("name")
    if not isinstance(name, str) or not name:
        failures.append("name_missing")
    elif not NAME_PATTERN.match(name):
        failures.append("name_not_kebab")

    return (len(failures) == 0), failures, data


def render_failure_message(failures: list[str], data: dict) -> str:
    """Render a human-readable stderr message for the failures."""
    lines = []
    name = data.get("name", "")
    if "name_missing" in failures:
        lines.append("ERROR: experiment.yaml is missing the `name` field.")
        lines.append("  `name` is required (kebab-case slug, ^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$).")
    if "name_not_kebab" in failures:
        suggestion = kebab_suggest(name)
        suggestion_note = (
            f"Suggested: \"{suggestion}\""
            if suggestion and NAME_PATTERN.match(suggestion)
            else "Suggested: (pick a manual letter prefix; auto-suggestion empty)"
        )
        lines.append(
            "ERROR: experiment.yaml `name` must be kebab-case (^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$)."
        )
        lines.append(f'  Current: "{name}"')
        lines.append(f"  {suggestion_note}")
    lines.append("Edit experiment.yaml and re-run /bootstrap.")
    return "\n".join(lines)


def write_trace(trace_path: str, is_valid: bool, failures: list[str]) -> None:
    """Write the bootstrap validation trace atomically.

    Keeps the existing schema used by state-3 (`experiment_valid`,
    `checks_passed`, `warnings`) and adds `checks_failed` for the new path.
    The earlier inline trace-writer also wrote `checks_passed`; keep it for
    backwards compatibility with any consumer that looks at it.
    """
    os.makedirs(os.path.dirname(trace_path) or ".", exist_ok=True)
    trace = {
        "experiment_valid": bool(is_valid),
        "checks_passed": ["name"] if is_valid else [],
        "checks_failed": failures,
        "warnings": [],
    }
    tmp = trace_path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(trace, fh, indent=2)
    os.replace(tmp, trace_path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate experiment.yaml for /bootstrap state-3."
    )
    parser.add_argument("--yaml", default="experiment/experiment.yaml")
    parser.add_argument(
        "--trace",
        default=".runs/bootstrap-validation-trace.json",
    )
    args = parser.parse_args()

    is_valid, failures, data = validate(args.yaml)
    write_trace(args.trace, is_valid, failures)

    if not is_valid:
        print(render_failure_message(failures, data), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
