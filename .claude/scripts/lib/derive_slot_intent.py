"""Per-slot intent derivation for .runs/slot-intent.json (Issue #1077).

Three pure functions:
  - derive_og_photo_default(phase_a_sentinel_path) — reads gate-verdict JSON
  - derive_runtime_gate(behaviors, auth_stack_yaml_frontmatter) — admin
    role detection from structured signals
  - derive_slot_role_from_lineage(...) — Per-Slot Decision Table

These run at scaffold-init time (state-10) BEFORE any agent has produced
emitted code. They consume only experiment.yaml, archetype context, the
phase-a sentinel artifact (if produced), and auth stack frontmatter.

No grep on markdown prose; no static-analysis on emitted JSX; no dependency
on later pipeline phases. Pattern reuse: shaped like derive_pages.py
(returns dict; pure; no side effects).
"""
import json
import os
from typing import Any


# ---------------------------------------------------------------------------
# og-photo
# ---------------------------------------------------------------------------

def derive_og_photo_default(phase_a_sentinel_path: str) -> dict[str, Any]:
    """Decide og-photo's slot_role + production_method from the phase-a sentinel.

    state-11 Phase A (.claude/skills/bootstrap/state-11-core-scaffold.md:23,35)
    creates src/app/opengraph-image.tsx for web-app archetype unconditionally.
    When that file is in the sentinel's `files` list, the static og-photo asset
    is structurally dead — next/og generates the OG card dynamically — so we
    declare it 'none' + 'dynamic_runtime' upfront.

    When the sentinel does not exist (e.g., scaffold-init runs before Phase A,
    which is the normal order), we return a CONFIDENT default for web-app
    archetype: web-app always emits opengraph-image.tsx in current state-11
    Phase A. If a future archetype changes that, this function must be revised
    AND a coherence rule added (or state-2b drift detection will catch it).

    Returns a dict with three keys:
      {
        "slot_role": "none" | "focal",
        "production_method": "dynamic_runtime" | "ai_generated",
        "evidence": "<string explaining the derivation>"
      }
    """
    if os.path.exists(phase_a_sentinel_path):
        try:
            with open(phase_a_sentinel_path) as f:
                sentinel = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "slot_role": "focal",
                "production_method": "ai_generated",
                "evidence": (
                    f"phase-a sentinel unreadable ({exc!r}); falling back "
                    "to focal+ai_generated to avoid silent drift"
                ),
            }
        files = sentinel.get("files") or []
        has_dynamic_og = any(
            isinstance(f, str) and f.endswith("opengraph-image.tsx")
            for f in files
        )
        if has_dynamic_og:
            return {
                "slot_role": "none",
                "production_method": "dynamic_runtime",
                "evidence": (
                    "phase-a sentinel records src/app/opengraph-image.tsx; "
                    "static og-photo would be dead asset"
                ),
            }
        return {
            "slot_role": "focal",
            "production_method": "ai_generated",
            "evidence": (
                "phase-a sentinel does not record opengraph-image.tsx; "
                "static og-photo is the active producer"
            ),
        }

    # Sentinel missing — typical at scaffold-init time. For web-app archetype
    # state-11 Phase A always emits opengraph-image.tsx; declare the dynamic
    # default. Caller may override via experiment.yaml.design.slots.
    return {
        "slot_role": "none",
        "production_method": "dynamic_runtime",
        "evidence": (
            "phase-a sentinel not yet written (scaffold-init runs before "
            "state-11 Phase A); web-app archetype default: opengraph-image.tsx "
            "is always emitted by state-11-core-scaffold.md"
        ),
    }


# ---------------------------------------------------------------------------
# runtime_gate
# ---------------------------------------------------------------------------

def derive_runtime_gate(
    behaviors: list[dict[str, Any]] | None,
    auth_stack_frontmatter: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Decide whether a slot should carry runtime_gate (admin-only visibility).

    Primary signal: behaviors[*].requires_role (NEW structured field, Issue
    #1077). Looks for any behavior whose requires_role is a non-empty string
    and is not the demo-mode role.

    Secondary signal: auth_stack_frontmatter.demo_mode_role. When the demo
    user lacks the required role's metadata, the slot is unreachable in
    DEMO_MODE — suppress polish-floor escalation and skip generation.

    Returns:
      {
        "role": <required role>,
        "reason": <human description>,
        "evidence": <citation>
      }
    or None when there is no role-gated behavior in scope.
    """
    if not behaviors:
        return None

    # Find the strictest role required across behaviors.
    required_roles: list[tuple[str, str]] = []
    for b in behaviors:
        if not isinstance(b, dict):
            continue
        role = b.get("requires_role")
        if isinstance(role, str) and role:
            required_roles.append((role, str(b.get("id") or "<unknown>")))

    if not required_roles:
        return None

    # Pick the first declared role (callers may iterate per-slot if needed).
    role, behavior_id = required_roles[0]

    demo_role: Any = None
    if isinstance(auth_stack_frontmatter, dict):
        demo_role = auth_stack_frontmatter.get("demo_mode_role")

    if demo_role == role:
        # Demo user has the required role — slot IS reachable in DEMO_MODE.
        return None

    reason_bits = [
        f"behavior '{behavior_id}' declares requires_role={role!r}",
    ]
    if demo_role is None or demo_role == "":
        reason_bits.append(
            "auth stack demo_mode_role is null (demo user lacks role metadata)"
        )
    else:
        reason_bits.append(
            f"auth stack demo_mode_role={demo_role!r} != {role!r}"
        )

    return {
        "role": role,
        "reason": "; ".join(reason_bits),
        "evidence": f"experiment.yaml.behaviors[{behavior_id}].requires_role",
    }


# ---------------------------------------------------------------------------
# Per-Slot Decision Table
# ---------------------------------------------------------------------------

# Brand lineages whose hero treatment is typography-first / texture overlay.
_TEXTURE_LINEAGES = {
    "linear",
    "vercel",
    "stripe",
    "apple",
    "rauno",
    "rauno freiberg",
    "framer",
}

# Product domain keywords that signal an image-driven hero (focal, full opacity).
_IMAGE_HEAVY_KEYWORDS = (
    "photography",
    "photo",
    "art",
    "design portfolio",
    "portfolio",
    "food",
    "travel",
    "real estate",
    "real-estate",
    "fashion",
    "interior",
    "architecture",
)

# Optimization targets that suggest hero=none (text-first).
_DOC_TARGETS = {"documentation", "tool", "api-reference", "reference"}


def _normalize_lineage(design_lineage: list[str] | None) -> set[str]:
    if not design_lineage:
        return set()
    return {str(x).strip().lower() for x in design_lineage if isinstance(x, str)}


def derive_slot_role_from_lineage(
    slot_name: str,
    design_lineage: list[str] | None,
    optimization_target: str | None,
    description: str | None,
) -> dict[str, Any]:
    """Decide a non-og-photo slot's slot_role from product context.

    Returns:
      {
        "slot_role": <focal | texture | watermark | conditional | none>,
        "production_method": <ai_generated | programmatic_css | svg_icon | ...>,
        "candidate_budget": <high | medium | low>,
        "intended_render": <object | null>,
        "evidence": <string>
      }

    Caller resolves runtime_gate separately via derive_runtime_gate().
    """
    lineage_lc = _normalize_lineage(design_lineage)
    target_lc = (optimization_target or "").strip().lower()
    desc_lc = (description or "").strip().lower()

    image_heavy = any(kw in desc_lc for kw in _IMAGE_HEAVY_KEYWORDS)
    texture_lineage = bool(lineage_lc & _TEXTURE_LINEAGES)
    is_doc = target_lc in _DOC_TARGETS

    if slot_name == "logo":
        # Logo always foreground, foreground full-opacity. Never demoted.
        return {
            "slot_role": "focal",
            "production_method": "svg_icon",
            "candidate_budget": "medium",
            "intended_render": {
                "opacity": 1.0,
                "blend_mode": "normal",
                "filter": "none",
            },
            "evidence": "logo is universally a foreground brand mark",
        }

    if slot_name == "hero":
        if is_doc and not image_heavy:
            return _slot_descriptor(
                slot_role="none",
                production_method="programmatic_css",
                candidate_budget="low",
                intended_render=None,
                evidence=(
                    f"optimization_target={target_lc!r} is documentation-class; "
                    "hero is typography-only (no image)"
                ),
            )
        if texture_lineage and not image_heavy:
            return _slot_descriptor(
                slot_role="texture",
                production_method="ai_generated",
                candidate_budget="low",
                intended_render={
                    "opacity": 0.08,
                    "blend_mode": "luminosity",
                    "filter": "none",
                },
                evidence=(
                    f"design_lineage∩texture_set={sorted(lineage_lc & _TEXTURE_LINEAGES)} "
                    "→ typography-first hero with low-opacity texture overlay"
                ),
            )
        if image_heavy:
            return _slot_descriptor(
                slot_role="focal",
                production_method="ai_generated",
                candidate_budget="high",
                intended_render={
                    "opacity": 1.0,
                    "blend_mode": "normal",
                    "filter": "none",
                },
                evidence=(
                    "description matches image-heavy product domain; "
                    "hero is the focal element"
                ),
            )
        return _slot_descriptor(
            slot_role="focal",
            production_method="ai_generated",
            candidate_budget="high",
            intended_render={
                "opacity": 1.0,
                "blend_mode": "normal",
                "filter": "none",
            },
            evidence="safe default: hero=focal",
        )

    if slot_name in {"feature-1", "feature-2", "feature-3", "features"}:
        if texture_lineage:
            return _slot_descriptor(
                slot_role="texture",
                production_method="ai_generated",
                candidate_budget="low",
                intended_render={
                    "opacity": 0.35,
                    "blend_mode": "normal",
                    "filter": "grayscale(1) brightness(0.75)",
                },
                evidence=(
                    f"design_lineage∩texture_set={sorted(lineage_lc & _TEXTURE_LINEAGES)} "
                    "→ feature row uses muted silhouettes"
                ),
            )
        return _slot_descriptor(
            slot_role="focal",
            production_method="ai_generated",
            candidate_budget="medium",
            intended_render={
                "opacity": 1.0,
                "blend_mode": "normal",
                "filter": "none",
            },
            evidence="safe default: features=focal",
        )

    if slot_name in {"empty-state", "empty_state", "emptystate"}:
        # By default empty-state is focal; runtime_gate is decided separately
        # by derive_runtime_gate() and slot_role flips to 'conditional' if
        # role-gated.
        return _slot_descriptor(
            slot_role="focal",
            production_method="ai_generated",
            candidate_budget="low",
            intended_render={
                "opacity": 1.0,
                "blend_mode": "normal",
                "filter": "none",
            },
            evidence="default: empty-state visible foreground (override via runtime_gate)",
        )

    # Unknown slot — safe default focal+ai_generated full opacity.
    return _slot_descriptor(
        slot_role="focal",
        production_method="ai_generated",
        candidate_budget="medium",
        intended_render={
            "opacity": 1.0,
            "blend_mode": "normal",
            "filter": "none",
        },
        evidence=f"unknown slot {slot_name!r}; safe default focal",
    )


def _slot_descriptor(
    slot_role: str,
    production_method: str,
    candidate_budget: str,
    intended_render: dict[str, Any] | None,
    evidence: str,
) -> dict[str, Any]:
    return {
        "slot_role": slot_role,
        "production_method": production_method,
        "candidate_budget": candidate_budget,
        "intended_render": intended_render,
        "evidence": evidence,
    }


# ---------------------------------------------------------------------------
# Archetype short-circuit
# ---------------------------------------------------------------------------

def archetype_default(archetype: str) -> dict[str, Any] | None:
    """For non-web-app archetypes, all slots default to none.

    Returns a slot descriptor when the archetype short-circuits;
    None when per-slot derivation should proceed (web-app).
    """
    if archetype == "web-app":
        return None
    return {
        "slot_role": "none",
        "production_method": "none",
        "candidate_budget": "low",
        "intended_render": None,
        "evidence": (
            f"archetype={archetype!r} does not run image pipeline; "
            "all slots default to none"
        ),
    }


# ---------------------------------------------------------------------------
# Override merge (design.slots from experiment.yaml)
# ---------------------------------------------------------------------------

def merge_user_overrides(
    derived: dict[str, Any],
    overrides: dict[str, Any] | None,
) -> dict[str, Any]:
    """Apply experiment.yaml.design.slots[<slot>] overrides on top of derived.

    Override semantics: each user-supplied key replaces the derived key
    verbatim; absent keys fall through to derivation. This is per-key
    shallow merge (NOT deep) — if user overrides intended_render, they
    must supply the full sub-object. The 'source' field becomes 'override'
    when ANY key was overridden, else 'derived'.
    """
    if not overrides:
        result = dict(derived)
        result.setdefault("source", "derived")
        return result

    if not isinstance(overrides, dict):
        result = dict(derived)
        result.setdefault("source", "derived")
        return result

    result = dict(derived)
    overridden = False
    for key, value in overrides.items():
        if key in {"slot_role", "production_method", "candidate_budget",
                   "intended_render", "runtime_gate"}:
            result[key] = value
            overridden = True
    result["source"] = "override" if overridden else "derived"
    return result
