#!/usr/bin/env python3
"""test_concern_id_stability.py — RMG v2 Phase D.

The concern_id is the sole key used by the within-run-round1-concern-
unaddressed vector to match round-1 concerns against round-2 responses.
The hash must therefore be stable across whitespace, case, and quote
variations.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / ".claude" / "scripts" / "lib"))

from concern_id import concern_id_for  # noqa: E402


class StabilityTests(unittest.TestCase):
    def test_same_inputs_same_id(self):
        a = concern_id_for("symptom-only", "the fix suppresses errors instead of addressing them")
        b = concern_id_for("symptom-only", "the fix suppresses errors instead of addressing them")
        self.assertEqual(a, b)

    def test_case_insensitive(self):
        a = concern_id_for("Symptom-Only", "The Fix Suppresses Errors")
        b = concern_id_for("symptom-only", "the fix suppresses errors")
        self.assertEqual(a, b)

    def test_whitespace_collapsed(self):
        a = concern_id_for("symptom-only", "the   fix\nsuppresses\terrors")
        b = concern_id_for("symptom-only", "the fix suppresses errors")
        self.assertEqual(a, b)

    def test_quotes_stripped(self):
        a = concern_id_for("symptom-only", "the 'fix' suppresses \"errors\"")
        b = concern_id_for("symptom-only", "the fix suppresses errors")
        self.assertEqual(a, b)

    def test_different_category_different_id(self):
        a = concern_id_for("symptom-only", "x")
        b = concern_id_for("uncovered-instances", "x")
        self.assertNotEqual(a, b)

    def test_different_description_different_id(self):
        a = concern_id_for("symptom-only", "x")
        b = concern_id_for("symptom-only", "y")
        self.assertNotEqual(a, b)

    def test_id_length_12(self):
        cid = concern_id_for("symptom-only", "any description")
        self.assertEqual(len(cid), 12)
        self.assertTrue(all(c in "0123456789abcdef" for c in cid))

    def test_none_inputs_treated_as_empty(self):
        a = concern_id_for(None, None)  # type: ignore[arg-type]
        b = concern_id_for("", "")
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
