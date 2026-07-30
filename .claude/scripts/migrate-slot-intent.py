#!/usr/bin/env python3
"""Backward-compat tool for projects bootstrapped before slot-intent
contract shipped (Issue #1077, PR1.5; refactored in PR3 to share
render_context.py parser).

Reads existing .runs/image-manifest.json + greps src/**/*.{tsx,jsx,ts,js}
to infer per-slot intent. Writes SUGGESTIONS to
.runs/slot-intent-migration-suggestions.json (NOT canonical
.runs/slot-intent.json) per Round 2 critic Concern 5: never auto-write
canonical from inference, since the static analyzer has known limits
(walker depth, clsx/cva resolution, dynamic className).

Confidence levels (mirrors render_context.py):
  high   — direct grep hit at module level, unambiguous className
  medium — import-walker resolved at depth ≤ 2 (future enhancement)
  low    — clsx/cn/cva detected OR dynamic className OR walker depth > 2

User reviews suggestions and promotes to canonical via /resolve or
hand-edit. /upgrade skill invokes this tool as part of template-sync.

Run:
  python3 .claude/scripts/migrate-slot-intent.py
  python3 .claude/scripts/migrate-slot-intent.py --src-root /path/to/src
"""
import argparse
import datetime
import json
import os
import sys


# Use the shared parser from PR3 (avoids divergence with drift detector).
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, ".claude", "scripts"))

from lib.render_context import (  # noqa: E402
    compute_effective_weight,
    extract_render_from_text,
    find_image_usages,
)


# ---------------------------------------------------------------------------
# Slot inference per filename
# ---------------------------------------------------------------------------

def infer_slot_role(intended_render: dict) -> str:
    """Map an inferred intended_render to a likely slot_role.

    Aligned with render_context.severity_for_drift thresholds: a slot
    suggested as 'focal' must reach effective_weight >= 0.5; otherwise
    suggest 'texture'. This guarantees the migration tool's suggestions
    will not later BLOCK in the PR3 drift detector.
    """
    weight = compute_effective_weight(intended_render)
    if weight is None or weight < 0.5:
        return "texture"
    return "focal"


def infer_for_filename(src_root: str, filename: str,
                      opengraph_image_exists: bool) -> dict:
    """Produce a suggestion for one image filename."""
    # Special case: og-photo with opengraph-image.tsx → dynamic_runtime
    if filename.startswith("og-photo") and opengraph_image_exists:
        return {
            "slot_role": "none",
            "production_method": "dynamic_runtime",
            "intended_render": None,
            "candidate_budget": "low",
            "runtime_gate": None,
            "confidence": "high",
            "evidence": (
                "src/app/opengraph-image.tsx exists; static og-photo is "
                "dead asset. Recommendation: delete public/images/og-photo.* "
                "and og-photo entry from image-manifest.json."
            ),
            "import_sites": [],
        }

    usages = find_image_usages(src_root, filename)
    if not usages:
        return {
            "slot_role": "none",
            "production_method": "none",
            "intended_render": None,
            "candidate_budget": "low",
            "runtime_gate": None,
            "confidence": "high",
            "evidence": (
                f"no import sites in src/ for {filename}; asset appears "
                "unused. Recommendation: delete public/images and manifest entry."
            ),
            "import_sites": [],
        }

    # Use the first usage's snippet for render extraction (shared parser).
    render, confidence = extract_render_from_text(usages[0]["snippet"])
    slot_role = infer_slot_role(render)

    return {
        "slot_role": slot_role,
        "production_method": "ai_generated",
        "intended_render": render,
        "candidate_budget": "low" if slot_role == "texture" else "medium",
        "runtime_gate": None,
        "confidence": confidence,
        "evidence": (
            f"found {len(usages)} usage(s); inferred slot_role={slot_role!r} "
            f"from observed render: opacity={render['opacity']}, "
            f"blend={render['blend_mode']}, filter={render['filter']!r} "
            f"(effective_weight={compute_effective_weight(render):.3f})"
        ),
        "import_sites": [
            {"path": u["path"], "line": u["line"]} for u in usages[:5]
        ],
    }


# ---------------------------------------------------------------------------
# Top-level migration
# ---------------------------------------------------------------------------

def main(argv: list[str] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--src-root", default="src",
        help="Path to src/ (default: 'src' relative to cwd)",
    )
    parser.add_argument(
        "--manifest", default=".runs/image-manifest.json",
        help="Path to image-manifest.json",
    )
    parser.add_argument(
        "--output", default=".runs/slot-intent-migration-suggestions.json",
        help="Output file for suggestions",
    )
    args = parser.parse_args(argv)

    if not os.path.exists(args.manifest):
        print(f"ERROR: manifest not found at {args.manifest}", file=sys.stderr)
        print(
            "This tool migrates legacy projects bootstrapped before the "
            "slot-intent contract shipped. If image-manifest.json doesn't "
            "exist, there is nothing to migrate.",
            file=sys.stderr,
        )
        return 1

    with open(args.manifest) as f:
        manifest = json.load(f)

    images = manifest.get("images", [])
    if not isinstance(images, list):
        print(f"ERROR: manifest.images is not a list", file=sys.stderr)
        return 1

    src_root = args.src_root
    opengraph_image_exists = os.path.exists("src/app/opengraph-image.tsx")

    suggestions: dict[str, dict] = {}
    for entry in images:
        if not isinstance(entry, dict):
            continue
        filename = entry.get("filename")
        if not filename:
            continue
        # Map filename → slot key (drop extension; "feature-1.webp" → "feature-1")
        slot_key = filename.rsplit(".", 1)[0]
        suggestions[slot_key] = infer_for_filename(
            src_root, filename, opengraph_image_exists,
        )

    output = {
        "_schema_version": 1,
        "_kind": "slot-intent-migration-suggestions",
        "_disclaimer": (
            "These are SUGGESTIONS only. Review and promote to canonical "
            ".runs/slot-intent.json manually or via /resolve. The static "
            "analyzer has known limits (walker depth ≤ 2, clsx/cva "
            "resolution, dynamic className) — confidence flags reflect "
            "those limits. Slot_role suggestions are aligned with the "
            "drift detector's effective_weight threshold (0.5) so promoted "
            "suggestions will not later BLOCK at /verify state-2b."
        ),
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
                                .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "manifest_path": args.manifest,
        "src_root": src_root,
        "opengraph_image_tsx_exists": opengraph_image_exists,
        "suggestions": suggestions,
    }

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)

    counts = {"high": 0, "medium": 0, "low": 0}
    for s in suggestions.values():
        c = s.get("confidence", "low")
        counts[c] = counts.get(c, 0) + 1

    print(f"Wrote {args.output}: {len(suggestions)} suggestions")
    print(f"  confidence: high={counts['high']}, medium={counts['medium']}, "
          f"low={counts['low']}")
    print()
    print("REVIEW REQUIRED — these are suggestions, not canonical. "
          "Hand-edit .runs/slot-intent.json or invoke /resolve.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
