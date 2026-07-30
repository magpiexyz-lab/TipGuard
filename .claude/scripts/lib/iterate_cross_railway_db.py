"""
Railway DB ground-truth fetcher for /iterate --cross state-x0b.

Sibling of iterate_cross_db.py (Supabase). Same role: fold authoritative DB
signup counts into context.mvps so state-x3 can cross-check PostHog paid
signups against the database.

Architecture difference vs Supabase:
- Supabase has a Management API (one Bearer token, one HTTP endpoint per query).
- Railway has CLI-only access to per-project Postgres URLs. We use:
    1. `railway list --json` — one-shot enumeration of every project + service
       (incl. workspace, service IDs). Cheap; no per-project link required.
    2. `railway link --project <id>` + `railway variables --service <name> --json`
       — to pull DATABASE_PUBLIC_URL for a chosen Postgres service. The link
       writes state to .railway/config.json in the cwd, so we use a temp dir
       per call to avoid contaminating the iterate-cross run state.
    3. `psql <url> -c "<sql>"` — run schema + count queries directly.
  No GraphQL path because the CLI session token (rw_Fe26.2*…) is rejected by
  Cloudflare when sent as a direct Bearer header (1010 error); a dedicated
  Personal API Token would work but adds operator setup friction.

Subcommands
-----------
  list-postgres-projects  — print every Railway project that has a Postgres
                            service (one row per project: id, name, services)
  fuzzy-match             — given mvps[] from context, propose name → railway
                            project mapping (3 strategies, same as Supabase)
  query-signups           — for one (project_id, service_name), pull DB URL,
                            discover signup table, return count
  merge                   — orchestrator called from state-x0b. Only touches
                            MVPs whose db_signups is still None after the
                            Supabase pass — Railway is a *fallback*, not
                            duplicate work. Idempotent re-write of config.

Schema written into each mvp record (additive — preserves Supabase fields)
--------------------------------------------------------------------------
  railway_project_id      str | None  (UUID; None = no Railway match)
  railway_project_name    str | None  (display name)
  railway_service_name    str | None  (which Postgres service won)
  railway_service_id      str | None
  db_signups              int | None  (set ONLY if previously None; never overwrites)
  db_signups_paid         int | None  (union real emails with a valid POPULATED
                                       gclid; 0 = column exists, none validate;
                                       None = no gclid column on any table)
  db_attribution          str | None  ("gclid_shape" iff db_signups_paid > 0,
                                       else "window"; None = unmapped)
  db_signups_table        str | None  (top real contributor, prefixed with
                                       `railway:` when Railway-sourced)
  db_union_tables         list[str]   (tables contributing >=1 real email to
                                       the cross-table union; [] otherwise)
  db_first_signup_at      str | None
  db_unmapped_reason      str | None  (refined: 'no_match' becomes 'no_match_neither'
                                       when Railway also lacks a match)
  db_breakdown            dict        ({table: count} for transparency)
  db_source               str         ('supabase' | 'railway' | None)

Operator config (experiment/iterate-cross-config.yaml) additions
----------------------------------------------------------------
  mvp_mappings:
    <name>:
      railway_project_id: <uuid>         # locks the match against future drift
      railway_service_name: Postgres     # disambiguates when project has multiple
      db_signup_table: public.users      # SAME override field as Supabase path
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

# Re-use the well-tuned constants from the Supabase sibling. They're table-name
# heuristics, not host-specific, so duplicating them would just drift.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from iterate_cross_db import (  # noqa: E402
    SIGNUP_TABLE_EXCLUSIONS,
    SIGNUP_TABLE_PATTERNS,
    TIMESTAMP_COLUMN_CANDIDATES,
    allow_railway_fallback,
    fuzzy_match_projects,
    normalize_name,
    _detected_gclid_column,
    _priority_value,
    _rank_signup_tables_for_probe,
    _union_ground_truth,
)
from iterate_cross_email_filter import filter_signups, internal_domains_for_mvp  # noqa: E402

try:
    import yaml
except ImportError:
    yaml = None


def _check_railway_auth() -> str | None:
    """Return None if logged in, else an operator-facing instruction string."""
    try:
        r = subprocess.run(
            ["railway", "whoami"], capture_output=True, text=True, timeout=10
        )
    except FileNotFoundError:
        return (
            "Railway CLI not installed. Install via `brew install railway` "
            "(or see https://docs.railway.com/guides/cli)."
        )
    if r.returncode == 0 and "@" in r.stdout:
        return None
    return (
        "Railway CLI is not authenticated. Run `! railway login` in the prompt box "
        "(the `!` prefix lets the browser flow run in your session)."
    )


def _check_psql_available() -> str | None:
    """Return None if psql is on PATH, else an operator-facing instruction string.

    psql is required for the actual data queries (Railway's CLI only fetches
    the connection URL — it does not execute SQL). Without psql, the whole
    pass must skip cleanly rather than crash with FileNotFoundError mid-loop.
    """
    try:
        r = subprocess.run(
            ["psql", "--version"], capture_output=True, text=True, timeout=5
        )
    except FileNotFoundError:
        return (
            "psql client not installed. Install via `brew install libpq && "
            "brew link --force libpq` (macOS) — required for Railway DB queries."
        )
    if r.returncode != 0:
        return f"psql --version returned {r.returncode}: {r.stderr[:100]}"
    return None


def list_railway_projects() -> list[dict]:
    """Enumerate every Railway project + its services in one call.

    Returns: [{id, name, workspace, workspace_id, services: [{id, name}]}, ...]
    Postgres services are NOT filtered here — caller decides.
    """
    r = subprocess.run(
        ["railway", "list", "--json"], capture_output=True, text=True, timeout=30
    )
    if r.returncode != 0:
        return []
    try:
        raw = json.loads(r.stdout)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    out = []
    for p in raw:
        svcs = []
        for edge in (p.get("services") or {}).get("edges", []):
            node = edge.get("node") or {}
            if node.get("id") and node.get("name"):
                svcs.append({"id": node["id"], "name": node["name"]})
        workspace = p.get("workspace") or {}
        out.append(
            {
                "id": p.get("id"),
                "name": p.get("name"),
                "workspace": workspace.get("name") if isinstance(workspace, dict) else None,
                "workspace_id": workspace.get("id") if isinstance(workspace, dict) else None,
                "services": svcs,
            }
        )
    return out


def projects_with_postgres(projects: list[dict]) -> list[dict]:
    """Filter to projects that have at least one Postgres-shape service.

    Postgres detection: service name contains 'postgres' or 'pgsql' (case-insensitive).
    Excludes generic 'database' which on Railway can mean MongoDB / MySQL too —
    we don't currently know how to introspect those, so we don't claim them.
    """
    out = []
    for p in projects:
        pg = [
            s for s in p["services"]
            if "postgres" in s["name"].lower() or "pgsql" in s["name"].lower()
        ]
        if pg:
            out.append({**p, "postgres_services": pg})
    return out


def get_database_url(project_id: str, service_name: str, environment: str = "production") -> dict:
    """Fetch DATABASE_PUBLIC_URL for a project+service.

    Side-effect-free for the cwd: links inside a tempdir, never the caller's cwd.
    Returns: {url: str | None, error: str | None}.
    """
    tmpdir = tempfile.mkdtemp(prefix="railway-x0b-")
    try:
        link = subprocess.run(
            [
                "railway", "link",
                "--project", project_id,
                "--environment", environment,
            ],
            capture_output=True, text=True, timeout=30, cwd=tmpdir,
        )
        if link.returncode != 0 or "linked successfully" not in link.stdout:
            return {"url": None, "error": f"link failed: {link.stderr[:200] or link.stdout[:200]}"}

        vars_r = subprocess.run(
            ["railway", "variables", "--service", service_name, "--json"],
            capture_output=True, text=True, timeout=30, cwd=tmpdir,
        )
        if vars_r.returncode != 0:
            return {"url": None, "error": f"variables failed: {vars_r.stderr[:200]}"}
        try:
            v = json.loads(vars_r.stdout)
        except json.JSONDecodeError:
            return {"url": None, "error": "variables returned non-JSON"}
        url = v.get("DATABASE_PUBLIC_URL") or v.get("DATABASE_URL")
        if not url:
            return {"url": None, "error": "no DATABASE_PUBLIC_URL or DATABASE_URL in service vars"}
        # Prefer PUBLIC_URL when both are set (DATABASE_URL is the internal
        # `postgres.railway.internal` host, unreachable from local machine).
        return {"url": v.get("DATABASE_PUBLIC_URL") or url, "error": None}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _psql_query(db_url: str, sql: str, timeout: int = 30) -> dict:
    """Run a SQL query via psql, return {rows: list[list], error: str | None}.

    Uses -A (unaligned, tab-separated) + -F$'\\t' + -t (tuples-only) for easy parsing.
    """
    r = subprocess.run(
        ["psql", db_url, "-A", "-t", "-F", "\t", "-c", sql],
        capture_output=True, text=True, timeout=timeout,
    )
    if r.returncode != 0:
        # Trim noisy stderr (TLS warnings etc.) — surface the actual SQL error.
        err = r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "psql failed"
        return {"rows": [], "error": err[:200]}
    rows = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(line.split("\t"))
    return {"rows": rows, "error": None}


def discover_signup_tables_pg(db_url: str) -> list[dict]:
    """Same shape as iterate_cross_db.discover_signup_tables but via psql.

    Returns list of {table, columns, timestamp_column, priority} sorted by
    SIGNUP_TABLE_PATTERNS order.
    """
    sql = (
        "SELECT table_name, "
        "string_agg(column_name, ',' ORDER BY ordinal_position) "
        "FROM information_schema.columns "
        "WHERE table_schema = 'public' "
        "GROUP BY table_name "
        "ORDER BY table_name"
    )
    r = _psql_query(db_url, sql)
    if r["error"]:
        return []

    candidates = []
    for row in r["rows"]:
        if len(row) < 2:
            continue
        table_name = row[0]
        if table_name in SIGNUP_TABLE_EXCLUSIONS:
            continue
        columns = row[1].split(",")
        ts_col = None
        for cand in TIMESTAMP_COLUMN_CANDIDATES:
            if cand in columns:
                ts_col = cand
                break
        priority = None
        for i, pat in enumerate(SIGNUP_TABLE_PATTERNS):
            if pat in table_name.lower():
                priority = i
                break
        if priority is None:
            continue
        gclid_column = _detected_gclid_column(columns)
        candidates.append({
            "table": table_name,
            "columns": columns,
            "timestamp_column": ts_col,
            "priority": priority,
            "gclid_column": gclid_column,
        })

    candidates.sort(key=lambda c: c["priority"])
    return candidates


def count_signups_in_window_pg(
    db_url: str, table: str, timestamp_column: str | None, window_days: int,
) -> dict:
    """Count rows in public.<table>; falls back to total when no ts column."""
    if timestamp_column:
        sql = (
            f'SELECT count(*), min("{timestamp_column}")::text '
            f'FROM public."{table}" '
            f"WHERE \"{timestamp_column}\" >= now() - INTERVAL '{window_days} days'"
        )
        window_filtered = True
    else:
        sql = f'SELECT count(*), NULL::text FROM public."{table}"'
        window_filtered = False

    r = _psql_query(db_url, sql)
    if r["error"]:
        return {"count": None, "first_at": None, "window_filtered": window_filtered, "error": r["error"]}
    if not r["rows"]:
        return {"count": 0, "first_at": None, "window_filtered": window_filtered}
    row = r["rows"][0]
    try:
        cnt = int(row[0])
    except (ValueError, IndexError):
        cnt = 0
    first_at = row[1] if len(row) >= 2 and row[1] else None
    return {"count": cnt, "first_at": first_at, "window_filtered": window_filtered}


def select_signups_in_window_pg(
    db_url: str,
    table: str,
    timestamp_column: str | None,
    window_days: int,
    gclid_column: str | None = None,
) -> dict:
    gclid_select = f', "{gclid_column}"' if gclid_column else ""
    if timestamp_column:
        sql = (
            f'SELECT email, "{timestamp_column}"::text AS signup_at{gclid_select} '
            f'FROM public."{table}" '
            f"WHERE \"{timestamp_column}\" >= now() - INTERVAL '{window_days} days'"
        )
        window_filtered = True
    else:
        sql = f'SELECT email, NULL::text AS signup_at{gclid_select} FROM public."{table}"'
        window_filtered = False
    r = _psql_query(db_url, sql)
    if r["error"]:
        return {"rows": None, "window_filtered": window_filtered, "error": r["error"]}
    rows = []
    for row in r["rows"]:
        if len(row) >= 1 and str(row[0]).isdigit():
            first_at = row[1] if len(row) >= 2 and row[1] else None
            # legacy_count marks synthetic placeholder rows (mirrors the
            # Supabase twins) so the union path can keep them count-only —
            # their identical emails would otherwise collide across tables.
            return {
                "rows": [
                    {"email": f"legacy-{i}@legacy-count.invalid-real", "signup_at": first_at}
                    for i in range(int(row[0]))
                ],
                "window_filtered": window_filtered,
                "legacy_count": int(row[0]),
                "legacy_first_at": first_at,
            }
        if len(row) >= 2:
            parsed = {"email": row[0], "signup_at": row[1] or None}
            if gclid_column:
                parsed["gclid"] = row[2] if len(row) >= 3 and row[2] else None
            rows.append(parsed)
        elif len(row) == 1:
            rows.append({"email": row[0], "signup_at": None})
    return {"rows": rows, "window_filtered": window_filtered}


def _filtered_pg_result(
    table_name: str,
    rows: list[dict],
    config: dict,
    windowed: bool,
    priority: int | None = None,
    gclid_column: str | None = None,
    internal_domains=(),
) -> dict:
    filtered = filter_signups(rows, config, internal_domains=internal_domains)
    paid = None
    attribution = "window"
    if windowed and gclid_column:
        paid = filtered["paid"] if filtered.get("paid") is not None else 0
        # Evidence-based attribution (mirrors _filtered_table_result): the
        # gclid_shape label requires a populated valid gclid, not just the column.
        if paid > 0:
            attribution = "gclid_shape"
    return {
        "table": table_name,
        "priority": _priority_value({"priority": priority}),
        "gclid_column": gclid_column,
        "db_signups_raw": filtered["raw"],
        "db_signups_real": filtered["real"],
        "db_signups_team": filtered["team"],
        "db_signups_test": filtered["test"],
        "db_signups_paid": paid,
        "db_attribution": attribution,
        "db_signups_filter_audit": filtered["audit"],
        "db_signups_real_windowed": windowed,
        "db_first_signup_at": filtered["first_real_signup_at"],
    }


def query_mvp_ground_truth_railway(
    db_url: str,
    window_days: int,
    operator_override_table: str | None = None,
    config: dict | None = None,
    internal_domains=(),
) -> dict:
    """Full ground-truth probe for one MVP via Railway Postgres.

    Mirrors query_mvp_ground_truth (Supabase) but skips auth.users (Railway
    Postgres doesn't have a Supabase-Auth schema — apps usually own a
    public.users table directly).

    Returns:
      {db_signups, db_signups_table, db_first_signup_at, db_breakdown, errors}

    Same union-dedupe winner rule as Supabase: windowed email tables merge
    into one gmail-normalized deduped candidate (db_attribution="gclid_shape"
    only when db_signups_paid > 0), which competes with legacy/count-only
    candidates on (real, raw, -priority). db_signups_table is prefixed with
    `railway:` so x3 / x4 can tell which source produced the number.
    """
    config = config or {}
    errors: list[str] = []
    candidates: list[dict] = []

    if operator_override_table:
        # public.<table> only; auth schema doesn't apply on raw Postgres.
        # Detecting auth.<X> on a Railway MVP is operator error: Supabase's
        # `auth.users` schema is a Supabase-Auth construct, not a Postgres
        # standard. Silently rewriting to `public.<X>` would query the wrong
        # table — so fail loud with a fix-it message.
        schema, table_only = (
            operator_override_table.split(".", 1)
            if "." in operator_override_table
            else ("public", operator_override_table)
        )
        if schema not in ("public",):
            return {
                "db_signups": None,
                "db_signups_raw": None,
                "db_signups_real": None,
                "db_signups_paid": None,
                "db_attribution": None,
                "db_signups_team": 0,
                "db_signups_test": 0,
                "db_signups_filter_audit": [],
                "db_signups_real_windowed": None,
                "db_signups_table": f"railway:{operator_override_table}",
                "db_first_signup_at": None,
                "db_breakdown": {},
                "db_unmapped_reason": "query_error",
                "errors": [
                    f"db_signup_table='{operator_override_table}' uses schema '{schema}' "
                    f"which is not supported on Railway Postgres. Only `public.<table>` works "
                    f"here (Supabase's auth.users construct doesn't exist on raw Postgres). "
                    f"Edit mvp_mappings.<name>.db_signup_table to public.<your-signup-table>."
                ],
            }
        tables = discover_signup_tables_pg(db_url)
        table_meta = next((t for t in tables if t["table"] == table_only), None)
        if not table_meta or "email" not in (table_meta.get("columns") or []):
            return {
                "db_signups": None, "db_signups_raw": None, "db_signups_real": None,
                "db_signups_paid": None, "db_attribution": None,
                "db_signups_team": 0, "db_signups_test": 0,
                "db_signups_filter_audit": [], "db_signups_real_windowed": None,
                "db_signups_table": f"railway:public.{table_only}",
                "db_first_signup_at": None, "db_breakdown": {},
                "db_unmapped_reason": "no_email_column",
                "errors": ["no email column"],
            }
        ts_col = table_meta["timestamp_column"]
        gclid_column = table_meta.get("gclid_column")
        result = select_signups_in_window_pg(db_url, table_only, ts_col, window_days, gclid_column)
        if result.get("error"):
            errors.append(f"public.{table_only}: {result['error']}")
            return {
                "db_signups": None,
                "db_signups_raw": None,
                "db_signups_real": None,
                "db_signups_paid": None,
                "db_attribution": None,
                "db_signups_team": 0,
                "db_signups_test": 0,
                "db_signups_filter_audit": [],
                "db_signups_real_windowed": None,
                "db_signups_table": f"railway:public.{table_only}",
                "db_first_signup_at": None,
                "db_breakdown": {},
                "db_unmapped_reason": "query_error",
                "errors": errors,
            }
        row = _filtered_pg_result(
            f"public.{table_only}",
            result["rows"],
            config,
            bool(result["window_filtered"]),
            priority=table_meta.get("priority"),
            gclid_column=gclid_column,
            internal_domains=internal_domains,
        )
        breakdown = {row["table"]: row["db_signups_raw"]}
        return {
            **row,
            "db_signups": row["db_signups_raw"],
            "db_signups_table": f"railway:public.{table_only}",
            "db_breakdown": breakdown,
            "db_unmapped_reason": None,
            "errors": errors or None,
        }

    tables = discover_signup_tables_pg(db_url)
    if not tables:
        return {
            "db_signups": None,
            "db_signups_raw": None,
            "db_signups_real": None,
            "db_signups_paid": None,
            "db_attribution": None,
            "db_signups_team": 0,
            "db_signups_test": 0,
            "db_signups_filter_audit": [],
            "db_signups_real_windowed": None,
            "db_signups_table": None,
            "db_first_signup_at": None,
            "db_breakdown": {},
            "db_unmapped_reason": "no_email_column",
            "errors": ["no signup-shape tables in public schema"],
        }

    union_inputs: list[dict] = []
    for t in _rank_signup_tables_for_probe(tables):
        if "email" not in (t.get("columns") or []):
            continue
        r = select_signups_in_window_pg(
            db_url,
            t["table"],
            t["timestamp_column"],
            window_days,
            t.get("gclid_column"),
        )
        if r.get("error"):
            errors.append(f"public.{t['table']}: {r['error']}")
            continue
        table_candidate = _filtered_pg_result(
            f"public.{t['table']}",
            r["rows"],
            config,
            bool(r["window_filtered"]),
            priority=t.get("priority"),
            gclid_column=t.get("gclid_column"),
            internal_domains=internal_domains,
        )
        candidates.append(table_candidate)
        # Union membership mirrors the Supabase path: windowed, real email
        # rows only — legacy-count synthetic rows stay count-only.
        if r.get("legacy_count") is None and r["window_filtered"]:
            union_inputs.append({
                "table": f"public.{t['table']}",
                "rows": r["rows"],
                "priority": t.get("priority"),
                "gclid_column": t.get("gclid_column"),
                "candidate": table_candidate,
            })

    if not candidates:
        return {
            "db_signups": None,
            "db_signups_raw": None,
            "db_signups_real": None,
            "db_signups_paid": None,
            "db_attribution": None,
            "db_signups_team": 0,
            "db_signups_test": 0,
            "db_signups_filter_audit": [],
            "db_signups_real_windowed": None,
            "db_signups_table": None,
            "db_first_signup_at": None,
            "db_breakdown": {},
            "db_unmapped_reason": "query_error" if errors else "no_email_column",
            "errors": errors or ["all table queries failed"],
        }

    # Same union-vs-residual competition as the Supabase path (see
    # query_mvp_ground_truth): windowed email tables merge into one deduped
    # candidate; legacy-count candidates compete on (real, raw, -priority).
    union_cand = _union_ground_truth(union_inputs, config, internal_domains)
    union_member_tables = {i["table"] for i in union_inputs}
    residual = [c for c in candidates if c["table"] not in union_member_tables]
    pool = ([union_cand] if union_cand else []) + residual
    winner = max(
        pool,
        key=lambda c: (
            c["db_signups_real"],
            c["db_signups_raw"],
            -_priority_value(c),
        ),
    )
    breakdown = {r["table"]: r["db_signups_raw"] for r in candidates}
    return {
        **winner,
        "db_signups": winner["db_signups_raw"],
        "db_signups_table": f"railway:{winner['table']}",
        "db_breakdown": breakdown,
        "db_union_tables": winner.get("db_union_tables") or [],
        "db_unmapped_reason": None,
        "errors": errors or None,
    }


def merge_into_context(
    context_path: str,
    config_path: str,
    auto_confirm: bool = False,
    dry_run: bool = False,
) -> dict:
    """Top-level orchestrator. ONLY operates on MVPs where db_signups is still
    None after the Supabase pass — Railway is a fallback, never duplicate work.

    Returns summary dict for stdout logging.
    """
    if yaml is None:
        raise SystemExit("ERROR: PyYAML required (pip install pyyaml)")

    auth_err = _check_railway_auth()
    if auth_err:
        # Non-halt: Railway is optional. Mark all candidates as unmapped-railway
        # and let state-x0b proceed.
        return {"step": "skipped_auth", "reason": auth_err}

    psql_err = _check_psql_available()
    if psql_err:
        # Same shape as auth_err: non-halting skip. psql is required for the
        # SQL queries; without it the Railway pass cannot proceed. Distinct
        # step type ("skipped_no_psql") so the operator can act on the
        # specific missing dependency instead of getting a generic skip notice.
        return {"step": "skipped_no_psql", "reason": psql_err}

    ctx = json.load(open(context_path))
    config = yaml.safe_load(open(config_path)) if os.path.exists(config_path) else {}
    config = config or {}
    mappings = config.get("mvp_mappings") or {}
    window_days = ctx.get("window_days", 90)

    for mvp in ctx.get("mvps", []):
        mapping = mappings.get(mvp.get("name")) or {}
        mvp["lifecycle_status"] = mapping.get("lifecycle_status") or mvp.get("lifecycle_status") or "active"
        if mapping.get("lifecycle_status_at"):
            mvp["lifecycle_status_at"] = mapping.get("lifecycle_status_at")

    # Only target MVPs that need a fallback. Orphans excluded (no project_name).
    candidates = [
        m for m in ctx["mvps"]
        if not m.get("orphan")
        and m.get("lifecycle_status") != "killed"
        and m.get("db_signups") is None
        and allow_railway_fallback(m.get("db_unmapped_reason"))
    ]
    if not candidates:
        if not dry_run:
            with open(context_path, "w") as f:
                json.dump(ctx, f, indent=2)
        return {"step": "no_candidates", "queried": 0, "unmapped": 0, "errors": 0}

    # Enumerate Railway projects with Postgres.
    all_projects = list_railway_projects()
    pg_projects = projects_with_postgres(all_projects)
    if not pg_projects:
        if not dry_run:
            with open(context_path, "w") as f:
                json.dump(ctx, f, indent=2)
        return {"step": "no_postgres_projects", "queried": 0, "unmapped": len(candidates), "errors": 0}

    # Fuzzy-match candidate MVPs against Postgres-bearing projects.
    pg_proj_for_match = [{"id": p["id"], "name": p["name"]} for p in pg_projects]
    matches = fuzzy_match_projects([m["name"] for m in candidates], pg_proj_for_match)

    needs_confirm: list[dict] = []
    proposed_writes: dict[str, dict] = {}
    for cand in candidates:
        existing = (mappings.get(cand["name"]) or {}).get("railway_project_id")
        if existing:
            continue  # already locked by operator/prior run
        m = matches.get(cand["name"])
        if not m:
            continue
        # Find the Postgres service to use. If project has multiple, prefer the
        # plain "Postgres" name; if still ambiguous, take the first and let
        # operator override via railway_service_name.
        pg_proj = next(p for p in pg_projects if p["id"] == m["id"])
        pg_svcs = pg_proj["postgres_services"]
        chosen_svc = next(
            (s for s in pg_svcs if s["name"].lower() == "postgres"),
            pg_svcs[0],
        )
        needs_confirm.append({
            "mvp": cand["name"],
            "project_id": m["id"],
            "project_name": m["name"],
            "service_name": chosen_svc["name"],
            "match_type": m["match_type"],
            "n_postgres_services": len(pg_svcs),
        })
        proposed_writes[cand["name"]] = {
            "project_id": m["id"],
            "service_name": chosen_svc["name"],
            "service_id": chosen_svc["id"],
        }

    if needs_confirm and not auto_confirm:
        # Return needs_confirm — caller surfaces the mapping for operator review.
        # Re-run with --auto-confirm to persist + query.
        unmapped_after = [c["name"] for c in candidates if matches.get(c["name"]) is None]
        return {
            "step": "needs_confirm",
            "needs_confirm": needs_confirm,
            "auto_matched_count": len(proposed_writes),
            "unmapped": unmapped_after,
            "total_candidates": len(candidates),
        }

    # Persist mappings.
    if proposed_writes and not dry_run:
        for mvp_name, write in proposed_writes.items():
            entry = mappings.setdefault(mvp_name, {})
            entry["railway_project_id"] = write["project_id"]
            entry["railway_service_name"] = write["service_name"]
            entry["railway_service_id"] = write["service_id"]
        config["mvp_mappings"] = mappings
        with open(config_path, "w") as f:
            yaml.safe_dump(config, f, sort_keys=False, default_flow_style=False)

    # Query each newly-mapped candidate.
    queried = 0
    errors_total = 0
    refined_unmapped = 0
    for cand in candidates:
        mvp = next(m for m in ctx["mvps"] if m["name"] == cand["name"])
        mapping = mappings.get(cand["name"]) or {}
        project_id = mapping.get("railway_project_id")
        if not project_id:
            # No Railway match either. Preserve definitive/policy signals
            # (project_deleted = observed deletion; archived_killed = killed
            # policy skip) — only the weaker "no_match" becomes
            # "no_match_neither". Overwriting them here blinds the
            # money-leak / archived / kill-proposal logic that keys on them.
            # (archived_killed rows are already excluded from candidates by
            # the lifecycle filter above; listed here as divergence-safety.)
            if mvp.get("db_unmapped_reason") not in ("project_deleted", "archived_killed"):
                mvp["db_unmapped_reason"] = "no_match_neither"
            refined_unmapped += 1
            continue

        service_name = mapping.get("railway_service_name") or "Postgres"
        url_r = get_database_url(project_id, service_name)
        if not url_r["url"]:
            refreshed_pg_projects = projects_with_postgres(list_railway_projects())
            if refreshed_pg_projects:
                pg_projects = refreshed_pg_projects
            pg_proj = next((p for p in pg_projects if p["id"] == project_id), None)
            pg_svcs = (pg_proj or {}).get("postgres_services") or []
            canonical = [s for s in pg_svcs if "postgres" in s["name"].lower()]
            if len(canonical) == 1 and canonical[0]["name"] != service_name:
                retry_name = canonical[0]["name"]
                retry_r = get_database_url(project_id, retry_name)
                if retry_r["url"]:
                    service_name = retry_name
                    url_r = retry_r
                    mapping["railway_service_name"] = retry_name
                    mapping["railway_service_id"] = canonical[0].get("id")
            if not url_r["url"]:
                mvp["db_unmapped_reason"] = "railway_service_missing"
                mvp["db_signups_real"] = None
                mvp["db_signups_paid"] = None
                mvp["db_attribution"] = None
                mvp["db_errors"] = (mvp.get("db_errors") or []) + [f"railway: {url_r['error']}"]
                errors_total += 1
                continue

        override = mapping.get("db_signup_table")
        internal_domains = internal_domains_for_mvp(config, cand["name"])
        gt = query_mvp_ground_truth_railway(
            url_r["url"],
            window_days,
            override,
            config,
            internal_domains=internal_domains,
        )
        if gt["db_signups"] is None:
            mvp["db_errors"] = (mvp.get("db_errors") or []) + (gt.get("errors") or [])
            mvp["db_unmapped_reason"] = gt.get("db_unmapped_reason") or "query_error"
            mvp["db_signups_real"] = None
            mvp["db_signups_paid"] = None
            mvp["db_attribution"] = None
            errors_total += 1
            continue

        # SUCCESS — fill in db_* fields. Never overwrites a non-null value (we
        # only got here because db_signups was None after Supabase pass).
        mvp["db_signups"] = gt["db_signups"]
        mvp["db_signups_raw"] = gt.get("db_signups_raw")
        mvp["db_signups_real"] = gt.get("db_signups_real")
        mvp["db_signups_paid"] = gt.get("db_signups_paid")
        mvp["db_attribution"] = gt.get("db_attribution")
        mvp["db_signups_team"] = gt.get("db_signups_team", 0)
        mvp["db_signups_test"] = gt.get("db_signups_test", 0)
        mvp["db_signups_filter_audit"] = gt.get("db_signups_filter_audit", [])
        mvp["db_signups_real_windowed"] = gt.get("db_signups_real_windowed")
        mvp["db_signups_table"] = gt["db_signups_table"]
        mvp["db_first_signup_at"] = gt["db_first_signup_at"]
        mvp["db_breakdown"] = gt["db_breakdown"]
        mvp["db_union_tables"] = gt.get("db_union_tables", [])
        mvp["db_unmapped_reason"] = None
        mvp["db_source"] = "railway"
        mvp["railway_project_id"] = project_id
        mvp["railway_project_name"] = mapping.get("railway_project_name") or next(
            (p["name"] for p in pg_projects if p["id"] == project_id), None,
        )
        mvp["railway_service_name"] = service_name
        queried += 1

    # Write back context.
    if not dry_run:
        with open(context_path, "w") as f:
            json.dump(ctx, f, indent=2)

    return {
        "step": "merged",
        "queried": queried,
        "unmapped": refined_unmapped,
        "errors": errors_total,
        "total_candidates": len(candidates),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-postgres-projects")

    p_match = sub.add_parser("fuzzy-match")
    p_match.add_argument("--context", required=True)

    p_q = sub.add_parser("query-signups")
    p_q.add_argument("--project-id", required=True)
    p_q.add_argument("--service-name", default="Postgres")
    p_q.add_argument("--window-days", type=int, default=90)
    p_q.add_argument("--table", default=None)

    p_merge = sub.add_parser("merge")
    p_merge.add_argument("--context", required=True)
    p_merge.add_argument("--config", required=True)
    p_merge.add_argument("--run-dir", default=".runs")
    p_merge.add_argument("--auto-confirm", action="store_true")
    p_merge.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)

    if args.cmd == "list-postgres-projects":
        auth_err = _check_railway_auth()
        if auth_err:
            print(f"ERROR: {auth_err}", file=sys.stderr)
            return 1
        projs = projects_with_postgres(list_railway_projects())
        for p in projs:
            svcs = [s["name"] for s in p["postgres_services"]]
            print(f"{p['id']}\t{p['name']}\t{','.join(svcs)}")
        return 0

    if args.cmd == "fuzzy-match":
        ctx = json.load(open(args.context))
        names = [m["name"] for m in ctx["mvps"] if not m.get("orphan")]
        pg = projects_with_postgres(list_railway_projects())
        results = fuzzy_match_projects(names, [{"id": p["id"], "name": p["name"]} for p in pg])
        for name, m in results.items():
            if m:
                print(f"{name}\t{m['id']}\t{m['name']}\t{m['match_type']}")
            else:
                print(f"{name}\tNO_MATCH")
        return 0

    if args.cmd == "query-signups":
        url_r = get_database_url(args.project_id, args.service_name)
        if not url_r["url"]:
            print(json.dumps({"error": url_r["error"]}, indent=2))
            return 1
        result = query_mvp_ground_truth_railway(url_r["url"], args.window_days, args.table)
        print(json.dumps(result, indent=2))
        return 0

    if args.cmd == "merge":
        result = merge_into_context(
            args.context, args.config,
            auto_confirm=args.auto_confirm, dry_run=args.dry_run,
        )
        print(json.dumps(result, indent=2))
        return 0 if result.get("step") in ("merged", "no_candidates", "no_postgres_projects", "skipped_auth") else 2

    return 1


if __name__ == "__main__":
    sys.exit(main())
