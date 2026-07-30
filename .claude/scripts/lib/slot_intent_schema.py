"""Manual schema validator for .runs/slot-intent.json (Issue #1077).

No external dependency (no jsonschema lib) per existing template pattern in
.claude/hooks/artifact-integrity-gate.sh:44-60. Instead, plain dict traversal
+ isinstance() + value-in-set checks.

Schema (v1):

    {
      "_schema_version": 1,
      "_schema_version_notes": "<string>",
      "generated_at": "<ISO 8601>",
      "archetype": "web-app | service | cli",
      "design_slots_enabled": true | false,
      "slots": {
        "<slot-name>": {
          "slot_role": "focal | texture | watermark | conditional | none",
          "production_method": "ai_generated | programmatic_css | svg_icon | dynamic_runtime | none",
          "intended_render": {
            "opacity": <float 0.0-1.0>,
            "blend_mode": "<string>",
            "filter": "<string>"
          } | null,
          "candidate_budget": "high | medium | low",
          "runtime_gate": {
            "role": "<string>",
            "reason": "<string>",
            "evidence": "<string>"
          } | null,
          "source": "derived | override"
        }
      }
    }

oneOf rejection rules (caught at validation time):
  R1: slot_role=none     -> production_method ∈ {none, dynamic_runtime}
                            AND intended_render is null
                            AND runtime_gate is null
  R2: slot_role=conditional -> runtime_gate is not null
  R3: production_method=ai_generated -> intended_render is not null
  R4: production_method=dynamic_runtime -> slot_role=none
  R5: production_method=none -> slot_role=none AND intended_render is null
"""

VALID_SLOT_ROLE = {"focal", "texture", "watermark", "conditional", "none"}
VALID_PRODUCTION_METHOD = {
    "ai_generated", "programmatic_css", "svg_icon", "dynamic_runtime", "none",
}
VALID_CANDIDATE_BUDGET = {"high", "medium", "low"}
VALID_ARCHETYPE = {"web-app", "service", "cli"}
VALID_SOURCE = {"derived", "override"}

REQUIRED_TOP_LEVEL = ("_schema_version", "archetype", "design_slots_enabled", "slots")
REQUIRED_SLOT_FIELDS = (
    "slot_role",
    "production_method",
    "intended_render",
    "candidate_budget",
    "runtime_gate",
    "source",
)


def validate(doc: dict) -> list[str]:
    """Return a list of error strings; empty list = valid."""
    errors: list[str] = []

    if not isinstance(doc, dict):
        return ["root must be an object"]

    for key in REQUIRED_TOP_LEVEL:
        if key not in doc:
            errors.append(f"missing required field '{key}'")

    if doc.get("_schema_version") != 1:
        errors.append(
            f"_schema_version must be 1; got {doc.get('_schema_version')!r}"
        )

    archetype = doc.get("archetype")
    if archetype not in VALID_ARCHETYPE:
        errors.append(
            f"archetype must be one of {sorted(VALID_ARCHETYPE)}; got {archetype!r}"
        )

    if not isinstance(doc.get("design_slots_enabled"), bool):
        errors.append("design_slots_enabled must be a bool")

    slots = doc.get("slots")
    if not isinstance(slots, dict):
        errors.append("slots must be an object")
        return errors

    for slot_name, entry in slots.items():
        errors.extend(_validate_slot(slot_name, entry))

    return errors


def _validate_slot(slot_name: str, entry: object) -> list[str]:
    errors: list[str] = []
    prefix = f"slots.{slot_name}"

    if not isinstance(entry, dict):
        return [f"{prefix} must be an object"]

    for key in REQUIRED_SLOT_FIELDS:
        if key not in entry:
            errors.append(f"{prefix}.{key} missing")

    if errors:
        # If structural fields missing, skip oneOf checks (would be noisy).
        return errors

    slot_role = entry["slot_role"]
    production_method = entry["production_method"]
    intended_render = entry["intended_render"]
    candidate_budget = entry["candidate_budget"]
    runtime_gate = entry["runtime_gate"]
    source = entry["source"]

    if slot_role not in VALID_SLOT_ROLE:
        errors.append(
            f"{prefix}.slot_role must be one of {sorted(VALID_SLOT_ROLE)}; "
            f"got {slot_role!r}"
        )
    if production_method not in VALID_PRODUCTION_METHOD:
        errors.append(
            f"{prefix}.production_method must be one of "
            f"{sorted(VALID_PRODUCTION_METHOD)}; got {production_method!r}"
        )
    if candidate_budget not in VALID_CANDIDATE_BUDGET:
        errors.append(
            f"{prefix}.candidate_budget must be one of "
            f"{sorted(VALID_CANDIDATE_BUDGET)}; got {candidate_budget!r}"
        )
    if source not in VALID_SOURCE:
        errors.append(
            f"{prefix}.source must be one of {sorted(VALID_SOURCE)}; "
            f"got {source!r}"
        )

    # intended_render: null OR object with opacity/blend_mode/filter
    if intended_render is not None:
        if not isinstance(intended_render, dict):
            errors.append(f"{prefix}.intended_render must be an object or null")
        else:
            for k in ("opacity", "blend_mode", "filter"):
                if k not in intended_render:
                    errors.append(f"{prefix}.intended_render.{k} missing")
            opacity = intended_render.get("opacity")
            if opacity is not None and not (
                isinstance(opacity, (int, float)) and 0.0 <= float(opacity) <= 1.0
            ):
                errors.append(
                    f"{prefix}.intended_render.opacity must be 0.0-1.0; "
                    f"got {opacity!r}"
                )

    # runtime_gate: null OR object with role/reason/evidence
    if runtime_gate is not None:
        if not isinstance(runtime_gate, dict):
            errors.append(f"{prefix}.runtime_gate must be an object or null")
        else:
            for k in ("role", "reason", "evidence"):
                if k not in runtime_gate:
                    errors.append(f"{prefix}.runtime_gate.{k} missing")

    # If we already have shape errors, skip oneOf checks.
    if errors:
        return errors

    # oneOf rejection rules
    if slot_role == "none":
        if production_method not in {"none", "dynamic_runtime"}:
            errors.append(
                f"{prefix}: slot_role='none' requires production_method∈"
                f"{{none, dynamic_runtime}}; got {production_method!r} (R1)"
            )
        if intended_render is not None:
            errors.append(
                f"{prefix}: slot_role='none' requires intended_render=null (R1)"
            )
        if runtime_gate is not None:
            errors.append(
                f"{prefix}: slot_role='none' requires runtime_gate=null (R1)"
            )

    if slot_role == "conditional" and runtime_gate is None:
        errors.append(
            f"{prefix}: slot_role='conditional' requires runtime_gate!=null (R2)"
        )

    if production_method == "ai_generated" and intended_render is None:
        errors.append(
            f"{prefix}: production_method='ai_generated' requires "
            f"intended_render!=null (R3)"
        )

    if production_method == "dynamic_runtime" and slot_role != "none":
        errors.append(
            f"{prefix}: production_method='dynamic_runtime' requires "
            f"slot_role='none'; got {slot_role!r} (R4)"
        )

    if production_method == "none":
        if slot_role != "none":
            errors.append(
                f"{prefix}: production_method='none' requires slot_role='none'; "
                f"got {slot_role!r} (R5)"
            )
        if intended_render is not None:
            errors.append(
                f"{prefix}: production_method='none' requires intended_render=null (R5)"
            )

    return errors


def is_valid(doc: dict) -> bool:
    return not validate(doc)
