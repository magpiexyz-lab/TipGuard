#!/usr/bin/env python3
"""Compute iterate-cross state x1a data-integrity flags."""

from __future__ import annotations

import argparse
import json
import os

try:
    import yaml
except ImportError:
    yaml = None


def load_config(path: str) -> dict:
    if yaml is None or not os.path.exists(path):
        return {}
    return yaml.safe_load(open(path)) or {}


def compute_flags(data: dict, config: dict) -> dict:
    mappings = config.get("mvp_mappings") or {}
    whitelist = set(config.get("signup_whitelist") or [
        "signup_complete", "waitlist_signup", "waitlist_submit",
        "early_access_signup", "activate", "form_submitted",
    ])
    out = []
    for m in data.get("mvps", []):
        name = m.get("name")
        events = {e.get("event") for e in m.get("event_catalog", [])}
        mapping = mappings.get(name) or {}
        classified = "signup_events" in mapping
        no_event_data = not events and not m.get("ga_only")
        ga_clicks = m.get("ga_clicks", 0) or 0
        gclid_visitors = m.get("gclid_visitors", 0) or 0
        out.append({
            "name": name,
            "missing_project_name": bool(m.get("orphan")),
            "signup_classified": classified,
            "auto_default_match": (not classified) and bool(events & whitelist),
            "low_traffic": gclid_visitors < 10 and ga_clicks < 10,
            "no_event_data": no_event_data,
            "needs_llm_classification": (not classified) and bool(events) and not bool(events & whitelist),
            "ga_clicks_without_ph_traffic": ga_clicks > 0 and gclid_visitors == 0 and bool(m.get("ga_only")),
        })
    return {"mvps": out}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data", default=".runs/iterate-cross-data.json")
    p.add_argument("--config", default="experiment/iterate-cross-config.yaml")
    p.add_argument("--run-dir", default=".runs")
    p.add_argument("--output", default=None)
    p.add_argument("--dry-run", action="store_true", help="Compute and print summary without writing output.")
    args = p.parse_args(argv)
    output = args.output or os.path.join(args.run_dir, "iterate-cross-data-issues.json")
    payload = compute_flags(json.load(open(args.data)), load_config(args.config))
    if args.dry_run:
        print(f"DRY-RUN: would write {output} ({len(payload['mvps'])} MVPs)")
        return 0
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    json.dump(payload, open(output, "w"), indent=2)
    print(f"Wrote {output} ({len(payload['mvps'])} MVPs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
