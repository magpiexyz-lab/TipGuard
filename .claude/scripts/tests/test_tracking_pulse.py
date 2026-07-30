#!/usr/bin/env python3
"""Tests for .claude/scripts/lib/tracking_pulse.py."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import tracking_pulse as pulse  # noqa: E402
from gclid_filter import PAID_GCLID_FILTER  # noqa: E402


def test_campaign_query_uses_values_param_since_bound_hours_and_paid_filter():
    sql, values, created_at_missing = pulse.build_campaign_count_query(
        "alpha-search-phase2-v1",
        since="2026-06-01",
        hours=24,
    )

    assert "count(DISTINCT distinct_id)" in sql
    assert PAID_GCLID_FILTER in sql
    assert "toString(properties.utm_campaign) = {campaign}" in sql
    assert "alpha-search-phase2-v1" not in sql
    assert "timestamp >= {since}" in sql
    assert "timestamp >= now() - INTERVAL 24 HOUR" in sql
    assert values == {"campaign": "alpha-search-phase2-v1", "since": "2026-06-01"}
    assert created_at_missing is False


def test_campaign_query_falls_back_to_90d_when_created_at_missing():
    sql, values, created_at_missing = pulse.build_campaign_count_query(
        "alpha-search-phase2-v1",
        since=None,
    )

    assert "timestamp >= now() - INTERVAL 90 DAY" in sql
    assert values == {"campaign": "alpha-search-phase2-v1"}
    assert created_at_missing is True


def test_project_window_query_drops_campaign_filter_and_uses_paid_filter():
    sql, values = pulse.build_project_window_query()

    assert PAID_GCLID_FILTER in sql
    assert "utm_campaign" not in sql
    assert "timestamp >= now() - INTERVAL 90 DAY" in sql
    assert values == {}


def test_parse_count_response_accepts_list_and_dict_shapes():
    assert pulse.parse_count_response({"results": [[7]]}) == 7
    assert pulse.parse_count_response({"results": [{"gclid_visitors": "8"}]}) == 8
    assert pulse.parse_count_response({"results": [{"count": 9}]}) == 9
    assert pulse.parse_count_response({"results": []}) == 0


def test_single_project_shortcut(monkeypatch):
    monkeypatch.setattr(pulse, "list_posthog_projects", lambda api_key: [{"id": 123}])

    project_id, skip_reason = pulse.resolve_posthog_project_id("phx_test")

    assert project_id == "123"
    assert skip_reason is None


def test_multi_project_uses_ads_ready_discovery(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(
        pulse,
        "list_posthog_projects",
        lambda api_key: [{"id": "one"}, {"id": "two"}],
    )

    def fake_discover(ctx):
        seen.update(ctx)
        return {"project_id": "two"}

    monkeypatch.setattr(pulse, "discover_posthog_project", fake_discover)

    project_id, skip_reason = pulse.resolve_posthog_project_id("phx_test", tmp_path)

    assert project_id == "two"
    assert skip_reason is None
    assert seen["mvp_root"] == str(tmp_path)


def test_cli_exit_2_prints_skip_json(monkeypatch, capsys):
    monkeypatch.setattr(
        pulse,
        "read_posthog_api_key",
        lambda path=pulse.POSTHOG_KEY_PATH: (None, "missing_posthog_personal_api_key"),
    )

    rc = pulse.main(["--campaign-name", "alpha"])

    assert rc == 2
    assert json.loads(capsys.readouterr().out) == {
        "skip_reason": "missing_posthog_personal_api_key"
    }


def test_query_tracking_pulse_runs_three_queries_and_parses(monkeypatch):
    calls = []
    responses = iter([
        {"results": [[3]]},
        {"results": [[12]]},
        {"results": [[40]]},
    ])

    def fake_query(sql, values, project_id, api_key):
        calls.append((sql, values, project_id, api_key))
        return next(responses)

    monkeypatch.setattr(pulse, "_posthog_query", fake_query)

    result = pulse.query_tracking_pulse(
        campaign_name="alpha-search-phase2-v1",
        since=None,
        hours=24,
        project_id="42",
        api_key="phx_test",
    )

    assert result["ph_gclid_visitors_24h"] == 3
    assert result["ph_gclid_visitors_campaign"] == 12
    assert result["ph_gclid_visitors_project_window"] == 40
    assert result["created_at_missing"] is True
    assert len(calls) == 3
    assert calls[0][1] == {"campaign": "alpha-search-phase2-v1"}
    assert "INTERVAL 24 HOUR" in calls[0][0]
    assert "utm_campaign" not in calls[2][0]
