#!/usr/bin/env python3
"""Canonical page-inventory derivation for experiment.yaml.

Single source of truth for "what pages must exist on disk" (SET semantics)
and "what is the user journey" (LIST semantics). All count-based and
inventory-based consumers MUST call these functions; raw access to
`golden_path` for these purposes is forbidden by `verify-linter.sh`
field_role_map rule.

Also provides design-critic orchestration helpers (#1042):
- `derive_page_set_for_design_critic()` — operational page list with
  concretized test URLs for dynamic routes.
- `derive_page_images()` — two-layer static image-render classifier.

See .claude/templates/experiment-yaml.md for the full schema.
"""
import glob
import json
import os
import re
import sys
from typing import Any


# Pages that scaffold-pages does NOT own (other agents handle them).
_EXCLUDED_FROM_SCOPE = {None, "", "landing"}


def derive_scope_pages(experiment: dict[str, Any]) -> list[str]:
    """Return the sorted set of pages that must exist on disk for web-app archetype.

    Set semantics: order does not matter. Use this for inventory counts,
    spawn lists, sitemap entries, and existence checks.

    Sources, in union:
      1. golden_path[*].page  (where present)
      2. behaviors[*].pages   (where present — required for web-app + actor:user)
      3. auth-derived         (login, signup if stack.auth is set)

    Excluded: None, empty string, and "landing" (scaffold-landing owns it).
    """
    pages: set[str] = set()

    for step in (experiment.get("golden_path") or []):
        if isinstance(step, dict):
            page = step.get("page")
            if page:
                pages.add(page)

    for behavior in (experiment.get("behaviors") or []):
        if not isinstance(behavior, dict):
            continue
        for page in (behavior.get("pages") or []):
            if page:
                pages.add(page)

    stack = experiment.get("stack") or {}
    if stack.get("auth"):
        pages.add("login")
        pages.add("signup")

    return sorted(p for p in pages if p not in _EXCLUDED_FROM_SCOPE)


def derive_validation_pages(experiment: dict[str, Any]) -> list[str]:
    """Return the page set for behavior.pages MEMBERSHIP validation.

    Same union as `derive_scope_pages()` but does NOT exclude "landing".
    Use this set when validating that every `behaviors[*].pages` element
    references a real surface in the experiment — landing IS a real surface
    (root `/`), even though it has no folder under `src/app/<page>/` (the
    scaffold-landing agent owns it).

    Inventory consumers (sitemap, nav-bar, page-existence audit, scaffold-pages
    spawn list) MUST keep using `derive_scope_pages()` because they care about
    disk presence. Only consumers performing membership validation against
    `behaviors[*].pages` should use this helper — currently that is gate-keeper
    BG2 check 3c-2 (`agents/gate-keeper.md`). See issue #1184.
    """
    pages: set[str] = set()

    for step in (experiment.get("golden_path") or []):
        if isinstance(step, dict):
            page = step.get("page")
            if page:
                pages.add(page)

    for behavior in (experiment.get("behaviors") or []):
        if not isinstance(behavior, dict):
            continue
        for page in (behavior.get("pages") or []):
            if page:
                pages.add(page)

    stack = experiment.get("stack") or {}
    if stack.get("auth"):
        pages.add("login")
        pages.add("signup")

    return sorted(p for p in pages if p not in {None, ""})


def derive_public_paths(experiment: dict[str, Any]) -> list[str]:
    """Return the sorted set of route paths that the auth proxy/middleware
    treats as public (no auth required).

    Issue #1126: the auth template's hardcoded `publicPaths` array drifts from
    `behaviors[*]` semantics whenever an experiment declares anonymous-allowed
    pages outside the static defaults (e.g., a public `/spec` builder, public
    quote-view pages). Bootstrap MUST substitute the derived array into the
    proxy/middleware template at scaffold-libs time.

    The public set is the union of:
      1. Marketing landing route ("/") -- always public
      2. Auth landing pages ("/login", "/signup") -- always public
      3. Auth callback routes ("/auth/callback", "/auth/reset-password") -- always public
      4. Health endpoint ("/api/health") -- always public
      5. Behaviors[*].pages where every owning behavior has `anonymous_allowed: true`
         (intersection / fail-secure: a page shared between two behaviors is
         public only if BOTH behaviors mark it anonymous_allowed)

    `behavior.anonymous_allowed: bool (default false)` is the explicit
    schema marker. Absence means "auth required" (default-deny). This is
    distinct from `requires_role`, which gates AUTHENTICATED users by role.
    The two are mutually exclusive (validate-experiment.py enforces).

    Variant routes "/v/*" and the analytics ingest prefix "/ingest/" are
    handled separately by the proxy template (path-prefix match), not
    enumerated here.
    """
    auth_landing = {"/", "/login", "/signup", "/auth/callback", "/auth/reset-password"}
    api_public = {"/api/health"}

    # Map page -> list of behaviors that own it (for intersection check).
    page_owners: dict[str, list[dict]] = {}
    for behavior in (experiment.get("behaviors") or []):
        if not isinstance(behavior, dict):
            continue
        for page in (behavior.get("pages") or []):
            if not page:
                continue
            page_owners.setdefault(page, []).append(behavior)

    # Page is public iff EVERY owning behavior marks it anonymous_allowed=true
    # (fail-secure intersection). One auth-required behavior anywhere on the
    # page keeps it auth-gated.
    behavior_public: set[str] = set()
    for page, owners in page_owners.items():
        if owners and all(b.get("anonymous_allowed") is True for b in owners):
            # Convert page slug to route ("/<page>")
            behavior_public.add(f"/{page}")

    return sorted(auth_landing | api_public | behavior_public)


def derive_funnel_steps(experiment: dict[str, Any]) -> list[dict]:
    """Return the ordered list of golden_path steps for sequence-based consumers.

    List semantics: order matters. Use this for nav-bar generation,
    funnel test sequences, sitemap ordering, and journey walkthroughs.

    Returns the raw list (each entry is a dict with `step`, `event`, `page`).
    Callers iterate in order; do not call set() or len() on this for inventory
    purposes — use derive_scope_pages() instead.
    """
    return list(experiment.get("golden_path") or [])


def derive_dynamic_only_pages(
    experiment: dict[str, Any],
    repo_root: str = ".",
) -> dict[str, str]:
    """Classify each scope page by route shape (GECR — closes #1473).

    Returns a dict mapping each scope-page slug (from derive_scope_pages())
    to one of four classification strings:

      - "static"       — `src/app/<page>/page.tsx` exists, no `[*]/page.tsx`
                         children. Bare-slug href= in nav-bar is sufficient
                         (current BG2-WIRE check 1 semantics).
      - "dynamic-only" — no `src/app/<page>/page.tsx`, at least one
                         `src/app/<page>/[*]/page.tsx` child. Bare-slug
                         `href="/<page>"` is INSUFFICIENT (would 404);
                         require template-literal navigation
                         `<Link href={`/<page>/${...}`}>` somewhere reachable.
      - "mixed"        — BOTH a static `page.tsx` AND dynamic children.
                         Both bare-slug AND template-literal navigation
                         expected (list view + detail view both reachable).
      - "absent"       — neither file present (declared in experiment.yaml
                         but not yet scaffolded). Trivially passes — other
                         BG2 checks (3c) enforce existence separately.

    Slug-suffix handling: scope-page slugs come from derive_scope_pages()
    which returns canonical short slugs from experiment.yaml (e.g.,
    `portfolio-detail`). The filesystem folder may be a static prefix of
    the slug (e.g., `src/app/portfolio/[slug]/page.tsx`). This function
    handles the mismatch via the same static-prefix fallback used by
    derive_page_set_for_design_critic (lines 362-374): for each scope page,
    if the literal folder is absent, fall back to the slug's static prefix
    (`slug.split("-", 1)[0]`).

    Dynamic-segment forms:
      - `[id]`        — regular dynamic; contributes to "dynamic-only" or "mixed"
      - `[...slug]`   — catch-all; must always be parameterized → contributes to
                        "dynamic-only"
      - `[[...slug]]` — optional catch-all; matches both `/` and `/anything` →
                        contributes to "mixed" (bare slug also reachable)

    Service/cli archetypes (no `src/app/`): returns {} (consistent with
    derive_landing_for_design_critic returning None for these archetypes).

    Round-2 critic mitigations applied:
      - Concern 487fdf73cf62 (slug suffix mismatch): direct filesystem scan
        with explicit static-prefix fallback — does NOT route through
        derive_page_set_for_design_critic's slug-munging path.
      - Concern cfb66259539e (mixed-route ambiguity): explicit `mixed` state
        rather than collapsing to dynamic-only or static.
      - Concern Plan-Agent-B-5 (REPLACE-mode breaks static pages): trinary
        classification means caller can branch behavior per page.
    """
    src_app = os.path.join(repo_root, "src", "app")
    if not os.path.isdir(src_app):
        return {}

    scope_pages = derive_scope_pages(experiment)
    result: dict[str, str] = {}

    for slug in scope_pages:
        # Try literal slug folder first; fall back to static prefix
        # (`portfolio-detail` → `portfolio`) so hyphenated experiment.yaml
        # slugs find their on-disk folder.
        candidate_folders: list[str] = [slug]
        if "-" in slug:
            prefix = slug.split("-", 1)[0]
            if prefix and prefix != slug:
                candidate_folders.append(prefix)

        static_index_found = False
        regular_dynamic_children = False
        optional_catch_all_children = False
        folder_found = False

        for folder in candidate_folders:
            folder_abs = os.path.join(src_app, folder)
            if not os.path.isdir(folder_abs):
                continue
            folder_found = True

            # Static index check
            for ext in (".tsx", ".jsx", ".ts", ".js"):
                if os.path.isfile(os.path.join(folder_abs, f"page{ext}")):
                    static_index_found = True
                    break

            # Dynamic child check — glob.escape protects bracket folders
            # (see #1450 gap 2 in derive_pages.py:328-352)
            escaped = glob.escape(folder_abs)
            for ext in ("tsx", "jsx", "ts", "js"):
                # Look for any */page.<ext> under direct children
                for child_page in glob.glob(
                    os.path.join(escaped, "*", f"page.{ext}")
                ):
                    # Extract the immediate-child segment name to classify
                    rel = os.path.relpath(child_page, folder_abs)
                    parts = rel.split(os.sep)
                    if not parts:
                        continue
                    segment = parts[0]
                    if not segment.startswith("["):
                        # static sibling (e.g., src/app/<page>/about/page.tsx);
                        # doesn't make this a dynamic route
                        continue
                    # Detect optional catch-all `[[...slug]]` (starts with `[[`)
                    if segment.startswith("[["):
                        optional_catch_all_children = True
                    else:
                        regular_dynamic_children = True
            # Stop after first folder found — don't double-count prefix
            # fallback when literal folder also exists.
            if folder_found:
                break

        if not folder_found:
            result[slug] = "absent"
            continue

        # Bare-slug reachability: either a static page.tsx OR an optional
        # catch-all (`[[...slug]]`) which matches `/` with no parameter.
        bare_slug_reachable = static_index_found or optional_catch_all_children
        # Template-literal use case exists when a regular dynamic segment
        # `[id]` is present (route REQUIRES a parameter to render).
        template_literal_required = regular_dynamic_children

        if bare_slug_reachable and template_literal_required:
            # Both nav forms expected — list view (bare slug) + detail (template literal)
            result[slug] = "mixed"
        elif template_literal_required:
            # Only `[id]`-style children — bare slug would 404
            result[slug] = "dynamic-only"
        elif bare_slug_reachable:
            # Static or optional-catch-all-only — bare slug works, no template literal needed
            result[slug] = "static"
        else:
            # Folder exists but no recognizable page.* — treat as absent
            result[slug] = "absent"

    return result


# ---------------------------------------------------------------------------
# Design-critic orchestration helpers (#1042 / Session C)
# ---------------------------------------------------------------------------

# Synthetic test IDs for dynamic route segments. DEMO_MODE Supabase stub
# returns null from .single() for any ID, so the exact value only needs to be
# URL-safe and deterministic. Choosing distinctly-fixture values (nil UUID,
# "demo-fixture-*") avoids collision with real production IDs if these URLs
# ever leak into non-DEMO_MODE contexts.
_SYNTHETIC_SEGMENT_IDS: dict[str, str] = {
    "id": "00000000-0000-0000-0000-000000000000",
    "slug": "demo-fixture-slug",
    "token": "demo-fixture-token",
    "uuid": "00000000-0000-0000-0000-000000000000",
}

# Static image-render detection patterns (Layer 1 + Layer 2).
# Matching any of these in a .tsx / .jsx file classifies the owning page
# has_images=true.
_IMAGE_PATTERNS: list[str] = [
    r"<Image\b",
    r'from\s+["\']next/image["\']',
    r"<img\b",
    r"public/images/",
    r"empty-state",
]

# Route-path bracket regex identifies dynamic routes (e.g., /quote/[id],
# /docs/[[...slug]]). Any bracket counts.
_DYNAMIC_SEGMENT_RE = re.compile(r"\[([^\]]+)\]")

# Cap filesystem-scan patterns to tsx/jsx under src/app, excluding API routes.
_PAGE_FILE_GLOBS = (
    "src/app/**/page.tsx",
    "src/app/**/page.jsx",
    "src/app/**/page.ts",
    "src/app/**/page.js",
)


def _concretize_url(route_pattern: str) -> str:
    """Substitute each [segment] with a synthetic test ID deterministically."""
    def sub(m: "re.Match[str]") -> str:
        raw = m.group(1)
        # Handle catch-all / optional-catchall ([...slug], [[...slug]])
        stripped = raw.lstrip(".").lstrip("[").rstrip("]")
        key = stripped.lower()
        return _SYNTHETIC_SEGMENT_IDS.get(key, f"demo-fixture-{key}")
    return _DYNAMIC_SEGMENT_RE.sub(sub, route_pattern)


def _path_to_page_info(page_file: str) -> tuple[str, str]:
    """Convert src/app/<p>/page.tsx → (page_name, route_pattern).

    page_name is the folder slug (or "landing" if directly under src/app).
    route_pattern preserves [segment] literals for dynamic routes.

    For dynamic routes, the page_name suffixes the bracket-segment names so
    src/app/portfolio/page.tsx and src/app/portfolio/[slug]/page.tsx produce
    DIFFERENT slugs (`portfolio` and `portfolio-slug`) — this prevents
    discovery-dict collisions and downstream trace-filename collisions
    (design-critic-<page_name>.json) when both routes coexist (#1144).
    """
    # Strip src/app/ prefix and /page.<ext> suffix
    rel = page_file
    if rel.startswith("src/app/"):
        rel = rel[len("src/app/"):]
    # rel is now e.g. "quote/[id]/page.tsx" or "page.tsx"
    parts = rel.split("/")
    filename = parts[-1]
    folder_parts = parts[:-1]
    if not filename.startswith("page."):
        # Not a recognisable page file — caller should have filtered
        return ("", "")
    if not folder_parts:
        return ("landing", "/")
    route = "/" + "/".join(folder_parts)
    # Slug is the last non-bracketed folder name; for purely-dynamic leaf
    # (e.g. src/app/[locale]/page.tsx), fall back to the raw folder name.
    non_bracket_parts = [p for p in folder_parts if "[" not in p]
    if non_bracket_parts:
        base = non_bracket_parts[-1]
    else:
        base = folder_parts[-1].strip("[]")
    # #1144: append bracket-segment names to disambiguate dynamic routes from
    # their static parents. Each segment contributes its inner identifier
    # (stripped of optional-catchall syntax: leading "[" + any number of dots,
    # trailing "]", whitespace). When the leaf folder is itself the dynamic
    # segment (no static parent — e.g., src/app/[locale]/page.tsx where
    # base==folder_parts[-1]), keep the base alone to avoid `locale-locale`.
    has_static_parent = bool(non_bracket_parts)
    bracket_parts = []
    for p in folder_parts:
        m = _DYNAMIC_SEGMENT_RE.search(p)
        if m:
            # Strip in order: trailing `]` (defensive — regex usually consumed it),
            # leading `[` (optional-catchall outer bracket already inside the captured
            # group for [[...slug]]), then any number of leading dots (catchall `...`).
            inner = m.group(1).rstrip("]").lstrip("[").lstrip(".")
            if inner:
                bracket_parts.append(inner)
    if has_static_parent and bracket_parts:
        name = "-".join([base, *bracket_parts])
    else:
        name = base
    return (name, route)


def derive_page_set_for_design_critic(
    experiment: dict[str, Any],
    repo_root: str = ".",
) -> list[dict[str, Any]]:
    """Return the list of pages for design-critic per-page spawns (#1042).

    Matches state-3a Stage-1 discovery semantics: filesystem scan UNION
    golden_path UNION auth-derived, EXCLUDING "landing" from the operational
    list. Landing is exposed separately via :func:`derive_landing_for_design_critic`
    and surfaces as the sibling ``landing`` field in
    ``.runs/design-page-set.json`` (state-2a writes both). State-3a Stage 1
    spawns the landing-critic alongside non-landing per-page critics in the
    same parallel batch (#1143). Excluding landing from this list is required
    because state-3b VERIFY iterates ``pages`` to assert each page emits
    ``image_issues_for_landing``, a field the landing critic does NOT emit
    (landing OWNS image decisions and emits ``candidates_tried`` instead).

    Each entry:
        {
            "name": <page-slug>,
            "route_pattern": "/<slug>" or "/<slug>/[<seg>]" (literal bracket),
            "test_url":     concrete URL safe for page.goto,
            "source_files": [<repo-relative .tsx/.jsx paths>],
            "dynamic_segments": [<segment-name>, ...]  (empty for static routes)
        }
    """
    # 1. Filesystem scan
    discovered: dict[str, dict[str, Any]] = {}
    for pattern in _PAGE_FILE_GLOBS:
        for p in glob.glob(os.path.join(repo_root, pattern), recursive=True):
            rel = os.path.relpath(p, repo_root).replace(os.sep, "/")
            # Skip API routes
            if "/api/" in rel or rel.startswith("api/"):
                continue
            name, route = _path_to_page_info(rel)
            if not name:
                continue
            entry = discovered.setdefault(
                name,
                {
                    "name": name,
                    "route_pattern": route,
                    "source_files": [],
                    "dynamic_segments": [
                        m.group(1) for m in _DYNAMIC_SEGMENT_RE.finditer(route)
                    ],
                },
            )
            if rel not in entry["source_files"]:
                entry["source_files"].append(rel)
            # Also enumerate nested .tsx/.jsx files under this page's folder.
            # #1450 gap 2: glob.glob interprets `[seg]` in dynamic-route
            # folder names (e.g., src/app/portfolio/[slug]/) as a character
            # class, so the recursive pattern returns [] for dynamic routes.
            # Escape the folder portion with glob.escape so bracket segments
            # are treated as literals; the `**/*.<ext>` glob portion stays
            # unescaped to preserve recursion semantics.
            folder = os.path.dirname(rel)
            if folder:
                folder_abs = os.path.join(repo_root, folder)
                escaped = glob.escape(folder_abs)
                for ext in ("tsx", "jsx"):
                    # Two passes: (a) same-folder files (no `**` so siblings
                    # like `portfolio-client.tsx` appear), (b) recursive
                    # subdir files.
                    same_dir = glob.glob(os.path.join(escaped, f"*.{ext}"))
                    nested = glob.glob(
                        os.path.join(escaped, f"**/*.{ext}"),
                        recursive=True,
                    )
                    for nrel in same_dir + nested:
                        nrel_norm = os.path.relpath(nrel, repo_root).replace(
                            os.sep, "/"
                        )
                        if nrel_norm not in entry["source_files"]:
                            entry["source_files"].append(nrel_norm)

    # 2. Union with golden_path + behavior.pages + auth-derived via
    #    derive_scope_pages (already excludes "landing"). For entries not yet
    #    discovered, the slug references no file on disk — emit a stderr
    #    warning and skip from the operational list (#1144). The warning
    #    surfaces the underlying scaffold-pages drift (slug declared in
    #    experiment.yaml but no matching page file) without polluting state-3a
    #    with phantom URLs that 404 in design-critic.
    scope_names = derive_scope_pages(experiment)
    for name in scope_names:
        if name in discovered:
            continue
        # The slug may correspond to a dynamic route whose discovered name has
        # been suffixed (e.g., experiment.yaml says "portfolio-detail" and the
        # file lives at src/app/portfolio/[slug]/page.tsx → discovered as
        # "portfolio-slug"). Skip the warning when ANY discovered entry's
        # static prefix matches the scope name.
        prefix_match = any(
            disc_name.split("-", 1)[0] == name for disc_name in discovered
        )
        if prefix_match:
            continue
        sys.stderr.write(
            f"WARN: derive_pages — scope page '{name}' has no matching file under "
            f"src/app/. Skipping from design-critic operational list. "
            f"(scaffold-pages drift; see #1144)\n"
        )

    # 3. Exclude landing from the operational list — it is exposed via the
    #    sibling `landing` field in design-page-set.json (state-2a writes both).
    #    state-3a Stage 1 spawns landing-critic separately because:
    #      a. Landing has full read-write access to .runs/image-candidates.json
    #         (per design-critic.md: "Landing-page critic owns ALL image
    #         decisions"). Non-landing critics get read-only context.
    #      b. Landing's trace must NOT emit `image_issues_for_landing` (it owns
    #         image decisions). Including landing in `pages` would corrupt
    #         state-3b VERIFY's per-page iteration that requires that field.
    #    See #1143.
    discovered.pop("landing", None)

    # 4. Build final entries with concretized test_urls, sorted by name
    out: list[dict[str, Any]] = []
    for name in sorted(discovered):
        entry = discovered[name]
        entry["test_url"] = _concretize_url(entry["route_pattern"])
        # Deterministic source_files order
        entry["source_files"] = sorted(entry["source_files"])
        out.append(entry)
    return out


def derive_landing_for_design_critic(
    repo_root: str = ".",
) -> dict[str, Any] | None:
    """Return the operational landing entry for state-3a Stage 1 spawn (#1143).

    Returns None when ``src/app/page.{tsx,jsx,ts,js}`` does not exist (e.g.,
    archetype != web-app, or web-app project pre-scaffold-pages).

    Schema mirrors :func:`derive_page_set_for_design_critic` per-page entries
    so state-3a Stage 1 can plug landing into the same parallel spawn batch
    using the existing prompt template.

    Source files are discovered by globbing ``src/app/page.*`` (extensions in
    ``{tsx,jsx,ts,js}`` per ``_PAGE_FILE_GLOBS``) — robust across file
    extensions, unlike the prior hardcoded ``["src/app/page.tsx"]``.
    """
    candidates = sorted(
        os.path.relpath(p, repo_root).replace(os.sep, "/")
        for p in glob.glob(os.path.join(repo_root, "src/app/page.*"))
        if p.endswith((".tsx", ".jsx", ".ts", ".js"))
    )
    if not candidates:
        return None
    return {
        "name": "landing",
        "route_pattern": "/",
        "test_url": "/",
        "source_files": candidates,
        "dynamic_segments": [],
    }


def dynamic_public_pages(
    experiment: dict[str, Any],
    repo_root: str = ".",
) -> list[dict[str, Any]]:
    """Enumerate concrete URL instances for dynamic-segment public pages (#1387).

    For each behavior with ``anonymous_allowed=true`` AND a declared
    ``dynamic_segments`` map of ``{segment_name: [value, ...]}``, expand
    into concrete entries the sitemap.ts emitter can iterate.

    Schema (experiment.yaml):
        behaviors:
          - id: b-13
            pages: [portfolio-detail]
            anonymous_allowed: true
            dynamic_segments:
              slug: [harborline-internal-orders, northwind-tutoring-marketplace,
                     tinroof-photo-orders-refunded]

    Returns: list of dicts sorted by (page, segment, value):
        [
          {
            "page": "portfolio-detail",
            "segment": "slug",
            "value": "harborline-internal-orders",
            "route_pattern": "/portfolio/[slug]",  # from filesystem scan or None
            "concrete_url": "/portfolio/harborline-internal-orders",  # or None when no route_pattern
          },
          ...
        ]

    The route_pattern is derived by matching the behavior's pages against
    discovered dynamic routes (filesystem scan via
    ``derive_page_set_for_design_critic``). When no matching dynamic
    route exists for the declared segment, the entry still appears with
    ``route_pattern=None``; sitemap emitter MUST skip those entries
    (warn-only — auditor surfaces them as findings).

    Warning emission (#1387 round-2 caveat 2c8be80f0b5b): when a
    behavior has ``anonymous_allowed=true`` AND its pages include any
    discovered dynamic route BUT it has no ``dynamic_segments``
    declaration, emit stderr warning. state-11c audit (F2) treats this
    warning as a BLOCK, not a soft warning.

    Empty list when no behavior declares dynamic_segments. Filesystem-
    independent failure mode: when repo_root has no src/app/ tree, the
    route_pattern lookup short-circuits to None for all entries.
    """
    # Discover dynamic routes from filesystem (once, shared across behaviors).
    try:
        discovered = derive_page_set_for_design_critic(experiment, repo_root)
    except Exception:
        discovered = []

    # Map: page-slug-prefix -> {route_pattern, segments}
    # (e.g., portfolio -> {route_pattern: "/portfolio/[slug]", segments: ["slug"]})
    # We index by the static prefix of the discovered entry's name (before
    # the first "-") so behaviors that declare pages: [portfolio-detail]
    # can match a discovered "portfolio-slug" route via static prefix
    # "portfolio".
    prefix_to_route: dict[str, dict[str, Any]] = {}
    for entry in discovered:
        segments = entry.get("dynamic_segments") or []
        if not segments:
            continue
        name = entry.get("name") or ""
        prefix = name.split("-", 1)[0] if "-" in name else name
        prefix_to_route.setdefault(prefix, {
            "route_pattern": entry.get("route_pattern"),
            "segments": segments,
            "name": name,
        })

    out: list[dict[str, Any]] = []
    for behavior in (experiment.get("behaviors") or []):
        if not isinstance(behavior, dict):
            continue
        if behavior.get("anonymous_allowed") is not True:
            continue
        pages = behavior.get("pages") or []
        dyn_segments = behavior.get("dynamic_segments")

        # Determine eligibility for the missing-declaration warning.
        eligible_dynamic_pages: list[str] = []
        for page in pages:
            if not page:
                continue
            # A page is "eligible" iff its static prefix maps to a discovered
            # dynamic route. Without filesystem state we cannot detect this;
            # in that case eligible list is empty (no warning emitted).
            prefix = page.split("-", 1)[0] if "-" in page else page
            if prefix in prefix_to_route:
                eligible_dynamic_pages.append(page)

        if not dyn_segments:
            for page in eligible_dynamic_pages:
                sys.stderr.write(
                    f"WARN: derive_pages — behavior with anonymous_allowed=true "
                    f"and dynamic-segment page '{page}' lacks dynamic_segments "
                    f"declaration (#1387). State-11c audit blocks on this.\n"
                )
            continue

        if not isinstance(dyn_segments, dict):
            sys.stderr.write(
                f"WARN: derive_pages — dynamic_segments must be a dict "
                f"{{segment: [value...]}}, got {type(dyn_segments).__name__}\n"
            )
            continue

        for page in pages:
            if not page:
                continue
            prefix = page.split("-", 1)[0] if "-" in page else page
            route_info = prefix_to_route.get(prefix)
            route_pattern = route_info.get("route_pattern") if route_info else None

            for segment, values in dyn_segments.items():
                if not isinstance(values, list):
                    continue
                for value in values:
                    if not value:
                        continue
                    if route_pattern and f"[{segment}]" in route_pattern:
                        concrete_url = route_pattern.replace(f"[{segment}]", str(value))
                    else:
                        concrete_url = None
                    out.append({
                        "page": page,
                        "segment": segment,
                        "value": str(value),
                        "route_pattern": route_pattern,
                        "concrete_url": concrete_url,
                    })

    out.sort(key=lambda e: (e["page"], e["segment"], e["value"]))
    return out


def _grep_image_patterns(file_path: str) -> list[str]:
    """Return the subset of _IMAGE_PATTERNS that match in the file, or []."""
    if not os.path.isfile(file_path):
        return []
    try:
        with open(file_path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return []
    matched: list[str] = []
    for pat in _IMAGE_PATTERNS:
        if re.search(pat, text):
            matched.append(pat)
    return matched


# Regex for top-level relative imports that can be resolved to src/components
# or src/lib. Single line captures the quoted path.
_IMPORT_RE = re.compile(
    r'^\s*import\s+(?:[^"\']+from\s+)?["\']([^"\']+)["\'];?\s*$',
    re.MULTILINE,
)


def _resolve_import(
    importer_path: str, import_spec: str, repo_root: str
) -> str | None:
    """Resolve an import spec to a repo-relative source-file path.

    Handles:
      - "@/components/foo" → "src/components/foo.tsx" (or .jsx/.ts/.js)
      - "@/lib/bar"        → "src/lib/bar.tsx"
      - "@/app/<route>/x"  → "src/app/<route>/x.{tsx,jsx,ts,js}" — only when
        the importer is itself under src/app/<route>/ (#1273: co-located
        route data modules like src/app/portfolio/cases.ts referenced from
        src/app/portfolio/[slug]/page.tsx). The boundary check prevents
        Layer 2 from leaking src/app/ resolution to src/lib/ importers.
      - relative (./ or ../) paths resolved against importer's directory,
        but ONLY if the resolved path sits under src/components/, src/lib/,
        or — when the importer is itself under src/app/ — src/app/.
    Returns None when the import cannot be resolved to a source file under
    those allowed trees.
    """
    importer_under_app = importer_path.startswith("src/app/")
    allowed_prefixes = ("src/components/", "src/lib/")
    if importer_under_app:
        allowed_prefixes = allowed_prefixes + ("src/app/",)

    if import_spec.startswith("@/components/") or import_spec.startswith(
        "@/lib/"
    ):
        base = import_spec[2:]  # strip "@/"
        candidate_roots = [os.path.join(repo_root, "src", base)]
    elif import_spec.startswith("@/app/") and importer_under_app:
        # #1273: only resolve @/app/* when the importer itself is under
        # src/app/ — keeps Layer 2 walk locality intact.
        base = import_spec[2:]  # strip "@/"
        candidate_roots = [os.path.join(repo_root, "src", base)]
    elif import_spec.startswith("./") or import_spec.startswith("../"):
        importer_dir = os.path.dirname(
            os.path.join(repo_root, importer_path)
        )
        resolved = os.path.normpath(os.path.join(importer_dir, import_spec))
        rel = os.path.relpath(resolved, repo_root).replace(os.sep, "/")
        if not any(rel.startswith(p) for p in allowed_prefixes):
            return None
        candidate_roots = [resolved]
    else:
        return None
    for cr in candidate_roots:
        for ext in (".tsx", ".jsx", ".ts", ".js"):
            p = cr + ext
            if os.path.isfile(p):
                return os.path.relpath(p, repo_root).replace(os.sep, "/")
        # also try index.<ext>
        for ext in (".tsx", ".jsx", ".ts", ".js"):
            p = os.path.join(cr, f"index{ext}")
            if os.path.isfile(p):
                return os.path.relpath(p, repo_root).replace(os.sep, "/")
    return None


def derive_page_images(
    page_set: list[dict[str, Any]],
    repo_root: str = ".",
    include_landing: bool = True,
) -> dict[str, dict[str, Any]]:
    """Two-layer static image-render classifier for design-critic.

    Layer 1 (direct-source): grep each entry's source_files for image patterns.
    Layer 2 (one-level import-graph walk): parse the top page file for import
    statements and grep each resolved import target. Resolution scope (#1273):
      - src/components/** and src/lib/** for any importer (canonical shared
        component / utility trees);
      - src/app/<route>/** ONLY when the importer is itself under src/app/
        (co-located route data modules like src/app/portfolio/cases.ts
        referenced from src/app/portfolio/[slug]/page.tsx). The locality
        guard prevents Layer 2 from leaking src/app/ resolution to
        src/lib/ importers.

    Landing override (when include_landing=True): if an entry is named
    "landing", force has_images=true (owns global slots: hero/features/logo/
    og-photo/empty-state).

    Returns: {
        "<page>": {
            "has_images": bool,
            "detected_via": "direct-source" | "imported-component" |
                            "landing-hardcoded" | "none",
            "evidence_files": [<repo-relative paths where matches fired>],
            "patterns_matched": [<matched regex strings>],
        },
        ...
    }
    """
    result: dict[str, dict[str, Any]] = {}

    # Ensure landing is classified when caller asks (pre-state-3a workflow).
    # Discover landing's source via derive_landing_for_design_critic so the
    # entry survives non-.tsx file extensions (#1143). When src/app/page.* is
    # absent (e.g., service archetype called include_landing=True by mistake),
    # do not inject a phantom landing entry — caller will see no `landing` key
    # in the result, which is the correct signal.
    if include_landing and not any(p.get("name") == "landing" for p in page_set):
        landing_entry = derive_landing_for_design_critic(repo_root)
        if landing_entry is not None:
            page_set = [landing_entry, *page_set]

    for entry in page_set:
        name = entry.get("name", "")
        if not name:
            continue
        if name == "landing":
            result[name] = {
                "has_images": True,
                "detected_via": "landing-hardcoded",
                "evidence_files": [],
                "patterns_matched": [],
            }
            continue

        source_files: list[str] = entry.get("source_files") or []
        # Layer 1 — direct source grep
        layer1_hits: list[tuple[str, list[str]]] = []
        for sf in source_files:
            abs_path = os.path.join(repo_root, sf)
            matches = _grep_image_patterns(abs_path)
            if matches:
                layer1_hits.append((sf, matches))

        if layer1_hits:
            result[name] = {
                "has_images": True,
                "detected_via": "direct-source",
                "evidence_files": [sf for sf, _ in layer1_hits],
                "patterns_matched": sorted(
                    {m for _, ms in layer1_hits for m in ms}
                ),
            }
            continue

        # Layer 2 — one-level import-graph walk
        layer2_hits: list[tuple[str, list[str]]] = []
        seen_imports: set[str] = set()
        for sf in source_files:
            abs_path = os.path.join(repo_root, sf)
            if not os.path.isfile(abs_path):
                continue
            try:
                with open(abs_path, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            for m in _IMPORT_RE.finditer(text):
                spec = m.group(1)
                resolved = _resolve_import(sf, spec, repo_root)
                if not resolved or resolved in seen_imports:
                    continue
                seen_imports.add(resolved)
                matches = _grep_image_patterns(
                    os.path.join(repo_root, resolved)
                )
                if matches:
                    layer2_hits.append((resolved, matches))

        if layer2_hits:
            result[name] = {
                "has_images": True,
                "detected_via": "imported-component",
                "evidence_files": [path for path, _ in layer2_hits],
                "patterns_matched": sorted(
                    {m for _, ms in layer2_hits for m in ms}
                ),
            }
            continue

        result[name] = {
            "has_images": False,
            "detected_via": "none",
            "evidence_files": [],
            "patterns_matched": [],
        }

    return result


def _load_experiment() -> dict:
    """Load experiment.yaml from disk or stdin."""
    try:
        import yaml
    except ImportError:
        sys.stderr.write("ERROR: PyYAML not installed (pip install pyyaml)\n")
        sys.exit(2)

    if not sys.stdin.isatty():
        return yaml.safe_load(sys.stdin)
    try:
        return yaml.safe_load(open("experiment/experiment.yaml"))
    except FileNotFoundError:
        sys.stderr.write("ERROR: experiment/experiment.yaml not found and no stdin input\n")
        sys.exit(2)


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in (
        "scope",
        "validation",
        "funnel",
        "public_paths",
        "design_critic_pages",
        "dynamic_public_pages",
        "dynamic_only_pages",
    ):
        sys.stderr.write(
            "usage: derive_pages.py "
            "{scope|validation|funnel|public_paths|design_critic_pages|dynamic_public_pages|dynamic_only_pages} "
            "[< experiment.yaml]\n"
        )
        sys.exit(2)

    experiment = _load_experiment()
    if sys.argv[1] == "scope":
        result = derive_scope_pages(experiment)
    elif sys.argv[1] == "validation":
        result = derive_validation_pages(experiment)
    elif sys.argv[1] == "public_paths":
        result = derive_public_paths(experiment)
    elif sys.argv[1] == "design_critic_pages":
        # #1379 G3: spec-reviewer S2 page-existence check must use this output
        # (returns list[dict] with name + source_files) instead of `scope`
        # (returns disambiguated names). Dynamic routes like
        # src/app/portfolio/[slug]/page.tsx are returned as
        # name='portfolio-slug' which does NOT exist as a literal directory.
        # source_files[] contains the actual repo-relative .tsx paths.
        result = derive_page_set_for_design_critic(experiment)
    elif sys.argv[1] == "dynamic_public_pages":
        # #1387: enumerate concrete URL instances for dynamic-segment public
        # pages (sitemap.ts emitter consumer + post-fan-out audit input).
        result = dynamic_public_pages(experiment)
    elif sys.argv[1] == "dynamic_only_pages":
        # GECR #1473: classify each scope page by route shape so BG2-WIRE
        # check 1 can branch behavior (static → bare-slug; dynamic-only →
        # template-literal REPLACE; mixed → both; absent → trivially pass).
        result = derive_dynamic_only_pages(experiment)
    else:
        result = derive_funnel_steps(experiment)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
