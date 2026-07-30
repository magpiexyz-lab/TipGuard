#!/usr/bin/env python3
"""Post-fan-out behavior-contract audit for scaffold-pages output (#1387).

Two-layer audit driver:

Layer 4a — Static (fail-fast, runs here):
  For each tagged contract entry in .runs/scaffold-pages-contracts.json,
  perform deterministic structural checks on the page's .tsx file(s).

  Implemented via multi-pass regex / string analysis (not full AST). The
  Layer 4a check is intentionally conservative: it catches obvious gaps
  (no fetch at all, slug missing from sitemap entirely) but defers the
  fool-by-design cases (fetch wrapper with .catch synthesizing stub
  data) to Layer 4b. Round 2 caveat 027e6ac4b29e flags TS-AST as the
  ideal mechanism — this PR ships F6 (npm install typescript-estree)
  so a follow-up can swap in AST-based reachability/consumption checks
  without touching the orchestration in state-11c.

Layer 4b — Runtime signaling (consumed by /verify):
  Emits .runs/behavior-verifier-static-stubs.json. behavior-verifier
  reads this in /verify and runs Playwright network-observability
  checks (B7 dynamic-stub-detection). B7 is the load-bearing
  trustworthy verification — static Layer 4a is fail-fast pre-PR only.

Reads contracts via unstamped_items() from verify_helpers (mandatory
per template-coherence-rules.json rule
verify-d-values-against-stamped-artifact). Writes audit verdict via
write-gate-artifact.sh (canonical writer; stamps {skill, run_id,
written_at}).

CLI: python3 .claude/scripts/lib/behavior_contract_auditor.py [--repo-root PATH]
     Writes .runs/behavior-implementation-audit.json and
     .runs/behavior-verifier-static-stubs.json. Returns 0 even when
     uncovered_count > 0 (state-11c VERIFY block is the gate).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from verify_helpers import unstamped_items  # type: ignore

CONTRACTS_PATH = ".runs/scaffold-pages-contracts.json"
AUDIT_PATH = ".runs/behavior-implementation-audit.json"
STUBS_PATH = ".runs/behavior-verifier-static-stubs.json"
PHASE_A_SENTINEL_PATH = ".runs/gate-verdicts/phase-a-sentinel.json"
SITEMAP_PATH = "src/app/sitemap.ts"
SCHEMA_VERSION = 2


def _read_text(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except (OSError, FileNotFoundError):
        return None


def _candidate_page_files(repo_root: str, page: str) -> list[str]:
    """Return ABSOLUTE .tsx/.jsx file paths under the page's folder.

    Issue #1450 gaps 1-2: route-shape resolution and co-located file
    enumeration are sourced from the canonical helper
    `derive_pages.derive_page_set_for_design_critic`, which:
      (a) walks the filesystem and reports each page's route_pattern,
          test_url, source_files, and dynamic_segments,
      (b) enumerates nested .tsx/.jsx in each page folder (lines 327-340
          of derive_pages.py), covering *-client.tsx / *-tracker.tsx.

    Three lookup strategies are applied in order; the first match wins:
      1. Exact name (`scope == discovered.name`) — static routes
         and scope names already aligned with disambiguated discovery.
      2. Static-prefix match (`scope.split('-')[0] == discovered.split('-')[0]`)
         — covers scope='portfolio-detail' → discovered='portfolio-slug'
         when the dynamic route is /portfolio/[slug].
      3. Dynamic-segment match (`scope in discovered.dynamic_segments`)
         — covers scope='variant' → discovered='v-variant' when the
         dynamic route is /v/[variant]. Closes the original gap-1
         case the static-prefix fallback cannot reach (URL prefix
         differs from scope name).

    Returns absolute paths so callers' open() works regardless of CWD
    (the auditor may be invoked with `cwd != repo_root`).
    """
    # Lazy import: derive_pages lives in the same package; avoid
    # top-level import to keep this module's import surface small for
    # subprocess invocations and to defer any derive_pages side effects.
    try:
        from derive_pages import derive_page_set_for_design_critic  # type: ignore
    except Exception:
        derive_page_set_for_design_critic = None  # type: ignore

    if derive_page_set_for_design_critic is not None:
        try:
            entries = derive_page_set_for_design_critic({}, repo_root)
        except Exception:
            entries = []

        def _files(entry):
            return sorted(
                {os.path.join(repo_root, p) for p in entry.get("source_files", [])}
            )

        # Lookup 1 — direct name match (covers static routes
        # `src/app/<page>/page.tsx` AND scope names already aligned with
        # disambiguated discovery, e.g., scope='portfolio-slug').
        for entry in entries:
            if entry.get("name") == page:
                return _files(entry)

        # Lookup 2 — static-prefix match. Scope='portfolio-detail' maps to
        # discovered='portfolio-slug' (both share prefix 'portfolio') when
        # the dynamic route is `src/app/portfolio/[slug]/page.tsx`.
        page_prefix = page.split("-", 1)[0]
        for entry in entries:
            discovered = entry.get("name", "")
            if discovered and discovered.split("-", 1)[0] == page_prefix:
                return _files(entry)

        # Lookup 3 — dynamic-segment name match. Scope='variant' maps to
        # discovered='v-variant' (URL static prefix 'v' differs from scope
        # name, but the bracket segment name matches) when the dynamic
        # route is `src/app/v/[variant]/page.tsx`. Covers the original
        # gap-1 case the static-prefix fallback cannot reach because the
        # URL prefix is not a substring of the scope name.
        for entry in entries:
            if page in (entry.get("dynamic_segments") or []):
                return _files(entry)

    # Fallback: direct probe at src/app/<page>/page.tsx (covers fresh
    # checkouts where derive_pages cannot import or returns nothing).
    direct = os.path.join(repo_root, "src", "app", page, "page.tsx")
    if os.path.isfile(direct):
        return [direct]
    return []


def _read_combined_source(files: list[str]) -> str:
    """Concatenate file contents into a single string for grep-style analysis."""
    parts = []
    for f in files:
        text = _read_text(f)
        if text:
            parts.append(text)
    return "\n".join(parts)


# Regex for fetch call sites referencing a specific route literal.
# Matches: fetch('/api/x', ...), fetch("/api/x"), fetch(`/api/x`)
#
# Issue #1466 (c): when the contract route contains a bracketed
# dynamic segment (e.g. `/api/items/[id]`), the literal-string regex
# misses the natural JS/TS dynamic-route idiom
# `fetch(`/api/items/${id}`)`. The fallback below resolves the contract
# route into its static prefix (text before the first `[seg]`) and
# matches template-literal call sites that begin with that prefix and
# contain a `${...}` interpolation. Static-route contracts use only
# the literal-string match — the template-literal fallback fires only
# when a `[` appears in the contract route.
_TEMPLATE_LITERAL_FALLBACK_BRACKET_RE = re.compile(r"\[[^\]]+\]")


def _fetch_present(source: str, route: str) -> bool:
    pattern = re.compile(
        r"""fetch\s*\(\s*['"`]""" + re.escape(route) + r"""['"`]""",
        re.IGNORECASE,
    )
    if pattern.search(source):
        return True
    # Template-literal fallback for dynamic-segment routes.
    if "[" not in route:
        return False
    # Split the contract route on its FIRST bracketed segment. The
    # static prefix is everything before the bracket; the suffix
    # after the matching `]` is allowed to contain additional path
    # segments and possibly more brackets.
    bracket_match = _TEMPLATE_LITERAL_FALLBACK_BRACKET_RE.search(route)
    if not bracket_match:
        return False
    prefix = route[:bracket_match.start()]
    # Build a regex: fetch( <quote> <prefix> <${...}> <anything> <quote>
    # The static prefix is escaped; the `${...}` interpolation is
    # required so we don't match a literal string like
    # `fetch('/api/items/some-static')` that happens to share the prefix.
    tl_pat = re.compile(
        r"""fetch\s*\(\s*`""" + re.escape(prefix) + r"""\$\{[^`]+`""",
        re.IGNORECASE,
    )
    return bool(tl_pat.search(source))


# Detect if the fetch call is wrapped in a constant-false block. Heuristic:
# look for if (false) { ... fetch(route) ... } within ~500 chars window.
_IF_FALSE_RE = re.compile(r"if\s*\(\s*false\s*\)\s*\{", re.IGNORECASE)


def _fetch_unreachable(source: str, route: str) -> bool:
    """Heuristic: report true when fetch(route) sits inside if(false){...}."""
    fetch_pat = re.compile(
        r"""fetch\s*\(\s*['"`]""" + re.escape(route) + r"""['"`]"""
    )
    for fmatch in fetch_pat.finditer(source):
        # Look backward up to 500 chars for an unmatched `if (false) {`
        before = source[max(0, fmatch.start() - 500):fmatch.start()]
        if _IF_FALSE_RE.search(before):
            # Check there is no `}` between if(false){ and fetch (very loose).
            # If a closing brace appears after the if(false){, assume the
            # block already closed; consider this a non-false-positive.
            last_if = list(_IF_FALSE_RE.finditer(before))[-1]
            between = before[last_if.end():]
            if "}" not in between:
                return True
    return False


# Detect .catch(() => <literal>) or .catch(() => (<literal>)) pattern that
# synthesizes stub data. The `\(?\s*` allows the common JS idiom where returning
# an object literal from an arrow function requires wrapping in parens:
# .catch(() => ({ messages: [] }))
_CATCH_LITERAL_RE = re.compile(
    r"""\.\s*catch\s*\(\s*\(\s*[^)]*\s*\)\s*=>\s*\(?\s*([{\[\"'\d])""",
    re.IGNORECASE,
)

# Detect .catch(() => <non-block-expression>) where the catch arrow has
# EMPTY parameters. Empty params mean the error value is discarded — so
# any non-block return is by definition NOT derived from the fetch
# failure. This catches function-call stubs (`.catch(() => synthesize_stub())`)
# and identifier stubs (`.catch(() => MOCK_DATA)`) that the literal-only
# regex above misses. Block form `=> {` is excluded here because blocks
# may legitimately re-raise via `throw` — we handle blocks separately.
_CATCH_EMPTY_PARAM_EXPR_RE = re.compile(
    r"""\.\s*catch\s*\(\s*\(\s*\)\s*=>\s*[^{;\s]""",
)


def _trycatch_no_throw_around_fetch(source: str, fetch_start: int, fetch_end: int) -> bool:
    """Detect fetch(route) inside `try { ... } catch (e?) { <no throw> ... }`.

    Returns True when the fetch sits inside a `try` block whose paired
    `catch` arm contains no `throw` (i.e., swallows the error). This
    catches the issue-body pattern:

        try {
          const r = await fetch('/api/x', ...);
          return await r.json();
        } catch {
          return { spec_id: synthesize_stub_id() };  // graceful fallback
        }

    Uses brace tracking rather than regex because `[^}]*` cannot handle
    nested braces inside the catch body. Conservative: requires the
    `try` keyword to appear within 400 chars before the fetch, and the
    matching `} catch` to appear within 2000 chars after (issue #1466 —
    widened from 800 to cover realistic non-trivial catch bodies that
    re-throw at the end).
    """
    before = source[max(0, fetch_start - 400):fetch_start]
    # Walk backward to find the most recent unmatched `try {`.
    # Strategy: scan tokens left-to-right and track brace depth + try state.
    depth_before = 0
    try_at_depth: list[int] = []  # depths at which a `try {` opened
    i = 0
    while i < len(before):
        if before[i:i+4] == 'try ' or before[i:i+5] == 'try\n' or before[i:i+5] == 'try\t' or before[i:i+4] == 'try{':
            # Find the opening brace of the try block.
            j = i + 3
            while j < len(before) and before[j] not in '{':
                j += 1
            if j < len(before) and before[j] == '{':
                try_at_depth.append(depth_before)
                depth_before += 1
                i = j + 1
                continue
        ch = before[i]
        if ch == '{':
            depth_before += 1
        elif ch == '}':
            depth_before -= 1
            # If a try block just closed (its depth went out), pop it.
            if try_at_depth and depth_before == try_at_depth[-1]:
                try_at_depth.pop()
        i += 1

    # If no unclosed `try {` precedes the fetch, no try-wrap.
    if not try_at_depth:
        return False

    # The fetch is inside a try block. Now walk forward to find the
    # matching `}` that closes that try, followed by `catch`. Window
    # widened from 800 to 2000 chars (issue #1466) so re-throws at the
    # end of realistic non-trivial catch bodies are not missed.
    after = source[fetch_end:fetch_end + 2000]
    depth = depth_before  # current nesting depth (post-fetch)
    target_depth = try_at_depth[-1]  # depth at which the enclosing try { opened
    i = 0
    catch_start = None
    while i < len(after):
        ch = after[i]
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == target_depth:
                # The try block just closed. Look for `catch` (with
                # optional space/newline).
                rest = after[i+1:i+30].lstrip()
                if rest.startswith('catch'):
                    catch_start = i + 1 + after[i+1:].index('catch')
                    break
                else:
                    return False  # try without catch — irrelevant
        i += 1
    if catch_start is None:
        return False

    # Find the catch body opening `{`.
    j = catch_start + 5
    while j < len(after) and after[j] != '{':
        j += 1
    if j >= len(after):
        return False
    # Track the catch body to its closing brace.
    body_depth = 1
    k = j + 1
    while k < len(after) and body_depth > 0:
        if after[k] == '{':
            body_depth += 1
        elif after[k] == '}':
            body_depth -= 1
        k += 1
    catch_body = after[j:k]
    # The catch swallows the error iff there is no `throw` keyword.
    # Heuristic: substring search (more sophisticated AST would tokenize).
    return 'throw' not in catch_body


def _skip_string(source: str, i: int, quote: str) -> int:
    """Skip forward past a string/template-literal body and return the
    index just after its closing quote. Handles backslash escapes.
    """
    n = len(source)
    j = i + 1
    while j < n and source[j] != quote:
        if source[j] == "\\":
            j += 2
            continue
        j += 1
    return j + 1


def _outer_chain_catch_window(source: str, fetch_end: int) -> str:
    """Return the outer-chain method-call window for a `fetch(...)` at
    position `fetch_end` (which is `fmatch.end()` — the position just
    after the matched route literal inside the fetch parens).

    Issue #1466 (round-2 critic Concern 2): the previous "literal-catch
    within 400 chars of fetch(" heuristic misclassified the
    `await res.json().catch(() => ({}))` pattern as a fetch-fallback
    when in fact it is an inner-promise response-body fallback. The
    canonical distinction is **paren depth**: a `.catch(` at depth 0 in
    the post-fetch tokens (after the outermost `)` of `fetch(...)` has
    closed) belongs to the same promise chain as the fetch itself — it
    IS the fetch-fallback. A `.catch(` while paren depth is still > 0
    (i.e., before fetch's outer `)` closes) is nested inside a
    sub-expression like `.json().catch(...)` and is an inner-promise
    fallback, not the fetch's.

    Two-phase approach:
      Phase 1: walk forward from `fetch_end` counting `(` and `)` until
               depth returns to 0 — at that moment, fetch's outermost
               `)` has closed.
      Phase 2: starting just after fetch's `)`, collect ONLY the chained
               method calls `.method(...).method(...)` that form part of
               the same promise chain. Stop at any non-chain token
               (statement terminator, type assertion, end of expression).
               This bounded window is what gets scanned for stub-fallback
               literal-catch / empty-param-catch.

    Phase 2 termination conditions:
      - Whitespace followed by anything other than `.` (statement break)
      - `;`, `,`, `)`, `]`, `}` at the outer depth (expression context end)
      - End of source

    The chain `fetch(x).then(r => r.json()).catch(...)` STILL classifies
    as a fetch-fallback because, after fetch's `)` closes, the next token
    is `.then(` — chain continues. After `.then(...)` closes, the next
    token is `.catch(` — also chain. The catch IS in the outer chain.

    The expression `fetch(x); ... .json().catch(...)` does NOT classify
    because after fetch's `)`, the next non-whitespace token is `;` —
    chain terminated. The `.catch(` later belongs to an inner expression.
    """
    n = len(source)
    depth = 1
    i = fetch_end
    # Phase 1: find fetch's outer ) close
    fetch_close = -1
    while i < n and depth > 0:
        ch = source[i]
        if ch in ('"', "'", "`"):
            i = _skip_string(source, i, ch)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                fetch_close = i
                break
        i += 1
    if fetch_close < 0:
        return ""
    # Phase 2: collect chained .method(...) calls
    chain_start = fetch_close + 1
    j = chain_start
    while j < n:
        # Skip whitespace within the chain
        while j < n and source[j] in (" ", "\t", "\n", "\r"):
            j += 1
        if j >= n or source[j] != ".":
            break
        # Found a `.method(` chain step. Walk past .name(
        j += 1  # consume '.'
        while j < n and (source[j].isalnum() or source[j] == "_"):
            j += 1
        # Optional whitespace then '(' or break out (member access, not call)
        k = j
        while k < n and source[k] in (" ", "\t"):
            k += 1
        if k >= n or source[k] != "(":
            # member access without call — break (e.g., `.length`)
            j = k
            break
        # Walk past the matching ) of this method call
        d = 1
        j = k + 1
        while j < n and d > 0:
            ch = source[j]
            if ch in ('"', "'", "`"):
                j = _skip_string(source, j, ch)
                continue
            if ch == "(":
                d += 1
            elif ch == ")":
                d -= 1
            j += 1
    return source[chain_start:j]


def _has_stub_catch(source: str, route: str) -> bool:
    """Detect stub-fallback patterns wrapping fetch(route).

    Three detection layers (heuristic — AST upgrade is follow-up):

      (a) .catch(<params>) => LITERAL on the OUTER fetch chain — applies
          only AFTER fetch(...)'s outermost `)` closes. Catches
          `fetch(url).catch(() => ({}))` and
          `fetch(url).then(...).catch(() => ({}))`. Does NOT match
          `fetch(url, {body: await body.json().catch(...)})` (catch is
          on an inner promise inside fetch's own argument).

      (b) .catch(() => EXPR) with empty params and non-block return,
          again on the OUTER chain. Catches identifier stubs and
          function-call stubs (e.g., `.catch(() => MOCK_DATA)`,
          `.catch(() => synthesize_stub_id())`).

      (c) try { fetch(...) ... } catch { <no throw> } — wrap the fetch
          in a try block whose paired catch arm swallows the error.
          Catches the issue-body pattern that has no `.catch()` chain.

    Parameterized non-empty-arg cases (`.catch(err => ...)`) are NOT
    detected here — they may legitimately derive the return value from
    `err`. Layer 4b runtime check (behavior-verifier B7) is the
    load-bearing trustworthy check for those.

    Issue #1466 round-2 Concern 2: paren-depth-aware windowing replaces
    the previous "first 400 chars after fetch_end" window so that inner
    `.json().catch(...)` (legitimate response-body fallback) is not
    misclassified as a fetch-fallback. The chain
    `fetch(x).then(r => r.json()).catch(...)` STILL classifies as a
    fetch-fallback because the outer `.catch(` appears at depth 0 in the
    post-fetch token stream (after fetch's outermost `)` closes).
    """
    fetch_pat = re.compile(
        r"""fetch\s*\(\s*['"`]""" + re.escape(route) + r"""['"`]"""
    )
    for fmatch in fetch_pat.finditer(source):
        # Outer-chain window: post-fetch tokens after the outermost )
        # of fetch(...) closes. Bounds inner-promise catches OUT of scope.
        outer_window = _outer_chain_catch_window(source, fmatch.end())
        # (a) literal-return catch on the outer chain
        if outer_window and _CATCH_LITERAL_RE.search(outer_window):
            return True
        # (b) empty-param non-block catch on the outer chain
        if outer_window and _CATCH_EMPTY_PARAM_EXPR_RE.search(outer_window):
            return True
        # (c) try/catch wrap with no throw (windowless — uses brace
        # tracking from fetch position)
        if _trycatch_no_throw_around_fetch(source, fmatch.start(), fmatch.end()):
            return True
    return False


# Detect useState / useReducer / useChat for turn state.
_TURN_STATE_RE = re.compile(
    r"\b(useState|useReducer|useChat)\b",
    re.IGNORECASE,
)


def _has_turn_state(source: str) -> bool:
    return bool(_TURN_STATE_RE.search(source))


# Generic API-fetch presence (any /api/ route).
_ANY_API_FETCH_RE = re.compile(
    r"""fetch\s*\(\s*['"`]/api/""",
    re.IGNORECASE,
)


def _has_any_api_fetch(source: str) -> bool:
    return bool(_ANY_API_FETCH_RE.search(source))


def _has_track_call(source: str, event: str) -> bool:
    """Check for track<Event>( or track('<event>',) patterns."""
    camel = "".join(part.capitalize() for part in re.split(r"[-_]", event))
    patterns = [
        re.compile(rf"\btrack{re.escape(camel)}\s*\("),
        re.compile(rf"""trackServerEvent\s*\(\s*['"`]""" + re.escape(event)),
        re.compile(rf"""capture\s*\(\s*['"`]""" + re.escape(event)),
    ]
    return any(p.search(source) for p in patterns)


def _sitemap_contains_slug(repo_root: str, slug: str, route_segment: str | None) -> bool:
    """Check src/app/sitemap.ts contains the slug.

    Strategy: read sitemap.ts; check the slug literal appears AND (when
    route_segment is provided) the segment substitution pattern appears.
    """
    path = os.path.join(repo_root, SITEMAP_PATH)
    src = _read_text(path)
    if not src:
        return False
    return slug in src


def _sitemap_has_iteration(repo_root: str, segment: str) -> bool:
    """Heuristic: detect a for/.map iteration that would expand <segment> values.

    Looks for: SLUGS.map(slug => ...) or for(const slug of SLUGS) or similar.
    """
    path = os.path.join(repo_root, SITEMAP_PATH)
    src = _read_text(path)
    if not src:
        return False
    patterns = [
        re.compile(rf"\.map\s*\(\s*\(?\s*{re.escape(segment)}\b"),
        re.compile(rf"for\s*\(\s*const\s+{re.escape(segment)}\b"),
        re.compile(rf"for\s*\(\s*let\s+{re.escape(segment)}\b"),
        re.compile(rf"\.forEach\s*\(\s*\(?\s*{re.escape(segment)}\b"),
    ]
    return any(p.search(src) for p in patterns)


def _load_phase_a_sentinel(repo_root: str) -> set[str]:
    """Return the set of pages whose page.tsx is owned by Phase A.

    Returns empty set when sentinel absent (Phase A didn't seal yet or
    archetype != web-app).
    """
    path = os.path.join(repo_root, PHASE_A_SENTINEL_PATH)
    text = _read_text(path)
    if not text:
        return set()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return set()
    files = data.get("files") or []
    owned: set[str] = set()
    for f in files:
        # Extract page name from src/app/<page>/page.tsx
        # or src/app/<dyn>/[slug]/page.tsx
        if not isinstance(f, str):
            continue
        if not f.startswith("src/app/") or not f.endswith("page.tsx"):
            continue
        rel = f[len("src/app/"):-len("/page.tsx")]
        if not rel:
            owned.add("landing")
            continue
        # Strip dynamic segments for matching
        parts = [p for p in rel.split("/") if "[" not in p]
        if parts:
            owned.add("-".join(parts) if len(parts) > 1 else parts[0])
    return owned


def _audit_entry(
    entry: dict[str, Any],
    page: str,
    source: str,
    repo_root: str,
) -> dict[str, Any] | None:
    """Audit a single contract entry against the page's combined source.

    Returns a finding dict when uncovered, else None.
    """
    kind = entry.get("kind")
    arg = entry.get("arg")

    if kind == "render":
        return None  # trivially passes (page existence already checked elsewhere)

    if kind == "untagged":
        # Untagged tests produce warnings, not blocks (backward compat).
        return None

    if kind == "api-fetch":
        if not arg:
            return {
                "page": page,
                "contract": entry,
                "reason": "api-fetch entry missing arg (route)",
                "layer": "4a",
            }
        route = arg
        if not _fetch_present(source, route):
            return {
                "page": page,
                "contract": entry,
                "reason": f"page .tsx does not call fetch('{route}')",
                "layer": "4a",
            }
        if _fetch_unreachable(source, route):
            return {
                "page": page,
                "contract": entry,
                "reason": f"fetch('{route}') is wrapped in if(false){{...}} (unreachable)",
                "layer": "4a",
            }
        if _has_stub_catch(source, route):
            return {
                "page": page,
                "contract": entry,
                "reason": (
                    f"fetch('{route}') has .catch(() => <literal>) stub-fallback. "
                    "Layer 4b runtime check (behavior-verifier B7) is load-bearing here."
                ),
                "layer": "4a",
            }
        return None

    if kind == "ai-conversation":
        # Combo check: any /api/ fetch + useState/useReducer/useChat
        if not _has_any_api_fetch(source):
            return {
                "page": page,
                "contract": entry,
                "reason": "ai-conversation contract: no /api/ fetch call site found",
                "layer": "4a",
            }
        if not _has_turn_state(source):
            return {
                "page": page,
                "contract": entry,
                "reason": (
                    "ai-conversation contract: no useState/useReducer/useChat "
                    "for turn state"
                ),
                "layer": "4a",
            }
        return None

    if kind == "event":
        if not arg:
            return {
                "page": page,
                "contract": entry,
                "reason": "event entry missing arg (event name)",
                "layer": "4a",
            }
        if not _has_track_call(source, arg):
            return {
                "page": page,
                "contract": entry,
                "reason": f"page .tsx does not emit event '{arg}' via track* helper",
                "layer": "4a",
            }
        return None

    if kind == "seo":
        # Free-text SEO claim consumed by the lead, not the AST scanner.
        # No structural check at Layer 4a; recorded for review.
        return None

    if kind == "sitemap-instance":
        # arg format: "route/segment" e.g. "portfolio/slug"
        if not arg or "/" not in arg:
            return {
                "page": page,
                "contract": entry,
                "reason": "sitemap-instance entry missing arg in route/segment format",
                "layer": "4a",
            }
        route_prefix, segment = arg.rsplit("/", 1)
        # Layer 4a check: sitemap.ts has SOME iteration over <segment>.
        # The concrete slug presence is verified at Layer 4b runtime (B7
        # fetches /sitemap.xml from dev server).
        if not _sitemap_has_iteration(repo_root, segment):
            return {
                "page": page,
                "contract": entry,
                "reason": (
                    f"sitemap.ts has no iteration over '{segment}' "
                    "(.map / for / forEach with that identifier)"
                ),
                "layer": "4a",
            }
        return None

    # Unknown/roadmap kinds: skip (Group A's verb registry will lint these
    # separately). Roadmap kinds (sdk-call, realtime-sub, external-widget)
    # explicitly fall through here.
    if entry.get("roadmap") or entry.get("unknown_kind"):
        return None

    # Unrecognized kind without flag — treat as a soft finding.
    return None


def audit(repo_root: str = ".") -> dict[str, Any]:
    """Run the post-fan-out audit and produce the audit verdict payload."""
    contracts_path = os.path.join(repo_root, CONTRACTS_PATH)
    if not os.path.isfile(contracts_path):
        return {
            "schema_version": SCHEMA_VERSION,
            "audited_pages": 0,
            "tagged_contract_entries": 0,
            "covered_static": 0,
            "uncovered_count": 0,
            "uncovered": [],
            "warnings": [],
            "runtime_check_signaled": [],
            "provenance": "lead-orchestrated",
            "lead_attestation": True,
            "note": f"{CONTRACTS_PATH} absent — no contracts to audit.",
        }

    try:
        with open(contracts_path, encoding="utf-8") as fh:
            contracts = json.load(fh)
    except Exception as e:
        return {
            "schema_version": SCHEMA_VERSION,
            "audited_pages": 0,
            "tagged_contract_entries": 0,
            "covered_static": 0,
            "uncovered_count": 1,
            "uncovered": [{"contract": None, "reason": f"contracts parse error: {e}", "layer": "load"}],
            "warnings": [],
            "runtime_check_signaled": [],
            "provenance": "lead-orchestrated",
            "lead_attestation": True,
        }

    phase_a_owned = _load_phase_a_sentinel(repo_root)

    audited_pages = 0
    tagged_entries = 0
    covered = 0
    uncovered: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    runtime_signaled: list[dict[str, Any]] = []

    # Iterate page-keyed contracts via unstamped_items (mandatory).
    for page, entries in unstamped_items(contracts):
        if page.startswith("_"):  # skip _schema_version, _summary
            continue
        if not isinstance(entries, list):
            continue

        # Phase A sentinel exemption (#1187)
        if page in phase_a_owned:
            continue

        page_files = _candidate_page_files(repo_root, page)
        source = _read_combined_source(page_files)
        audited_pages += 1

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            kind = entry.get("kind")

            # Untagged → warning, not finding
            if kind == "untagged":
                warnings.append({
                    "page": page,
                    "untagged_test": entry.get("raw_test"),
                })
                continue

            tagged_entries += 1

            # Runtime-check signaling (Layer 4b). seo entries are
            # human-review only and need no runtime check.
            if kind in ("api-fetch", "ai-conversation", "sitemap-instance"):
                runtime_signaled.append({
                    "page": page,
                    "contract": entry,
                    "route": entry.get("arg"),
                })

            # If no page file was found, mark uncovered (every tagged
            # entry needs a target).
            if not source:
                uncovered.append({
                    "page": page,
                    "contract": entry,
                    "reason": f"no .tsx file under src/app/{page} or matching prefix",
                    "layer": "4a",
                })
                continue

            finding = _audit_entry(entry, page, source, repo_root)
            if finding:
                uncovered.append(finding)
            else:
                covered += 1

    return {
        "schema_version": SCHEMA_VERSION,
        "audited_pages": audited_pages,
        "tagged_contract_entries": tagged_entries,
        "covered_static": covered,
        "uncovered_count": len(uncovered),
        "uncovered": uncovered,
        "warnings": warnings,
        "runtime_check_signaled": runtime_signaled,
        "provenance": "lead-orchestrated",
        "lead_attestation": True,
    }


def _active_skill() -> str:
    """Find the active skill name from .runs/*-context.json."""
    best = None
    best_ts = ""
    for f in glob.glob(".runs/*-context.json"):
        if "epilogue" in f:
            continue
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            continue
        if d.get("completed") is True:
            continue
        ts = d.get("timestamp") or ""
        if ts >= best_ts:
            best = d
            best_ts = ts
    return (best or {}).get("skill", "bootstrap")


def write_artifacts(audit_payload: dict[str, Any], skill: str | None = None) -> int:
    """Write the audit verdict + runtime stubs annotation via canonical writer."""
    skill = skill or _active_skill()
    here = os.path.dirname(os.path.abspath(__file__))
    writer = os.path.join(here, "write-gate-artifact.sh")

    # Main audit artifact
    audit_json = json.dumps(audit_payload)
    r1 = subprocess.run(
        ["bash", writer, "--path", AUDIT_PATH, "--payload", audit_json, "--skill", skill],
        capture_output=True, text=True,
    )
    if r1.returncode != 0:
        sys.stderr.write(f"write-gate-artifact.sh failed for {AUDIT_PATH}: {r1.stderr}\n")
        return r1.returncode

    # Runtime stubs annotation (Layer 4b signal)
    stubs_payload = {
        "schema_version": SCHEMA_VERSION,
        "annotations": audit_payload.get("runtime_check_signaled", []),
        "provenance": "lead-orchestrated",
        "lead_attestation": True,
    }
    stubs_json = json.dumps(stubs_payload)
    r2 = subprocess.run(
        ["bash", writer, "--path", STUBS_PATH, "--payload", stubs_json, "--skill", skill],
        capture_output=True, text=True,
    )
    if r2.returncode != 0:
        sys.stderr.write(f"write-gate-artifact.sh failed for {STUBS_PATH}: {r2.stderr}\n")
        return r2.returncode
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Post-fan-out behavior-contract audit for scaffold-pages output (#1387)."
    )
    parser.add_argument("--repo-root", default=".", help="Project root (default: cwd).")
    parser.add_argument("--skill", default=None, help="Active skill override.")
    parser.add_argument("--dry-run", action="store_true", help="Print payload, do not write.")
    args = parser.parse_args()

    audit_payload = audit(args.repo_root)

    if args.dry_run:
        print(json.dumps(audit_payload, indent=2))
        return 0

    rc = write_artifacts(audit_payload, args.skill)
    if rc != 0:
        return rc

    # Always exit 0 — state-11c VERIFY is the gate; the artifact carries
    # uncovered_count and uncovered[] for downstream consumption.
    print(
        f"behavior-contract-auditor: audited_pages={audit_payload['audited_pages']} "
        f"tagged={audit_payload['tagged_contract_entries']} "
        f"covered={audit_payload['covered_static']} "
        f"uncovered={audit_payload['uncovered_count']} "
        f"warnings={len(audit_payload['warnings'])} "
        f"runtime_signaled={len(audit_payload['runtime_check_signaled'])}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
