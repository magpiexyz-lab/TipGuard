"""RMG v2 — Canonicalize a symptom string into a stable signature.

Used by the recurrence detector to group fix-ledger rows by symptom even when
surface noise (line numbers, timestamps, PR/commit numbers, absolute paths,
short SHAs) varies between occurrences.

Public surface:
    canonicalize_symptom(actual: str) -> str
    symptom_signature_hash(actual: str) -> str   # 12-char sha1 hex

Canonicalization rules (applied in order):
  1. lowercase
  2. strip ANSI escape sequences
  3. replace ":<digits>:<digits>" line:col positions with ":N:N"
  4. replace "#<digits>" PR/issue/commit references with "#N"
  5. replace ISO-8601 / YYYY-MM-DD timestamps with "<TS>"
  6. replace absolute paths (/Users/..., /tmp/..., /private/...) with "<PATH>"
  7. replace short-sha [0-9a-f]{7,40} with "<SHA>"
  8. collapse whitespace runs to single space; strip ends
"""

from __future__ import annotations

import hashlib
import re

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# ISO-8601 timestamps (date plus optional time and offset). Matched BEFORE the
# line:col rule so "2026-04-15T10:00:00Z" collapses as a unit rather than
# letting the trailing time fragment masquerade as a line:col.
_ISO_TS_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:[T\s]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:z|[+-]\d{2}:?\d{2})?)?",
    re.IGNORECASE,
)
# Absolute paths under common roots. Pattern operates on the post-lowercase
# string, so character-class members are lowercase.
_ABS_PATH_RE = re.compile(r"(?:/private)?/(?:users|tmp|var|home|opt|root)/[^\s'\"`)\]]+")
# Match line:col or bare :line position (e.g. "bar.ts:10:5", "bar.ts:10").
# Side effect: URL-style "host:port/path" also collapses to ":N/path", which is
# acceptable for our symptom-grouping use case.
_LINE_COL_RE = re.compile(r":\d+(?::\d+)?")
_HASH_NUM_RE = re.compile(r"#\d+")
_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b")
_WS_RE = re.compile(r"\s+")


def canonicalize_symptom(actual: str) -> str:
    """Apply canonicalization rules and return the normalized symptom string."""
    if actual is None:
        return ""
    if not isinstance(actual, str):
        actual = str(actual)
    text = actual.lower()
    text = _ANSI_RE.sub("", text)
    # ISO timestamps must collapse before line:col so "T10:00:00Z" stays one unit
    text = _ISO_TS_RE.sub("<TS>", text)
    text = _ABS_PATH_RE.sub("<PATH>", text)
    text = _LINE_COL_RE.sub(":N", text)
    text = _HASH_NUM_RE.sub("#N", text)
    text = _SHA_RE.sub("<SHA>", text)
    text = _WS_RE.sub(" ", text)
    return text.strip()


def symptom_signature_hash(actual: str) -> str:
    """Return a 12-char sha1 hex digest of the canonicalized symptom."""
    canon = canonicalize_symptom(actual)
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()[:12]
