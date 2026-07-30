#!/usr/bin/env python3
"""Tests for .claude/scripts/lib/iterate_cross_phase2_db.py."""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import iterate_cross_phase2_db as db  # noqa: E402


REAL_GCLID = "Cj" + ("a" * 45)
REAL_GCLID_2 = "EAI" + ("b" * 45)


def test_fetch_pay_intent_rows_assembles_sql_with_probe_and_filters(monkeypatch):
    calls = []

    def fake_query(project_ref, sql, token):
        calls.append((project_ref, sql, token))
        if "to_regclass" in sql:
            return [{"regclass": "pay_intent"}]
        return [{"user_id": "u1", "distinct_id": "d1", "email": "a@example.org"}]

    monkeypatch.setattr(db, "_management_api_query", fake_query)
    rows, reason = db.fetch_pay_intent_rows("project-ref", 14, "%phase2%' OR true --", "token")

    assert reason is None
    assert rows == [{"user_id": "u1", "distinct_id": "d1", "email": "a@example.org"}]
    assert len(calls) == 2
    assert "SELECT to_regclass('public.pay_intent')" in calls[0][1]
    sql = calls[1][1]
    assert "LEFT JOIN auth.users u ON u.id = p.user_id" in sql
    assert "p.utm_campaign ILIKE '%phase2%'' OR true --'" in sql
    assert "p.created_at >= now() - INTERVAL '14 days'" in sql
    assert f"p.utm_campaign != '{db.PROBE_UTM}'" in sql
    assert "p.price_cents::float8" in sql


def test_fetch_pay_intent_rows_returns_no_table_after_probe(monkeypatch):
    calls = []

    def fake_query(project_ref, sql, token):
        calls.append(sql)
        return [{"regclass": None}]

    monkeypatch.setattr(db, "_management_api_query", fake_query)
    rows, reason = db.fetch_pay_intent_rows("project-ref", 90, "%phase2%", "token")

    assert rows is None
    assert reason == "no_table"
    assert len(calls) == 1


def test_fetch_pay_intent_rows_maps_management_errors(monkeypatch):
    for reason in ["forbidden", "project_deleted", "query_error", "unknown"]:
        responses = iter([
            [{"regclass": "pay_intent"}],
            {"error": "boom", "reason": reason},
        ])
        monkeypatch.setattr(db, "_management_api_query", lambda *_args: next(responses))
        rows, mapped = db.fetch_pay_intent_rows("project-ref", 90, "%phase2%", "token")
        assert rows is None
        assert mapped == (reason if reason in db.ERROR_REASONS else "query_error")


def test_summarize_pay_intents_dedupes_then_filters_and_splits_paid():
    config = {
        "email_filter": {
            "rules": {
                "team_domains": ["draftlabs.org"],
            }
        }
    }
    rows = [
        {
            "user_id": "u1",
            "distinct_id": "d1",
            "email": "buyer@acmeco.io",
            "gclid": "fake",
            "price_cents": 1000,
            "created_at": "2026-06-01T00:00:00Z",
        },
        {
            "user_id": "u1",
            "distinct_id": "d1-later",
            "email": "buyer@acmeco.io",
            "gclid": REAL_GCLID,
            "price_cents": "2000",
            "created_at": "2026-06-02T00:00:00Z",
        },
        {
            "user_id": None,
            "distinct_id": "d2",
            "email": "organic@customer.io",
            "gclid": None,
            "price_cents": 3000,
            "created_at": "2026-06-03T00:00:00Z",
        },
        {
            "user_id": "u3",
            "distinct_id": "d3",
            "email": "founder@draftlabs.org",
            "gclid": REAL_GCLID_2,
            "price_cents": 4000,
            "created_at": "2026-06-04T00:00:00Z",
        },
        {
            "user_id": "u4",
            "distinct_id": "d4",
            "email": None,
            "gclid": REAL_GCLID_2,
            "price_cents": 5000,
            "created_at": "2026-06-05T00:00:00Z",
        },
    ]

    summary = db.summarize_pay_intents(rows, config)

    assert summary["db_pay_intents_raw"] == 4
    assert summary["db_pay_intents_real"] == 2
    assert summary["db_pay_intents_paid"] == 1
    assert summary["db_pay_intents_unattributed"] == 1
    assert summary["db_pay_intents_team"] == 1
    assert summary["db_pay_intents_test"] == 1
    assert summary["db_pay_intent_price_cents_max"] == 2000.0
    assert summary["db_pay_intent_price_variants"] == 1
    assert any(a["reason"] == "missing-email" for a in summary["db_pay_intents_filter_audit"])


def _write_json(path, data):
    path.write_text(json.dumps(data))


def test_merge_no_token_is_non_halting_and_writes_triage(tmp_path, monkeypatch):
    context = tmp_path / "context.json"
    config = tmp_path / "config.yaml"
    triage = tmp_path / "triage.json"
    _write_json(
        context,
        {
            "phase2_run_token": "run-1",
            "window_days": 30,
            "phase2_utm_campaign_like": "%phase2%",
            "mvps": [
                {"name": "alpha", "pay_intents": 2},
                {"name": "beta", "pay_intents": 0, "orphan": True},
            ],
        },
    )
    config.write_text("mvp_mappings:\n  alpha:\n    supabase_project_ref: alpha-ref\n")
    monkeypatch.setattr(db, "TOKEN_PATH", tmp_path / "missing-token")

    result = db.merge_context(str(context), str(config), str(triage))

    assert result["step"] == "merged"
    assert result["run_token"] == "run-1"
    merged = json.loads(context.read_text())
    assert merged["phase2_db_merge"]["run_token"] == "run-1"
    assert merged["phase2_db_merge"]["mvps_no_token"] == 2
    for mvp in merged["mvps"]:
        assert mvp["db_pay_intents_unmapped_reason"] == "no_token"
        assert mvp["db_pay_intents_paid"] is None
        assert (mvp["db_pay_intents_paid"] is None) == (mvp["db_pay_intents_unmapped_reason"] is not None)
        assert "db_pay_intent_source" not in mvp
    triage_payload = json.loads(triage.read_text())
    assert triage_payload["run_token"] == "run-1"
    assert [row["name"] for row in triage_payload["mvps"]] == ["alpha", "beta"]


def test_merge_stamps_success_failures_defaults_and_triage(tmp_path, monkeypatch):
    context = tmp_path / "context.json"
    config = tmp_path / "config.yaml"
    triage = tmp_path / "triage.json"
    _write_json(
        context,
        {
            "phase2_run_token": "run-2",
            "window_days": 7,
            "phase2_utm_campaign_like": "%Phase2%",
            "mvps": [
                {"name": "alpha", "pay_intents": 1},
                {"name": "beta", "pay_intents": 2},
                {"name": "gamma", "pay_intents": 3},
                {"name": "__orphan_site__", "pay_intents": 4, "orphan": True},
            ],
        },
    )
    config.write_text(
        "\n".join([
            "mvp_mappings:",
            "  alpha:",
            "    supabase_project_ref: alpha-ref",
            "  beta:",
            "    supabase_project_ref: beta-ref",
            "email_filter:",
            "  rules:",
            "    team_domains: []",
            "",
        ])
    )

    def fake_query(project_ref, sql, token):
        if "to_regclass" in sql and project_ref == "alpha-ref":
            return [{"regclass": "pay_intent"}]
        if project_ref == "alpha-ref":
            return [
                {
                    "user_id": "u1",
                    "distinct_id": "d1",
                    "email": "buyer@acmeco.io",
                    "gclid": REAL_GCLID,
                    "price_cents": 1200,
                    "created_at": "2026-06-01T00:00:00Z",
                }
            ]
        if "to_regclass" in sql and project_ref == "beta-ref":
            return [{"regclass": None}]
        raise AssertionError(f"unexpected query: {project_ref} {sql}")

    monkeypatch.setattr(db, "_management_api_query", fake_query)

    result = db.merge_context(str(context), str(config), str(triage), token="token")

    assert result["mvps_queried"] == 2
    assert result["mvps_no_table"] == 1
    merged = json.loads(context.read_text())
    by_name = {m["name"]: m for m in merged["mvps"]}
    assert by_name["alpha"]["db_pay_intent_source"] == "supabase"
    assert by_name["alpha"]["db_pay_intents_paid"] == 1
    assert by_name["alpha"]["db_pay_intents_real_windowed"] is True
    assert by_name["alpha"]["db_pay_intents_unmapped_reason"] is None
    assert by_name["alpha"]["db_pay_intent_price_cents_max"] == 1200.0
    assert by_name["beta"]["db_pay_intents_unmapped_reason"] == "no_table"
    assert by_name["gamma"]["db_pay_intents_unmapped_reason"] == "no_match"
    assert by_name["__orphan_site__"]["db_pay_intents_unmapped_reason"] == "orphan"
    for mvp in merged["mvps"]:
        assert (mvp["db_pay_intents_paid"] is None) == (mvp["db_pay_intents_unmapped_reason"] is not None)

    triage_payload = json.loads(triage.read_text())
    assert triage_payload["run_token"] == "run-2"
    assert {row["name"] for row in triage_payload["mvps"]} == set(by_name)
    assert {row["reason"] for row in triage_payload["mvps"]} == {None, "no_table", "no_match", "orphan"}


def test_product_domain_filter_threads_through_phase2_merge(tmp_path, monkeypatch):
    context = tmp_path / "context.json"
    config = tmp_path / "config.yaml"
    triage = tmp_path / "triage.json"
    _write_json(
        context,
        {
            "phase2_run_token": "run-product-domain",
            "window_days": 7,
            "phase2_utm_campaign_like": "%Phase2%",
            "mvps": [{"name": "alpha", "pay_intents": 2}],
        },
    )
    config.write_text(
        "\n".join([
            "mvp_mappings:",
            "  alpha:",
            "    supabase_project_ref: alpha-ref",
            "    deploy_domain: alpha.dev",
            "email_filter:",
            "  rules: {}",
            "",
        ])
    )

    def fake_query(project_ref, sql, token):
        if "to_regclass" in sql:
            return [{"regclass": "pay_intent"}]
        assert project_ref == "alpha-ref"
        return [
            {
                "user_id": "u1",
                "distinct_id": "d1",
                "email": "founder@alpha.dev",
                "gclid": REAL_GCLID,
                "price_cents": 1200,
                "created_at": "2026-06-01T00:00:00Z",
            },
            {
                "user_id": "u2",
                "distinct_id": "d2",
                "email": "buyer@customer.io",
                "gclid": REAL_GCLID_2,
                "price_cents": 1400,
                "created_at": "2026-06-02T00:00:00Z",
            },
        ]

    monkeypatch.setattr(db, "_management_api_query", fake_query)

    result = db.merge_context(str(context), str(config), str(triage), token="token")
    merged = json.loads(context.read_text())["mvps"][0]

    assert result["mvps_queried"] == 1
    assert merged["db_pay_intents_raw"] == 2
    assert merged["db_pay_intents_real"] == 1
    assert merged["db_pay_intents_paid"] == 1
    assert merged["db_pay_intents_test"] == 1
    assert any(
        row.get("reason") == "product-own-domain"
        for row in merged["db_pay_intents_filter_audit"]
    )


# ---------- B1 wiring liveness + B5 gclid-no-utm diagnostics ----------

def _diag_setup(tmp_path):
    context = tmp_path / "context.json"
    config = tmp_path / "config.yaml"
    triage = tmp_path / "triage.json"
    _write_json(
        context,
        {
            "phase2_run_token": "run-diag",
            "window_days": 30,
            "phase2_utm_campaign_like": "%phase2%",
            "mvps": [{"name": "alpha", "pay_intents": 0}],
        },
    )
    config.write_text(
        "mvp_mappings:\n  alpha:\n    supabase_project_ref: alpha-ref\n"
    )
    return context, config, triage


def test_merge_stamps_db_last_pay_intent_at_unfiltered_including_probe(tmp_path, monkeypatch):
    context, config, triage = _diag_setup(tmp_path)
    diag_sqls = []

    def fake_query(project_ref, sql, token):
        if "to_regclass" in sql:
            return [{"regclass": "pay_intent"}]
        if "max(created_at)" in sql:
            diag_sqls.append(sql)
            return [{"last_at": "2026-06-12 00:25:03.739932+00"}]
        if "utm_campaign IS NULL" in sql:
            return []
        return []  # windowed phase fetch: no rows

    monkeypatch.setattr(db, "_management_api_query", fake_query)
    db.merge_context(str(context), str(config), str(triage), token="token")

    merged = json.loads(context.read_text())
    alpha = merged["mvps"][0]
    # "+00" normalized to "+00:00" so python3.9 fromisoformat can parse it
    assert alpha["db_last_pay_intent_at"] == "2026-06-12 00:25:03.739932+00:00"
    # liveness SQL is deliberately unfiltered: no utm/probe/window clauses
    assert len(diag_sqls) == 1
    assert "utm_campaign" not in diag_sqls[0]
    assert "dayzero" not in diag_sqls[0]
    assert "INTERVAL" not in diag_sqls[0]


def test_merge_counts_gclid_no_utm_python_side_with_is_real_gclid(tmp_path, monkeypatch):
    context, config, triage = _diag_setup(tmp_path)

    def fake_query(project_ref, sql, token):
        if "to_regclass" in sql:
            return [{"regclass": "pay_intent"}]
        if "max(created_at)" in sql:
            return [{"last_at": None}]
        if "utm_campaign IS NULL" in sql:
            return [
                {"gclid": REAL_GCLID},              # counts
                {"gclid": "analytics-verify-123"},  # placeholder shape -> excluded
                {"gclid": ""},                      # empty -> excluded
                {"gclid": None},                    # null -> excluded
            ]
        return []

    monkeypatch.setattr(db, "_management_api_query", fake_query)
    db.merge_context(str(context), str(config), str(triage), token="token")

    merged = json.loads(context.read_text())
    alpha = merged["mvps"][0]
    assert alpha["db_gclid_no_utm_count"] == 1
    assert alpha["db_last_pay_intent_at"] is None  # empty table -> not checkable

    triage_payload = json.loads(triage.read_text())
    assert triage_payload["mvps"][0]["db_gclid_no_utm"] == 1


def test_merge_failure_paths_stamp_diag_fields_none(tmp_path, monkeypatch):
    context = tmp_path / "context.json"
    config = tmp_path / "config.yaml"
    triage = tmp_path / "triage.json"
    _write_json(
        context,
        {
            "phase2_run_token": "run-diag-fail",
            "window_days": 30,
            "phase2_utm_campaign_like": "%phase2%",
            "mvps": [
                {"name": "alpha", "pay_intents": 0},          # no_match
                {"name": "beta", "pay_intents": 0},           # no_table
                {"name": "__orphan_x__", "orphan": True},     # orphan
            ],
        },
    )
    config.write_text("mvp_mappings:\n  beta:\n    supabase_project_ref: beta-ref\n")

    def fake_query(project_ref, sql, token):
        if "to_regclass" in sql:
            return [{"regclass": None}]
        raise AssertionError(f"unexpected query: {sql}")

    monkeypatch.setattr(db, "_management_api_query", fake_query)
    db.merge_context(str(context), str(config), str(triage), token="token")

    merged = json.loads(context.read_text())
    for mvp in merged["mvps"]:
        assert mvp["db_last_pay_intent_at"] is None
        assert mvp["db_gclid_no_utm_count"] is None
        assert (mvp["db_pay_intents_paid"] is None) == (
            mvp["db_pay_intents_unmapped_reason"] is not None
        )


def test_diag_query_exception_is_non_fatal(tmp_path, monkeypatch):
    context, config, triage = _diag_setup(tmp_path)

    def fake_query(project_ref, sql, token):
        if "to_regclass" in sql:
            return [{"regclass": "pay_intent"}]
        if "max(created_at)" in sql or "utm_campaign IS NULL" in sql:
            raise RuntimeError("diag transport blew up")
        return []

    monkeypatch.setattr(db, "_management_api_query", fake_query)
    result = db.merge_context(str(context), str(config), str(triage), token="token")

    assert result["mvps_queried"] == 1
    assert result["mvps_errored"] == 0  # diag failures never count as errors
    merged = json.loads(context.read_text())
    alpha = merged["mvps"][0]
    assert alpha["db_pay_intents_unmapped_reason"] is None  # main fetch succeeded
    assert alpha["db_last_pay_intent_at"] is None
    assert alpha["db_gclid_no_utm_count"] is None


def test_merge_context_after_orphan_merge_keeps_triage_set_and_xor_invariant(tmp_path, monkeypatch):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
    from iterate_cross_classify import apply_orphan_merge_to_mvps

    mvps = [
        {"name": "neuralpost", "pay_intents": 0, "gclid_visitors": 63,
         "sample_utm_campaign": "u", "first_seen": "a", "last_seen": "b"},
        {"name": "__orphan_neuralpost__", "orphan": True, "gclid_visitors": 16},
        {"name": "__orphan_unknown__", "orphan": True, "gclid_visitors": 2},
    ]
    overlap = {
        "neuralpost": {
            "orphan_host": "neuralpost",
            "canonical_gclids": 63,
            "orphan_gclids": 16,
            "overlap": 15,
        }
    }
    merged_mvps, _ = apply_orphan_merge_to_mvps(mvps, overlap, threshold=0.70)

    context = tmp_path / "context.json"
    config = tmp_path / "config.yaml"
    triage = tmp_path / "triage.json"
    _write_json(
        context,
        {
            "phase2_run_token": "run-invariant",
            "window_days": 30,
            "phase2_utm_campaign_like": "%phase2%",
            "mvps": merged_mvps,
        },
    )
    config.write_text("mvp_mappings:\n  neuralpost:\n    supabase_project_ref: n-ref\n")

    def fake_query(project_ref, sql, token):
        if "to_regclass" in sql:
            return [{"regclass": "pay_intent"}]
        if "max(created_at)" in sql:
            return [{"last_at": "2026-06-15 03:29:57+00"}]
        if "utm_campaign IS NULL" in sql:
            return []
        return []

    monkeypatch.setattr(db, "_management_api_query", fake_query)
    db.merge_context(str(context), str(config), str(triage), token="token")

    merged = json.loads(context.read_text())
    triage_payload = json.loads(triage.read_text())
    # the exact registry-VERIFY invariants, at unit level:
    ctx_names = {m["name"] for m in merged["mvps"]}
    triage_names = {row["name"] for row in triage_payload["mvps"]}
    assert triage_names == ctx_names == {"neuralpost", "__orphan_unknown__"}
    for mvp in merged["mvps"]:
        assert (mvp["db_pay_intents_paid"] is None) == (
            mvp["db_pay_intents_unmapped_reason"] is not None
        )
    neural = next(m for m in merged["mvps"] if m["name"] == "neuralpost")
    assert neural["partial_tracking_pct"] == 0.0625
    assert neural["db_last_pay_intent_at"] == "2026-06-15 03:29:57+00:00"


# ---------- Railway backend (per-MVP fallback, strict precedence) ----------

PAY_INTENT_COLS = "user_id,distinct_id,gclid,price_cents,created_at,utm_campaign"
PAY_INTENT_COLS_WITH_EMAIL = "user_id,distinct_id,email,gclid,price_cents,created_at,utm_campaign"


def _railway_env_ok(monkeypatch):
    monkeypatch.setattr(db, "_check_railway_auth", lambda: None)
    monkeypatch.setattr(db, "_check_psql_available", lambda: None)


def test_fetch_pay_intent_rows_railway_joins_users_email_and_parses_rows(monkeypatch):
    captured = []

    def fake_psql(db_url, sql, timeout=30):
        captured.append(sql)
        if "information_schema.columns" in sql:
            return {"rows": [
                ["pay_intent", PAY_INTENT_COLS],
                ["users", "id,email,created_at"],
            ], "error": None}
        return {"rows": [
            ["u1", "d1", "buyer@acmeco.io", REAL_GCLID, "9900", "2026-06-01 00:00:00+00"],
            ["u2", "", "", "", "", ""],
        ], "error": None}

    monkeypatch.setattr(db, "_psql_query", fake_psql)
    rows, reason = db.fetch_pay_intent_rows_railway("postgresql://fake", 30, "%phase2%")
    assert reason is None
    data_sql = captured[1]
    assert "LEFT JOIN public.users u ON u.id::text = p.user_id::text" in data_sql
    assert "ILIKE '%phase2%'" in data_sql
    assert "!= 'dayzero-probe'" in data_sql
    assert "INTERVAL '30 days'" in data_sql
    assert rows[0] == {
        "user_id": "u1",
        "distinct_id": "d1",
        "email": "buyer@acmeco.io",
        "gclid": REAL_GCLID,
        "price_cents": "9900",
        "created_at": "2026-06-01 00:00:00+00",
    }
    # psql renders NULL as empty string; the parser must map "" -> None.
    assert rows[1]["email"] is None
    assert rows[1]["gclid"] is None


def test_fetch_pay_intent_rows_railway_no_table_and_no_email_column(monkeypatch):
    monkeypatch.setattr(
        db, "_psql_query",
        lambda *a, **k: {"rows": [["users", "id,email"]], "error": None},
    )
    rows, reason = db.fetch_pay_intent_rows_railway("postgresql://fake", 30, "%phase2%")
    assert rows is None and reason == "no_table"

    # pay_intent present but no email source anywhere: MUST fail, never return
    # email-less rows — the email filter would classify them all as test and
    # produce a trusted zero that beats the PostHog fallback.
    monkeypatch.setattr(
        db, "_psql_query",
        lambda *a, **k: {"rows": [["pay_intent", PAY_INTENT_COLS]], "error": None},
    )
    rows, reason = db.fetch_pay_intent_rows_railway("postgresql://fake", 30, "%phase2%")
    assert rows is None and reason == "no_email_column"


def _railway_scripted_psql(monkeypatch, data_rows):
    def fake_psql(db_url, sql, timeout=30):
        if "information_schema.columns" in sql:
            return {"rows": [["pay_intent", PAY_INTENT_COLS_WITH_EMAIL]], "error": None}
        if "max(created_at)" in sql:
            return {"rows": [["2026-06-15 03:29:57+00"]], "error": None}
        if "utm_campaign IS NULL" in sql:
            return {"rows": [[REAL_GCLID], [""]], "error": None}
        return {"rows": data_rows, "error": None}

    monkeypatch.setattr(db, "_psql_query", fake_psql)


def test_merge_railway_only_mvp_stamps_source_railway(tmp_path, monkeypatch):
    context = tmp_path / "context.json"
    config = tmp_path / "config.yaml"
    triage = tmp_path / "triage.json"
    _write_json(
        context,
        {
            "phase2_run_token": "run-rw",
            "window_days": 30,
            "phase2_utm_campaign_like": "%phase2%",
            "mvps": [{"name": "alpha", "pay_intents": 1}],
        },
    )
    config.write_text(
        "mvp_mappings:\n  alpha:\n    railway_project_id: proj-1\n"
        "email_filter:\n  rules:\n    team_domains: []\n"
    )
    _railway_env_ok(monkeypatch)
    monkeypatch.setattr(
        db, "get_database_url",
        lambda project_id, service_name, environment="production": {
            "url": "postgresql://fake", "error": None,
        },
    )
    _railway_scripted_psql(monkeypatch, [
        ["u1", "d1", "buyer@acmeco.io", REAL_GCLID, "9900", "2026-06-01 00:00:00+00"],
    ])
    monkeypatch.setattr(
        db, "_management_api_query",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("supabase path must not run")),
    )

    result = db.merge_context(str(context), str(config), str(triage), token="token")

    assert result["mvps_railway_queried"] == 1
    merged = json.loads(context.read_text())
    alpha = merged["mvps"][0]
    assert alpha["db_pay_intent_source"] == "railway"
    assert alpha["db_pay_intents_paid"] == 1
    assert alpha["db_pay_intent_price_cents_max"] == 9900.0
    assert alpha["db_pay_intents_unmapped_reason"] is None
    assert alpha["railway_project_id"] == "proj-1"
    assert alpha["db_last_pay_intent_at"] == "2026-06-15 03:29:57+00:00"
    assert alpha["db_gclid_no_utm_count"] == 1
    for mvp in merged["mvps"]:
        assert (mvp["db_pay_intents_paid"] is None) == (
            mvp["db_pay_intents_unmapped_reason"] is not None
        )
    triage_payload = json.loads(triage.read_text())
    assert triage_payload["run_token"] == "run-rw"
    assert {row["name"] for row in triage_payload["mvps"]} == {"alpha"}


def test_merge_railway_fallback_when_supabase_no_token(tmp_path, monkeypatch):
    context = tmp_path / "context.json"
    config = tmp_path / "config.yaml"
    triage = tmp_path / "triage.json"
    _write_json(
        context,
        {
            "phase2_run_token": "run-fb",
            "window_days": 30,
            "phase2_utm_campaign_like": "%phase2%",
            "mvps": [
                {"name": "alpha", "pay_intents": 1},
                {"name": "beta", "pay_intents": 0},
            ],
        },
    )
    config.write_text(
        "\n".join([
            "mvp_mappings:",
            "  alpha:",
            "    supabase_project_ref: alpha-ref",
            "    railway_project_id: proj-1",
            "  beta:",
            "    supabase_project_ref: beta-ref",
            "email_filter:",
            "  rules:",
            "    team_domains: []",
            "",
        ])
    )
    monkeypatch.setattr(db, "TOKEN_PATH", tmp_path / "missing-token")
    _railway_env_ok(monkeypatch)
    monkeypatch.setattr(
        db, "get_database_url",
        lambda project_id, service_name, environment="production": {
            "url": "postgresql://fake", "error": None,
        },
    )
    _railway_scripted_psql(monkeypatch, [
        ["u1", "d1", "buyer@acmeco.io", REAL_GCLID, "9900", "2026-06-01 00:00:00+00"],
    ])
    monkeypatch.setattr(
        db, "_management_api_query",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no token — supabase must not be queried")),
    )

    result = db.merge_context(str(context), str(config), str(triage))

    merged = json.loads(context.read_text())
    by_name = {m["name"]: m for m in merged["mvps"]}
    assert by_name["alpha"]["db_pay_intent_source"] == "railway"
    assert by_name["alpha"]["db_pay_intents_paid"] == 1
    assert by_name["beta"]["db_pay_intents_unmapped_reason"] == "no_token"
    assert result["mvps_no_token"] == 1
    assert result["mvps_railway_queried"] == 1
    for mvp in merged["mvps"]:
        assert (mvp["db_pay_intents_paid"] is None) == (
            mvp["db_pay_intents_unmapped_reason"] is not None
        )


def test_merge_supabase_wins_when_both_mapped(tmp_path, monkeypatch):
    context = tmp_path / "context.json"
    config = tmp_path / "config.yaml"
    triage = tmp_path / "triage.json"
    _write_json(
        context,
        {
            "phase2_run_token": "run-pref",
            "window_days": 30,
            "phase2_utm_campaign_like": "%phase2%",
            "mvps": [{"name": "alpha", "pay_intents": 1}],
        },
    )
    config.write_text(
        "mvp_mappings:\n  alpha:\n    supabase_project_ref: alpha-ref\n"
        "    railway_project_id: proj-1\n"
        "email_filter:\n  rules:\n    team_domains: []\n"
    )

    def fake_query(project_ref, sql, token):
        if "to_regclass" in sql:
            return [{"regclass": "pay_intent"}]
        if "max(created_at)" in sql or "utm_campaign IS NULL" in sql:
            return []
        return [{
            "user_id": "u1",
            "distinct_id": "d1",
            "email": "buyer@acmeco.io",
            "gclid": REAL_GCLID,
            "price_cents": 1200,
            "created_at": "2026-06-01T00:00:00Z",
        }]

    monkeypatch.setattr(db, "_management_api_query", fake_query)
    monkeypatch.setattr(
        db, "get_database_url",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("railway must not be touched")),
    )

    result = db.merge_context(str(context), str(config), str(triage), token="token")

    assert result["mvps_railway_queried"] == 0
    merged = json.loads(context.read_text())
    assert merged["mvps"][0]["db_pay_intent_source"] == "supabase"
    assert merged["mvps"][0]["db_pay_intents_paid"] == 1


def test_merge_railway_auth_missing_is_non_halting(tmp_path, monkeypatch):
    context = tmp_path / "context.json"
    config = tmp_path / "config.yaml"
    triage = tmp_path / "triage.json"
    _write_json(
        context,
        {
            "phase2_run_token": "run-auth",
            "window_days": 30,
            "phase2_utm_campaign_like": "%phase2%",
            "mvps": [{"name": "alpha", "pay_intents": 1}],
        },
    )
    config.write_text("mvp_mappings:\n  alpha:\n    railway_project_id: proj-1\n")
    monkeypatch.setattr(db, "_check_railway_auth", lambda: "not logged in")
    monkeypatch.setattr(
        db, "get_database_url",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("env gate must run first")),
    )

    result = db.merge_context(str(context), str(config), str(triage), token="token")

    assert result["mvps_railway_unavailable"] == 1
    merged = json.loads(context.read_text())
    alpha = merged["mvps"][0]
    assert alpha["db_pay_intents_unmapped_reason"] == "railway_auth_missing"
    assert (alpha["db_pay_intents_paid"] is None) == (
        alpha["db_pay_intents_unmapped_reason"] is not None
    )


def test_merge_railway_query_failure_degrades_not_crashes(tmp_path, monkeypatch):
    import subprocess

    context = tmp_path / "context.json"
    config = tmp_path / "config.yaml"
    triage = tmp_path / "triage.json"
    _write_json(
        context,
        {
            "phase2_run_token": "run-err",
            "window_days": 30,
            "phase2_utm_campaign_like": "%phase2%",
            "mvps": [
                {"name": "alpha", "pay_intents": 1},
                {"name": "beta", "pay_intents": 0},
            ],
        },
    )
    config.write_text(
        "mvp_mappings:\n"
        "  alpha:\n    railway_project_id: proj-timeout\n"
        "  beta:\n    railway_project_id: proj-no-url\n"
    )
    _railway_env_ok(monkeypatch)

    def fake_url(project_id, service_name, environment="production"):
        if project_id == "proj-timeout":
            raise subprocess.TimeoutExpired(cmd="railway link", timeout=30)
        return {"url": None, "error": "link failed"}

    monkeypatch.setattr(db, "get_database_url", fake_url)

    result = db.merge_context(str(context), str(config), str(triage), token="token")

    assert result["mvps_railway_queried"] == 0
    merged = json.loads(context.read_text())
    by_name = {m["name"]: m for m in merged["mvps"]}
    assert by_name["alpha"]["db_pay_intents_unmapped_reason"] == "query_error"
    assert by_name["beta"]["db_pay_intents_unmapped_reason"] == "railway_service_missing"
    for mvp in merged["mvps"]:
        assert (mvp["db_pay_intents_paid"] is None) == (
            mvp["db_pay_intents_unmapped_reason"] is not None
        )


def test_merge_railway_stamps_diag_fields_non_fatally(tmp_path, monkeypatch):
    context = tmp_path / "context.json"
    config = tmp_path / "config.yaml"
    triage = tmp_path / "triage.json"
    _write_json(
        context,
        {
            "phase2_run_token": "run-diag",
            "window_days": 30,
            "phase2_utm_campaign_like": "%phase2%",
            "mvps": [{"name": "alpha", "pay_intents": 1}],
        },
    )
    config.write_text(
        "mvp_mappings:\n  alpha:\n    railway_project_id: proj-1\n"
        "email_filter:\n  rules:\n    team_domains: []\n"
    )
    _railway_env_ok(monkeypatch)
    monkeypatch.setattr(
        db, "get_database_url",
        lambda project_id, service_name, environment="production": {
            "url": "postgresql://fake", "error": None,
        },
    )

    def fake_psql(db_url, sql, timeout=30):
        if "information_schema.columns" in sql:
            return {"rows": [["pay_intent", PAY_INTENT_COLS_WITH_EMAIL]], "error": None}
        if "max(created_at)" in sql or "utm_campaign IS NULL" in sql:
            return {"rows": [], "error": "diag query failed"}
        return {"rows": [
            ["u1", "d1", "buyer@acmeco.io", REAL_GCLID, "9900", "2026-06-01 00:00:00+00"],
        ], "error": None}

    monkeypatch.setattr(db, "_psql_query", fake_psql)

    db.merge_context(str(context), str(config), str(triage), token="token")

    merged = json.loads(context.read_text())
    alpha = merged["mvps"][0]
    assert alpha["db_pay_intent_source"] == "railway"
    assert alpha["db_pay_intents_paid"] == 1
    assert alpha["db_last_pay_intent_at"] is None
    assert alpha["db_gclid_no_utm_count"] is None
