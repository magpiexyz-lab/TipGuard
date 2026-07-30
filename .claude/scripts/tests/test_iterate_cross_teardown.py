#!/usr/bin/env python3
"""Tests for .claude/scripts/lib/iterate_cross_teardown.py (state-x4b)."""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import iterate_cross_teardown as td  # noqa: E402


def _fake_probe_gone(name, timeout=8):
    return {"status": "surface_gone", "evidence": "probe: http 404 (weak edge evidence)"}


def _fake_probe_live(name, timeout=8):
    return {"status": "live", "evidence": "probe: http 200"}


def _cfg(**mappings):
    return {"mvp_mappings": mappings, "team_roster": {
        "lee": {"tg": "@Kol520"},
        "priyanshu": {"status": "departed"},
    }}


def _killed(name="dead", **kw):
    base = {"lifecycle_status": "killed", "lifecycle_status_at": "2026-07-01T00:00:00Z"}
    base.update(kw)
    return base


REF_NOW = "2026-07-21T00:00:00Z"


def test_closeout_rule_matrix():
    gone = {"status": td.DB_GONE}
    na = {"status": td.DB_NA}
    live = {"status": td.DB_LIVE}
    unverifiable = {"status": td.DB_UNVERIFIABLE}
    host_gone = {"status": "surface_gone"}
    host_live = {"status": "live"}
    ads_ok = {"status": "confirmed_paused"}
    ads_none = {"status": "none_in_window"}
    ads_unknown = {"status": "unknown"}

    assert td.closeout(gone, host_gone, ads_ok, waived=False) == "verified"
    assert td.closeout(na, host_gone, ads_none, waived=False) == "verified"
    # Any unmet line keeps it due — never auto-closes.
    assert td.closeout(live, host_gone, ads_ok, waived=False) == "due"
    assert td.closeout(gone, host_live, ads_ok, waived=False) == "due"
    assert td.closeout(gone, host_gone, ads_unknown, waived=False) == "due"
    # not_visible cannot verify.
    assert td.closeout(unverifiable, host_gone, ads_ok, waived=False) == "due"
    # Waiver wins over everything.
    assert td.closeout(live, host_live, ads_unknown, waived=True) == "waived"


def test_build_obligations_scope_owner_and_age():
    cfg = _cfg(
        dead=_killed(owner="lee", db_backend={"status": "deleted_verified"}),
        unowned=_killed(db_backend={"status": "deleted_verified"}),
        orphaned=_killed(owner="priyanshu", db_backend={"status": "alive"}),
        active_mvp={"lifecycle_status": "active"},
        __orphan_x__=_killed(),
    )
    obs = td.build_obligations(cfg, None, {}, REF_NOW, probe=_fake_probe_gone)
    names = [o["mvp"] for o in obs]
    assert names == ["dead", "orphaned", "unowned"]  # sorted; active + orphan excluded
    by = {o["mvp"]: o for o in obs}
    assert by["dead"]["owner"] == "lee"
    assert by["unowned"]["owner"] == "alan"      # unowned → operator
    assert by["orphaned"]["owner"] == "alan"     # departed → operator
    assert by["dead"]["killed_age_days"] == 20   # 07-01 → 07-21
    # No scores → ads none_in_window; db gone + host gone → verified.
    assert by["dead"]["teardown_state"] == "verified"
    # Backend alive → due regardless of other lines.
    assert by["orphaned"]["db"]["status"] == td.DB_LIVE
    assert by["orphaned"]["teardown_state"] == "due"


def test_waiver_and_missing_backend_record():
    cfg = _cfg(
        kept=_killed(db_backend={"status": "alive"},
                     backend_keep={"reason": "shared project"}),
        unknown=_killed(),  # no db_backend record at all
    )
    obs = {o["mvp"]: o for o in td.build_obligations(cfg, None, {}, REF_NOW, probe=_fake_probe_gone)}
    assert obs["kept"]["teardown_state"] == "waived"
    assert obs["unknown"]["db"]["status"] == td.DB_UNKNOWN
    assert obs["unknown"]["teardown_state"] == "due"


def test_ads_evidence_prefers_sticky_confirmation_then_campaigns():
    scores = {"mvps": [{"name": "m", "ga_campaigns": ["m-search-v1"]}]}
    by_name = {s["name"]: s for s in scores["mvps"]}
    # Sticky operator confirmation wins.
    row = {"teardown_evidence": {"ads": {"status": "confirmed_paused", "confirmed_at": "2026-07-20"}}}
    assert td.ads_evidence("m", by_name, row)["status"] == "confirmed_paused"
    # Campaigns in window without confirmation → unknown.
    assert td.ads_evidence("m", by_name, None)["status"] == "unknown"
    # No campaigns → auto-satisfied.
    assert td.ads_evidence("other", by_name, None)["status"] == "none_in_window"


def _ledger_file(rows):
    f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    for r in rows:
        f.write(json.dumps(r) + "\n")
    f.close()
    return f.name


def test_stamp_teardown_fields_without_unfreezing():
    path = _ledger_file([
        {"mvp": "dead", "archived_at": "2026-07-01", "current": {"verdict": "NO_GO"},
         "verdict_history": [], "what_it_does": {}, "tags": {}},
    ])
    try:
        obs = [{
            "mvp": "dead", "owner": "lee", "money_leak": False,
            "killed_at": "2026-07-01T00:00:00Z", "killed_age_days": 20,
            "db": {"status": td.DB_LIVE, "evidence": "e"},
            "hosting": {"status": "live", "evidence": "e"},
            "ads": {"status": "unknown", "evidence": "e"},
            "waived": False, "teardown_state": "due",
        }]
        r1 = td.stamp_teardown_fields(path, obs, "2026-07-21")
        r2 = td.stamp_teardown_fields(path, obs, "2026-07-28")
        rows = [json.loads(l) for l in open(path) if l.strip()]
        row = rows[0]
        assert r1["stamped"] == 1 and r2["stamped"] == 1
        assert row["teardown_state"] == "due"
        assert row["teardown_first_due_at"] == "2026-07-21"   # set once
        assert row["teardown_reminder_count"] == 2            # +1 per due run
        assert row["archived_at"] == "2026-07-01"             # frozen untouched
        assert row["current"] == {"verdict": "NO_GO"}
        # Verify transition: verified_at stamped once, counter stops.
        obs[0]["teardown_state"] = "verified"
        td.stamp_teardown_fields(path, obs, "2026-08-04")
        row = [json.loads(l) for l in open(path) if l.strip()][0]
        assert row["teardown_state"] == "verified"
        assert row["teardown_verified_at"] == "2026-08-04"
        assert row["teardown_reminder_count"] == 2
    finally:
        os.unlink(path)


def test_stamp_reports_missing_ledger_rows():
    path = _ledger_file([{"mvp": "other", "archived_at": None}])
    try:
        obs = [{
            "mvp": "ghost", "owner": "alan", "money_leak": False,
            "killed_at": None, "killed_age_days": None,
            "db": {"status": td.DB_NA, "evidence": "e"},
            "hosting": {"status": "surface_gone", "evidence": "e"},
            "ads": {"status": "none_in_window", "evidence": "e"},
            "waived": False, "teardown_state": "verified",
        }]
        result = td.stamp_teardown_fields(path, obs, "2026-07-21")
        assert result["missing_ledger_rows"] == ["ghost"]
    finally:
        os.unlink(path)


def test_confirm_ads_sticky_roundtrip():
    path = _ledger_file([{"mvp": "dead", "archived_at": "2026-07-01"}])
    try:
        assert td.confirm_ads_paused(path, "dead", "2026-07-21") is True
        assert td.confirm_ads_paused(path, "nope", "2026-07-21") is False
        row = [json.loads(l) for l in open(path) if l.strip()][0]
        assert row["teardown_evidence"]["ads"]["status"] == "confirmed_paused"
        # And ads_evidence consumes it.
        assert td.ads_evidence("dead", {}, row)["status"] == "confirmed_paused"
    finally:
        os.unlink(path)


def test_render_report_sections():
    obs = [
        {"mvp": "leaky", "owner": "lee", "money_leak": True, "killed_age_days": 3,
         "killed_at": "x", "db": {"status": td.DB_LIVE}, "hosting": {"status": "live"},
         "ads": {"status": "unknown"}, "waived": False, "teardown_state": "due"},
        {"mvp": "old", "owner": "alan", "money_leak": False, "killed_age_days": 30,
         "killed_at": "x", "db": {"status": td.DB_LIVE}, "hosting": {"status": "surface_gone"},
         "ads": {"status": "none_in_window"}, "waived": False, "teardown_state": "due"},
        {"mvp": "done", "owner": "lee", "money_leak": False, "killed_age_days": 30,
         "killed_at": "x", "db": {"status": td.DB_GONE}, "hosting": {"status": "surface_gone"},
         "ads": {"status": "none_in_window"}, "waived": False, "teardown_state": "verified"},
    ]
    report = td.render_report(obs)
    assert "🔥 MONEY_LEAK" in report and "leaky" in report
    assert "🚨 OVERDUE" in report and "old" in report
    assert "✅ VERIFIED" in report and "done" in report


def test_reconcile_end_to_end_with_injected_probe():
    with tempfile.TemporaryDirectory() as t:
        cfg_path = os.path.join(t, "cfg.yaml")
        ledger_path = os.path.join(t, "ledger.jsonl")
        out_path = os.path.join(t, "obligations.json")
        import yaml as _yaml
        with open(cfg_path, "w") as f:
            _yaml.safe_dump(_cfg(
                dead=_killed(owner="lee", db_backend={"status": "deleted_verified"}),
            ), f)
        with open(ledger_path, "w") as f:
            f.write(json.dumps({"mvp": "dead", "archived_at": "2026-07-01"}) + "\n")
        result = td.reconcile(
            cfg_path, None, ledger_path, out_path,
            reference_now=REF_NOW, probe=_fake_probe_gone,
        )
        assert result["counts"] == {"due": 0, "verified": 1, "waived": 0}
        assert os.path.exists(out_path)
        row = [json.loads(l) for l in open(ledger_path) if l.strip()][0]
        assert row["teardown_state"] == "verified"
        # Dry-run leaves everything untouched.
        result2 = td.reconcile(
            cfg_path, None, ledger_path, out_path + ".x",
            reference_now=REF_NOW, probe=_fake_probe_gone, dry_run=True,
        )
        assert result2["ledger"]["stamped"] == 0
        assert not os.path.exists(out_path + ".x")


# ---------- csv_paused (GA CSV status columns) + STILL_SERVING ----------

def _score_row(name, campaigns, detail, all_stopped):
    return {
        "name": name,
        "ga_campaigns": campaigns,
        "ga_campaign_status_detail": detail,
        "ga_ads_all_stopped": all_stopped,
    }


_STOPPED_DETAIL = [
    {"name": "m-search-v1", "campaign_status": "Paused",
     "serving_status": "Paused", "normalized": "stopped"},
]
_ACTIVE_DETAIL = [
    {"name": "m-search-v1", "campaign_status": "Enabled",
     "serving_status": "Eligible", "normalized": "active"},
]


def _write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f)


def test_closeout_accepts_csv_paused():
    gone = {"status": td.DB_GONE}
    host_gone = {"status": "surface_gone"}
    host_live = {"status": "live"}
    ads_csv = {"status": "csv_paused"}
    assert td.closeout(gone, host_gone, ads_csv, waived=False) == "verified"
    assert td.closeout(gone, host_live, ads_csv, waived=False) == "due"
    assert td.closeout({"status": td.DB_LIVE}, host_gone, ads_csv, waived=False) == "due"


def test_ads_evidence_csv_paused_matrix():
    by = {"m": _score_row("m", ["m-search-v1"], _STOPPED_DETAIL, True)}
    # Gate open → csv_paused; evidence carries per-campaign statuses.
    ev = td.ads_evidence("m", by, None, unmatched_active=0)
    assert ev["status"] == "csv_paused"
    assert "m-search-v1: Paused/Paused" in ev["evidence"]
    # An unattributable live campaign anywhere in the export → blocked.
    assert td.ads_evidence("m", by, None, unmatched_active=1)["status"] == "unknown"
    # No unmatched info (standalone run / old-format) → conservatively blocked.
    assert td.ads_evidence("m", by, None, unmatched_active=None)["status"] == "unknown"
    # all_stopped False (some campaign active/unknown) → never csv_paused.
    by_active = {"m": _score_row("m", ["m-search-v1"], _ACTIVE_DETAIL, False)}
    assert td.ads_evidence("m", by_active, None, unmatched_active=0)["status"] == "unknown"
    # Sticky operator confirmation still wins over CSV evidence.
    row = {"teardown_evidence": {"ads": {"status": "confirmed_paused", "confirmed_at": "2026-07-20"}}}
    assert td.ads_evidence("m", by, row, unmatched_active=0)["status"] == "confirmed_paused"


def test_ads_evidence_none_in_window_tightened_by_active_dropped_campaigns():
    # All campaigns left the analysis window (pre-relaunch drop) but one is
    # still deliverable per CSV → must NOT auto-close.
    by = {"m": _score_row("m", [], _ACTIVE_DETAIL, False)}
    ev = td.ads_evidence("m", by, None, unmatched_active=0)
    assert ev["status"] == "unknown"
    assert "still deliverable" in ev["evidence"]
    # Status columns absent: dropped rows normalize to unknown → close as
    # before this feature existed (back-compat).
    detail_unknown = [{"name": "m-search-v1", "campaign_status": None,
                       "serving_status": None, "normalized": "unknown"}]
    by2 = {"m": _score_row("m", [], detail_unknown, None)}
    assert td.ads_evidence("m", by2, None, unmatched_active=0)["status"] == "none_in_window"


def test_build_obligations_csv_paused_and_still_serving_including_waived():
    cfg = _cfg(
        stoppedone=_killed(owner="lee", db_backend={"status": "deleted_verified"}),
        burning=_killed(owner="lee", db_backend={"status": "deleted_verified"}),
        keptlive=_killed(owner="lee", db_backend={"status": "alive"},
                         backend_keep={"reason": "shared project"}),
    )
    scores = {"mvps": [
        _score_row("stoppedone", ["stoppedone-search-v1"], [
            {"name": "stoppedone-search-v1", "campaign_status": "Paused",
             "serving_status": "Paused", "normalized": "stopped"}], True),
        _score_row("burning", ["burning-search-v1"], [
            {"name": "burning-search-v1", "campaign_status": "Enabled",
             "serving_status": "Eligible", "normalized": "active"}], False),
        _score_row("keptlive", ["keptlive-search-v1"], [
            {"name": "keptlive-search-v1", "campaign_status": "Enabled",
             "serving_status": "Eligible", "normalized": "active"}], False),
    ]}
    obs = {o["mvp"]: o for o in td.build_obligations(
        cfg, scores, {}, REF_NOW, probe=_fake_probe_gone, unmatched_active=0)}
    assert obs["stoppedone"]["ads"]["status"] == "csv_paused"
    assert obs["stoppedone"]["ads"]["checked_at"] == REF_NOW
    assert obs["stoppedone"]["teardown_state"] == "verified"
    assert obs["stoppedone"]["still_serving"] == []
    assert obs["burning"]["ads"]["status"] == "unknown"
    assert obs["burning"]["teardown_state"] == "due"
    assert [c["name"] for c in obs["burning"]["still_serving"]] == ["burning-search-v1"]
    # Waived row: the teardown obligation is waived, but the live ad still
    # surfaces — backend_keep waives the backend, not the ads.
    assert obs["keptlive"]["teardown_state"] == "waived"
    assert [c["name"] for c in obs["keptlive"]["still_serving"]] == ["keptlive-search-v1"]


def test_render_report_still_serving_section_marks_waived():
    obs = [
        {"mvp": "burning", "owner": "lee", "money_leak": False, "killed_age_days": 3,
         "killed_at": "x", "db": {"status": td.DB_GONE}, "hosting": {"status": "surface_gone"},
         "ads": {"status": "unknown"},
         "still_serving": [{"name": "burning-search-v1", "campaign_status": "Enabled",
                            "serving_status": "Eligible"}],
         "waived": False, "teardown_state": "due"},
        {"mvp": "keptlive", "owner": "taran", "money_leak": False, "killed_age_days": 9,
         "killed_at": "x", "db": {"status": td.DB_LIVE}, "hosting": {"status": "live"},
         "ads": {"status": "unknown"},
         "still_serving": [{"name": "keptlive-search-v1", "campaign_status": "Enabled",
                            "serving_status": "Eligible"}],
         "waived": True, "teardown_state": "waived"},
    ]
    report = td.render_report(obs)
    assert "📣 STILL_SERVING" in report
    assert "burning — burning-search-v1 (Enabled/Eligible) → lee" in report
    assert "keptlive — keptlive-search-v1 (Enabled/Eligible) [backend_keep waived] → taran" in report


def test_reconcile_csv_paused_end_to_end_with_unmatched_gate():
    with tempfile.TemporaryDirectory() as t:
        cfg_path = os.path.join(t, "cfg.yaml")
        ledger_path = os.path.join(t, "ledger.jsonl")
        out_path = os.path.join(t, "obligations.json")
        scores_path = os.path.join(t, "scores.json")
        unmatched_path = os.path.join(t, "unmatched.json")
        import yaml as _yaml
        with open(cfg_path, "w") as f:
            _yaml.safe_dump(_cfg(
                dead=_killed(owner="lee", db_backend={"status": "deleted_verified"}),
            ), f)
        with open(ledger_path, "w") as f:
            f.write(json.dumps({"mvp": "dead", "archived_at": "2026-07-01"}) + "\n")
        _write_json(scores_path, {"mvps": [
            _score_row("dead", ["dead-search-v1"], [
                {"name": "dead-search-v1", "campaign_status": "Removed",
                 "serving_status": "Removed", "normalized": "stopped"}], True),
        ]})
        # New-format unmatched: a stopped placeholder counts 0; a pre-relaunch
        # active row is EXCLUDED (attributed to its own MVP) → gate passes.
        _write_json(unmatched_path, [
            {"name": "Campaign #1", "reason": "placeholder", "status_normalized": "stopped"},
            {"name": "old-search-v1", "reason": "pre-relaunch", "status_normalized": "active"},
        ])
        result = td.reconcile(
            cfg_path, scores_path, ledger_path, out_path,
            reference_now=REF_NOW, probe=_fake_probe_gone,
            unmatched_path=unmatched_path,
        )
        assert result["counts"] == {"due": 0, "verified": 1, "waived": 0}
        payload = json.load(open(out_path))
        assert payload["unmatched_active"] == 0
        assert payload["obligations"][0]["ads"]["status"] == "csv_paused"

        # Old-format entries (no status_normalized) → conservative block.
        _write_json(unmatched_path, [{"name": "Campaign #1", "reason": "placeholder"}])
        result2 = td.reconcile(
            cfg_path, scores_path, ledger_path, out_path + ".2",
            reference_now=REF_NOW, probe=_fake_probe_gone,
            unmatched_path=unmatched_path,
        )
        assert result2["counts"]["due"] == 1

        # Missing unmatched file → None gate → blocked as well.
        result3 = td.reconcile(
            cfg_path, scores_path, ledger_path, out_path + ".3",
            reference_now=REF_NOW, probe=_fake_probe_gone,
            unmatched_path=os.path.join(t, "nope.json"),
        )
        assert result3["counts"]["due"] == 1
        assert json.load(open(out_path + ".3"))["unmatched_active"] is None


def test_reconcile_flip_flop_verified_then_reenabled_goes_due_again():
    with tempfile.TemporaryDirectory() as t:
        cfg_path = os.path.join(t, "cfg.yaml")
        ledger_path = os.path.join(t, "ledger.jsonl")
        unmatched_path = os.path.join(t, "unmatched.json")
        import yaml as _yaml
        with open(cfg_path, "w") as f:
            _yaml.safe_dump(_cfg(
                dead=_killed(owner="lee", db_backend={"status": "deleted_verified"}),
            ), f)
        with open(ledger_path, "w") as f:
            f.write(json.dumps({"mvp": "dead", "archived_at": "2026-07-01"}) + "\n")
        _write_json(unmatched_path, [])
        s1 = os.path.join(t, "s1.json")
        _write_json(s1, {"mvps": [
            _score_row("dead", ["dead-search-v1"], [
                {"name": "dead-search-v1", "campaign_status": "Paused",
                 "serving_status": "Paused", "normalized": "stopped"}], True),
        ]})
        td.reconcile(cfg_path, s1, ledger_path, os.path.join(t, "o1.json"),
                     reference_now="2026-07-21T00:00:00Z", probe=_fake_probe_gone,
                     unmatched_path=unmatched_path)
        row = [json.loads(l) for l in open(ledger_path) if l.strip()][0]
        assert row["teardown_state"] == "verified"
        assert row["teardown_verified_at"] == "2026-07-21"
        assert "teardown_reminder_count" not in row

        # Operator re-enables the campaign → next export shows it active.
        s2 = os.path.join(t, "s2.json")
        _write_json(s2, {"mvps": [
            _score_row("dead", ["dead-search-v1"], [
                {"name": "dead-search-v1", "campaign_status": "Enabled",
                 "serving_status": "Eligible", "normalized": "active"}], False),
        ]})
        result = td.reconcile(cfg_path, s2, ledger_path, os.path.join(t, "o2.json"),
                              reference_now="2026-07-28T00:00:00Z", probe=_fake_probe_gone,
                              unmatched_path=unmatched_path)
        assert result["counts"]["due"] == 1
        row = [json.loads(l) for l in open(ledger_path) if l.strip()][0]
        assert row["teardown_state"] == "due"                # reopened honestly
        assert row["teardown_verified_at"] == "2026-07-21"   # set-once preserved
        assert row["teardown_first_due_at"] == "2026-07-28"
        assert row["teardown_reminder_count"] == 1           # reminders resume
        ob = json.load(open(os.path.join(t, "o2.json")))["obligations"][0]
        assert [c["name"] for c in ob["still_serving"]] == ["dead-search-v1"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
