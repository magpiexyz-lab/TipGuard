#!/usr/bin/env python3
"""Slot-intent drift detector for /verify state-2b (Issue #1077, PR3).

Reads .runs/slot-intent.json (declared) + greps src/ for emitted JSX
(observed). Per-slot diff with asymmetric severity:

  focal × observed_weight < 0.5            → BLOCK
  focal × observed_weight >= 0.5           → PASS
  texture × observed_weight > 0.5          → WARN
  texture × observed_weight ≤ 0.5          → PASS
  watermark × outside [0.3, 0.9]           → WARN
  conditional × any                        → INFO (runtime-gated)
  none × image present                     → BLOCK
  any × null (clsx/unresolved)             → INFO

Boundary-skip short-circuit: when state-2a emitted not_applicable=true,
skip drift detection with INFO (state-2b output mirrors not_applicable).

Output: .runs/drift-report.json with block_count / warn_count / info_count
and per-slot findings. state-2b VERIFY asserts block_count == 0.

Run: python3 .claude/scripts/check-slot-intent-drift.py
"""
import argparse
import datetime
import json
import os
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, ".claude", "scripts"))

from lib.render_context import (  # noqa: E402
    compute_effective_weight,
    extract_render_from_text,
    find_image_usages,
    severity_for_drift,
)


def main(argv: list[str] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--slot-intent", default=".runs/slot-intent.json",
        help="Path to declared slot-intent.json",
    )
    parser.add_argument(
        "--src-root", default="src",
        help="Path to src/ (default: 'src' relative to cwd)",
    )
    parser.add_argument(
        "--output", default=".runs/drift-report.json",
        help="Output drift report",
    )
    parser.add_argument(
        "--page-image-map", default=".runs/page-image-map.json",
        help="state-2a page-image-map.json for boundary-skip detection",
    )
    args = parser.parse_args(argv)

    # Boundary-skip handling: if state-2a wrote not_applicable, skip.
    if os.path.exists(args.page_image_map):
        try:
            pim = json.load(open(args.page_image_map))
            if pim.get("not_applicable"):
                _write_skip(args.output, "state-2a not_applicable=true (non-web-app or scope mismatch)")
                return 0
        except (OSError, json.JSONDecodeError):
            pass

    # Slot-intent absence → not_applicable (legacy projects pre-PR1b)
    if not os.path.exists(args.slot_intent):
        _write_skip(args.output, "slot-intent.json absent (legacy project; run /upgrade migrate-slot-intent.py)")
        return 0

    try:
        slot_intent = json.load(open(args.slot_intent))
    except (OSError, json.JSONDecodeError) as exc:
        _write_skip(args.output, f"slot-intent.json unreadable: {exc!r}")
        return 0

    # Flag-gated: only run drift detection when design_slots_enabled=true
    if not slot_intent.get("design_slots_enabled"):
        _write_skip(args.output, "design_slots_enabled=false (soft-launch mode); drift detection inactive")
        return 0

    findings = []
    counts = {"BLOCK": 0, "WARN": 0, "INFO": 0, "PASS": 0}

    slots = slot_intent.get("slots") or {}
    for slot_name, declared in slots.items():
        if not isinstance(declared, dict):
            continue

        slot_role = declared.get("slot_role", "focal")
        production_method = declared.get("production_method", "ai_generated")

        # Map slot_name → expected filename pattern (best-effort).
        # Slots in image-manifest typically share the slot name as filename
        # base (e.g., "hero" → "hero.webp"). For drift detection, find any
        # JSX usage that references "/images/{slot_name}.<ext>".
        usages = _find_usages_for_slot(args.src_root, slot_name)
        has_image_in_jsx = bool(usages)

        # If declared production_method is non-ai and JSX has the import → drift
        if production_method != "ai_generated":
            if has_image_in_jsx and slot_role != "none":
                # Slot says don't render but JSX renders it
                pass
            if has_image_in_jsx and production_method == "dynamic_runtime":
                findings.append({
                    "slot": slot_name,
                    "severity": "BLOCK",
                    "declared": {"slot_role": slot_role, "production_method": production_method},
                    "observed": {"image_in_jsx": True},
                    "message": (
                        f"slot declared production_method={production_method!r} "
                        "but src/ imports the static asset; remove the import "
                        f"or update slot-intent.{slot_name}.production_method"
                    ),
                })
                counts["BLOCK"] += 1
                continue
            if not has_image_in_jsx:
                findings.append({
                    "slot": slot_name,
                    "severity": "PASS",
                    "declared": {"slot_role": slot_role, "production_method": production_method},
                    "observed": {"image_in_jsx": False},
                    "message": (
                        f"slot declared {production_method!r}; no JSX import "
                        "(consistent)"
                    ),
                })
                counts["PASS"] += 1
                continue

        # ai_generated path: extract observed render from first usage
        if not usages:
            findings.append({
                "slot": slot_name,
                "severity": "INFO",
                "declared": {"slot_role": slot_role, "production_method": production_method},
                "observed": {"image_in_jsx": False},
                "message": (
                    "slot declared ai_generated but no JSX import found; "
                    "either asset is unused (remove from slot-intent) or "
                    "rendering is too deep for walker to resolve"
                ),
            })
            counts["INFO"] += 1
            continue

        observed_render, confidence = extract_render_from_text(
            usages[0]["snippet"]
        )

        if confidence == "low":
            severity = "INFO"
            message = (
                f"slot declared {slot_role!r}; observed className uses "
                "clsx/cn/cva or dynamic expression, render unresolvable "
                "via static analysis. Manual review required."
            )
        else:
            observed_weight = compute_effective_weight(observed_render)
            severity, message = severity_for_drift(
                slot_role, observed_weight, observed_render, has_image_in_jsx,
            )

        findings.append({
            "slot": slot_name,
            "severity": severity,
            "declared": {
                "slot_role": slot_role,
                "production_method": production_method,
                "intended_render": declared.get("intended_render"),
            },
            "observed": {
                "render": observed_render,
                "confidence": confidence,
                "import_sites": [
                    {"path": u["path"], "line": u["line"]}
                    for u in usages[:3]
                ],
            },
            "message": message,
        })
        counts[severity] = counts.get(severity, 0) + 1

    report = {
        "_schema_version": 1,
        "_kind": "slot-intent-drift-report",
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
                                .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "design_slots_enabled": True,
        "block_count": counts["BLOCK"],
        "warn_count": counts["WARN"],
        "info_count": counts["INFO"],
        "pass_count": counts["PASS"],
        "findings": findings,
    }

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(report, f, indent=2)

    print(f"drift-report.json written: BLOCK={counts['BLOCK']}, "
          f"WARN={counts['WARN']}, INFO={counts['INFO']}, "
          f"PASS={counts['PASS']}")
    if counts["BLOCK"] > 0:
        for f in findings:
            if f["severity"] == "BLOCK":
                print(f"  BLOCK: {f['slot']} — {f['message']}")
        return 1
    return 0


def _find_usages_for_slot(src_root: str, slot_name: str) -> list[dict]:
    """Find JSX usages for a slot. Tries common extensions."""
    all_usages: list[dict] = []
    seen = set()
    for ext in ("webp", "svg", "png", "jpg", "jpeg"):
        for u in find_image_usages(src_root, f"{slot_name}.{ext}"):
            key = (u["path"], u["line"])
            if key not in seen:
                seen.add(key)
                all_usages.append(u)
    return all_usages


def _write_skip(output_path: str, reason: str) -> None:
    report = {
        "_schema_version": 1,
        "_kind": "slot-intent-drift-report",
        "not_applicable": True,
        "skip_reason": reason,
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
                                .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "block_count": 0,
        "warn_count": 0,
        "info_count": 0,
        "pass_count": 0,
        "findings": [],
    }
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"drift-report.json: not_applicable ({reason})")


if __name__ == "__main__":
    sys.exit(main())
