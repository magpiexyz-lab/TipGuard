#!/usr/bin/env python3
"""Tests for iterate_cross_posthog_batch.py."""

from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import iterate_cross_posthog_batch as batch  # noqa: E402
from gclid_filter import PAID_GCLID_FILTER, SYNTHETIC_GCLID_PREFIX  # noqa: E402


def test_posthog_query_retries_empty_stdout_then_succeeds():
    calls = [
        SimpleNamespace(returncode=0, stdout="", stderr=""),
        SimpleNamespace(returncode=0, stdout=json.dumps({"results": [["ok"]]}), stderr=""),
    ]
    with patch("iterate_cross_posthog_batch.subprocess.run", side_effect=calls) as mock_run, \
         patch("iterate_cross_posthog_batch.time.sleep") as mock_sleep:
        resp = batch._posthog_query("SELECT 1", {}, "pid", "key", max_time_seconds=12)

    assert resp["results"] == [["ok"]]
    assert mock_run.call_count == 2
    mock_sleep.assert_called_once_with(1)


def test_posthog_query_passes_curl_max_time():
    with patch(
        "iterate_cross_posthog_batch.subprocess.run",
        return_value=SimpleNamespace(returncode=0, stdout=json.dumps({"results": []}), stderr=""),
    ) as mock_run:
        batch._posthog_query("SELECT 1", {}, "pid", "key", max_time_seconds=7)

    argv = mock_run.call_args.args[0]
    assert "--max-time" in argv
    assert argv[argv.index("--max-time") + 1] == "7"


def test_paginate_discovery_query_single_offset_free_fetch():
    # Personal API keys reject OFFSET, so a discovery query is a single capped
    # LIMIT-only fetch; a short page (< cap) proves completeness.
    calls = []

    def fake_query(sql, values, project_id, api_key, max_time_seconds=30):
        calls.append(sql)
        return {"results": [[i] for i in range(67)]}

    with patch("iterate_cross_posthog_batch._posthog_query", side_effect=fake_query):
        rows, meta = batch.paginate_discovery_query(
            "SELECT x FROM events ORDER BY x LIMIT 200",
            {},
            "pid",
            "key",
            page_size=200,
        )

    assert len(rows) == 67
    assert meta == {"status": "complete", "pages_fetched": 1}
    assert len(calls) == 1
    assert "OFFSET" not in calls[0].upper()
    # cap = page_size(200) * default max_pages(20)
    assert calls[0].endswith("LIMIT 4000")


def test_paginate_discovery_query_normalizes_placeholders_without_offset():
    seen = []

    def fake_query(sql, values, project_id, api_key, max_time_seconds=30):
        seen.append(sql)
        return {"results": []}

    with patch("iterate_cross_posthog_batch._posthog_query", side_effect=fake_query):
        rows, meta = batch.paginate_discovery_query(
            "SELECT x LIMIT {limit} OFFSET {offset}",
            {},
            "pid",
            "key",
            page_size=50,
        )

    assert rows == []
    assert meta["pages_fetched"] == 1
    # cap = page_size(50) * default max_pages(20); OFFSET placeholder dropped.
    assert seen == ["SELECT x LIMIT 1000"]


def test_paginate_discovery_query_raises_when_cap_hit():
    # A full page (== cap) cannot prove completeness without OFFSET, so raise.
    cap = 10 * 2
    with patch(
        "iterate_cross_posthog_batch._posthog_query",
        return_value={"results": [[i] for i in range(cap)]},
    ):
        with pytest.raises(RuntimeError, match="cap"):
            batch.paginate_discovery_query(
                "SELECT x",
                {},
                "pid",
                "key",
                page_size=10,
                max_pages=2,
            )


def test_run_union_batches_splits_parts():
    sqls = []

    def fake_query(sql, values, project_id, api_key, max_time_seconds=30):
        sqls.append(sql)
        return {"results": [[len(sqls)]]}

    parts = [f"SELECT {i}" for i in range(45)]
    with patch("iterate_cross_posthog_batch._posthog_query", side_effect=fake_query):
        rows, meta = batch.run_union_batches(parts, {"x": 1}, "pid", "key", batch_size=15)

    assert rows == [[1], [2], [3]]
    assert meta == {"complete": True, "batches_run": 3, "parts_total": 45}
    assert len(sqls) == 3
    assert all(" UNION ALL " in sql for sql in sqls)


def test_run_union_batches_empty_fast_path():
    rows, meta = batch.run_union_batches([], {}, "pid", "key")
    assert rows == []
    assert meta == {"complete": True, "batches_run": 0, "parts_total": 0}


def test_paid_gclid_filter_excludes_ads_ready_synthetic_prefix():
    assert SYNTHETIC_GCLID_PREFIX == "Cj0KCQjw_ads_ready_synthetic_"
    assert "AND NOT startsWith" in PAID_GCLID_FILTER
    assert SYNTHETIC_GCLID_PREFIX in PAID_GCLID_FILTER


# ---------- compute_orphan_overlap ----------

def _overlap_pairs():
    return [("neuralpost", "neuralpost"), ("x-predict", "xpredict")]


def test_compute_orphan_overlap_threads_phase_clause_and_values():
    calls = []

    def fake_query(sql, values, project_id, api_key, max_time_seconds=30, attempts=3):
        calls.append((sql, dict(values)))
        return {"results": [[10, 5, 4]]}

    phase_clause = "AND toString(properties.utm_campaign) LIKE {phase_campaign} "
    with patch("iterate_cross_posthog_batch._posthog_query", side_effect=fake_query):
        out = batch.compute_orphan_overlap(
            _overlap_pairs(),
            "pid",
            "key",
            365,
            phase_clause=phase_clause,
            phase_values={"phase_campaign": "%phase2%"},
        )

    assert len(calls) == 2  # serial, one query per pair
    for sql, values in calls:
        assert sql.count(phase_clause.strip()) == 2  # both CTEs phase-scoped
        assert "INTERSECT" in sql
        assert "INTERVAL 365 DAY" in sql
        assert values["phase_campaign"] == "%phase2%"
        assert "cn" in values and "oh" in values
    assert out["neuralpost"]["orphan_host"] == "neuralpost"


def test_compute_orphan_overlap_returns_by_canonical_shape():
    def fake_query(sql, values, project_id, api_key, max_time_seconds=30, attempts=3):
        return {"results": [[63, 16, 15]]}

    with patch("iterate_cross_posthog_batch._posthog_query", side_effect=fake_query):
        out = batch.compute_orphan_overlap([("neuralpost", "neuralpost")], "pid", "key", 90)

    assert out == {
        "neuralpost": {
            "orphan_host": "neuralpost",
            "canonical_gclids": 63,
            "orphan_gclids": 16,
            "overlap": 15,
        }
    }


def test_compute_orphan_overlap_cache_hit_skips_queried_pairs(tmp_path):
    cache = tmp_path / "overlap.json"
    calls = []

    def fake_query(sql, values, project_id, api_key, max_time_seconds=30, attempts=3):
        calls.append(values)
        return {"results": [[10, 5, 4]]}

    with patch("iterate_cross_posthog_batch._posthog_query", side_effect=fake_query):
        first = batch.compute_orphan_overlap(
            _overlap_pairs(), "pid", "key", 90, cache_path=str(cache)
        )
        assert len(calls) == 2
        second = batch.compute_orphan_overlap(
            _overlap_pairs(), "pid", "key", 90, cache_path=str(cache)
        )

    assert len(calls) == 2  # cache hit: zero new queries
    assert second == first


def test_compute_orphan_overlap_cache_invalidated_by_phase_scope(tmp_path):
    cache = tmp_path / "overlap.json"
    calls = []

    def fake_query(sql, values, project_id, api_key, max_time_seconds=30, attempts=3):
        calls.append(values)
        return {"results": [[10, 5, 4]]}

    pairs = [("neuralpost", "neuralpost")]
    with patch("iterate_cross_posthog_batch._posthog_query", side_effect=fake_query):
        batch.compute_orphan_overlap(pairs, "pid", "key", 90, cache_path=str(cache))
        batch.compute_orphan_overlap(
            pairs,
            "pid",
            "key",
            90,
            phase_clause="AND x LIKE {phase_campaign} ",
            phase_values={"phase_campaign": "%phase2%"},
            cache_path=str(cache),
        )

    assert len(calls) == 2  # same pairs, different scope_hash -> requeried


def test_compute_orphan_overlap_pair_failure_warns_and_omits(capsys):
    def fake_query(sql, values, project_id, api_key, max_time_seconds=30, attempts=3):
        if values["cn"] == "neuralpost":
            raise RuntimeError("boom")
        return {"results": [[10, 5, 4]]}

    with patch("iterate_cross_posthog_batch._posthog_query", side_effect=fake_query):
        out = batch.compute_orphan_overlap(_overlap_pairs(), "pid", "key", 90)

    assert "neuralpost" not in out
    assert "x-predict" in out
    assert "WARN: overlap query failed for neuralpost/neuralpost" in capsys.readouterr().err


def test_compute_orphan_overlap_writes_cache_incrementally_and_atomically(tmp_path):
    cache = tmp_path / "overlap.json"
    seen_after_first_pair = {}

    def fake_query(sql, values, project_id, api_key, max_time_seconds=30, attempts=3):
        if values["cn"] == "x-predict" and cache.exists():
            seen_after_first_pair.update(json.loads(cache.read_text()))
        return {"results": [[10, 5, 4]]}

    with patch("iterate_cross_posthog_batch._posthog_query", side_effect=fake_query):
        batch.compute_orphan_overlap(_overlap_pairs(), "pid", "key", 90, cache_path=str(cache))

    # cache was valid JSON containing the first pair BEFORE the second ran
    assert "neuralpost" in (seen_after_first_pair.get("by_canonical") or {})
    final = json.loads(cache.read_text())
    assert set(final["by_canonical"]) == {"neuralpost", "x-predict"}
    assert {"project_id", "window_days", "pairs_hash", "scope_hash"} <= set(final)
    assert not list(tmp_path.glob("*.tmp.*"))  # atomic replace leaves no residue


# ---------- server-error + retry semantics ----------

def test_posthog_query_raises_immediately_on_server_error():
    # A resp["error"] body (max-execution-time / circuit-breaker) must raise on
    # the first attempt with no retry sleeps — in-function retries would trip
    # the PostHog circuit breaker harder; cooldown-resume lives at the
    # compute_orphan_overlap pass level.
    with patch(
        "iterate_cross_posthog_batch.subprocess.run",
        return_value=SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"error": "Query has hit the max execution time"}),
            stderr="",
        ),
    ) as mock_run, patch("iterate_cross_posthog_batch.time.sleep") as mock_sleep:
        with pytest.raises(RuntimeError, match="max execution time"):
            batch._posthog_query("SELECT 1", {}, "pid", "key")

    assert mock_run.call_count == 1
    mock_sleep.assert_not_called()


def test_posthog_query_transport_retry_exhaustion():
    calls = [SimpleNamespace(returncode=28, stdout="", stderr="timeout")] * 3
    with patch("iterate_cross_posthog_batch.subprocess.run", side_effect=calls) as mock_run, \
         patch("iterate_cross_posthog_batch.time.sleep") as mock_sleep:
        with pytest.raises(RuntimeError, match="after 3 attempts"):
            batch._posthog_query("SELECT 1", {}, "pid", "key")

    assert mock_run.call_count == 3
    assert [c.args[0] for c in mock_sleep.call_args_list] == [1, 2]


def test_paginate_discovery_query_forwards_max_time_seconds():
    seen = []

    def fake_query(sql, values, project_id, api_key, max_time_seconds=30):
        seen.append(max_time_seconds)
        return {"results": []}

    with patch("iterate_cross_posthog_batch._posthog_query", side_effect=fake_query):
        batch.paginate_discovery_query(
            "SELECT x LIMIT 10", {}, "pid", "key", page_size=10, max_time_seconds=120
        )

    assert seen == [120]


def test_run_union_batches_forwards_max_time_seconds():
    seen = []

    def fake_query(sql, values, project_id, api_key, max_time_seconds=30):
        seen.append(max_time_seconds)
        return {"results": []}

    with patch("iterate_cross_posthog_batch._posthog_query", side_effect=fake_query):
        batch.run_union_batches(
            ["SELECT 1", "SELECT 2"], {}, "pid", "key", batch_size=1,
            max_time_seconds=120,
        )

    assert seen == [120, 120]


# ---------- cooldown-resume passes ----------

def test_compute_orphan_overlap_multipass_cooldown_recovers_failures(tmp_path):
    cache = tmp_path / "overlap.json"
    attempts_by_pair = {}

    def fake_query(sql, values, project_id, api_key, max_time_seconds=30, attempts=3):
        key = values["cn"]
        attempts_by_pair[key] = attempts_by_pair.get(key, 0) + 1
        if key == "x-predict" and attempts_by_pair[key] == 1:
            raise RuntimeError("max execution time")
        return {"results": [[10, 5, 4]]}

    with patch("iterate_cross_posthog_batch._posthog_query", side_effect=fake_query), \
         patch("iterate_cross_posthog_batch.time.sleep") as mock_sleep:
        out = batch.compute_orphan_overlap(
            _overlap_pairs(),
            "pid",
            "key",
            365,
            cache_path=str(cache),
            max_time_seconds=120,
            cooldown_seconds=300,
            failure_sleep_seconds=20,
            max_passes=3,
        )

    # Pass 1: neuralpost ok, x-predict fails (sleep 20); pass 2: cooldown 300,
    # only x-predict retried (neuralpost served from cache), succeeds; no third
    # pass and no trailing sleep.
    assert [c.args[0] for c in mock_sleep.call_args_list] == [20, 300]
    assert attempts_by_pair == {"neuralpost": 1, "x-predict": 2}
    assert set(out) == {"neuralpost", "x-predict"}


def test_compute_orphan_overlap_exhausted_passes_omit_and_stop_sleeping(tmp_path):
    cache = tmp_path / "overlap.json"

    def fake_query(sql, values, project_id, api_key, max_time_seconds=30, attempts=3):
        if values["cn"] == "x-predict":
            raise RuntimeError("max execution time")
        return {"results": [[10, 5, 4]]}

    with patch("iterate_cross_posthog_batch._posthog_query", side_effect=fake_query), \
         patch("iterate_cross_posthog_batch.time.sleep") as mock_sleep:
        out = batch.compute_orphan_overlap(
            _overlap_pairs(),
            "pid",
            "key",
            365,
            cache_path=str(cache),
            cooldown_seconds=300,
            failure_sleep_seconds=20,
            max_passes=2,
        )

    # failure sleeps (20) in both passes, exactly ONE inter-pass cooldown (300),
    # and no cooldown after the final pass.
    assert [c.args[0] for c in mock_sleep.call_args_list] == [20, 300, 20]
    assert "x-predict" not in out  # WARN + omit
    assert "neuralpost" in out


def test_compute_orphan_overlap_single_pass_default_never_sleeps(tmp_path):
    def fake_query(sql, values, project_id, api_key, max_time_seconds=30, attempts=3):
        if values["cn"] == "x-predict":
            raise RuntimeError("boom")
        return {"results": [[10, 5, 4]]}

    with patch("iterate_cross_posthog_batch._posthog_query", side_effect=fake_query), \
         patch("iterate_cross_posthog_batch.time.sleep") as mock_sleep:
        out = batch.compute_orphan_overlap(
            _overlap_pairs(), "pid", "key", 365,
            cache_path=str(tmp_path / "overlap.json"),
        )

    mock_sleep.assert_not_called()
    assert "x-predict" not in out
