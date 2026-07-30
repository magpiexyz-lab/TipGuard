#!/usr/bin/env python3
"""Per-MVP Phase-1 relaunch window for /iterate --cross.

When an MVP's first Phase-1 flight fails (NO_GO / low conversion) but the team
fixes the product / landing / tracking and wants to re-test, a straight re-run
would pool the new paid clicks with the old failed ones — the stale denominator
drags the conversion rate down forever. `phase1_relaunch_at` marks a cut date:
Phase-1 evaluation then ignores everything before it and judges only the
relaunch-onward window.

Operator sets it per MVP in experiment/iterate-cross-config.yaml:

    mvp_mappings:
      mooncub:
        phase1_relaunch_at: "2026-07-25"   # ISO date (YYYY-MM-DD)

Semantics: the effective Phase-1 lower time bound for that MVP becomes
`max(now() - window_days, phase1_relaunch_at)`. Three consumers apply it:
  - GA merge (iterate_cross_ga): a campaign counts toward ga_clicks/ga_cost only
    when its Start date is on/after the relaunch date. Relaunch REQUIRES a new
    campaign name (e.g. mooncub-search-v2) so the old flight's Start date sorts
    before the cut — documented in state-x0a. Phase-1 merges only: the x5
    `--phase-filter` merge ignores the relaunch map (the phase2 denominator is
    scoped by the utm token, and the phase2 CSV export need not carry Start
    date, which an active cut would conservatively drop).
  - PostHog signup count (state-x2) and catalog (state-x1): the per-MVP subquery
    lower bound is raised to the relaunch instant.
  - DB ground truth (state-x0b, iterate_cross_db): the windowed signup/auth
    queries raise their lower bound to the relaunch instant.

`gclid_visitors` from state-x0 discovery is deliberately NOT re-scoped (it is a
diagnostic + fallback denominator, computed by a single GROUP BY across all
MVPs); the verdict denominator uses the relaunch-scoped GA clicks. state-x4
renders a "relaunch <date>" marker and notes the raw PostHog visitor count spans
the pre-relaunch flight too.

This module is pure (no I/O) so it is unit-testable and shared by every site;
never inline the date math at a call site.
"""

from __future__ import annotations

import re
from datetime import date

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_relaunch_at(value: object) -> str | None:
    """Validate and normalize a `phase1_relaunch_at` config value.

    Accepts an ISO ``YYYY-MM-DD`` string (optionally with a trailing time that we
    drop to the date). Returns the normalized ``YYYY-MM-DD`` string, or None when
    the value is absent/empty. Raises ValueError on a malformed non-empty value
    so a typo surfaces loudly instead of silently disabling the window.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # Tolerate a full ISO timestamp by taking the date part.
    s = s.split("T")[0].split(" ")[0]
    if not _ISO_DATE.match(s):
        raise ValueError(
            f"phase1_relaunch_at must be an ISO date (YYYY-MM-DD), got {value!r}"
        )
    try:
        date.fromisoformat(s)
    except ValueError as exc:
        raise ValueError(f"phase1_relaunch_at is not a real date: {value!r}") from exc
    return s


def relaunch_at_for(mvp_name: str, mvp_mappings: dict | None) -> str | None:
    """Read + validate the relaunch date for one MVP from mvp_mappings."""
    mapping = (mvp_mappings or {}).get(mvp_name) or {}
    if not isinstance(mapping, dict):
        return None
    return parse_relaunch_at(mapping.get("phase1_relaunch_at"))


def posthog_lower_bound_expr(window_days: int, relaunch_at: str | None) -> str:
    """HogQL time lower-bound expression for a per-MVP subquery.

    Without a relaunch date: ``now() - INTERVAL <window_days> DAY`` (unchanged
    behavior). With one: ``greatest(now() - INTERVAL <window_days> DAY,
    toDateTime('<relaunch_at> 00:00:00'))`` so the window never widens past the
    global window, only narrows to the relaunch onward.
    """
    base = f"now() - INTERVAL {int(window_days)} DAY"
    rel = parse_relaunch_at(relaunch_at)
    if rel is None:
        return base
    return f"greatest({base}, toDateTime('{rel} 00:00:00'))"


def postgres_lower_bound_expr(
    column: str, window_days: int, relaunch_at: str | None
) -> str:
    """Postgres WHERE lower-bound fragment for the windowed DB queries.

    Returns a boolean fragment (no leading AND) comparing `column` to the
    greater of the rolling window and the relaunch instant. `column` must be a
    trusted identifier from the caller (table's timestamp column), not user
    input — it is quoted but not otherwise sanitized.
    """
    base = f"\"{column}\" >= now() - INTERVAL '{int(window_days)} days'"
    rel = parse_relaunch_at(relaunch_at)
    if rel is None:
        return base
    return (
        f"\"{column}\" >= greatest("
        f"now() - INTERVAL '{int(window_days)} days', "
        f"timestamptz '{rel}')"
    )


def campaign_passes_relaunch(start_date: object, relaunch_at: str | None) -> bool:
    """True when a GA campaign's Start date qualifies under the relaunch cut.

    No relaunch date → always True (every campaign counts). With one, the
    campaign counts only if its Start date is a valid ISO date on/after the
    relaunch date. A missing/blank/malformed Start date under an ACTIVE relaunch
    is treated as NOT passing (conservative: an unattributable-age campaign must
    not silently re-pollute a relaunch denominator; the operator uses a fresh
    v2 campaign whose Start date is present and post-cut).
    """
    rel = parse_relaunch_at(relaunch_at)
    if rel is None:
        return True
    s = str(start_date or "").strip()
    if not _ISO_DATE.match(s):
        return False
    return s >= rel
