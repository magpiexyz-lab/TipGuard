"""
DB ground-truth fetcher for /iterate --cross state-x0b.

Queries each MVP's Supabase project for the authoritative signup count and folds
it into iterate-cross-context.json. State-x3 cross-checks this against PostHog
paid signups and emits sanity flags (ph_attribution_broken, ph_undercount,
ph_overcount, late_instrumentation) so the operator sees when PostHog tracking
diverges from the database.

PostHog visitor counts answer "how many paid users engaged with the page".
Supabase signup count answers "how many actually completed registration".
The two should roughly agree; when they don't, that's a tracking gap worth
surfacing — not a verdict bug.

Subcommands
-----------
  list-projects       — list Supabase projects via Management API (cached)
  fuzzy-match         — given mvps[] from context, propose name → project_ref
  discover-tables     — for one project_ref, enumerate candidate signup tables
  query-signups       — for one project_ref, count signups in window
  merge               — orchestrator: read context, fuzzy-match (or use config
                        overrides), discover, query, write back to context

Schema written into each mvp record
------------------------------------
  supabase_project_ref     str | None  (None = unmapped, can't validate)
  supabase_project_name    str | None  (display name, for confirm UI)
      db_signups               int | None  (None = unmapped or query failed;
                                           union raw when the union candidate wins)
      db_signups_paid          int | None  (union real emails with a valid
                                           POPULATED gclid in >=1 table; 0 =
                                           gclid columns exist but none
                                           validate; None = no contributing
                                           table has a gclid column)
      db_attribution           str | None  ("gclid_shape" iff db_signups_paid > 0,
                                           else "window"; None = unmapped)
  db_signups_table         str | None  (top real contributor — reporting only,
                                        counts are cross-table union-deduped)
  db_union_tables          list[str]   (tables contributing >=1 real email to
                                        the union; [] on single/legacy paths)
  db_first_signup_at       str | None  (ISO timestamp of earliest row in window)
  db_unmapped_reason       str | None  ("no_match", "ambiguous", "operator_skip")
  db_breakdown             dict        ({table_name: count} for transparency)

The discover-tables logic is shared with the persist step so unit tests don't
need a live API. Network IO is isolated in `_management_api_query`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

from iterate_cross_relaunch import parse_relaunch_at, postgres_lower_bound_expr
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gclid_filter import is_real_gclid  # noqa: E402
from iterate_cross_email_filter import filter_signups, gmail_normalize, internal_domains_for_mvp  # noqa: E402

try:
    import yaml
except ImportError:
    yaml = None

# Supabase's Cloudflare edge rejects the default urllib UA (`Python-urllib/*`)
# with error 1010. Send a self-identifying User-Agent like every well-behaved
# client (curl, the Supabase CLI, requests) so the Management API stays reachable.
_SUPABASE_USER_AGENT = "mvp-template-iterate-cross/1.0 (+supabase-management-api)"

# Table names that strongly suggest signup data. Matched as case-insensitive
# substring on table_name. Order matters for table-discovery priority.
SIGNUP_TABLE_PATTERNS = [
    "signup",
    "waitlist",
    "early_access",
    "email_subscribers",
    "subscribers",
    "registrations",
    "users",
    "profiles",
    # Appended LAST (lowest priority) so existing fleet selections are
    # unchanged: "leads" only wins when no other pattern matches. Added for
    # the pagoo false-zero (emails persisted to public.leads; discovery fell
    # back to auth.users' single test row and reported db_real_zero, hiding
    # 11 PostHog-verified paid signups).
    "leads",
]

# Tables to exclude even when the name matches the patterns above. These are
# Supabase-internal tables, billing tables, or other false positives we've
# observed across the fleet (auditbot v1 launch sample).
SIGNUP_TABLE_EXCLUSIONS = {
    "auth.users",  # handled separately as auth_users count
    "billing_users",
    "stripe_users",
    "team_members",  # team invites, not signups
    "team_invites",
    "_auto_migrations",
}

# Common signup-timestamp column names, probed in order. First match wins.
TIMESTAMP_COLUMN_CANDIDATES = [
    "created_at",
    "inserted_at",
    "signed_up_at",
    "submitted_at",
    "registered_at",
]


# "archived_killed" (policy skip for killed MVPs) is deliberately ABSENT:
# killed rows are archived, not retried — burning a Railway probe on them
# buys nothing. "project_deleted" stays: an actively-queried MVP whose
# Supabase was torn down may have moved its DB to Railway. "ref_invalid"
# (tombstone probe says the ref never existed — a bad/stale mapping, not an
# observed deletion) gets the same retry: the real DB may live on Railway.
RAILWAY_FALLBACK_REASONS = {
    "no_match", "no_token", "no_email_column", "project_deleted", "ref_invalid",
}


def _detected_gclid_column(columns: list[str]) -> str | None:
    if "gclid" in columns:
        return "gclid"
    if "click_id" in columns:
        return "click_id"
    return None


def _priority_value(candidate: dict) -> int:
    priority = candidate.get("priority")
    return int(priority) if priority is not None else 999


def _rank_signup_tables_for_probe(tables: list[dict], limit: int = 5) -> list[dict]:
    """Rank before capping, while keeping email/gclid-bearing tables discoverable."""
    ranked = sorted(
        tables,
        key=lambda t: (
            0 if t.get("gclid_column") else 1,
            _priority_value(t),
            t.get("table") or "",
        ),
    )
    selected: list[dict] = []
    for table in ranked:
        columns = table.get("columns") or []
        protected = bool(table.get("gclid_column") or "email" in columns)
        if protected or len(selected) < limit:
            selected.append(table)
    return selected


def allow_railway_fallback(reason: str | None) -> bool:
    return reason in RAILWAY_FALLBACK_REASONS


PROJECT_REMOVED_MESSAGES = {
    "resource has been removed",
    "project not found",
}


def _project_removed_payload(payload: Any) -> bool:
    """True only for project-level deletion payloads, not SQL/table errors."""
    if not isinstance(payload, dict):
        return False
    message = payload.get("message")
    if not isinstance(message, str):
        return False
    return message.strip().lower() in PROJECT_REMOVED_MESSAGES


def _error_reason(status: int | None = None, payload: Any = None) -> str:
    if status == 403:
        return "forbidden"
    if status == 404:
        return "project_deleted"
    if _project_removed_payload(payload):
        return "project_deleted"
    return "query_error"


def _error_payload(message: str, reason: str = "query_error") -> dict:
    return {"error": message, "reason": reason}


def _decode_http_body(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace")


def _urlopen_text(req: urllib.request.Request, timeout: int) -> tuple[int | None, str, str | None]:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", None)
            if status is None:
                status = resp.getcode()
            return status, _decode_http_body(resp.read()), None
    except urllib.error.HTTPError as e:
        return e.code, _decode_http_body(e.read()), None
    except TimeoutError:
        return None, "", "urlopen timed out"
    except urllib.error.URLError as e:
        return None, "", f"urlopen error: {e.reason}"


def _read_token_from_keychain() -> str | None:
    """Best-effort, targeted macOS Keychain lookup for Supabase CLI tokens."""
    if sys.platform != "darwin":
        return None
    try:
        r = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s",
                "supabase",
                "-a",
                "access-token",
                "-w",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    token = (r.stdout or "").strip()
    if r.returncode == 0 and token:
        return token
    return None


def _read_token() -> str:
    """Resolve Supabase personal access token.

    Resolution order is intentionally narrow:
      1. SUPABASE_ACCESS_TOKEN
      2. ~/.supabase/access-token
      3. one targeted macOS Keychain lookup (best-effort)

    Failure mode is loud — the caller HALTs with operator-facing instructions
    so a missing token is treated like a missing GA CSV (state-x0a precedent),
    not silently skipped.
    """
    env_token = (os.environ.get("SUPABASE_ACCESS_TOKEN") or "").strip()
    if env_token:
        return env_token

    path = Path.home() / ".supabase" / "access-token"
    if path.exists():
        token = path.read_text().strip()
        if token:
            return token

    keychain_token = _read_token_from_keychain()
    if keychain_token:
        return keychain_token

    raise SystemExit(
        "ERROR: Supabase access token not found.\n"
        "Resolution order: SUPABASE_ACCESS_TOKEN, ~/.supabase/access-token, "
        "then one targeted macOS Keychain lookup.\n"
        "Run `supabase login` once or export SUPABASE_ACCESS_TOKEN."
    )


def _management_api_query(project_ref: str, sql: str, token: str | None = None) -> Any:
    """Execute SQL against a Supabase project via Management API.

    Network IO is isolated here so the unit tests can monkeypatch this single
    function without spinning up a fake HTTP server.
    """
    token = token or _read_token()
    body = json.dumps({"query": sql})
    req = urllib.request.Request(
        f"https://api.supabase.com/v1/projects/{project_ref}/database/query",
        data=body.encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": _SUPABASE_USER_AGENT,
        },
        method="POST",
    )
    status, body_text, transport_error = _urlopen_text(req, timeout=30)
    if transport_error:
        return _error_payload(transport_error)
    try:
        data = json.loads(body_text) if body_text.strip() else {}
    except json.JSONDecodeError:
        return _error_payload(f"non-json response: {body_text[:200]}", _error_reason(status))
    if status and status >= 400:
        return _error_payload(f"http {status}: {json.dumps(data)[:200]}", _error_reason(status, data))
    if not isinstance(data, list):
        reason = data.get("reason") if isinstance(data, dict) else None
        return _error_payload(f"non-list response: {json.dumps(data)[:200]}", reason or _error_reason(status, data))
    return data


def probe_supabase_projects(token: str | None = None) -> dict:
    """Live GET /v1/projects probe used by state-x0b availability gating."""
    token = token or _read_token()
    req = urllib.request.Request(
        "https://api.supabase.com/v1/projects",
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": _SUPABASE_USER_AGENT,
        },
        method="GET",
    )
    status, body_text, transport_error = _urlopen_text(req, timeout=15)
    if transport_error:
        return {"ok": False, "projects": [], "reason": transport_error}
    try:
        data = json.loads(body_text) if body_text.strip() else []
    except json.JSONDecodeError:
        return {"ok": False, "projects": [], "reason": f"non-json response: {body_text[:200]}"}
    if status and status >= 400:
        return {"ok": False, "projects": [], "reason": f"http {status}: {json.dumps(data)[:200]}"}
    if not isinstance(data, list):
        return {"ok": False, "projects": [], "reason": f"non-list response: {json.dumps(data)[:200]}"}
    projects = [
        {
            "id": p.get("id"),
            "name": p.get("name"),
            "region": p.get("region"),
            # Raw platform status (e.g. ACTIVE_HEALTHY, INACTIVE/paused).
            # Carried as evidence for the killed-MVP backend verification —
            # a paused project still appears in this list, so list membership
            # proves existence regardless of pause state.
            "status": p.get("status"),
        }
        for p in data
        if p.get("id")
    ]
    return {"ok": True, "projects": projects, "reason": None}


def list_supabase_projects(token: str | None = None) -> list[dict]:
    """List Supabase projects accessible to the token."""
    probe = probe_supabase_projects(token)
    if not probe.get("ok"):
        return []
    return [
        {
            "id": p.get("id"),
            "name": p.get("name"),
            "region": p.get("region"),
            "status": p.get("status"),
        }
        for p in probe.get("projects", [])
    ]


# --- Killed-MVP backend verification (honest db_backend state) ---------------
#
# lifecycle_status is a DECISION about the product; backend existence is a FACT
# about infrastructure. The two used to be conflated: every killed MVP was
# stamped db_unmapped_reason="project_deleted" without any query (live audit
# 2026-07-21: 6 of 48 killed backends were still alive). Killed rows now carry
# db_unmapped_reason="archived_killed" (policy skip) and the knowledge state
# lives in the sticky config record mvp_mappings.<name>.db_backend.

BACKEND_STATUS_ALIVE = "alive"
BACKEND_STATUS_DELETED = "deleted_verified"
BACKEND_STATUS_NEVER_EXISTED = "never_existed"
BACKEND_STATUS_NOT_VISIBLE = "not_visible"
BACKEND_STATUS_NEVER_LOCATED = "never_located"

# Terminal states are never re-probed: a tombstone cannot come back to life,
# and a never-existed ref stays wrong until the operator fixes the mapping.
BACKEND_TERMINAL_STATUSES = {BACKEND_STATUS_DELETED, BACKEND_STATUS_NEVER_EXISTED}


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def probe_project_tombstone(project_ref: str, token: str | None = None) -> dict:
    """Classify one Supabase ref via GET /v1/projects/{ref} (detail endpoint).

    Live-verified mapping (2026-07-21, admin token):
      200                                    -> alive
      any status + body message in
        PROJECT_REMOVED_MESSAGES (seen: 400) -> deleted_verified (tombstone)
      403                                    -> not_visible (exists outside org)
      404 (plain "Not Found" body)           -> never_existed (bad ref)
    Transport errors / 5xx / unrecognized bodies -> status None so callers
    never persist a terminal state on flaky evidence.

    NOTE: this is the project-detail endpoint, NOT the SQL query endpoint used
    by _management_api_query — their status semantics differ (the SQL endpoint
    404s for both deleted and never-existed refs).
    """
    token = token or _read_token()
    req = urllib.request.Request(
        f"https://api.supabase.com/v1/projects/{project_ref}",
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": _SUPABASE_USER_AGENT,
        },
        method="GET",
    )
    status, body_text, transport_error = _urlopen_text(req, timeout=15)
    if transport_error:
        return {"status": None, "http_status": None, "message": transport_error}
    try:
        data = json.loads(body_text) if body_text.strip() else {}
    except json.JSONDecodeError:
        data = {}
    message = data.get("message") if isinstance(data, dict) else None
    if status == 200:
        return {"status": BACKEND_STATUS_ALIVE, "http_status": 200, "message": None}
    if _project_removed_payload(data):
        return {"status": BACKEND_STATUS_DELETED, "http_status": status, "message": message}
    if status == 403:
        return {"status": BACKEND_STATUS_NOT_VISIBLE, "http_status": 403, "message": message}
    if status == 404:
        return {"status": BACKEND_STATUS_NEVER_EXISTED, "http_status": 404, "message": message}
    return {"status": None, "http_status": status, "message": message or body_text[:200]}


def resolve_backend_state(
    name: str,
    mapping: dict,
    live_project_ids: set[str],
    token: str | None = None,
    backend_writes: dict | None = None,
) -> dict | None:
    """Resolve a killed MVP's db_backend knowledge state.

    Free path first: a ref present in the already-fetched org project list is
    alive (membership proves existence even for paused projects). Refs absent
    from the list get a one-time tombstone probe unless a terminal sticky
    record already exists. No ref at all -> never_located (unless the row is
    Railway-backed — Railway probing lands with the x4b reconcile state).

    When `backend_writes` is provided, changed records are queued there for a
    single config write by the caller. Returns the record (or the untouched
    sticky record), or None when nothing can be said (Railway-backed rows,
    probe returned flaky evidence with no prior sticky record).
    """
    sticky = mapping.get("db_backend") or {}
    project_ref = mapping.get("supabase_project_ref")

    def queue(record: dict) -> dict:
        if backend_writes is not None and (
            record.get("status") != sticky.get("status")
            or not sticky.get("checked_at")
        ):
            backend_writes[name] = record
        return record

    if not project_ref:
        if mapping.get("railway_project_id"):
            # Railway-backed: tombstone probing is Supabase-only; the x4b
            # reconcile state owns the Railway evidence line. Keep sticky.
            return sticky or None
        return queue({
            "status": BACKEND_STATUS_NEVER_LOCATED,
            "checked_at": _utc_now_iso(),
            "evidence": "no supabase_project_ref or railway_project_id in config",
        })

    if project_ref in live_project_ids:
        return queue({
            "status": BACKEND_STATUS_ALIVE,
            "checked_at": _utc_now_iso(),
            "evidence": "ref present in org project list",
        })

    if sticky.get("status") in BACKEND_TERMINAL_STATUSES:
        return sticky

    probe = probe_project_tombstone(project_ref, token)
    if probe.get("status") is None:
        # Flaky/unrecognized evidence — never persist; keep whatever we knew.
        return sticky or None
    return queue({
        "status": probe["status"],
        "checked_at": _utc_now_iso(),
        "evidence": f"http {probe.get('http_status')}: {probe.get('message') or 'ok'}",
    })


def confirm_project_deleted(
    project_ref: str,
    mapping: dict,
    live_project_ids: set[str],
    token: str | None = None,
) -> tuple[str, dict | None]:
    """Confirm a query-path "project_deleted" via the tombstone endpoint.

    The SQL query endpoint 404s for BOTH deleted and never-existed refs (see
    probe_project_tombstone's NOTE), so the query-path reason alone overclaims
    deletion — a bad/stale mapping ref would read as "backend gone" and force
    a rule-3 NO_GO on a product whose real DB was simply never located.

    Returns (final_reason, db_backend_record_or_None):
      sticky deleted_verified          -> ("project_deleted", None)  # terminal, no re-probe
      sticky never_existed             -> ("ref_invalid", None)
      ref in live org list             -> ("query_error", alive record)  # exists; the 404 was transient/something else
      probe deleted_verified           -> ("project_deleted", tombstone record)
      probe never_existed              -> ("ref_invalid", record)
      probe not_visible                -> ("forbidden", record)
      probe alive                      -> ("query_error", alive record)
      probe flaky (status None)        -> ("query_error", None)

    Failure direction: deletion is only ever CONCLUDED on tombstone evidence
    (payload "Resource has been removed"); flaky probes downgrade to
    query_error and the next run re-confirms — a real deletion is delayed one
    run at worst, a false deletion verdict is never minted.
    """
    sticky = (mapping.get("db_backend") or {})
    if sticky.get("status") == BACKEND_STATUS_DELETED:
        return "project_deleted", None
    if sticky.get("status") == BACKEND_STATUS_NEVER_EXISTED:
        return "ref_invalid", None

    def record(status: str, evidence: str) -> dict:
        return {"status": status, "checked_at": _utc_now_iso(), "evidence": evidence}

    if project_ref in live_project_ids:
        return "query_error", record(
            BACKEND_STATUS_ALIVE, "ref present in org project list"
        )

    probe = probe_project_tombstone(project_ref, token)
    status = probe.get("status")
    evidence = f"http {probe.get('http_status')}: {probe.get('message') or 'ok'}"
    if status == BACKEND_STATUS_DELETED:
        return "project_deleted", record(status, evidence)
    if status == BACKEND_STATUS_NEVER_EXISTED:
        return "ref_invalid", record(status, evidence)
    if status == BACKEND_STATUS_NOT_VISIBLE:
        return "forbidden", record(status, evidence)
    if status == BACKEND_STATUS_ALIVE:
        return "query_error", record(status, evidence)
    return "query_error", None


def write_backend_records(config_path: str, config: dict, backend_writes: dict) -> None:
    """Persist queued db_backend records into mvp_mappings (idempotent)."""
    if not backend_writes:
        return
    mappings = config.setdefault("mvp_mappings", {})
    for mvp_name, record in backend_writes.items():
        entry = mappings.setdefault(mvp_name, {})
        entry["db_backend"] = record
    with open(config_path, "w") as f:
        yaml.safe_dump(config, f, sort_keys=False, default_flow_style=False)


def normalize_name(s: str) -> str:
    """Strip non-alphanumerics + lowercase. Used for fuzzy matching MVP names
    against Supabase project names. "stylica-ai" → "stylicaai",
    "neuralpost-prod" → "neuralpostprod"."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def fuzzy_match_projects(
    mvp_names: list[str],
    projects: list[dict],
) -> dict[str, dict | None]:
    """Match MVP names to Supabase projects by normalized-name similarity.

    Strategies (in order, first wins per MVP):
      1. Exact normalized match (stylica-ai == stylica-ai)
      2. Project-name CONTAINS mvp normalized name (neuralpost vs neuralpost-prod)
      3. MVP normalized name CONTAINS project name (handpick vs handpick)

    Returns: {mvp_name: {"id": ref, "name": display_name, "match_type": str} | None}
    """
    by_norm = {normalize_name(p["name"]): p for p in projects}
    results: dict[str, dict | None] = {}

    for mvp in mvp_names:
        mvp_norm = normalize_name(mvp)
        if not mvp_norm:
            results[mvp] = None
            continue

        # 1. Exact match
        if mvp_norm in by_norm:
            p = by_norm[mvp_norm]
            results[mvp] = {"id": p["id"], "name": p["name"], "match_type": "exact"}
            continue

        # 2. Project name contains MVP name (prod suffix etc.)
        candidates_2 = [
            p for norm, p in by_norm.items()
            if mvp_norm in norm and len(norm) > len(mvp_norm)
        ]
        if len(candidates_2) == 1:
            p = candidates_2[0]
            results[mvp] = {"id": p["id"], "name": p["name"], "match_type": "project_contains_mvp"}
            continue
        if len(candidates_2) > 1:
            # Ambiguous — surface and let operator pick. Prefer shortest project
            # name (less likely to be a "stylica-ai-staging" instance).
            candidates_2.sort(key=lambda p: len(p["name"]))
            p = candidates_2[0]
            results[mvp] = {
                "id": p["id"],
                "name": p["name"],
                "match_type": "ambiguous_project_contains_mvp",
                "alternatives": [c["id"] for c in candidates_2[1:]],
            }
            continue

        # 3. MVP name contains project name (rarer; e.g. mvp 'agent-cost-monitor-v2'
        # → project 'agent-cost-monitor')
        candidates_3 = [
            p for norm, p in by_norm.items()
            if norm in mvp_norm and len(norm) >= 5
        ]
        if len(candidates_3) == 1:
            p = candidates_3[0]
            results[mvp] = {"id": p["id"], "name": p["name"], "match_type": "mvp_contains_project"}
            continue

        results[mvp] = None
    return results


def _signup_table_catalog_sql() -> str:
    return (
        "SELECT table_name, "
        "string_agg(column_name, ',' ORDER BY ordinal_position) AS columns "
        "FROM information_schema.columns "
        "WHERE table_schema = 'public' "
        "GROUP BY table_name "
        "ORDER BY table_name"
    )


def _signup_candidates_from_catalog(resp: list[dict]) -> list[dict]:
    candidates = []
    for row in resp:
        table_name = row.get("table_name")
        if not table_name or table_name in SIGNUP_TABLE_EXCLUSIONS:
            continue
        columns = (row.get("columns") or "").split(",")
        # Find a timestamp column
        ts_col = None
        for cand in TIMESTAMP_COLUMN_CANDIDATES:
            if cand in columns:
                ts_col = cand
                break
        # Match patterns
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


def _discover_signup_tables_result(project_ref: str, token: str | None = None) -> dict:
    sql = _signup_table_catalog_sql()
    resp = _management_api_query(project_ref, sql, token)
    if isinstance(resp, dict) and "error" in resp:
        return {
            "tables": [],
            "error": resp["error"],
            "reason": resp.get("reason", "query_error"),
        }
    if not isinstance(resp, list):
        return {"tables": [], "error": "non-list response", "reason": "query_error"}

    return {"tables": _signup_candidates_from_catalog(resp), "error": None, "reason": None}


def discover_signup_tables(project_ref: str, token: str | None = None) -> list[dict]:
    """Find candidate signup tables in public schema.

    Returns list of {table, columns: [...], timestamp_column: str | None}
    sorted by signup-pattern priority (signup → waitlist → ... → users).
    """
    return _discover_signup_tables_result(project_ref, token)["tables"]


def count_signups_in_window(
    project_ref: str,
    table: str,
    timestamp_column: str | None,
    window_days: int,
    token: str | None = None,
    relaunch_at: str | None = None,
) -> dict:
    """Count rows in `public.{table}` whose timestamp_column is within window.

    Falls back to total row count when timestamp_column is None (table has no
    obvious created_at). Returns {"count": int, "first_at": str | None,
    "window_filtered": bool}. `relaunch_at` (per-MVP Phase-1 relaunch date)
    raises the lower bound to max(window, relaunch) — see iterate_cross_relaunch.
    """
    if timestamp_column:
        sql = (
            f'SELECT count(*) AS n, '
            f'min("{timestamp_column}")::text AS first_at '
            f'FROM public."{table}" '
            f'WHERE {postgres_lower_bound_expr(timestamp_column, window_days, relaunch_at)}'
        )
        window_filtered = True
    else:
        sql = f'SELECT count(*) AS n, NULL::text AS first_at FROM public."{table}"'
        window_filtered = False

    resp = _management_api_query(project_ref, sql, token)
    if isinstance(resp, dict) and "error" in resp:
        return {"count": None, "first_at": None, "window_filtered": window_filtered, "error": resp["error"]}
    if not isinstance(resp, list) or not resp:
        return {"count": 0, "first_at": None, "window_filtered": window_filtered}
    row = resp[0]
    return {
        "count": int(row.get("n", 0) or 0),
        "first_at": row.get("first_at"),
        "window_filtered": window_filtered,
    }


def count_auth_users_in_window(
    project_ref: str,
    window_days: int,
    token: str | None = None,
    relaunch_at: str | None = None,
) -> dict:
    """Count Supabase Auth users in window, both total and confirmed."""
    sql = (
        f"SELECT count(*) AS total, "
        f"count(*) FILTER (WHERE email_confirmed_at IS NOT NULL) AS confirmed, "
        f"min(created_at)::text AS first_at "
        f"FROM auth.users "
        f"WHERE {postgres_lower_bound_expr('created_at', window_days, relaunch_at)}"
    )
    resp = _management_api_query(project_ref, sql, token)
    if isinstance(resp, dict) and "error" in resp:
        return {"total": 0, "confirmed": 0, "first_at": None, "error": resp["error"]}
    if not isinstance(resp, list) or not resp:
        return {"total": 0, "confirmed": 0, "first_at": None}
    row = resp[0]
    return {
        "total": int(row.get("total", 0) or 0),
        "confirmed": int(row.get("confirmed", 0) or 0),
        "first_at": row.get("first_at"),
    }


def select_signups_in_window(
    project_ref: str,
    table: str,
    timestamp_column: str | None,
    window_days: int,
    token: str | None = None,
    gclid_column: str | None = None,
    relaunch_at: str | None = None,
) -> dict:
    gclid_select = f', "{gclid_column}" AS gclid' if gclid_column else ""
    if timestamp_column:
        sql = (
            f'SELECT email, "{timestamp_column}" AS signup_at{gclid_select} '
            f'FROM public."{table}" '
            f'WHERE {postgres_lower_bound_expr(timestamp_column, window_days, relaunch_at)}'
        )
        windowed = True
    else:
        sql = f'SELECT email, NULL AS signup_at{gclid_select} FROM public."{table}"'
        windowed = False
    resp = _management_api_query(project_ref, sql, token)
    if isinstance(resp, dict) and "error" in resp:
        return {"rows": None, "windowed": windowed, "error": resp["error"], "reason": resp.get("reason", "query_error")}
    if not isinstance(resp, list):
        return {"rows": None, "windowed": windowed, "error": "non-list response", "reason": "query_error"}
    if resp and isinstance(resp[0], dict) and ("n" in resp[0] or "count" in resp[0]):
        n = int(resp[0].get("n", resp[0].get("count", 0)) or 0)
        return {
            "rows": [{"email": f"legacy-{i}@legacy-count.invalid-real", "signup_at": resp[0].get("first_at")} for i in range(n)],
            "windowed": windowed,
            "legacy_count": n,
            "legacy_first_at": resp[0].get("first_at"),
        }
    return {"rows": resp, "windowed": windowed}


def select_auth_users_in_window(
    project_ref: str,
    window_days: int,
    token: str | None = None,
    gclid_column: str | None = None,
    relaunch_at: str | None = None,
) -> dict:
    gclid_select = f', "{gclid_column}" AS gclid' if gclid_column else ""
    sql = (
        f"SELECT email, created_at AS signup_at, email_confirmed_at{gclid_select} "
        "FROM auth.users "
        f"WHERE {postgres_lower_bound_expr('created_at', window_days, relaunch_at)} "
        "AND email_confirmed_at IS NOT NULL"
    )
    resp = _management_api_query(project_ref, sql, token)
    if isinstance(resp, dict) and "error" in resp:
        return {"rows": None, "windowed": True, "error": resp["error"], "reason": resp.get("reason", "query_error")}
    if not isinstance(resp, list):
        return {"rows": None, "windowed": True, "error": "non-list response", "reason": "query_error"}
    if resp and isinstance(resp[0], dict) and "confirmed" in resp[0]:
        n = int(resp[0].get("confirmed", 0) or 0)
        return {
            "rows": [{"email": f"legacy-{i}@legacy-count.invalid-real", "signup_at": resp[0].get("first_at")} for i in range(n)],
            "windowed": True,
            "legacy_count": n,
            "legacy_first_at": resp[0].get("first_at"),
        }
    return {"rows": [r for r in resp if r.get("email_confirmed_at") is not None], "windowed": True}


def _legacy_count_result(
    result: dict,
    table_name: str,
    windowed: bool = True,
    priority: int | None = None,
    gclid_column: str | None = None,
) -> dict:
    count = result.get("confirmed", result.get("count"))
    if count is None:
        return {}
    n = int(count or 0)
    return {
        "table": table_name,
        "priority": _priority_value({"priority": priority}),
        "gclid_column": gclid_column,
        "db_signups_raw": n,
        "db_signups_real": n,
        "db_signups_team": 0,
        "db_signups_test": 0,
        "db_signups_paid": None,
        "db_attribution": "window",
        "db_signups_filter_audit": [],
        "db_signups_real_windowed": windowed,
        "db_first_signup_at": result.get("first_at"),
    }


def _filtered_table_result(
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
        # Evidence-based attribution: a gclid COLUMN is only shape; the label
        # requires at least one real row with a valid POPULATED gclid. A
        # present-but-never-populated column stays "window" so verdicts fall
        # back to db_signups_real instead of trusting paid=0 as truth.
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


def _union_ground_truth(contributors: list[dict], config: dict, internal_domains=()) -> dict | None:
    """Merge windowed email-bearing candidates into one deduped union candidate.

    contributors: [{"table": str, "rows": list[dict], "priority": int | None,
    "gclid_column": str | None, "candidate": dict}] where `candidate` is the
    already-computed `_filtered_table_result` dict for that table (its audit
    entries are 1:1 with `rows`, in order — reused here so no email is
    classified twice).

    The union is keyed on `gmail_normalize(email)`: the same person appearing
    in waitlist AND auth.users counts once, and gclid evidence from ANY table
    attributes their signup. Missing-email rows can't be keyed, so they count
    per-occurrence into raw+test (preserves raw == real + team + test).

    Returns a candidate-shaped dict (same keys as `_filtered_table_result`)
    plus `db_union_tables`, or None when there are no contributors.
    """
    if not contributors:
        return None

    by_email: dict[str, dict] = {}
    missing_email_rows = 0
    for contrib in contributors:
        rows = contrib.get("rows") or []
        audit = (contrib.get("candidate") or {}).get("db_signups_filter_audit") or []
        for row, entry in zip(rows, audit):
            if not row.get("email"):
                missing_email_rows += 1
                continue
            key = gmail_normalize(str(row["email"]))
            rec = by_email.setdefault(key, {
                "category": entry.get("category"),
                "has_valid_gclid": False,
                "first_at": None,
                "tables": set(),
            })
            rec["tables"].add(contrib["table"])
            if is_real_gclid(row.get("gclid") or row.get("click_id")):
                rec["has_valid_gclid"] = True
            signup_at = row.get("signup_at")
            if signup_at and (rec["first_at"] is None or str(signup_at) < rec["first_at"]):
                rec["first_at"] = str(signup_at)

    real_keys = {k for k, r in by_email.items() if r["category"] == "real"}
    team_keys = {k for k, r in by_email.items() if r["category"] == "team"}
    test_keys = {k for k, r in by_email.items() if r["category"] == "test"}

    any_gclid_column = any(c.get("gclid_column") for c in contributors)
    paid = None
    if any_gclid_column:
        paid = sum(1 for k in real_keys if by_email[k]["has_valid_gclid"])
    attribution = "gclid_shape" if (type(paid) is int and paid > 0) else "window"

    def _real_contribution(table: str) -> int:
        return sum(1 for k in real_keys if table in by_email[k]["tables"])

    def _raw_contribution(table: str) -> int:
        return sum(1 for k in by_email if table in by_email[k]["tables"])

    priority_by_table = {c["table"]: _priority_value(c) for c in contributors}
    union_tables = sorted(
        (c["table"] for c in contributors if _real_contribution(c["table"]) > 0),
        key=lambda t: (-_real_contribution(t), priority_by_table.get(t, 999), t),
    )
    if union_tables:
        top_table = union_tables[0]
    else:
        top_table = min(
            (c["table"] for c in contributors),
            key=lambda t: (-_raw_contribution(t), priority_by_table.get(t, 999), t),
        )

    gclid_contribs = [c for c in contributors if c.get("gclid_column")]
    gclid_column = None
    if gclid_contribs:
        gclid_column = min(
            gclid_contribs,
            key=lambda c: (
                -sum(1 for k in real_keys if by_email[k]["has_valid_gclid"] and c["table"] in by_email[k]["tables"]),
                _priority_value(c),
                c["table"],
            ),
        ).get("gclid_column")

    audit_union: list[dict] = []
    for contrib in contributors:
        for entry in ((contrib.get("candidate") or {}).get("db_signups_filter_audit") or []):
            audit_union.append({**entry, "table": contrib["table"]})

    real_times = [by_email[k]["first_at"] for k in real_keys if by_email[k]["first_at"]]

    return {
        "table": top_table,
        "priority": min(_priority_value(c) for c in contributors),
        "gclid_column": gclid_column,
        "db_signups_raw": len(by_email) + missing_email_rows,
        "db_signups_real": len(real_keys),
        "db_signups_team": len(team_keys),
        "db_signups_test": len(test_keys) + missing_email_rows,
        "db_signups_paid": paid,
        "db_attribution": attribution,
        "db_signups_filter_audit": audit_union,
        "db_signups_real_windowed": True,
        "db_first_signup_at": min(real_times) if real_times else None,
        "db_union_tables": union_tables,
    }


def _empty_ground_truth(reason: str, errors: list[str] | None = None) -> dict:
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
        "db_union_tables": [],
        "db_unmapped_reason": reason,
        "errors": errors,
    }


def _dry_run_filter_result(name: str, existing: dict) -> dict | None:
    path = ".runs/_email_filter_results.json"
    if not os.path.exists(path):
        return None
    try:
        rows = json.load(open(path))
    except Exception:
        return None
    row = next((r for r in rows if r.get("mvp") == name), None)
    if not row or row.get("real") is None:
        return None
    raw = row.get("orig_total")
    return {
        "db_signups": raw,
        "db_signups_raw": raw,
        "db_signups_real": row.get("real"),
        "db_signups_paid": None,
        "db_attribution": "window",
        "db_signups_team": row.get("team", 0),
        "db_signups_test": row.get("test", 0),
        "db_signups_filter_audit": [],
        "db_signups_real_windowed": True,
        "db_signups_table": existing.get("db_signups_table"),
        "db_first_signup_at": existing.get("db_first_signup_at"),
        "db_breakdown": existing.get("db_breakdown") or {},
        "db_unmapped_reason": None,
        "errors": None,
    }


def query_mvp_ground_truth(
    project_ref: str,
    window_days: int,
    operator_override_table: str | None = None,
    token: str | None = None,
    config: dict | None = None,
    internal_domains=(),
    relaunch_at: str | None = None,
) -> dict:
    """Full ground-truth probe for one MVP.

    Returns:
      {
        "db_signups": int,                  # raw count from winning table
        "db_signups_table": str | None,     # which table won
        "db_first_signup_at": str | None,
        "db_breakdown": {table: count, ...},
        "errors": [str, ...] | None,
      }

    Winner rule: all windowed email-bearing tables (public + auth.users
    confirmed) are merged into ONE union candidate — emails gmail-normalized
    and deduplicated across tables, so the same person in waitlist AND
    auth.users counts once and gclid evidence from any table attributes them.
    `db_signups_paid` counts union real emails with a valid populated gclid
    (None when no table has a gclid column); `db_attribution` is "gclid_shape"
    only when paid > 0. The union candidate then competes against residual
    candidates (no-email legacy counts, non-windowed tables) on real count
    first, raw count second, table-name priority as tie-breaker — identical to
    the historical else-branch, so legacy-only projects are unchanged.
    Operators can still override via `mvp_mappings.<name>.db_signup_table`.
    """
    config = config or {}
    errors: list[str] = []
    error_reasons: list[str] = []
    candidates: list[dict] = []
    union_inputs: list[dict] = []
    saw_email_table = False

    # Operator override path: only query that one table.
    if operator_override_table:
        # Parse "schema.table" or default to public.
        if "." in operator_override_table:
            schema, table_only = operator_override_table.split(".", 1)
        else:
            schema, table_only = "public", operator_override_table
        if schema == "auth":
            auth_rows = select_auth_users_in_window(project_ref, window_days, token, relaunch_at=relaunch_at)
            if auth_rows.get("error"):
                return _empty_ground_truth(auth_rows.get("reason", "query_error"), [f"auth.users: {auth_rows['error']}"])
            table_name = "auth.users.confirmed" if auth_rows.get("legacy_count") is not None else "auth.users"
            row = _filtered_table_result(table_name, auth_rows["rows"], config, True, internal_domains=internal_domains)
            candidates.append(row)
            saw_email_table = True
            breakdown = {row["table"]: row["db_signups_raw"]}
            return {
                **row,
                "db_signups": row["db_signups_raw"],
                "db_signups_table": operator_override_table,
                "db_breakdown": breakdown,
                "db_unmapped_reason": None,
                "errors": None,
            }
        # public.<table>: discover its timestamp column
        discovery = _discover_signup_tables_result(project_ref, token)
        if discovery.get("error"):
            return _empty_ground_truth(
                discovery.get("reason", "query_error"),
                [f"public.{table_only}: {discovery['error']}"],
            )
        tables = discovery["tables"]
        ts_col = None
        columns: list[str] = []
        priority = None
        gclid_column = None
        for t in tables:
            if t["table"] == table_only:
                ts_col = t["timestamp_column"]
                columns = t.get("columns") or []
                priority = t.get("priority")
                gclid_column = t.get("gclid_column")
                break
        if "email" not in columns and config.get("email_filter"):
            return _empty_ground_truth("no_email_column")
        if "email" not in columns:
            legacy = count_signups_in_window(project_ref, table_only, ts_col, window_days, token, relaunch_at=relaunch_at)
            if "error" in legacy:
                return _empty_ground_truth("query_error", [f"public.{table_only}: {legacy['error']}"])
            row = _legacy_count_result(
                legacy,
                f"public.{table_only}",
                bool(legacy.get("window_filtered", True)),
                priority=priority,
                gclid_column=gclid_column,
            )
            breakdown = {row["table"]: row["db_signups_raw"]}
            return {
                **row,
                "db_signups": row["db_signups_raw"],
                "db_signups_table": operator_override_table,
                "db_breakdown": breakdown,
                "db_unmapped_reason": None,
                "errors": None,
            }
        result = select_signups_in_window(project_ref, table_only, ts_col, window_days, token, gclid_column, relaunch_at=relaunch_at)
        if "error" in result:
            return _empty_ground_truth(result.get("reason", "query_error"), [f"public.{table_only}: {result['error']}"])
        row = _filtered_table_result(
            f"public.{table_only}",
            result["rows"],
            config,
            bool(result["windowed"]),
            priority=priority,
            gclid_column=gclid_column,
            internal_domains=internal_domains,
        )
        breakdown = {row["table"]: row["db_signups_raw"]}
        return {
            **row,
            "db_signups": row["db_signups_raw"],
            "db_signups_table": operator_override_table,
            "db_breakdown": breakdown,
            "db_unmapped_reason": None,
            "errors": None,
        }

    # Auto-discovery path: probe auth.users and all candidate signup tables,
    # union the windowed email-bearing ones, then let the union compete with
    # residual (legacy/non-windowed) candidates.
    auth_rows = select_auth_users_in_window(project_ref, window_days, token, relaunch_at=relaunch_at)
    if "error" in auth_rows:
        errors.append(f"auth.users: {auth_rows['error']}")
        error_reasons.append(auth_rows.get("reason", "query_error"))
    else:
        auth_result_rows = auth_rows.get("rows") or []
        saw_email_table = True
        if auth_result_rows:
            table_name = "auth.users.confirmed" if auth_rows.get("legacy_count") is not None else "auth.users"
            auth_candidate = _filtered_table_result(
                table_name, auth_result_rows, config, True, internal_domains=internal_domains
            )
            candidates.append(auth_candidate)
            # Legacy-count responses synthesize placeholder emails
            # (legacy-N@legacy-count.invalid-real) that would collide across
            # tables — keep those candidates count-only, out of the union.
            if auth_rows.get("legacy_count") is None:
                union_inputs.append({
                    "table": table_name,
                    "rows": auth_result_rows,
                    "priority": None,
                    "gclid_column": None,
                    "candidate": auth_candidate,
                })

    tables = discover_signup_tables(project_ref, token)
    for t in _rank_signup_tables_for_probe(tables):
        columns = t.get("columns") or []
        if "email" not in columns and config.get("email_filter"):
            continue
        if "email" not in columns:
            result = count_signups_in_window(
                project_ref, t["table"], t["timestamp_column"], window_days, token,
                relaunch_at=relaunch_at,
            )
            if "error" in result:
                errors.append(f"public.{t['table']}: {result['error']}")
                continue
            row = _legacy_count_result(
                result,
                f"public.{t['table']}",
                bool(result.get("window_filtered", True)),
                priority=t.get("priority"),
                gclid_column=t.get("gclid_column"),
            )
            if row:
                candidates.append(row)
            continue
        saw_email_table = True
        result = select_signups_in_window(
            project_ref, t["table"], t["timestamp_column"], window_days, token, t.get("gclid_column"),
            relaunch_at=relaunch_at,
        )
        if "error" in result:
            errors.append(f"public.{t['table']}: {result['error']}")
            continue
        table_candidate = _filtered_table_result(
            f"public.{t['table']}",
            result["rows"],
            config,
            bool(result["windowed"]),
            priority=t.get("priority"),
            gclid_column=t.get("gclid_column"),
            internal_domains=internal_domains,
        )
        candidates.append(table_candidate)
        # Union membership: windowed, real email rows only. Non-windowed
        # tables would falsify db_signups_real_windowed=True for the whole
        # union; legacy-count synthetic rows would collide across tables.
        if result.get("legacy_count") is None and result["windowed"]:
            union_inputs.append({
                "table": f"public.{t['table']}",
                "rows": result["rows"],
                "priority": t.get("priority"),
                "gclid_column": t.get("gclid_column"),
                "candidate": table_candidate,
            })

    if not candidates:
        if errors:
            reason = "query_error"
            for candidate_reason in ("forbidden", "project_deleted"):
                if candidate_reason in error_reasons:
                    reason = candidate_reason
                    break
            return _empty_ground_truth(reason, errors)
        if tables and not saw_email_table:
            return _empty_ground_truth("no_email_column")
        return _empty_ground_truth("no_email_column", ["no email-bearing signup tables found"])

    # Cross-table union of windowed email tables vs residual candidates
    # (no-email legacy counts, non-windowed tables). Same (real, raw,
    # -priority) competition as the historical else-branch — the union
    # replaces its member tables in the pool, never demotes a residual
    # candidate that would have won before.
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
        "db_signups_table": winner["table"],
        "db_breakdown": breakdown,
        "db_union_tables": winner.get("db_union_tables") or [],
        "db_unmapped_reason": None,
        "errors": errors or None,
    }


def merge_into_context(
    context_path: str,
    config_path: str,
    token: str | None = None,
    auto_confirm: bool = False,
    dry_run: bool = False,
) -> dict:
    """Top-level orchestrator called from state-x0b.

    Returns summary dict for stdout logging.
    """
    if yaml is None:
        raise SystemExit("ERROR: PyYAML required (pip install pyyaml)")

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

    # Step 1: list Supabase projects + fuzzy-match unmapped MVPs.
    projects = list_supabase_projects(token)
    # Membership in this list proves existence (paused projects stay listed) —
    # the free half of the killed-MVP backend verification below.
    live_project_ids = {p["id"] for p in projects if p.get("id")}
    mvp_names = [
        m["name"] for m in ctx["mvps"]
        if not m.get("orphan") and m.get("lifecycle_status") != "killed"
    ]
    matches = fuzzy_match_projects(mvp_names, projects)

    # Identify which MVPs need confirmation (no existing supabase_project_ref in config).
    needs_confirm: list[dict] = []
    proposed_writes: dict[str, str] = {}  # mvp_name → project_ref to persist
    for mvp_name in mvp_names:
        existing = (mappings.get(mvp_name) or {}).get("supabase_project_ref")
        m = matches.get(mvp_name)
        if existing:
            # Rebuilt-project re-match (ShelfCurve 2026-07-24 incident): the
            # sticky config ref is absent from the live org list while an
            # EXACT-name project exists under a different id — the member
            # deleted and recreated the project, and the stale ref would
            # otherwise read as project_deleted (forcing a rule-3 NO_GO on a
            # product whose backend is alive). Propose the re-match through
            # the same operator-confirm flow as fresh matches. Guards:
            # non-empty projects list (an API hiccup must never mass-propose)
            # and exact-name matches only (contains-matches are too weak to
            # overwrite an operator-visible ref).
            if (
                projects
                and existing not in live_project_ids
                and m
                and m.get("match_type") == "exact"
                and m["id"] != existing
            ):
                needs_confirm.append({
                    "mvp": mvp_name,
                    "project_ref": m["id"],
                    "project_name": m["name"],
                    "match_type": "rebuilt-ref",
                    "old_ref": existing,
                    "alternatives": m.get("alternatives") or [],
                })
                proposed_writes[mvp_name] = m["id"]
            continue
        if not m:
            continue
        needs_confirm.append({
            "mvp": mvp_name,
            "project_ref": m["id"],
            "project_name": m["name"],
            "match_type": m["match_type"],
            "alternatives": m.get("alternatives") or [],
        })
        proposed_writes[mvp_name] = m["id"]

    if needs_confirm and not auto_confirm:
        # Print the proposed mapping for operator review. The caller (state-x0b)
        # checks `confirm_required` in the result and prompts the operator to
        # re-run with --auto-confirm after eyeballing.
        return {
            "step": "needs_confirm",
            "needs_confirm": needs_confirm,
            "auto_matched_count": len(proposed_writes),
            "unmatched": [m for m in mvp_names if matches.get(m) is None and not (mappings.get(m) or {}).get("supabase_project_ref")],
        }

    # Step 2: persist confirmed mappings into config (idempotent).
    if proposed_writes and not dry_run:
        for mvp_name, ref in proposed_writes.items():
            entry = mappings.setdefault(mvp_name, {})
            entry["supabase_project_ref"] = ref
        config["mvp_mappings"] = mappings
        with open(config_path, "w") as f:
            yaml.safe_dump(config, f, sort_keys=False, default_flow_style=False)

    # Step 3: query each MVP that has a project_ref.
    queried = 0
    unmapped = 0
    errors_total = 0
    backend_writes: dict[str, dict] = {}  # mvp_name → db_backend record to persist
    for mvp in ctx["mvps"]:
        if mvp.get("orphan"):
            # Orphan rows can't be cross-checked (no canonical project_name).
            mvp["db_signups"] = None
            mvp["db_signups_raw"] = None
            mvp["db_signups_real"] = None
            mvp["db_signups_paid"] = None
            mvp["db_attribution"] = None
            mvp["db_signups_team"] = 0
            mvp["db_signups_test"] = 0
            mvp["db_signups_filter_audit"] = []
            mvp["db_signups_real_windowed"] = None
            mvp["db_unmapped_reason"] = "orphan"
            continue
        mapping = mappings.get(mvp["name"]) or {}
        lifecycle_status = mapping.get("lifecycle_status") or mvp.get("lifecycle_status") or "active"
        mvp["lifecycle_status"] = lifecycle_status
        if mapping.get("lifecycle_status_at"):
            mvp["lifecycle_status_at"] = mapping.get("lifecycle_status_at")
        project_ref = mapping.get("supabase_project_ref")
        if lifecycle_status == "killed":
            # Policy skip, honestly labeled: "archived_killed" says "not
            # re-queried because the MVP is killed" — it does NOT claim the
            # backend is gone. The backend knowledge state (alive / deleted /
            # never existed / not visible / never located) is verified
            # near-free and recorded in the sticky db_backend config field.
            mvp.update(_empty_ground_truth("archived_killed"))
            mvp["supabase_project_ref"] = project_ref
            mvp["db_source"] = None
            backend = resolve_backend_state(
                mvp["name"], mapping, live_project_ids, token, backend_writes,
            )
            if backend:
                mvp["db_backend"] = backend
            unmapped += 1
            continue
        if not project_ref:
            mvp["db_signups"] = None
            mvp["db_signups_raw"] = None
            mvp["db_signups_real"] = None
            mvp["db_signups_paid"] = None
            mvp["db_attribution"] = None
            mvp["db_signups_team"] = 0
            mvp["db_signups_test"] = 0
            mvp["db_signups_filter_audit"] = []
            mvp["db_signups_real_windowed"] = None
            mvp["db_unmapped_reason"] = "no_match"
            mvp["supabase_project_ref"] = None
            unmapped += 1
            continue
        override_table = mapping.get("db_signup_table")
        internal_domains = internal_domains_for_mvp(config, mvp["name"])
        relaunch_at = parse_relaunch_at(mapping.get("phase1_relaunch_at"))
        gt = query_mvp_ground_truth(
            project_ref,
            window_days,
            override_table,
            token,
            config,
            internal_domains=internal_domains,
            relaunch_at=relaunch_at,
        )
        if dry_run and gt.get("db_signups_real") is None:
            gt = _dry_run_filter_result(mvp["name"], mvp) or gt
        mvp["supabase_project_ref"] = project_ref
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
        reason = gt.get("db_unmapped_reason")
        if reason == "project_deleted":
            # The SQL endpoint 404s for deleted AND never-existed refs — only
            # the tombstone endpoint can tell them apart. Confirm before the
            # reason reaches the rule-3 forced NO_GO; persist the verified
            # backend state so the evidence is durable (sticky db_backend).
            reason, backend_rec = confirm_project_deleted(
                project_ref, mapping, live_project_ids, token
            )
            if backend_rec:
                mvp["db_backend"] = backend_rec
                sticky = mapping.get("db_backend") or {}
                if (
                    backend_rec.get("status") != sticky.get("status")
                    or not sticky.get("checked_at")
                ):
                    backend_writes[mvp["name"]] = backend_rec
        mvp["db_unmapped_reason"] = reason
        # db_source stamps which backend produced this number. Symmetric with
        # the Railway pass (which sets "railway"); without stamping the
        # Supabase side too, x4 would see db_source=None everywhere except
        # Railway-sourced rows, which reads as "unknown source" rather than
        # the actual Supabase-sourced default. Only stamp on success — if the
        # query returned None, we have no source to attribute.
        if gt.get("db_signups_real") is not None or gt.get("db_signups") is not None:
            mvp["db_source"] = "supabase"
        if gt.get("errors"):
            errors_total += len(gt["errors"])
            mvp["db_errors"] = gt["errors"]
        queried += 1

    for mvp in ctx["mvps"]:
        mvp.setdefault("db_unmapped_reason", None)
        mvp.setdefault("db_signups_raw", mvp.get("db_signups"))
        mvp.setdefault("db_signups_real", mvp.get("db_signups"))
        mvp.setdefault("db_signups_paid", None)
        mvp.setdefault("db_attribution", "window" if mvp.get("db_signups_real") is not None else None)
        mvp.setdefault("db_signups_team", 0)
        mvp.setdefault("db_signups_test", 0)
        mvp.setdefault("db_signups_filter_audit", [])
        mvp.setdefault("db_signups_real_windowed", True if mvp.get("db_signups_real") is not None else None)
        mvp.setdefault("db_first_signup_at", None)
        mvp.setdefault("db_union_tables", [])
        mvp.setdefault("lifecycle_status", "active")

    # Persist verified db_backend records (independent of the proposed_writes
    # gate above — killed rows never enter that batch).
    if not dry_run:
        write_backend_records(config_path, config, backend_writes)

    # Write back context (preserve base + extra fields).
    if not dry_run:
        with open(context_path, "w") as f:
            json.dump(ctx, f, indent=2)

    return {
        "step": "merged",
        "queried": queried,
        "unmapped": unmapped,
        "errors": errors_total,
        "backend_verified": len(backend_writes),
    }


def verify_backends(
    config_path: str,
    token: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Config-driven backend verification over ALL killed mvp_mappings rows.

    Drives from config (NOT run context) so killed MVPs with zero traffic in
    the discovery window — which never enter a cross run's mvps list — are
    covered too. Same engine as the merge path (resolve_backend_state); used
    for the one-time rollout backfill and reusable by the x4b reconcile state.
    """
    if yaml is None:
        raise SystemExit("ERROR: PyYAML required (pip install pyyaml)")
    config = yaml.safe_load(open(config_path)) if os.path.exists(config_path) else {}
    config = config or {}
    mappings = config.get("mvp_mappings") or {}

    live_project_ids = {p["id"] for p in list_supabase_projects(token) if p.get("id")}
    backend_writes: dict[str, dict] = {}
    rows = []
    for name, mapping in sorted(mappings.items()):
        if not isinstance(mapping, dict) or name.startswith("__orphan"):
            continue
        if mapping.get("lifecycle_status") != "killed":
            continue
        record = resolve_backend_state(
            name, mapping, live_project_ids, token, backend_writes,
        )
        rows.append({
            "mvp": name,
            "supabase_project_ref": mapping.get("supabase_project_ref"),
            "status": (record or {}).get("status"),
            "evidence": (record or {}).get("evidence"),
        })

    if not dry_run:
        write_backend_records(config_path, config, backend_writes)

    by_status: dict[str, int] = {}
    for r in rows:
        key = r["status"] or "unresolved"
        by_status[key] = by_status.get(key, 0) + 1
    return {
        "killed_rows": len(rows),
        "written": 0 if dry_run else len(backend_writes),
        "would_write": len(backend_writes) if dry_run else 0,
        "by_status": by_status,
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list-projects")
    p_list.add_argument("--token", default=None)

    p_match = sub.add_parser("fuzzy-match")
    p_match.add_argument("--context", required=True)

    p_disc = sub.add_parser("discover-tables")
    p_disc.add_argument("--ref", required=True)

    p_q = sub.add_parser("query-signups")
    p_q.add_argument("--ref", required=True)
    p_q.add_argument("--window-days", type=int, default=90)
    p_q.add_argument("--table", default=None, help="operator override")

    p_merge = sub.add_parser("merge")
    p_merge.add_argument("--context", required=True)
    p_merge.add_argument("--config", required=True)
    p_merge.add_argument("--run-dir", default=".runs")
    p_merge.add_argument("--auto-confirm", action="store_true")
    p_merge.add_argument("--dry-run", action="store_true")

    p_vb = sub.add_parser(
        "verify-backends",
        help="verify killed MVPs' Supabase backend state (tombstone probe) and persist sticky db_backend records",
    )
    p_vb.add_argument("--config", default="experiment/iterate-cross-config.yaml")
    p_vb.add_argument("--token", default=None)
    p_vb.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)

    if args.cmd == "list-projects":
        for p in list_supabase_projects(args.token):
            print(f"{p['id']}\t{p['name']}\t{p['region']}")
        return 0

    if args.cmd == "fuzzy-match":
        ctx = json.load(open(args.context))
        names = [m["name"] for m in ctx["mvps"] if not m.get("orphan")]
        projects = list_supabase_projects()
        results = fuzzy_match_projects(names, projects)
        for name, m in results.items():
            if m:
                print(f"{name}\t{m['id']}\t{m['name']}\t{m['match_type']}")
            else:
                print(f"{name}\tNO_MATCH")
        return 0

    if args.cmd == "discover-tables":
        tables = discover_signup_tables(args.ref)
        for t in tables:
            print(f"{t['table']}\t{t['timestamp_column'] or '(no_ts)'}\tpriority={t['priority']}")
        return 0

    if args.cmd == "query-signups":
        result = query_mvp_ground_truth(args.ref, args.window_days, args.table)
        print(json.dumps(result, indent=2))
        return 0

    if args.cmd == "merge":
        result = merge_into_context(
            args.context,
            args.config,
            auto_confirm=args.auto_confirm,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, indent=2))
        return 0 if result.get("step") == "merged" else 2  # exit 2 = needs_confirm

    if args.cmd == "verify-backends":
        result = verify_backends(args.config, token=args.token, dry_run=args.dry_run)
        for r in result["rows"]:
            print(f"{r['mvp']:24s} {r['status'] or 'unresolved':16s} {r['evidence'] or ''}")
        print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
