#!/usr/bin/env python3
"""Validate experiment/EVENTS.yaml structure + optional cross-check vs src/lib/events.ts.

Two passes:

1. Shape validation (always): EVENTS.yaml must be a flat events map keyed by event
   name, each entry having `funnel_stage` and `trigger`. funnel_stage must be one
   of the canonical 5 stages.

2. Cross-file drift detection (only when src/lib/events.ts exists): walk events.ts
   entries (NOT EVENTS.yaml — events.ts is the filtered/generated artifact, so
   iterating events.ts avoids false positives from EVENTS.yaml entries skipped
   via `requires`/`archetypes` filters during bootstrap generation). For each
   event found in events.ts assert its funnel_stage matches EVENTS.yaml's
   `events.<name>.funnel_stage` — checked in BOTH the EVENT_FUNNEL_MAP block AND
   inside each trackX() wrapper body (a three-way equality).

Skips Pass 2 cleanly when src/lib/events.ts is absent (template repo + service /
CLI archetypes that don't generate typed wrappers).

See `.claude/stacks/analytics/posthog.md` `### src/lib/events.ts` for the
generated-file contract that Pass 2 enforces. Issue #1408 Gap 1.
"""

import os
import re
import sys

import yaml

VALID_STAGES = {"reach", "demand", "activate", "monetize", "retain"}
EVENTS_YAML = "experiment/EVENTS.yaml"
EVENTS_TS = "src/lib/events.ts"


def validate_yaml_shape(data):
    errors = []
    if not data:
        errors.append(f"{EVENTS_YAML} is empty")
        return errors, {}
    events = data.get("events")
    if events is None:
        errors.append('missing required key "events"')
        return errors, {}
    if not isinstance(events, dict):
        errors.append('"events" must be a dict (flat map keyed by event name)')
        return errors, {}
    for name, ev in events.items():
        if not isinstance(ev, dict):
            errors.append(f"events.{name} must be a dict")
            continue
        if "funnel_stage" not in ev:
            errors.append(f'events.{name} missing "funnel_stage"')
        elif ev["funnel_stage"] not in VALID_STAGES:
            errors.append(
                f'events.{name} funnel_stage "{ev["funnel_stage"]}" '
                f"not in {sorted(VALID_STAGES)}"
            )
        if "trigger" not in ev:
            errors.append(f'events.{name} missing "trigger"')
    return errors, events


def _extract_event_funnel_map(src):
    """Extract entries from the EVENT_FUNNEL_MAP block. Returns {event_name: stage}."""
    match = re.search(
        r"EVENT_FUNNEL_MAP[^=]*=\s*\{(.*?)\}\s+as\s+const;",
        src,
        re.DOTALL,
    )
    if not match:
        return None
    block = match.group(1)
    entries = {}
    for ev, stage in re.findall(r"(\w+)\s*:\s*\"(\w+)\"", block):
        entries[ev] = stage
    return entries


def _extract_trackx_body_stages(src):
    """Extract funnel_stage from each trackX wrapper body. Returns {event_name: stage}.

    Each wrapper has shape:
        export function trackX(...) {
          track("<event_name>", { ...props, funnel_stage: "<stage>" });
        }
    """
    pattern = re.compile(
        r'export\s+function\s+track\w+\s*\([^)]*\)\s*\{\s*'
        r'track\(\s*"(\w+)"\s*,\s*\{[^}]*?funnel_stage\s*:\s*"(\w+)"',
        re.DOTALL,
    )
    return {ev: stage for ev, stage in pattern.findall(src)}


def cross_check_events_ts(events_yaml):
    """Pass 2: if src/lib/events.ts exists, assert it agrees with EVENTS.yaml.

    Iterates events.ts (the filtered/generated artifact) and verifies each event
    found there maps to a matching funnel_stage in EVENTS.yaml. Avoids the
    filter-divergence false positive that iterating EVENTS.yaml -> events.ts
    would create (e.g., payment events absent from events.ts when stack.payment
    is missing).
    """
    if not os.path.exists(EVENTS_TS):
        return []
    src = open(EVENTS_TS).read()
    errors = []

    map_entries = _extract_event_funnel_map(src)
    body_entries = _extract_trackx_body_stages(src)

    if map_entries is None:
        errors.append(
            f"{EVENTS_TS} missing EVENT_FUNNEL_MAP block — regenerate from EVENTS.yaml"
        )
        return errors

    for event, stage in map_entries.items():
        yaml_stage = (events_yaml.get(event) or {}).get("funnel_stage")
        if yaml_stage is None:
            errors.append(
                f"{EVENTS_TS} EVENT_FUNNEL_MAP.{event} = \"{stage}\" but "
                f"{EVENTS_YAML} has no events.{event}"
            )
            continue
        if stage != yaml_stage:
            errors.append(
                f"{EVENTS_TS} EVENT_FUNNEL_MAP.{event} = \"{stage}\" but "
                f"{EVENTS_YAML} events.{event}.funnel_stage = \"{yaml_stage}\" "
                "— regenerate events.ts"
            )

    for event, stage in body_entries.items():
        yaml_stage = (events_yaml.get(event) or {}).get("funnel_stage")
        if yaml_stage is None:
            errors.append(
                f"{EVENTS_TS} trackX wrapper for {event} has funnel_stage=\"{stage}\" "
                f"but {EVENTS_YAML} has no events.{event}"
            )
            continue
        if stage != yaml_stage:
            errors.append(
                f"{EVENTS_TS} trackX wrapper for {event} has funnel_stage=\"{stage}\" "
                f"but {EVENTS_YAML} events.{event}.funnel_stage = \"{yaml_stage}\" "
                "— regenerate events.ts"
            )
        map_stage = map_entries.get(event)
        if map_stage is not None and map_stage != stage:
            errors.append(
                f"{EVENTS_TS} EVENT_FUNNEL_MAP.{event}=\"{map_stage}\" "
                f"diverges from trackX wrapper body funnel_stage=\"{stage}\" "
                "— regenerate events.ts"
            )
    return errors


def main():
    data = yaml.safe_load(open(EVENTS_YAML))
    errors, events_yaml = validate_yaml_shape(data)
    if not errors:
        errors.extend(cross_check_events_ts(events_yaml))
    if errors:
        print(f"{EVENTS_YAML} issues:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
