# Scaffold: Visual Design Foundation

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
> web-app/service/cli: archetype-driven scaffold templates and defaults

## Prerequisites
- Branch already created (by bootstrap Step 0)
- Plan approved and saved to `.runs/current-plan.md`
- Packages installed and UI framework configured (by scaffold-setup agent)
- Read all context files listed in your task assignment before starting

## Steps

### Step 1: Design decisions
0. **Read user-supplied design constraints from `experiment.yaml.design`** (issue #1050).
   When the block is present it is a hard constraint on subsequent choices — it overrides any judgment you would otherwise make from `target_user` or `description`:
   - `design.theme: dark | light | auto` — if `dark` or `light`, the theme is fixed; skip product-domain reasoning that would flip it. Record the forced theme in the visual brief and enforce it in `globals.css` color tokens.
   - `design.design_lineage: [Brand, ...]` — mandatory reference set for the visual brief. Consult those brands' known aesthetics (e.g., Linear = editorial precision; Vercel = monochrome-first; Rauno Freiberg = dense information design) and cite them in the brief.
   - `design.aesthetic_notes: "<freeform>"` — soft override to your own aesthetic reasoning. Incorporate into the Design Constraints section as a guiding principle.

   When the block is absent or a field is unset, fall back to full judgment (unchanged behavior).
1. Derive the three design constraints per `.claude/patterns/design.md` (color direction, design philosophy, optimization target) from experiment.yaml's product domain, **filtered by the user-supplied constraints from Step 0 above**.
2. Apply the preloaded `frontend-design` guidelines (injected via skills)
   for visual direction within the derived constraints. If not available,
   use your own judgment — match the product's personality, not framework defaults.
3. Record choices in globals.css custom properties and tailwind config per the theme contract in design.md. Font setup applies when layout.tsx is created by the pages subagent.
4. Write `.runs/current-visual-brief.md` — a structured brief that all page-generating subagents will read for visual coherence. Sections:
   - **Design Constraints**: the 3 constraints derived above (color direction, design philosophy, optimization target)
   - **Color Palette**: primary, accent, background treatment, dark mode approach
   - **Typography**: display font, body font, scale, letter-spacing stance (tight / normal / wide)
   - **Animation & Motion**: philosophy (e.g., subtle/energetic), scroll effects, micro-interactions, loading states, easing character (snappy / organic / elastic), duration scale (fast / moderate / deliberate), stagger rhythm (tight / relaxed)
   - **Spacing & Density**: overall density, section spacing, card spacing
   - **Component Style**: shape vocabulary (pill / rounded / sharp), shadows, borders, button style
   - **Visual Texture**: decorative elements, background patterns, depth technique
   - **Social Proof Treatment**: approach (ticker/marquee / testimonial cards / metric counters / logo strip / none), density, position relative to hero
   - **Image Direction**: comprehensive visual guidance for AI image generation during bootstrap Phase B1. Must cover ALL image types:
     - **Visual system**: photography / illustration / mixed — the overall approach for all generated images
     - **Hero**: subject matter (abstract/concrete), composition direction (negative space placement for text overlay), mood (aspirational/functional/dramatic)
     - **Features**: style (iconographic/photographic/illustrative), consistency rule (all features must share the same visual treatment)
     - **Logo**: graphic type (geometric/organic/letterform), shape logic (symmetry, complexity), constraint level (minimal 2-color / moderate / detailed)
     - **OG/Social**: text hierarchy approach, background treatment, brand presentation style
     - **Empty states**: emotional tone (encouraging/humorous/neutral), abstraction level
     - **Color temperature**: warm/cool/neutral alignment with the Color Palette above — this ensures AI-generated images harmonize with page CSS
   - **Numeric Precision** (brief MUST include concrete values, not directional terms):
     - **Letter-spacing**: display heading value in px (e.g., "-2.0px"), body value (e.g., "-0.1px")
     - **Line-height**: heading value (e.g., 1.1), body value (e.g., 1.55)
     - **Shadow stack**: define 3 elevation levels — each as a complete multi-layer box-shadow value with brand-color-tinted rgba. Example: light `0 1px 2px rgba(accent, 0.06), 0 2px 4px rgba(accent, 0.08)`, medium `0 4px 8px rgba(accent, 0.10), 0 8px 16px rgba(accent, 0.12)`, heavy `0 0 0 1px rgba(accent, 0.08), 0 8px 16px rgba(accent, 0.15), 0 16px 32px rgba(accent, 0.10)`
     - **Color count**: exact number of brand colors (max 3) with their roles (primary, accent, CTA) and hex values
     - **Border-radius scale**: at least 3 levels (pill: 9999px, card: Npx, input: Npx)
     - **Neutral tint**: specific tinted near-white (e.g., "#f5f4ed") and near-black (e.g., "#1a1a0e") with warm/cool justification from the color direction
   - **Signature Animation**: one hero-level micro-interaction tied to the product concept. The animation must TELL THE PRODUCT STORY, not be generic decoration. Selection guide:
     - Audio / voice / music product → waveform equalizer bars
     - Dashboard / analytics → NumberTicker counter cascade
     - Messaging / communication → typing indicator pulse
     - File / storage / upload → progress shimmer beam
     - Search / discovery → spotlight sweep
     - Scheduling / calendar → clock hand rotation
     - Payment / finance → transaction flow animation
     - Security / auth → lock/shield pulse
     - AI / ML → particle system or neural network dots
     - Social / community → avatar orbit or marquee
     - If no clear mapping: choose from Spotlight, Ripple, or Particles (neutral effects)
   - **Project-Specific Guardrails**: derive at least 3 "Never do" rules specific to THIS product's palette, domain, and visual stance. These are in ADDITION to the universal anti-patterns in design.md. Examples:
     - Warm palette: "Never use cool blue-gray for text, borders, or shadows"
     - Dark theme: "Never use drop shadows on dark surfaces — use translucent borders and subtle glows"
     - Minimalist stance: "Never add decorative gradients or background patterns"
     - Professional services: "Never use AI-generated human faces — use Unsplash real photography"
     - Playful brand: "Never use sharp corners — minimum border-radius 12px on all elements"
   - **Image source strategy**: photography (Unsplash) / illustration (AI-generated) / mixed — choose based on product domain using the Image Source Strategy table in design.md. When "photography": include specific Unsplash search terms per image type (e.g., hero: "modern dental office professional", features: "patient consultation"). When "mixed": specify which images use photography and which use illustration. When "illustration": follow existing fal.md model selection

### Step 5: Write `.runs/slot-intent.json` (Issue #1077)

**Purpose:** declare per-slot visual intent BEFORE scaffold-images / scaffold-landing / scaffold-pages run, so all four pipeline layers (generate, select, integrate, review) align on each slot's purpose. This prevents the four root-cause symptoms documented in #1077: hero opacity-0.055 invisible focal images, og-photo dead asset, feature grayscale silhouettes, empty-state DEMO-unreachable.

**Read these inputs:**

1. `experiment.yaml.type` (archetype: web-app | service | cli)
2. `experiment.yaml.behaviors` (full list — needed for `requires_role` extraction)
3. `experiment.yaml.design` block (theme, design_lineage, aesthetic_notes; AND optional `slots` user override)
4. `experiment.yaml.optimization_target` if present (or derive from `target_user`)
5. `experiment.yaml.description`
6. `.claude/stacks/auth/<stack.auth>.md` YAML frontmatter `demo_mode` block (when `stack.auth` is set; field `demo_mode_role` may be null)
7. `.runs/gate-verdicts/phase-a-sentinel.json` if it exists (it usually does NOT at state-10 time — sentinel is written by state-11 Phase A; the helper handles absence gracefully)

**Compute:**

```bash
python3 - <<'PYEOF'
import datetime, json, os, sys, yaml
sys.path.insert(0, ".claude/scripts")
from lib.derive_slot_intent import (
    archetype_default,
    derive_og_photo_default,
    derive_runtime_gate,
    derive_slot_role_from_lineage,
    merge_user_overrides,
)
from lib.slot_intent_schema import validate

exp = yaml.safe_load(open("experiment/experiment.yaml"))
archetype = exp.get("type", "web-app")
design = exp.get("design") or {}
design_lineage = design.get("design_lineage")
description = exp.get("description") or ""
optimization_target = exp.get("optimization_target") or design.get("optimization_target")
behaviors = exp.get("behaviors") or []
user_overrides = (design.get("slots") or {})

# Optional auth-stack frontmatter — extract demo_mode block.
# Anchored on '---' as full-line delimiters; bare 'split("---", 2)' breaks
# on '# --- foo ---' comment lines inside the file list.
auth_stack_frontmatter = None
auth_stack = (exp.get("stack") or {}).get("auth")
if auth_stack and auth_stack != "none":
    stack_path = f".claude/stacks/auth/{auth_stack}.md"
    if os.path.exists(stack_path):
        with open(stack_path) as f:
            text = f.read()
        if text.startswith("---\n"):
            rest = text[4:]
            end = rest.find("\n---\n")
            if end < 0 and rest.endswith("\n---"):
                end = len(rest) - 4
            if end >= 0:
                fm_text = rest[:end]
                try:
                    auth_stack_frontmatter = (yaml.safe_load(fm_text) or {}).get("demo_mode")
                except yaml.YAMLError:
                    auth_stack_frontmatter = None

# Archetype short-circuit
short = archetype_default(archetype)
slot_names = ["hero", "feature-1", "feature-2", "feature-3", "logo", "og-photo", "empty-state"]
slots_out = {}
runtime_gate = derive_runtime_gate(behaviors, auth_stack_frontmatter)

for slot in slot_names:
    if short is not None:
        derived = dict(short)
        derived["evidence"] = short["evidence"]
    elif slot == "og-photo":
        og = derive_og_photo_default(".runs/gate-verdicts/phase-a-sentinel.json")
        # og-photo derivation produces full slot descriptor; fill missing fields
        derived = {
            "slot_role": og["slot_role"],
            "production_method": og["production_method"],
            "candidate_budget": "low",
            "intended_render": (
                None if og["slot_role"] == "none"
                else {"opacity": 1.0, "blend_mode": "normal", "filter": "none"}
            ),
            "evidence": og["evidence"],
        }
    else:
        derived = derive_slot_role_from_lineage(
            slot_name=slot,
            design_lineage=design_lineage,
            optimization_target=optimization_target,
            description=description,
        )
    # Apply per-slot user override (experiment.yaml.design.slots[<slot>])
    merged = merge_user_overrides(derived, user_overrides.get(slot))
    # Attach runtime_gate for empty-state when role-gated behavior detected;
    # if user override already supplied runtime_gate, do not override it.
    if slot in {"empty-state", "empty_state", "emptystate"} and runtime_gate:
        if "runtime_gate" not in merged or merged["runtime_gate"] is None:
            merged["runtime_gate"] = runtime_gate
            # When runtime_gate is set, slot_role becomes 'conditional' unless
            # the user explicitly chose otherwise.
            if merged["slot_role"] == "focal":
                merged["slot_role"] = "conditional"
    merged.setdefault("runtime_gate", None)
    merged.setdefault("source", "derived")
    # Drop the helper-only 'evidence' field; keep the rest.
    merged.pop("evidence", None)
    slots_out[slot] = merged

design_slots_enabled = bool(design.get("slots_enabled", True))

doc = {
    "_schema_version": 1,
    "_schema_version_notes": "v1 (2026-04-26, #1077): per-slot intent contract written by scaffold-init at state-10",
    "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "archetype": archetype,
    "design_slots_enabled": design_slots_enabled,
    "slots": slots_out,
}

errors = validate(doc)
if errors:
    print("slot-intent.json validation failed:", file=sys.stderr)
    for e in errors:
        print("  -", e, file=sys.stderr)
    sys.exit(1)

os.makedirs(".runs", exist_ok=True)
with open(".runs/slot-intent.json", "w") as f:
    json.dump(doc, f, indent=2)
print(f"slot-intent.json written: {len(slots_out)} slots, design_slots_enabled={design_slots_enabled}")
PYEOF
```

**Outcome:** `.runs/slot-intent.json` exists, schema-valid, with one entry per slot. `design_slots_enabled` defaults to `true` — slot-intent contract is active for new bootstraps. To opt out (e.g., for legacy compatibility), set `experiment.yaml.design.slots_enabled: false`. When `experiment.yaml.design.slots` provides overrides, they take precedence verbatim.

**Note:** PR1b only writes the file. PR2 wires scaffold-images / scaffold-landing / scaffold-pages / design-critic to read it. PR3 adds drift-detection enforcement.

