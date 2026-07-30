#!/usr/bin/env python3
"""Parse experiment.yaml behaviors[*].tests[*] for directive tokens.

Issue #1387: scaffold-pages produces pages that pass static checks but
stub the dynamic behavior contract. This builder extracts structured
contract entries from behavior tests so the pre-fan-out lead can give
scaffold-pages agents an explicit Input Contract, and the post-fan-out
auditor can verify implementation against it.

Directive token grammar (BNF):
    test_entry  := [directive_token]? prose
    directive_token := "[audit:" kind ("=" arg)? "]"
    kind        := "api-fetch" | "sitemap-instance" | "event"
                 | "ai-conversation" | "render"
    arg         := path | event_name | segment-spec

The legal verb set is governed by `.claude/patterns/audit-verb-registry.json`
(#1393 r3 Item 3 — Group A). This PR extends that registry with
sitemap-instance, ai-conversation, and render. The `event` verb pre-exists
there; `event-emit` is NOT a valid verb (use `event`).

Untagged tests are emitted as kind="untagged" (audit produces warnings,
not blocks — backward compat). Unknown verbs (not in the registry) are
tagged via `unknown_kind: true` so the registry's audit-tag-verb-recognized
lint rule can surface them.

CLI:
    python3 .claude/scripts/lib/behavior_contract_builder.py --emit-payload
        Reads experiment/experiment.yaml; writes JSON payload to stdout
        for write-gate-artifact.sh consumption.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any


SCHEMA_VERSION = 2

# Directive token regex. Captures kind (required) and arg (optional).
# kind is lowercase letters + hyphens; arg is everything until ].
_DIRECTIVE_RE = re.compile(r"\[audit:(?P<kind>[a-z][a-z0-9-]*)(?:=(?P<arg>[^\]]+))?\]")

# Kinds whose semantics this PR understands. Aligned with
# .claude/patterns/audit-verb-registry.json (#1393 r3 Item 3). New
# entries here MUST also be added to the registry, or the
# audit-tag-verb-recognized linter will flag them.
_KNOWN_KINDS = frozenset({
    "api-fetch",        # pre-existing in registry
    "event",            # pre-existing in registry (NOT "event-emit")
    "seo",              # pre-existing in registry (free-text, lead-consumed)
    "sitemap-instance", # added by #1387
    "ai-conversation",  # added by #1387
    "render",           # added by #1387
})

# Roadmap (declared but not implemented in this PR):
_ROADMAP_KINDS = frozenset({
    "sdk-call",
    "realtime-sub",
    "external-widget",
})


def parse_test_entry(raw: str) -> list[dict[str, Any]]:
    """Extract zero-or-more directive entries from a single test string.

    Returns: list of {kind, arg, raw_test}. Empty list when no directives
    matched (caller decides what to do — typically emit `untagged`).
    """
    matches = list(_DIRECTIVE_RE.finditer(raw))
    if not matches:
        return []
    entries: list[dict[str, Any]] = []
    for m in matches:
        kind = m.group("kind")
        arg = m.group("arg")
        entry = {
            "kind": kind,
            "arg": arg,
            "raw_test": raw,
        }
        if kind in _ROADMAP_KINDS:
            entry["roadmap"] = True
        elif kind not in _KNOWN_KINDS:
            entry["unknown_kind"] = True
        entries.append(entry)
    return entries


def build_contracts(experiment: dict[str, Any]) -> dict[str, Any]:
    """Return page-keyed contract map.

    Output shape:
        {
          "<page-slug>": [
            {"kind": "api-fetch", "arg": "/api/x", "raw_test": "..."},
            {"kind": "untagged", "raw_test": "..."},
            ...
          ],
          ...,
          "_schema_version": <int>,
          "_summary": {
            "behaviors_processed": N,
            "tagged_count": N,
            "untagged_count": N,
            "unknown_kind_count": N,
            "roadmap_count": N,
          }
        }

    Pages absent from behaviors[*].pages are not represented; auditor
    treats missing pages as "no contract → nothing to verify".
    """
    by_page: dict[str, list[dict[str, Any]]] = {}
    behaviors_processed = 0
    tagged_count = 0
    untagged_count = 0
    unknown_kind_count = 0
    roadmap_count = 0

    for behavior in (experiment.get("behaviors") or []):
        if not isinstance(behavior, dict):
            continue
        pages = behavior.get("pages") or []
        tests = behavior.get("tests") or []
        if not pages or not tests:
            continue
        behaviors_processed += 1
        for test in tests:
            if not isinstance(test, str):
                continue
            entries = parse_test_entry(test)
            if not entries:
                # Untagged test: emit one entry per affected page so
                # the auditor can surface a per-page warning.
                for page in pages:
                    if not page:
                        continue
                    by_page.setdefault(page, []).append({
                        "kind": "untagged",
                        "arg": None,
                        "raw_test": test,
                    })
                    untagged_count += 1
                continue
            for entry in entries:
                tagged_count += 1
                if entry.get("unknown_kind"):
                    unknown_kind_count += 1
                if entry.get("roadmap"):
                    roadmap_count += 1
                for page in pages:
                    if not page:
                        continue
                    by_page.setdefault(page, []).append(entry)

    by_page["_schema_version"] = SCHEMA_VERSION
    by_page["_summary"] = {
        "behaviors_processed": behaviors_processed,
        "tagged_count": tagged_count,
        "untagged_count": untagged_count,
        "unknown_kind_count": unknown_kind_count,
        "roadmap_count": roadmap_count,
    }
    return by_page


def _load_experiment(path: str | None) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError:
        sys.stderr.write("ERROR: PyYAML not installed (pip install pyyaml)\n")
        sys.exit(2)
    if path:
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    # Prefer the conventional path when present. stdin is the FALLBACK
    # (not the default) — relying on `sys.stdin.isatty()` precedence
    # breaks under `$(...)` command substitution where stdin is a closed
    # pipe with no real content.
    default_path = "experiment/experiment.yaml"
    if os.path.isfile(default_path):
        with open(default_path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    if not sys.stdin.isatty():
        data = sys.stdin.read()
        if data.strip():
            return yaml.safe_load(data) or {}
    sys.stderr.write("ERROR: experiment.yaml not found and no stdin input\n")
    sys.exit(2)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parse experiment.yaml directive tokens into page-keyed contracts."
    )
    parser.add_argument(
        "--emit-payload",
        action="store_true",
        help="Write JSON payload to stdout (for write-gate-artifact.sh consumption).",
    )
    parser.add_argument(
        "--experiment",
        default=None,
        help="Path to experiment.yaml (default: experiment/experiment.yaml).",
    )
    args = parser.parse_args()

    experiment = _load_experiment(args.experiment)
    contracts = build_contracts(experiment)

    if args.emit_payload:
        print(json.dumps(contracts))
        return 0

    # Human-readable summary
    summary = contracts.get("_summary", {})
    print(
        f"behaviors_processed={summary.get('behaviors_processed', 0)} "
        f"tagged={summary.get('tagged_count', 0)} "
        f"untagged={summary.get('untagged_count', 0)} "
        f"unknown_kind={summary.get('unknown_kind_count', 0)} "
        f"roadmap={summary.get('roadmap_count', 0)}"
    )
    for page, entries in contracts.items():
        if page.startswith("_"):
            continue
        print(f"  {page}: {len(entries)} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
