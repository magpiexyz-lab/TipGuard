#!/usr/bin/env python3
"""Tests for .claude/scripts/lib/iterate_cross_verdicts.py (PostHog-only).

Run:
  python3 -m pytest .claude/scripts/tests/test_iterate_cross_verdicts.py -v
  # OR (no pytest dependency):
  python3 .claude/scripts/tests/test_iterate_cross_verdicts.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import iterate_cross_verdicts as verdicts  # noqa: E402
from iterate_cross_verdicts import (  # noqa: E402
    DEFAULT_CONFIG,
    VERDICT_ENUM,
    VERDICT_GA_NO_PH_TRACKING,
    VERDICT_GO,
    VERDICT_INSUFFICIENT,
    VERDICT_MISSING_PROJECT_NAME,
    VERDICT_NO_DATA,
    VERDICT_NO_GO,
    VERDICT_WEAK,
    action_line,
    compute_headline_verdict,
    compute_money_leak,
    compute_pay_intent_verdict,
    compute_pay_intent_wiring_flag,
    compute_price_change_flag,
    emit_team_message,
    is_trusted_db_pay_intents,
    is_trusted_db_paid,
    is_trusted_db_real,
    main,
    pay_intent_action_line,
    pay_intent_go_rank_key,
    pay_intent_revenue_cell,
    resolve_effective_pay_intents,
    sort_scores_by_owner,
    sort_scores_global,
)
from iterate_cross_ga import campaign_matches_phase_filter  # noqa: E402


THRESHOLDS = DEFAULT_CONFIG["thresholds"]


def mvp(name="m", owner="alice", visitors=0, signups=0, signup_events=None,
        ga_clicks=0, ga_only=False):
    """Build a PostHog MVP record matching state-x2's data.json schema.

    Set `ga_clicks` to simulate state-x0a having merged Google Ads data.
    Set `ga_only=True` for a synthetic record (campaign exists in GA but PH has nothing).
    """
    return {
        "name": name,
        "owner": owner,
        "gclid_visitors": visitors,
        "signups": signups,
        "signup_events": signup_events or ["signup_complete"],
        "total_events_count": 100,
        "event_catalog": [],
        "ga_clicks": ga_clicks,
        "ga_only": ga_only,
    }


def pay_mvp(name="m", owner="alice", ga_clicks=0, pay_intents=0,
            gclid_visitors_phase2=0, ga_only=False,
            pay_intent_price_cents=0, pay_intent_price_variants=0,
            **extra):
    record = {
        "name": name,
        "owner": owner,
        "gclid_visitors": gclid_visitors_phase2,
        "gclid_visitors_phase2": gclid_visitors_phase2,
        "ga_clicks": ga_clicks,
        "pay_intents": pay_intents,
        "ga_only": ga_only,
        "phase_match": True,
        "orphan": False,
        "pay_intent_price_cents": pay_intent_price_cents,
        "pay_intent_price_variants": pay_intent_price_variants,
    }
    record.update(extra)
    return record


# ---------- Verdict precedence (rule v2: vis<100 → INSUF; vis≥100 & conv≥6% → GO; else NO_GO) ----------

def test_go_at_floor_with_6pct_conv():
    """visitors=100 & signups=6 → conv=6.0% (exactly at threshold) → GO."""
    score = compute_headline_verdict(mvp(visitors=100, signups=6), {}, THRESHOLDS)
    assert score["headline_verdict"] == VERDICT_GO
    assert score["visitors_needed"] == 0


def test_go_with_high_conv():
    """visitors=200 & signups=20 → conv=10% → GO."""
    score = compute_headline_verdict(mvp(visitors=200, signups=20), {}, THRESHOLDS)
    assert score["headline_verdict"] == VERDICT_GO


def test_no_go_at_floor_with_zero_signups():
    """visitors=100 & signups=0 → conv=0% < 6% → NO_GO."""
    score = compute_headline_verdict(mvp(visitors=100, signups=0), {}, THRESHOLDS)
    assert score["headline_verdict"] == VERDICT_NO_GO


def test_no_go_above_floor_with_some_signups_below_6pct():
    """≥100 visitors with conv < 6% → NO_GO (WEAK no longer emitted)."""
    score = compute_headline_verdict(mvp(visitors=107, signups=1), {}, THRESHOLDS)
    assert score["headline_verdict"] == VERDICT_NO_GO


def test_no_go_with_2_signups_at_high_volume():
    """200 visitors / 2 signups = 1% conv → NO_GO."""
    score = compute_headline_verdict(mvp(visitors=200, signups=2), {}, THRESHOLDS)
    assert score["headline_verdict"] == VERDICT_NO_GO


def test_no_go_just_below_6pct_threshold():
    """100 visitors / 5 signups = 5.0% conv → NO_GO (just under 6%)."""
    score = compute_headline_verdict(mvp(visitors=100, signups=5), {}, THRESHOLDS)
    assert score["headline_verdict"] == VERDICT_NO_GO


def test_project_deleted_db_forces_no_go_despite_inflated_ph():
    """Deleted backend (project_deleted) must NOT promote on the inflated PostHog
    fallback. leasebrief regression: 22 PH signup_start over 150 GA clicks (14.7%)
    would be GO, but the deleted DB means no trusted ground truth → NO_GO.
    """
    record = mvp(visitors=134, signups=22, ga_clicks=150, signup_events=["signup_start"])
    record.update({
        "ph_signups": 22,
        "ph_signups_available": True,
        "db_signups_real": None,
        "db_unmapped_reason": "project_deleted",
    })
    assert compute_headline_verdict(record, {}, THRESHOLDS)["headline_verdict"] == VERDICT_NO_GO


def test_project_deleted_rule_is_narrow_same_record_without_signal_is_go():
    """The rule is scoped to project_deleted only: the identical inflated record
    with no deletion signal still scores GO — proving the deletion reason is what
    flips the verdict, not an over-broad gate.
    """
    record = mvp(visitors=134, signups=22, ga_clicks=150, signup_events=["signup_start"])
    record.update({
        "ph_signups": 22,
        "ph_signups_available": True,
        "db_signups_real": None,
        "db_unmapped_reason": None,
    })
    assert compute_headline_verdict(record, {}, THRESHOLDS)["headline_verdict"] == VERDICT_GO


def test_archived_killed_forces_no_go_despite_inflated_ph():
    """archived_killed (killed policy skip — x0b did not re-query) must behave
    exactly like the old assumed project_deleted for verdict purposes: no
    trusted ground truth → NO_GO, never a PostHog-fallback resurrection.
    """
    record = mvp(visitors=134, signups=22, ga_clicks=150, signup_events=["signup_start"])
    record.update({
        "ph_signups": 22,
        "ph_signups_available": True,
        "db_signups_real": None,
        "db_unmapped_reason": "archived_killed",
        "lifecycle_status": "killed",
    })
    assert compute_headline_verdict(record, {}, THRESHOLDS)["headline_verdict"] == VERDICT_NO_GO


def test_money_leak_flags_archived_killed_with_recent_last_seen():
    rec = {
        "db_unmapped_reason": "archived_killed",
        "lifecycle_status": "killed",
        "last_seen": "2026-06-24T00:00:00Z",
    }
    assert compute_money_leak(rec, "2026-06-25T00:00:00Z", window_days=14)


def test_zombie_backend_requires_killed_alive_and_no_waiver():
    ref_now = "2026-07-21T00:00:00Z"
    base = {
        "lifecycle_status": "killed",
        "db_backend": {"status": "alive", "checked_at": "2026-07-21T00:00:00Z"},
    }
    assert verdicts.compute_zombie_backend(dict(base), ref_now) is True
    # Verified-deleted backend → not a zombie.
    dead = dict(base, db_backend={"status": "deleted_verified"})
    assert verdicts.compute_zombie_backend(dead, ref_now) is False
    # Active (non-killed) MVP with a live backend is just... an MVP.
    alive_mvp = dict(base, lifecycle_status="active")
    assert verdicts.compute_zombie_backend(alive_mvp, ref_now) is False
    # No backend knowledge → no claim.
    unknown = dict(base, db_backend=None)
    assert verdicts.compute_zombie_backend(unknown, ref_now) is False


def test_zombie_backend_waiver_suppresses_until_expiry():
    ref_now = "2026-07-21T00:00:00Z"
    base = {
        "lifecycle_status": "killed",
        "db_backend": {"status": "alive"},
    }
    kept = dict(base, backend_keep={"reason": "shared project hosts other work"})
    assert verdicts.compute_zombie_backend(kept, ref_now) is False
    unexpired = dict(base, backend_keep={"reason": "keep", "expires_at": "2026-12-31T00:00:00Z"})
    assert verdicts.compute_zombie_backend(unexpired, ref_now) is False
    expired = dict(base, backend_keep={"reason": "keep", "expires_at": "2026-01-01T00:00:00Z"})
    assert verdicts.compute_zombie_backend(expired, ref_now) is True


def test_headline_metrics_carry_zombie_and_backend_status():
    record = mvp(visitors=10, signups=0)
    record.update({
        "lifecycle_status": "killed",
        "db_unmapped_reason": "archived_killed",
        "db_signups_real": None,
        "db_backend": {"status": "alive", "checked_at": "2026-07-21T00:00:00Z"},
        "last_seen": "2026-07-20T00:00:00Z",
    })
    score = compute_headline_verdict(
        record, {}, THRESHOLDS, money_leak_reference_now="2026-07-21T00:00:00Z",
    )
    assert score["metrics"]["db_backend_status"] == "alive"
    assert score["metrics"]["zombie_backend"] is True
    assert score["db_backend"]["status"] == "alive"


def test_insufficient_data_below_floor():
    """visitors=20 < 100 floor → INSUF regardless of signups."""
    score = compute_headline_verdict(mvp(visitors=20, signups=1), {}, THRESHOLDS)
    assert score["headline_verdict"] == VERDICT_INSUFFICIENT
    assert score["visitors_needed"] == 80


def test_insufficient_with_great_conv_but_low_traffic():
    """8 visitors / 6 signups = 75% conv, but vis<100 → INSUF.

    dead-link real case: tiny sample with extreme conversion is exactly
    the case the visitors_floor protects against (likely attribution issue,
    not real conversion rate)."""
    score = compute_headline_verdict(mvp(visitors=8, signups=6), {}, THRESHOLDS)
    assert score["headline_verdict"] == VERDICT_INSUFFICIENT
    assert score["visitors_needed"] == 92


def test_insufficient_zero_visitors():
    score = compute_headline_verdict(mvp(visitors=0, signups=0), {}, THRESHOLDS)
    assert score["headline_verdict"] == VERDICT_INSUFFICIENT
    assert score["visitors_needed"] == 100


def test_no_data_takes_precedence_over_go():
    """no_event_data flag wins even with conv-passing scenario."""
    score = compute_headline_verdict(
        mvp(visitors=100, signups=10),  # 10% conv would be GO
        {"no_event_data": True},
        THRESHOLDS,
    )
    assert score["headline_verdict"] == VERDICT_NO_DATA


def test_no_data_takes_precedence_over_no_go():
    score = compute_headline_verdict(
        mvp(visitors=154, signups=0),
        {"no_event_data": True},
        THRESHOLDS,
    )
    assert score["headline_verdict"] == VERDICT_NO_DATA


def test_no_data_takes_precedence_over_insufficient():
    """no_event_data wins even when visitors are below floor."""
    score = compute_headline_verdict(
        mvp(visitors=20, signups=0),
        {"no_event_data": True},
        THRESHOLDS,
    )
    assert score["headline_verdict"] == VERDICT_NO_DATA


def test_missing_project_name_takes_precedence_over_no_data():
    """missing_project_name is precedence rule 0 — wins over every other flag.

    Orphan MVPs (events with NULL project_name) have empty event_catalog by
    definition (catalog query filters by project_name), so no_event_data is
    also true. The verdict must surface the ROOT cause (tracking gap) not
    the SYMPTOM (no catalog).
    """
    score = compute_headline_verdict(
        mvp(visitors=20, signups=0),
        {"missing_project_name": True, "no_event_data": True},
        THRESHOLDS,
    )
    assert score["headline_verdict"] == VERDICT_MISSING_PROJECT_NAME


def test_missing_project_name_takes_precedence_over_go():
    """Even with a high signup count, MISSING_PROJECT_NAME wins — the data is
    suspect when identity is missing (signups attributed to wrong MVP, etc.).
    """
    score = compute_headline_verdict(
        mvp(visitors=200, signups=20),
        {"missing_project_name": True},
        THRESHOLDS,
    )
    assert score["headline_verdict"] == VERDICT_MISSING_PROJECT_NAME


def test_missing_project_name_falsy_falls_through_to_normal_precedence():
    """When missing_project_name is False/absent, normal verdict logic runs."""
    score = compute_headline_verdict(
        mvp(visitors=100, signups=8),  # 8% conv → GO
        {"missing_project_name": False},
        THRESHOLDS,
    )
    assert score["headline_verdict"] == VERDICT_GO


def test_missing_project_name_in_verdict_enum():
    """Defense-in-depth: the new verdict must be in the enum so x3 VERIFY
    accepts it as a legal output and downstream consumers don't choke."""
    assert VERDICT_MISSING_PROJECT_NAME in VERDICT_ENUM


# ---------- GA_NO_PH_TRACKING precedence ----------

def test_ga_no_ph_tracking_fires_when_flag_set():
    """ga_clicks_without_ph_traffic flag → GA_NO_PH_TRACKING verdict."""
    score = compute_headline_verdict(
        mvp(visitors=0, signups=0, ga_clicks=58, ga_only=True),
        {"ga_clicks_without_ph_traffic": True},
        THRESHOLDS,
    )
    assert score["headline_verdict"] == VERDICT_GA_NO_PH_TRACKING


def test_ga_no_ph_tracking_yields_to_missing_project_name():
    """MISSING_PROJECT_NAME (rank 0) outranks GA_NO_PH_TRACKING (rank 1)."""
    score = compute_headline_verdict(
        mvp(visitors=0, signups=0, ga_clicks=58),
        {"missing_project_name": True, "ga_clicks_without_ph_traffic": True},
        THRESHOLDS,
    )
    assert score["headline_verdict"] == VERDICT_MISSING_PROJECT_NAME


def test_ga_no_ph_tracking_outranks_no_data():
    """GA_NO_PH_TRACKING (rank 1) outranks NO_DATA (rank 2). Both can be true
    for the same ga_only MVP (no PH events → no_event_data) but the stricter
    diagnosis (GA spend without PH tracking) is the actionable one."""
    score = compute_headline_verdict(
        mvp(visitors=0, signups=0, ga_clicks=58),
        {"ga_clicks_without_ph_traffic": True, "no_event_data": True},
        THRESHOLDS,
    )
    assert score["headline_verdict"] == VERDICT_GA_NO_PH_TRACKING


def test_ga_no_ph_tracking_in_verdict_enum():
    assert VERDICT_GA_NO_PH_TRACKING in VERDICT_ENUM


# ---------- Phase 2 pay-intent verdict ----------

def test_pay_intent_go_at_threshold():
    thresholds = dict(THRESHOLDS, pay_intent_rate_go=0.02)
    score = compute_pay_intent_verdict(
        pay_mvp(ga_clicks=300, pay_intents=6, gclid_visitors_phase2=150),
        {},
        thresholds,
    )
    assert score["headline_verdict"] == VERDICT_GO
    assert score["metrics"]["denominator_source"] == "ga"
    assert score["metrics"]["pay_intent_rate"] == 0.02


def test_pay_intent_revenue_metrics_use_event_price():
    thresholds = dict(THRESHOLDS, pay_intent_rate_go=0.02)
    score = compute_pay_intent_verdict(
        pay_mvp(
            ga_clicks=300,
            pay_intents=15,
            gclid_visitors_phase2=150,
            pay_intent_price_cents=1900,
            pay_intent_price_variants=1,
        ),
        {},
        thresholds,
    )
    assert score["headline_verdict"] == VERDICT_GO
    assert score["metrics"]["pay_intent_rate"] == 0.05
    assert score["metrics"]["pay_intent_price_cents"] == 1900.0
    assert score["metrics"]["revenue_intent_per_click"] == 95.0
    assert score["metrics"]["pay_intent_price_variants"] == 1


def test_pay_intent_no_go_just_below_threshold():
    thresholds = dict(THRESHOLDS, pay_intent_rate_go=0.02)
    score = compute_pay_intent_verdict(
        pay_mvp(ga_clicks=300, pay_intents=3, gclid_visitors_phase2=240),
        {},
        thresholds,
    )
    assert score["headline_verdict"] == VERDICT_NO_GO
    assert score["metrics"]["pay_intent_rate"] == 0.01


def test_pay_intent_zero_price_or_clicks_has_zero_revenue():
    thresholds = dict(THRESHOLDS, pay_intent_rate_go=0.02)
    zero_price = compute_pay_intent_verdict(
        pay_mvp(ga_clicks=300, pay_intents=9, pay_intent_price_cents=0),
        {},
        thresholds,
    )
    assert zero_price["metrics"]["revenue_intent_per_click"] == 0.0

    zero_clicks = compute_pay_intent_verdict(
        pay_mvp(ga_clicks=0, pay_intents=9, pay_intent_price_cents=1900),
        {},
        thresholds,
    )
    assert zero_clicks["headline_verdict"] == VERDICT_INSUFFICIENT
    assert zero_clicks["metrics"]["revenue_intent_per_click"] == 0.0


def test_pay_intent_revenue_rank_beats_higher_raw_rate():
    thresholds = dict(THRESHOLDS, pay_intent_rate_go=0.02)
    cheap_high_rate = compute_pay_intent_verdict(
        pay_mvp(name="a", ga_clicks=300, pay_intents=24, pay_intent_price_cents=500),
        {},
        thresholds,
    )
    expensive_lower_rate = compute_pay_intent_verdict(
        pay_mvp(name="b", ga_clicks=300, pay_intents=9, pay_intent_price_cents=5000),
        {},
        thresholds,
    )
    assert cheap_high_rate["headline_verdict"] == VERDICT_GO
    assert expensive_lower_rate["headline_verdict"] == VERDICT_GO
    ranked = sorted([cheap_high_rate, expensive_lower_rate], key=pay_intent_go_rank_key)
    assert [score["name"] for score in ranked] == ["b", "a"]


def test_pay_intent_revenue_cell_flags_mixed_price():
    assert pay_intent_revenue_cell(
        {"revenue_intent_per_click": 95.0, "pay_intent_price_variants": 1}
    ) == "$0.95"
    assert "mixed-price" in pay_intent_revenue_cell(
        {"revenue_intent_per_click": 95.0, "pay_intent_price_variants": 2}
    )


def test_pay_intent_zero_at_click_floor_is_no_go():
    thresholds = dict(THRESHOLDS, pay_intent_rate_go=0.02)
    score = compute_pay_intent_verdict(
        pay_mvp(ga_clicks=300, pay_intents=0, gclid_visitors_phase2=120),
        {},
        thresholds,
    )
    assert score["headline_verdict"] == VERDICT_NO_GO
    assert score["visitors_needed"] == 0


def test_pay_intent_mixed_phase1_phase2_events_only_counts_phase2_campaign():
    """Non-Phase-2 pay_intent events must not contribute to the numerator."""
    events = [
        *[
            {"event": "pay_intent", "distinct_id": f"phase1-{i}", "properties": {"utm_campaign": "mvp-search-v1"}}
            for i in range(15)
        ],
        *[
            {"event": "pay_intent", "distinct_id": f"phase2-{i}", "properties": {"utm_campaign": "mvp-search-phase2-v1"}}
            for i in range(3)
        ],
    ]
    phase2_users = {
        e["distinct_id"]
        for e in events
        if e["event"] == "pay_intent"
        and campaign_matches_phase_filter(e["properties"].get("utm_campaign", ""), "%phase2%")
    }
    all_users = {e["distinct_id"] for e in events if e["event"] == "pay_intent"}
    assert len(phase2_users) == 3
    assert len(all_users) == 18

    thresholds = dict(THRESHOLDS, pay_intent_rate_go=0.05)
    score = compute_pay_intent_verdict(
        pay_mvp(ga_clicks=300, pay_intents=len(phase2_users), gclid_visitors_phase2=60),
        {},
        thresholds,
    )
    assert score["headline_verdict"] == VERDICT_NO_GO
    assert score["metrics"]["pay_intents"] == 3
    assert compute_pay_intent_verdict(
        pay_mvp(ga_clicks=300, pay_intents=len(all_users), gclid_visitors_phase2=60),
        {},
        thresholds,
    )["headline_verdict"] == VERDICT_GO


def test_pay_intent_integrity_precedence():
    thresholds = dict(THRESHOLDS, pay_intent_rate_go=0.02)
    score = compute_pay_intent_verdict(
        pay_mvp(ga_clicks=300, pay_intents=30),
        {"missing_project_name": True, "ga_clicks_without_ph_traffic": True},
        thresholds,
    )
    assert score["headline_verdict"] == VERDICT_MISSING_PROJECT_NAME


def test_pay_intent_action_line_go_is_phase3_eligible():
    action = pay_intent_action_line(VERDICT_GO, "mvp", 9, 0, 300, 0.02)
    assert "Phase 3 eligibility" in action


def test_pay_intent_default_floor_300_requires_more_clicks():
    score = compute_pay_intent_verdict(
        pay_mvp(ga_clicks=250, pay_intents=10),
        {},
        THRESHOLDS,
    )
    assert score["headline_verdict"] == VERDICT_INSUFFICIENT
    assert score["visitors_needed"] == 50


def test_pay_intent_legacy_thresholds_fall_back_to_visitors_floor():
    thresholds = dict(THRESHOLDS, pay_intent_rate_go=0.02)
    thresholds.pop("pay_intent_visitors_floor", None)
    score = compute_pay_intent_verdict(
        pay_mvp(ga_clicks=100, pay_intents=2),
        {},
        thresholds,
    )
    assert score["headline_verdict"] == VERDICT_GO


def test_pay_intent_operator_floor_override_is_evaluable():
    thresholds = dict(THRESHOLDS, pay_intent_rate_go=0.02, pay_intent_visitors_floor=150)
    score = compute_pay_intent_verdict(
        pay_mvp(ga_clicks=200, pay_intents=4),
        {},
        thresholds,
    )
    assert score["headline_verdict"] == VERDICT_GO


def trusted_pay_intent_db(**patch):
    base = {
        "db_pay_intents_paid": 6,
        "db_pay_intents_real": 6,
        "db_pay_intents_unattributed": 0,
        "db_pay_intents_raw": 6,
        "db_pay_intents_real_windowed": True,
        "db_pay_intents_unmapped_reason": None,
        "db_pay_intent_source": "supabase",
        "db_pay_intent_price_cents_max": None,
        "db_pay_intent_price_variants": 0,
    }
    base.update(patch)
    return base


def test_pay_intent_db_paid_count_preferred_over_posthog():
    thresholds = dict(THRESHOLDS, pay_intent_rate_go=0.02)
    record = pay_mvp(
        ga_clicks=300,
        pay_intents=3,
        **trusted_pay_intent_db(db_pay_intents_paid=9, db_pay_intents_raw=10),
    )
    score = compute_pay_intent_verdict(record, {}, thresholds)
    assert score["headline_verdict"] == VERDICT_GO
    assert score["metrics"]["pay_intents"] == 9
    assert score["metrics"]["pay_intent_source"] == "db_real"
    assert score["metrics"]["pay_intents_db"] == 9
    assert score["metrics"]["pay_intents_posthog"] == 3


def test_pay_intent_db_trust_rejection_falls_back_to_posthog():
    base = trusted_pay_intent_db(db_pay_intents_paid=9, db_pay_intents_raw=9)
    rejection_patches = [
        {"db_pay_intents_paid": None},
        {"db_pay_intents_unmapped_reason": "no_match"},
        {"db_pay_intents_real_windowed": False},
        {"db_pay_intent_source": "unknown"},
    ]
    for patch in rejection_patches:
        candidate = dict(base, **patch)
        assert not is_trusted_db_pay_intents(candidate)
        count, source, flags = resolve_effective_pay_intents(
            pay_mvp(ga_clicks=300, pay_intents=4, **candidate)
        )
        assert count == 4
        assert source == "ph"
        assert flags == []


def test_pay_intent_db_real_zero_flags_ph_contradiction():
    record = pay_mvp(
        ga_clicks=300,
        pay_intents=5,
        **trusted_pay_intent_db(db_pay_intents_paid=0, db_pay_intents_real=0, db_pay_intents_raw=0),
    )
    score = compute_pay_intent_verdict(record, {}, THRESHOLDS)
    assert score["metrics"]["pay_intent_source"] == "db_real_zero"
    assert score["metrics"]["pay_intents"] == 0
    assert score["headline_verdict"] == VERDICT_NO_GO
    assert any(f["flag"] == "pay_intent_db_zero_with_ph" and f["severity"] == "high" for f in score["tracking_sanity_flags"])


def test_pay_intent_ph_exceeds_db_uses_raw_1_5_boundary():
    high = compute_pay_intent_verdict(
        pay_mvp(ga_clicks=300, pay_intents=16, **trusted_pay_intent_db(db_pay_intents_paid=6, db_pay_intents_raw=10)),
        {},
        THRESHOLDS,
    )
    assert any(f["flag"] == "pay_intent_ph_exceeds_db" for f in high["tracking_sanity_flags"])

    tolerated = compute_pay_intent_verdict(
        pay_mvp(ga_clicks=300, pay_intents=15, **trusted_pay_intent_db(db_pay_intents_paid=6, db_pay_intents_raw=10)),
        {},
        THRESHOLDS,
    )
    assert not any(f["flag"] == "pay_intent_ph_exceeds_db" for f in tolerated["tracking_sanity_flags"])


def test_pay_intent_unattributed_rows_severity_respects_verdict_precedence():
    thresholds = dict(THRESHOLDS, pay_intent_rate_go=0.02, pay_intent_visitors_floor=300)
    flipping = compute_pay_intent_verdict(
        pay_mvp(
            ga_clicks=300,
            pay_intents=0,
            **trusted_pay_intent_db(
                db_pay_intents_paid=5,
                db_pay_intents_real=6,
                db_pay_intents_unattributed=1,
                db_pay_intents_raw=6,
            ),
        ),
        {},
        thresholds,
    )
    flag = next(f for f in flipping["tracking_sanity_flags"] if f["flag"] == "pay_intent_unattributed_rows")
    assert flag["severity"] == "high"
    assert flipping["headline_verdict"] == VERDICT_NO_GO

    already_go = compute_pay_intent_verdict(
        pay_mvp(
            ga_clicks=300,
            pay_intents=0,
            **trusted_pay_intent_db(
                db_pay_intents_paid=6,
                db_pay_intents_real=8,
                db_pay_intents_unattributed=2,
                db_pay_intents_raw=8,
            ),
        ),
        {},
        thresholds,
    )
    flag = next(f for f in already_go["tracking_sanity_flags"] if f["flag"] == "pay_intent_unattributed_rows")
    assert flag["severity"] == "info"
    assert already_go["headline_verdict"] == VERDICT_GO

    insufficient = compute_pay_intent_verdict(
        pay_mvp(
            ga_clicks=200,
            pay_intents=0,
            **trusted_pay_intent_db(
                db_pay_intents_paid=5,
                db_pay_intents_real=6,
                db_pay_intents_unattributed=1,
                db_pay_intents_raw=6,
            ),
        ),
        {},
        thresholds,
    )
    flag = next(f for f in insufficient["tracking_sanity_flags"] if f["flag"] == "pay_intent_unattributed_rows")
    assert flag["severity"] == "info"
    assert insufficient["headline_verdict"] == VERDICT_INSUFFICIENT

    ga_no_ph = compute_pay_intent_verdict(
        pay_mvp(
            ga_clicks=300,
            pay_intents=0,
            **trusted_pay_intent_db(
                db_pay_intents_paid=5,
                db_pay_intents_real=6,
                db_pay_intents_unattributed=1,
                db_pay_intents_raw=6,
            ),
        ),
        {"ga_clicks_without_ph_traffic": True},
        thresholds,
    )
    flag = next(f for f in ga_no_ph["tracking_sanity_flags"] if f["flag"] == "pay_intent_unattributed_rows")
    assert flag["severity"] == "info"
    assert ga_no_ph["headline_verdict"] == VERDICT_GA_NO_PH_TRACKING


def test_pay_intent_price_from_db_numeric_beats_posthog_string_trap():
    score = compute_pay_intent_verdict(
        pay_mvp(
            ga_clicks=300,
            pay_intents=6,
            pay_intent_price_cents="500",
            pay_intent_price_variants=1,
            **trusted_pay_intent_db(
                db_pay_intents_paid=6,
                db_pay_intent_price_cents_max=5000.0,
                db_pay_intent_price_variants=2,
            ),
        ),
        {},
        THRESHOLDS,
    )
    assert score["metrics"]["pay_intent_price_cents"] == 5000.0
    assert score["metrics"]["pay_intent_price_variants"] == 2
    assert score["metrics"]["revenue_intent_per_click"] == 100.0


def test_pay_intent_price_null_falls_back_to_posthog_price():
    score = compute_pay_intent_verdict(
        pay_mvp(
            ga_clicks=300,
            pay_intents=6,
            pay_intent_price_cents=1900,
            pay_intent_price_variants=1,
            **trusted_pay_intent_db(
                db_pay_intents_paid=6,
                db_pay_intent_price_cents_max=None,
                db_pay_intent_price_variants=0,
            ),
        ),
        {},
        THRESHOLDS,
    )
    assert score["metrics"]["pay_intent_source"] == "db_real"
    assert score["metrics"]["pay_intent_price_cents"] == 1900.0
    assert score["metrics"]["pay_intent_price_variants"] == 1


def test_pay_intent_source_present_on_orphan_and_ga_only_rows():
    for record, issues in [
        (pay_mvp(ga_clicks=0, pay_intents=0, ga_only=True), {}),
        (pay_mvp(ga_clicks=300, pay_intents=0, ga_only=True), {"ga_clicks_without_ph_traffic": True}),
        (pay_mvp(ga_clicks=300, pay_intents=0, orphan=True), {"missing_project_name": True}),
    ]:
        score = compute_pay_intent_verdict(record, issues, THRESHOLDS)
        assert score["metrics"]["pay_intent_source"] == "ph"
        assert score["metrics"]["pay_intents_db"] is None
        assert score["metrics"]["pay_intents_posthog"] == 0


def test_pay_intent_gate_uses_effective_numerator_regardless_of_source():
    thresholds = dict(THRESHOLDS, pay_intent_rate_go=0.02, pay_intent_visitors_floor=300)
    db_score = compute_pay_intent_verdict(
        pay_mvp(ga_clicks=300, pay_intents=3, **trusted_pay_intent_db(db_pay_intents_paid=6)),
        {},
        thresholds,
    )
    ph_score = compute_pay_intent_verdict(
        pay_mvp(ga_clicks=300, pay_intents=6, **trusted_pay_intent_db(db_pay_intents_unmapped_reason="no_table")),
        {},
        thresholds,
    )
    assert db_score["headline_verdict"] == VERDICT_GO
    assert db_score["metrics"]["pay_intent_source"] == "db_real"
    assert ph_score["headline_verdict"] == VERDICT_GO
    assert ph_score["metrics"]["pay_intent_source"] == "ph"


# ---------- GA-as-denominator ----------

def test_ga_clicks_used_as_denominator_when_present():
    """When mvp.ga_clicks > 0, verdict uses GA-clicks not PH visitors.

    stylica-ai real case: GA 575 / PH 201 / 33 signups. With GA denominator
    conv = 33/575 = 5.7% → below 6% threshold → NO_GO. This is exactly the
    over-counting trap the GA-first rule catches.
    """
    score = compute_headline_verdict(
        mvp(visitors=201, signups=33, ga_clicks=575),
        {},
        THRESHOLDS,
    )
    # 33/575 = 5.74% < 6% threshold → NO_GO (not GO as PH/201=16.4% would suggest).
    assert score["headline_verdict"] == VERDICT_NO_GO
    assert score["metrics"]["denominator_source"] == "ga"
    assert score["metrics"]["ga_clicks"] == 575
    assert score["metrics"]["gclid_visitors"] == 201
    assert abs(score["metrics"]["true_conv_rate"] - 33 / 575) < 1e-4
    assert abs(score["metrics"]["capture_rate"] - 201 / 575) < 1e-4


def test_ga_clicks_promotes_insuf_to_no_go_at_floor():
    """mosai real case: PH 44 visitors (below floor) but GA 100 clicks (at floor,
    0 signups → NO_GO). Workaround surfaces the deserved NO_GO."""
    score = compute_headline_verdict(
        mvp(visitors=44, signups=0, ga_clicks=100),
        {},
        THRESHOLDS,
    )
    assert score["headline_verdict"] == VERDICT_NO_GO


def test_falls_back_to_gclid_visitors_when_no_ga_data():
    """No ga_clicks → denominator_source = 'ph' and capture_rate = None."""
    score = compute_headline_verdict(
        mvp(visitors=80, signups=4),
        {},
        THRESHOLDS,
    )
    assert score["metrics"]["denominator_source"] == "ph"
    assert score["metrics"]["ga_clicks"] == 0
    assert score["metrics"]["capture_rate"] is None
    # When no GA, true_conv_rate falls back to PH-conv_rate.
    assert score["metrics"]["true_conv_rate"] == 0.05


def test_ga_clicks_zero_explicitly_uses_gclid_visitors_for_boundary():
    """ga_clicks=0 is not a real GA denominator; fall back to PH visitors."""
    score = compute_headline_verdict(
        mvp(visitors=100, signups=6, ga_clicks=0),
        {},
        THRESHOLDS,
    )
    assert score["metrics"]["denominator_source"] == "ph"
    assert score["headline_verdict"] == VERDICT_GO
    assert score["metrics"]["true_conv_rate"] == 0.06


def test_ph_overcount_capture_rate_above_100():
    """x-predict real case: GA 2055, PH 2545. capture_rate = 124% (PH over-counts)."""
    score = compute_headline_verdict(
        mvp(visitors=2545, signups=0, ga_clicks=2055),
        {},
        THRESHOLDS,
    )
    assert score["metrics"]["capture_rate"] > 1.0


# ---------- Phase-1 denominator scoping (ga_clicks_phase2 split) ----------

def _split_mvp(name="m", visitors=0, signups=0, ga_clicks=0, ga_clicks_phase2=0, **extra):
    record = mvp(name=name, visitors=visitors, signups=signups, ga_clicks=ga_clicks)
    record["ga_clicks_phase2"] = ga_clicks_phase2
    record.update(extra)
    return record


def test_phase1_scoped_denominator_flips_handpick_to_go():
    """handpick real case (2026-07): 12 signups all from the 113-click Phase-1
    flight; 258 phase2 clicks (pay-intent funnel, no signups by design) blended
    in produced a false NO_GO at 12/371=3.2%. Phase1-scoped: 12/113=10.6% → GO."""
    score = compute_headline_verdict(
        _split_mvp(visitors=311, signups=12, ga_clicks=371, ga_clicks_phase2=258),
        {},
        THRESHOLDS,
    )
    assert score["headline_verdict"] == VERDICT_GO
    assert score["metrics"]["denominator_source"] == "ga"
    assert score["metrics"]["ga_clicks"] == 371          # blended preserved
    assert score["metrics"]["ga_clicks_phase1"] == 113
    assert score["metrics"]["ga_clicks_phase2"] == 258
    assert abs(score["metrics"]["true_conv_rate"] - 12 / 113) < 1e-4
    # capture_rate stays blended/blended (PH cannot phase-split untagged flights).
    assert abs(score["metrics"]["capture_rate"] - 311 / 371) < 1e-4


def test_phase1_scoped_denominator_neuralpost_understated_go():
    """neuralpost real case: 22 signups / 246 blended (8.9%) vs 182 phase1 (12.1%)."""
    score = compute_headline_verdict(
        _split_mvp(visitors=223, signups=22, ga_clicks=246, ga_clicks_phase2=64),
        {},
        THRESHOLDS,
    )
    assert score["headline_verdict"] == VERDICT_GO
    assert score["metrics"]["ga_clicks_phase1"] == 182
    assert abs(score["metrics"]["true_conv_rate"] - 22 / 182) < 1e-4


def test_all_phase2_clicks_zero_guard_yields_insufficient_with_full_floor():
    """Blended clicks exist but ALL are phase2 → no Phase-1 traffic to judge.
    Rule 4 fires naturally: INSUFFICIENT_DATA, visitors_needed == the full floor
    (never 'need 0 more visitors'), and the score carries the zero-guard note."""
    score = compute_headline_verdict(
        _split_mvp(visitors=100, signups=5, ga_clicks=258, ga_clicks_phase2=258),
        {},
        THRESHOLDS,
    )
    assert score["headline_verdict"] == VERDICT_INSUFFICIENT
    assert score["visitors_needed"] == THRESHOLDS["visitors_floor"]
    assert score["note"] == "all paid clicks match phase2 pattern; no Phase-1 traffic in window"
    assert score["metrics"]["ga_clicks_phase1"] == 0
    # true_conv_rate falls back to the PH rate rather than dividing by zero.
    assert score["metrics"]["true_conv_rate"] == 0.05


def test_zero_guard_does_not_preempt_data_integrity_rules():
    """Precedence rules 0-3 outrank the zero-guard: a fully-phase2 MVP with
    broken tracking still gets its FIX-class verdict."""
    score = compute_headline_verdict(
        _split_mvp(visitors=50, signups=0, ga_clicks=258, ga_clicks_phase2=258),
        {"missing_project_name": True},
        THRESHOLDS,
    )
    assert score["headline_verdict"] == VERDICT_MISSING_PROJECT_NAME

    deleted = _split_mvp(visitors=50, signups=0, ga_clicks=258, ga_clicks_phase2=258)
    deleted["db_unmapped_reason"] = "project_deleted"
    score = compute_headline_verdict(deleted, {}, THRESHOLDS)
    assert score["headline_verdict"] == VERDICT_NO_GO


def test_missing_phase2_key_is_backward_compatible():
    """Records predating the split (no ga_clicks_phase2 key) behave exactly as
    before — stylica-ai fixture from test_ga_clicks_used_as_denominator_when_present."""
    score = compute_headline_verdict(
        mvp(visitors=201, signups=33, ga_clicks=575),
        {},
        THRESHOLDS,
    )
    assert score["headline_verdict"] == VERDICT_NO_GO
    assert score["metrics"]["ga_clicks_phase1"] == 575
    assert score["metrics"]["ga_clicks_phase2"] == 0
    assert abs(score["metrics"]["true_conv_rate"] - 33 / 575) < 1e-4


def test_ga_clicks_phase1_is_none_on_ph_fallback():
    score = compute_headline_verdict(mvp(visitors=80, signups=4), {}, THRESHOLDS)
    assert score["metrics"]["ga_clicks_phase1"] is None
    assert score["metrics"]["ga_clicks_phase2"] == 0
    assert score["note"] is None


def test_lifecycle_status_at_passthrough():
    record = mvp(visitors=100, signups=8, ga_clicks=100)
    record["lifecycle_status"] = "promoted"
    record["lifecycle_status_at"] = "2026-06-16T15:24:40Z"
    score = compute_headline_verdict(record, {}, THRESHOLDS)
    assert score["lifecycle_status"] == "promoted"
    assert score["lifecycle_status_at"] == "2026-06-16T15:24:40Z"
    # Passthrough never alters the verdict math (8/100 = 8% → GO).
    assert score["headline_verdict"] == VERDICT_GO


def test_ga_only_mvp_with_zero_ph_visitors_no_signups():
    """ga_only synthetic record below floor → INSUFFICIENT_DATA when no
    ga_clicks_without_ph_traffic flag set."""
    score = compute_headline_verdict(
        mvp(visitors=0, signups=0, ga_clicks=27, ga_only=True),
        {},  # no flag set
        THRESHOLDS,
    )
    assert score["headline_verdict"] == VERDICT_INSUFFICIENT
    assert score["ga_only"] is True


def test_visitors_needed_zero_for_go():
    score = compute_headline_verdict(mvp(visitors=100, signups=10), {}, THRESHOLDS)
    assert score["headline_verdict"] == VERDICT_GO
    assert score["visitors_needed"] == 0


def test_visitors_needed_zero_for_no_go():
    score = compute_headline_verdict(mvp(visitors=100, signups=0), {}, THRESHOLDS)
    assert score["headline_verdict"] == VERDICT_NO_GO
    assert score["visitors_needed"] == 0


def test_metrics_conv_rate_when_visitors_present():
    score = compute_headline_verdict(mvp(visitors=80, signups=4), {}, THRESHOLDS)
    assert score["metrics"]["conv_rate"] == 0.05


def test_metrics_conv_rate_zero_when_zero_visitors():
    score = compute_headline_verdict(mvp(visitors=0, signups=0), {}, THRESHOLDS)
    assert score["metrics"]["conv_rate"] == 0.0


def test_signup_events_carried_through():
    score = compute_headline_verdict(
        mvp(visitors=40, signups=3, signup_events=["signup_complete", "waitlist_signup"]),
        {},
        THRESHOLDS,
    )
    assert score["signup_events"] == ["signup_complete", "waitlist_signup"]


def test_verdict_enum_consistency():
    """Each verdict path returns a value in the registry-asserted enum."""
    cases = [
        (mvp(visitors=100, signups=10), {}, VERDICT_GO),       # 10% conv
        (mvp(visitors=100, signups=0), {}, VERDICT_NO_GO),     # 0% conv
        (mvp(visitors=200, signups=2), {}, VERDICT_NO_GO),     # 1% conv
        (mvp(visitors=20, signups=0), {}, VERDICT_INSUFFICIENT),
        (mvp(visitors=10, signups=0), {"no_event_data": True}, VERDICT_NO_DATA),
    ]
    for m, issues, expected in cases:
        score = compute_headline_verdict(m, issues, THRESHOLDS)
        assert score["headline_verdict"] == expected
        assert score["headline_verdict"] in VERDICT_ENUM


def test_signup_source_db_real_zero_suppresses_ph_go():
    record = mvp(visitors=100, signups=5, ga_clicks=100)
    record.update({
        "db_signups_real": 0,
        "db_signups_real_windowed": True,
        "db_source": "supabase",
        "db_unmapped_reason": None,
        "ph_signups": 5,
        "ph_signups_available": True,
    })
    score = compute_headline_verdict(record, {}, THRESHOLDS)
    assert score["headline_verdict"] == VERDICT_NO_GO
    assert score["metrics"]["signup_source"] == "db_real_zero"
    assert score["metrics"]["effective_signups"] == 0
    assert any(f["flag"] == "db_zero_with_ph_signups" for f in score["tracking_sanity_flags"])


def test_signup_source_db_paid_preferred_over_db_real_and_ph():
    record = mvp(visitors=100, signups=20, ga_clicks=100)
    record.update({
        "db_signups_paid": 4,
        "db_attribution": "gclid_shape",
        "db_signups_real": 20,
        "db_signups_real_windowed": True,
        "db_source": "supabase",
        "db_unmapped_reason": None,
        "ph_signups": 20,
        "ph_signups_available": True,
    })
    score = compute_headline_verdict(record, {}, THRESHOLDS)
    assert score["metrics"]["signup_source"] == "db_paid"
    assert score["metrics"]["effective_signups"] == 4
    assert score["metrics"]["db_signups_paid"] == 4
    assert score["metrics"]["db_attribution"] == "gclid_shape"
    assert score["headline_verdict"] == VERDICT_NO_GO


def test_signup_source_db_paid_zero_flags_ph_contradiction():
    # NOTE: since the union-dedupe fix, x0b can no longer PRODUCE this artifact
    # shape — the registry invariant rejects paid=0 with attribution="gclid_shape"
    # (a gclid-dead table now lands attribution="window" → source db_real).
    # Kept as defense-in-depth for hand-built artifacts: if a bad artifact
    # slips past the gate, the resolver must still refuse to report a false GO.
    record = mvp(visitors=100, signups=5, ga_clicks=100)
    record.update({
        "db_signups_paid": 0,
        "db_attribution": "gclid_shape",
        "db_signups_real": 10,
        "db_signups_real_windowed": True,
        "db_source": "supabase",
        "db_unmapped_reason": None,
        "ph_signups": 5,
        "ph_signups_available": True,
    })
    score = compute_headline_verdict(record, {}, THRESHOLDS)
    assert score["metrics"]["signup_source"] == "db_paid"
    assert score["metrics"]["effective_signups"] == 0
    assert any(
        f["flag"] == "db_zero_with_ph_signups" and f["severity"] == "high"
        for f in score["tracking_sanity_flags"]
    )


def test_signup_source_db_paid_rejected_when_unmapped():
    record = mvp(visitors=100, signups=8, ga_clicks=100)
    record.update({
        "db_signups_paid": 6,
        "db_attribution": "gclid_shape",
        "db_signups_real": 6,
        "db_signups_real_windowed": True,
        "db_source": "supabase",
        "db_unmapped_reason": "no_match",
        "ph_signups": 8,
        "ph_signups_available": True,
    })
    score = compute_headline_verdict(record, {}, THRESHOLDS)
    assert score["metrics"]["signup_source"] == "ph"
    assert score["metrics"]["effective_signups"] == 8


def test_signup_source_db_paid_rejected_when_out_of_bounds_falls_back_to_db_real():
    record = mvp(visitors=100, signups=8, ga_clicks=100)
    record.update({
        "db_signups_paid": 4,
        "db_attribution": "gclid_shape",
        "db_signups_real": 3,
        "db_signups_real_windowed": True,
        "db_source": "supabase",
        "db_unmapped_reason": None,
        "ph_signups": 8,
        "ph_signups_available": True,
    })
    score = compute_headline_verdict(record, {}, THRESHOLDS)
    assert not is_trusted_db_paid(record)
    assert score["metrics"]["signup_source"] == "db_real"
    assert score["metrics"]["effective_signups"] == 3


def test_db_paid_verdict_keeps_sanity_flags_on_db_real():
    record = mvp(visitors=200, signups=4, ga_clicks=200)
    record.update({
        "db_signups_paid": 4,
        "db_attribution": "gclid_shape",
        "db_signups_real": 20,
        "db_signups_real_windowed": True,
        "db_source": "railway",
        "db_unmapped_reason": None,
        "ph_signups": 4,
        "ph_signups_available": True,
    })
    score = compute_headline_verdict(record, {}, THRESHOLDS)
    assert score["metrics"]["signup_source"] == "db_paid"
    assert score["metrics"]["effective_signups"] == 4
    flags = score["tracking_sanity_flags"]
    assert any(f["flag"] == "ph_undercount" for f in flags)
    assert any("diagnostic compares PostHog paid signups against all real DB signups" in f["message"] for f in flags)


def test_money_leak_flags_project_deleted_with_recent_last_seen_deterministically():
    record = mvp(visitors=100, signups=0, ga_clicks=100)
    record.update({
        "db_unmapped_reason": "project_deleted",
        "last_seen": "2026-06-20T12:00:00Z",
    })
    assert compute_money_leak(record, "2026-06-25T00:00:00Z", window_days=14)
    score = compute_headline_verdict(
        record,
        {},
        THRESHOLDS,
        money_leak_reference_now="2026-06-25T00:00:00Z",
        money_leak_window_days=14,
    )
    assert score["metrics"]["money_leak"] is True


def test_money_leak_flags_killed_lifecycle_with_recent_last_seen():
    record = mvp(visitors=100, signups=0, ga_clicks=100)
    record.update({
        "lifecycle_status": "killed",
        "db_unmapped_reason": "no_token",
        "last_seen": "2026-06-24T00:00:00Z",
    })
    score = compute_headline_verdict(
        record,
        {},
        THRESHOLDS,
        money_leak_reference_now="2026-06-25T00:00:00Z",
    )
    assert score["lifecycle_status"] == "killed"
    assert score["last_seen"] == "2026-06-24T00:00:00Z"
    assert score["metrics"]["money_leak"] is True


def test_money_leak_rejects_stale_or_live_records():
    stale_deleted = {
        "db_unmapped_reason": "project_deleted",
        "last_seen": "2026-06-01T00:00:00Z",
    }
    live_recent = {
        "db_unmapped_reason": None,
        "lifecycle_status": "active",
        "last_seen": "2026-06-24T00:00:00Z",
    }
    assert not compute_money_leak(stale_deleted, "2026-06-25T00:00:00Z", window_days=14)
    assert not compute_money_leak(live_recent, "2026-06-25T00:00:00Z", window_days=14)


def test_main_money_leak_final_fallback_uses_wall_clock_not_max_last_seen():
    import json as _json
    import tempfile
    from datetime import datetime as _datetime
    from datetime import timezone as _timezone

    class FixedDateTime(_datetime):
        @classmethod
        def now(cls, tz=None):
            dt = cls(2026, 6, 25, 0, 0, 0, tzinfo=_timezone.utc)
            return dt if tz is None else dt.astimezone(tz)

    data = {
        "mvps": [
            {
                "name": "stale-deleted",
                "owner": "alice",
                "gclid_visitors": 100,
                "ga_clicks": 100,
                "signups": 0,
                "last_seen": "2026-05-01T00:00:00Z",
                "db_unmapped_reason": "project_deleted",
            }
        ]
    }
    issues = {"mvps": [{"name": "stale-deleted"}]}

    with tempfile.TemporaryDirectory() as td:
        data_path = os.path.join(td, "data.json")
        issues_path = os.path.join(td, "issues.json")
        out_path = os.path.join(td, "scores.json")
        _json.dump(data, open(data_path, "w"))
        _json.dump(issues, open(issues_path, "w"))

        original_datetime = verdicts.datetime
        verdicts.datetime = FixedDateTime
        try:
            rc = main([
                "--data", data_path,
                "--issues", issues_path,
                "--config", "/nonexistent.yaml",
                "--output", out_path,
            ])
        finally:
            verdicts.datetime = original_datetime

        assert rc == 0
        result = _json.load(open(out_path))
        assert result["mvps"][0]["metrics"]["money_leak"] is False


def test_signup_source_db_real_for_low_real_counts_with_ph_zero():
    """DB-first: when trusted DB is available, use it regardless of PH. Verdict
    follows conv >= 6%."""
    for n, expected in [(1, VERDICT_NO_GO), (5, VERDICT_NO_GO), (6, VERDICT_GO), (10, VERDICT_GO)]:
        record = mvp(visitors=100, signups=0, ga_clicks=100)
        record.update({
            "db_signups_real": n,
            "db_signups_real_windowed": True,
            "db_source": "railway",
            "db_unmapped_reason": None,
            "ph_signups": 0,
            "ph_signups_available": True,
        })
        score = compute_headline_verdict(record, {}, THRESHOLDS)
        assert score["headline_verdict"] == expected, f"n={n}: got {score['headline_verdict']}, expected {expected}"
        assert score["metrics"]["signup_source"] == "db_real"
        assert score["metrics"]["effective_signups"] == n


def test_signup_source_db_real_preferred_over_ph_when_both_positive():
    """Key DB-first behavior: when DB AND PH both have signal, use DB."""
    record = mvp(visitors=100, signups=14, ga_clicks=100)
    record.update({
        "db_signups_real": 17,             # DB has more (truth)
        "db_signups_real_windowed": True,
        "db_source": "supabase",
        "db_unmapped_reason": None,
        "ph_signups": 14,                  # PH undercounts
        "ph_signups_available": True,
    })
    score = compute_headline_verdict(record, {}, THRESHOLDS)
    assert score["metrics"]["signup_source"] == "db_real"
    assert score["metrics"]["effective_signups"] == 17
    # conv = 17/100 = 17% → GO
    assert score["headline_verdict"] == VERDICT_GO


def test_db_first_sanity_flags_compare_raw_ph_to_db_for_overcount():
    """DB-first verdicts still need PH-vs-DB sanity flags for bad signup_events."""
    record = mvp(visitors=100, signups=3, ga_clicks=100)
    record.update({
        "db_signups_real": 1,
        "db_signups_real_windowed": True,
        "db_source": "supabase",
        "db_unmapped_reason": None,
        "ph_signups": 3,
        "ph_signups_available": True,
    })
    score = compute_headline_verdict(record, {}, THRESHOLDS)
    assert score["metrics"]["signup_source"] == "db_real"
    assert score["metrics"]["effective_signups"] == 1
    assert score["headline_verdict"] == VERDICT_NO_GO
    assert any(f["flag"] == "ph_overcount" for f in score["tracking_sanity_flags"])


def test_db_first_sanity_flags_compare_raw_ph_to_db_for_attribution_gap():
    """DB-first must not mask PH paid=0 when DB proves real paid signups exist."""
    record = mvp(visitors=100, signups=0, ga_clicks=100)
    record.update({
        "db_signups_real": 6,
        "db_signups_real_windowed": True,
        "db_source": "railway",
        "db_unmapped_reason": None,
        "ph_signups": 0,
        "ph_signups_available": True,
    })
    score = compute_headline_verdict(record, {}, THRESHOLDS)
    assert score["metrics"]["signup_source"] == "db_real"
    assert score["metrics"]["effective_signups"] == 6
    assert score["headline_verdict"] == VERDICT_GO
    assert any(f["flag"] == "ph_attribution_broken" for f in score["tracking_sanity_flags"])


def test_db_first_sanity_flags_compare_raw_ph_to_db_for_undercount():
    """DB-first must still flag DB counts that are much higher than PH paid."""
    record = mvp(visitors=200, signups=2, ga_clicks=200)
    record.update({
        "db_signups_real": 10,
        "db_signups_real_windowed": True,
        "db_source": "supabase",
        "db_unmapped_reason": None,
        "ph_signups": 2,
        "ph_signups_available": True,
    })
    score = compute_headline_verdict(record, {}, THRESHOLDS)
    assert score["metrics"]["signup_source"] == "db_real"
    assert score["metrics"]["effective_signups"] == 10
    assert score["headline_verdict"] == VERDICT_NO_GO
    assert any(f["flag"] == "ph_undercount" for f in score["tracking_sanity_flags"])


def test_signup_source_ph_fallback_when_db_unmapped():
    """When db_unmapped_reason is set, DB is untrusted → fall back to PH."""
    record = mvp(visitors=100, signups=8, ga_clicks=100)
    record.update({
        "db_signups_real": None,
        "db_signups_real_windowed": False,
        "db_source": None,
        "db_unmapped_reason": "no_match",
        "ph_signups": 8,
        "ph_signups_available": True,
    })
    score = compute_headline_verdict(record, {}, THRESHOLDS)
    assert score["metrics"]["signup_source"] == "ph"
    assert score["metrics"]["effective_signups"] == 8
    assert score["headline_verdict"] == VERDICT_GO


def test_signup_source_ph_fallback_when_db_unmapped_even_with_count():
    """An unmapped DB count is not trusted; PH remains the fallback source."""
    record = mvp(visitors=100, signups=8, ga_clicks=100)
    record.update({
        "db_signups_real": 17,
        "db_signups_real_windowed": True,
        "db_source": "supabase",
        "db_unmapped_reason": "no_match",
        "ph_signups": 8,
        "ph_signups_available": True,
    })
    score = compute_headline_verdict(record, {}, THRESHOLDS)
    assert score["metrics"]["signup_source"] == "ph"
    assert score["metrics"]["effective_signups"] == 8
    assert score["headline_verdict"] == VERDICT_GO


def test_is_trusted_db_real_rejects_untrusted_sources():
    base = {"db_signups_real": 1, "db_signups_real_windowed": True, "db_source": "supabase", "db_unmapped_reason": None}
    assert is_trusted_db_real(base)
    for patch in [
        {"db_source": None},
        {"db_source": "unknown"},
        {"db_unmapped_reason": "query_error"},
        {"db_signups_real_windowed": False},
    ]:
        candidate = dict(base, **patch)
        assert not is_trusted_db_real(candidate)


def test_is_trusted_db_paid_gate():
    base = {
        "db_signups_paid": 1,
        "db_attribution": "gclid_shape",
        "db_signups_real": 1,
        "db_signups_real_windowed": True,
        "db_source": "supabase",
        "db_unmapped_reason": None,
    }
    assert is_trusted_db_paid(base)
    for patch in [
        {"db_signups_paid": None},
        {"db_attribution": "window"},
        {"db_source": None},
        {"db_source": "unknown"},
        {"db_unmapped_reason": "query_error"},
        {"db_signups_real_windowed": False},
        {"db_signups_paid": -1},
        {"db_signups_paid": 2},
        {"db_signups_real": None},
    ]:
        candidate = dict(base, **patch)
        assert not is_trusted_db_paid(candidate)


def test_sort_scores_global_verdict_precedence_before_owner():
    scores = [
        {"name": "weak-b", "owner": "a", "headline_verdict": VERDICT_WEAK, "metrics": {"gclid_visitors": 200}},
        {"name": "go", "owner": "z", "headline_verdict": VERDICT_GO, "metrics": {"gclid_visitors": 1}},
        {"name": "missing", "owner": "a", "headline_verdict": VERDICT_MISSING_PROJECT_NAME, "metrics": {"gclid_visitors": 1}},
    ]
    assert [s["name"] for s in sort_scores_global(scores)] == ["missing", "go", "weak-b"]


def test_sort_scores_global_uses_traffic_then_name_within_verdict():
    scores = [
        {"name": "b", "owner": "a", "headline_verdict": VERDICT_WEAK, "metrics": {"gclid_visitors": 5}},
        {"name": "a", "owner": "z", "headline_verdict": VERDICT_WEAK, "metrics": {"gclid_visitors": 5}},
        {"name": "c", "owner": "a", "headline_verdict": VERDICT_WEAK, "metrics": {"ga_clicks": 10, "gclid_visitors": 1}},
    ]
    assert [s["name"] for s in sort_scores_global(scores)] == ["c", "a", "b"]


def test_sort_scores_by_owner_groups_owner_before_global_ordering():
    scores = [
        {"name": "missing-z", "owner": "z", "headline_verdict": VERDICT_MISSING_PROJECT_NAME, "metrics": {"gclid_visitors": 100}},
        {"name": "weak-a", "owner": "a", "headline_verdict": VERDICT_WEAK, "metrics": {"gclid_visitors": 1}},
        {"name": "go-a", "owner": "a", "headline_verdict": VERDICT_GO, "metrics": {"gclid_visitors": 1}},
    ]
    assert [s["name"] for s in sort_scores_by_owner(scores)] == ["go-a", "weak-a", "missing-z"]


# ---------- Team message emission ----------

TEAM_THRESHOLDS = {"visitors_floor": 50, "conv_rate_go": 0.06}


def _insuf_row(name, owner, needed, denominator="ga", flags=None):
    return {
        "name": name,
        "owner": owner,
        "headline_verdict": VERDICT_INSUFFICIENT,
        "visitors_needed": needed,
        "metrics": {"gclid_visitors": 10, "ga_clicks": 10, "signups": 0,
                    "denominator_source": denominator},
        "tracking_sanity_flags": flags or [],
    }


def test_team_message_header_and_owner_grouping():
    scores = [
        _insuf_row("a", "alice", 40),
        _insuf_row("b", "bob", 30),
    ]
    text = emit_team_message(scores, TEAM_THRESHOLDS)
    assert text.startswith("📊 Latest Phase 1 Google Ads results: <google-doc-link>")
    assert "@alice" in text
    assert "@bob" in text
    assert "• a:" in text and "• b:" in text


def test_team_message_omits_owner_with_no_items():
    promoted = {
        "name": "handpick", "owner": "lew", "headline_verdict": VERDICT_GO,
        "visitors_needed": 0, "lifecycle_status": "promoted",
        "metrics": {"gclid_visitors": 300, "signups": 30},
    }
    scores = [promoted, _insuf_row("b", "bob", 30)]
    text = emit_team_message(scores, TEAM_THRESHOLDS)
    assert "@lew" not in text
    assert "handpick" not in text
    assert "@bob" in text


def test_team_message_excludes_missing_project_name_orphans():
    orphan = {
        "name": "__orphan_x__", "owner": None,
        "headline_verdict": VERDICT_MISSING_PROJECT_NAME,
        "visitors_needed": 0, "metrics": {"gclid_visitors": 100, "signups": 0},
    }
    text = emit_team_message([orphan], TEAM_THRESHOLDS)
    assert "__orphan_x__" not in text
    assert "No action items this run." in text


def test_team_message_excludes_promoted_and_archived_rows():
    archived = {
        "name": "old-dead", "owner": "alice", "headline_verdict": VERDICT_NO_GO,
        "visitors_needed": 0, "lifecycle_status": "killed",
        "metrics": {"gclid_visitors": 200, "signups": 1},
    }
    promoted = {
        "name": "shiny", "owner": "alice", "headline_verdict": VERDICT_GO,
        "visitors_needed": 0, "lifecycle_status": "promoted",
        "metrics": {"gclid_visitors": 300, "signups": 30},
    }
    text = emit_team_message([archived, promoted, _insuf_row("live", "alice", 5)], TEAM_THRESHOLDS)
    assert "old-dead" not in text
    assert "shiny" not in text
    assert "live" in text


def test_team_message_money_leak_only_when_still_serving():
    stopped = {
        "name": "quiet-kill", "owner": "kim", "headline_verdict": VERDICT_NO_GO,
        "visitors_needed": 0, "lifecycle_status": "killed",
        "ga_ads_all_stopped": True,
        "metrics": {"gclid_visitors": 100, "signups": 0, "money_leak": True},
    }
    burning = {
        "name": "burning-kill", "owner": "kim", "headline_verdict": VERDICT_NO_GO,
        "visitors_needed": 0, "lifecycle_status": "killed",
        "ga_ads_all_stopped": False,
        "ga_campaign_status_detail": [
            {"name": "burning-kill-search-v1", "normalized": "active"},
        ],
        "metrics": {"gclid_visitors": 100, "signups": 0, "money_leak": True},
    }
    text = emit_team_message([stopped, burning], TEAM_THRESHOLDS)
    assert "quiet-kill" not in text
    assert "burning-kill: PAUSE NOW in Google Ads — burning-kill-search-v1" in text


def test_team_message_insufficient_includes_clicks_to_floor():
    text = emit_team_message(
        [_insuf_row("ga-mvp", "a", 40, denominator="ga"),
         _insuf_row("ph-mvp", "a", 45, denominator="ph")],
        TEAM_THRESHOLDS,
    )
    assert "ga-mvp: keep running — 40 more clicks to the 50-click floor" in text
    assert "ph-mvp: keep running — 45 more visitors to the 50-visitor floor" in text


def test_team_message_includes_cpc_and_tracking_fix_items():
    cpc_no_go = {
        "name": "pricey", "owner": "b", "headline_verdict": VERDICT_NO_GO,
        "visitors_needed": 0,
        "metrics": {
            "gclid_visitors": 40, "ga_clicks": 40, "signups": 8,
            "denominator_source": "ga", "cpc_unit_economics_fail": True,
            "ga_cpc_usd": 3.5, "effective_cpc_cap_usd": 2.5,
            "implied_cac_usd": 70.0, "monthly_price_usd": 49.0,
        },
        "tracking_sanity_flags": [
            {"flag": "cpc_unit_economics_fail", "severity": "high", "message": "m"},
        ],
    }
    flagged = _insuf_row(
        "leaky", "b", 20,
        flags=[{"flag": "ph_attribution_broken", "severity": "high", "message": "m"}],
    )
    text = emit_team_message([cpc_no_go, flagged], TEAM_THRESHOLDS)
    assert "cpc_exception" in text
    assert "implied CAC $70.0 > $49.0/mo" in text
    # The CPC wording is not repeated as a flag suffix on the same bullet.
    assert "⚠ cpc_unit_economics_fail" not in text
    assert "leaky: keep running" in text and "⚠ ph_attribution_broken" in text


def test_team_message_merges_teardown_obligations_under_owner():
    obligations = [
        {"mvp": "dead-db", "owner": "bob", "teardown_state": "due",
         "db": {"status": "live"}, "hosting": {"status": "live"},
         "ads": {"status": "csv_paused"}, "killed_age_days": 7,
         "still_serving": []},
        {"mvp": "zombie-ads", "owner": "carol", "teardown_state": "waived",
         "db": {"status": "live"}, "hosting": {"status": "live"},
         "ads": {"status": "unknown"}, "killed_age_days": 3,
         "still_serving": [{"name": "zombie-ads-search-v1"}]},
    ]
    text = emit_team_message([], TEAM_THRESHOLDS, obligations=obligations)
    assert "@bob" in text
    assert "dead-db: tear down — DB:LIVE HOST:LIVE ADS:csv_paused (killed 7d ago)" in text
    assert "@carol" in text
    assert "zombie-ads: PAUSE NOW in Google Ads — zombie-ads-search-v1" in text
    # Waived rows get the pause bullet but never a teardown bullet.
    assert "zombie-ads: tear down" not in text


def test_team_message_phase2_actions_and_stopped_override():
    stopped_insuf = {
        "name": "p2-stalled", "owner": "dana", "headline_verdict": VERDICT_INSUFFICIENT,
        "visitors_needed": 30, "phase2_ads_all_stopped": True,
        "metrics": {"ga_clicks": 20, "pay_intents": 0},
    }
    go_row = {
        "name": "p2-winner", "owner": "dana", "headline_verdict": VERDICT_GO,
        "visitors_needed": 0,
        "metrics": {"ga_clicks": 60, "pay_intents": 4},
    }
    text = emit_team_message(
        [stopped_insuf, go_row],
        {"pay_intent_visitors_floor": 50, "pay_intent_rate_go": 0.02},
        phase=2,
    )
    assert text.startswith("📊 Latest Phase 2 Google Ads results:")
    assert "resume the campaign" in text            # stopped-ads override
    assert "Phase 3 eligibility" in text            # pay-intent GO action
    assert "@dana" in text


def test_team_message_empty_prints_no_action_line():
    text = emit_team_message([], TEAM_THRESHOLDS)
    assert text == "📊 Latest Phase 1 Google Ads results: <google-doc-link>\n\nNo action items this run."


def test_action_line_formats_visitors_needed():
    line = action_line(VERDICT_INSUFFICIENT, "smelt", signups=0, visitors_needed=9, visitors_floor=50)
    assert "9 more visitors" in line
    assert "50" in line


def test_action_line_weak_mentions_signups():
    line = action_line(VERDICT_WEAK, "statistica", signups=2, visitors_needed=0, visitors_floor=50)
    assert "2 signups" in line


# ---------- main() integration ----------

def test_main_requires_output_or_team_message_or_docx():
    """main() should error when no output flag (--output/--emit-team-message/--emit-docx) is given."""
    import io
    from contextlib import redirect_stderr

    err = io.StringIO()
    with redirect_stderr(err):
        rc = main(["--data", "/dev/null", "--issues", "/dev/null"])
    assert rc == 2
    assert "must specify at least one" in err.getvalue()


def test_main_writes_output_from_data_and_issues():
    """main() reads data + issues, applies verdict, writes scores.json."""
    import json as _json
    import tempfile

    data = {
        "mvps": [
            {
                "name": "diarly",
                "owner": "lego",
                "gclid_visitors": 100,
                "signups": 8,
                "signup_events": ["signup_complete"],
                "total_events_count": 745,
                "event_catalog": [],
            }
        ]
    }
    issues = {"mvps": [{"name": "diarly", "no_event_data": False}]}

    with tempfile.TemporaryDirectory() as td:
        data_path = os.path.join(td, "data.json")
        issues_path = os.path.join(td, "issues.json")
        out_path = os.path.join(td, "scores.json")
        _json.dump(data, open(data_path, "w"))
        _json.dump(issues, open(issues_path, "w"))

        rc = main([
            "--data", data_path,
            "--issues", issues_path,
            "--config", "/nonexistent.yaml",
            "--output", out_path,
        ])
        assert rc == 0
        result = _json.load(open(out_path))
        assert result["mvps"][0]["headline_verdict"] == VERDICT_GO
        assert result["mvps"][0]["metrics"]["conv_rate"] == 0.08


def test_main_scores_input_skips_recomputation():
    """When --scores is provided, the script reads it and skips data/issues recomputation."""
    import json as _json
    import tempfile

    pre_scores = {
        "thresholds": {"signups_go": 3, "visitors_floor": 50},
        "window_days": 90,
        "mvps": [
            {
                "name": "m",
                "owner": "alice",
                "headline_verdict": "GO",
                "visitors_needed": 0,
                "metrics": {"gclid_visitors": 80, "signups": 5, "conv_rate": 0.0625},
                "signup_events": ["signup_complete"],
            }
        ],
    }
    import io
    from contextlib import redirect_stdout

    with tempfile.TemporaryDirectory() as td:
        scores_path = os.path.join(td, "scores.json")
        _json.dump(pre_scores, open(scores_path, "w"))

        # Pass non-existent data/issues paths — the script must NOT touch them.
        out = io.StringIO()
        with redirect_stdout(out):
            rc = main([
                "--data", "/nonexistent-data.json",
                "--issues", "/nonexistent-issues.json",
                "--scores", scores_path,
                "--config", "/nonexistent.yaml",
                "--emit-team-message",
            ])
        assert rc == 0
        text = out.getvalue()
        assert "@alice" in text
        assert "GO" in text


def test_main_emits_visitors_floor_in_team_message():
    """The keep-running bullet references the configured visitors_floor."""
    import io
    import json as _json
    import tempfile
    from contextlib import redirect_stdout

    data = {"mvps": [{"name": "m", "owner": "alice", "gclid_visitors": 10, "signups": 0, "signup_events": []}]}
    issues = {"mvps": [{"name": "m"}]}
    config_yaml = "thresholds:\n  signups_go: 3\n  visitors_floor: 100\n"

    with tempfile.TemporaryDirectory() as td:
        data_path = os.path.join(td, "data.json")
        issues_path = os.path.join(td, "issues.json")
        cfg_path = os.path.join(td, "config.yaml")

        _json.dump(data, open(data_path, "w"))
        _json.dump(issues, open(issues_path, "w"))
        open(cfg_path, "w").write(config_yaml)

        out = io.StringIO()
        with redirect_stdout(out):
            rc = main([
                "--data", data_path,
                "--issues", issues_path,
                "--config", cfg_path,
                "--output", os.path.join(td, "scores.json"),
                "--emit-team-message",
            ])
        assert rc == 0
        text = out.getvalue()
        assert "100-visitor floor" in text  # The custom visitors_floor


# ---------- CPC discipline: compute_cpc_flags ----------

_CPC_TH = DEFAULT_CONFIG["thresholds"]
_CPC_FX = DEFAULT_CONFIG["fx_to_usd"]
_REF = "2026-06-26T00:00:00Z"


def _cpc(mvp):
    """Run compute_cpc_flags with default config; return (flagset, metrics)."""
    r = verdicts.compute_cpc_flags(mvp, _CPC_TH, fx_to_usd=_CPC_FX,
                                   max_cpc_basis="usd", reference_now=_REF)
    return {f["flag"] for f in r["flags"]}, r["metrics"]


def test_cpc_over_cap_usd_conversion_under():
    # SGD 3.0 * 0.74 = 2.22 USD < 2.5 → no over-cap flag.
    flags, m = _cpc({"ga_cpc": 3.0, "ga_currency": "SGD", "ga_clicks": 200,
                     "campaign_first_date": "2026-06-20"})
    assert "cpc_over_cap" not in flags
    assert m["ga_cpc_usd"] == 2.22


def test_cpc_over_cap_usd_conversion_over():
    # SGD 3.5 * 0.74 = 2.59 USD > 2.5 → over-cap.
    flags, _ = _cpc({"ga_cpc": 3.5, "ga_currency": "SGD", "ga_clicks": 200,
                     "campaign_first_date": "2026-06-20"})
    assert "cpc_over_cap" in flags


def test_cpc_over_cap_usd_native():
    flags, _ = _cpc({"ga_cpc": 9.0, "ga_currency": "USD", "ga_clicks": 12,
                     "campaign_first_date": "2026-06-20"})
    assert "cpc_over_cap" in flags


def test_channel_starved_fires_aged_lowclicks():
    flags, m = _cpc({"ga_cpc": 2.0, "ga_currency": "USD", "ga_clicks": 30,
                     "campaign_first_date": "2026-05-01"})
    assert "channel_starved" in flags
    assert m["campaign_age_days"] >= 21


def test_channel_starved_fires_for_ga_only():
    # ga_only record: no PH, no currency → currency defaults USD, still evaluates.
    flags, _ = _cpc({"ga_cpc": 1.5, "ga_currency": None, "ga_clicks": 20,
                     "campaign_first_date": "2026-05-01", "ga_only": True})
    assert "channel_starved" in flags


def test_channel_starved_skips_young_campaign():
    flags, _ = _cpc({"ga_cpc": 2.0, "ga_currency": "USD", "ga_clicks": 30,
                     "campaign_first_date": "2026-06-22"})  # ~4 days old
    assert "channel_starved" not in flags


def test_channel_starved_skips_above_floor():
    flags, _ = _cpc({"ga_cpc": 2.0, "ga_currency": "USD", "ga_clicks": 80,
                     "campaign_first_date": "2026-05-01"})  # >= channel_floor(50)
    assert "channel_starved" not in flags


def test_cpc_exception_suppresses_and_raises_cap():
    flags, m = _cpc({"ga_cpc": 4.0, "ga_currency": "USD", "ga_clicks": 80,
                     "campaign_first_date": "2026-06-20",
                     "cpc_exception": {"reason": "high LTV", "max_cpc_override": 5.0}})
    assert "cpc_over_cap" not in flags
    assert m["effective_cpc_cap_usd"] == 5.0


def test_expired_cpc_exception_does_not_suppress():
    flags, _ = _cpc({"ga_cpc": 4.0, "ga_currency": "USD", "ga_clicks": 80,
                     "campaign_first_date": "2026-06-20",
                     "cpc_exception": {"reason": "x", "max_cpc_override": 5.0,
                                       "expires_at": "2026-06-01"}})
    assert "cpc_over_cap" in flags


def test_channel_waiver_suppresses_starved():
    flags, _ = _cpc({"ga_cpc": 2.0, "ga_currency": "USD", "ga_clicks": 30,
                     "campaign_first_date": "2026-05-01",
                     "channel_waiver": {"reason": "strategic"}})
    assert "channel_starved" not in flags


def test_cpc_currency_unmapped_falls_back_native():
    flags, _ = _cpc({"ga_cpc": 3.0, "ga_currency": "EUR", "ga_clicks": 200,
                     "campaign_first_date": "2026-06-20"})
    assert "cpc_currency_unmapped" in flags
    assert "cpc_over_cap" in flags  # native 3.0 > 2.5 (no silent pass)


def test_no_cost_no_cpc_flags():
    flags, _ = _cpc({"ga_cpc": None, "ga_currency": None, "ga_clicks": 200,
                     "campaign_first_date": "2026-06-20"})
    assert not (flags & {"cpc_over_cap", "channel_starved"})


def test_channel_starved_fires_zero_click_no_cpc():
    # The starved-est case: 0 clicks → no CPC exists ($0 spend can't be over
    # cap) → counts as in-cap. Previously the None-guard skipped exactly this.
    r = verdicts.compute_cpc_flags(
        {"ga_cpc": None, "ga_currency": None, "ga_clicks": 0,
         "campaign_first_date": "2026-05-01"},
        _CPC_TH, fx_to_usd=_CPC_FX, max_cpc_basis="usd", reference_now=_REF)
    starved = [f for f in r["flags"] if f["flag"] == "channel_starved"]
    assert len(starved) == 1
    assert "0 clicks" in starved[0]["message"]


def test_channel_starved_zero_click_waiver_suppresses():
    flags, _ = _cpc({"ga_cpc": None, "ga_currency": None, "ga_clicks": 0,
                     "campaign_first_date": "2026-05-01",
                     "channel_waiver": {"reason": "strategic"}})
    assert "channel_starved" not in flags


def test_channel_starved_cpc_none_with_clicks_still_skipped():
    # Cost column absent but clicks exist → no proof of in-cap → no flag.
    flags, _ = _cpc({"ga_cpc": None, "ga_currency": None, "ga_clicks": 30,
                     "campaign_first_date": "2026-05-01"})
    assert "channel_starved" not in flags


def test_cpc_flags_do_not_change_headline_verdict():
    # An over-cap MVP that still converts >= 6% must remain GO; the flag rides
    # tracking_sanity_flags and the metrics carry CPC, but the verdict is unchanged.
    m = mvp(name="rich", visitors=0, signups=10, signup_events=["signup_complete"],
            ga_clicks=100)
    m.update({"ga_cpc": 9.0, "ga_currency": "USD", "ga_cost": 900.0,
              "campaign_first_date": "2026-06-20",
              "db_signups_real": 10, "db_signups": 10})
    score = compute_headline_verdict(m, {}, THRESHOLDS,
                                     money_leak_reference_now=_REF,
                                     fx_to_usd=_CPC_FX, max_cpc_basis="usd")
    assert score["headline_verdict"] == VERDICT_GO
    flagset = {f["flag"] for f in score["tracking_sanity_flags"]}
    assert "cpc_over_cap" in flagset
    assert score["metrics"]["ga_cpc_usd"] == 9.0
    assert score["metrics"]["ga_cost"] == 900.0


# ---------- CPC unit-economics gate (verdict-changing) ----------


def _econ_mvp(monthly_price=None, ga_cpc=3.16, ga_clicks=100, signups=7, **extra):
    """Over-cap (CPC $3.16) MVP that would otherwise be GO (7% conv on 100 clicks)."""
    m = mvp(name="econ", visitors=0, signups=signups,
            signup_events=["signup_complete"], ga_clicks=ga_clicks)
    m.update({"ga_cpc": ga_cpc, "ga_currency": "USD",
              "ga_cost": round(ga_cpc * ga_clicks, 2),
              "campaign_first_date": "2026-06-20",
              "db_signups_real": signups, "db_signups": signups,
              "db_attribution": "window"})
    if monthly_price is not None:
        m["monthly_price_usd"] = monthly_price
    m.update(extra)
    return m


def _econ_verdict(m, issues=None, thresholds=None):
    return compute_headline_verdict(m, issues or {}, thresholds or THRESHOLDS,
                                    money_leak_reference_now=_REF,
                                    fx_to_usd=_CPC_FX, max_cpc_basis="usd")


def test_cpc_economics_forces_no_go_when_cac_exceeds_price():
    # CPC 3.16 * 20 = 63.2 implied CAC > $50 monthly price → NO_GO.
    score = _econ_verdict(_econ_mvp(monthly_price=50))
    assert score["headline_verdict"] == VERDICT_NO_GO
    flagset = {f["flag"] for f in score["tracking_sanity_flags"]}
    assert "cpc_unit_economics_fail" in flagset
    assert score["metrics"]["cpc_unit_economics_fail"] is True
    assert score["metrics"]["implied_cac_usd"] == 63.2
    assert score["metrics"]["monthly_price_usd"] == 50


def test_cpc_economics_affordable_price_stays_go():
    # CPC*20 = 63.2 <= $70 → economics OK → GO (over-cap advisory rides along).
    score = _econ_verdict(_econ_mvp(monthly_price=70))
    assert score["headline_verdict"] == VERDICT_GO
    flagset = {f["flag"] for f in score["tracking_sanity_flags"]}
    assert "cpc_unit_economics_fail" not in flagset
    assert "cpc_over_cap" in flagset
    assert score["metrics"]["cpc_unit_economics_fail"] is False


def test_cpc_economics_price_unmapped_is_advisory_only():
    # Over cap but monthly_price unset → cannot evaluate → advisory flag, no NO_GO.
    score = _econ_verdict(_econ_mvp(monthly_price=None))
    assert score["headline_verdict"] == VERDICT_GO
    flagset = {f["flag"] for f in score["tracking_sanity_flags"]}
    assert "cpc_price_unmapped" in flagset
    assert "cpc_unit_economics_fail" not in flagset


def test_cpc_economics_exception_bypasses_gate():
    # Operator's "special approval" keeps an over-cap unprofitable MVP at GO.
    score = _econ_verdict(_econ_mvp(monthly_price=50,
                                    cpc_exception={"reason": "strategic LTV"}))
    assert score["headline_verdict"] == VERDICT_GO
    flagset = {f["flag"] for f in score["tracking_sanity_flags"]}
    assert "cpc_unit_economics_fail" not in flagset
    assert "cpc_over_cap" not in flagset  # exception suppresses over_cap too


def test_cpc_economics_under_cap_no_gate():
    # CPC 2.0 <= cap → the gate never evaluates even with a tiny price.
    score = _econ_verdict(_econ_mvp(monthly_price=10, ga_cpc=2.0))
    assert score["headline_verdict"] == VERDICT_GO
    assert score["metrics"]["cpc_unit_economics_fail"] is False


def test_cpc_economics_overrides_insufficient():
    # Below the visitor floor (50 clicks) AND over-cap-unprofitable → NO_GO, not INSUFFICIENT.
    score = _econ_verdict(_econ_mvp(monthly_price=50, ga_clicks=50, signups=2))
    assert score["headline_verdict"] == VERDICT_NO_GO
    assert score["visitors_needed"] == 0


def test_cpc_economics_does_not_override_data_integrity_verdicts():
    # Fix tracking first: an economics call on untrusted data is meaningless.
    score = _econ_verdict(_econ_mvp(monthly_price=50),
                          issues={"missing_project_name": True})
    assert score["headline_verdict"] == VERDICT_MISSING_PROJECT_NAME


def test_cpc_economics_configurable_multiple():
    # Lower the multiple to 10 → 3.16*10 = 31.6 <= $50 → no longer fails.
    th = dict(THRESHOLDS, cpc_payback_multiple=10)
    score = _econ_verdict(_econ_mvp(monthly_price=50), thresholds=th)
    assert score["headline_verdict"] == VERDICT_GO
    assert score["metrics"]["cpc_payback_multiple"] == 10
    assert score["metrics"]["implied_cac_usd"] == 31.6


# ---------- CPC dual basis under the phase2 split (gate=phase1, advisory=blended) ----------

def test_cpc_no_split_phase1_equals_blended():
    # Without a phase2 split the phase1 CPC IS the blended CPC — gate behavior
    # identical to pre-split (existing econ tests above pin this); metric present.
    flags, m = _cpc({"ga_cpc": 3.16, "ga_currency": "USD", "ga_clicks": 100,
                     "campaign_first_date": "2026-06-20"})
    assert m["ga_cpc_phase1"] == 3.16


def test_cpc_gate_fires_on_phase1_slice_even_when_blended_under_cap():
    # Phase-1 slice over cap (350/100 = $3.50) while blended is under ($2.00):
    # the verdict-changing gate runs on the phase1 basis → forced NO_GO; the
    # advisory cpc_over_cap worklist flag stays blended → absent here.
    score = _econ_verdict(_econ_mvp(
        monthly_price=50, ga_cpc=2.0, ga_clicks=200,
        ga_clicks_phase2=100, ga_cost_phase2=50.0,
    ))
    assert score["headline_verdict"] == VERDICT_NO_GO
    flagset = {f["flag"] for f in score["tracking_sanity_flags"]}
    assert "cpc_unit_economics_fail" in flagset
    assert "cpc_over_cap" not in flagset
    assert score["metrics"]["ga_cpc_phase1"] == 3.5
    assert score["metrics"]["implied_cac_usd"] == 70.0


def test_cpc_gate_skips_when_phase1_under_cap_but_blended_over():
    # Blended CPC $3.16 over cap keeps the advisory worklist flag, but the
    # phase1 slice is cheap ((632-482)/100 = $1.50) → economics gate must NOT
    # force NO_GO (7/100 = 7% conv → GO stands).
    score = _econ_verdict(_econ_mvp(
        monthly_price=50, ga_cpc=3.16, ga_clicks=200,
        ga_clicks_phase2=100, ga_cost_phase2=482.0,
    ))
    assert score["headline_verdict"] == VERDICT_GO
    flagset = {f["flag"] for f in score["tracking_sanity_flags"]}
    assert "cpc_over_cap" in flagset
    assert "cpc_unit_economics_fail" not in flagset
    assert score["metrics"]["ga_cpc_phase1"] == 1.5
    assert score["metrics"]["implied_cac_usd"] == 30.0


def test_cpc_split_without_cost_disables_gate():
    # Split present but no Cost column → phase1 CPC underivable → gate off
    # (same graceful degradation as today's cost-less exports).
    flags, m = _cpc({"ga_clicks": 200, "ga_clicks_phase2": 100,
                     "campaign_first_date": "2026-06-20"})
    assert m["ga_cpc_phase1"] is None
    assert "cpc_unit_economics_fail" not in flags
    assert "cpc_over_cap" not in flags


# Self-runner so this file works without pytest installed.


# ---------- compute_pay_intent_wiring_flag (B1) ----------

def _wiring_mvp(**over):
    base = {
        "name": "neuralpost",
        "ga_clicks": 64,
        "first_seen": "2026-06-29T03:35:03Z",
        "ph_last_pay_intent_any_at": "2026-06-15T03:29:57Z",
        "db_last_pay_intent_at": "2026-06-15 03:29:57.001721+00:00",
    }
    base.update(over)
    return base


def test_pay_intent_wiring_unproven_fires_when_no_pay_intent_ever_on_both_sides():
    flag = compute_pay_intent_wiring_flag(_wiring_mvp(), 0)
    assert flag is not None
    assert flag["flag"] == "pay_intent_wiring_unproven"
    assert flag["severity"] == "info"  # 64 clicks < 150
    assert "2026-06-29" in flag["message"]
    assert "dayzero probe" in flag["message"]


def test_pay_intent_wiring_severity_boundary_150_vs_149_clicks():
    assert compute_pay_intent_wiring_flag(_wiring_mvp(ga_clicks=149), 0)["severity"] == "info"
    assert compute_pay_intent_wiring_flag(_wiring_mvp(ga_clicks=150), 0)["severity"] == "high"


def test_pay_intent_wiring_threshold_overridable_via_thresholds():
    thresholds = dict(DEFAULT_CONFIG["thresholds"])
    thresholds["pay_intent_wiring_high_clicks"] = 50
    assert compute_pay_intent_wiring_flag(_wiring_mvp(ga_clicks=64), 0, thresholds)["severity"] == "high"


def test_pay_intent_wiring_not_flagged_when_db_probe_row_postdates_first_seen():
    # A fresh dayzero-probe row after campaign start proves the wiring.
    mvp = _wiring_mvp(db_last_pay_intent_at="2026-07-10 08:00:00+00:00")
    assert compute_pay_intent_wiring_flag(mvp, 0) is None
    mvp2 = _wiring_mvp(ph_last_pay_intent_any_at="2026-07-04T13:40:38Z")
    assert compute_pay_intent_wiring_flag(mvp2, 0) is None


def test_pay_intent_wiring_not_flagged_when_effective_pay_intents_positive():
    assert compute_pay_intent_wiring_flag(_wiring_mvp(), 3) is None


def test_pay_intent_wiring_skipped_without_first_seen_ga_only_rows():
    assert compute_pay_intent_wiring_flag(_wiring_mvp(first_seen=None), 0) is None
    assert compute_pay_intent_wiring_flag(_wiring_mvp(ga_clicks=0), 0) is None


def test_pay_intent_wiring_unparseable_and_missing_sides_named_in_message():
    mvp = _wiring_mvp(ph_last_pay_intent_any_at=None, db_last_pay_intent_at="not-a-date")
    flag = compute_pay_intent_wiring_flag(mvp, 0)
    assert flag is not None
    assert "PH not checkable" in flag["message"]
    assert "unparseable" in flag["message"]


# ---------- compute_price_change_flag (B4) ----------

def _variant(price, n, first, last):
    return {"price_cents": price, "pay_intents": n, "first_at": first, "last_at": last}


def test_price_change_flag_sequential_disjoint_ranges_info_with_counts_in_message():
    mvp = {
        "pay_intent_price_variant_rows": [
            _variant("20000", 2, "2026-07-04T13:40:38Z", "2026-07-05T19:27:09Z"),
            _variant("10000", 1, "2026-07-14T00:58:53Z", "2026-07-14T00:58:53Z"),
        ]
    }
    flag = compute_price_change_flag(mvp)
    assert flag is not None
    assert flag["flag"] == "price_change_mid_phase"
    assert flag["severity"] == "info"
    assert "20000¢: 2 intents" in flag["message"]
    assert "10000¢: 1 intents" in flag["message"]
    assert flag["message"].index("20000¢") < flag["message"].index("10000¢")  # chronological


def test_price_change_flag_interleaved_or_single_variant_returns_none():
    interleaved = {
        "pay_intent_price_variant_rows": [
            _variant("20000", 3, "2026-07-01T00:00:00Z", "2026-07-10T00:00:00Z"),
            _variant("10000", 2, "2026-07-05T00:00:00Z", "2026-07-12T00:00:00Z"),
        ]
    }
    assert compute_price_change_flag(interleaved) is None
    single = {"pay_intent_price_variant_rows": [_variant("20000", 3, "2026-07-01T00:00:00Z", "2026-07-10T00:00:00Z")]}
    assert compute_price_change_flag(single) is None
    assert compute_price_change_flag({}) is None


def test_price_change_flag_24h_gap_boundary_exclusive():
    exactly_24h = {
        "pay_intent_price_variant_rows": [
            _variant("20000", 1, "2026-07-01T00:00:00Z", "2026-07-02T00:00:00Z"),
            _variant("10000", 1, "2026-07-03T00:00:00Z", "2026-07-03T12:00:00Z"),
        ]
    }
    assert compute_price_change_flag(exactly_24h) is None  # gap == 24h -> not sequential
    over_24h = {
        "pay_intent_price_variant_rows": [
            _variant("20000", 1, "2026-07-01T00:00:00Z", "2026-07-02T00:00:00Z"),
            _variant("10000", 1, "2026-07-03T00:00:01Z", "2026-07-03T12:00:00Z"),
        ]
    }
    assert compute_price_change_flag(over_24h) is not None


# ---------- extra_sanity_flags channel + verdict integration ----------

def _phase2_mvp(**over):
    base = {
        "name": "handpick",
        "ga_clicks": 258,
        "pay_intents": 3,
        "gclid_visitors_phase2": 197,
        "first_seen": "2026-06-29T16:20:32Z",
        "ph_last_pay_intent_any_at": "2026-07-14T00:58:53Z",
    }
    base.update(over)
    return base


def test_extra_sanity_flags_concatenated_after_source_flags():
    foreign = {"flag": "foreign_campaign_traffic", "severity": "high", "message": "m"}
    mvp = _phase2_mvp(extra_sanity_flags=[foreign])
    score = compute_pay_intent_verdict(mvp, {}, DEFAULT_CONFIG["thresholds"])
    assert foreign in score["tracking_sanity_flags"]


def test_extra_sanity_flags_malformed_entries_dropped():
    mvp = _phase2_mvp(extra_sanity_flags=["junk", {"severity": "high"}, None])
    score = compute_pay_intent_verdict(mvp, {}, DEFAULT_CONFIG["thresholds"])
    assert score["tracking_sanity_flags"] == []


def test_pay_intent_wiring_never_changes_headline_verdict():
    thresholds = DEFAULT_CONFIG["thresholds"]
    silent = _phase2_mvp(
        name="neuralpost",
        ga_clicks=400,
        pay_intents=0,
        ph_last_pay_intent_any_at="2026-06-15T00:00:00Z",
        db_last_pay_intent_at=None,
        first_seen="2026-06-29T00:00:00Z",
    )
    with_flag = compute_pay_intent_verdict(dict(silent), {}, thresholds)
    stripped = dict(silent)
    stripped.pop("ph_last_pay_intent_any_at")
    stripped.pop("db_last_pay_intent_at")
    without_flag = compute_pay_intent_verdict(stripped, {}, thresholds)
    assert any(f["flag"] == "pay_intent_wiring_unproven" and f["severity"] == "high"
               for f in with_flag["tracking_sanity_flags"])
    assert with_flag["headline_verdict"] == without_flag["headline_verdict"] == VERDICT_NO_GO


def test_load_config_merges_cross_campaign_whitelist_and_defaults_empty(tmp_path):
    import json as _json
    assert DEFAULT_CONFIG["cross_campaign_whitelist"] == []
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text("cross_campaign_whitelist:\n- handpick-search-phase2-v1\n", encoding="utf-8")
    cfg = verdicts.load_config(str(cfg_path))
    assert cfg["cross_campaign_whitelist"] == ["handpick-search-phase2-v1"]
    assert verdicts.load_config(None)["cross_campaign_whitelist"] == []


def test_pay_intent_score_includes_partial_tracking_pct_passthrough():
    score = compute_pay_intent_verdict(
        _phase2_mvp(partial_tracking_pct=0.0625), {}, DEFAULT_CONFIG["thresholds"]
    )
    assert score["partial_tracking_pct"] == 0.0625
    score_none = compute_pay_intent_verdict(_phase2_mvp(), {}, DEFAULT_CONFIG["thresholds"])
    assert score_none["partial_tracking_pct"] is None


# ---------- INSUF futility triage (annotate_futility) ----------


def _insuf_score(name, ga_p1, k_eff, ph=None, last_seen=None, verdict=VERDICT_INSUFFICIENT):
    return {
        "name": name,
        "headline_verdict": verdict,
        "last_seen": last_seen,
        "metrics": {
            "ga_clicks": ga_p1,
            "ga_clicks_phase1": ga_p1,
            "gclid_visitors": ga_p1,
            "effective_signups": k_eff,
            "ph_signups": ph,
        },
    }


def test_futility_probability_boundaries_and_known_values():
    floor, rate = 100, 0.06
    # Already at/over the bar → certainty either way.
    assert verdicts.futility_probability(50, 6, floor, rate) == 1.0
    assert verdicts.futility_probability(100, 3, floor, rate) == 0.0
    assert verdicts.futility_probability(120, 3, floor, rate) == 0.0
    # Mathematically impossible: 0 signups at 97 clicks needs 6 in 3 remaining.
    assert verdicts.futility_probability(97, 0, floor, rate) == 0.0
    # Dead: 1 signup at 95 clicks needs 5 more in 5 clicks at ~2% posterior.
    assert verdicts.futility_probability(95, 1, floor, rate) < 0.001
    # Alive: 5 signups at 35 clicks (14%+) almost certainly clears 6 at 100.
    assert verdicts.futility_probability(35, 5, floor, rate) > 0.99
    # Calibration anchors from the 2026-07-19 portfolio triage.
    assert verdicts.futility_probability(80, 2, floor, rate) < 0.05
    assert verdicts.futility_probability(62, 4, floor, rate) > 0.5
    # Probabilities are valid.
    p = verdicts.futility_probability(40, 1, floor, rate)
    assert 0.0 <= p <= 1.0


def test_annotate_futility_bucket_assignment():
    thresholds = dict(DEFAULT_CONFIG["thresholds"])
    ref = "2026-07-18T00:00:00Z"
    scores = [
        # Both numerators dead → kill_candidate.
        _insuf_score("dead", 80, 0, ph=0, last_seen="2026-07-16T00:00:00Z"),
        # DB says futile-ish, PH numerator clears easily → verify_data
        # (pagoo pattern: 36 clicks, DB 0, PH 11).
        _insuf_score("discrepant", 36, 0, ph=11, last_seen="2026-07-16T00:00:00Z"),
        # Healthy posterior but campaign stopped 8 weeks ago → revive_candidate.
        _insuf_score("dormant", 35, 5, ph=5, last_seen="2026-05-22T00:00:00Z"),
        # Healthy-ish and still running → keep.
        _insuf_score("running", 69, 4, ph=4, last_seen="2026-07-17T00:00:00Z"),
        # Tiny sample → too_new regardless of numbers.
        _insuf_score("tiny", 5, 0, ph=3, last_seen="2026-07-16T00:00:00Z"),
    ]
    verdicts.annotate_futility(scores, thresholds, reference_now=ref)
    buckets = {s["name"]: s["metrics"]["futility_bucket"] for s in scores}
    assert buckets == {
        "dead": "kill_candidate",
        "discrepant": "verify_data",
        "dormant": "revive_candidate",
        "running": "keep",
        "tiny": "too_new",
    }
    for s in scores:
        met = s["metrics"]
        assert 0.0 <= met["futility_prob"] <= 1.0
        assert met["futility_prob_ph"] >= met["futility_prob"]
        assert met["futility_bucket"] in verdicts.FUTILITY_BUCKETS


def test_annotate_futility_leaves_non_insuf_rows_untouched():
    thresholds = dict(DEFAULT_CONFIG["thresholds"])
    go_row = _insuf_score("winner", 200, 30, ph=30, verdict=VERDICT_GO)
    no_go_row = _insuf_score("loser", 200, 1, ph=1, verdict=VERDICT_NO_GO)
    verdicts.annotate_futility([go_row, no_go_row], thresholds, reference_now=None)
    for row in (go_row, no_go_row):
        assert "futility_bucket" not in row["metrics"]
        assert "futility_prob" not in row["metrics"]


def test_annotate_futility_dual_numerator_guard_blocks_kill():
    # DB-zero row whose PostHog count would clear the bar must NEVER be a
    # kill_candidate — data quality blocks the statistical call.
    thresholds = dict(DEFAULT_CONFIG["thresholds"])
    row = _insuf_score("ph-alive", 49, 0, ph=4, last_seen="2026-07-16T00:00:00Z")
    verdicts.annotate_futility([row], thresholds, reference_now="2026-07-18T00:00:00Z")
    assert row["metrics"]["futility_bucket"] != "kill_candidate"


def test_annotate_futility_no_reference_now_never_marks_stale():
    thresholds = dict(DEFAULT_CONFIG["thresholds"])
    row = _insuf_score("dormant", 35, 5, ph=5, last_seen="2026-01-01T00:00:00Z")
    verdicts.annotate_futility([row], thresholds, reference_now=None)
    # Without a reference clock the stale signal is unknowable → keep, not revive.
    assert row["metrics"]["futility_campaign_stale"] is False
    assert row["metrics"]["futility_bucket"] == "keep"


# ---------- Stalled-flow triage (annotate_stalled) ----------

_S_TH = DEFAULT_CONFIG["thresholds"]
_S_REF = "2026-07-22T00:00:00Z"


def _stalled_score(name="s", ga_clicks=0, age=23, impressions=None,
                   verdict=VERDICT_INSUFFICIENT, **extra):
    """Score shape after compute_headline_verdict, pre-annotation."""
    score = {
        "name": name,
        "headline_verdict": verdict,
        "metrics": {
            "ga_clicks": ga_clicks,
            "ga_clicks_phase1": ga_clicks,
            "gclid_visitors": 0,
            "campaign_age_days": age,
            "ga_impressions": impressions,
        },
    }
    score.update(extra)
    return score


def _prev(name, ga_clicks, last_run, since=None, streak=0, bucket=None, cause=None,
          first_seen=None):
    cur = {"ga_clicks": ga_clicks, "last_run": last_run,
           "stalled_since": since, "stalled_streak": streak}
    if bucket is not None:
        cur["stalled_bucket"] = bucket
    if cause is not None:
        cur["stalled_cause"] = cause
    row = {"mvp": name, "current": cur}
    if first_seen is not None:
        row["first_seen_in_ledger"] = first_seen
    return {name: row}


def _stall(score, prev_ledger=None, ref=_S_REF):
    verdicts.annotate_stalled([score], _S_TH, prev_ledger, reference_now=ref)
    return score["metrics"]


def test_annotate_stalled_zero_delta_first_flag_no_escalation():
    m = _stall(_stalled_score("x402-wrap", ga_clicks=19),
               _prev("x402-wrap", 19, "2026-07-19"))
    assert m["stalled_bucket"] == "stalled"
    assert m["click_delta"] == 0 and m["delta_days"] == 3
    assert m["stalled_streak"] == 1
    assert m["stalled_since"] == "2026-07-19"
    assert m["stalled_escalated"] is False  # first flagged run never escalates


def test_annotate_stalled_second_run_sustained_escalates():
    m = _stall(_stalled_score("x402-wrap", ga_clicks=19),
               _prev("x402-wrap", 19, "2026-07-21", since="2026-07-05", streak=1))
    assert m["stalled_bucket"] == "stalled"
    assert m["stalled_streak"] == 2
    assert m["stalled_since"] == "2026-07-05"  # carried, not reset
    assert m["stalled_escalated"] is True      # 17d sustained >= 14


def test_annotate_stalled_streak2_not_sustained_no_escalation():
    m = _stall(_stalled_score("s", ga_clicks=19),
               _prev("s", 19, "2026-07-21", since="2026-07-12", streak=1))
    assert m["stalled_streak"] == 2
    assert m["stalled_escalated"] is False  # only 10d sustained < 14


def test_annotate_stalled_growth_clears_state():
    m = _stall(_stalled_score("s", ga_clicks=60),
               _prev("s", 10, "2026-07-19", since="2026-06-29", streak=3))
    assert m["click_delta"] == 50
    assert m["stalled_bucket"] == "none"  # ETA (100-60)/(60/23) ≈ 15d < 45
    assert m["stalled_streak"] == 0 and m["stalled_since"] is None


def test_annotate_stalled_click_decrease_clears():
    # Window slide / relaunch cut: blended clicks can shrink → conservative reset.
    m = _stall(_stalled_score("s", ga_clicks=60),
               _prev("s", 90, "2026-07-19", since="2026-06-29", streak=2))
    assert m["click_delta"] == -30
    assert m["stalled_bucket"] == "none"
    assert m["stalled_streak"] == 0


def test_annotate_stalled_zero_clicks_hard_stall_without_prev():
    # scangap shape: lifetime-zero clicks needs no previous ledger row.
    m = _stall(_stalled_score("scangap", ga_clicks=0, age=23))
    assert m["stalled_bucket"] == "stalled"
    assert m["stalled_streak"] == 1
    assert m["stalled_since"] == "2026-06-29"  # ref − age = campaign start
    assert m["stalled_age_days"] == 23
    assert m["stalled_escalated"] is False
    assert m["stalled_eta_days"] is None       # zero velocity → infinite


def test_annotate_stalled_slow_eta():
    # skyvault shape: trickling — ETA (100-7)/(7/23) ≈ 306d ≫ 45.
    m = _stall(_stalled_score("skyvault", ga_clicks=7, age=23))
    assert m["stalled_bucket"] == "stalled_slow"
    assert m["stalled_eta_days"] > 45
    assert m["stalled_escalated"] is False  # stalled_slow never escalates in v1


def test_annotate_stalled_eta_ok_stays_none():
    m = _stall(_stalled_score("s", ga_clicks=60, age=23))
    assert m["stalled_bucket"] == "none"
    assert m["stalled_eta_days"] is None


def test_annotate_stalled_young_campaign_skipped():
    m = _stall(_stalled_score("s", ga_clicks=0, age=4))
    assert m["stalled_bucket"] == "none"
    assert m["click_delta"] is None


def test_annotate_stalled_age_none_skipped():
    # First-ever sighting: no GA Start date AND no prior ledger row → no call.
    m = _stall(_stalled_score("brand-new", ga_clicks=0, age=None))
    assert m["stalled_bucket"] == "none"
    assert m["stalled_age_days"] is None


def test_annotate_stalled_age_fallback_from_ledger_first_seen():
    # Real exports often omit Start date (2026-07-21 run: 0/101 records had
    # it) — channel_starved was permanently silent because of exactly this.
    # Stalled falls back to days-in-ledger so it still fires.
    m = _stall(_stalled_score("scangap", ga_clicks=0, age=None),
               _prev("scangap", 0, "2026-07-21", first_seen="2026-06-29"))
    assert m["stalled_age_days"] == 23          # ref 07-22 − first_seen 06-29
    assert m["stalled_bucket"] == "stalled"
    assert m["stalled_since"] == "2026-06-29"   # ref − ledger age (lower bound)


def test_annotate_stalled_ledger_age_below_gate_skipped():
    # Fallback age is still gated: 4 days in the ledger → too young to judge.
    m = _stall(_stalled_score("young", ga_clicks=0, age=None),
               _prev("young", 0, "2026-07-21", first_seen="2026-07-18"))
    assert m["stalled_bucket"] == "none"


def test_annotate_stalled_waiver_suppresses():
    m = _stall(_stalled_score("s", ga_clicks=0,
                              channel_waiver={"reason": "strategic"}))
    assert m["stalled_bucket"] == "none"


def test_annotate_stalled_expired_waiver_does_not_suppress():
    m = _stall(_stalled_score("s", ga_clicks=0,
                              channel_waiver={"reason": "x", "expires_at": "2026-07-01"}))
    assert m["stalled_bucket"] == "stalled"


def test_annotate_stalled_relaunch_protection_suppresses():
    m = _stall(_stalled_score("s", ga_clicks=0, phase1_relaunch_at="2026-07-10"))
    assert m["stalled_bucket"] == "none"


def test_annotate_stalled_non_insuf_untouched():
    go_row = _stalled_score("winner", ga_clicks=200, verdict=VERDICT_GO)
    verdicts.annotate_stalled([go_row], _S_TH, {}, reference_now=_S_REF)
    assert "stalled_bucket" not in go_row["metrics"]


def test_annotate_stalled_killed_promoted_skipped():
    row = _stalled_score("dead", ga_clicks=0, lifecycle_status="killed")
    verdicts.annotate_stalled([row], _S_TH, {}, reference_now=_S_REF)
    assert "stalled_bucket" not in row["metrics"]


def test_annotate_stalled_same_day_rerun_idempotent():
    prev = _prev("s", 19, "2026-07-22", since="2026-07-05", streak=2,
                 bucket="stalled", cause="zero_serve")
    row = _stalled_score("s", ga_clicks=19)
    m1 = dict(_stall(row, prev))
    assert m1["delta_days"] == 0
    assert m1["stalled_streak"] == 2          # carried verbatim, NOT +1
    assert m1["stalled_since"] == "2026-07-05"
    assert m1["stalled_bucket"] == "stalled"
    assert m1["stalled_escalated"] is True    # recomputed from carried fields
    m2 = dict(_stall(row, prev))
    assert m2 == m1


def test_annotate_stalled_cause_zero_serve():
    m = _stall(_stalled_score("s", ga_clicks=0, impressions=37))
    assert m["stalled_cause"] == "zero_serve"  # 37/23 ≈ 1.6 impr/day < 10


def test_annotate_stalled_cause_weak_demand():
    m = _stall(_stalled_score("s", ga_clicks=0, impressions=1200))
    assert m["stalled_bucket"] == "stalled"
    assert m["stalled_cause"] == "weak_demand"  # serving fine, CTR 0 < 1%


def test_annotate_stalled_cause_no_telemetry():
    m = _stall(_stalled_score("s", ga_clicks=0, impressions=None))
    assert m["stalled_cause"] == "no_telemetry"


def test_annotate_stalled_cause_indeterminate_is_none():
    # Serving ok/day but below the weak-demand impression floor → no diagnosis.
    m = _stall(_stalled_score("s", ga_clicks=0, impressions=500))
    assert m["stalled_bucket"] == "stalled"
    assert m["stalled_cause"] is None


def test_headline_score_passes_overrides_and_impressions():
    m = mvp(name="pass", visitors=5, signups=0)
    m.update({
        "ga_impressions": 812,
        "cpc_exception": {"reason": "r", "max_cpc_override": 5.0},
        "channel_waiver": {"reason": "w"},
        "phase1_relaunch_at": "2026-07-10",
    })
    score = compute_headline_verdict(m, {}, THRESHOLDS,
                                     money_leak_reference_now=_S_REF)
    assert score["metrics"]["ga_impressions"] == 812
    assert score["cpc_exception"]["max_cpc_override"] == 5.0
    assert score["channel_waiver"]["reason"] == "w"
    assert score["phase1_relaunch_at"] == "2026-07-10"


def _stall_e2e_data(name="stall-e2e"):
    return {
        "mvps": [
            {
                "name": name,
                "owner": "lee",
                "gclid_visitors": 0,
                "signups": 0,
                "signup_events": ["signup_complete"],
                "total_events_count": 100,
                "event_catalog": [],
                "ga_clicks": 19,
                "ga_impressions": 37,
                "campaign_first_date": "2026-06-29",
            }
        ]
    }


def test_main_ledger_missing_graceful():
    """--ledger → nonexistent path: rc 0, lifetime-only detection, no escalation."""
    import json as _json
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        data_path = os.path.join(td, "data.json")
        issues_path = os.path.join(td, "issues.json")
        out_path = os.path.join(td, "scores.json")
        _json.dump(_stall_e2e_data(), open(data_path, "w"))
        _json.dump({"mvps": [{"name": "stall-e2e", "no_event_data": False}]},
                   open(issues_path, "w"))
        rc = main([
            "--data", data_path,
            "--issues", issues_path,
            "--config", "/nonexistent.yaml",
            "--ledger", os.path.join(td, "no-such-ledger.jsonl"),
            "--reference-now", _S_REF,
            "--output", out_path,
        ])
        assert rc == 0
        m = _json.load(open(out_path))["mvps"][0]["metrics"]
        # 19 clicks / 23d → ETA (100-19)/(19/23) ≈ 98d > 45 → stalled_slow.
        assert m["stalled_bucket"] == "stalled_slow"
        assert m["stalled_cause"] == "zero_serve"
        assert m["stalled_escalated"] is False


def test_main_reads_ledger_and_annotates():
    """e2e: seeded ledger row → streak increments + escalates; --scores re-run
    (the x4 team-message/docx branch) must NOT re-annotate."""
    import json as _json
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        data_path = os.path.join(td, "data.json")
        issues_path = os.path.join(td, "issues.json")
        ledger_path = os.path.join(td, "ledger.jsonl")
        out_path = os.path.join(td, "scores.json")
        out2_path = os.path.join(td, "scores2.json")
        _json.dump(_stall_e2e_data(), open(data_path, "w"))
        _json.dump({"mvps": [{"name": "stall-e2e", "no_event_data": False}]},
                   open(issues_path, "w"))
        with open(ledger_path, "w") as fh:
            fh.write(_json.dumps({
                "mvp": "stall-e2e",
                "current": {"ga_clicks": 19, "last_run": "2026-07-19",
                            "stalled_since": "2026-07-05", "stalled_streak": 1},
            }) + "\n")
            fh.write("{corrupt line\n")  # tolerant reader must skip this

        rc = main([
            "--data", data_path,
            "--issues", issues_path,
            "--config", "/nonexistent.yaml",
            "--ledger", ledger_path,
            "--reference-now", _S_REF,
            "--output", out_path,
        ])
        assert rc == 0
        m = _json.load(open(out_path))["mvps"][0]["metrics"]
        assert m["stalled_bucket"] == "stalled"
        assert m["click_delta"] == 0 and m["delta_days"] == 3
        assert m["stalled_streak"] == 2
        assert m["stalled_since"] == "2026-07-05"
        assert m["stalled_escalated"] is True  # 17d sustained, streak 2

        # x4 branch: precomputed --scores skips compute → annotations frozen.
        rc = main([
            "--data", "/nonexistent-data.json",
            "--issues", "/nonexistent-issues.json",
            "--scores", out_path,
            "--config", "/nonexistent.yaml",
            "--ledger", ledger_path,
            "--output", out2_path,
        ])
        assert rc == 0
        m2 = _json.load(open(out2_path))["mvps"][0]["metrics"]
        assert {k: m2[k] for k in m if k.startswith("stalled")} == \
               {k: m[k] for k in m if k.startswith("stalled")}


# ---------- Phase2-scoped ads-status on pay-intent rows ----------

_ADS_DETAIL_STOPPED = [
    {"name": "m-search-phase2-v1", "campaign_status": "Paused",
     "serving_status": "Paused", "status_reasons": None, "normalized": "stopped"},
]


def test_pay_intent_score_carries_phase2_ads_status_fields():
    score = compute_pay_intent_verdict(
        pay_mvp(ga_ads_all_stopped=True, ga_campaign_status_detail=_ADS_DETAIL_STOPPED),
        {},
        dict(THRESHOLDS),
    )
    assert score["phase2_ads_all_stopped"] is True
    assert score["phase2_campaign_status_detail"] == _ADS_DETAIL_STOPPED
    # Name guard: the unprefixed phase-1 fields must NOT appear on pay-intent
    # rows — the --phase-filter slice would read as a fleet-wide claim.
    assert "ga_ads_all_stopped" not in score
    assert "ga_campaign_status_detail" not in score


def test_pay_intent_ads_stopped_flag_on_insufficient():
    score = compute_pay_intent_verdict(
        pay_mvp(ga_clicks=10, ga_ads_all_stopped=True,
                ga_campaign_status_detail=_ADS_DETAIL_STOPPED),
        {},
        dict(THRESHOLDS),
    )
    assert score["headline_verdict"] == VERDICT_INSUFFICIENT
    flags = [f for f in score["tracking_sanity_flags"] if f["flag"] == "phase2_ads_stopped"]
    assert len(flags) == 1
    assert flags[0]["severity"] == "high"
    assert "m-search-phase2-v1" in flags[0]["message"]
    action = verdicts.pay_intent_ads_stopped_action(score)
    assert action is not None and "resume the campaign" in action


def test_pay_intent_ads_stopped_action_on_no_data():
    score = compute_pay_intent_verdict(
        pay_mvp(ga_clicks=5, ga_ads_all_stopped=True,
                ga_campaign_status_detail=_ADS_DETAIL_STOPPED),
        {"no_event_data": True},
        dict(THRESHOLDS),
    )
    assert score["headline_verdict"] == VERDICT_NO_DATA
    assert any(f["flag"] == "phase2_ads_stopped" for f in score["tracking_sanity_flags"])
    assert "no traffic to track" in verdicts.pay_intent_ads_stopped_action(score)


def test_pay_intent_ads_stopped_go_row_still_ranks_no_flag():
    """A stopped campaign changes what happens NEXT, not what a conclusive
    sample already measured — GO keeps its rank, no flag, no override."""
    thresholds = dict(THRESHOLDS, pay_intent_rate_go=0.02)
    score = compute_pay_intent_verdict(
        pay_mvp(ga_clicks=300, pay_intents=9, ga_ads_all_stopped=True,
                ga_campaign_status_detail=_ADS_DETAIL_STOPPED),
        {},
        thresholds,
    )
    assert score["headline_verdict"] == VERDICT_GO
    assert not any(f["flag"] == "phase2_ads_stopped" for f in score["tracking_sanity_flags"])
    assert verdicts.pay_intent_ads_stopped_action(score) is None
    assert verdicts.pay_intent_go_rank_key(score)[2] == -300


def test_pay_intent_ads_status_none_and_false_no_flag():
    for stopped, detail in ((None, []), (False, [{"name": "c", "normalized": "active"}])):
        score = compute_pay_intent_verdict(
            pay_mvp(ga_clicks=10, ga_ads_all_stopped=stopped,
                    ga_campaign_status_detail=detail),
            {},
            dict(THRESHOLDS),
        )
        assert score["phase2_ads_all_stopped"] is stopped
        assert not any(
            f["flag"] == "phase2_ads_stopped" for f in score["tracking_sanity_flags"]
        )
        assert verdicts.pay_intent_ads_stopped_action(score) is None


def test_pay_intent_ads_status_false_via_unknown_no_flag():
    # All-unknown detail derives all_stopped False upstream ("alive is the
    # default" — the fail-safe direction: never claim stopped without proof).
    score = compute_pay_intent_verdict(
        pay_mvp(ga_clicks=10, ga_ads_all_stopped=False,
                ga_campaign_status_detail=[{"name": "c", "normalized": "unknown"}]),
        {},
        dict(THRESHOLDS),
    )
    assert not any(f["flag"] == "phase2_ads_stopped" for f in score["tracking_sanity_flags"])


# ---------- Ledger-free stalled triage on phase2 rows ----------

def test_pay_intent_metrics_carry_campaign_age_and_impressions():
    score = compute_pay_intent_verdict(
        pay_mvp(ga_clicks=10, campaign_first_date="2026-06-29", ga_impressions=500),
        {},
        dict(THRESHOLDS),
        reference_now="2026-07-22T00:00:00Z",
    )
    assert score["metrics"]["campaign_age_days"] == 23
    assert score["metrics"]["ga_impressions"] == 500


def test_pay_intent_reference_now_absent_age_none_and_stalled_skips():
    score = compute_pay_intent_verdict(
        pay_mvp(ga_clicks=0, campaign_first_date="2026-06-29", ga_impressions=0),
        {},
        dict(THRESHOLDS),
    )
    assert score["metrics"]["campaign_age_days"] is None
    verdicts.annotate_stalled([score], dict(_S_TH, visitors_floor=300), None, reference_now=_S_REF)
    # No age and no ledger fallback -> first-sighting skip, defaults only.
    assert score["metrics"]["stalled_bucket"] == "none"


def test_annotate_stalled_phase2_floor_override():
    """The phase2 sample gate/ETA target is clicks vs pay_intent_visitors_floor:
    150 clicks at age 60d flags stalled_slow under floor 300 (ETA 60d > 45)
    while the phase-1 floor 100 would have skipped the row entirely."""
    row = _stalled_score("p2", ga_clicks=150, age=60, impressions=1000)
    verdicts.annotate_stalled([row], dict(_S_TH, visitors_floor=300), None, reference_now=_S_REF)
    assert row["metrics"]["stalled_bucket"] == "stalled_slow"
    assert row["metrics"]["stalled_eta_days"] == 60.0

    phase1_row = _stalled_score("p2", ga_clicks=150, age=60, impressions=1000)
    verdicts.annotate_stalled([phase1_row], _S_TH, None, reference_now=_S_REF)
    assert phase1_row["metrics"]["stalled_bucket"] == "none"


def test_annotate_stalled_phase2_zero_clicks_hard_stall_zero_serve():
    score = compute_pay_intent_verdict(
        pay_mvp(ga_clicks=0, campaign_first_date="2026-06-29", ga_impressions=0),
        {},
        dict(THRESHOLDS),
        reference_now=_S_REF,
    )
    verdicts.annotate_stalled([score], dict(_S_TH, visitors_floor=300), None, reference_now=_S_REF)
    met = score["metrics"]
    assert met["stalled_bucket"] == "stalled"
    assert met["stalled_cause"] == "zero_serve"
    assert met["stalled_since"] == "2026-06-29"
    assert met["stalled_streak"] == 1
    assert met["stalled_escalated"] is False
    assert met["click_delta"] is None


def test_annotate_stalled_phase2_no_telemetry_without_impressions():
    score = compute_pay_intent_verdict(
        pay_mvp(ga_clicks=0, campaign_first_date="2026-06-29"),
        {},
        dict(THRESHOLDS),
        reference_now=_S_REF,
    )
    verdicts.annotate_stalled([score], dict(_S_TH, visitors_floor=300), None, reference_now=_S_REF)
    assert score["metrics"]["stalled_bucket"] == "stalled"
    assert score["metrics"]["stalled_cause"] == "no_telemetry"


def test_annotate_stalled_phase2_never_escalates_without_ledger():
    """No phase2 ledger -> streak can never exceed 1, escalation never fires.
    (The documented omission: click_delta/streak carry need prev-run state.)"""
    score = compute_pay_intent_verdict(
        pay_mvp(ga_clicks=0, campaign_first_date="2026-06-01", ga_impressions=0),
        {},
        dict(THRESHOLDS),
        reference_now=_S_REF,
    )
    for _ in range(3):
        verdicts.annotate_stalled(
            [score], dict(_S_TH, visitors_floor=300), None, reference_now=_S_REF
        )
        assert score["metrics"]["stalled_streak"] == 1
        assert score["metrics"]["stalled_escalated"] is False


def test_annotate_stalled_phase2_go_row_untouched():
    thresholds = dict(THRESHOLDS, pay_intent_rate_go=0.02)
    score = compute_pay_intent_verdict(
        pay_mvp(ga_clicks=300, pay_intents=9, campaign_first_date="2026-06-29"),
        {},
        thresholds,
        reference_now=_S_REF,
    )
    assert score["headline_verdict"] == VERDICT_GO
    verdicts.annotate_stalled([score], dict(_S_TH, visitors_floor=300), None, reference_now=_S_REF)
    assert "stalled_bucket" not in score["metrics"]


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
