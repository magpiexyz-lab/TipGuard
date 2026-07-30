#!/usr/bin/env python3
"""Tests for .claude/scripts/lib/iterate_cross_propagate.py."""

from __future__ import annotations

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from iterate_cross_propagate import build_records, main  # noqa: E402


def test_propagate_raises_when_catalog_batches_status_missing():
    with tempfile.TemporaryDirectory() as td:
        context_p = os.path.join(td, "context.json")
        raw_p = os.path.join(td, "catalog-raw.json")
        output_p = os.path.join(td, "data.json")

        json.dump({"mvps": [{"name": "alpha", "owner": "Ada"}]}, open(context_p, "w"))
        json.dump({"results": []}, open(raw_p, "w"))

        with pytest.raises(RuntimeError, match="_x1_catalog_batches_status missing from catalog raw JSON"):
            main([
                "--context", context_p,
                "--catalog-raw", raw_p,
                "--output", output_p,
            ])


def test_db_paid_and_attribution_fields_survive_x1():
    payload = build_records(
        {
            "mvps": [
                {
                    "name": "alpha",
                    "owner": "Ada",
                    "gclid_visitors": 10,
                    "ga_clicks": 10,
                    "db_signups": 5,
                    "db_signups_raw": 5,
                    "db_signups_real": 5,
                    "db_signups_paid": 3,
                    "db_attribution": "gclid_shape",
                    "db_signups_real_windowed": True,
                    "db_union_tables": ["auth.users", "public.waitlist"],
                    "db_unmapped_reason": None,
                },
            ],
        },
        catalog_rows=[],
        batch_status={"complete": True},
    )
    record = payload["mvps"][0]
    assert record["db_signups_paid"] == 3
    assert record["db_attribution"] == "gclid_shape"
    assert record["db_union_tables"] == ["auth.users", "public.waitlist"]


def test_db_union_tables_defaults_to_empty_list():
    payload = build_records(
        {"mvps": [{"name": "beta", "gclid_visitors": 0, "ga_clicks": 0}]},
        catalog_rows=[],
        batch_status={"complete": True},
    )
    assert payload["mvps"][0]["db_union_tables"] == []


def test_db_backend_and_backend_keep_overlay_from_config():
    """db_backend + backend_keep ride from config mvp_mappings onto the x1
    record (config is authoritative — survives x0b skip paths)."""
    payload = build_records(
        {"mvps": [{"name": "alpha", "owner": "Ada", "gclid_visitors": 1, "ga_clicks": 1}]},
        catalog_rows=[],
        batch_status={"complete": True},
        mvp_mappings={"alpha": {
            "backend_keep": {"reason": "shared backend hosts other work"},
            "db_backend": {"status": "alive", "checked_at": "2026-07-21T00:00:00Z"},
        }},
    )
    rec = payload["mvps"][0]
    assert rec["backend_keep"]["reason"] == "shared backend hosts other work"
    assert rec["db_backend"]["status"] == "alive"


def test_owner_backstop_overlay_from_config():
    """A record with no owner (ga_only creation paths) inherits the config
    mapping owner at x1; an existing record owner is never overwritten."""
    payload = build_records(
        {"mvps": [
            {"name": "reset-app", "owner": None, "gclid_visitors": 0, "ga_clicks": 58, "ga_only": True},
            {"name": "alpha", "owner": "Ada", "gclid_visitors": 1, "ga_clicks": 1},
        ]},
        catalog_rows=[],
        batch_status={"complete": True},
        mvp_mappings={
            "reset-app": {"owner": "radlin"},
            "alpha": {"owner": "config-owner-must-not-win"},
        },
    )
    by = {r["name"]: r for r in payload["mvps"]}
    assert by["reset-app"]["owner"] == "radlin"
    assert by["alpha"]["owner"] == "Ada"


def test_owner_stays_none_when_config_has_no_mapping():
    payload = build_records(
        {"mvps": [{"name": "echo", "owner": None, "gclid_visitors": 0, "ga_clicks": 21, "ga_only": True}]},
        catalog_rows=[],
        batch_status={"complete": True},
        mvp_mappings={},
    )
    assert payload["mvps"][0]["owner"] is None


def test_db_backend_carries_from_context_when_config_lacks_it():
    payload = build_records(
        {"mvps": [{
            "name": "alpha", "gclid_visitors": 1, "ga_clicks": 1,
            "db_backend": {"status": "deleted_verified"},
        }]},
        catalog_rows=[],
        batch_status={"complete": True},
    )
    assert payload["mvps"][0]["db_backend"]["status"] == "deleted_verified"


def test_lifecycle_and_last_seen_survive_x1():
    payload = build_records(
        {
            "mvps": [
                {
                    "name": "dead",
                    "owner": "Ada",
                    "gclid_visitors": 10,
                    "last_seen": "2026-06-20T00:00:00Z",
                    "lifecycle_status": "killed",
                    "lifecycle_status_at": "2026-06-01T00:00:00Z",
                },
            ],
        },
        catalog_rows=[],
        batch_status={"complete": True},
    )
    record = payload["mvps"][0]
    assert record["last_seen"] == "2026-06-20T00:00:00Z"
    assert record["lifecycle_status"] == "killed"
    assert record["lifecycle_status_at"] == "2026-06-01T00:00:00Z"


def test_ga_cost_fields_survive_x1():
    payload = build_records(
        {
            "mvps": [
                {
                    "name": "dvara",
                    "gclid_visitors": 120,
                    "ga_clicks": 125,
                    "ga_cost": 204.93,
                    "ga_cpc": 1.64,
                    "ga_currency": "SGD",
                    "campaign_first_date": "2026-05-31",
                },
            ],
        },
        catalog_rows=[],
        batch_status={"complete": True},
    )
    record = payload["mvps"][0]
    assert record["ga_cost"] == 204.93
    assert record["ga_cpc"] == 1.64
    assert record["ga_currency"] == "SGD"
    assert record["campaign_first_date"] == "2026-05-31"


def test_ga_impressions_survives_x1():
    # Whitelist is hand-listed — dropping ga_impressions here would silently
    # turn every stalled cause into no_telemetry at x3.
    payload = build_records(
        {
            "mvps": [
                {"name": "served", "gclid_visitors": 5, "ga_clicks": 3, "ga_impressions": 812},
                {"name": "no-column", "gclid_visitors": 5, "ga_clicks": 3},
            ],
        },
        catalog_rows=[],
        batch_status={"complete": True},
    )
    by = {r["name"]: r for r in payload["mvps"]}
    assert by["served"]["ga_impressions"] == 812
    assert "ga_impressions" in by["no-column"]
    assert by["no-column"]["ga_impressions"] is None


def test_cpc_exception_overlay_from_config():
    # Override lives in config mvp_mappings, NOT on the context record. The
    # propagate overlay stamps it onto the record so compute_cpc_flags can read it.
    payload = build_records(
        {"mvps": [{"name": "bayt-labs", "gclid_visitors": 60, "ga_clicks": 60}]},
        catalog_rows=[],
        batch_status={"complete": True},
        mvp_mappings={
            "bayt-labs": {
                "cpc_exception": {"reason": "high LTV", "max_cpc_override": 5.0},
                "channel_waiver": {"reason": "strategic"},
            },
        },
    )
    record = payload["mvps"][0]
    assert record["cpc_exception"]["max_cpc_override"] == 5.0
    assert record["channel_waiver"]["reason"] == "strategic"


def test_no_overlay_when_mapping_absent():
    payload = build_records(
        {"mvps": [{"name": "plain", "gclid_visitors": 5}]},
        catalog_rows=[],
        batch_status={"complete": True},
        mvp_mappings={},
    )
    record = payload["mvps"][0]
    assert "cpc_exception" not in record
    assert "channel_waiver" not in record


def test_ga_phase2_split_fields_survive_x1():
    # The rec dict in build_records is a hand-listed whitelist: dropping these
    # keys silently re-blends the Phase-1 denominator downstream (x3 defaults
    # the missing key to 0). This test pins them into the whitelist.
    payload = build_records(
        {
            "mvps": [
                {
                    "name": "handpick",
                    "gclid_visitors": 311,
                    "ga_clicks": 371,
                    "ga_clicks_phase2": 258,
                    "ga_cost_phase2": 103.2,
                    "ga_campaigns_phase2": ["handpick-search-phase2-v1"],
                },
            ],
        },
        catalog_rows=[],
        batch_status={"complete": True},
    )
    record = payload["mvps"][0]
    assert record["ga_clicks_phase2"] == 258
    assert record["ga_cost_phase2"] == 103.2
    assert record["ga_campaigns_phase2"] == ["handpick-search-phase2-v1"]


def test_ga_ads_status_fields_survive_x1():
    # Same whitelist trap as the phase2 split: dropping these keys silently
    # blinds x4b's csv_paused ads evidence (it would read every MVP as
    # "no status data" and fall back to manual confirm-ads).
    payload = build_records(
        {
            "mvps": [
                {
                    "name": "termob",
                    "gclid_visitors": 10,
                    "ga_clicks": 50,
                    "ga_campaign_status_detail": [
                        {"name": "termob-search-v1", "campaign_status": "Enabled",
                         "serving_status": "Eligible", "status_reasons": "--",
                         "normalized": "active"},
                    ],
                    "ga_ads_all_stopped": False,
                },
            ],
        },
        catalog_rows=[],
        batch_status={"complete": True},
    )
    record = payload["mvps"][0]
    assert record["ga_ads_all_stopped"] is False
    assert record["ga_campaign_status_detail"][0]["normalized"] == "active"


def test_ga_ads_status_defaults_when_absent():
    # Pre-status context records (or exports without the status columns) get
    # the safe defaults: detail=[] and tri-state None (→ confirm-ads path).
    payload = build_records(
        {"mvps": [{"name": "legacy", "gclid_visitors": 5, "ga_clicks": 40}]},
        catalog_rows=[],
        batch_status={"complete": True},
    )
    record = payload["mvps"][0]
    assert record["ga_campaign_status_detail"] == []
    assert record["ga_ads_all_stopped"] is None


def test_ga_phase2_split_defaults_when_absent():
    # Pre-split context records (or MVPs with no phase2 campaigns) get safe
    # defaults so x3's subtraction is a no-op.
    payload = build_records(
        {"mvps": [{"name": "legacy", "gclid_visitors": 5, "ga_clicks": 40}]},
        catalog_rows=[],
        batch_status={"complete": True},
    )
    record = payload["mvps"][0]
    assert record["ga_clicks_phase2"] == 0
    assert record["ga_cost_phase2"] is None
    assert record["ga_campaigns_phase2"] == []
