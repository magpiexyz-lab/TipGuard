#!/usr/bin/env python3
"""PostHog query batching helpers for /iterate --cross.

The state files use these helpers for two shapes that otherwise silently cap
portfolio-size runs:
- discovery queries fetched via a single OFFSET-free capped LIMIT (personal API
  keys reject OFFSET; these GROUP BY aggregates are small and bounded)
- UNION ALL query groups that need bounded batch sizes
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from typing import Any


def _posthog_query(
    sql: str,
    values: dict[str, Any],
    project_id: str,
    api_key: str,
    max_time_seconds: int = 30,
    attempts: int = 3,
) -> dict:
    body = {"query": {"kind": "HogQLQuery", "query": sql, "values": values}}
    last_error = "unknown error"
    attempts = max(1, int(attempts or 1))
    for attempt in range(attempts):
        r = subprocess.run(
            [
                "curl", "-s", "--max-time", str(max_time_seconds), "-X", "POST",
                f"https://us.i.posthog.com/api/projects/{project_id}/query/",
                "-H", "Content-Type: application/json",
                "-H", f"Authorization: Bearer {api_key}",
                "--data", json.dumps(body),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if r.returncode != 0:
            last_error = f"curl exit {r.returncode}: {r.stderr[:200]}"
        elif not r.stdout.strip():
            last_error = "empty response"
        else:
            try:
                resp = json.loads(r.stdout)
            except json.JSONDecodeError:
                last_error = f"non-JSON response: {r.stdout[:200]}"
            else:
                if isinstance(resp, dict) and resp.get("error"):
                    raise RuntimeError(f"PostHog query failed: {resp.get('error')}")
                if "results" in resp and isinstance(resp["results"], list):
                    return resp
                last_error = f"missing results: {json.dumps(resp)[:400]}"

        if attempt < attempts - 1:
            time.sleep((1, 2, 4)[min(attempt, 2)])
    raise RuntimeError(f"PostHog query failed after {attempts} attempts: {last_error}")


def _limit_only_sql(sql_template: str, limit: int) -> str:
    """Render the discovery SQL with a single LIMIT and no OFFSET.

    Personal API keys reject OFFSET (PostHog only permits keyset pagination on
    the timestamp column, which does not apply to these GROUP BY aggregates), so
    pagination is expressed as one capped LIMIT-only fetch. Both the literal
    ``... LIMIT N`` shape used by the state files and the ``{limit}``/``{offset}``
    placeholder shape are normalized to ``... LIMIT <limit>``.
    """
    if "{limit}" in sql_template or "{offset}" in sql_template:
        rendered = sql_template.format(limit=limit, offset=0)
        return re.sub(r"\s+OFFSET\s+\d+\s*$", "", rendered, flags=re.I)
    base = re.sub(r"\s+LIMIT\s+\d+(\s+OFFSET\s+\d+)?\s*$", "", sql_template, flags=re.I)
    return f"{base} LIMIT {limit}"


def paginate_discovery_query(
    sql_template: str,
    values: dict[str, Any] | None,
    project_id: str,
    api_key: str,
    page_size: int = 200,
    max_pages: int = 20,
    max_time_seconds: int = 30,
) -> tuple[list[list], dict[str, Any]]:
    """Fetch a discovery result set in one OFFSET-free, capped query.

    /iterate --cross authenticates with a PostHog *personal* API key, for which
    PostHog rejects OFFSET ("use keyset pagination on the timestamp column").
    These discovery queries are GROUP BY aggregates (one row per MVP / orphan
    host) for which timestamp keyset pagination does not apply, and the result
    set is small and bounded by the number of groups. So instead of an OFFSET
    page loop we issue a single LIMIT-only query capped at page_size * max_pages
    and prove completeness with a short page — the same completeness contract as
    before, minus the unsupported OFFSET.
    """
    if page_size <= 0:
        raise ValueError("page_size must be > 0")
    if max_pages <= 0:
        raise ValueError("max_pages must be > 0")

    values = values or {}
    cap = page_size * max_pages
    resp = _posthog_query(
        _limit_only_sql(sql_template, cap),
        values,
        project_id,
        api_key,
        max_time_seconds=max_time_seconds,
    )
    rows = resp["results"]
    if len(rows) < cap:
        return rows, {"status": "complete", "pages_fetched": 1}
    raise RuntimeError(
        f"PostHog discovery returned the full cap of {cap} rows "
        f"(page_size={page_size} * max_pages={max_pages}); OFFSET paging is "
        "unavailable for personal API keys. Raise page_size/max_pages or add "
        "keyset pagination on a unique ordering key."
    )


def run_union_batches(
    parts: list[str],
    values: dict[str, Any] | None,
    project_id: str,
    api_key: str,
    batch_size: int = 20,
    max_time_seconds: int = 30,
) -> tuple[list[list], dict[str, Any]]:
    """Run UNION ALL query parts in bounded batches and concatenate rows.

    Contract: all-or-nothing. Any batch failure propagates and the partial
    rows are discarded — callers' VERIFY gates assert `complete: True`, and a
    silently partial result set would produce wrong per-MVP verdicts. On long
    windows the fix for HogQL max-execution-time is a SMALLER batch_size (and
    a larger max_time_seconds), not partial tolerance; `complete` is True by
    construction because the failure path raises.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be > 0")
    values = values or {}
    if not parts:
        return [], {"complete": True, "batches_run": 0, "parts_total": 0}

    rows: list[list] = []
    batches_run = 0
    for start in range(0, len(parts), batch_size):
        sql = " UNION ALL ".join(parts[start:start + batch_size])
        resp = _posthog_query(
            sql, values, project_id, api_key, max_time_seconds=max_time_seconds
        )
        rows.extend(resp["results"])
        batches_run += 1
    return rows, {
        "complete": True,
        "batches_run": batches_run,
        "parts_total": len(parts),
    }


def compute_orphan_overlap(
    pairs: list,
    project_id: str,
    api_key: str,
    window_days: int,
    phase_clause: str = "",
    phase_values: dict[str, Any] | None = None,
    cache_path: str | None = None,
    max_time_seconds: int = 30,
    cooldown_seconds: int = 300,
    failure_sleep_seconds: int = 0,
    max_passes: int = 1,
) -> dict[str, dict]:
    """Query per-pair gclid intersections between canonical and orphan traffic.

    Shared implementation for state-x0 and state-x5. Pairs run serially —
    a UNION ALL of 7+ subqueries exceeds HogQL's max-execution-time, one query
    per pair at ~500ms is comfortably inside it. Returns overlap_counts shaped
    for `iterate_cross_classify.merge_orphan_overlap`:
    {canonical: {orphan_host, canonical_gclids, orphan_gclids, overlap}}.

    `phase_clause` (e.g. the x5 utm_campaign LIKE clause) is appended to BOTH
    CTEs so phase-scoped callers intersect only phase traffic; its placeholder
    values go in `phase_values`. The resumable cache is keyed on
    {project_id, window_days, pairs_hash, scope_hash} — scope_hash covers the
    phase clause + values so a phase-2 run can never reuse phase-1 counts.
    A failed pair is WARNed and omitted (downstream conservatively keeps the
    orphan separate). Cache writes are incremental and atomic (tmp + replace).

    Cooldown-resume (long windows): on 365-day windows PostHog times these
    queries out and then applies a server-side circuit breaker ("This query
    failed the same way 4 times in a row … It can run again in about 4
    minutes") — immediate retries fail instantly regardless of the timeout.
    With `max_passes > 1`, pairs that failed a pass are retried in later
    passes separated by `cooldown_seconds` (~the breaker window); within a
    pass, each failure sleeps `failure_sleep_seconds` before the next pair.
    No sleep runs after the final pass. The per-pair cache makes resume work
    both across passes in-process and across invocations of the caller.
    Defaults (`max_passes=1`, `failure_sleep_seconds=0`) preserve the
    single-pass behavior.
    """
    from gclid_filter import PAID_GCLID_FILTER

    norm_pairs = [(str(c), str(o)) for c, o in pairs]
    values_base = dict(phase_values or {})
    pairs_hash = hashlib.sha256(
        json.dumps(norm_pairs, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    scope_hash = hashlib.sha256(
        json.dumps(
            {"phase_clause": phase_clause, "phase_values": values_base},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    def write_cache(by_canonical: dict) -> None:
        if not cache_path:
            return
        artifact = {
            "project_id": str(project_id),
            "window_days": int(window_days),
            "pairs_hash": pairs_hash,
            "scope_hash": scope_hash,
            "by_canonical": by_canonical,
        }
        tmp_path = f"{cache_path}.tmp.{os.getpid()}"
        with open(tmp_path, "w") as fh:
            json.dump(artifact, fh, indent=2)
            fh.write("\n")
        os.replace(tmp_path, cache_path)

    existing: dict = {}
    if cache_path:
        try:
            with open(cache_path) as fh:
                existing = json.load(fh)
        except Exception:
            existing = {}
    cache_matches = (
        existing.get("project_id") == str(project_id)
        and existing.get("window_days") == int(window_days)
        and existing.get("pairs_hash") == pairs_hash
        and existing.get("scope_hash") == scope_hash
    )
    by_canonical: dict[str, dict] = (existing.get("by_canonical") or {}) if cache_matches else {}

    def pending_pairs() -> list[tuple[str, str]]:
        return [
            (c, o) for c, o in norm_pairs
            if (by_canonical.get(c) or {}).get("orphan_host") != o
        ]

    def run_pass(pending: list[tuple[str, str]]) -> None:
        for canon, orphan_host in pending:
            sql = (
                f"WITH c AS (SELECT DISTINCT toString(coalesce(properties.$session_entry_gclid, properties.gclid)) AS g "
                f"FROM events WHERE properties.project_name = {{cn}} AND {PAID_GCLID_FILTER} "
                f"{phase_clause} "
                f"AND timestamp >= now() - INTERVAL {int(window_days)} DAY), "
                f"o AS (SELECT DISTINCT toString(coalesce(properties.$session_entry_gclid, properties.gclid)) AS g "
                f"FROM events WHERE (properties.project_name IS NULL OR properties.project_name = '') AND {PAID_GCLID_FILTER} "
                f"{phase_clause} "
                f"AND splitByChar('.', domain(coalesce(properties.$current_url, '')))[1] = {{oh}} "
                f"AND timestamp >= now() - INTERVAL {int(window_days)} DAY) "
                f"SELECT (SELECT count() FROM c) AS canonical_gclids, "
                f"(SELECT count() FROM o) AS orphan_gclids, "
                f"(SELECT count() FROM (SELECT g FROM c INTERSECT SELECT g FROM o)) AS overlap"
            )
            try:
                resp = _posthog_query(
                    sql,
                    {**values_base, "cn": canon, "oh": orphan_host},
                    project_id,
                    api_key,
                    max_time_seconds=max_time_seconds,
                )
                row = (resp.get("results") or [[0, 0, 0]])[0]
                by_canonical[canon] = {
                    "orphan_host": orphan_host,
                    "canonical_gclids": row[0],
                    "orphan_gclids": row[1],
                    "overlap": row[2],
                }
                write_cache(by_canonical)
            except Exception as exc:
                print(
                    f"WARN: overlap query failed for {canon}/{orphan_host}: {exc}",
                    file=sys.stderr,
                )
                if failure_sleep_seconds > 0:
                    time.sleep(failure_sleep_seconds)

    total_passes = max(1, int(max_passes or 1))
    for pass_idx in range(total_passes):
        pending = pending_pairs()
        if not pending:
            break
        if pass_idx > 0:
            print(
                f"INFO: overlap pass {pass_idx + 1}/{total_passes}: "
                f"{len(pending)} pair(s) still unresolved; sleeping "
                f"{cooldown_seconds}s for the PostHog circuit-breaker cooldown",
                file=sys.stderr,
            )
            time.sleep(cooldown_seconds)
        run_pass(pending)

    write_cache(by_canonical)
    return by_canonical
