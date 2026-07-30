#!/usr/bin/env python3
"""Tests for .claude/scripts/lib/iterate_cross_ga.py.

Run:
  python3 -m pytest .claude/scripts/tests/test_iterate_cross_ga.py -v
  # OR (no pytest dependency):
  python3 .claude/scripts/tests/test_iterate_cross_ga.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from iterate_cross_ga import (  # noqa: E402
    _load_owner_map,
    _read_csv_text,
    _sniff_delimiter,
    bucket_campaign,
    campaign_matches_phase_exclude,
    cmd_validate_csv,
    compute_foreign_campaign_flags,
    extract_mvp_name,
    is_placeholder_campaign,
    main,
    merge_ga_clicks,
    normalize_campaign_status,
    parse_ga_csv,
)


# ---------- extract_mvp_name (suffix stripping) ----------

def test_extract_strips_search_v1():
    assert extract_mvp_name("reset-app-search-v1") == "reset-app"


def test_extract_strips_underscored_search_v1():
    assert extract_mvp_name("CommissionIQ_Search_V1") == "CommissionIQ"


def test_extract_strips_validation_v1():
    assert extract_mvp_name("PubCheck_Search_Validation_V1") == "PubCheck"


def test_extract_strips_search_v2():
    assert extract_mvp_name("brigent-search-v2") == "brigent"


def test_extract_strips_v1_manual_suffix():
    assert extract_mvp_name("smelt-search-v1-manual") == "smelt"


def test_extract_strips_phase_search():
    assert extract_mvp_name("NeuralPost — Phase 1 — Search") == "NeuralPost"


def test_extract_strips_date_phase():
    assert extract_mvp_name("NeuralPost_5Day_Apr2026") == "NeuralPost"


def test_extract_strips_owner_suffix_lumen_parth():
    assert extract_mvp_name("Lumen-Parth") == "Lumen"


def test_extract_strips_owner_suffix_staylica_lew():
    assert extract_mvp_name("StaylicaAi-Lew") == "StaylicaAi"


def test_extract_strips_hashtag_number():
    assert extract_mvp_name("xpredict #2") == "xpredict"


def test_extract_handles_dubai_geo_suffix():
    assert extract_mvp_name("Handpick - Dubai Search") == "Handpick"


def test_extract_leaves_clean_names_alone():
    assert extract_mvp_name("flowops") == "flowops"
    assert extract_mvp_name("agent-cost-monitor") == "agent-cost-monitor"


def test_extract_strips_search_phase2_v1():
    """Phase 2 playbook naming: {mvp}-search-phase2-v{N} → {mvp}."""
    assert extract_mvp_name("reset-app-search-phase2-v1") == "reset-app"


# ---------- is_placeholder_campaign ----------

def test_placeholder_simple_form():
    assert is_placeholder_campaign("Campaign #1")
    assert is_placeholder_campaign("Campaign #42")
    assert is_placeholder_campaign("campaign 1")


def test_placeholder_with_owner_annotation():
    """`Campaign #1 (Parth)` — operator added a hint but never renamed."""
    assert is_placeholder_campaign("Campaign #1 (Parth)")
    assert is_placeholder_campaign("Campaign #1 (karan)")


def test_not_placeholder_real_name():
    assert not is_placeholder_campaign("xpredict")
    assert not is_placeholder_campaign("brigent-search-v2")


# ---------- bucket_campaign ----------

def test_bucket_substring_xpredict_to_x_predict():
    """match_key('xpredict') == match_key('x-predict') == 'xpredict' → substring match."""
    mvp, reason = bucket_campaign("xpredict", {"x-predict", "diarly", "lumen"})
    assert mvp == "x-predict"
    assert reason == "ph-substring"


def test_bucket_substring_with_numbered_variant():
    mvp, reason = bucket_campaign("xpredict #2", {"x-predict", "diarly"})
    assert mvp == "x-predict"
    assert reason == "ph-substring"


def test_bucket_substring_strips_search_v1():
    mvp, reason = bucket_campaign("brigent-search-v2", {"brigent", "diarly"})
    assert mvp == "brigent"
    assert reason == "ph-substring"


def test_bucket_substring_handles_compound_name():
    """rubber-duck-api-search-v1 → rubber-duck-api."""
    mvp, reason = bucket_campaign("rubber-duck-api-search-v1", {"rubber-duck-api", "x-predict"})
    assert mvp == "rubber-duck-api"
    assert reason == "ph-substring"


def test_bucket_substring_lumen_parth_to_lumen():
    mvp, reason = bucket_campaign("Lumen-Parth", {"lumen", "diarly"})
    assert mvp == "lumen"
    assert reason == "ph-substring"


def test_bucket_longest_match_wins():
    """When both 'agent' and 'agent-lens' exist, agent-lens (longer key) wins for agentlens-search-v1."""
    mvp, _ = bucket_campaign(
        "agent-lens-search-v1",
        {"agent", "agent-lens"},
    )
    assert mvp == "agent-lens"


def test_bucket_alias_for_typo():
    """StaylicaAi-Lew can't substring-match 'stylica-ai' (extra 'a'). Operator alias rescues."""
    aliases = {"staylicaai": "stylica-ai"}
    mvp, reason = bucket_campaign("StaylicaAi-Lew", {"stylica-ai", "diarly"}, aliases=aliases)
    assert mvp == "stylica-ai"
    assert reason == "alias"


def test_bucket_substring_strips_phase2_suffix():
    """A prefix-named Phase 2 campaign buckets to its project without an alias
    (the guarantee behind check 39's {mvp} == experiment name rule)."""
    mvp, reason = bucket_campaign("xpredict-search-phase2-v1", {"x-predict", "diarly"})
    assert mvp == "x-predict"
    assert reason == "ph-substring"


def test_bucket_alias_for_disjoint_naming():
    """PubCheck_Search_Validation_V1 maps to 'verify' by operator alias only."""
    aliases = {"pubcheck": "verify"}
    mvp, reason = bucket_campaign(
        "PubCheck_Search_Validation_V1",
        {"verify", "diarly"},
        aliases=aliases,
    )
    assert mvp == "verify"
    assert reason == "alias"


def test_bucket_ga_only_auto_creation():
    """reset-app-search-v1 with no matching MVP → auto-create 'reset-app' as ga_only."""
    mvp, reason = bucket_campaign("reset-app-search-v1", {"diarly", "lumen"})
    assert mvp == "reset-app"
    assert reason == "ga-only-auto"


def test_bucket_ga_only_underscored_form():
    mvp, reason = bucket_campaign("CommissionIQ_Search_V1", {"diarly"})
    assert mvp == "commissioniq"
    assert reason == "ga-only-auto"


def test_bucket_placeholder_returns_unmatched():
    mvp, reason = bucket_campaign("Campaign #1", {"diarly"})
    assert mvp is None
    assert reason == "placeholder"


def test_bucket_skips_orphan_keys():
    """__orphan_*__ MVP keys are excluded from substring matching."""
    mvp, _reason = bucket_campaign("xpredict", {"__orphan_x__", "diarly"})
    # Falls through to ga-only-auto since no real MVP key matched
    assert mvp == "xpredict"


# ---------- parse_ga_csv ----------

def test_parse_ga_csv_with_header():
    """Real Google Ads CSV header form."""
    csv_text = "Campaign,Clicks,Conversions\nxpredict,1082,94\nbrigent-search-v2,158,0\n"
    parsed = parse_ga_csv(csv_text)
    assert len(parsed) == 2
    assert parsed[0]["name"] == "xpredict"
    assert parsed[0]["clicks"] == 1082
    assert parsed[0]["conv"] == 94.0


def test_parse_ga_csv_without_header_returns_empty():
    """Header is REQUIRED — parser must find Campaign + Clicks columns by name."""
    csv_text = "xpredict,1082\nbrigent,158\n"
    parsed = parse_ga_csv(csv_text)
    # First row is treated as header; finds no 'campaign'/'clicks' substring → []
    assert parsed == []


def test_parse_ga_csv_with_account():
    csv_text = "campaign,clicks,conv,account\nxpredict,1082,94,Lee MVP\n"
    parsed = parse_ga_csv(csv_text)
    assert parsed[0]["account"] == "Lee MVP"


def test_parse_ga_csv_arbitrary_column_order():
    """Column ORDER does not matter — parser indexes by header substring."""
    csv_text = "Account,Clicks,Conversions,Campaign\nLee MVP,1082,94,xpredict\n"
    parsed = parse_ga_csv(csv_text)
    assert len(parsed) == 1
    assert parsed[0]["name"] == "xpredict"
    assert parsed[0]["clicks"] == 1082
    assert parsed[0]["conv"] == 94.0
    assert parsed[0]["account"] == "Lee MVP"


def test_parse_ga_csv_strips_thousands_separator():
    """Google Ads CSV exports use `1,082` formatting."""
    csv_text = 'Campaign,Clicks,Conversions\nxpredict,"1,082","94"\n'
    parsed = parse_ga_csv(csv_text)
    assert parsed[0]["clicks"] == 1082
    assert parsed[0]["conv"] == 94.0


def test_parse_ga_csv_strips_utf8_bom():
    """Google Ads CSV exports as UTF-8 with BOM."""
    csv_text = "﻿Campaign,Clicks\nxpredict,1082\n"
    parsed = parse_ga_csv(csv_text)
    assert len(parsed) == 1
    assert parsed[0]["name"] == "xpredict"


def test_parse_ga_csv_skips_summary_total_row():
    """Google Ads CSV exports include a summary footer row starting with 'Total:'."""
    csv_text = "Campaign,Clicks\nxpredict,1082\nbrigent,158\nTotal,1240\n"
    parsed = parse_ga_csv(csv_text)
    assert len(parsed) == 2
    assert {c["name"] for c in parsed} == {"xpredict", "brigent"}


def test_parse_ga_csv_accepts_conv_dot_alias():
    """Header `Conv.` (Google Ads abbreviation) is recognized as conversions column."""
    csv_text = "Campaign,Clicks,Conv.\nxpredict,1082,94\n"
    parsed = parse_ga_csv(csv_text)
    assert parsed[0]["conv"] == 94.0


def test_parse_ga_csv_missing_required_columns_returns_empty():
    csv_text = "Foo,Bar\nbaz,42\n"
    parsed = parse_ga_csv(csv_text)
    assert parsed == []


def test_parse_ga_csv_skips_google_ads_preamble_and_exact_campaign_column():
    csv_text = (
        "Campaign report\n"
        "All time\n"
        "\n"
        "Campaign status,Campaign,Clicks\n"
        "Enabled,xpredict,1082\n"
    )
    parsed = parse_ga_csv(csv_text)
    assert len(parsed) == 1
    assert parsed[0]["name"] == "xpredict"
    assert parsed[0]["clicks"] == 1082


# ---------- UTF-16 / TSV decoding + delimiter sniff (real Google Ads export) ----------

def test_sniff_delimiter_prefers_tab_for_tsv():
    """Google Ads TSV: tab-rich header wins even past delimiter-free preamble lines."""
    text = (
        "Campaign report\nAll time\n"
        "Campaign status\tCampaign\tClicks\nEnabled\txpredict\t1082\n"
    )
    assert _sniff_delimiter(text) == "\t"


def test_sniff_delimiter_prefers_comma_for_csv():
    assert _sniff_delimiter("Campaign,Clicks\nxpredict,1082\n") == ","


def test_parse_ga_csv_tab_delimited_with_preamble():
    """Google Ads default export is TAB-delimited with 2 preamble lines."""
    text = (
        "Campaign report\nAll time\n"
        "Campaign status\tCampaign\tClicks\n"
        "Enabled\txpredict\t1082\n"
        "Paused\tbrigent\t158\n"
    )
    parsed = parse_ga_csv(text)
    assert {c["name"] for c in parsed} == {"xpredict", "brigent"}
    assert {c["clicks"] for c in parsed} == {1082, 158}


def test_read_csv_text_decodes_utf16_le():
    """Google Ads exports are UTF-16 LE w/ BOM; _read_csv_text must decode them."""
    text = "Campaign status\tCampaign\tClicks\nEnabled\txpredict\t1082\n"
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as f:
        f.write(text.encode("utf-16"))  # encodes with the LE BOM
        path = f.name
    try:
        decoded = _read_csv_text(path)
        assert "xpredict" in decoded
        parsed = parse_ga_csv(decoded)
        assert parsed[0]["name"] == "xpredict"
        assert parsed[0]["clicks"] == 1082
    finally:
        os.unlink(path)


def test_validate_csv_accepts_utf16_tab_export():
    """End-to-end: real UTF-16 LE + TAB export validates without manual transcode."""
    text = (
        "Campaign report\nAll time\n"
        "Campaign status\tCampaign\tClicks\nEnabled\txpredict\t1082\n"
    )
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as f:
        f.write(text.encode("utf-16"))
        path = f.name
    try:
        assert cmd_validate_csv(_Args(ga_csv=path)) == 0
    finally:
        os.unlink(path)


def test_parse_ga_csv_skips_total_rows_with_dash_campaign_tsv():
    """'Total: Campaigns' rows put the marker in Campaign status; Campaign cell is '--'."""
    text = (
        "Campaign status\tCampaign\tClicks\n"
        "Enabled\txpredict\t1082\n"
        "Total: Campaigns\t--\t5054\n"
        "Total: Account\t--\t3645\n"
    )
    parsed = parse_ga_csv(text)
    assert [c["name"] for c in parsed] == ["xpredict"]
    assert sum(c["clicks"] for c in parsed) == 1082  # total rows excluded


def test_parse_ga_csv_skips_dash_total_rows_comma():
    """Same '--' total-row skip for comma exports."""
    text = "Campaign status,Campaign,Clicks\nEnabled,xpredict,1082\nTotal: Campaigns,--,5054\n"
    parsed = parse_ga_csv(text)
    assert [c["name"] for c in parsed] == ["xpredict"]


# ---------- merge_ga_clicks (end-to-end) ----------

def _mvp(name, gclid_visitors=0):
    return {
        "name": name,
        "gclid_visitors": gclid_visitors,
        "first_seen": "2026-02-01T00:00:00Z",
        "last_seen": "2026-05-01T00:00:00Z",
        "sample_utm_campaign": None,
        "owner": None,
        "deploy_domain": None,
        "phase_match": True,
        "orphan": False,
        "partial_tracking_pct": None,
    }


def test_merge_augments_existing_ph_mvp():
    mvps = [_mvp("x-predict", gclid_visitors=2545), _mvp("diarly", gclid_visitors=87)]
    campaigns = [
        {"name": "xpredict", "clicks": 1082, "conv": 94, "account": "Lee MVP"},
        {"name": "xpredict #2", "clicks": 973, "conv": 212, "account": "Lee MVP"},
        {"name": "diarly-search-v1", "clicks": 102, "conv": 0, "account": "Lew"},
    ]
    merged, unmatched = merge_ga_clicks(campaigns, mvps)
    by = {m["name"]: m for m in merged}
    assert by["x-predict"]["ga_clicks"] == 2055  # 1082 + 973
    assert by["x-predict"]["ga_conv"] == 306.0
    assert by["x-predict"]["ga_campaigns"] == sorted(["xpredict", "xpredict #2"])
    assert by["diarly"]["ga_clicks"] == 102
    assert unmatched == []


def test_merge_creates_ga_only_mvp():
    """reset-app-search-v1 → no PH MVP → creates 'reset-app' as ga_only."""
    mvps = [_mvp("diarly", gclid_visitors=87)]
    campaigns = [{"name": "reset-app-search-v1", "clicks": 58, "conv": 0, "account": "Radlin"}]
    merged, _ = merge_ga_clicks(campaigns, mvps)
    by = {m["name"]: m for m in merged}
    assert "reset-app" in by
    assert by["reset-app"]["ga_only"] is True
    assert by["reset-app"]["ga_clicks"] == 58
    assert by["reset-app"]["gclid_visitors"] == 0


def test_load_owner_map_reads_mvp_mappings():
    """_load_owner_map: truthy owners only; malformed rows and missing file → {}."""
    with tempfile.TemporaryDirectory() as td:
        cfg = os.path.join(td, "cfg.yaml")
        with open(cfg, "w") as f:
            f.write(
                "mvp_mappings:\n"
                "  reset-app:\n"
                "    owner: radlin\n"
                "  no-owner-row:\n"
                "    signup_events: []\n"
                "  null-owner:\n"
                "    owner: null\n"
                "  not-a-dict: 3\n"
            )
        assert _load_owner_map(cfg) == {"reset-app": "radlin"}
        assert _load_owner_map(os.path.join(td, "absent.yaml")) == {}
        assert _load_owner_map(None) == {}


def test_merge_ga_only_inherits_config_owner():
    """ga_only creation reads mvp_mappings owner (reset-app @unassigned bug)."""
    mvps = [_mvp("diarly", gclid_visitors=87)]
    campaigns = [{"name": "reset-app-search-v1", "clicks": 58, "conv": 0, "account": "Radlin"}]
    merged, _ = merge_ga_clicks(campaigns, mvps, owner_by_mvp={"reset-app": "radlin"})
    by = {m["name"]: m for m in merged}
    assert by["reset-app"]["ga_only"] is True
    assert by["reset-app"]["owner"] == "radlin"


def test_merge_ga_only_owner_none_without_map():
    """No owner_by_mvp (legacy callers) → ga_only owner stays None."""
    mvps = []
    campaigns = [{"name": "reset-app-search-v1", "clicks": 58, "conv": 0, "account": "Radlin"}]
    merged, _ = merge_ga_clicks(campaigns, mvps)
    assert merged[0]["owner"] is None


def test_merge_ga_only_unmapped_name_owner_none():
    """owner_by_mvp present but MVP not in it → owner None (no misattribution)."""
    mvps = []
    campaigns = [{"name": "echo-search-v1", "clicks": 21, "conv": 0, "account": "Ops"}]
    merged, _ = merge_ga_clicks(campaigns, mvps, owner_by_mvp={"reset-app": "radlin"})
    assert merged[0]["name"] == "echo"
    assert merged[0]["owner"] is None


def test_merge_handles_unmatched_placeholder():
    mvps = [_mvp("diarly", gclid_visitors=87)]
    campaigns = [{"name": "Campaign #1", "clicks": 21, "conv": 0, "account": "karan"}]
    _, unmatched = merge_ga_clicks(campaigns, mvps)
    assert len(unmatched) == 1
    assert unmatched[0]["reason"] == "placeholder"


def test_merge_uses_alias_map():
    mvps = [_mvp("verify"), _mvp("diarly")]
    campaigns = [{"name": "PubCheck_Search_Validation_V1", "clicks": 154, "conv": 0, "account": "Radlin"}]
    aliases = {"pubcheck": "verify"}
    merged, unmatched = merge_ga_clicks(campaigns, mvps, aliases=aliases)
    by = {m["name"]: m for m in merged}
    assert by["verify"]["ga_clicks"] == 154
    assert unmatched == []


def test_merge_idempotent_on_rerun():
    """Re-applying with the same input → same ga_clicks (not double-counted)."""
    mvps = [_mvp("x-predict", gclid_visitors=2545)]
    campaigns = [{"name": "xpredict", "clicks": 1082, "conv": 0, "account": "Lee MVP"}]
    merged1, _ = merge_ga_clicks(campaigns, mvps)
    merged2, _ = merge_ga_clicks(campaigns, merged1)
    assert merged2[0]["ga_clicks"] == 1082
    # Even when ga_clicks was already 1082, second pass overwrites cleanly


def test_merge_zero_click_campaigns_are_dropped_when_ga_only():
    """A ga-only auto-creation should not happen for a 0-click campaign."""
    mvps = []
    campaigns = [{"name": "suits-parth", "clicks": 0, "conv": 0, "account": "Parth"}]
    merged, _ = merge_ga_clicks(campaigns, mvps)
    assert merged == []


def test_merge_existing_mvp_with_zero_clicks_keeps_ga_clicks_zero():
    """If the operator has an MVP but no GA campaign clicks, ga_clicks stays 0."""
    mvps = [_mvp("ghostops", gclid_visitors=2)]
    campaigns = []
    merged, _ = merge_ga_clicks(campaigns, mvps)
    assert merged[0]["ga_clicks"] == 0


def test_merge_silent_skip_path_zeros_every_record():
    """Critical fallback path: with NO campaigns at all (Chrome MCP unavailable +
    no CSV), every existing MVP must still get ga_clicks=0 so the x0a VERIFY
    assertion (`ga_clicks in m`) passes. Without this, the silent-skip path
    would break the state machine.
    """
    mvps = [
        _mvp("x-predict", gclid_visitors=2545),
        _mvp("diarly", gclid_visitors=87),
        _mvp("__orphan_hospitica__", gclid_visitors=38),
    ]
    merged, unmatched = merge_ga_clicks([], mvps)
    # Every record has ga_clicks=0
    for m in merged:
        assert "ga_clicks" in m, f"{m['name']} missing ga_clicks"
        assert m["ga_clicks"] == 0
    # No new ga_only records added
    assert all(not m.get("ga_only") for m in merged)
    assert unmatched == []


def test_merge_silent_skip_does_not_clobber_other_fields():
    """Silent-skip must not erase pre-existing fields like gclid_visitors,
    partial_tracking_pct, or owner."""
    mvps = [{
        "name": "x-predict",
        "gclid_visitors": 2545,
        "owner": "lee",
        "partial_tracking_pct": 0.14,
        "first_seen": "2026-02-01T00:00:00Z",
        "last_seen": "2026-05-01T00:00:00Z",
    }]
    merged, _ = merge_ga_clicks([], mvps)
    assert merged[0]["gclid_visitors"] == 2545
    assert merged[0]["owner"] == "lee"
    assert merged[0]["partial_tracking_pct"] == 0.14


# ---------- merge edge cases ----------

def test_merge_attributes_ga_to_orphan_record_not_separate_ga_only():
    """When GA campaign name matches an existing __orphan_X__ record, attribute
    clicks to the orphan (not a new ga_only). Orphan = PH partial-tracking;
    ga_only = PH zero presence. The former is stricter PH presence.

    Real case: PostHog has `__orphan_hospitica__` (38 visitors with NULL
    project_name). Google Ads has `Hospitica-search-v2` (95 clicks). Merge
    must augment the orphan record, not create both rows.
    """
    mvps = [
        _mvp("diarly"),
        {
            "name": "__orphan_hospitica__",
            "gclid_visitors": 38,
            "first_seen": "2026-04-01T00:00:00Z",
            "last_seen": "2026-05-01T00:00:00Z",
            "orphan": True,
        },
    ]
    campaigns = [{"name": "Hospitica-search-v2", "clicks": 95, "conv": 0, "account": "Lew"}]
    merged, _ = merge_ga_clicks(campaigns, mvps)
    # No ga_only "hospitica" record created — clicks absorbed by orphan.
    by = {m["name"]: m for m in merged}
    assert "hospitica" not in by
    assert by["__orphan_hospitica__"]["ga_clicks"] == 95


def test_merge_alias_routes_autodropship_to_dropship_ops():
    """autodropship-search-v1 → dropship-ops via operator alias (no substring match)."""
    mvps = [_mvp("dropship-ops")]
    campaigns = [{"name": "autodropship-search-v1", "clicks": 35, "conv": 5, "account": "Lee"}]
    aliases = {"autodropship": "dropship-ops"}
    merged, _ = merge_ga_clicks(campaigns, mvps, aliases=aliases)
    by = {m["name"]: m for m in merged}
    assert by["dropship-ops"]["ga_clicks"] == 35
    assert "autodropship" not in by


def test_merge_full_experiment_data_shape_smoke():
    """Smoke test mirroring the operator-validated experiment.

    Covers: PH-substring match, alias, ga_only auto-create, placeholder skip,
    multi-campaign accumulation, idempotent suffix stripping.
    """
    mvps = [
        _mvp("x-predict", gclid_visitors=2545),
        _mvp("stylica-ai", gclid_visitors=201),
        _mvp("verify", gclid_visitors=102),
        _mvp("diarly", gclid_visitors=87),
    ]
    campaigns = [
        {"name": "xpredict", "clicks": 1082, "conv": 94, "account": "Lee MVP"},
        {"name": "xpredict #2", "clicks": 973, "conv": 212, "account": "Lee MVP"},
        {"name": "StaylicaAi-Lew", "clicks": 575, "conv": 0, "account": "Lew"},
        {"name": "verify-search-v1", "clicks": 106, "conv": 0, "account": "Lego"},
        {"name": "PubCheck_Search_Validation_V1", "clicks": 154, "conv": 0, "account": "Radlin"},
        {"name": "diarly-search-v1", "clicks": 102, "conv": 0, "account": "Lew"},
        {"name": "reset-app-search-v1", "clicks": 58, "conv": 0, "account": "Radlin"},
        {"name": "CommissionIQ_Search_V1", "clicks": 40, "conv": 0, "account": "Radlin"},
        {"name": "sdr-copilot-search-v1", "clicks": 27, "conv": 0, "account": "Radlin"},
        {"name": "Campaign #1", "clicks": 6, "conv": 0, "account": "Taran"},
    ]
    aliases = {"staylicaai": "stylica-ai", "pubcheck": "verify"}
    merged, unmatched = merge_ga_clicks(campaigns, mvps, aliases=aliases)
    by = {m["name"]: m for m in merged}

    assert by["x-predict"]["ga_clicks"] == 2055
    assert by["stylica-ai"]["ga_clicks"] == 575
    assert by["verify"]["ga_clicks"] == 260  # 106 (verify-search-v1) + 154 (PubCheck via alias)
    assert by["diarly"]["ga_clicks"] == 102
    assert by["reset-app"]["ga_only"] is True
    assert by["commissioniq"]["ga_only"] is True
    assert by["sdr-copilot"]["ga_only"] is True
    assert len(unmatched) == 1
    assert unmatched[0]["reason"] == "placeholder"


# ---------- validate-csv subcommand ----------

class _Args:
    """Minimal argparse.Namespace stand-in for direct cmd_validate_csv calls."""
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def test_validate_csv_missing_file_exits_nonzero(tmp_path=None):
    args = _Args(ga_csv=str(tempfile.mktemp(suffix=".csv")))
    assert cmd_validate_csv(args) == 2


def test_validate_csv_missing_required_columns_exits_nonzero():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("Foo,Bar\nbaz,42\n")
        path = f.name
    try:
        rc = cmd_validate_csv(_Args(ga_csv=path))
        assert rc == 2
    finally:
        os.unlink(path)


def test_validate_csv_accepts_valid_export():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("Campaign,Account,Clicks,Conversions\nxpredict,Lee MVP,1082,94\n")
        path = f.name
    try:
        rc = cmd_validate_csv(_Args(ga_csv=path))
        assert rc == 0
    finally:
        os.unlink(path)


def test_validate_csv_accepts_header_only_with_warning():
    """Legitimate case: date window had zero paid clicks. Soft-warn, exit 0."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("Campaign,Clicks\n")
        path = f.name
    try:
        rc = cmd_validate_csv(_Args(ga_csv=path))
        assert rc == 0
    finally:
        os.unlink(path)


def test_validate_csv_rejects_header_only_when_context_has_gclid_traffic():
    with tempfile.TemporaryDirectory() as td:
        csv_path = os.path.join(td, "ga.csv")
        ctx_path = os.path.join(td, "ctx.json")
        open(csv_path, "w").write("Campaign,Clicks\n")
        json.dump({"mvps": [{"name": "x", "gclid_visitors": 1}]}, open(ctx_path, "w"))
        rc = cmd_validate_csv(_Args(ga_csv=csv_path, context=ctx_path))
        assert rc == 2


def test_validate_csv_accepts_zero_rows_after_phase_filter_with_context_traffic():
    """Phase 2 validation scopes zero matching campaigns to 0 clicks, not invalid CSV."""
    with tempfile.TemporaryDirectory() as td:
        csv_path = os.path.join(td, "ga.csv")
        ctx_path = os.path.join(td, "ctx.json")
        open(csv_path, "w").write("Campaign,Clicks\nxpredict-search-v1,1082\n")
        json.dump({"mvps": [{"name": "x-predict", "gclid_visitors": 9}]}, open(ctx_path, "w"))
        rc = cmd_validate_csv(_Args(ga_csv=csv_path, context=ctx_path, phase_filter="%phase2%"))
        assert rc == 0


def test_validate_csv_handles_bom():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write("﻿Campaign,Clicks\nxpredict,1082\n")
        path = f.name
    try:
        rc = cmd_validate_csv(_Args(ga_csv=path))
        assert rc == 0
    finally:
        os.unlink(path)


# ---------- main() integration ----------

def test_main_merge_subcommand_smoke():
    with tempfile.TemporaryDirectory() as td:
        ga_csv_path = os.path.join(td, "ga-clicks.csv")
        ctx_path = os.path.join(td, "context.json")
        unmatched_path = os.path.join(td, "unmatched.json")

        with open(ga_csv_path, "w", encoding="utf-8") as f:
            f.write("Campaign,Clicks,Conversions,Account\n")
            f.write("xpredict,1082,94,Lee MVP\n")
            f.write("reset-app-search-v1,58,0,Radlin\n")

        json.dump({
            "mvps": [_mvp("x-predict", gclid_visitors=2545)],
            "mode": "cross",
            "window_days": 90,
        }, open(ctx_path, "w"))

        rc = main([
            "merge",
            "--ga-csv", ga_csv_path,
            "--context", ctx_path,
            "--config", os.path.join(td, "no-such-config.yaml"),
            "--unmatched-out", unmatched_path,
        ])
        assert rc == 0

        result = json.load(open(ctx_path))
        by = {m["name"]: m for m in result["mvps"]}
        assert by["x-predict"]["ga_clicks"] == 1082
        assert "reset-app" in by  # ga_only auto-created
        assert by["reset-app"]["ga_only"] is True


def test_main_merge_phase_filter_only_merges_matching_campaigns():
    with tempfile.TemporaryDirectory() as td:
        ga_csv_path = os.path.join(td, "ga-clicks.csv")
        ctx_path = os.path.join(td, "context.json")
        unmatched_path = os.path.join(td, "unmatched.json")

        with open(ga_csv_path, "w", encoding="utf-8") as f:
            f.write("Campaign,Clicks,Conversions,Account\n")
            f.write("xpredict-search-v1,1082,94,Lee MVP\n")
            f.write("xpredict-search-phase2-v1,40,0,Lee MVP\n")

        json.dump({
            "mvps": [_mvp("x-predict", gclid_visitors=12)],
            "mode": "cross-phase2",
            "window_days": 90,
        }, open(ctx_path, "w"))

        rc = main([
            "merge",
            "--ga-csv", ga_csv_path,
            "--context", ctx_path,
            "--config", os.path.join(td, "no-such-config.yaml"),
            "--unmatched-out", unmatched_path,
            "--phase-filter", "%phase2%",
        ])
        assert rc == 0

        result = json.load(open(ctx_path))
        by = {m["name"]: m for m in result["mvps"]}
        assert by["x-predict"]["ga_clicks"] == 40
        assert by["x-predict"]["ga_campaigns"] == ["xpredict-search-phase2-v1"]


def test_main_validate_csv_subcommand_smoke():
    with tempfile.TemporaryDirectory() as td:
        ga_csv_path = os.path.join(td, "ga.csv")
        with open(ga_csv_path, "w", encoding="utf-8") as f:
            f.write("Campaign,Clicks\nxpredict,1082\n")
        rc = main(["validate-csv", "--ga-csv", ga_csv_path])
        assert rc == 0

        # Now break the CSV — missing Clicks column
        with open(ga_csv_path, "w", encoding="utf-8") as f:
            f.write("Campaign,Account\nxpredict,Lee\n")
        rc = main(["validate-csv", "--ga-csv", ga_csv_path])
        assert rc == 2


# ---------- CPC discipline: Cost / Currency / Start date ingest ----------

def test_parse_ga_csv_cost_currency_start():
    csv = ("Campaign,Clicks,Cost,Currency code,Start date,Account\n"
           "foo-search,12,109.03,SGD,2026-05-01,Acct\n")
    r = parse_ga_csv(csv)[0]
    assert r["cost"] == 109.03
    assert r["currency"] == "SGD"
    assert r["start_date"] == "2026-05-01"


def test_parse_ga_csv_cost_absent_is_none():
    # No Cost/Currency/Start columns → cost is None (not 0.0) so ga_cpc stays None.
    r = parse_ga_csv("Campaign,Clicks\nfoo,12\n")[0]
    assert r["cost"] is None
    assert r["currency"] == ""
    assert r["start_date"] == ""


def test_parse_ga_csv_cost_thousands_separator():
    r = parse_ga_csv('Campaign,Clicks,Cost\nfoo,"1,000","1,234.50"\n')[0]
    assert r["cost"] == 1234.50


def test_merge_computes_cpc_and_first_date():
    camps = [
        {"name": "foo-search", "clicks": 10, "conv": 0.0, "cost": 50.0,
         "currency": "USD", "start_date": "2026-05-10"},
        {"name": "foo-brand", "clicks": 10, "conv": 0.0, "cost": 30.0,
         "currency": "USD", "start_date": "2026-05-01"},
    ]
    merged, _ = merge_ga_clicks(camps, [{"name": "foo"}])
    m = merged[0]
    assert m["ga_clicks"] == 20
    assert m["ga_cost"] == 80.0
    assert m["ga_cpc"] == 4.0                        # 80 / 20
    assert m["campaign_first_date"] == "2026-05-01"  # earliest start
    assert m["ga_currency"] == "USD"


def test_merge_cost_absent_leaves_cpc_none():
    camps = [{"name": "foo-search", "clicks": 10, "conv": 0.0,
              "cost": None, "currency": "", "start_date": ""}]
    merged, _ = merge_ga_clicks(camps, [{"name": "foo"}])
    m = merged[0]
    assert m["ga_clicks"] == 10
    assert m["ga_cost"] is None
    assert m["ga_cpc"] is None
    assert m["campaign_first_date"] is None


def test_merge_ga_only_carries_cpc():
    camps = [{"name": "ghost-search", "clicks": 8, "conv": 0.0, "cost": 40.0,
              "currency": "SGD", "start_date": "2026-06-01"}]
    merged, _ = merge_ga_clicks(camps, [])  # no PH record → ga_only synthetic
    ghost = [m for m in merged if m.get("ga_only")][0]
    assert ghost["ga_cpc"] == 5.0
    assert ghost["ga_currency"] == "SGD"
    assert ghost["campaign_first_date"] == "2026-06-01"


# ---------- Impressions ingest (stalled-cause diagnosis) ----------

def test_parse_ga_csv_impressions_column():
    csv = ('Campaign,Clicks,Impr.\n'
           'foo-search,12,"4,210"\n')
    r = parse_ga_csv(csv)[0]
    assert r["impressions"] == 4210


def test_parse_ga_csv_impressions_absent_is_none():
    # No Impr. column → None (not 0) so downstream reads no_telemetry, not zero.
    r = parse_ga_csv("Campaign,Clicks\nfoo,12\n")[0]
    assert r["impressions"] is None


def test_parse_ga_csv_impressions_pct_column_ignored():
    # Only the percentage variant present → a rate, not a count → must not bind.
    r = parse_ga_csv("Campaign,Clicks,Impr. (Top) %\nfoo,12,85.5%\n")[0]
    assert r["impressions"] is None


def test_parse_ga_csv_impressions_count_wins_over_pct():
    csv = "Campaign,Clicks,Impr.,Impr. (Top) %\nfoo,12,900,85.5%\n"
    r = parse_ga_csv(csv)[0]
    assert r["impressions"] == 900


def test_merge_sums_impressions():
    camps = [
        {"name": "foo-search", "clicks": 10, "conv": 0.0, "cost": None,
         "currency": "", "start_date": "", "impressions": 1200},
        {"name": "foo-brand", "clicks": 5, "conv": 0.0, "cost": None,
         "currency": "", "start_date": "", "impressions": 300},
    ]
    merged, _ = merge_ga_clicks(camps, [{"name": "foo"}])
    assert merged[0]["ga_impressions"] == 1500


def test_merge_impressions_absent_leaves_none():
    # Campaign dicts without the key (old parses / no Impr. column) → None.
    camps = [{"name": "foo-search", "clicks": 10, "conv": 0.0, "cost": None,
              "currency": "", "start_date": ""}]
    merged, _ = merge_ga_clicks(camps, [{"name": "foo"}])
    assert merged[0]["ga_impressions"] is None


def test_merge_ga_only_carries_impressions():
    camps = [{"name": "ghost-search", "clicks": 8, "conv": 0.0, "cost": None,
              "currency": "", "start_date": "", "impressions": 640}]
    merged, _ = merge_ga_clicks(camps, [])
    ghost = [m for m in merged if m.get("ga_only")][0]
    assert ghost["ga_impressions"] == 640


def test_merge_zero_click_known_mvp_keeps_impressions():
    # The bid-capped shortfall shape: matched campaign, 0 clicks, impressions
    # present-but-tiny. The record must show 0 clicks + real impressions.
    camps = [{"name": "scangap-search-v1", "clicks": 0, "conv": 0.0, "cost": 0.0,
              "currency": "USD", "start_date": "2026-06-29", "impressions": 37}]
    merged, _ = merge_ga_clicks(camps, [_mvp("scangap")])
    m = [r for r in merged if r["name"] == "scangap"][0]
    assert m["ga_clicks"] == 0
    assert m["ga_impressions"] == 37


# Self-runner so this file works without pytest installed.


# ---------- compute_foreign_campaign_flags (B3) ----------

def _fc_mvps():
    return [
        {"name": "handpick"},
        {"name": "stylica-ai"},
        {"name": "neuralpost"},
        {"name": "__orphan_neuralpost__", "orphan": True},
    ]


def _fc_rows():
    return [
        ["handpick", "handpick-search-phase2-v1", 197],
        ["stylica-ai", "handpick-search-phase2-v1", 3],
        ["neuralpost", "neuralpost-search-phase2-v1", 63],
    ]


def test_foreign_campaign_flags_two_sided_high_for_payer_info_for_receiver():
    flags, audit = compute_foreign_campaign_flags(_fc_rows(), _fc_mvps())
    assert [f["severity"] for f in flags["handpick"]] == ["high"]
    assert [f["severity"] for f in flags["stylica-ai"]] == ["info"]
    assert "neuralpost" not in flags
    payer_msg = flags["handpick"][0]["message"]
    assert "handpick-search-phase2-v1" in payer_msg
    assert "stylica-ai" in payer_msg
    assert "Final URL" in payer_msg
    assert [a for a in audit if a["action"] == "flagged"][0]["visitors"] == 3


def test_foreign_campaign_own_campaign_matchkey_variants_not_flagged():
    rows = [["x-predict", "XPredict-Search-V1", 10]]
    flags, audit = compute_foreign_campaign_flags(rows, [{"name": "x-predict"}])
    assert flags == {}
    assert not [a for a in audit if a["action"] == "flagged"]


def test_foreign_campaign_unknown_ga_only_auto_owner_skipped():
    rows = [["handpick", "mysteryproduct-search-v1", 4]]
    flags, audit = compute_foreign_campaign_flags(rows, _fc_mvps())
    assert flags == {}
    assert any(a["action"] == "skipped-unknown-owner" for a in audit)


def test_foreign_campaign_whitelist_exempts_by_campaign_mvp_or_receiver():
    for wl in (["handpick-search-phase2-v1"], ["handpick"], ["stylica-ai"]):
        flags, audit = compute_foreign_campaign_flags(_fc_rows(), _fc_mvps(), whitelist=wl)
        assert flags == {}, wl
        assert any(a["action"] == "whitelisted" for a in audit), wl


def test_foreign_campaign_aggregates_multiple_campaigns_per_pair():
    rows = _fc_rows() + [["stylica-ai", "handpick-display-phase2-v1", 2]]
    flags, _ = compute_foreign_campaign_flags(rows, _fc_mvps())
    assert len(flags["handpick"]) == 1  # one aggregated flag per (payer, receiver)
    msg = flags["handpick"][0]["message"]
    assert "5 phase-scoped paid visitor(s)" in msg
    assert "handpick-display-phase2-v1" in msg and "handpick-search-phase2-v1" in msg


def test_foreign_campaign_orphan_receiver_and_alias_resolution():
    # orphan receiver -> audit only; alias maps an otherwise-unknown campaign to a payer
    rows = [
        ["__orphan_neuralpost__", "handpick-search-phase2-v1", 2],
        ["stylica-ai", "staylicaai-search-v9", 1],  # alias typo campaign, resolves to stylica-ai itself
        ["neuralpost", "staylicaai-search-v9", 4],  # same alias, foreign receiver
    ]
    aliases = {"staylicaaisearchv9": "stylica-ai"}
    flags, audit = compute_foreign_campaign_flags(rows, _fc_mvps(), aliases=aliases)
    assert any(a["action"] == "skipped-orphan-or-unknown-receiver" for a in audit)
    assert "stylica-ai" in flags  # payer via alias
    assert any(f["severity"] == "high" for f in flags["stylica-ai"])
    assert any(f["severity"] == "info" for f in flags["neuralpost"])


# ---------- Phase-2 exclude split (x0a Phase-1 denominator scoping) ----------

def _handpick_campaigns():
    """handpick's real 2026-07 shape: one untagged Phase-1 flight + one phase2 flight."""
    return [
        {"name": "Handpick - Dubai Search", "account": "Lew", "type": None,
         "clicks": 113, "conv": 0.0, "cost": 45.2, "currency": "USD",
         "start_date": "2026-05-01"},
        {"name": "handpick-search-phase2-v1", "account": "Lew", "type": None,
         "clicks": 258, "conv": 0.0, "cost": 103.2, "currency": "USD",
         "start_date": "2026-06-16"},
    ]


def test_exclude_matcher_empty_pattern_matches_nothing():
    # EXCLUDE inverts the include helper's empty-pattern default: empty/None/blank
    # must exclude NOTHING (the include helper returns True for empty patterns —
    # reusing it would zero the Phase-1 denominator fleet-wide).
    assert campaign_matches_phase_exclude("anything-phase2-v1", None) is False
    assert campaign_matches_phase_exclude("anything-phase2-v1", "") is False
    assert campaign_matches_phase_exclude("anything-phase2-v1", "   ") is False
    assert campaign_matches_phase_exclude("anything-phase2-v1", "%phase2%") is True
    assert campaign_matches_phase_exclude("plain-search-v1", "%phase2%") is False


def test_merge_phase_exclude_splits_clicks_cost_and_campaigns():
    merged, unmatched = merge_ga_clicks(
        _handpick_campaigns(), [_mvp("handpick", gclid_visitors=311)], {},
        phase_exclude="%phase2%",
    )
    assert unmatched == []
    h = {m["name"]: m for m in merged}["handpick"]
    assert h["ga_clicks"] == 371  # blended stays the full paid picture
    assert h["ga_clicks_phase2"] == 258
    assert h["ga_campaigns_phase2"] == ["handpick-search-phase2-v1"]
    assert h["ga_cost_phase2"] == 103.2
    assert h["ga_cost"] == 148.4
    assert sorted(h["ga_campaigns"]) == ["Handpick - Dubai Search", "handpick-search-phase2-v1"]


def test_merge_phase_exclude_exempt_name_never_counts_as_phase2():
    merged, _ = merge_ga_clicks(
        _handpick_campaigns(), [_mvp("handpick")], {},
        phase_exclude="%phase2%",
        phase_exclude_exempt=["handpick-search-phase2-v1"],
    )
    h = {m["name"]: m for m in merged}["handpick"]
    assert h["ga_clicks"] == 371
    assert h["ga_clicks_phase2"] == 0
    assert h["ga_campaigns_phase2"] == []
    assert h["ga_cost_phase2"] is None


def test_merge_phase_exclude_exempt_unknown_name_is_noop():
    merged, _ = merge_ga_clicks(
        _handpick_campaigns(), [_mvp("handpick")], {},
        phase_exclude="%phase2%",
        phase_exclude_exempt=["no-such-campaign"],
    )
    h = {m["name"]: m for m in merged}["handpick"]
    assert h["ga_clicks_phase2"] == 258


def test_merge_empty_phase_exclude_is_identical_to_none():
    base, _ = merge_ga_clicks(_handpick_campaigns(), [_mvp("handpick")], {})
    empty, _ = merge_ga_clicks(_handpick_campaigns(), [_mvp("handpick")], {}, phase_exclude="")
    b = {m["name"]: m for m in base}["handpick"]
    e = {m["name"]: m for m in empty}["handpick"]
    assert b == e
    assert e["ga_clicks_phase2"] == 0
    assert e["ga_cost_phase2"] is None


def test_merge_phase_exclude_cost_only_on_phase2_rows():
    campaigns = [
        {"name": "alpha-search-v1", "account": None, "type": None,
         "clicks": 50, "conv": 0.0, "cost": None, "currency": None, "start_date": None},
        {"name": "alpha-search-phase2-v1", "account": None, "type": None,
         "clicks": 30, "conv": 0.0, "cost": 60.0, "currency": "USD", "start_date": None},
    ]
    merged, _ = merge_ga_clicks(campaigns, [_mvp("alpha")], {}, phase_exclude="%phase2%")
    a = {m["name"]: m for m in merged}["alpha"]
    assert a["ga_clicks_phase2"] == 30
    assert a["ga_cost_phase2"] == 60.0
    assert a["ga_cost"] == 60.0  # blended cost = the only cost present


def test_merge_ga_only_record_carries_phase2_split():
    campaigns = [
        {"name": "ghost-search-phase2-v1", "account": None, "type": None,
         "clicks": 40, "conv": 0.0, "cost": None, "currency": None, "start_date": None},
    ]
    merged, _ = merge_ga_clicks(campaigns, [], {}, phase_exclude="%phase2%")
    g = {m["name"]: m for m in merged}["ghost"]
    assert g["ga_only"] is True
    assert g["ga_clicks"] == 40
    assert g["ga_clicks_phase2"] == 40
    assert g["ga_campaigns_phase2"] == ["ghost-search-phase2-v1"]


def test_merge_phase_exclude_idempotent_on_rerun():
    mvps = [_mvp("handpick")]
    merged1, _ = merge_ga_clicks(_handpick_campaigns(), mvps, {}, phase_exclude="%phase2%")
    merged2, _ = merge_ga_clicks(_handpick_campaigns(), merged1, {}, phase_exclude="%phase2%")
    h = {m["name"]: m for m in merged2}["handpick"]
    assert h["ga_clicks"] == 371
    assert h["ga_clicks_phase2"] == 258
    assert len([m for m in merged2 if m["name"] == "handpick"]) == 1


def test_main_merge_phase_filter_and_exclude_mutually_exclusive():
    with tempfile.TemporaryDirectory() as td:
        ga_csv_path = os.path.join(td, "ga.csv")
        ctx_path = os.path.join(td, "context.json")
        with open(ga_csv_path, "w", encoding="utf-8") as f:
            f.write("Campaign,Clicks\nalpha-search-v1,10\n")
        json.dump({"mvps": [_mvp("alpha")]}, open(ctx_path, "w"))
        rc = main([
            "merge",
            "--ga-csv", ga_csv_path,
            "--context", ctx_path,
            "--config", os.path.join(td, "none.yaml"),
            "--unmatched-out", os.path.join(td, "unmatched.json"),
            "--phase-filter", "%phase2%",
            "--phase-exclude", "%phase2%",
        ])
        assert rc == 2


def test_main_merge_phase_exclude_stamps_context_and_reads_exempt_config():
    with tempfile.TemporaryDirectory() as td:
        ga_csv_path = os.path.join(td, "ga.csv")
        ctx_path = os.path.join(td, "context.json")
        cfg_path = os.path.join(td, "config.yaml")
        with open(ga_csv_path, "w", encoding="utf-8") as f:
            f.write("Campaign,Clicks,Conversions\n")
            f.write("handpick - Dubai Search,113,0\n")
            f.write("handpick-search-phase2-v1,258,0\n")
            f.write("alpha-legit-phase2-name,20,0\n")
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write("phase2:\n  utm_campaign_like: '%phase2%'\n")
            f.write("  exclude_exempt_campaigns:\n    - alpha-legit-phase2-name\n")
        json.dump({"mvps": [_mvp("handpick"), _mvp("alpha-legit")]}, open(ctx_path, "w"))
        rc = main([
            "merge",
            "--ga-csv", ga_csv_path,
            "--context", ctx_path,
            "--config", cfg_path,
            "--unmatched-out", os.path.join(td, "unmatched.json"),
            "--phase-exclude", "%phase2%",
        ])
        assert rc == 0
        ctx = json.load(open(ctx_path))
        assert ctx["ga_phase_exclude_applied"] == "%phase2%"
        by = {m["name"]: m for m in ctx["mvps"]}
        assert by["handpick"]["ga_clicks"] == 371
        assert by["handpick"]["ga_clicks_phase2"] == 258
        # Exempt campaign: name matches the pattern but is operator-whitelisted.
        assert by["alpha-legit"]["ga_clicks"] == 20
        assert by["alpha-legit"]["ga_clicks_phase2"] == 0


def test_merge_relaunch_drops_pre_relaunch_campaign():
    """A relaunched MVP's old flight (Start date before the cut) is excluded;
    the new v2 campaign (on/after the cut) is the only denominator."""
    mvps = [_mvp("mooncub", gclid_visitors=84)]
    campaigns = [
        {"name": "mooncub-search-v1", "clicks": 102, "conv": 0,
         "account": "Lee", "start_date": "2026-07-01"},
        {"name": "mooncub-search-v2", "clicks": 40, "conv": 4,
         "account": "Lee", "start_date": "2026-07-25"},
    ]
    merged, unmatched = merge_ga_clicks(
        campaigns, mvps, relaunch_by_mvp={"mooncub": "2026-07-25"}
    )
    by = {m["name"]: m for m in merged}
    assert by["mooncub"]["ga_clicks"] == 40  # v1's 102 excluded
    assert by["mooncub"]["ga_campaigns"] == ["mooncub-search-v2"]
    dropped = [u for u in unmatched if u.get("reason") == "pre-relaunch"]
    assert [u["name"] for u in dropped] == ["mooncub-search-v1"]


def test_merge_relaunch_absent_counts_all_campaigns():
    """Without a relaunch date the same campaigns both count (back-compat)."""
    mvps = [_mvp("mooncub", gclid_visitors=84)]
    campaigns = [
        {"name": "mooncub-search-v1", "clicks": 102, "conv": 0,
         "account": "Lee", "start_date": "2026-07-01"},
        {"name": "mooncub-search-v2", "clicks": 40, "conv": 4,
         "account": "Lee", "start_date": "2026-07-25"},
    ]
    merged, _ = merge_ga_clicks(campaigns, mvps)
    by = {m["name"]: m for m in merged}
    assert by["mooncub"]["ga_clicks"] == 142


def test_merge_relaunch_only_scopes_the_named_mvp():
    """A relaunch date on one MVP must not affect another MVP's campaigns."""
    mvps = [_mvp("mooncub", gclid_visitors=84), _mvp("diarly", gclid_visitors=87)]
    campaigns = [
        {"name": "mooncub-search-v1", "clicks": 102, "conv": 0,
         "account": "Lee", "start_date": "2026-07-01"},
        {"name": "diarly-search-v1", "clicks": 102, "conv": 8,
         "account": "Lew", "start_date": "2026-05-01"},
    ]
    merged, _ = merge_ga_clicks(
        campaigns, mvps, relaunch_by_mvp={"mooncub": "2026-07-25"}
    )
    by = {m["name"]: m for m in merged}
    assert by["mooncub"]["ga_clicks"] == 0    # only old flight → all dropped
    assert by["diarly"]["ga_clicks"] == 102   # untouched


def test_main_merge_phase_filter_skips_relaunch_map():
    """The x5 --phase-filter merge must ignore phase1_relaunch_at: the phase2
    denominator is scoped by the utm token, and the x5 CSV export need not
    carry Start date — an active cut would drop every phase2 campaign."""
    with tempfile.TemporaryDirectory() as td:
        ga_csv_path = os.path.join(td, "ga.csv")
        ctx_path = os.path.join(td, "context.json")
        cfg_path = os.path.join(td, "config.yaml")
        unmatched_path = os.path.join(td, "unmatched.json")
        with open(ga_csv_path, "w", encoding="utf-8") as f:
            f.write("Campaign,Clicks\n")            # x5 export shape: no Start date
            f.write("mooncub-search-phase2-v1,40\n")
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write("mvp_mappings:\n  mooncub:\n    phase1_relaunch_at: '2026-07-25'\n")
        json.dump({"mvps": [_mvp("mooncub")], "mode": "cross-phase2"}, open(ctx_path, "w"))
        rc = main([
            "merge",
            "--ga-csv", ga_csv_path,
            "--context", ctx_path,
            "--config", cfg_path,
            "--unmatched-out", unmatched_path,
            "--phase-filter", "%phase2%",
        ])
        assert rc == 0
        ctx = json.load(open(ctx_path))
        by = {m["name"]: m for m in ctx["mvps"]}
        assert by["mooncub"]["ga_clicks"] == 40
        assert by["mooncub"]["ga_campaigns"] == ["mooncub-search-phase2-v1"]
        unmatched = json.load(open(unmatched_path))
        assert [u for u in unmatched if u.get("reason") == "pre-relaunch"] == []


def test_main_merge_without_phase_filter_still_applies_relaunch_map():
    """Regression guard for the else-branch: the Phase-1 (no --phase-filter)
    merge keeps applying the relaunch cut."""
    with tempfile.TemporaryDirectory() as td:
        ga_csv_path = os.path.join(td, "ga.csv")
        ctx_path = os.path.join(td, "context.json")
        cfg_path = os.path.join(td, "config.yaml")
        unmatched_path = os.path.join(td, "unmatched.json")
        with open(ga_csv_path, "w", encoding="utf-8") as f:
            f.write("Campaign,Clicks,Start date\n")
            f.write("mooncub-search-v1,102,2026-07-01\n")
            f.write("mooncub-search-v2,40,2026-07-25\n")
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write("mvp_mappings:\n  mooncub:\n    phase1_relaunch_at: '2026-07-25'\n")
        json.dump({"mvps": [_mvp("mooncub")]}, open(ctx_path, "w"))
        rc = main([
            "merge",
            "--ga-csv", ga_csv_path,
            "--context", ctx_path,
            "--config", cfg_path,
            "--unmatched-out", unmatched_path,
        ])
        assert rc == 0
        ctx = json.load(open(ctx_path))
        by = {m["name"]: m for m in ctx["mvps"]}
        assert by["mooncub"]["ga_clicks"] == 40
        unmatched = json.load(open(unmatched_path))
        assert [u["name"] for u in unmatched if u.get("reason") == "pre-relaunch"] == [
            "mooncub-search-v1"
        ]


# ---------- status columns (campaign deliverability) ----------

def test_parse_ga_csv_reads_status_columns():
    """Real export shape: Campaign status (switch), Status (serving), Status reasons."""
    text = (
        "Campaign report\nAll time\n"
        "Campaign status\tCampaign\tStatus\tStatus reasons\tClicks\n"
        "Enabled\txpredict\tEligible\t--\t1082\n"
        "Enabled\ttermob-search-v1\tEnded\tCampaign ended\t50\n"
        "Paused\tbrigent\tPaused\t--\t158\n"
    )
    parsed = parse_ga_csv(text)
    by = {c["name"]: c for c in parsed}
    assert by["xpredict"]["campaign_status"] == "Enabled"
    assert by["xpredict"]["serving_status"] == "Eligible"
    assert by["xpredict"]["status_normalized"] == "active"
    assert by["termob-search-v1"]["status_normalized"] == "stopped"  # Enabled+Ended
    assert by["termob-search-v1"]["status_reasons"] == "Campaign ended"
    assert by["brigent"]["status_normalized"] == "stopped"


def test_parse_ga_csv_status_columns_absent_yield_none():
    parsed = parse_ga_csv("Campaign,Clicks\nxpredict,1082\n")
    assert parsed[0]["campaign_status"] is None
    assert parsed[0]["serving_status"] is None
    assert parsed[0]["status_reasons"] is None
    assert parsed[0]["status_normalized"] == "unknown"


def test_parse_ga_csv_serving_status_never_substring_binds_to_campaign_status():
    """With `Campaign status` present but no `Status` column, serving_status must
    stay None — a substring pass would bind it to `Campaign status` (#1482's
    sibling trap)."""
    text = "Campaign status,Campaign,Clicks\nEnabled,xpredict,1082\n"
    parsed = parse_ga_csv(text)
    assert parsed[0]["campaign_status"] == "Enabled"
    assert parsed[0]["serving_status"] is None
    # Enabled switch with no serving info → can spend → active.
    assert parsed[0]["status_normalized"] == "active"


def test_parse_ga_csv_empty_status_cells_normalize_unknown():
    text = "Campaign status,Campaign,Status,Clicks\n,xpredict,,1082\n"
    parsed = parse_ga_csv(text)
    assert parsed[0]["campaign_status"] == ""
    assert parsed[0]["serving_status"] == ""
    assert parsed[0]["status_normalized"] == "unknown"


def test_normalize_campaign_status_matrix():
    n = normalize_campaign_status
    # stopped whitelist: switch Paused/Removed or serving Ended/Paused/Removed.
    assert n("Paused", "Paused") == "stopped"
    assert n("Removed", "Removed") == "stopped"
    assert n("Enabled", "Ended") == "stopped"        # past end date ≠ live
    # active: Enabled switch with any non-stopped serving value.
    assert n("Enabled", "Eligible") == "active"
    assert n("Enabled", "Eligible (Limited)") == "active"
    assert n("Enabled", "Eligible (Learning)") == "active"
    assert n("Enabled", "Pending") == "active"
    assert n("ENABLED", "  eligible  ") == "active"  # case/whitespace tolerant
    # unknown: localized/unrecognized switch values or no data at all — every
    # consumer treats unknown like active (over-alert, never silent close-out).
    assert n("Aktiviert", "Berechtigt") == "unknown"
    assert n(None, None) == "unknown"
    assert n("", "") == "unknown"


def test_merge_all_stopped_true_when_every_campaign_stopped():
    mvps = [_mvp("stylistly")]
    campaigns = [
        {"name": "stylistly-search-v1", "clicks": 10, "conv": 0, "account": "a",
         "campaign_status": "Paused", "serving_status": "Paused"},
    ]
    merged, _ = merge_ga_clicks(campaigns, mvps)
    by = {m["name"]: m for m in merged}
    assert by["stylistly"]["ga_ads_all_stopped"] is True
    assert by["stylistly"]["ga_campaign_status_detail"][0]["normalized"] == "stopped"


def test_merge_all_stopped_false_on_any_active():
    mvps = [_mvp("termob")]
    campaigns = [
        {"name": "termob-search-v1", "clicks": 10, "conv": 0, "account": "a",
         "campaign_status": "Enabled", "serving_status": "Eligible"},
        {"name": "termob-search-v2", "clicks": 5, "conv": 0, "account": "a",
         "campaign_status": "Paused", "serving_status": "Paused"},
    ]
    merged, _ = merge_ga_clicks(campaigns, mvps)
    by = {m["name"]: m for m in merged}
    assert by["termob"]["ga_ads_all_stopped"] is False


def test_merge_all_stopped_none_without_status_columns():
    """Legacy/synthetic campaign dicts without status keys → tri-state None;
    MVPs untouched by any campaign keep the None default from the reset loop."""
    mvps = [_mvp("x-predict"), _mvp("idle")]
    campaigns = [{"name": "xpredict", "clicks": 1082, "conv": 0, "account": "a"}]
    merged, _ = merge_ga_clicks(campaigns, mvps)
    by = {m["name"]: m for m in merged}
    assert by["x-predict"]["ga_ads_all_stopped"] is None
    assert by["x-predict"]["ga_campaign_status_detail"][0]["normalized"] == "unknown"
    assert by["idle"]["ga_ads_all_stopped"] is None
    assert by["idle"]["ga_campaign_status_detail"] == []


def test_merge_pre_relaunch_campaign_still_contributes_status():
    """The old flight leaves the click denominator but its deliverability must
    still land on the record — dropped ≠ not burning money."""
    mvps = [_mvp("mooncub")]
    campaigns = [
        {"name": "mooncub-search-v1", "clicks": 102, "conv": 0, "account": "a",
         "start_date": "2026-07-01",
         "campaign_status": "Enabled", "serving_status": "Eligible"},
        {"name": "mooncub-search-v2", "clicks": 40, "conv": 4, "account": "a",
         "start_date": "2026-07-25",
         "campaign_status": "Paused", "serving_status": "Paused"},
    ]
    merged, _ = merge_ga_clicks(
        campaigns, mvps, relaunch_by_mvp={"mooncub": "2026-07-25"}
    )
    by = {m["name"]: m for m in merged}
    assert by["mooncub"]["ga_clicks"] == 40  # v1 still excluded from denominator
    assert by["mooncub"]["ga_campaigns"] == ["mooncub-search-v2"]
    names = [d["name"] for d in by["mooncub"]["ga_campaign_status_detail"]]
    assert names == ["mooncub-search-v1", "mooncub-search-v2"]  # both, sorted
    assert by["mooncub"]["ga_ads_all_stopped"] is False  # v1 still deliverable


def test_merge_all_dropped_bucket_still_lands_status():
    """Every campaign dropped pre-relaunch: no click totals, but the record
    still carries the deliverability detail (union iteration over buckets)."""
    mvps = [_mvp("mooncub")]
    campaigns = [
        {"name": "mooncub-search-v1", "clicks": 102, "conv": 0, "account": "a",
         "start_date": "2026-07-01",
         "campaign_status": "Enabled", "serving_status": "Eligible"},
    ]
    merged, unmatched = merge_ga_clicks(
        campaigns, mvps, relaunch_by_mvp={"mooncub": "2026-07-25"}
    )
    by = {m["name"]: m for m in merged}
    assert by["mooncub"]["ga_clicks"] == 0
    assert by["mooncub"]["ga_campaigns"] == []
    assert by["mooncub"]["ga_ads_all_stopped"] is False
    detail_names = [d["name"] for d in by["mooncub"]["ga_campaign_status_detail"]]
    assert detail_names == ["mooncub-search-v1"]
    assert [u["name"] for u in unmatched] == ["mooncub-search-v1"]  # still reported


def test_merge_ga_only_records_carry_status_fields():
    merged, _ = merge_ga_clicks(
        [{"name": "reset-app-search-v1", "clicks": 58, "conv": 0, "account": "a",
          "campaign_status": "Removed", "serving_status": "Removed"}],
        [],
    )
    assert merged[0]["ga_only"] is True
    assert merged[0]["ga_ads_all_stopped"] is True
    assert merged[0]["ga_campaign_status_detail"][0]["normalized"] == "stopped"


def test_merge_unmatched_entries_carry_status_fields():
    _, unmatched = merge_ga_clicks(
        [{"name": "Campaign #1", "clicks": 21, "conv": 0, "account": "a",
          "campaign_status": "Enabled", "serving_status": "Eligible",
          "status_normalized": "active"}],
        [_mvp("diarly")],
    )
    assert unmatched[0]["reason"] == "placeholder"
    assert unmatched[0]["status_normalized"] == "active"


def test_merge_rerun_clears_stale_status_detail():
    mvps = [_mvp("x-predict")]
    active = [{"name": "xpredict", "clicks": 10, "conv": 0, "account": "a",
               "campaign_status": "Enabled", "serving_status": "Eligible"}]
    merged1, _ = merge_ga_clicks(active, mvps)
    assert merged1[0]["ga_ads_all_stopped"] is False
    merged2, _ = merge_ga_clicks([], merged1)
    assert merged2[0]["ga_campaign_status_detail"] == []
    assert merged2[0]["ga_ads_all_stopped"] is None


if __name__ == "__main__":
    import inspect

    failed = 0
    passed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn) and inspect.signature(fn).parameters == {}:
            try:
                fn()
                print(f"PASS  {name}")
                passed += 1
            except Exception as e:
                print(f"FAIL  {name}: {e!r}")
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
