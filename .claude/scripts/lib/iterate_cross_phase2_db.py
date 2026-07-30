#!/usr/bin/env python3
"""DB pay-intent ground truth for /iterate --cross --phase2.

Queries each MVP's Supabase or Railway `public.pay_intent` table and folds a
DB-first pay-intent numerator into `.runs/iterate-cross-phase2-context.json`.
PostHog remains the fallback when the DB row source is unavailable or
untrusted.

Backend precedence (mirrors the Phase-1 state-x0b semantics — strict per-MVP
precedence, never a cross-backend union: one MVP has one production DB, and
unioning two databases risks double-counting the same user):
  1. Supabase Management API when `mvp_mappings.<name>.supabase_project_ref`
     is set and the local token exists.
  2. Railway Postgres via psql when the Supabase attempt ends in a reason in
     RAILWAY_PAY_INTENT_FALLBACK_REASONS and
     `mvp_mappings.<name>.railway_project_id` is mapped (config-driven only;
     fuzzy match / auto-confirm is x0b's job, never x5's).

Railway-specific failure reasons (all non-halting; the VERIFY invariant only
checks paid/reason None-ness, reason values are free-form):
  railway_auth_missing / railway_psql_missing — environment not ready
  railway_service_missing — could not resolve a DATABASE_PUBLIC_URL
  no_email_column — no email source (pay_intent.email or a joinable
     public.users) — MUST fail rather than return email-less rows, because
     the email filter classifies missing email as `test` and would produce a
     trusted zero that beats the PostHog fallback.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gclid_filter import is_real_gclid  # noqa: E402
from iterate_cross_db import _error_reason, _management_api_query  # noqa: E402
from iterate_cross_email_filter import filter_signups, internal_domains_for_mvp  # noqa: E402
from iterate_cross_railway_db import (  # noqa: E402
    _check_psql_available,
    _check_railway_auth,
    _psql_query,
    get_database_url,
)

try:
    import yaml
except ImportError:  # pragma: no cover - exercised by operator environments
    yaml = None


PROBE_UTM = "dayzero-probe"
TOKEN_PATH = Path.home() / ".supabase" / "access-token"
ERROR_REASONS = {"forbidden", "project_deleted", "query_error"}
# Supabase outcomes that make the Railway fallback worth attempting. Phase-1's
# RAILWAY_FALLBACK_REASONS plus "no_table": pay_intent is a fixed table name,
# so its absence on Supabase with an explicit railway_project_id mapping
# plausibly means the table lives on Railway (the extra probe only runs when
# the operator mapped the project).
RAILWAY_PAY_INTENT_FALLBACK_REASONS = {"no_token", "no_match", "no_table", "project_deleted"}


def _load_config(path: str) -> dict[str, Any]:
    if not path or not os.path.exists(path) or yaml is None:
        return {}
    return yaml.safe_load(open(path)) or {}


def _read_token_non_halting() -> str | None:
    """Read Supabase token without calling iterate_cross_db._read_token.

    `_read_token` raises SystemExit on absence. x5 must keep running so it can
    stamp fallback rows and fail visibly through source metrics.
    """
    if not TOKEN_PATH.exists():
        return None
    token = TOKEN_PATH.read_text().strip()
    return token or None


def _reason_from_response(payload: Any) -> str:
    if isinstance(payload, dict):
        reason = payload.get("reason")
        if reason in ERROR_REASONS:
            return str(reason)
    return _error_reason()


def _probe_has_pay_intent_table(response: Any) -> bool | None:
    if isinstance(response, dict):
        return None
    if not isinstance(response, list) or not response:
        return None
    row = response[0] if isinstance(response[0], dict) else {}
    value = row.get("regclass", row.get("to_regclass"))
    return value is not None


def _sql_quote(value: str) -> str:
    return str(value).replace("'", "''")


def fetch_pay_intent_rows(
    project_ref: str,
    window_days: int,
    phase_filter: str,
    token: str,
) -> tuple[list[dict] | None, str | None]:
    """Fetch phase-windowed pay_intent rows or return a non-halting reason."""
    probe_sql = "SELECT to_regclass('public.pay_intent') AS regclass"
    probe = _management_api_query(project_ref, probe_sql, token)
    has_table = _probe_has_pay_intent_table(probe)
    if has_table is None:
        return None, _reason_from_response(probe)
    if not has_table:
        return None, "no_table"

    escaped_filter = _sql_quote(str(phase_filter))
    escaped_probe_utm = _sql_quote(PROBE_UTM)
    days = int(window_days)
    sql = (
        "SELECT p.user_id::text AS user_id, "
        "p.distinct_id, "
        "u.email, "
        "p.gclid, "
        "p.price_cents::float8 AS price_cents, "
        "p.created_at::text AS created_at "
        "FROM public.pay_intent p "
        "LEFT JOIN auth.users u ON u.id = p.user_id "
        f"WHERE p.utm_campaign ILIKE '{escaped_filter}' "
        f"AND p.utm_campaign != '{escaped_probe_utm}' "
        f"AND p.created_at >= now() - INTERVAL '{days} days'"
    )
    rows = _management_api_query(project_ref, sql, token)
    if isinstance(rows, dict):
        return None, _reason_from_response(rows)
    if not isinstance(rows, list):
        return None, "query_error"
    return rows, None


def fetch_last_pay_intent_at(
    project_ref: str,
    token: str,
) -> tuple[str | None, str | None]:
    """Last pay_intent row EVER (wiring-liveness diagnostic).

    Deliberately unfiltered — no utm/window/probe exclusion. A fresh
    dayzero-probe row legitimately re-proves the client->DB wiring, which is
    exactly what the pay_intent_wiring_unproven flag asks the operator to do.
    """
    sql = "SELECT max(created_at)::text AS last_at FROM public.pay_intent"
    rows = _management_api_query(project_ref, sql, token)
    if isinstance(rows, dict):
        return None, _reason_from_response(rows)
    if not isinstance(rows, list):
        return None, "query_error"
    row = rows[0] if rows and isinstance(rows[0], dict) else {}
    return _normalize_pg_ts(row.get("last_at")), None


def fetch_gclid_no_utm_gclids(
    project_ref: str,
    window_days: int,
    token: str,
) -> tuple[list[str] | None, str | None]:
    """gclid values of windowed rows with NULL/empty utm_campaign.

    These rows are invisible to `fetch_pay_intent_rows` (its WHERE filters on
    the phase utm pattern) AND to the PostHog phase numerator — a shared blind
    spot. Callers count them python-side with `is_real_gclid` so the gclid
    validity rule stays single-source.
    """
    days = int(window_days)
    sql = (
        "SELECT p.gclid FROM public.pay_intent p "
        "WHERE (p.utm_campaign IS NULL OR p.utm_campaign = '') "
        f"AND p.created_at >= now() - INTERVAL '{days} days'"
    )
    rows = _management_api_query(project_ref, sql, token)
    if isinstance(rows, dict):
        return None, _reason_from_response(rows)
    if not isinstance(rows, list):
        return None, "query_error"
    return [str(r.get("gclid") or "") for r in rows if isinstance(r, dict)], None


def _railway_unavailable_reason() -> str | None:
    """Environment gate for the Railway path (auth + psql), non-halting."""
    if _check_railway_auth() is not None:
        return "railway_auth_missing"
    if _check_psql_available() is not None:
        return "railway_psql_missing"
    return None


def _railway_pay_intent_schema(db_url: str) -> tuple[dict[str, list[str]] | None, str | None]:
    """Column lists for public.pay_intent / public.users in one query."""
    sql = (
        "SELECT table_name, "
        "string_agg(column_name, ',' ORDER BY ordinal_position) "
        "FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name IN ('pay_intent', 'users') "
        "GROUP BY table_name"
    )
    r = _psql_query(db_url, sql)
    if r.get("error"):
        return None, "query_error"
    schema: dict[str, list[str]] = {}
    for row in r.get("rows") or []:
        if len(row) >= 2 and row[0]:
            schema[row[0]] = [c for c in row[1].split(",") if c]
    return schema, None


def _railway_row_to_dict(row: list[str]) -> dict[str, Any]:
    padded = list(row) + [""] * (6 - len(row))
    return {
        "user_id": padded[0] or None,
        "distinct_id": padded[1] or None,
        "email": padded[2] or None,
        "gclid": padded[3] or None,
        "price_cents": padded[4] or None,
        "created_at": padded[5] or None,
    }


def fetch_pay_intent_rows_railway(
    db_url: str,
    window_days: int,
    phase_filter: str,
) -> tuple[list[dict] | None, str | None]:
    """Railway twin of fetch_pay_intent_rows (same row-dict shape).

    Raw Postgres has no auth.users, so the email source is probed: an email
    column on pay_intent itself, else a joinable public.users(id, email).
    Neither -> "no_email_column" — never email-less rows (the email filter
    would classify them all as test and produce a trusted zero).
    """
    schema, reason = _railway_pay_intent_schema(db_url)
    if reason is not None:
        return None, reason
    if "pay_intent" not in (schema or {}):
        return None, "no_table"
    pay_cols = schema["pay_intent"]
    users_cols = schema.get("users") or []

    join_clause = ""
    if "email" in pay_cols:
        email_expr = "p.email"
    elif "user_id" in pay_cols and "id" in users_cols and "email" in users_cols:
        # ::text casts on both sides avoid a uuid/text operator mismatch.
        email_expr = "u.email"
        join_clause = "LEFT JOIN public.users u ON u.id::text = p.user_id::text "
    else:
        return None, "no_email_column"

    user_id_expr = "p.user_id::text" if "user_id" in pay_cols else "NULL::text"
    escaped_filter = _sql_quote(str(phase_filter))
    escaped_probe_utm = _sql_quote(PROBE_UTM)
    days = int(window_days)
    sql = (
        f"SELECT {user_id_expr}, p.distinct_id, {email_expr}, p.gclid, "
        "p.price_cents::float8, p.created_at::text "
        "FROM public.pay_intent p "
        f"{join_clause}"
        f"WHERE p.utm_campaign ILIKE '{escaped_filter}' "
        f"AND p.utm_campaign != '{escaped_probe_utm}' "
        f"AND p.created_at >= now() - INTERVAL '{days} days'"
    )
    r = _psql_query(db_url, sql)
    if r.get("error"):
        return None, "query_error"
    return [_railway_row_to_dict(row) for row in r.get("rows") or []], None


def fetch_last_pay_intent_at_railway(db_url: str) -> tuple[str | None, str | None]:
    """Railway twin of fetch_last_pay_intent_at (deliberately unfiltered)."""
    r = _psql_query(db_url, "SELECT max(created_at)::text FROM public.pay_intent")
    if r.get("error"):
        return None, "query_error"
    rows = r.get("rows") or []
    value = rows[0][0] if rows and rows[0] else None
    return _normalize_pg_ts(value), None


def fetch_gclid_no_utm_gclids_railway(
    db_url: str,
    window_days: int,
) -> tuple[list[str] | None, str | None]:
    """Railway twin of fetch_gclid_no_utm_gclids (caller counts python-side)."""
    days = int(window_days)
    sql = (
        "SELECT p.gclid FROM public.pay_intent p "
        "WHERE (p.utm_campaign IS NULL OR p.utm_campaign = '') "
        f"AND p.created_at >= now() - INTERVAL '{days} days'"
    )
    r = _psql_query(db_url, sql)
    if r.get("error"):
        return None, "query_error"
    return [str(row[0]) if row and row[0] else "" for row in r.get("rows") or []], None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dedupe_pay_intent_rows(rows: list[dict]) -> list[dict]:
    deduped: dict[str, dict] = {}
    order: list[str] = []
    for idx, row in enumerate(rows):
        key = row.get("user_id") or row.get("distinct_id") or f"__row_{idx}"
        key = str(key)
        if key not in deduped:
            deduped[key] = {
                "_key": key,
                "user_id": row.get("user_id"),
                "distinct_id": row.get("distinct_id"),
                "email": row.get("email"),
                "signup_at": row.get("created_at"),
                "gclid": row.get("gclid"),
                "_paid_prices": [],
            }
            order.append(key)
        target = deduped[key]
        if not target.get("email") and row.get("email"):
            target["email"] = row.get("email")
        if not target.get("signup_at") and row.get("created_at"):
            target["signup_at"] = row.get("created_at")
        gclid = row.get("gclid")
        if is_real_gclid(gclid):
            if not is_real_gclid(target.get("gclid")):
                target["gclid"] = gclid
            price = _to_float(row.get("price_cents"))
            if price is not None:
                target["_paid_prices"].append(price)
        elif not target.get("gclid") and gclid:
            target["gclid"] = gclid
    return [deduped[key] for key in order]


def summarize_pay_intents(
    rows: list[dict],
    config: dict[str, Any],
    internal_domains=(),
) -> dict[str, Any]:
    """Summarize DB pay_intent rows after user dedupe and email filtering."""
    deduped = _dedupe_pay_intent_rows(rows)
    filtered = filter_signups(deduped, config, internal_domains=internal_domains)
    audit = filtered.get("audit") or []
    real_rows = [
        row
        for row, audit_row in zip(deduped, audit)
        if audit_row.get("category") == "real"
    ]
    paid_rows = [row for row in real_rows if is_real_gclid(row.get("gclid"))]
    paid_prices = [
        price
        for row in paid_rows
        for price in (row.get("_paid_prices") or [])
        if price is not None
    ]

    return {
        "db_pay_intents_paid": len(paid_rows),
        "db_pay_intents_real": int(filtered.get("real", 0) or 0),
        "db_pay_intents_unattributed": int(filtered.get("real", 0) or 0) - len(paid_rows),
        "db_pay_intents_raw": len(deduped),
        "db_pay_intents_team": int(filtered.get("team", 0) or 0),
        "db_pay_intents_test": int(filtered.get("test", 0) or 0),
        "db_pay_intent_price_cents_max": max(paid_prices) if paid_prices else None,
        "db_pay_intent_price_variants": len(set(paid_prices)),
        "db_pay_intents_filter_audit": audit,
    }


def _stamp_failure(mvp: dict, reason: str) -> None:
    mvp["db_pay_intents_paid"] = None
    mvp["db_pay_intents_real"] = None
    mvp["db_pay_intents_unattributed"] = None
    mvp["db_pay_intents_raw"] = None
    mvp["db_pay_intents_team"] = 0
    mvp["db_pay_intents_test"] = 0
    mvp["db_pay_intents_filter_audit"] = []
    mvp["db_pay_intents_real_windowed"] = None
    mvp["db_pay_intents_unmapped_reason"] = reason
    mvp["db_pay_intent_price_cents_max"] = None
    mvp["db_pay_intent_price_variants"] = 0
    mvp.pop("db_pay_intent_source", None)
    # Diagnostic-only fields (wiring liveness / utm-null visibility). None means
    # "not checkable" — the paid/reason XOR invariant above is not involved.
    _stamp_diag_defaults(mvp)


def _stamp_diag_defaults(mvp: dict) -> None:
    mvp["db_last_pay_intent_at"] = None
    mvp["db_gclid_no_utm_count"] = None


def _normalize_pg_ts(value: object) -> str | None:
    """Normalize Postgres `::text` timestamps for datetime.fromisoformat.

    Supabase renders offsets as `+00`, which Python 3.9's fromisoformat (the
    interpreter the x5 state heredocs run under) rejects — append `:00`.
    """
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if re.search(r"[+-]\d{2}$", text):
        text += ":00"
    return text


def _stamp_success(mvp: dict, summary: dict[str, Any], source: str = "supabase") -> None:
    for key, value in summary.items():
        mvp[key] = value
    mvp["db_pay_intents_real_windowed"] = True
    mvp["db_pay_intents_unmapped_reason"] = None
    mvp["db_pay_intent_source"] = source


def _merge_railway_mvp(
    mvp: dict,
    mapping: dict[str, Any],
    window_days: int,
    phase_filter: str,
    config: dict[str, Any],
    env_cache: dict[str, Any],
) -> str | None:
    """Attempt the Railway pay-intent path for one MVP. None = success.

    The whole body degrades to a reason instead of raising: get_database_url /
    _psql_query shell out and can raise (TimeoutExpired, FileNotFoundError)
    mid-run, and the merge must stamp every MVP either way.
    """
    try:
        if "reason" not in env_cache:
            # Evaluated lazily on the first railway-mapped MVP so pure-Supabase
            # fleets never shell out to `railway whoami` / `psql --version`.
            env_cache["reason"] = _railway_unavailable_reason()
        if env_cache["reason"]:
            return str(env_cache["reason"])

        project_id = str(mapping.get("railway_project_id"))
        service_name = mapping.get("railway_service_name") or "Postgres"
        url_r = get_database_url(project_id, service_name)
        if not url_r.get("url"):
            return "railway_service_missing"

        rows, reason = fetch_pay_intent_rows_railway(url_r["url"], window_days, phase_filter)
        if reason is not None:
            return reason

        internal_domains = internal_domains_for_mvp(config, str(mvp.get("name") or ""))
        _stamp_success(
            mvp,
            summarize_pay_intents(rows or [], config, internal_domains=internal_domains),
            source="railway",
        )
        mvp["railway_project_id"] = project_id

        # Diagnostic twins — non-fatal by construction, same as the Supabase path.
        _stamp_diag_defaults(mvp)
        try:
            last_at, last_reason = fetch_last_pay_intent_at_railway(url_r["url"])
            if last_reason is None:
                mvp["db_last_pay_intent_at"] = last_at
        except Exception:
            pass
        try:
            gclids, gclid_reason = fetch_gclid_no_utm_gclids_railway(url_r["url"], window_days)
            if gclid_reason is None and gclids is not None:
                mvp["db_gclid_no_utm_count"] = sum(1 for g in gclids if is_real_gclid(g))
        except Exception:
            pass
        return None
    except Exception:
        return "query_error"


def _default_fill(mvp: dict) -> None:
    reason = mvp.get("db_pay_intents_unmapped_reason")
    if mvp.get("db_pay_intents_paid") is None and reason is None:
        mvp["db_pay_intents_unmapped_reason"] = "query_error"
        reason = "query_error"
    if reason is not None:
        _stamp_failure(mvp, str(reason))
        return
    mvp.setdefault("db_pay_intents_real", mvp.get("db_pay_intents_paid", 0))
    mvp.setdefault("db_pay_intents_unattributed", 0)
    mvp.setdefault("db_pay_intents_raw", mvp.get("db_pay_intents_real", 0))
    mvp.setdefault("db_pay_intents_team", 0)
    mvp.setdefault("db_pay_intents_test", 0)
    mvp.setdefault("db_pay_intents_filter_audit", [])
    mvp.setdefault("db_pay_intents_real_windowed", True)
    mvp.setdefault("db_pay_intent_price_cents_max", None)
    mvp.setdefault("db_pay_intent_price_variants", 0)


def _triage_row(mvp: dict) -> dict[str, Any]:
    return {
        "name": mvp.get("name"),
        "reason": mvp.get("db_pay_intents_unmapped_reason"),
        "db_pay_intents_real": mvp.get("db_pay_intents_real"),
        "db_pay_intents_raw": mvp.get("db_pay_intents_raw"),
        "pay_intents_ph": int(mvp.get("pay_intents", 0) or 0),
        "db_gclid_no_utm": mvp.get("db_gclid_no_utm_count"),
    }


def merge_context(
    context_path: str,
    config_path: str,
    triage_out: str,
    token: str | None = None,
) -> dict[str, Any]:
    if not os.path.exists(context_path):
        raise SystemExit(f"ERROR: --context path does not exist: {context_path}")

    ctx = json.load(open(context_path))
    config = _load_config(config_path)
    mappings = config.get("mvp_mappings") or {}
    mvps = ctx.get("mvps") or []
    run_token = ctx.get("phase2_run_token")
    if not run_token:
        run_token = datetime.now(timezone.utc).isoformat()
        ctx["phase2_run_token"] = run_token
    window_days = int(ctx.get("window_days", config.get("window_days", 90)) or 90)
    phase_filter = str(
        ctx.get(
            "phase2_utm_campaign_like",
            (config.get("phase2") or {}).get("utm_campaign_like", "%phase2%"),
        )
    )

    token = token if token is not None else _read_token_non_halting()
    queried = 0
    no_token = 0
    no_table = 0
    errored = 0
    railway_queried = 0
    railway_unavailable = 0
    railway_env: dict[str, Any] = {}

    for mvp in mvps:
        name = mvp.get("name")
        mapping = mappings.get(name) or {}
        railway_project_id = mapping.get("railway_project_id")
        if token is None and not railway_project_id:
            _stamp_failure(mvp, "no_token")
            no_token += 1
            continue
        if mvp.get("orphan"):
            _stamp_failure(mvp, "orphan")
            continue
        project_ref = mapping.get("supabase_project_ref")

        # --- Supabase attempt (primary backend) ---
        reason: str | None
        if token is None:
            reason = "no_token"
        elif not project_ref:
            reason = "no_match"
        else:
            rows, reason = fetch_pay_intent_rows(project_ref, window_days, phase_filter, token)
            queried += 1
            mvp["supabase_project_ref"] = project_ref
            if reason is None:
                internal_domains = internal_domains_for_mvp(config, str(name or ""))
                _stamp_success(mvp, summarize_pay_intents(rows or [], config, internal_domains=internal_domains))

                # Diagnostic queries (B1 wiring liveness + B5 utm-null visibility).
                # Non-fatal by construction: ANY diag failure — error payload OR
                # raised exception — leaves the field None ("not checkable")
                # without touching the paid/reason invariant or counters.
                _stamp_diag_defaults(mvp)
                try:
                    last_at, last_reason = fetch_last_pay_intent_at(project_ref, token)
                    if last_reason is None:
                        mvp["db_last_pay_intent_at"] = last_at
                except Exception:
                    pass
                try:
                    gclids, gclid_reason = fetch_gclid_no_utm_gclids(project_ref, window_days, token)
                    if gclid_reason is None and gclids is not None:
                        mvp["db_gclid_no_utm_count"] = sum(1 for g in gclids if is_real_gclid(g))
                except Exception:
                    pass
                continue

        # --- Railway fallback (strict precedence, config-driven mapping only) ---
        if railway_project_id and reason in RAILWAY_PAY_INTENT_FALLBACK_REASONS:
            railway_reason = _merge_railway_mvp(
                mvp, mapping, window_days, phase_filter, config, railway_env
            )
            if railway_reason is None:
                railway_queried += 1
                continue
            if railway_reason in ("railway_auth_missing", "railway_psql_missing"):
                railway_unavailable += 1
            reason = railway_reason

        _stamp_failure(mvp, reason)
        if reason == "no_table":
            no_table += 1
        elif reason in ERROR_REASONS:
            errored += 1

    for mvp in mvps:
        _default_fill(mvp)
        mvp.setdefault("db_last_pay_intent_at", None)
        mvp.setdefault("db_gclid_no_utm_count", None)

    triage = {
        "run_token": run_token,
        "mvps": [_triage_row(mvp) for mvp in mvps],
    }
    ctx["phase2_db_merge"] = {
        "run_token": run_token,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "mvps_queried": queried,
        "mvps_no_token": no_token,
        "mvps_no_table": no_table,
        "mvps_errored": errored,
        "mvps_railway_queried": railway_queried,
        "mvps_railway_unavailable": railway_unavailable,
    }
    ctx["mvps"] = mvps

    json.dump(ctx, open(context_path, "w"), indent=2)
    json.dump(triage, open(triage_out, "w"), indent=2)
    return {"step": "merged", **ctx["phase2_db_merge"], "triage_out": triage_out}


def cmd_merge(args: argparse.Namespace) -> int:
    result = merge_context(args.context, args.config, args.triage_out)
    print(json.dumps(result, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_merge = sub.add_parser("merge", help="Fold DB pay_intent counts into phase2 context.")
    p_merge.add_argument("--context", required=True)
    p_merge.add_argument("--config", required=True)
    p_merge.add_argument("--triage-out", default=".runs/_iterate-cross-phase2-db-unmatched.json")
    p_merge.set_defaults(func=cmd_merge)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
