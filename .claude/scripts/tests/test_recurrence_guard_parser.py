#!/usr/bin/env python3
"""test_recurrence_guard_parser.py — RMG v2 Phase A.

Exercises `.claude/scripts/lib/recurrence_guard_parser.py` across full-mode
dict, light-mode bullet, list-of-bullets, legacy free-text, and invalid
shapes. Tolerant mode is toggled via the RMG_V2_TOLERANT env var.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / ".claude" / "scripts" / "lib"))

from recurrence_guard_parser import (  # noqa: E402
    FALSIFICATION_JACCARD_TAUTOLOGY,
    FALSIFICATION_STRENGTH_VALUES,
    FALSIFICATION_TEXT_MIN,
    KIND_VALUES,
    LEGACY_KIND,
    RATIONALE_MAX,
    UNGUARDABILITY_MIN,
    FalsificationParseError,
    RecurrenceGuardParseError,
    parse,
    parse_falsification,
)


def _strict_env(monkeypatch_value: str = "0"):
    """Context manager-ish helper that sets RMG_V2_TOLERANT to the given value."""

    class _Env:
        def __enter__(self):
            self.prev = os.environ.get("RMG_V2_TOLERANT")
            os.environ["RMG_V2_TOLERANT"] = monkeypatch_value
            return self

        def __exit__(self, *_):
            if self.prev is None:
                os.environ.pop("RMG_V2_TOLERANT", None)
            else:
                os.environ["RMG_V2_TOLERANT"] = self.prev

    return _Env()


class FullModeDictTests(unittest.TestCase):
    def test_each_kind_with_artifact(self):
        for kind in ("test", "lint", "hook", "invariant"):
            value = {
                "kind": kind,
                "artifact": f"path/to/{kind}.py",
                "rationale": f"covers the {kind} regression vector",
            }
            result = parse(value)
            self.assertEqual(result["kind"], kind)
            self.assertEqual(result["artifact"], f"path/to/{kind}.py")
            self.assertEqual(result["rationale"], f"covers the {kind} regression vector")
            self.assertNotIn("unguardability_rationale", result)

    def test_artifact_null_allowed_for_lint(self):
        # Lint kinds may point at a rule id rather than a path; null is also OK
        result = parse({"kind": "lint", "artifact": None, "rationale": "uses existing AOC rule"})
        self.assertIsNone(result["artifact"])

    def test_kind_none_requires_unguardability(self):
        rationale = "audit-by-review only"
        unguard = (
            "no executable check expresses this invariant because it is prose; "
            "human reviewers must inspect every PR for drift and observability "
            "monitors the docs site"
        )
        result = parse({
            "kind": "none",
            "artifact": None,
            "rationale": rationale,
            "unguardability_rationale": unguard,
        })
        self.assertEqual(result["kind"], "none")
        self.assertEqual(result["unguardability_rationale"], unguard)

    def test_kind_none_missing_unguardability_raises(self):
        with self.assertRaises(RecurrenceGuardParseError):
            parse({"kind": "none", "artifact": None, "rationale": "no check"})

    def test_kind_none_unguardability_too_short_raises(self):
        with self.assertRaises(RecurrenceGuardParseError):
            parse({
                "kind": "none",
                "artifact": None,
                "rationale": "rfc",
                "unguardability_rationale": "too short",
            })

    def test_kind_none_unguardability_missing_review_hint_raises(self):
        # Missing the (b) requirement: must mention a review/observ/monitor process
        unguard = (
            "no executable check expresses this invariant because it is prose. "
            "We will rely on developer discipline."
        )
        with self.assertRaises(RecurrenceGuardParseError):
            parse({
                "kind": "none",
                "artifact": None,
                "rationale": "n/a",
                "unguardability_rationale": unguard,
            })

    def test_unknown_kind_raises(self):
        with self.assertRaises(RecurrenceGuardParseError):
            parse({"kind": "manual", "artifact": "x", "rationale": "y"})

    def test_rationale_too_long_raises(self):
        with self.assertRaises(RecurrenceGuardParseError):
            parse({
                "kind": "test",
                "artifact": "x.py",
                "rationale": "a" * (RATIONALE_MAX + 1),
            })

    def test_rationale_empty_raises(self):
        with self.assertRaises(RecurrenceGuardParseError):
            parse({"kind": "test", "artifact": "x.py", "rationale": "   "})

    def test_artifact_blank_normalised_to_none(self):
        result = parse({"kind": "lint", "artifact": "  ", "rationale": "empty path"})
        self.assertIsNone(result["artifact"])


class LightModeBulletTests(unittest.TestCase):
    def test_single_bullet(self):
        text = "- kind=test | artifact=tests/foo_test.py | rationale=guards null path"
        result = parse(text)
        self.assertEqual(result["kind"], "test")
        self.assertEqual(result["artifact"], "tests/foo_test.py")
        self.assertEqual(result["rationale"], "guards null path")

    def test_artifact_null_token(self):
        text = "- kind=lint | artifact=null | rationale=existing AOC rule covers this"
        result = parse(text)
        self.assertIsNone(result["artifact"])

    def test_leading_whitespace_tolerated(self):
        text = "   - kind=hook | artifact=hooks/foo.sh | rationale=cli safety"
        result = parse(text)
        self.assertEqual(result["kind"], "hook")

    def test_list_with_one_bullet(self):
        result = parse([
            "- kind=invariant | artifact=type-system | rationale=enum exhaustiveness",
        ])
        self.assertEqual(result["kind"], "invariant")

    def test_multiple_bullets_rejected(self):
        with self.assertRaises(RecurrenceGuardParseError):
            parse([
                "- kind=test | artifact=a | rationale=x",
                "- kind=lint | artifact=b | rationale=y",
            ])

    def test_kind_none_in_light_mode_rejected(self):
        # Light mode cannot embed unguardability_rationale on the same bullet
        with self.assertRaises(RecurrenceGuardParseError):
            parse("- kind=none | artifact=null | rationale=no check")

    def test_extra_pipes_rejected(self):
        with self.assertRaises(RecurrenceGuardParseError):
            parse("- kind=test | artifact=a | rationale=b | extra=c")

    def test_unknown_kind_rejected(self):
        with self.assertRaises(RecurrenceGuardParseError):
            parse("- kind=manual | artifact=x | rationale=y")


class TolerantModeTests(unittest.TestCase):
    """Post-cutover: tolerant mode is OFF by default.

    `RMG_V2_TOLERANT=1` re-enables the legacy free-text escape hatch as an
    emergency-only switch. The default behavior rejects free-text entirely.
    """

    def test_legacy_freetext_tolerant_when_explicitly_enabled(self):
        with _strict_env("1"):
            result = parse("we will add a regression test in a follow-up PR")
            self.assertEqual(result["kind"], LEGACY_KIND)
            self.assertIsNone(result["artifact"])
            self.assertTrue(result["rationale"].startswith("we will add"))

    def test_legacy_freetext_default_off_rejects(self):
        # Clear the env var so the default (off) takes effect.
        prev = os.environ.pop("RMG_V2_TOLERANT", None)
        try:
            with self.assertRaises(RecurrenceGuardParseError):
                parse("we will add a regression test in a follow-up PR")
        finally:
            if prev is not None:
                os.environ["RMG_V2_TOLERANT"] = prev

    def test_legacy_freetext_explicit_off_rejects(self):
        with _strict_env("0"):
            with self.assertRaises(RecurrenceGuardParseError):
                parse("we will add a regression test in a follow-up PR")

    def test_dict_still_strict_under_tolerant(self):
        with _strict_env("1"):
            with self.assertRaises(RecurrenceGuardParseError):
                parse({"kind": "manual", "artifact": "x", "rationale": "y"})

    def test_long_legacy_truncated_when_tolerant(self):
        with _strict_env("1"):
            long_text = "x" * (RATIONALE_MAX + 50)
            result = parse(long_text)
            self.assertEqual(len(result["rationale"]), RATIONALE_MAX)


class TypeRejectionTests(unittest.TestCase):
    def test_none_value_rejected(self):
        with self.assertRaises(RecurrenceGuardParseError):
            parse(None)

    def test_int_value_rejected(self):
        with self.assertRaises(RecurrenceGuardParseError):
            parse(42)

    def test_empty_list_rejected(self):
        with self.assertRaises(RecurrenceGuardParseError):
            parse([])


class ConstantsTests(unittest.TestCase):
    def test_kinds_are_canonical(self):
        self.assertEqual(KIND_VALUES, ("test", "lint", "hook", "invariant", "none"))
        self.assertEqual(LEGACY_KIND, "legacy_freetext")
        self.assertEqual(RATIONALE_MAX, 200)
        self.assertGreaterEqual(UNGUARDABILITY_MIN, 80)

    def test_falsification_constants(self):
        self.assertGreaterEqual(FALSIFICATION_TEXT_MIN, 40)
        self.assertEqual(
            FALSIFICATION_STRENGTH_VALUES, ("high", "low", "untestable")
        )
        self.assertGreater(FALSIFICATION_JACCARD_TAUTOLOGY, 0.5)
        self.assertLess(FALSIFICATION_JACCARD_TAUTOLOGY, 1.0)


class FalsificationParserTests(unittest.TestCase):
    """parse_falsification — RMG v2 + Falsification Gate."""

    def _valid(self) -> dict:
        return {
            "prediction": (
                "If H (missing null-guard in state-X) is the root cause, the "
                "skill should hang on input Y because the early-exit branch "
                "is never taken in the observed crash logs."
            ),
            "opposite_prediction": (
                "If H is wrong and the bug is in the downstream validator, "
                "we would expect input Y to pass state-X cleanly and crash "
                "later inside scripts/validate-Z when fed a synthetic null."
            ),
            "observable_signal": (
                "The crash trace shows the process exiting at state-X "
                "before scripts/validate-Z runs, matching H's prediction "
                "and not the validator-bug alternative."
            ),
            "strength": "high",
        }

    def test_valid_block_returns_canonical_dict(self):
        result = parse_falsification(self._valid())
        self.assertEqual(result["strength"], "high")
        self.assertLess(result["jaccard_score"], FALSIFICATION_JACCARD_TAUTOLOGY)
        for field in ("prediction", "opposite_prediction", "observable_signal"):
            self.assertGreaterEqual(len(result[field]), FALSIFICATION_TEXT_MIN)

    def test_missing_field_rejected(self):
        v = self._valid()
        del v["prediction"]
        with self.assertRaises(FalsificationParseError):
            parse_falsification(v)

    def test_short_text_rejected(self):
        v = self._valid()
        v["observable_signal"] = "too short"
        with self.assertRaises(FalsificationParseError):
            parse_falsification(v)

    def test_invalid_strength_rejected(self):
        v = self._valid()
        v["strength"] = "medium"
        with self.assertRaises(FalsificationParseError):
            parse_falsification(v)

    def test_untestable_strength_accepted(self):
        v = self._valid()
        v["strength"] = "untestable"
        v["observable_signal"] = (
            "No machine-checkable signal exists for this prose-only invariant; "
            "human review catches the next instance via the coherence-rule audit."
        )
        result = parse_falsification(v)
        self.assertEqual(result["strength"], "untestable")

    def test_tautological_overlap_rejected(self):
        # prediction and opposite_prediction share >=80% tokens — circular framing.
        v = {
            "prediction": (
                "The build will succeed when null-guard added because the "
                "early-exit branch in state-X handles input Y cleanly forever."
            ),
            "opposite_prediction": (
                "The build will not succeed when null-guard added because the "
                "early-exit branch in state-X handles input Y cleanly forever."
            ),
            "observable_signal": (
                "Build log shows green status across all archetype fixtures "
                "after the null-guard patch lands in state-X."
            ),
            "strength": "high",
        }
        with self.assertRaises(FalsificationParseError) as ctx:
            parse_falsification(v)
        self.assertIn("Jaccard", str(ctx.exception))

    def test_non_dict_rejected(self):
        for bad in (None, "string", 42, ["list"]):
            with self.assertRaises(FalsificationParseError):
                parse_falsification(bad)

    def test_strength_case_normalized(self):
        v = self._valid()
        v["strength"] = "HIGH"
        result = parse_falsification(v)
        self.assertEqual(result["strength"], "high")

    def test_placeholder_template_rejected(self):
        # Verbatim state-5-fix-design.md template strings — leads who fail to
        # replace the placeholders must NOT pass the gate.
        v = {
            "prediction": "<≥40 chars: signal H predicts to observe — specific to root cause>",
            "opposite_prediction": "<≥40 chars: signal ¬H would predict instead — structurally distinct>",
            "observable_signal": "<≥40 chars: actual observation cited from reproduction/evidence>",
            "strength": "high",
        }
        with self.assertRaises(FalsificationParseError) as ctx:
            parse_falsification(v)
        self.assertIn("placeholder", str(ctx.exception))

    def test_placeholder_single_field_rejected(self):
        # Even one unreplaced placeholder among three real fields → reject.
        v = self._valid()
        v["observable_signal"] = "<≥40 chars: actual observation cited from evidence>"
        with self.assertRaises(FalsificationParseError):
            parse_falsification(v)


if __name__ == "__main__":
    unittest.main()
