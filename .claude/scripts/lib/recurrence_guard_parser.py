"""RMG v2 — Recurrence guard parser.

Single source of truth for the typed `recurrence_guard` field that lives in
`.runs/solve-trace.json[].prevention_analysis.recurrence_guard` and feeds the
Phase E artifact-existence gate at lifecycle-finalize.sh Step 4.6.

Two input shapes:
  * Full mode   — dict written by Phase 4 of solve-reasoning
  * Light mode  — single bullet string (or list of bullet strings) written by
                  the inline light-mode template

Tolerant mode is **off by default** post-cutover. Setting
`RMG_V2_TOLERANT=1` re-enables the legacy free-text escape hatch and
returns `{kind: "legacy_freetext"}` instead of raising. The escape
hatch is preserved for emergencies — e.g., an unforeseen agent prompt
regression that re-emits prose. Default off because no in-tree code
path writes legacy free-text after Phase A (all four writers emit
typed dicts or `None`), so soak protection has no real surface area
(see RMG v2 first-principles cutover analysis).

Public surface:
    parse(value)                 -> dict canonical guard
    parse_falsification(value)   -> dict canonical falsification block
    RecurrenceGuardParseError    -> raised when guard is invalid (tolerant=False)
    FalsificationParseError      -> raised when falsification is invalid

The canonical guard shape is::

    {
      "kind": "test" | "lint" | "hook" | "invariant" | "none",
      "artifact": "<path-or-rule-id>" | None,
      "rationale": "<≤200ch>",
      "unguardability_rationale": "<≥80ch>"   # only when kind == "none"
    }

The canonical falsification shape is::

    {
      "prediction":          "<≥40ch: signal H predicts to observe>",
      "opposite_prediction": "<≥40ch: signal ¬H would predict instead>",
      "observable_signal":   "<≥40ch: actual observation cited from evidence>",
      "strength":            "high" | "low" | "untestable"
    }
"""

from __future__ import annotations

import os
import re
from typing import Any

KIND_VALUES = ("test", "lint", "hook", "invariant", "none")
LEGACY_KIND = "legacy_freetext"
RATIONALE_MAX = 200
UNGUARDABILITY_MIN = 80

# Falsification schema constants. Each text field must be at least this long
# so trivial placeholders ("yes", "see code") are rejected at parse time.
FALSIFICATION_TEXT_MIN = 40
FALSIFICATION_STRENGTH_VALUES = ("high", "low", "untestable")
# token-Jaccard threshold above which prediction and opposite_prediction are
# treated as tautological (same observable, opposite framing). Tuned to 0.8;
# adjust here if soak data shows persistent false-positives on terse text.
FALSIFICATION_JACCARD_TAUTOLOGY = 0.8
# Reject text that looks like a template placeholder. The state-file templates
# embed strings like `<≥40 chars: signal H predicts to observe>`. Length and
# Jaccard checks alone let those literals through (~60 chars, distinct tokens
# per field). This pattern catches them — leads must replace the brackets.
_FALSIFICATION_PLACEHOLDER_RE = re.compile(r"^\s*<.+>\s*$", re.DOTALL)

_LIGHT_BULLET_RE = re.compile(
    r"^\s*-\s*kind=([a-z]+)\s*\|\s*artifact=([^|]+?)\s*\|\s*rationale=([^|]{1,%d})\s*$"
    % RATIONALE_MAX
)
_UNGUARDABILITY_HINT_A = re.compile(r"\b(no|cannot|cant|can\s*not)\b", re.IGNORECASE)
_UNGUARDABILITY_HINT_B = re.compile(r"\b(review|observ|monitor|audit)", re.IGNORECASE)


class RecurrenceGuardParseError(ValueError):
    """Raised when a recurrence_guard value cannot be parsed under strict mode."""

    def __init__(self, message: str, raw_value: Any) -> None:
        super().__init__(message)
        self.raw_value = raw_value


def _tolerant_enabled() -> bool:
    # Default off post-cutover. Set RMG_V2_TOLERANT=1 to re-enable the
    # legacy free-text escape hatch in an emergency.
    return os.environ.get("RMG_V2_TOLERANT", "0") in ("1", "true", "True")


def _validate_kind(kind: str, raw: Any) -> str:
    if kind not in KIND_VALUES:
        raise RecurrenceGuardParseError(
            f"unknown kind={kind!r}; expected one of {KIND_VALUES}", raw
        )
    return kind


def _validate_rationale(rationale: str, raw: Any) -> str:
    if not isinstance(rationale, str) or not rationale.strip():
        raise RecurrenceGuardParseError("rationale empty", raw)
    if len(rationale) > RATIONALE_MAX:
        raise RecurrenceGuardParseError(
            f"rationale length {len(rationale)} exceeds {RATIONALE_MAX}", raw
        )
    return rationale


def _validate_unguardability(value: Any, raw: Any) -> str:
    if not isinstance(value, str) or len(value) < UNGUARDABILITY_MIN:
        raise RecurrenceGuardParseError(
            f"kind=none requires unguardability_rationale of at least "
            f"{UNGUARDABILITY_MIN} characters",
            raw,
        )
    if not _UNGUARDABILITY_HINT_A.search(value):
        raise RecurrenceGuardParseError(
            "unguardability_rationale must explain WHY no executable check "
            "expresses the invariant (use 'no'/'cannot'/'can not')",
            raw,
        )
    if not _UNGUARDABILITY_HINT_B.search(value):
        raise RecurrenceGuardParseError(
            "unguardability_rationale must name the human/observability process "
            "that catches the next instance (mention review/observ/monitor/audit)",
            raw,
        )
    return value


def _parse_dict(value: dict) -> dict:
    kind = _validate_kind(str(value.get("kind", "")).strip(), value)
    artifact = value.get("artifact")
    if artifact is not None and not isinstance(artifact, str):
        raise RecurrenceGuardParseError("artifact must be string or null", value)
    rationale = _validate_rationale(str(value.get("rationale", "")).strip(), value)
    canonical = {
        "kind": kind,
        "artifact": artifact if (artifact and artifact.strip()) else None,
        "rationale": rationale,
    }
    if kind == "none":
        canonical["unguardability_rationale"] = _validate_unguardability(
            value.get("unguardability_rationale"), value
        )
    return canonical


def _parse_bullet(text: str) -> dict:
    match = _LIGHT_BULLET_RE.match(text)
    if not match:
        raise RecurrenceGuardParseError(
            "light-mode bullet must match `- kind=<token> | artifact=<path|null> | "
            "rationale=<≤200ch>`",
            text,
        )
    kind = _validate_kind(match.group(1), text)
    artifact_raw = match.group(2).strip()
    artifact = None if artifact_raw.lower() in ("null", "none", "") else artifact_raw
    rationale = _validate_rationale(match.group(3).strip(), text)
    canonical = {"kind": kind, "artifact": artifact, "rationale": rationale}
    if kind == "none":
        # Light mode cannot embed unguardability_rationale on the same bullet;
        # callers MUST switch to dict shape when kind=none.
        raise RecurrenceGuardParseError(
            "kind=none requires the dict shape so unguardability_rationale can be set",
            text,
        )
    return canonical


def _parse_legacy(text: str, raw: Any) -> dict:
    if not _tolerant_enabled():
        raise RecurrenceGuardParseError(
            "legacy free-text recurrence_guard rejected (set RMG_V2_TOLERANT=1 to allow)",
            raw,
        )
    return {
        "kind": LEGACY_KIND,
        "artifact": None,
        "rationale": text.strip()[:RATIONALE_MAX],
    }


def parse(value: Any) -> dict:
    """Parse any supported recurrence_guard shape into the canonical dict."""
    if value is None:
        raise RecurrenceGuardParseError("recurrence_guard is null", value)

    if isinstance(value, dict):
        return _parse_dict(value)

    if isinstance(value, list):
        bullets = [item for item in value if isinstance(item, str) and item.strip()]
        if not bullets:
            raise RecurrenceGuardParseError("empty bullet list", value)
        if len(bullets) > 1:
            raise RecurrenceGuardParseError(
                "exactly one bullet expected in light-mode list", value
            )
        return _parse_bullet(bullets[0])

    if isinstance(value, str):
        text = value.strip()
        if text.startswith("- kind="):
            return _parse_bullet(text)
        return _parse_legacy(text, value)

    raise RecurrenceGuardParseError(
        f"unsupported recurrence_guard type {type(value).__name__}", value
    )


# ---------------------------------------------------------------------------
# Falsification block — sibling of recurrence_guard. Lives alongside it inside
# prevention_analysis. Validated at STATE 5 VERIFY when problem_type=defect.
# ---------------------------------------------------------------------------


class FalsificationParseError(ValueError):
    """Raised when a falsification block is missing required fields or fails
    structural checks (length, strength enum, tautology overlap)."""

    def __init__(self, message: str, raw_value: Any) -> None:
        super().__init__(message)
        self.raw_value = raw_value


_TOKEN_SPLIT_RE = re.compile(r"[A-Za-z0-9]+")


def _tokenize(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_SPLIT_RE.findall(text) if len(t) > 2}


def _token_jaccard(a: str, b: str) -> float:
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def parse_falsification(value: Any) -> dict:
    """Validate and canonicalize a `falsification` block.

    Required fields: prediction, opposite_prediction, observable_signal, strength.
    Each text field ≥ FALSIFICATION_TEXT_MIN chars.
    `strength` must be one of FALSIFICATION_STRENGTH_VALUES.
    `prediction` vs `opposite_prediction` must have token-Jaccard
    < FALSIFICATION_JACCARD_TAUTOLOGY (else circular framing).

    Raises FalsificationParseError on any violation.
    """
    if value is None:
        raise FalsificationParseError("falsification is null", value)
    if not isinstance(value, dict):
        raise FalsificationParseError(
            f"falsification must be a dict, got {type(value).__name__}", value
        )

    for field in ("prediction", "opposite_prediction", "observable_signal", "strength"):
        if field not in value:
            raise FalsificationParseError(f"falsification missing {field!r}", value)

    prediction = str(value.get("prediction", "")).strip()
    opposite = str(value.get("opposite_prediction", "")).strip()
    signal = str(value.get("observable_signal", "")).strip()
    strength = str(value.get("strength", "")).strip().lower()

    if strength not in FALSIFICATION_STRENGTH_VALUES:
        raise FalsificationParseError(
            f"strength={strength!r} must be one of {FALSIFICATION_STRENGTH_VALUES}",
            value,
        )

    for name, text in (
        ("prediction", prediction),
        ("opposite_prediction", opposite),
        ("observable_signal", signal),
    ):
        if len(text) < FALSIFICATION_TEXT_MIN:
            raise FalsificationParseError(
                f"{name} length {len(text)} < {FALSIFICATION_TEXT_MIN} chars "
                "(forces a concrete, non-trivial claim)",
                value,
            )
        if _FALSIFICATION_PLACEHOLDER_RE.match(text):
            raise FalsificationParseError(
                f"{name} looks like a template placeholder (wrapped in <...>). "
                "Replace the brackets with a concrete claim — leaving the "
                "state-file template literal in the trace is not a valid "
                "falsification.",
                value,
            )

    overlap = _token_jaccard(prediction, opposite)
    if overlap >= FALSIFICATION_JACCARD_TAUTOLOGY:
        raise FalsificationParseError(
            f"prediction and opposite_prediction overlap (token-Jaccard="
            f"{overlap:.2f} >= {FALSIFICATION_JACCARD_TAUTOLOGY}) — likely "
            "tautological / circular framing. ¬H must predict a structurally "
            "distinct observable, not just the negation of H's prediction.",
            value,
        )

    return {
        "prediction": prediction,
        "opposite_prediction": opposite,
        "observable_signal": signal,
        "strength": strength,
        "jaccard_score": round(overlap, 3),
    }
