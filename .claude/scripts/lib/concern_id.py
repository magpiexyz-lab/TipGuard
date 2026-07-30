"""RMG v2 — Stable concern_id for solve-critic concerns.

The id is `sha1(<canonical category>|<canonical description>)[:12]` and is the
sole key used by Phase D's `within-run-round1-concern-unaddressed` vector to
match round-1 concerns against round-2 design responses. The hash must be
stable across whitespace and quote variations so paraphrased descriptions
collide deterministically.

Public surface:
    concern_id_for(category: str, description: str) -> str
"""

from __future__ import annotations

import hashlib
import re

_QUOTE_RE = re.compile(r"['\"`]")
_WS_RE = re.compile(r"\s+")


def _canonicalize(text: str) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    text = text.lower().strip()
    text = _QUOTE_RE.sub("", text)
    text = _WS_RE.sub(" ", text)
    return text


def concern_id_for(category: str, description: str) -> str:
    """Return the 12-char sha1 hex of `<category>|<description>` after canonicalization."""
    payload = f"{_canonicalize(category)}|{_canonicalize(description)}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


__all__ = ["concern_id_for"]
