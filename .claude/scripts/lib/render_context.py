"""CSS / className parser for emitted JSX, used by both the migration tool
and the state-2b drift detector (Issue #1077, PR3).

Two consumers:
  - .claude/scripts/migrate-slot-intent.py (PR1.5) — infers slot intent from
    legacy projects (no slot-intent.json yet exists)
  - .claude/scripts/check-slot-intent-drift.py (PR3) — compares declared
    intended_render (slot-intent.json) against observed JSX

Heuristics covered:
  - Tailwind opacity classes (opacity-N for N in [0..100, step 5])
  - Arbitrary opacity (opacity-[0.055], opacity-[5%])
  - Color-modifier opacity (bg-white/5 / text-white/5 → matters for
    background-as-image cases; excluded from primary opacity reading by default)
  - Mix-blend-mode (16 modes from Tailwind)
  - Inline style={{ opacity, mixBlendMode, filter }}
  - Filter classes (grayscale, brightness-N, contrast-N, blur)
  - clsx / cn / cva conditional className → confidence='low' marker

Walker depth: best-effort one-level grep + import-walker depth ≤ 2 (matches
derive_pages.py walker semantics; deeper nesting yields confidence='unresolved').
"""
import os
import re
from typing import Optional


# ---------------------------------------------------------------------------
# Tailwind lookup tables
# ---------------------------------------------------------------------------

OPACITY_TAILWIND: dict[str, float] = {
    f"opacity-{n}": n / 100.0
    for n in (0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50,
              55, 60, 65, 70, 75, 80, 85, 90, 95, 100)
}

OPACITY_ARBITRARY_RE = re.compile(r"opacity-\[([\d.]+)(%?)\]")
OPACITY_CSS_STYLE_RE = re.compile(r"\[opacity:([\d.]+)\]")
COLOR_MOD_OPACITY_RE = re.compile(
    r"\b(?:bg|text|border|ring|fill|stroke)-[a-z\-]+/(\d+)\b"
)

BLEND_RE = re.compile(r"\bmix-blend-([a-z\-]+)\b")
GRAYSCALE_BARE_RE = re.compile(r"\bgrayscale\b(?![-\d])")
GRAYSCALE_VAL_RE = re.compile(r"\bgrayscale-\[([\d.]+)\]")
BRIGHTNESS_RE = re.compile(r"\bbrightness-(\d+)\b")
BRIGHTNESS_ARBITRARY_RE = re.compile(r"\bbrightness-\[([\d.]+)\]")
CONTRAST_RE = re.compile(r"\bcontrast-(\d+)\b")
BLUR_RE = re.compile(r"\bblur(?:-\w+)?\b")

INLINE_OPACITY_RE = re.compile(r"opacity\s*:\s*([\d.]+)")
INLINE_BLEND_RE = re.compile(r"mixBlendMode\s*:\s*['\"]([\w-]+)")
INLINE_FILTER_RE = re.compile(r"filter\s*:\s*['\"]([^'\"]+)")

CONDITIONAL_RE = re.compile(r"\b(?:clsx|cn|cva|cx)\s*\(")
# Dynamic className: `className={...}` whose brace content contains anything
# other than a single string literal. Matches function calls (cva-derived
# variants), variable refs, template literals, conditionals, etc.
# Pattern: className={<not just a quoted string>}
DYNAMIC_CLASSNAME_RE = re.compile(
    r"className=\{(?![\"'][^\"']*[\"']\s*\})[^}]*\}"
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_render_from_text(text: str) -> tuple[dict, str]:
    """Parse a snippet of JSX into intended_render + confidence label.

    Args:
        text: Multi-line JSX snippet around an image element.

    Returns:
        ({opacity, blend_mode, filter}, confidence) where confidence is one
        of 'high', 'low', or 'unresolved'.
    """
    confidence = "high"

    # Conditional className OR dynamic className → low confidence.
    if CONDITIONAL_RE.search(text) or DYNAMIC_CLASSNAME_RE.search(text):
        confidence = "low"

    # Opacity: priority is inline style > arbitrary > color-modifier > Tailwind utility.
    opacity = 1.0
    found_explicit = False

    m = INLINE_OPACITY_RE.search(text)
    if m:
        try:
            opacity = float(m.group(1))
            found_explicit = True
        except ValueError:
            confidence = "low"

    if not found_explicit:
        m = OPACITY_ARBITRARY_RE.search(text)
        if m:
            try:
                v = float(m.group(1))
                if m.group(2) == "%":
                    v /= 100.0
                opacity = v
                found_explicit = True
            except ValueError:
                confidence = "low"

    if not found_explicit:
        m = OPACITY_CSS_STYLE_RE.search(text)
        if m:
            try:
                opacity = float(m.group(1))
                found_explicit = True
            except ValueError:
                confidence = "low"

    if not found_explicit:
        # Tailwind opacity-N utility classes
        for cls, val in OPACITY_TAILWIND.items():
            if re.search(rf"\b{re.escape(cls)}\b", text):
                opacity = val
                found_explicit = True
                break

    # Note: COLOR_MOD_OPACITY_RE intentionally NOT applied here — it modifies
    # background/text color opacity, not the image element's opacity. Callers
    # interested in background-image patterns can apply it separately.

    # Blend mode: inline style overrides class.
    blend_mode = "normal"
    m = INLINE_BLEND_RE.search(text)
    if m:
        blend_mode = m.group(1).lower()
    else:
        m = BLEND_RE.search(text)
        if m:
            blend_mode = m.group(1)

    # Filter chain: collect Tailwind utilities; inline filter wins if set.
    filter_parts = []
    inline_filter = INLINE_FILTER_RE.search(text)
    if inline_filter:
        filter_str = inline_filter.group(1)
    else:
        if GRAYSCALE_BARE_RE.search(text):
            filter_parts.append("grayscale(1)")
        m = GRAYSCALE_VAL_RE.search(text)
        if m:
            filter_parts.append(f"grayscale({m.group(1)})")
        m = BRIGHTNESS_RE.search(text)
        if m:
            try:
                v = int(m.group(1)) / 100.0
                filter_parts.append(f"brightness({v})")
            except ValueError:
                pass
        m = BRIGHTNESS_ARBITRARY_RE.search(text)
        if m:
            try:
                v = float(m.group(1))
                filter_parts.append(f"brightness({v})")
            except ValueError:
                pass
        m = CONTRAST_RE.search(text)
        if m:
            try:
                v = int(m.group(1)) / 100.0
                filter_parts.append(f"contrast({v})")
            except ValueError:
                pass
        if BLUR_RE.search(text):
            filter_parts.append("blur(*)")  # qualitative; reduces signal
        filter_str = " ".join(filter_parts) if filter_parts else "none"

    return (
        {"opacity": opacity, "blend_mode": blend_mode, "filter": filter_str},
        confidence,
    )


def find_image_usages(src_root: str, filename: str) -> list[dict]:
    """Find all import/usage sites for a given image filename in src/.

    Args:
        src_root: Directory containing the project's TypeScript source
                  (typically 'src' relative to repo root).
        filename: Image filename (e.g., 'hero.webp', 'og-photo.png').

    Returns: list of {path, line, snippet} where snippet is a 5-line window.
    """
    import glob

    public_path = f"/images/{filename}"
    results = []
    if not os.path.isdir(src_root):
        return results

    patterns = (
        os.path.join(src_root, "**/*.tsx"),
        os.path.join(src_root, "**/*.jsx"),
        os.path.join(src_root, "**/*.ts"),
        os.path.join(src_root, "**/*.js"),
    )
    for pattern in patterns:
        for path in glob.glob(pattern, recursive=True):
            try:
                with open(path) as f:
                    lines = f.readlines()
            except OSError:
                continue
            for i, line in enumerate(lines):
                if public_path in line or filename in line:
                    start = max(0, i - 2)
                    end = min(len(lines), i + 3)
                    snippet = "".join(lines[start:end])
                    rel = os.path.relpath(path, os.path.dirname(src_root)
                                                if os.path.basename(src_root)
                                                else src_root)
                    results.append({
                        "path": rel.replace(os.sep, "/"),
                        "line": i + 1,
                        "snippet": snippet,
                    })
    return results


def compute_effective_weight(intended_render: Optional[dict]) -> Optional[float]:
    """Derive a 0..1 weight from intended_render (used for asymmetric drift).

    Returns None if intended_render is None (slot has production_method != ai).

    Formula:
      weight = opacity * blend_signal_survival * filter_signal_survival
    """
    if intended_render is None:
        return None

    opacity = float(intended_render.get("opacity") or 1.0)

    blend = (intended_render.get("blend_mode") or "normal").lower()
    blend_table = {
        "normal": 1.0, "screen": 0.85, "multiply": 0.85, "overlay": 0.85,
        "darken": 0.7, "lighten": 0.7,
        "color-dodge": 0.6, "color-burn": 0.6,
        "hard-light": 0.7, "soft-light": 0.85,
        "difference": 0.5, "exclusion": 0.5,
        "hue": 0.4, "saturation": 0.4, "color": 0.4, "luminosity": 0.3,
    }
    blend_survival = blend_table.get(blend, 1.0)

    filter_str = (intended_render.get("filter") or "none").lower()
    filter_survival = 1.0
    # Single grayscale handler: regex captures the numeric arg; falls back to
    # full grayscale (value=1.0) when the arg isn't extractable.
    m = re.search(r"grayscale\(([\d.]+)\)", filter_str)
    if m:
        try:
            g = float(m.group(1))
            filter_survival *= max(0.1, 1.0 - 0.5 * g)
        except ValueError:
            pass
    elif "grayscale" in filter_str:
        # Bare 'grayscale' or 'grayscale)' — treat as full grayscale.
        filter_survival *= 0.5
    m = re.search(r"brightness\(([\d.]+)\)", filter_str)
    if m:
        try:
            b = float(m.group(1))
            filter_survival *= max(0.1, b)
        except ValueError:
            pass
    if "blur" in filter_str:
        filter_survival *= 0.7

    return max(0.0, min(1.0, opacity * blend_survival * filter_survival))


def severity_for_drift(slot_role: str, observed_weight: Optional[float],
                      observed_render: dict, has_image_in_jsx: bool) -> tuple[str, str]:
    """Asymmetric severity table per /solve v2 design.

    Args:
        slot_role: declared slot_role from slot-intent.json
        observed_weight: effective_weight computed from observed JSX (None=unresolved)
        observed_render: parsed render dict from observed JSX
        has_image_in_jsx: whether ANY <Image>/<img> for the slot was found

    Returns: (severity, message) where severity ∈ {BLOCK, WARN, INFO, PASS}.
    """
    if slot_role == "none":
        if has_image_in_jsx:
            return ("BLOCK",
                    "slot declared 'none' but JSX imports an image; remove "
                    "the import or update slot-intent")
        return ("PASS", "slot=none, no image rendered (consistent)")

    if observed_weight is None:
        return ("INFO",
                "render context unresolved (clsx/cva or deep nesting); "
                "manually verify declared intent matches actual render")

    if slot_role == "focal":
        if observed_weight < 0.5:
            return ("BLOCK",
                    f"slot declared 'focal' but observed effective_weight="
                    f"{observed_weight:.3f} (<0.5); image is too dim/filtered "
                    "to convey focal intent")
        return ("PASS", f"focal slot at effective_weight={observed_weight:.3f}")

    if slot_role == "texture":
        if observed_weight > 0.5:
            return ("WARN",
                    f"slot declared 'texture' but observed effective_weight="
                    f"{observed_weight:.3f} (>0.5); render is more focal than "
                    "declared — update slot-intent or reduce opacity/blend")
        return ("PASS", f"texture slot at effective_weight={observed_weight:.3f}")

    if slot_role == "watermark":
        if not (0.3 <= observed_weight <= 0.9):
            return ("WARN",
                    f"slot declared 'watermark' but observed effective_weight="
                    f"{observed_weight:.3f} outside [0.3, 0.9]")
        return ("PASS", f"watermark slot at effective_weight={observed_weight:.3f}")

    if slot_role == "conditional":
        return ("INFO",
                "slot declared 'conditional' (runtime-gated); build-time "
                "drift detection skipped")

    return ("INFO", f"unknown slot_role={slot_role!r}")
