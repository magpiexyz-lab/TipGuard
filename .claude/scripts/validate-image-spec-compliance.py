#!/usr/bin/env python3
"""Validate scaffold-images actuals match spec OR declare deviations.

Issue context: #1261 — scaffold-images agent silently overrides model
selections (e.g., uses FLUX for all slots when spec says hero=FLUX,
feature=Recraft, og=GPT-2). Observer was blind because:
  1. No JSON spec to compare against (only markdown tables)
  2. Agent trace had no spec_deviations[] field

This validator:
  1. Reads .claude/patterns/scaffold-images-spec.json (canonical truth)
  2. Reads .runs/image-manifest.json (actual outputs) and
     .runs/agent-traces/scaffold-images.json (declared deviations)
  3. For each manifest entry: if model != primary_model AND model not in
     alternate_models, requires a matching entry in spec_deviations[]
  4. Each spec_deviations[].reason must be in the closed enum
  5. Each enum value's required_evidence must be present:
     - source-rate-limited      → .runs/fal-api-errors.jsonl with HTTP 429
     - model-unavailable-fallback → .runs/fal-api-errors.jsonl with 404/422
     - visual-brief-overrides   → grep .runs/current-visual-brief.md

Round-2 critic Concern 2: 'budget-low-quality-gate-tripped' enum value is
deliberately ABSENT — it was self-corroborating (same actor wrote both the
deviation claim and the self_score corroborator). Remaining enum values
require external-actor witnesses.

MODE: SCAFFOLD_IMAGES_SPEC_MODE (default warn during rollout).
Schema: skip when run_id pre-cutoff.
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.schema_version_gate import required_schema_version  # type: ignore

SPEC_PATH = ".claude/patterns/scaffold-images-spec.json"
MANIFEST_PATH = ".runs/image-manifest.json"
TRACE_PATH = ".runs/agent-traces/scaffold-images.json"
FAL_ERRORS_PATH = ".runs/fal-api-errors.jsonl"
VISUAL_BRIEF_PATH = ".runs/current-visual-brief.md"


def _active_run_id() -> str:
    best = None
    best_ts = ""
    for f in glob.glob(".runs/*-context.json"):
        if "epilogue" in f:
            continue
        try:
            d = json.load(open(f))
        except Exception:
            continue
        if d.get("completed") is True:
            continue
        ts = d.get("timestamp") or ""
        if ts >= best_ts:
            best = d
            best_ts = ts
    return (best or {}).get("run_id", "")


def _mode() -> str:
    return os.environ.get("SCAFFOLD_IMAGES_SPEC_MODE", "warn").lower()


def _slot_from_filename(filename: str) -> str:
    """Map 'hero.webp' → 'hero', 'feature-1.webp' → 'feature-1', etc."""
    base = os.path.basename(filename).rsplit(".", 1)[0]
    return base


def _load_fal_errors() -> list[dict]:
    if not os.path.isfile(FAL_ERRORS_PATH):
        return []
    out: list[dict] = []
    try:
        with open(FAL_ERRORS_PATH) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        pass
    return out


def _check_evidence(slot: str, reason: str, fal_errors: list[dict]) -> tuple[bool, str]:
    if reason == "source-rate-limited":
        for e in fal_errors:
            if e.get("slot") == slot and int(e.get("http_status", 0)) == 429:
                return True, ""
        return False, f"no fal-api-errors.jsonl entry with slot={slot!r} http_status=429"
    if reason == "model-unavailable-fallback":
        for e in fal_errors:
            if e.get("slot") == slot and int(e.get("http_status", 0)) in (404, 422):
                return True, ""
            body = (e.get("error_body") or "")
            if e.get("slot") == slot and "model_not_found" in body:
                return True, ""
        return False, (
            f"no fal-api-errors.jsonl entry with slot={slot!r} http_status in (404,422) "
            f"or error_body containing 'model_not_found'"
        )
    if reason == "visual-brief-overrides":
        if not os.path.isfile(VISUAL_BRIEF_PATH):
            return False, f"{VISUAL_BRIEF_PATH} does not exist"
        try:
            content = open(VISUAL_BRIEF_PATH).read().lower()
        except Exception as e:
            return False, f"cannot read {VISUAL_BRIEF_PATH}: {e}"
        if slot.lower() in content and "mandate" in content:
            return True, ""
        return False, (
            f"{VISUAL_BRIEF_PATH} does not mention slot {slot!r} alongside 'mandate'"
        )
    return False, f"unknown reason {reason!r}"


def main() -> int:
    mode = _mode()
    rid = _active_run_id()

    required_v = required_schema_version(rid) if rid else 1
    if required_v < 2:
        print(
            f"validate-image-spec-compliance: SKIP (run_id={rid!r} pre-cutoff; "
            f"required schema_version={required_v})"
        )
        return 0

    if not os.path.isfile(MANIFEST_PATH):
        print(f"validate-image-spec-compliance: SKIP (no {MANIFEST_PATH})")
        return 0
    if not os.path.isfile(SPEC_PATH):
        msg = f"BLOCK: {SPEC_PATH} missing — spec is the canonical source"
        print(msg, file=sys.stderr)
        return 0 if mode == "warn" else 1

    try:
        spec = json.load(open(SPEC_PATH))
        manifest = json.load(open(MANIFEST_PATH))
    except Exception as e:
        msg = f"BLOCK: parse error: {e}"
        print(msg, file=sys.stderr)
        return 0 if mode == "warn" else 1

    valid_reasons = set((spec.get("deviation_enum") or {}).keys())
    spec_slots = spec.get("slots") or {}

    # Read trace for spec_deviations[]
    spec_deviations: list[dict] = []
    if os.path.isfile(TRACE_PATH):
        try:
            trace = json.load(open(TRACE_PATH))
            spec_deviations = trace.get("spec_deviations") or []
        except Exception:
            spec_deviations = []

    # Index deviations by slot
    deviations_by_slot: dict[str, dict] = {}
    for d in spec_deviations:
        s = d.get("slot")
        if s:
            deviations_by_slot[s] = d

    fal_errors = _load_fal_errors()
    errors: list[str] = []

    # Iterate manifest entries
    images = manifest.get("images") or manifest.get("entries") or []
    if isinstance(images, dict):
        # Manifest may be {filename: {model, ...}} — convert
        images = [{"filename": k, **v} for k, v in images.items() if isinstance(v, dict)]
    for entry in images:
        if not isinstance(entry, dict):
            continue
        filename = entry.get("filename") or entry.get("path") or ""
        if not filename:
            continue
        slot = _slot_from_filename(filename)
        if slot not in spec_slots:
            continue  # unknown slot — not in spec
        actual_model = entry.get("model") or ""
        if not actual_model:
            errors.append(f"slot {slot!r}: manifest entry missing 'model' field")
            continue
        spec_entry = spec_slots[slot]
        primary = spec_entry.get("primary_model")
        alternates = set(spec_entry.get("alternate_models") or [])
        allowed = {primary} | alternates
        if actual_model in allowed:
            continue  # spec-compliant

        # Deviation — must be declared
        dev = deviations_by_slot.get(slot)
        if not dev:
            errors.append(
                f"slot {slot!r}: actual_model={actual_model!r} not in spec "
                f"(primary={primary!r}, alternates={sorted(alternates)}); "
                f"no spec_deviations[] entry declares this"
            )
            continue
        reason = dev.get("reason") or ""
        if reason not in valid_reasons:
            errors.append(
                f"slot {slot!r}: spec_deviations.reason={reason!r} not in closed enum "
                f"({sorted(valid_reasons)})"
            )
            continue
        ok, why = _check_evidence(slot, reason, fal_errors)
        if not ok:
            errors.append(
                f"slot {slot!r}: spec_deviations.reason={reason!r} but evidence missing — {why}"
            )

    # Allow explicit none
    if not images:
        explicit_none = manifest.get("spec_deviations_explicit_none")
        if not explicit_none:
            errors.append(
                f"{MANIFEST_PATH}: empty image set without "
                "spec_deviations_explicit_none=true"
            )

    if not errors:
        print(
            f"validate-image-spec-compliance: OK ({len(images)} manifest entries, "
            f"{len(spec_deviations)} declared deviations)"
        )
        return 0

    print(
        f"validate-image-spec-compliance: FAIL ({len(errors)} errors)",
        file=sys.stderr,
    )
    for e in errors:
        print(f"  {e}", file=sys.stderr)

    if mode == "warn":
        print("\n[MODE=warn] not blocking", file=sys.stderr)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
