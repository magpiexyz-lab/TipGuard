#!/usr/bin/env python3
"""Tests for .claude/scripts/lib/iterate_cross_ledger.py (state x4a decision ledger).

Run:
  python3 -m pytest .claude/scripts/tests/test_iterate_cross_ledger.py -v
  # OR (no pytest dependency):
  python3 .claude/scripts/tests/test_iterate_cross_ledger.py
"""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

# Direct-run isolation (pytest gets the same via conftest.py): keep the gh
# name-index cache out of the production .runs/ artifact.
os.environ.setdefault(
    "ITERATE_CROSS_NAME_INDEX_CACHE",
    os.path.join(tempfile.gettempdir(), "gh-name-index-test.json"),
)

import iterate_cross_ledger as L  # noqa: E402
import iterate_cross_pricing as P  # noqa: E402


def _score(name, verdict, **kw):
    metrics = kw.pop("metrics", {})
    s = {"name": name, "headline_verdict": verdict, "metrics": metrics}
    s.update(kw)
    return s


def _fake_gh(repos=(), files=None):
    """files: {(repo, path): text}. Missing -> rc 1 (404). Mirrors pricing test."""
    files = files or {}

    def gh(args, timeout=30):
        if args[:2] == ["auth", "status"]:
            return 0, "", ""
        if args[:2] == ["repo", "list"]:
            return 0, json.dumps([{"name": r} for r in repos]), ""
        if args and args[0] == "api":
            endpoint = args[1]
            parts = endpoint.split("/")
            repo, path = parts[2], "/".join(parts[4:])
            text = files.get((repo, path))
            if text is None:
                return 1, "", "gh: Not Found (HTTP 404)"
            return 0, base64.b64encode(text.encode()).decode(), ""
        return 1, "", "unknown"
    return gh


# ---------- canonical_name + alias ----------

def test_canonical_alias_collapse():
    idx = L.build_alias_index({"splitshare": ["split-share-neon"]})
    assert L.canonical_name(_score("split-share-neon", "NO_GO"), idx) == "splitshare"
    assert L.canonical_name(_score("splitshare", "NO_GO"), idx) == "splitshare"


def test_canonical_orphan_is_none():
    assert L.canonical_name(_score("__orphan_x__", "MISSING_PROJECT_NAME"), {}) is None
    assert L.canonical_name(_score("y", "NO_DATA", db_unmapped_reason="orphan"), {}) is None


def test_alias_collision_raises():
    try:
        L.build_alias_index({"a": ["dup"], "b": ["dup"]})
    except ValueError as e:
        assert "dup" in str(e)
        return
    raise AssertionError("expected ValueError on alias collision")


# ---------- append_history ----------

def test_history_dedup_consecutive():
    h = []
    h = L.append_history(h, {"date": "d1", "verdict": "INSUFFICIENT_DATA", "why": ""})
    h = L.append_history(h, {"date": "d2", "verdict": "INSUFFICIENT_DATA", "why": ""})
    assert len(h) == 1  # identical verdict+why → no new row
    h = L.append_history(h, {"date": "d3", "verdict": "NO_GO", "why": "low conv"})
    assert len(h) == 2


def test_history_cap():
    h = []
    for i in range(20):
        h = L.append_history(h, {"date": f"d{i}", "verdict": f"V{i}", "why": ""}, cap=12)
    assert len(h) == 12
    assert h[0]["verdict"] == "V8"  # kept last 12


# ---------- merge_sticky ----------

def test_sticky_never_overwrites_with_empty():
    out = L.merge_sticky({"thesis": "kept"}, {"thesis": "", "target_user": "new"})
    assert out == {"thesis": "kept", "target_user": "new"}


def test_sticky_fills_empty_only():
    out = L.merge_sticky({"thesis": "old"}, {"thesis": "newer"})
    assert out["thesis"] == "old"  # not overwritten (fill-if-empty)


def test_sticky_force_overwrites():
    out = L.merge_sticky({"thesis": "old"}, {"thesis": "newer"}, force=True)
    assert out["thesis"] == "newer"


# ---------- validate_tags ----------

def test_validate_tags_drops_out_of_vocab():
    clean, warnings = L.validate_tags(
        {"vertical": "ai-content", "gtm": "bogus", "pricing_model": "subscription"},
        L.DEFAULT_TAG_VOCAB,
    )
    assert clean == {"vertical": "ai-content", "pricing_model": "subscription"}
    assert any("bogus" in w for w in warnings)


# ---------- parse_description ----------

def test_parse_description_mechanical():
    text = "name: x\nthesis: A clear thesis\ntarget_user: SMB CTOs\nproblem: manual work\n"
    out = L.parse_description(text)
    assert out["thesis"] == "A clear thesis"
    assert out["target_user"] == "SMB CTOs"
    assert out["problem"] == "manual work"


def test_parse_description_empty_on_garbage():
    assert L.parse_description(None) == {}
    assert L.parse_description("::: not yaml :::\n  - [") == {}


# ---------- upsert_row: freeze / un-freeze / sticky ----------

def test_upsert_creates_row():
    s = _score("a", "GO", db_source="supabase",
               metrics={"ga_clicks": 100, "db_signups_real": 8, "signup_source": "db_real"})
    row = L.upsert_row(None, s, {}, "2026-06-29", {"thesis": "t"}, {"vertical": "dev-tools"}, "RepoA", why="")
    assert row["mvp"] == "a"
    assert row["current"]["verdict"] == "GO"
    assert row["what_it_does"]["thesis"] == "t"
    assert row["tags"]["vertical"] == "dev-tools"
    assert row["first_seen_in_ledger"] == "2026-06-29"
    assert row["archived_at"] is None


def test_upsert_freeze_on_killed():
    s = _score("a", "NO_GO", lifecycle_status="killed", metrics={"ga_clicks": 100})
    row = L.upsert_row(None, s, {}, "2026-06-29", {}, {}, None, why="x")
    assert row["archived_at"] == "2026-06-29"
    # current is still snapshotted (the pre-teardown state)
    assert row["current"]["verdict"] == "NO_GO"


def test_upsert_freeze_on_project_deleted():
    s = _score("a", "NO_GO", db_unmapped_reason="project_deleted", metrics={"ga_clicks": 100})
    row = L.upsert_row(None, s, {}, "2026-06-29", {}, {}, None, why="x")
    assert row["archived_at"] == "2026-06-29"


def test_upsert_promoted_never_freezes_and_captures_lifecycle():
    s = _score("h", "GO", lifecycle_status="promoted",
               lifecycle_status_at="2026-06-16T15:24:40Z",
               metrics={"ga_clicks": 371, "ga_clicks_phase1": 113})
    row = L.upsert_row(None, s, {}, "2026-07-18", {}, {}, None, why="")
    assert row["archived_at"] is None
    assert row["current"]["lifecycle_status"] == "promoted"
    assert row["current"]["ga_clicks_phase1"] == 113


def test_upsert_active_to_promoted_appends_one_transition_event():
    existing = {
        "mvp": "h", "phase": "phase-1",
        "current": {"verdict": "GO", "lifecycle_status": "active", "ga_clicks": 371},
        "verdict_history": [{"date": "2026-07-15", "verdict": "GO", "why": ""}],
        "what_it_does": {}, "tags": {},
        "first_seen_in_ledger": "2026-07-15", "last_seen_in_ledger": "2026-07-15",
        "archived_at": None,
    }
    s = _score("h", "GO", lifecycle_status="promoted",
               lifecycle_status_at="2026-06-16T15:24:40Z",
               metrics={"ga_clicks": 371})
    row = L.upsert_row(existing, s, {}, "2026-07-18", {}, {}, None, why="")
    events = [e for e in row["verdict_history"] if e.get("verdict") == "PROMOTED"]
    assert len(events) == 1
    assert "2026-06-16T15:24:40Z" in events[0]["why"]

    # Re-run: stored snapshot is already promoted → edge does not re-fire.
    row2 = L.upsert_row(row, s, {}, "2026-07-19", {}, {}, None, why="")
    assert len([e for e in row2["verdict_history"] if e.get("verdict") == "PROMOTED"]) == 1


def test_upsert_pre_split_existing_row_backfills_lifecycle_without_event_dup():
    # Rows written before current.lifecycle_status existed: prev defaults to
    # "active", so a promoted incoming score appends exactly one event.
    existing = {
        "mvp": "h", "phase": "phase-1",
        "current": {"verdict": "GO", "ga_clicks": 371},  # no lifecycle_status key
        "verdict_history": [{"date": "2026-07-15", "verdict": "GO", "why": ""}],
        "what_it_does": {}, "tags": {},
        "first_seen_in_ledger": "2026-07-15", "last_seen_in_ledger": "2026-07-15",
        "archived_at": None,
    }
    s = _score("h", "GO", lifecycle_status="promoted", metrics={"ga_clicks": 371})
    row = L.upsert_row(existing, s, {}, "2026-07-18", {}, {}, None, why="")
    assert row["current"]["lifecycle_status"] == "promoted"
    assert len([e for e in row["verdict_history"] if e.get("verdict") == "PROMOTED"]) == 1


def test_upsert_promoted_then_killed_freezes_normally():
    existing = {
        "mvp": "h", "phase": "phase-1",
        "current": {"verdict": "GO", "lifecycle_status": "promoted", "ga_clicks": 371},
        "verdict_history": [{"date": "2026-07-18", "verdict": "PROMOTED", "why": "operator confirmed"}],
        "what_it_does": {}, "tags": {},
        "first_seen_in_ledger": "2026-07-15", "last_seen_in_ledger": "2026-07-18",
        "archived_at": None,
    }
    s = _score("h", "NO_GO", lifecycle_status="killed", metrics={"ga_clicks": 371})
    row = L.upsert_row(existing, s, {}, "2026-08-01", {}, {}, None, why="stopped")
    assert row["archived_at"] == "2026-08-01"
    assert row["current"]["lifecycle_status"] == "killed"


def test_upsert_sticky_preserved_on_degraded_rerun():
    # Seed a rich row, then re-run with EMPTY parsed_desc + tags (repo gone).
    existing = {
        "mvp": "a", "phase": "phase-1",
        "current": {"verdict": "NO_GO", "ga_clicks": 100},
        "verdict_history": [{"date": "2026-06-01", "verdict": "NO_GO", "why": "low conv"}],
        "what_it_does": {"thesis": "original thesis", "target_user": "SMBs"},
        "tags": {"vertical": "fintech", "gtm": "waitlist"},
        "first_seen_in_ledger": "2026-06-01", "last_seen_in_ledger": "2026-06-01",
        "archived_at": None,
    }
    s = _score("a", "NO_GO", metrics={"ga_clicks": 150, "true_conv_rate": 0.01})
    row = L.upsert_row(existing, s, {}, "2026-06-29", parsed_desc={}, tags={}, repo=None, why="low conv")
    # sticky fields intact
    assert row["what_it_does"] == {"thesis": "original thesis", "target_user": "SMBs"}
    assert row["tags"] == {"vertical": "fintech", "gtm": "waitlist"}
    # current refreshed
    assert row["current"]["ga_clicks"] == 150
    # history NOT appended (same verdict+why)
    assert len(row["verdict_history"]) == 1


def test_upsert_frozen_row_untouched():
    existing = {
        "mvp": "a", "phase": "phase-1",
        "current": {"verdict": "NO_GO", "ga_clicks": 100, "db_signups_real": 4},
        "verdict_history": [{"date": "2026-06-01", "verdict": "NO_GO", "why": "low conv"}],
        "what_it_does": {"thesis": "frozen thesis"},
        "tags": {"vertical": "fintech"},
        "first_seen_in_ledger": "2026-06-01", "last_seen_in_ledger": "2026-06-01",
        "archived_at": "2026-06-08",
    }
    # later run shows DIFFERENT metrics but backend still deleted → must stay frozen + untouched
    s = _score("a", "NO_GO", db_unmapped_reason="project_deleted",
               metrics={"ga_clicks": 999, "db_signups_real": 0})
    row = L.upsert_row(existing, s, {}, "2026-06-29", {"thesis": "new"}, {"vertical": "other"}, None, why="x")
    assert row["archived_at"] == "2026-06-08"  # unchanged
    assert row["current"]["ga_clicks"] == 100  # frozen ground truth, NOT 999
    assert row["what_it_does"]["thesis"] == "frozen thesis"
    assert len(row["verdict_history"]) == 1


def test_upsert_unfreeze_when_live_db_returns():
    existing = {
        "mvp": "a", "phase": "phase-1",
        "current": {"verdict": "NO_GO", "ga_clicks": 100},
        "verdict_history": [{"date": "2026-06-01", "verdict": "NO_GO", "why": "x"}],
        "what_it_does": {}, "tags": {},
        "first_seen_in_ledger": "2026-06-01", "last_seen_in_ledger": "2026-06-01",
        "archived_at": "2026-06-08",
    }
    # backend is live again: db_source set + real int db_signups, not deleted/killed
    s = _score("a", "INSUFFICIENT_DATA", db_source="supabase",
               metrics={"ga_clicks": 120, "db_signups_real": 3})
    row = L.upsert_row(existing, s, {}, "2026-06-29", {}, {}, None, why="")
    assert row["archived_at"] is None  # un-frozen
    assert row["current"]["ga_clicks"] == 120  # resumed updating
    assert len(row["verdict_history"]) == 2  # new verdict appended


# ---------- end-to-end persist (orphan skip, ga_only include, atomic sorted write) ----------

def test_persist_e2e_orphan_skip_and_sorted():
    with tempfile.TemporaryDirectory() as td:
        scores_path = os.path.join(td, "scores.json")
        ledger_path = os.path.join(td, "ledger.jsonl")
        input_path = os.path.join(td, "input.json")
        proposals_path = os.path.join(td, "proposals.json")
        json.dump({
            "thresholds": {"visitors_floor": 100, "conv_rate_go": 0.06, "max_cpc": 2.5},
            "mvps": [
                _score("zeta", "GO", db_source="supabase",
                       metrics={"ga_clicks": 110, "db_signups_real": 8, "true_conv_rate": 0.07}),
                _score("alpha", "NO_GO", metrics={"ga_clicks": 200, "true_conv_rate": 0.01}),
                _score("ga-blind", "GA_NO_PH_TRACKING", ga_only=True, metrics={"ga_clicks": 30}),
                _score("__orphan_x__", "MISSING_PROJECT_NAME", metrics={}),
            ],
        }, open(scores_path, "w"))
        json.dump({"to_enrich": [], "desc_only": []}, open(input_path, "w"))
        json.dump([], open(proposals_path, "w"))

        L.cmd_persist(scores_path, None, ledger_path, input_path, proposals_path, now_iso="2026-06-29")

        rows = [json.loads(l) for l in open(ledger_path)]
        names = [r["mvp"] for r in rows]
        assert names == ["alpha", "ga-blind", "zeta"]  # sorted, orphan excluded
        ga_blind = next(r for r in rows if r["mvp"] == "ga-blind")
        assert ga_blind["current"]["verdict"] == "GA_NO_PH_TRACKING"  # ga_only included


def test_persist_e2e_no_dup_history_on_rerun():
    with tempfile.TemporaryDirectory() as td:
        scores_path = os.path.join(td, "scores.json")
        ledger_path = os.path.join(td, "ledger.jsonl")
        input_path = os.path.join(td, "input.json")
        proposals_path = os.path.join(td, "proposals.json")
        doc = {
            "thresholds": {"visitors_floor": 100, "conv_rate_go": 0.06, "max_cpc": 2.5},
            "mvps": [_score("a", "NO_GO", metrics={"ga_clicks": 200, "true_conv_rate": 0.01})],
        }
        json.dump(doc, open(scores_path, "w"))
        json.dump({"to_enrich": [], "desc_only": []}, open(input_path, "w"))
        json.dump([], open(proposals_path, "w"))
        L.cmd_persist(scores_path, None, ledger_path, input_path, proposals_path, now_iso="2026-06-29")
        L.cmd_persist(scores_path, None, ledger_path, input_path, proposals_path, now_iso="2026-06-30")
        rows = [json.loads(l) for l in open(ledger_path)]
        assert len(rows) == 1
        assert len(rows[0]["verdict_history"]) == 1  # same verdict+why → no dup


def test_current_snapshot_carries_stalled_fields():
    s = _score("s", "INSUFFICIENT_DATA", metrics={
        "ga_clicks": 19, "ga_impressions": 37, "stalled_bucket": "stalled",
        "stalled_cause": "zero_serve", "stalled_since": "2026-07-05",
        "stalled_streak": 2,
    })
    cur = L.current_snapshot(s, "", "2026-07-22")
    assert cur["ga_impressions"] == 37
    assert cur["stalled_bucket"] == "stalled"
    assert cur["stalled_cause"] == "zero_serve"
    assert cur["stalled_since"] == "2026-07-05"
    assert cur["stalled_streak"] == 2


def test_stalled_why_constant_and_number_free():
    assert L.stalled_why(_score("s", "INSUFFICIENT_DATA",
                                metrics={"stalled_escalated": False})) == ""
    why = L.stalled_why(_score("s", "INSUFFICIENT_DATA", metrics={
        "stalled_escalated": True, "stalled_cause": "zero_serve"}))
    assert "NOT a product NO-GO" in why
    # Constant per cause — any varying number would defeat append_history dedup.
    assert not any(ch.isdigit() for ch in why)
    weak = L.stalled_why(_score("s", "INSUFFICIENT_DATA", metrics={
        "stalled_escalated": True, "stalled_cause": "weak_demand"}))
    assert "weak-demand" in weak and "NOT a product NO-GO" not in weak


def test_persist_e2e_stalled_escalated_records_why_pre_kill():
    # The channel-infeasible story must land in the ledger WHILE the row is
    # still INSUF — a later confirmed kill flips it to the generic archived
    # NO_GO and the nuance would otherwise be lost.
    with tempfile.TemporaryDirectory() as td:
        scores_path = os.path.join(td, "scores.json")
        ledger_path = os.path.join(td, "ledger.jsonl")
        input_path = os.path.join(td, "input.json")
        proposals_path = os.path.join(td, "proposals.json")
        json.dump({
            "thresholds": {"visitors_floor": 100, "conv_rate_go": 0.06, "max_cpc": 2.5},
            "mvps": [_score("scangap", "INSUFFICIENT_DATA", metrics={
                "ga_clicks": 0, "ga_impressions": 37,
                "stalled_bucket": "stalled", "stalled_cause": "zero_serve",
                "stalled_since": "2026-06-29", "stalled_streak": 2,
                "stalled_escalated": True,
            })],
        }, open(scores_path, "w"))
        json.dump({"to_enrich": [], "desc_only": []}, open(input_path, "w"))
        json.dump([], open(proposals_path, "w"))
        L.cmd_persist(scores_path, None, ledger_path, input_path, proposals_path, now_iso="2026-07-22")
        L.cmd_persist(scores_path, None, ledger_path, input_path, proposals_path, now_iso="2026-07-23")
        row = [json.loads(l) for l in open(ledger_path)][0]
        assert row["current"]["verdict"] == "INSUFFICIENT_DATA"  # verdict unchanged
        assert "channel infeasible" in row["current"]["why"]
        assert row["current"]["stalled_streak"] == 2
        assert row["current"]["ga_impressions"] == 37
        assert len(row["verdict_history"]) == 1  # constant why → dedup holds


def test_prepare_fetches_description_with_mocked_gh():
    with tempfile.TemporaryDirectory() as td:
        scores_path = os.path.join(td, "scores.json")
        ledger_path = os.path.join(td, "ledger.jsonl")
        config_path = os.path.join(td, "cfg.yaml")
        output_path = os.path.join(td, "input.json")
        json.dump({
            "thresholds": {"visitors_floor": 100},
            "mvps": [
                _score("alpha", "NO_GO", metrics={"ga_clicks": 200}),
                _score("beta", "NO_GO", metrics={"ga_clicks": 100}),
            ],
        }, open(scores_path, "w"))
        P.dump_yaml({"mvp_mappings": {}}, config_path)
        files = {("Alpha", "experiment/experiment.yaml"): "thesis: Alpha does X\ntarget_user: devs\n"}
        with patch.object(P, "_gh", _fake_gh(repos=("Alpha",), files=files)):
            L.cmd_prepare(scores_path, None, ledger_path, config_path, False, output_path)
        out = json.load(open(output_path))
        by = {e["mvp"]: e for e in out["to_enrich"]}
        assert by["alpha"]["parsed_desc"]["thesis"] == "Alpha does X"   # fetched + parsed
        assert by["beta"]["parsed_desc"] == {}                          # 404 → empty, no crash


if __name__ == "__main__":
    import inspect

    failed = passed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn) and not inspect.signature(fn).parameters:
            try:
                fn()
                print(f"PASS  {name}")
                passed += 1
            except Exception as e:  # noqa: BLE001
                print(f"FAIL  {name}: {e!r}")
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
