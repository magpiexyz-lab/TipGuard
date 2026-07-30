#!/usr/bin/env python3
"""PostHog paid-gclid tracking pulse for /iterate --check.

This helper is intentionally stdout-only. The iterate c1 state owns the
health artifact; this script only resolves the PostHog project, runs the
campaign-scoped queries, and prints one JSON object.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ads_ready_smoke import discover_posthog_project, list_posthog_projects  # noqa: E402
from gclid_filter import PAID_GCLID_FILTER  # noqa: E402
from iterate_cross_posthog_batch import _posthog_query  # noqa: E402


POSTHOG_KEY_PATH = Path.home() / ".posthog" / "personal-api-key"
DEFAULT_PROJECT_WINDOW_DAYS = 90


def read_posthog_api_key(path: Path | None = None) -> tuple[str | None, str | None]:
    """Return the personal API key or a skip reason."""
    path = Path(path or POSTHOG_KEY_PATH)
    try:
        api_key = path.expanduser().read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None, "missing_posthog_personal_api_key"
    except OSError as exc:
        return None, f"posthog_personal_api_key_unreadable: {exc}"
    if not api_key:
        return None, "empty_posthog_personal_api_key"
    return api_key, None


def resolve_posthog_project_id(
    api_key: str,
    mvp_root: str | Path = ".",
) -> tuple[str | None, str | None]:
    """Resolve the PostHog project id or return a visible skip reason.

    Resolution mirrors /ads-ready: the single accessible project is accepted as
    a shortcut; multiple projects use discover_posthog_project(ctx), which
    matches the production PostHog key against team config.
    """
    try:
        projects = list_posthog_projects(api_key)
    except Exception as exc:
        return None, f"posthog_project_list_failed: {exc}"

    if len(projects) == 1:
        project_id = projects[0].get("id")
        if project_id:
            return str(project_id), None
        return None, "posthog_single_project_missing_id"

    if len(projects) > 1:
        try:
            resolved = discover_posthog_project({"mvp_root": str(mvp_root)})
        except Exception as exc:
            return None, f"posthog_project_unresolvable: {exc}"
        project_id = resolved.get("project_id") or (resolved.get("project") or {}).get("id")
        if project_id:
            return str(project_id), None
        return None, "posthog_project_unresolvable: missing project_id"

    return None, "no_posthog_projects_visible"


def _time_bound(since: str | None) -> tuple[str, dict[str, Any], bool]:
    if since:
        return "timestamp >= {since}", {"since": since}, False
    return f"timestamp >= now() - INTERVAL {DEFAULT_PROJECT_WINDOW_DAYS} DAY", {}, True


def build_campaign_count_query(
    campaign_name: str,
    *,
    since: str | None,
    hours: int | None = None,
) -> tuple[str, dict[str, Any], bool]:
    """Build a campaign-scoped paid-gclid visitor count query."""
    values: dict[str, Any] = {"campaign": campaign_name}
    since_bound, since_values, created_at_missing = _time_bound(since)
    values.update(since_values)
    where = [
        PAID_GCLID_FILTER,
        "properties.utm_campaign IS NOT NULL",
        "toString(properties.utm_campaign) = {campaign}",
        since_bound,
    ]
    if hours is not None:
        safe_hours = int(hours)
        if safe_hours <= 0:
            raise ValueError("hours must be positive")
        where.append(f"timestamp >= now() - INTERVAL {safe_hours} HOUR")
    sql = (
        "SELECT count(DISTINCT distinct_id) AS gclid_visitors "
        "FROM events WHERE "
        + " AND ".join(where)
    )
    return sql, values, created_at_missing


def build_project_window_query(
    *,
    days: int = DEFAULT_PROJECT_WINDOW_DAYS,
) -> tuple[str, dict[str, Any]]:
    """Build the unscoped project-window paid-gclid visitor count query."""
    safe_days = int(days)
    if safe_days <= 0:
        raise ValueError("days must be positive")
    sql = (
        "SELECT count(DISTINCT distinct_id) AS gclid_visitors "
        f"FROM events WHERE {PAID_GCLID_FILTER} "
        f"AND timestamp >= now() - INTERVAL {safe_days} DAY"
    )
    return sql, {}


def parse_count_response(response: dict[str, Any]) -> int:
    """Parse a PostHog count(DISTINCT distinct_id) response."""
    results = response.get("results") if isinstance(response, dict) else None
    if not isinstance(results, list) or not results:
        return 0
    row = results[0]
    value: Any
    if isinstance(row, dict):
        value = (
            row.get("gclid_visitors")
            if "gclid_visitors" in row
            else next(iter(row.values()), 0)
        )
    elif isinstance(row, (list, tuple)):
        value = row[0] if row else 0
    else:
        value = row
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def query_tracking_pulse(
    *,
    campaign_name: str,
    since: str | None,
    hours: int,
    project_id: str,
    api_key: str,
) -> dict[str, Any]:
    """Run the three tracking-pulse queries and return the JSON payload."""
    q_24h, v_24h, created_at_missing = build_campaign_count_query(
        campaign_name,
        since=since,
        hours=hours,
    )
    q_campaign, v_campaign, _ = build_campaign_count_query(
        campaign_name,
        since=since,
        hours=None,
    )
    q_project, v_project = build_project_window_query()

    ph_24h = parse_count_response(_posthog_query(q_24h, v_24h, project_id, api_key))
    ph_campaign = parse_count_response(
        _posthog_query(q_campaign, v_campaign, project_id, api_key)
    )
    ph_project = parse_count_response(_posthog_query(q_project, v_project, project_id, api_key))

    return {
        "ph_gclid_visitors_24h": ph_24h,
        "ph_gclid_visitors_campaign": ph_campaign,
        "ph_gclid_visitors_project_window": ph_project,
        "queried_at": datetime.now(timezone.utc).isoformat(),
        "created_at_missing": created_at_missing,
    }


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-name", required=True)
    parser.add_argument("--since", default=None, help="Campaign creation date, YYYY-MM-DD.")
    parser.add_argument("--hours", type=int, default=24)
    args = parser.parse_args(argv)

    api_key, skip_reason = read_posthog_api_key()
    if skip_reason:
        _print_json({"skip_reason": skip_reason})
        return 2

    project_id, skip_reason = resolve_posthog_project_id(api_key or "", Path.cwd())
    if skip_reason:
        _print_json({"skip_reason": skip_reason})
        return 2

    payload = query_tracking_pulse(
        campaign_name=args.campaign_name,
        since=args.since,
        hours=args.hours,
        project_id=project_id or "",
        api_key=api_key or "",
    )
    _print_json(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
