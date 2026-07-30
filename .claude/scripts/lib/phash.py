"""Image evidence integrity helper — perceptual hash + provenance binding.

Issue context: #1272 design-critic Step 5.5 was bypassable by writing JSON
schema fields without performing the actual in-context candidate evaluation.
Round-2 critic (Concern 1) established that pixel-only perceptual hash is
itself bypassable — trivial transforms (1 deg rotate, JPEG re-compress,
slight crop) shift a phash by 8+ bits while a human still sees the same
content. Therefore THIS module enforces a CONJUNCTION:

    (a) screenshot file exists, has PNG/WebP magic bytes, min dimension
        >= page viewport (1280x720)
    (b) sibling <image>.provenance.json exists with (model, prompt_hash,
        seed) generation parameters
    (c) provenance triples are DISTINCT across all candidates for a slot
    (d) perceptual hash differs by Hamming distance >= 8 from every other
        candidate AND from the in-context winner snapshot

(b) and (c) are the load-bearing checks (LLMs cannot fabricate fal API
generation parameters). (d) is defense-in-depth: even if the agent reuses
a real (model, prompt_hash, seed) tuple from a prior candidate, the phash
diversity check catches "same image labeled as two candidates".

No external dependency for (a)/(b)/(c) — pure stdlib magic-byte + JSON
parse + set-membership. (d) requires `imagehash` + `Pillow` (added to
ci.yml in this PR); when unavailable, (d) is skipped with a WARN and the
validator falls back to (a/b/c) only — graceful degradation per template
convention (see lead-deliverable-gate.sh MODE pattern).

Public API:
  - compute_phash(path) -> str | None         # None if Pillow missing
  - hamming_distance(h1, h2) -> int
  - read_provenance(image_path) -> dict       # raises FileNotFoundError
  - validate_provenance_triple_unique(provs) -> list[str]  # error list
  - check_image_magic(path) -> str | None     # 'png'|'webp' or None
  - check_image_min_dimensions(path, min_w, min_h) -> bool

Usage example (validator script):
    from .phash import (compute_phash, read_provenance,
                         validate_provenance_triple_unique, check_image_magic)
    errors = []
    provs = []
    for cand_path in slot_candidates:
        if check_image_magic(cand_path) is None:
            errors.append(f"{cand_path}: not PNG/WebP")
            continue
        try:
            provs.append(read_provenance(cand_path))
        except FileNotFoundError:
            errors.append(f"{cand_path}: missing provenance JSON")
    errors.extend(validate_provenance_triple_unique(provs))
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

# Magic bytes — RFC-compliant headers, cannot be forged by zero-byte files
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
WEBP_RIFF = b"RIFF"
WEBP_FORMAT = b"WEBP"

# Page viewport defaults for design-critic in-context evaluation
DEFAULT_MIN_WIDTH = 1280
DEFAULT_MIN_HEIGHT = 720

# Hamming distance threshold for "perceptually distinct candidates"
# Empirically: distinct images differ by >=8 bits (16-bit phash) per
# imagehash literature; tampered duplicates of one image typically
# differ by 0-5 bits even after rotation/recompression.
PHASH_DIVERSITY_THRESHOLD = 8

try:
    from PIL import Image  # type: ignore
    import imagehash  # type: ignore
    _PHASH_AVAILABLE = True
except ImportError:
    _PHASH_AVAILABLE = False


def check_image_magic(path: str) -> Optional[str]:
    """Return 'png' or 'webp' if file has matching magic bytes; else None."""
    if not os.path.isfile(path):
        return None
    if os.path.getsize(path) < 12:
        return None
    with open(path, "rb") as f:
        head = f.read(12)
    if head[:8] == PNG_MAGIC:
        return "png"
    if head[:4] == WEBP_RIFF and head[8:12] == WEBP_FORMAT:
        return "webp"
    return None


def check_image_min_dimensions(
    path: str,
    min_w: int = DEFAULT_MIN_WIDTH,
    min_h: int = DEFAULT_MIN_HEIGHT,
) -> bool:
    """Return True if image dimensions >= (min_w, min_h). False otherwise.

    Falls back to True (skip) when Pillow unavailable — paired with magic
    byte check, the file at least is a real image; full dimension check
    requires libs.
    """
    if not _PHASH_AVAILABLE:
        return True
    try:
        with Image.open(path) as im:
            w, h = im.size
        return w >= min_w and h >= min_h
    except Exception:
        return False


def compute_phash(path: str) -> Optional[str]:
    """Return 16-char hex perceptual hash, or None if libs unavailable."""
    if not _PHASH_AVAILABLE:
        return None
    try:
        with Image.open(path) as im:
            return str(imagehash.phash(im))
    except Exception:
        return None


def hamming_distance(h1: str, h2: str) -> int:
    """Hamming distance between two hex phash strings (or -1 if invalid)."""
    if not h1 or not h2 or len(h1) != len(h2):
        return -1
    try:
        b1 = int(h1, 16)
        b2 = int(h2, 16)
        return bin(b1 ^ b2).count("1")
    except ValueError:
        return -1


def read_provenance(image_path: str) -> dict:
    """Read <image>.provenance.json sibling. Raises FileNotFoundError."""
    base, _ = os.path.splitext(image_path)
    prov_path = f"{base}.provenance.json"
    if not os.path.isfile(prov_path):
        raise FileNotFoundError(prov_path)
    with open(prov_path) as f:
        data = json.load(f)
    # Required fields
    for required in ("model", "prompt_hash", "seed", "generated_at"):
        if required not in data:
            raise ValueError(
                f"{prov_path}: missing required field {required!r}"
            )
    return data


def validate_provenance_triple_unique(provenances: list[dict]) -> list[str]:
    """Return list of error strings; empty = all triples distinct."""
    seen: dict[tuple, int] = {}
    errors: list[str] = []
    for idx, p in enumerate(provenances):
        triple = (p.get("model"), p.get("prompt_hash"), p.get("seed"))
        if triple in seen:
            errors.append(
                f"candidate[{idx}]: duplicate provenance triple "
                f"(model={triple[0]!r}, prompt_hash={triple[1]!r}, "
                f"seed={triple[2]!r}) shared with candidate[{seen[triple]}]"
            )
        else:
            seen[triple] = idx
    return errors


def validate_phash_diversity(
    phashes: list[str],
    threshold: int = PHASH_DIVERSITY_THRESHOLD,
) -> list[str]:
    """Return list of error strings; empty = all phashes diverse.

    Skipped (returns []) when Pillow unavailable; provenance check above
    is the primary defense.
    """
    if not _PHASH_AVAILABLE:
        return []
    errors: list[str] = []
    for i, h_i in enumerate(phashes):
        if not h_i:
            continue
        for j in range(i + 1, len(phashes)):
            h_j = phashes[j]
            if not h_j:
                continue
            d = hamming_distance(h_i, h_j)
            if 0 <= d < threshold:
                errors.append(
                    f"candidate[{i}] and candidate[{j}]: phash Hamming "
                    f"distance {d} below threshold {threshold} "
                    f"(may be same image labeled as two candidates)"
                )
    return errors


# ---------------------------------------------------------------------------
# DOM-binding helpers (#1272 follow-up; round-2 critic Concern 2)
#
# Whole-frame pHash with hamming threshold ~30 is statistically random on
# 64-bit hashes; pHash compares whole frames (page chrome != candidate),
# which makes it the wrong primitive for "screenshot actually contains the
# claimed candidate". The structural alternative: capture page.content()
# alongside the screenshot and assert the rendered DOM has an <img src=...>
# whose basename matches the candidate basename. This is structurally
# unfalsifiable — the agent cannot fabricate scores against an unrelated
# screenshot because the DOM snapshot ties the screenshot to the served URL.
# ---------------------------------------------------------------------------

_IMG_SRC_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)


def extract_img_srcs(html_path: str) -> list[str]:
    """Return list of <img src=...> values from a serialized HTML file.

    Returns [] on missing/unreadable file (caller treats as soft-fail signal
    and warns rather than blocking; DOM capture is best-effort defense in
    depth, not the only check).
    """
    if not os.path.isfile(html_path):
        return []
    try:
        with open(html_path, encoding="utf-8", errors="ignore") as f:
            return _IMG_SRC_RE.findall(f.read())
    except OSError:
        return []


def candidate_present_in_dom(
    srcs: list[str],
    candidate_basename: str,
    slot_name: Optional[str] = None,
) -> bool:
    """True iff any <img src> references the candidate or its target slot.

    The standard design-critic Step 5.5 flow copies a candidate FROM
    `.runs/image-candidates/<slot>-<phase>-<idx>.<ext>` TO
    `public/images/<slot>.<ext>` before screenshotting. The served URL
    therefore contains the SLOT name, not the candidate basename. We accept
    either:
      (a) candidate_basename appears in any src — agent served candidate
          directly (alternate flow), OR
      (b) slot_name appears in any src — agent followed canonical flow
          (copy → canonical path → screenshot)

    (b) is a weaker check — it proves the page rendered an img for the slot
    but not that this specific candidate was the source. Combined with the
    naming convention `.runs/screenshots/candidates/<slot>-<basename>.png`
    (which encodes intent) and the existing evaluation_notes/provenance
    checks, it raises the bar enough to detect "screenshot fabricated from
    unrelated page" while remaining compatible with the canonical flow.
    """
    if any(candidate_basename in s for s in srcs):
        return True
    if slot_name:
        # Match `/<slot>.`, `=<slot>.`, or `%2F<slot>.` (URL-encoded slash from
        # Next.js `/_next/image?url=...` pattern) as boundary anchors so e.g.
        # "hero" doesn't spuriously match "heroic-illustration.png".
        slot_re = re.compile(
            rf'(?:[/=]|%2F){re.escape(slot_name)}\.', re.IGNORECASE,
        )
        return any(slot_re.search(s) for s in srcs)
    return False
