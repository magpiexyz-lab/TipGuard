#!/usr/bin/env python3
"""iterate_cross_verdicts.py — Pure-Python verdict computation for /iterate --cross.

PostHog-only. Reads:
  - .runs/iterate-cross-data.json     (gathered by state-x1, signups added in x2)
  - .runs/iterate-cross-data-issues.json (computed by state-x1a)
  - experiment/iterate-cross-config.yaml  (operator config; falls back to defaults)

Writes:
  - .runs/iterate-cross-scores.json   (consumed by state-x4)
  - stdout team message               (optional; --emit-team-message — never on disk)

Verdict precedence (first match wins):
  0. MISSING_PROJECT_NAME    (issues.missing_project_name — orphan event stream)
  1. GA_NO_PH_TRACKING       (issues.ga_clicks_without_ph_traffic — GA has spend, PostHog blind)
  2. NO_DATA                 (issues.no_event_data)
  3. INSUFFICIENT_DATA       (visitors < visitors_floor — not enough sample)
  4. GO                      (visitors >= visitors_floor AND conv_rate >= conv_rate_go)
  5. NO_GO                   (visitors >= visitors_floor AND conv_rate < conv_rate_go)

Denominator rule: when mvp.ga_clicks > 0 (state-x0a merged Google Ads clicks),
`visitors = ga_clicks` (the more reliable signal — clicks are GA-counted directly,
not subject to PostHog SDK lazy-load failures). Otherwise fall back to PostHog
`gclid_visitors`. The score record exposes both numbers + `denominator_source`
so x4 can flag PH-overcount discrepancies (ph > ga * 1.10).

Signups numerator: prefer trusted DB ground truth (Supabase or Railway) whenever
available; fall back to PostHog `ph_signups` only when DB has no mapping. DB rows
are the actual completed signups — PH events may over- or under-count due to
late instrumentation, ad-blocker drops, or wrong signup_events config.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone


DEFAULT_CONFIG = {
    "signup_whitelist": [
        "signup_complete",
        "waitlist_signup",
        "waitlist_submit",
        "early_access_signup",
        "activate",
        "form_submitted",
    ],
    "mvp_mappings": {},
    "thresholds": {
        "signups_go": 6,            # derived: visitors_floor * conv_rate_go
        "visitors_floor": 100,      # min paid visitors to commit either way
        "conv_rate_go": 0.06,       # min conversion rate to call GO
        "pay_intent_visitors_floor": 300,  # Phase 2 click floor (~6 expected pay-intents at theta2=2%; floor = 6/theta2)
        "pay_intent_rate_go": 0.02, # min Phase 2 pay-intent rate to call GO
        # pay_intent_wiring_unproven severity boundary: at >=150 zero-intent
        # clicks, P(0 intents | rate == theta2) = 0.98^150 ~= 4.8% — silence is
        # now more likely broken wiring than genuine zero demand -> "high".
        "pay_intent_wiring_high_clicks": 150,
        "max_cpc": 2.5,             # CPC cap (basis = max_cpc_basis); over → cpc_over_cap flag
        "cpc_payback_multiple": 20, # over-cap unit-economics gate: NO_GO when cpc_usd * this > monthly_price_usd
        "channel_floor": 50,        # clicks below which an aged in-cap campaign is "starved"
        "channel_starve_min_days": 21,  # campaign age (days) before channel_starved can fire
        # INSUF futility triage (state-x3 annotate_futility → state-x4 kill proposals).
        # Sequential-futility stopping: P(final conv >= conv_rate_go at the
        # visitors_floor | Beta-Binomial posterior on observed n/k).
        "futility_kill_prob": 0.05,   # below this on BOTH numerators → kill_candidate
        "futility_min_clicks": 30,    # below this n, futility never fires (too_new)
        "futility_revive_prob": 0.5,  # above this + stale campaign → revive_candidate
        "futility_stale_days": 14,    # last_seen older than this = campaign stopped
        "futility_verify_gap": 0.3,   # PH-vs-effective probability gap that routes to verify_data
        # Stalled-campaign triage (state-x3 annotate_stalled → state-x4 STALLED
        # worklist / kill proposals). Detects INSUF rows whose click FLOW is
        # ~zero — waiting is not a rational action for them (bid-capped
        # shortfall: enabled campaign priced out of the auction).
        "stalled_escalate_days": 14,      # min days since stalled_since before escalation can fire
        "stalled_eta_max_days": 45,       # lifetime ETA to visitors_floor above this → stalled_slow
        "stalled_impr_per_day_floor": 10, # lifetime impr/day below this → cause zero_serve
        "stalled_weak_demand_min_impr": 1000,  # min lifetime impressions before weak_demand may be diagnosed
        "stalled_weak_demand_ctr": 0.01,  # CTR below this (with impressions >= min) → weak_demand
        # Kill-proposal relaunch protection (state-x4) + stalled suppression:
        # an MVP relaunched within this many days is never proposed for kill
        # and never flagged stalled (fresh flight, no verdict-worthy data yet).
        "relaunch_protection_days": 30,
    },
    "window_days": 90,
    "money_leak_recent_days": 14,
    # CPC currency normalization. Operator chose USD basis: native CPC is
    # converted to USD via fx_to_usd before comparison against thresholds.max_cpc.
    # Set max_cpc_basis="native" to compare each campaign's CPC in its own currency.
    "max_cpc_basis": "usd",
    "fx_to_usd": {"USD": 1.0, "SGD": 0.74},
    # Campaigns allowed to send traffic to a different MVP's site without a
    # foreign_campaign_traffic flag (intentional cross-promo). Entries are
    # match_key-normalized and compared against the utm_campaign string, the
    # paying MVP name, and the receiving MVP name.
    "cross_campaign_whitelist": [],
}

VERDICT_GO = "GO"
VERDICT_WEAK = "WEAK"
VERDICT_NO_GO = "NO_GO"
VERDICT_INSUFFICIENT = "INSUFFICIENT_DATA"
VERDICT_NO_DATA = "NO_DATA"
VERDICT_MISSING_PROJECT_NAME = "MISSING_PROJECT_NAME"
# GA campaign has paid clicks but PostHog has zero presence for this MVP (neither
# canonical events nor orphan rows). Strictly stricter than MISSING_PROJECT_NAME
# (which fires when PH SEES the traffic but project_name is NULL). This verdict
# surfaces deploys that the operator is paying for but cannot measure at all.
VERDICT_GA_NO_PH_TRACKING = "GA_NO_PH_TRACKING"

VERDICT_ENUM = {
    VERDICT_GO,
    VERDICT_WEAK,
    VERDICT_NO_GO,
    VERDICT_INSUFFICIENT,
    VERDICT_NO_DATA,
    VERDICT_MISSING_PROJECT_NAME,
    VERDICT_GA_NO_PH_TRACKING,
}

VERDICT_SORT_ORDER = {
    VERDICT_MISSING_PROJECT_NAME: 0,
    VERDICT_GA_NO_PH_TRACKING: 1,
    VERDICT_GO: 2,
    VERDICT_WEAK: 3,
    VERDICT_INSUFFICIENT: 4,
    VERDICT_NO_GO: 5,
    VERDICT_NO_DATA: 6,
}

PAY_INTENT_VERDICT_SORT_ORDER = {
    VERDICT_MISSING_PROJECT_NAME: 0,
    VERDICT_GA_NO_PH_TRACKING: 1,
    VERDICT_GO: 2,
    VERDICT_INSUFFICIENT: 3,
    VERDICT_NO_GO: 4,
    VERDICT_NO_DATA: 5,
}


def is_trusted_db_real(mvp: dict) -> bool:
    return (
        mvp.get("db_signups_real") is not None
        and mvp.get("db_unmapped_reason") is None
        and mvp.get("db_signups_real_windowed") is True
        and mvp.get("db_source") in {"supabase", "railway"}
    )


def _db_paid_within_real_bound(mvp: dict) -> bool:
    db_paid = _int_or_none(mvp.get("db_signups_paid"))
    db_real = _int_or_none(mvp.get("db_signups_real"))
    return db_paid is not None and db_real is not None and 0 <= db_paid <= db_real


def is_trusted_db_paid(mvp: dict) -> bool:
    return (
        _db_paid_within_real_bound(mvp)
        and mvp.get("db_unmapped_reason") is None
        and mvp.get("db_signups_real_windowed") is True
        and mvp.get("db_source") in {"supabase", "railway"}
        and mvp.get("db_attribution") == "gclid_shape"
    )


def _db_zero_with_ph_signups_flag(
    db_signups: object,
    ph_signups_available: object,
    ph_signups: object,
) -> dict | None:
    if (
        _int_or_none(db_signups) == 0
        and ph_signups_available is True
        and _int_value(ph_signups) > 0
    ):
        return {
            "flag": "db_zero_with_ph_signups",
            "severity": "high",
            "message": "Trusted DB has zero real signups while PostHog has paid signup events.",
        }
    return None


def resolve_effective_signups(mvp: dict) -> tuple[int | None, str | None, list[dict]]:
    """Pick the signup count and source for the verdict.

    DB-first policy: when the MVP has a trusted DB ground-truth count
    (Supabase or Railway, mapped + windowed), use it regardless of what
    PostHog reports. PostHog is a fallback only when no DB is available.

    Rationale: DB rows are actual completed signups. PostHog events can be
    over-counted (wrong signup_events config), under-counted (late
    instrumentation, ad-blocker drops, OAuth callbacks fired server-side),
    or attribution-broken (gclid lost between landing and signup page).

    Returns (effective_signups, source, sanity_flags).
    Sources:
      - "db_paid":      trusted DB gclid-shape paid count used
      - "db_real":      trusted DB count used (preferred)
      - "db_real_zero": trusted DB == 0 while PostHog has paid signups
                        (flagged for operator review; treat as 0)
      - "ph":           PostHog count used (no trusted DB available)
      - None:           neither source has signal
    """
    ph_signups_available = mvp.get("ph_signups_available")
    if ph_signups_available is None:
        ph_signups_available = bool(mvp.get("signup_events"))
    ph_signups = mvp.get("ph_signups", mvp.get("signups"))
    if ph_signups is None and ph_signups_available:
        ph_signups = 0
    db_paid = mvp.get("db_signups_paid")
    db_real = mvp.get("db_signups_real")
    flags: list[dict] = []

    if is_trusted_db_paid(mvp):
        zero_flag = _db_zero_with_ph_signups_flag(db_paid, ph_signups_available, ph_signups)
        if zero_flag:
            flags.append(zero_flag)
        return int(db_paid or 0), "db_paid", flags

    if is_trusted_db_real(mvp):
        # DB has the truth. Emit a high-severity flag only when DB=0 contradicts
        # positive PH paid signups — that's a signal the PH config is wrong, not
        # that the verdict should change.
        zero_flag = _db_zero_with_ph_signups_flag(db_real, ph_signups_available, ph_signups)
        if zero_flag:
            flags.append(zero_flag)
            return 0, "db_real_zero", flags
        return int(db_real or 0), "db_real", flags

    # No trusted DB → fall back to PostHog when available.
    if ph_signups_available is True:
        return int(ph_signups or 0), "ph", flags
    return None, None, flags


def is_trusted_db_pay_intents(mvp: dict) -> bool:
    return (
        mvp.get("db_pay_intents_paid") is not None
        and mvp.get("db_pay_intents_unmapped_reason") is None
        and mvp.get("db_pay_intents_real_windowed") is True
        and mvp.get("db_pay_intent_source") in {"supabase", "railway"}
    )


def _int_value(value: object, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_value(value: object, default: float = 0.0) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return default


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_iso_datetime(value: object) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        s = s.replace(" ", "T")
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def reference_now_from_records(records: list[dict]) -> datetime | None:
    """Derive a deterministic window end from input data when none is supplied."""
    seen = [
        dt for dt in (_parse_iso_datetime(m.get("last_seen")) for m in records)
        if dt is not None
    ]
    return max(seen) if seen else None


def compute_money_leak(
    mvp: dict,
    reference_now: datetime | str | None,
    window_days: int = 14,
) -> bool:
    """Flag recent paid traffic to a killed/deleted backend."""
    ref = _parse_iso_datetime(reference_now)
    last_seen = _parse_iso_datetime(mvp.get("last_seen"))
    if ref is None or last_seen is None:
        return False
    dead_backend = (
        mvp.get("db_unmapped_reason") in ("project_deleted", "archived_killed")
        or mvp.get("lifecycle_status") == "killed"
    )
    if not dead_backend:
        return False
    return last_seen >= ref - timedelta(days=window_days)


def compute_zombie_backend(mvp: dict, reference_now: datetime | str | None) -> bool:
    """Killed MVP whose Supabase backend is verifiably ALIVE and unwaived.

    The mirror of money_leak: money_leak = paid traffic to a dead funnel;
    zombie = live infrastructure behind a dead product (cost/quota risk +
    pre-teardown ground truth still capturable). Evidence comes from the
    sticky db_backend record written by state-x0b / verify-backends — never
    from lifecycle status alone. Suppressed by an active backend_keep waiver
    (deliberately shared/kept projects).
    """
    if mvp.get("lifecycle_status") != "killed":
        return False
    backend = mvp.get("db_backend") or {}
    if backend.get("status") != "alive":
        return False
    keep = mvp.get("backend_keep")
    if isinstance(keep, dict):
        exp = _parse_iso_datetime(keep.get("expires_at"))
        ref = _parse_iso_datetime(reference_now)
        if exp is None or ref is None or exp > ref:
            return False  # active waiver suppresses
    return True


def _log_choose(n: int, k: int) -> float:
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def _betabin_pmf(x: int, m: int, a: float, b: float) -> float:
    """P(X = x) for X ~ BetaBinomial(m, a, b)."""
    return math.exp(
        _log_choose(m, x)
        + math.lgamma(a + x) + math.lgamma(b + m - x) - math.lgamma(a + b + m)
        + math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    )


def futility_probability(n: int, k: int, floor: int, rate: float) -> float:
    """P(final signups >= ceil(rate*floor) after buying up to `floor` clicks).

    Sequential-futility statistic (clinical-trial stopping logic): given n paid
    clicks with k signups observed, Beta(1,1) prior on the true conversion
    rate, return the Beta-Binomial predictive probability that the MVP still
    clears the GO bar once the click count reaches the verdict floor. Near 0
    means every further click only buys confirmation of NO_GO.
    """
    need_total = math.ceil(rate * floor)
    if k >= need_total:
        return 1.0
    # k can exceed n when the DB-real numerator includes organic signups the
    # paid-click denominator never saw (e.g. 4 DB signups on 3 paid visitors).
    # The Beta-Binomial conditions on k-of-n trials, so clamp to the most
    # optimistic consistent sample (all n clicks converted) — biases P upward,
    # i.e. away from kill_candidate, never toward it.
    k = min(k, n)
    m = floor - n
    if m <= 0:
        return 0.0
    need_more = need_total - k
    if need_more > m:
        return 0.0
    a, b = k + 1.0, n - k + 1.0
    return sum(_betabin_pmf(x, m, a, b) for x in range(need_more, m + 1))


FUTILITY_BUCKETS = ("too_new", "kill_candidate", "verify_data", "revive_candidate", "keep")

# Stalled triage (annotate_stalled). Orthogonal to futility: futility asks "is
# the observed sample already conclusive?", stalled asks "is the sample even
# growing?". A stalled row's verdict never changes here — forced resolution is
# an operator decision via the state-x4 STALLED worklist / kill proposals.
STALLED_BUCKETS = ("none", "stalled", "stalled_slow")
STALLED_CAUSES = ("zero_serve", "weak_demand", "no_telemetry")


def _active_override(override: object, ref: datetime | None) -> dict | None:
    """Return the operator override if present and not past expires_at, else None.

    Shared by compute_cpc_flags (cpc_exception / channel_waiver) and
    annotate_stalled (channel_waiver suppresses stalled too).
    """
    if not isinstance(override, dict):
        return None
    exp = _parse_iso_datetime(override.get("expires_at"))
    if exp is not None and ref is not None and exp <= ref:
        return None  # expired → no longer suppresses
    return override


def annotate_futility(
    scores: list[dict],
    thresholds: dict,
    reference_now: datetime | str | None = None,
) -> list[dict]:
    """Annotate INSUFFICIENT_DATA scores with futility triage fields (in place).

    Adds to `metrics`: futility_prob (effective-signups numerator),
    futility_prob_ph (numerator lifted to max(effective, ph_signups)), and
    futility_bucket:
      - too_new          n < thresholds.futility_min_clicks — no statistical call
      - kill_candidate   BOTH numerators give P < futility_kill_prob — x4 folds
                         these into the operator-confirmed kill-proposal file
                         (verdict stays INSUFFICIENT_DATA; a kill is an operator
                         decision, mirroring the GO→promote confirm flow)
      - verify_data      the two numerators disagree materially (ph > effective
                         AND p_ph − p_eff ≥ futility_verify_gap) — the PH-vs-DB
                         discrepancy decides the outcome, so verify the DB write
                         path / signup_events before buying more clicks
                         (perky/pagoo false-zero pattern)
      - revive_candidate P >= futility_revive_prob but the campaign looks
                         stopped (last_seen older than futility_stale_days) —
                         cheap information the portfolio forgot to buy
      - keep             everything else: let it run to the floor

    Non-INSUF rows are left untouched. Idempotent.
    """
    floor = int(thresholds.get("visitors_floor", 100) or 100)
    rate = float(thresholds.get("conv_rate_go", 0.06) or 0.06)
    kill_prob = float(thresholds.get("futility_kill_prob", 0.05) or 0.05)
    min_clicks = int(thresholds.get("futility_min_clicks", 30) or 30)
    revive_prob = float(thresholds.get("futility_revive_prob", 0.5) or 0.5)
    stale_days = int(thresholds.get("futility_stale_days", 14) or 14)
    verify_gap = float(thresholds.get("futility_verify_gap", 0.3) or 0.3)
    ref = _parse_iso_datetime(reference_now)

    for score in scores:
        if score.get("headline_verdict") != VERDICT_INSUFFICIENT:
            continue
        met = score.get("metrics") or {}
        ga_clicks = _int_value(met.get("ga_clicks"))
        if ga_clicks > 0:
            n = _int_value(met.get("ga_clicks_phase1"), ga_clicks)
        else:
            n = _int_value(met.get("gclid_visitors"))
        k_eff = _int_value(met.get("effective_signups"))
        k_ph = max(k_eff, _int_value(met.get("ph_signups")))

        p_eff = futility_probability(n, k_eff, floor, rate)
        p_ph = futility_probability(n, k_ph, floor, rate)

        last_seen = _parse_iso_datetime(score.get("last_seen"))
        stale = bool(
            ref is not None
            and last_seen is not None
            and last_seen < ref - timedelta(days=stale_days)
        )

        if n < min_clicks:
            bucket = "too_new"
        elif max(p_eff, p_ph) < kill_prob:
            bucket = "kill_candidate"
        elif k_ph > k_eff and (p_ph - p_eff) >= verify_gap:
            bucket = "verify_data"
        elif p_eff >= revive_prob and stale:
            bucket = "revive_candidate"
        else:
            bucket = "keep"

        met["futility_prob"] = round(p_eff, 4)
        met["futility_prob_ph"] = round(p_ph, 4)
        met["futility_campaign_stale"] = stale
        met["futility_bucket"] = bucket
        score["metrics"] = met
    return scores


def _read_prev_ledger(path: str) -> dict[str, dict]:
    """Read the decision ledger jsonl → {mvp: row} for stalled carry-forward.

    Missing file → {} (first-ever run: lifetime-velocity detection only).
    Per-line tolerant parse — one corrupt ledger line must not kill the x3
    compute path (the ledger module's own reader stays strict; x4a will
    surface real corruption).
    """
    rows: dict[str, dict] = {}
    if not path or not os.path.exists(path):
        return rows
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    rows[row["mvp"]] = row
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue
    except OSError:
        return {}
    return rows


def annotate_stalled(
    scores: list[dict],
    thresholds: dict,
    prev_ledger: dict[str, dict] | None = None,
    reference_now: datetime | str | None = None,
) -> list[dict]:
    """Annotate INSUFFICIENT_DATA scores with stalled-flow triage fields (in place).

    Futility asks "is the observed sample already conclusive?"; stalled asks
    "is the sample even growing?". An INSUF row whose click flow is ~zero is a
    zombie: waiting has zero expected information gain but the slot, calendar
    time, and operator attention keep burning. Typical cause: campaign bid at
    the $2.50 ceiling losing every auction (0 impressions → 0 clicks → $0
    spend), indistinguishable from "paused" in click-derived telemetry.

    Adds to `metrics` (uniform shape on every live INSUF row):
      stalled_bucket    "none" | "stalled" | "stalled_slow"
        - stalled        zero click growth since the previous ledger run, or
                         lifetime-zero clicks (provably zero growth over the
                         whole campaign age — needs no previous row)
        - stalled_slow   lifetime ETA to visitors_floor > stalled_eta_max_days
      stalled_cause     zero_serve (impr/day < stalled_impr_per_day_floor —
                        losing auctions: ZERO information about demand, do not
                        read as product NO-GO) | weak_demand (impressions >=
                        stalled_weak_demand_min_impr and CTR <
                        stalled_weak_demand_ctr — a REAL negative demand
                        signal) | no_telemetry (CSV had no Impr. column) | None
      stalled_since     ISO date the zero-growth window started (carried
                        forward from the previous ledger row; for
                        lifetime-zero rows, the observation start derived
                        from stalled_age_days)
      stalled_age_days  the age the gate/ETA/cause actually used:
                        campaign_age_days (GA Start date) when present, else
                        days since the row's first_seen_in_ledger — a LOWER
                        bound, so flagging is delayed, never premature. The
                        fallback matters: real exports often omit Start date
                        (the 2026-07-21 run had it on 0/101 records), which
                        left channel_starved permanently silent; stalled must
                        not inherit that failure mode.
      stalled_streak    consecutive runs observed stalled (prev streak + 1)
      stalled_escalated bucket == "stalled" AND streak >= 2 AND sustained >=
                        stalled_escalate_days → state-x4 folds the row into
                        the operator-confirmed kill proposals (verdict stays
                        INSUFFICIENT_DATA — a kill is an operator decision,
                        mirroring futility kill_candidate). The first flagged
                        run never escalates: the operator always sees the
                        STALLED worklist at least one run before any fold-in.
      click_delta / delta_days   raw run-over-run observation (None w/o prev)
      stalled_eta_days  lifetime ETA when computable (None = infinite)

    Suppressions (leave bucket "none"): active channel_waiver (same override
    that suppresses channel_starved — one waiver quiets both); a
    phase1_relaunch_at within relaunch_protection_days (fresh flight); age
    below channel_starve_min_days, or unknown on BOTH sources (no GA Start
    date AND no prior ledger row — first-ever sighting).

    Same-day re-run guard: delta_days <= 0 carries the previous stalled fields
    verbatim so an x3 re-run after x4a already persisted today's snapshot
    cannot double-increment the streak. Idempotent within a run.

    Non-INSUF and killed/promoted rows are left untouched.
    """
    floor = int(thresholds.get("visitors_floor", 100) or 100)
    min_age = int(thresholds.get("channel_starve_min_days", 21) or 21)
    escalate_days = int(thresholds.get("stalled_escalate_days", 14) or 14)
    eta_max = float(thresholds.get("stalled_eta_max_days", 45) or 45)
    impr_floor = float(thresholds.get("stalled_impr_per_day_floor", 10) or 10)
    weak_min_impr = int(thresholds.get("stalled_weak_demand_min_impr", 1000) or 1000)
    weak_ctr = float(thresholds.get("stalled_weak_demand_ctr", 0.01) or 0.01)
    protect_days = int(thresholds.get("relaunch_protection_days", 30) or 30)
    ref = _parse_iso_datetime(reference_now)

    for score in scores:
        if score.get("headline_verdict") != VERDICT_INSUFFICIENT:
            continue
        if (score.get("lifecycle_status") or "active") in ("killed", "promoted"):
            continue
        met = score.get("metrics") or {}
        # Uniform defaults first: downstream rendering and re-runs see one shape.
        met["stalled_bucket"] = "none"
        met["stalled_cause"] = None
        met["stalled_since"] = None
        met["stalled_age_days"] = None
        met["stalled_streak"] = 0
        met["stalled_escalated"] = False
        met["click_delta"] = None
        met["delta_days"] = None
        met["stalled_eta_days"] = None
        score["metrics"] = met

        ga_clicks = _int_value(met.get("ga_clicks"))
        if ga_clicks > 0:
            n = _int_value(met.get("ga_clicks_phase1"), ga_clicks)
        else:
            n = _int_value(met.get("gclid_visitors"))
        if n >= floor:
            continue  # not sample-starved; INSUF for another reason

        prev_row = (prev_ledger or {}).get(score.get("name")) or {}

        # Effective age: GA-side campaign age when the export had Start date,
        # else days since the row first entered the ledger (a lower bound —
        # delays flagging, never premature). Without the fallback the whole
        # feature is dead on real exports that omit Start date.
        age = met.get("campaign_age_days")
        if age is None and ref is not None:
            first_seen = _parse_iso_datetime(prev_row.get("first_seen_in_ledger"))
            if first_seen is not None:
                age = (ref.date() - first_seen.date()).days
        if age is None or age < min_age:
            continue  # too young — or first-ever sighting — to judge flow
        met["stalled_age_days"] = int(age)

        if _active_override(score.get("channel_waiver"), ref) is not None:
            continue
        relaunch = _parse_iso_datetime(score.get("phase1_relaunch_at"))
        if relaunch is not None and ref is not None and (ref - relaunch).days < protect_days:
            continue

        prev_cur = prev_row.get("current") or {}
        prev_clicks = prev_cur.get("ga_clicks")
        prev_last_run = _parse_iso_datetime(prev_cur.get("last_run"))
        prev_since = prev_cur.get("stalled_since")
        prev_streak = _int_value(prev_cur.get("stalled_streak"))

        click_delta = None
        delta_days = None
        if prev_clicks is not None and prev_last_run is not None and ref is not None:
            delta_days = (ref.date() - prev_last_run.date()).days
            click_delta = ga_clicks - _int_value(prev_clicks)
            met["click_delta"] = click_delta
            met["delta_days"] = delta_days
            if delta_days <= 0:
                # x3 re-run after x4a already persisted today's snapshot:
                # carry the prior state verbatim (streak must not double-count).
                met["stalled_bucket"] = prev_cur.get("stalled_bucket") or "none"
                met["stalled_cause"] = prev_cur.get("stalled_cause")
                met["stalled_since"] = prev_since
                met["stalled_streak"] = prev_streak
                met["stalled_escalated"] = _stalled_escalation(
                    met["stalled_bucket"], prev_streak, prev_since, ref, escalate_days
                )
                continue

        bucket = "none"
        since = None
        streak = 0
        zero_growth = click_delta == 0 and delta_days is not None and delta_days > 0
        if zero_growth or n == 0:
            bucket = "stalled"
            streak = prev_streak + 1
            if prev_since:
                since = str(prev_since)[:10]
            elif n == 0 and ref is not None:
                # Zero clicks over the whole observed age → the window started
                # at the campaign launch (or first ledger sighting, whichever
                # source stalled_age_days came from).
                since = (ref.date() - timedelta(days=int(age))).isoformat()
            elif prev_cur.get("last_run"):
                since = str(prev_cur.get("last_run"))[:10]
        elif age > 0 and n > 0:
            # Growth (or a window-slide/relaunch decrease) clears carry-state;
            # the row may still be crawling: lifetime ETA to the verdict floor.
            eta = (floor - n) / (float(n) / float(age))
            if eta > eta_max:
                bucket = "stalled_slow"

        if bucket == "none":
            continue  # defaults already written

        if n > 0:
            met["stalled_eta_days"] = round((floor - n) / (float(n) / float(age)), 1)

        impr = met.get("ga_impressions")
        if impr is None:
            met["stalled_cause"] = "no_telemetry"
        else:
            impr = float(impr)
            ctr = (float(ga_clicks) / impr) if impr > 0 else 0.0
            if (impr / float(age)) < impr_floor:
                met["stalled_cause"] = "zero_serve"
            elif impr >= weak_min_impr and ctr < weak_ctr:
                met["stalled_cause"] = "weak_demand"

        met["stalled_bucket"] = bucket
        met["stalled_since"] = since
        met["stalled_streak"] = streak
        met["stalled_escalated"] = _stalled_escalation(
            bucket, streak, since, ref, escalate_days
        )
    return scores


def _stalled_escalation(
    bucket: str,
    streak: int,
    since: str | None,
    ref: datetime | None,
    escalate_days: int,
) -> bool:
    """Escalation rule shared by the live and carry-forward paths.

    Only hard `stalled` escalates (stalled_slow is worklist-only in v1): the
    forced exit is tied to sustained ZERO growth, observed on >= 2 runs
    spanning >= escalate_days.
    """
    if bucket != "stalled" or streak < 2:
        return False
    since_dt = _parse_iso_datetime(since)
    if since_dt is None or ref is None:
        return False
    return (ref.date() - since_dt.date()).days >= escalate_days


def compute_cpc_flags(
    mvp: dict,
    thresholds: dict,
    fx_to_usd: dict | None = None,
    max_cpc_basis: str = "usd",
    reference_now: datetime | str | None = None,
) -> dict:
    """Compute CPC-discipline flags + derived CPC metrics for one MVP.

    Non-blocking flags (they NEVER alter headline_verdict — CPC channel efficiency
    is orthogonal to the conversion axis the verdict measures):
      - cpc_over_cap (high): effective CPC over the cap → the operator approval
        worklist. avg CPC > cap proves the max-CPC bid was set over cap (with
        Manual CPC, actual avg CPC <= max-CPC bid).
      - channel_starved (high): in-cap but an aged campaign still under
        channel_floor clicks → NO-GO candidate. Reliable only because Phase-1
        daily budgets are standardized (low clicks can't be blamed on
        under-funding). Uses ga_clicks directly so it fires for ga_only records.
        0-click campaigns count as in-cap (no CPC exists at $0 spend, and a bid
        can't be over cap without spending) — the starved-est case must not be
        the one case the flag misses. cpc_usd None WITH clicks (Cost column
        absent) still does not fire: no telemetry is not proof of in-cap.
      - cpc_price_unmapped (low): over cap but monthly_price_usd is unset, so the
        unit-economics gate cannot run.

    Verdict-changing signal (returned as `economics_fail`, applied by
    compute_headline_verdict — the ONE CPC signal that moves a verdict):
      - cpc_unit_economics_fail (high): over cap AND implied CAC
        (cpc_usd * thresholds.cpc_payback_multiple, default 20) exceeds the MVP's
        monthly_price_usd → the campaign can't pay back at this CPC → NO_GO. Only
        fires when a monthly price is known and no cpc_exception is active.

    Operator overrides (read off the record; overlaid from config mvp_mappings in
    iterate_cross_propagate.build_records):
      - cpc_exception{max_cpc_override, expires_at}: raises the effective cap and
        suppresses cpc_over_cap AND the unit-economics gate (the "special
        approval" that keeps an over-cap MVP in its conversion verdict).
      - channel_waiver{expires_at}: suppresses channel_starved.
      - monthly_price_usd: the MVP's monthly price; denominator of the gate.

    Returns {"flags": [...], "economics_fail": bool, "metrics": {...}}; metrics
    merge into the score record.
    """
    fx_to_usd = fx_to_usd or {}
    flags: list[dict] = []
    ref = _parse_iso_datetime(reference_now)

    ga_cpc = mvp.get("ga_cpc")
    ga_clicks = mvp.get("ga_clicks", 0) or 0
    currency = mvp.get("ga_currency") or "USD"

    # Phase-1 CPC (native units). With no phase2 split the phase1 CPC IS the
    # blended CPC (covers records predating the split and cost-less fixtures);
    # with a split it derives from the phase1 cost/click slices. The
    # unit-economics NO_GO gate runs on this basis so the verdict-changing
    # signal matches the phase1-scoped conversion denominator; the advisory
    # cpc_over_cap worklist stays on the blended basis (account hygiene covers
    # every campaign, phase2 included).
    ga_clicks_phase2 = mvp.get("ga_clicks_phase2", 0) or 0
    phase1_clicks = max(ga_clicks - ga_clicks_phase2, 0)
    ga_cost = mvp.get("ga_cost")
    ga_cost_phase2 = mvp.get("ga_cost_phase2")
    if ga_clicks_phase2 <= 0:
        ga_cpc_phase1 = ga_cpc
    elif ga_cost is not None and phase1_clicks > 0:
        ga_cpc_phase1 = round((float(ga_cost) - float(ga_cost_phase2 or 0.0)) / phase1_clicks, 4)
    else:
        ga_cpc_phase1 = None

    cpc_exc = _active_override(mvp.get("cpc_exception"), ref)
    chan_waiver = _active_override(mvp.get("channel_waiver"), ref)

    # Effective cap (USD basis): an active cpc_exception raises it; else global cap.
    base_cap = thresholds.get("max_cpc")
    effective_cap = None
    if base_cap is not None:
        effective_cap = float(base_cap)
        if cpc_exc and cpc_exc.get("max_cpc_override") is not None:
            try:
                effective_cap = float(cpc_exc["max_cpc_override"])
            except (TypeError, ValueError):
                pass

    # Convert native CPC → USD (operator chose usd basis). Missing FX rate falls
    # back to native units AND emits cpc_currency_unmapped — never silently pass.
    cpc_usd = None
    cpc_phase1_usd = None
    currency_unmapped = False
    if ga_cpc is not None or ga_cpc_phase1 is not None:
        if max_cpc_basis == "usd":
            rate = fx_to_usd.get(currency)
            if rate is None:
                currency_unmapped = True
                rate = 1.0
            if ga_cpc is not None:
                cpc_usd = round(ga_cpc * rate, 4)
            if ga_cpc_phase1 is not None:
                cpc_phase1_usd = round(ga_cpc_phase1 * rate, 4)
        else:
            if ga_cpc is not None:
                cpc_usd = round(float(ga_cpc), 4)
            if ga_cpc_phase1 is not None:
                cpc_phase1_usd = round(float(ga_cpc_phase1), 4)

    campaign_age_days = None
    first_dt = _parse_iso_datetime(mvp.get("campaign_first_date"))
    if first_dt is not None and ref is not None:
        campaign_age_days = (ref - first_dt).days

    # Advisory basis: BLENDED CPC — an over-cap phase2 campaign must stay on the
    # operator's bid-discipline worklist even though it is out of the Phase-1
    # verdict's denominator.
    over_cap = (
        cpc_usd is not None and effective_cap is not None
        and cpc_usd > effective_cap and cpc_exc is None
    )
    # Verdict basis: PHASE-1 CPC — the gate's trigger and CAC must share the
    # basis of the phase1-scoped conversion denominator it overrides.
    over_cap_phase1 = (
        cpc_phase1_usd is not None and effective_cap is not None
        and cpc_phase1_usd > effective_cap and cpc_exc is None
    )

    # Unit-economics gate (verdict-changing — consumed by compute_headline_verdict).
    # When the PHASE-1 CPC is over cap, check the implied CAC
    # (cpc_phase1_usd * cpc_payback_multiple) against the MVP's monthly price. If
    # the implied CAC exceeds a month's revenue, the campaign can't pay back at
    # this CPC → economics_fail (→ NO_GO upstream). An active cpc_exception
    # (operator's "special approval") suppresses the whole branch, so it never
    # fires here. Price unknown → cannot evaluate → advisory flag only, never a
    # forced NO_GO. Without a phase2 split, cpc_phase1_usd == cpc_usd — behavior
    # identical to the pre-split gate.
    payback_multiple = thresholds.get("cpc_payback_multiple", 20)
    monthly_price = _float_or_none(mvp.get("monthly_price_usd"))
    implied_cac_usd = (
        round(cpc_phase1_usd * payback_multiple, 2) if cpc_phase1_usd is not None else None
    )
    economics_fail = False

    if over_cap:
        flags.append({
            "flag": "cpc_over_cap",
            "severity": "high",
            "message": (
                f"avg CPC ${cpc_usd:.2f} > cap ${effective_cap:.2f} "
                f"({currency} native ${ga_cpc:.2f}) — max-CPC bid set above playbook; "
                f"lower the bid or request a cpc_exception"
            ),
        })
    if over_cap_phase1:
        if monthly_price is not None and monthly_price > 0:
            if implied_cac_usd is not None and implied_cac_usd > monthly_price:
                economics_fail = True
                flags.append({
                    "flag": "cpc_unit_economics_fail",
                    "severity": "high",
                    "message": (
                        f"implied CAC ${implied_cac_usd:.2f} (Phase-1 CPC ${cpc_phase1_usd:.2f} × "
                        f"{payback_multiple}) > monthly price ${monthly_price:.2f} — "
                        f"unviable unit economics → NO_GO. Approve via cpc_exception to override."
                    ),
                })
        else:
            flags.append({
                "flag": "cpc_price_unmapped",
                "severity": "low",
                "message": (
                    f"Phase-1 CPC ${cpc_phase1_usd:.2f} over cap but monthly_price_usd is not set in "
                    f"mvp_mappings — cannot run the unit-economics gate. Add "
                    f"mvp_mappings.<name>.monthly_price_usd to enable the CPC NO_GO rule."
                ),
            })

    if currency_unmapped:
        flags.append({
            "flag": "cpc_currency_unmapped",
            "severity": "low",
            "message": (
                f"no fx_to_usd rate for currency {currency!r}; CPC compared in native units"
            ),
        })

    channel_floor = thresholds.get("channel_floor", 50)
    min_days = thresholds.get("channel_starve_min_days", 21)
    # In-cap: proven by an observed CPC under the cap, OR by 0 clicks (no CPC
    # exists at $0 spend; a bid can't be over cap without spending). cpc None
    # with clicks > 0 means the Cost column was absent — not proof of in-cap.
    in_cap = (
        (cpc_usd is not None and effective_cap is not None and cpc_usd <= effective_cap)
        or (cpc_usd is None and ga_clicks == 0)
    )
    if (
        in_cap
        and ga_clicks < channel_floor
        and campaign_age_days is not None and campaign_age_days >= min_days
        and chan_waiver is None
    ):
        if cpc_usd is None:
            starve_msg = (
                f"no clicks at the bid cap (0 clicks after {campaign_age_days}d — "
                f"bid likely below the first-page minimum; NO-GO candidate)"
            )
        else:
            starve_msg = (
                f"in-cap (CPC ${cpc_usd:.2f}) but only {ga_clicks} clicks after "
                f"{campaign_age_days}d — channel can't deliver volume at a viable CAC "
                f"(NO-GO candidate)"
            )
        flags.append({
            "flag": "channel_starved",
            "severity": "high",
            "message": starve_msg,
        })

    return {
        "flags": flags,
        # economics_fail is consumed by compute_headline_verdict to force NO_GO.
        # Unlike the advisory flags above, this signal IS verdict-changing.
        "economics_fail": economics_fail,
        "metrics": {
            "ga_cost": mvp.get("ga_cost", 0.0),
            "ga_cpc": ga_cpc,
            "ga_cpc_usd": cpc_usd,
            "ga_cpc_phase1": ga_cpc_phase1,
            "ga_currency": mvp.get("ga_currency"),
            "effective_cpc_cap_usd": effective_cap,
            "campaign_age_days": campaign_age_days,
            "monthly_price_usd": monthly_price,
            "implied_cac_usd": implied_cac_usd,
            "cpc_payback_multiple": payback_multiple,
            "cpc_unit_economics_fail": economics_fail,
        },
    }


def _pay_intent_unattributed_severity(
    paid: int,
    unattributed: int,
    mvp: dict,
    issues: dict | None,
    thresholds: dict | None,
) -> str:
    issues = issues or {}
    thresholds = thresholds or DEFAULT_CONFIG["thresholds"]
    ga_clicks = _int_value(mvp.get("ga_clicks"))
    visitors_floor = thresholds.get("pay_intent_visitors_floor", thresholds["visitors_floor"])
    theta = thresholds.get("pay_intent_rate_go", 0.02)
    has_overriding_issue = bool(
        issues.get("missing_project_name")
        or issues.get("ga_clicks_without_ph_traffic")
        or issues.get("no_event_data")
    )
    if has_overriding_issue or ga_clicks < visitors_floor or ga_clicks <= 0:
        return "info"
    paid_rate = paid / ga_clicks
    all_rate = (paid + unattributed) / ga_clicks
    crosses = (paid_rate < theta <= all_rate) or (all_rate < theta <= paid_rate)
    return "high" if crosses else "info"


def resolve_effective_pay_intents(
    mvp: dict,
    issues: dict | None = None,
    thresholds: dict | None = None,
) -> tuple[int, str, list[dict]]:
    """Pick the Phase 2 pay-intent numerator and source.

    Trusted DB pay_intents are the paid-gclid subset from `public.pay_intent`.
    PostHog remains a total fallback so every Phase 2 row has a source.
    """
    ph_pay_intents = _int_value(mvp.get("pay_intents"))
    flags: list[dict] = []

    if is_trusted_db_pay_intents(mvp):
        db_paid = _int_value(mvp.get("db_pay_intents_paid"))
        db_raw = _int_or_none(mvp.get("db_pay_intents_raw"))
        unattributed = _int_value(mvp.get("db_pay_intents_unattributed"))

        if db_raw is not None and ph_pay_intents > db_raw * 1.5:
            flags.append({
                "flag": "pay_intent_ph_exceeds_db",
                "severity": "high",
                "message": (
                    f"PostHog pay_intents ({ph_pay_intents}) > DB raw pay_intent rows "
                    f"({db_raw}) * 1.5. Check pay_intent event instrumentation and attribution."
                ),
            })

        if unattributed > 0:
            severity = _pay_intent_unattributed_severity(
                db_paid,
                unattributed,
                mvp,
                issues,
                thresholds,
            )
            flags.append({
                "flag": "pay_intent_unattributed_rows",
                "severity": severity,
                "message": (
                    f"DB has {unattributed} real pay_intent rows without a real paid gclid. "
                    "They are excluded from the paid-click numerator but may indicate shared-link or organic traffic."
                ),
            })

        if db_paid == 0 and ph_pay_intents > 0:
            flags.append({
                "flag": "pay_intent_db_zero_with_ph",
                "severity": "high",
                "message": "Trusted DB has zero paid pay_intents while PostHog has paid pay_intent events.",
            })
            return 0, "db_real_zero", flags
        return db_paid, "db_real", flags

    return ph_pay_intents, "ph", flags


def compute_pay_intent_wiring_flag(
    mvp: dict,
    effective_pay_intents: int,
    thresholds: dict | None = None,
) -> dict | None:
    """Flag campaigns whose pay_intent wiring has never been proven live.

    Fires when the campaign has clicks but zero effective pay-intents AND the
    last pay_intent EVER observed (any traffic, probe included — a fresh
    dayzero-probe legitimately re-proves wiring) predates the campaign's
    first_seen on BOTH PostHog and the DB. A side that cannot be checked
    (missing field / DB unreachable) counts as unproven and is named in the
    message. Diagnostic only — NEVER changes the headline verdict; zero
    intents at low click counts is usually demand, not breakage, hence the
    severity tiering.
    """
    thresholds = thresholds or DEFAULT_CONFIG["thresholds"]
    ga_clicks = _int_value(mvp.get("ga_clicks"))
    first_seen = _parse_iso_datetime(mvp.get("first_seen"))
    if ga_clicks <= 0 or effective_pay_intents > 0 or first_seen is None:
        return None

    ph_last = _parse_iso_datetime(mvp.get("ph_last_pay_intent_any_at"))
    db_last = _parse_iso_datetime(mvp.get("db_last_pay_intent_at"))
    if (ph_last is not None and ph_last >= first_seen) or (
        db_last is not None and db_last >= first_seen
    ):
        return None

    def _side(label: str, last: datetime | None, raw: object) -> str:
        if last is not None:
            return f"{label} last pay_intent {last.date().isoformat()}"
        if raw:
            return f"{label} last pay_intent unparseable ({raw!r})"
        return f"{label} not checkable (no pay_intent ever recorded or source unreachable)"

    high_clicks = int(
        thresholds.get(
            "pay_intent_wiring_high_clicks",
            DEFAULT_CONFIG["thresholds"]["pay_intent_wiring_high_clicks"],
        )
    )
    severity = "high" if ga_clicks >= high_clicks else "info"
    return {
        "flag": "pay_intent_wiring_unproven",
        "severity": severity,
        "message": (
            f"{ga_clicks} clicks with 0 pay-intents and no pay_intent proven since campaign start "
            f"({first_seen.date().isoformat()}): "
            f"{_side('PH', ph_last, mvp.get('ph_last_pay_intent_any_at'))}; "
            f"{_side('DB', db_last, mvp.get('db_last_pay_intent_at'))}. "
            "Wiring is UNPROVEN, not necessarily broken — re-run the dayzero probe or walk the "
            "deployed funnel to the pay wall once, then re-run /iterate --cross --phase2."
        ),
    }


def compute_price_change_flag(mvp: dict, gap_hours: int = 24) -> dict | None:
    """Flag sequential mid-phase price changes (vs interleaved A/B variants).

    Reads `pay_intent_price_variant_rows` ([{price_cents, pay_intents,
    first_at, last_at}]). Two+ variants whose time ranges are pairwise
    disjoint with >gap_hours between them = the price was CHANGED, so the
    single blended pay-intent rate mixes two different offers. Interleaved
    ranges (a real A/B) return None — the mixed-price ⚠ in the revenue cell
    already covers that case. Info severity; never changes verdicts.
    """
    rows = mvp.get("pay_intent_price_variant_rows") or []
    parsed = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        first = _parse_iso_datetime(row.get("first_at"))
        last = _parse_iso_datetime(row.get("last_at"))
        if first is None or last is None:
            continue
        parsed.append({
            "price_cents": _float_value(row.get("price_cents")),
            "pay_intents": _int_value(row.get("pay_intents")),
            "first_at": first,
            "last_at": last,
        })
    if len(parsed) < 2:
        return None
    parsed.sort(key=lambda r: r["first_at"])
    gap = timedelta(hours=gap_hours)
    for prev, nxt in zip(parsed, parsed[1:]):
        if nxt["first_at"] - prev["last_at"] <= gap:
            return None
    timeline = " -> ".join(
        (
            f"{int(r['price_cents'])}¢: {r['pay_intents']} intents "
            f"{r['first_at'].date().isoformat()}..{r['last_at'].date().isoformat()}"
        )
        for r in parsed
    )
    return {
        "flag": "price_change_mid_phase",
        "severity": "info",
        "message": (
            f"Sequential price change detected ({timeline}). The blended pay-intent rate mixes "
            "different offers — judge each price segment separately before a GO/NO_GO call."
        ),
    }


def _traffic_for_sort(score: dict) -> int:
    metrics = score.get("metrics", {})
    return metrics.get("ga_clicks") or metrics.get("gclid_visitors") or 0


def _global_score_key(score: dict) -> tuple:
    return (
        VERDICT_SORT_ORDER.get(score.get("headline_verdict"), 99),
        -_traffic_for_sort(score),
        score.get("name") or "",
    )


def sort_scores_global(scores: list[dict]) -> list[dict]:
    """Rank-table ordering: verdict first, traffic second, name third."""
    return sorted(scores, key=_global_score_key)


def sort_scores_by_owner(scores: list[dict]) -> list[dict]:
    """Team-message ordering: owner first, then global ordering within each owner."""
    return sorted(
        scores,
        key=lambda s: (
            s.get("owner") or "unassigned",
            *_global_score_key(s),
        ),
    )


def load_config(path: str | None) -> dict:
    """Load YAML config; deep-merge with defaults so partial configs work."""
    config = {
        k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v)
        for k, v in DEFAULT_CONFIG.items()
    }
    if path and os.path.exists(path):
        try:
            import yaml
        except ImportError:
            print("WARN: PyYAML not installed; using defaults.", file=sys.stderr)
            return config
        user_config = yaml.safe_load(open(path)) or {}
        for key, default_value in DEFAULT_CONFIG.items():
            if key in user_config and user_config[key] is not None:
                if isinstance(default_value, dict) and isinstance(user_config[key], dict):
                    merged = dict(default_value)
                    merged.update(user_config[key])
                    config[key] = merged
                else:
                    config[key] = user_config[key]
        # Preserve user-supplied mvp_mappings (deep merge isn't appropriate; user controls)
        if "mvp_mappings" in user_config:
            config["mvp_mappings"] = user_config["mvp_mappings"] or {}
    return config


def compute_headline_verdict(
    mvp: dict,
    issues: dict,
    thresholds: dict,
    money_leak_reference_now: datetime | str | None = None,
    money_leak_window_days: int = 14,
    fx_to_usd: dict | None = None,
    max_cpc_basis: str = "usd",
) -> dict:
    """Apply precedence rules and return the score record for one MVP.

    Precedence (first match wins):
      0. missing_project_name → MISSING_PROJECT_NAME (orphan event stream — fix tracking)
      1. ga_clicks_without_ph_traffic → GA_NO_PH_TRACKING (paying for blind deploy)
      2. no_event_data → NO_DATA
      3. db_unmapped_reason in ("project_deleted", "archived_killed") → NO_GO
         (project_deleted = deletion OBSERVED via API; archived_killed = killed
         policy skip. Either way no trusted ground truth; do not promote on the
         inflated PostHog fallback. Backend knowledge lives in db_backend.)
      4. visitors < visitors_floor → INSUFFICIENT_DATA (not enough sample)
      5. conv_rate >= conv_rate_go → GO
      6. (default; visitors >= floor, conv below threshold) → NO_GO

    CPC unit-economics override (applied AFTER the precedence above): when the CPC
    is over cap and the implied CAC (cpc_usd * cpc_payback_multiple) exceeds the
    MVP's monthly_price_usd (and no cpc_exception), a GO / INSUFFICIENT_DATA /
    NO_GO verdict is forced to NO_GO. It does NOT override the data-integrity
    verdicts (MISSING_PROJECT_NAME / GA_NO_PH_TRACKING / NO_DATA) — tracking must
    be trusted before an economics call is meaningful. See compute_cpc_flags.

    Conversion rate is signups / visitors where signups uses DB-first priority
    (see resolve_effective_signups) and visitors uses GA-clicks when available
    (state-x0a merged Google Ads data), else PostHog gclid_visitors.
    """
    gclid_visitors = mvp.get("gclid_visitors", 0)
    ga_clicks = mvp.get("ga_clicks", 0) or 0
    # Phase-2 split (state-x0a --phase-exclude → x1 propagation). Records that
    # predate the split (or MVPs with no phase2 campaigns) default to 0 and
    # behave exactly as before.
    ga_clicks_phase2 = mvp.get("ga_clicks_phase2", 0) or 0
    phase1_clicks = max(ga_clicks - ga_clicks_phase2, 0)
    ph_signups = mvp.get("ph_signups", mvp.get("signups", 0))
    raw_ph_signups = int(ph_signups or 0)
    effective_signups, signup_source, source_flags = resolve_effective_signups(mvp)
    signups = effective_signups if effective_signups is not None else 0
    signup_events = mvp.get("signup_events") or []

    # Denominator selection: GA clicks override PH visitors when available.
    # The Phase-1 verdict denominator is the phase1 slice (blended minus phase2
    # campaigns, whose funnel by design collects pay_intent, not signups).
    # phase1_clicks may be 0 while ga_clicks > 0 (all paid clicks were phase2):
    # precedence rules 0-3 still run first, then rule 4 (visitors < floor)
    # naturally yields INSUFFICIENT_DATA with visitors_needed == the full floor.
    if ga_clicks > 0:
        visitors = phase1_clicks
        denominator_source = "ga"
    else:
        visitors = gclid_visitors
        denominator_source = "ph"

    visitors_floor = thresholds["visitors_floor"]
    conv_rate_go = thresholds.get("conv_rate_go", 0.06)
    # Effective conv rate uses the chosen denominator (GA when present).
    conv_rate_for_verdict = (signups / visitors) if visitors > 0 else 0.0

    # CPC discipline computed up-front so the unit-economics gate can override the
    # verdict below. Returns advisory flags + the verdict-changing economics_fail.
    cpc_result = compute_cpc_flags(
        mvp,
        thresholds,
        fx_to_usd=fx_to_usd,
        max_cpc_basis=max_cpc_basis,
        reference_now=money_leak_reference_now,
    )

    if issues.get("missing_project_name"):
        verdict = VERDICT_MISSING_PROJECT_NAME
    elif issues.get("ga_clicks_without_ph_traffic"):
        verdict = VERDICT_GA_NO_PH_TRACKING
    elif issues.get("no_event_data"):
        verdict = VERDICT_NO_DATA
    elif mvp.get("db_unmapped_reason") in ("project_deleted", "archived_killed"):
        # No trusted ground truth: project_deleted = deletion OBSERVED via
        # API; archived_killed = killed policy skip (x0b doesn't re-query).
        # Either way the PostHog fallback (esp. loose signup_start events)
        # inflates the count and would resurrect a killed MVP as a false GO.
        # Force NO_GO so both flow into the existing archived + kill-proposal
        # path (x4). The backend's actual state (alive/deleted/never found)
        # lives in the sticky db_backend config record, not in this verdict.
        verdict = VERDICT_NO_GO
    elif visitors < visitors_floor:
        verdict = VERDICT_INSUFFICIENT
    elif conv_rate_for_verdict >= conv_rate_go:
        verdict = VERDICT_GO
    else:
        verdict = VERDICT_NO_GO

    # CPC unit-economics override: over-cap MVP whose implied CAC exceeds its
    # monthly price can't pay back at this CPC → force NO_GO. Applies only to the
    # conversion verdicts; data-integrity verdicts (MISSING_PROJECT_NAME /
    # GA_NO_PH_TRACKING / NO_DATA) are left for the operator to fix tracking first.
    # pre_cpc_verdict is persisted (metrics) so x4's kill-proposal expansion can
    # tell a channel-problem NO_GO (solely this gate — expensive clicks ≠ no
    # demand) from a demand NO_GO; only the latter is kill-proposable.
    pre_cpc_verdict = verdict
    if cpc_result["economics_fail"] and verdict in (
        VERDICT_GO,
        VERDICT_INSUFFICIENT,
        VERDICT_NO_GO,
    ):
        verdict = VERDICT_NO_GO

    visitors_needed = (
        max(0, visitors_floor - visitors)
        if verdict == VERDICT_INSUFFICIENT
        else 0
    )

    # PH conv_rate retained for back-compat with existing x4/report consumers.
    conv_rate = (signups / gclid_visitors) if gclid_visitors > 0 else 0.0
    # True conv rate uses phase1-scoped GA clicks when present — the
    # operator-facing Phase-1 number. Falls back to the PH rate when the GA
    # denominator is absent OR entirely phase2 (zero-guard rows keep a defined
    # metric instead of dividing by zero).
    true_conv_rate = (signups / phase1_clicks) if phase1_clicks > 0 else conv_rate
    # Capture rate = how much of the paid traffic PostHog actually sees.
    # Deliberately BLENDED on both sides (PH visitors cannot be phase-split —
    # untagged phase1 flights carry no utm). Null when no GA data available.
    capture_rate = (gclid_visitors / ga_clicks) if ga_clicks > 0 else None

    # DB ground-truth cross-check (state-x0b → x1 propagation). These flags
    # compare raw PH paid signups against DB truth even when the verdict itself
    # uses DB-first effective signups.
    # db_signups is None when Supabase mapping is missing/unauthorized — treat
    # as "no comparison available", do NOT collapse to zero.
    db_signups = mvp.get("db_signups_real", mvp.get("db_signups"))
    db_first_signup_at = mvp.get("db_first_signup_at")
    sanity_flags = compute_db_sanity_flags(
        paid_signups=raw_ph_signups,
        db_signups=db_signups,
        db_first_signup_at=db_first_signup_at,
        first_seen=mvp.get("first_seen"),
        ga_clicks=ga_clicks,
        db_attribution=mvp.get("db_attribution"),
        db_union_tables=mvp.get("db_union_tables"),
    ) + source_flags
    money_leak = compute_money_leak(
        mvp,
        money_leak_reference_now,
        money_leak_window_days,
    )
    # Append the CPC flags (computed up-front for the unit-economics override) to
    # the advisory list. cpc_over_cap / channel_starved / cpc_currency_unmapped /
    # cpc_price_unmapped are advisory; cpc_unit_economics_fail already drove the
    # verdict override above and is surfaced here for x4 rendering.
    sanity_flags = sanity_flags + cpc_result["flags"]

    # Zero-guard annotation: blended GA clicks exist but every one of them
    # matched the phase2 pattern — there is no Phase-1 traffic to judge.
    note = None
    if ga_clicks > 0 and phase1_clicks == 0:
        note = "all paid clicks match phase2 pattern; no Phase-1 traffic in window"

    return {
        "name": mvp.get("name"),
        "owner": mvp.get("owner"),
        "lifecycle_status": mvp.get("lifecycle_status") or "active",
        # Decision timestamp (persist-lifecycle writes it next to the status).
        # Passed through for the docx promoted_at column and the ledger's
        # PROMOTED history event.
        "lifecycle_status_at": mvp.get("lifecycle_status_at"),
        "first_seen": mvp.get("first_seen"),
        "last_seen": mvp.get("last_seen"),
        "headline_verdict": verdict,
        "visitors_needed": visitors_needed,
        "note": note,
        "metrics": {
            "gclid_visitors": gclid_visitors,
            "ga_clicks": ga_clicks,
            "ga_clicks_phase1": phase1_clicks if ga_clicks > 0 else None,
            "ga_clicks_phase2": ga_clicks_phase2,
            "signups": signups,
            "effective_signups": effective_signups,
            "signup_source": signup_source,
            "ph_signups": ph_signups,
            "ph_signups_available": mvp.get("ph_signups_available"),
            "db_signups": mvp.get("db_signups"),
            "db_signups_real": mvp.get("db_signups_real"),
            "db_signups_raw": mvp.get("db_signups_raw"),
            "db_signups_paid": mvp.get("db_signups_paid"),
            "db_attribution": mvp.get("db_attribution"),
            "conv_rate": round(conv_rate, 4),
            "true_conv_rate": round(true_conv_rate, 4),
            "capture_rate": round(capture_rate, 4) if capture_rate is not None else None,
            "denominator_source": denominator_source,
            "money_leak": money_leak,
            # CPC-discipline metrics (state-x0a Cost ingest → compute_cpc_flags).
            "ga_cost": cpc_result["metrics"]["ga_cost"],
            "ga_cpc": cpc_result["metrics"]["ga_cpc"],
            "ga_cpc_usd": cpc_result["metrics"]["ga_cpc_usd"],
            "ga_cpc_phase1": cpc_result["metrics"]["ga_cpc_phase1"],
            "ga_currency": cpc_result["metrics"]["ga_currency"],
            "effective_cpc_cap_usd": cpc_result["metrics"]["effective_cpc_cap_usd"],
            "campaign_age_days": cpc_result["metrics"]["campaign_age_days"],
            # Impressions (state-x0a Impr. ingest). None = column absent —
            # annotate_stalled reads that as no_telemetry, 0 as present-but-zero.
            "ga_impressions": mvp.get("ga_impressions"),
            # CPC unit-economics gate (state-x3): implied CAC vs monthly price.
            "monthly_price_usd": cpc_result["metrics"]["monthly_price_usd"],
            "implied_cac_usd": cpc_result["metrics"]["implied_cac_usd"],
            "cpc_payback_multiple": cpc_result["metrics"]["cpc_payback_multiple"],
            "cpc_unit_economics_fail": cpc_result["metrics"]["cpc_unit_economics_fail"],
            # Killed-MVP backend knowledge (sticky db_backend record, x0b /
            # verify-backends). zombie_backend = killed + backend alive + no
            # active backend_keep waiver → teardown worklist (x4/x4b).
            "db_backend_status": (mvp.get("db_backend") or {}).get("status"),
            "zombie_backend": compute_zombie_backend(mvp, money_leak_reference_now),
            # Verdict BEFORE the CPC unit-economics override — x4's kill
            # proposals exempt rows where NO_GO came solely from that gate.
            "pre_cpc_verdict": pre_cpc_verdict,
        },
        "signup_events": signup_events,
        # When state-x0 merged an orphan into this canonical record (high gclid
        # overlap = same deploy with partial page tracking), partial_tracking_pct
        # is the fraction of orphan visitors NOT covered by canonical tracking.
        # state-x4 renders a "⚠ partial tracking" marker on the row when set.
        "partial_tracking_pct": mvp.get("partial_tracking_pct"),
        "ga_only": bool(mvp.get("ga_only")),
        "ga_campaigns": mvp.get("ga_campaigns") or [],
        # Campaign deliverability (state-x0a status-column ingest). None = the
        # operator's CSV omitted the status columns — x4b then keeps the manual
        # confirm-ads path. Pay-intent rows carry these ONLY under
        # phase2_-prefixed names (compute_pay_intent_verdict): the x5 merge is
        # --phase-filter scoped, so its all_stopped covers just the phase2
        # slice and must never be read as a fleet-wide claim.
        "ga_campaign_status_detail": mvp.get("ga_campaign_status_detail") or [],
        "ga_ads_all_stopped": mvp.get("ga_ads_all_stopped"),
        # DB cross-check artifacts (from state-x0b).
        # db_source discriminates which backend supplied db_signups so x4 can
        # render attribution ("supabase" | "railway" | None). db_signups_table
        # is already source-prefixed for Railway (e.g. "railway:public.users"),
        # but the explicit field is cleaner for downstream consumers than
        # string-prefix parsing.
        "db_signups_table": mvp.get("db_signups_table"),
        "db_first_signup_at": db_first_signup_at,
        "db_unmapped_reason": mvp.get("db_unmapped_reason"),
        "db_source": mvp.get("db_source"),
        # Sticky backend knowledge record (x0b/verify-backends) + waiver —
        # passed through for x4 rendering and the x4b teardown reconcile.
        "db_backend": mvp.get("db_backend"),
        "backend_keep": mvp.get("backend_keep"),
        # Operator overrides (config mvp_mappings, overlaid in x1) — passed
        # through so annotate_stalled (waiver / relaunch suppression) and the
        # x4 kill-proposal heredoc read them off the score.
        "cpc_exception": mvp.get("cpc_exception"),
        "channel_waiver": mvp.get("channel_waiver"),
        "phase1_relaunch_at": mvp.get("phase1_relaunch_at"),
        "tracking_sanity_flags": sanity_flags,
    }


def compute_pay_intent_verdict(
    mvp: dict,
    issues: dict,
    thresholds: dict,
    reference_now: datetime | str | None = None,
) -> dict:
    """Apply Phase 2 pay-intent precedence rules for one MVP.

    Precedence (first match wins):
      0. missing_project_name -> MISSING_PROJECT_NAME
      1. ga_clicks_without_ph_traffic -> GA_NO_PH_TRACKING
      2. no_event_data -> NO_DATA
      3. ga_clicks < pay_intent_visitors_floor -> INSUFFICIENT_DATA
      4. pay_intent_rate >= pay_intent_rate_go -> GO
      5. default -> NO_GO

    Phase 2 uses Google Ads clicks as the sole verdict denominator. PostHog
    phase-scoped gclid visitors are diagnostic only and are never a denominator
    fallback in this function.

    Ads-status fields land under phase2_-prefixed names: the x5 merge is
    --phase-filter scoped, so its all_stopped covers just the phase2 campaign
    slice and must never be read as a fleet-wide claim (the phase-1 rows carry
    the unprefixed fields, see compute_headline_verdict).

    `reference_now` (deterministic — max last_seen or the CSV mtime, never
    wall-clock) feeds metrics.campaign_age_days for the ledger-free stalled
    triage; absent -> campaign_age_days None and stalled detection safely
    skips first-sighting rows.
    """
    ga_clicks = _int_value(mvp.get("ga_clicks"))
    ph_pay_intents = _int_value(mvp.get("pay_intents"))
    pay_intents, pay_intent_source, source_flags = resolve_effective_pay_intents(
        mvp,
        issues,
        thresholds,
    )
    tracking_sanity_flags = list(source_flags)
    wiring_flag = compute_pay_intent_wiring_flag(mvp, pay_intents, thresholds)
    if wiring_flag:
        tracking_sanity_flags.append(wiring_flag)
    price_flag = compute_price_change_flag(mvp)
    if price_flag:
        tracking_sanity_flags.append(price_flag)
    # extra_sanity_flags is the cross-MVP side-channel (single writer: x5
    # Step 5.6 assigns it wholesale). Filter to well-formed flag dicts so a
    # malformed entry can't corrupt the report renderer.
    tracking_sanity_flags.extend(
        f
        for f in (mvp.get("extra_sanity_flags") or [])
        if isinstance(f, dict) and f.get("flag")
    )
    pay_intents_db = _int_or_none(mvp.get("db_pay_intents_paid"))
    gclid_visitors_phase2 = _int_value(
        mvp.get("gclid_visitors_phase2", mvp.get("gclid_visitors", 0))
    )
    visitors_floor = thresholds.get("pay_intent_visitors_floor", thresholds["visitors_floor"])
    pay_intent_rate_go = thresholds.get("pay_intent_rate_go", 0.02)
    db_price = mvp.get("db_pay_intent_price_cents_max")
    if pay_intent_source.startswith("db_") and db_price is not None:
        pay_intent_price_cents = _float_value(db_price)
        pay_intent_price_variants = _int_value(mvp.get("db_pay_intent_price_variants"))
    else:
        pay_intent_price_cents = _float_value(mvp.get("pay_intent_price_cents"))
        pay_intent_price_variants = _int_value(mvp.get("pay_intent_price_variants"))
    pay_intent_rate = (pay_intents / ga_clicks) if ga_clicks > 0 else 0.0
    revenue_intent_per_click = (
        pay_intents * pay_intent_price_cents / ga_clicks
        if ga_clicks > 0
        else 0.0
    )
    capture_rate = (gclid_visitors_phase2 / ga_clicks) if ga_clicks > 0 else None

    if issues.get("missing_project_name"):
        verdict = VERDICT_MISSING_PROJECT_NAME
    elif issues.get("ga_clicks_without_ph_traffic"):
        verdict = VERDICT_GA_NO_PH_TRACKING
    elif issues.get("no_event_data"):
        verdict = VERDICT_NO_DATA
    elif ga_clicks < visitors_floor:
        verdict = VERDICT_INSUFFICIENT
    elif pay_intent_rate >= pay_intent_rate_go:
        verdict = VERDICT_GO
    else:
        verdict = VERDICT_NO_GO

    visitors_needed = (
        max(0, visitors_floor - ga_clicks)
        if verdict == VERDICT_INSUFFICIENT
        else 0
    )

    # Phase2-scoped ads deliverability (True/False/None mirrors the phase-1
    # three-way fail-safe: "stopped" is the whitelist, alive is the default).
    # Flag only the verdicts that depend on FUTURE data — a stopped campaign
    # changes what happens next, not what a conclusive GO/NO_GO sample already
    # measured.
    ads_all_stopped = mvp.get("ga_ads_all_stopped")
    status_detail = mvp.get("ga_campaign_status_detail") or []
    if ads_all_stopped is True and verdict in (VERDICT_INSUFFICIENT, VERDICT_NO_DATA):
        names = sorted((d.get("name") or "?") for d in status_detail)
        tracking_sanity_flags.append({
            "flag": "phase2_ads_stopped",
            "severity": "high",
            "message": (
                f"All {len(status_detail)} phase-2 campaign(s) stopped per GA CSV "
                f"({', '.join(names)}) — phase-2 clicks cannot accrue, so this "
                "verdict cannot resolve on its own. Resume the campaign in "
                "Google Ads or close the verdict manually."
            ),
        })

    # Stalled-triage inputs (annotate_stalled reads both from metrics).
    ref = _parse_iso_datetime(reference_now)
    campaign_age_days = None
    first_dt = _parse_iso_datetime(mvp.get("campaign_first_date"))
    if first_dt is not None and ref is not None:
        campaign_age_days = (ref - first_dt).days

    return {
        "name": mvp.get("name"),
        "owner": mvp.get("owner"),
        "headline_verdict": verdict,
        "visitors_needed": visitors_needed,
        "metrics": {
            "gclid_visitors_phase2": gclid_visitors_phase2,
            "gclid_visitors": mvp.get("gclid_visitors", gclid_visitors_phase2),
            "ga_clicks": ga_clicks,
            "pay_intents": pay_intents,
            "pay_intent_source": pay_intent_source,
            "pay_intents_db": pay_intents_db,
            "pay_intents_posthog": ph_pay_intents,
            "pay_intents_unattributed": _int_value(mvp.get("db_pay_intents_unattributed")),
            "pay_intent_rate": round(pay_intent_rate, 4),
            "pay_intent_price_cents": pay_intent_price_cents,
            "revenue_intent_per_click": round(revenue_intent_per_click, 2),
            "pay_intent_price_variants": pay_intent_price_variants,
            "pay_intent_rate_go": pay_intent_rate_go,
            "capture_rate": round(capture_rate, 4) if capture_rate is not None else None,
            "denominator_source": "ga",
            "campaign_age_days": campaign_age_days,
            # None ⇔ the CSV had no Impr. column (stalled cause: no_telemetry).
            "ga_impressions": mvp.get("ga_impressions"),
        },
        "phase_match": mvp.get("phase_match"),
        "orphan": bool(mvp.get("orphan")),
        "ga_only": bool(mvp.get("ga_only")),
        "ga_campaigns": mvp.get("ga_campaigns") or [],
        "partial_tracking_pct": mvp.get("partial_tracking_pct"),
        "tracking_sanity_flags": tracking_sanity_flags,
        "phase2_ads_all_stopped": ads_all_stopped,
        "phase2_campaign_status_detail": status_detail,
    }


def pay_intent_go_rank_key(score: dict) -> tuple[float, float, int, str]:
    metrics = score.get("metrics", {})
    return (
        -float(metrics.get("revenue_intent_per_click") or 0),
        -float(metrics.get("pay_intent_rate") or 0),
        -int(metrics.get("ga_clicks") or 0),
        score.get("name") or "",
    )


def pay_intent_score_key(score: dict, order: dict | None = None) -> tuple:
    verdict_order = order or PAY_INTENT_VERDICT_SORT_ORDER
    return (
        verdict_order.get(score.get("headline_verdict"), 99),
        *pay_intent_go_rank_key(score),
    )


def pay_intent_revenue_cell(metrics: dict) -> str:
    rev = float(metrics.get("revenue_intent_per_click") or 0)
    cell = f"${rev / 100:.2f}"
    if int(metrics.get("pay_intent_price_variants") or 0) > 1:
        cell += " ⚠ mixed-price"
    return cell


def compute_db_sanity_flags(
    paid_signups: int,
    db_signups: int | None,
    db_first_signup_at: str | None,
    first_seen: str | None,
    ga_clicks: int,
    db_attribution: str | None = None,
    db_union_tables: list | None = None,
) -> list[dict]:
    """Emit human-readable sanity flags when PostHog and Supabase disagree.

    Returns a list of {flag, severity, message} dicts. Empty list means
    PH and DB agree (or DB has no signal to compare against).

    Flag semantics:
      - ph_attribution_broken: DB has signups but PH paid is zero. gclid
        attribution likely lost between landing and signup page. (x-predict
        is the canonical example: 18 DB users, 0 paid.)
      - ph_undercount: DB has > 3x PH paid signups. Either organic-only
        signups (fine) OR PostHog `signup_complete` track call instrumented
        late / not on every signup path (stylica-ai pattern).
      - ph_overcount: PH paid > DB total * 1.5. signup_events config likely
        wrong (counting a non-signup event — stylica-ai's `activate` before
        the operator-locked fix).
      - late_instrumentation: PH's first signup event is > 7 days AFTER the
        DB's first signup row. Operator likely added the track() call after
        product launched. Early signups silently lost.
      - db_union_multi_table: informational — the DB count is a cross-table
        email union (>=2 tables contributed real signups after dedupe), so
        db_signups_table names only the top contributor.

    All flags are non-blocking — they surface in x4 output for operator review.
    """
    flags: list[dict] = []
    attribution_note = (
        " Verdict used DB paid gclid-shape signups; this diagnostic compares PostHog paid signups "
        "against all real DB signups in the window."
        if db_attribution == "gclid_shape"
        else ""
    )

    if db_signups is None:
        # No DB comparison available; nothing to flag.
        return flags

    if db_union_tables and len(db_union_tables) >= 2:
        flags.append({
            "flag": "db_union_multi_table",
            "severity": "info",
            "message": (
                f"DB signup counts are a cross-table union of {len(db_union_tables)} tables "
                f"({', '.join(db_union_tables)}); emails gmail-normalized and deduplicated. "
                "db_signups_table names the top contributor; per-table raws in db_breakdown."
            ),
        })

    # ph_attribution_broken: paying for ads, DB has rows, PH paid is zero.
    if db_signups >= 3 and paid_signups == 0 and ga_clicks > 0:
        flags.append({
            "flag": "ph_attribution_broken",
            "severity": "high",
            "message": (
                f"DB has {db_signups} signups but PostHog paid count is 0. "
                "gclid attribution may be lost between landing and signup page — "
                "check that PostHog SDK captures $session_entry_gclid before the URL is cleaned."
                f"{attribution_note}"
            ),
        })

    # ph_overcount: PH > 1.5x DB total → likely wrong signup_events event name.
    elif db_signups > 0 and paid_signups > db_signups * 1.5:
        flags.append({
            "flag": "ph_overcount",
            "severity": "high",
            "message": (
                f"PostHog paid signups ({paid_signups}) > DB total ({db_signups}) * 1.5. "
                "Likely classified a non-signup event (e.g. activate firing on feature-use). "
                "Edit experiment/iterate-cross-config.yaml mvp_mappings.<name>.signup_events and lock with classified_by: operator."
                f"{attribution_note}"
            ),
        })

    # ph_undercount: DB > 3x PH paid → late instrumentation, broken track path, or organic-only.
    elif db_signups > paid_signups * 3 and db_signups >= 3:
        flags.append({
            "flag": "ph_undercount",
            "severity": "medium",
            "message": (
                f"DB has {db_signups} signups, PostHog paid only {paid_signups}. "
                "Could be organic-only traffic (no gclid) OR PostHog track('signup_complete') "
                "not covering all signup paths (e.g. OAuth callback fires server-side)."
                f"{attribution_note}"
            ),
        })

    # late_instrumentation: PH first event > 7d AFTER DB first row.
    # `first_seen` on the MVP is the earliest PH event with gclid attribution,
    # which is the right baseline for "when did paid tracking start working".
    if db_first_signup_at and first_seen:
        try:
            from datetime import datetime, timezone

            def parse_iso(s: str) -> datetime:
                # Tolerate space-separated and various trailing fragments.
                s = s.replace(" ", "T")
                if "+" in s:
                    s = s.split("+")[0] + "+00:00"
                if s.endswith("Z"):
                    s = s[:-1] + "+00:00"
                if "." in s and len(s.split(".")[-1].split("+")[0]) > 6:
                    # Trim sub-microsecond precision Postgres sometimes emits.
                    head, _, tail = s.partition(".")
                    frac, _, tz = tail.partition("+")
                    s = f"{head}.{frac[:6]}+{tz}" if tz else f"{head}.{frac[:6]}"
                if "+" not in s:
                    s = s + "+00:00"
                return datetime.fromisoformat(s)

            db_first = parse_iso(db_first_signup_at)
            ph_first = parse_iso(first_seen)
            gap_days = (ph_first - db_first).days
            if gap_days >= 7:
                flags.append({
                    "flag": "late_instrumentation",
                    "severity": "high",
                    "message": (
                        f"PostHog first paid event ({ph_first.date()}) is {gap_days} days AFTER "
                        f"first DB signup ({db_first.date()}). "
                        "Tracking was added after product launch — signups before the PH instrument "
                        "date are invisible to /iterate. Consider extending the analysis window or "
                        "noting the gap when interpreting the conversion rate."
                    ),
                })
        except (ValueError, TypeError):
            # Date parsing failure is non-critical; skip the flag.
            pass

    return flags


ACTION_TEMPLATES = {
    VERDICT_GO: "Confirm the promote proposal in the x4 report (writes lifecycle_status: promoted to config), then: fake-door -> manual Phase 2 campaign -> /ads-ready phase-2 -> /iterate --cross --phase2. See Phase 2 Playbook.",
    VERDICT_WEAK: "{name}: above visitors floor but only {signups} signups. Investigate landing-page friction or extend campaign window before deciding.",  # deprecated — current rule never emits WEAK
    VERDICT_NO_GO: "Stop {name}; document hypothesis rejection in retro. (≥{visitors_floor} visitors with conv < {conv_rate_go_pct})",
    VERDICT_INSUFFICIENT: "Keep {name} running until {visitors_needed} more visitors arrive (target: {visitors_floor}+).",
    VERDICT_NO_DATA: "Debug PostHog tracking for {name}. Run Claude Code in the MVP repo with the NO_DATA prompt below.",
    VERDICT_MISSING_PROJECT_NAME: "Fix {name} tracking: PostHog events arrived without `project_name`. Check `src/lib/analytics.ts` PROJECT_NAME constant — it must equal experiment.yaml.name (kebab-case). Re-run /verify in the MVP repo after fixing.",
    VERDICT_GA_NO_PH_TRACKING: "Fix {name}: Google Ads is serving paid traffic but PostHog records ZERO events. Either the deploy is missing src/lib/analytics.ts entirely, the ad's Final URL points to a page that doesn't import analytics, or PROJECT_NAME doesn't match what /iterate --cross expects. Check Final URL in Google Ads, then verify analytics.ts is imported on that page.",
}

PAY_INTENT_ACTION_TEMPLATES = {
    VERDICT_GO: "Promote {name} to Phase 3 eligibility; rank GO MVPs by revenue-intent per click (pay-intent rate × reference price) as slots open.",
    VERDICT_NO_GO: "Stop {name}; free usage did not convert to pay intent at Phase 2 threshold.",
    VERDICT_INSUFFICIENT: "Keep {name} running until {visitors_needed} more Phase 2 clicks arrive (target: {visitors_floor}+).",
    VERDICT_NO_DATA: "Debug Phase 2 PostHog tracking for {name}; no phase-scoped event data was observed.",
    VERDICT_MISSING_PROJECT_NAME: "Fix {name} tracking: Phase 2 paid events arrived without `project_name`.",
    VERDICT_GA_NO_PH_TRACKING: "Fix {name}: Phase 2 Google Ads has clicks but PostHog records zero phase-scoped paid traffic.",
}


def _format_rate_pct(rate: float) -> str:
    return f"{rate * 100:g}%"


def action_line(
    verdict: str,
    name: str,
    signups: int,
    visitors_needed: int,
    visitors_floor: int,
    conv_rate_go: float = 0.06,
) -> str:
    template = ACTION_TEMPLATES.get(verdict, "Unknown verdict.")
    return template.format(
        name=name,
        signups=signups,
        visitors_needed=visitors_needed,
        visitors_floor=visitors_floor,
        conv_rate_go_pct=_format_rate_pct(conv_rate_go),
    )


def pay_intent_action_line(
    verdict: str,
    name: str,
    pay_intents: int,
    visitors_needed: int,
    visitors_floor: int,
    pay_intent_rate_go: float = 0.02,
) -> str:
    template = PAY_INTENT_ACTION_TEMPLATES.get(verdict, "Unknown verdict.")
    return template.format(
        name=name,
        pay_intents=pay_intents,
        visitors_needed=visitors_needed,
        visitors_floor=visitors_floor,
        pay_intent_rate_go_pct=_format_rate_pct(pay_intent_rate_go),
    )


PAY_INTENT_ADS_STOPPED_ACTIONS = {
    VERDICT_INSUFFICIENT: (
        "Phase 2 ads stopped per GA CSV — {name} cannot reach the click floor "
        "on its own; resume the campaign in Google Ads or decide manually."
    ),
    VERDICT_NO_DATA: (
        "Phase 2 ads stopped per GA CSV — {name} has no traffic to track; "
        "resume the campaign before debugging tracking."
    ),
}


def pay_intent_ads_stopped_action(score: dict) -> str | None:
    """Override action for phase2 rows whose (phase-scoped) campaigns are all
    verifiably stopped: "keep collecting" / "debug tracking" are wrong when the
    denominator can no longer grow. None -> caller keeps the default action.
    GO/NO_GO never override — the observed sample is already conclusive."""
    if score.get("phase2_ads_all_stopped") is not True:
        return None
    template = PAY_INTENT_ADS_STOPPED_ACTIONS.get(score.get("headline_verdict"))
    if template is None:
        return None
    return template.format(name=score.get("name") or "(unknown)")


def _score_is_money_leak(score: dict) -> bool:
    return bool((score.get("metrics") or {}).get("money_leak"))


def _score_is_archived(score: dict) -> bool:
    return (
        score.get("lifecycle_status") == "killed"
        or score.get("db_unmapped_reason") in ("project_deleted", "archived_killed")
    )


# Conversion-class verdicts eligible for the promoted partition. Data-integrity
# verdicts (MISSING_PROJECT_NAME / GA_NO_PH_TRACKING / NO_DATA) always render in
# their FIX surfaces instead — a promoted MVP with broken tracking must stay on
# the fix worklist (phase2 measurement depends on tracking too).
_PROMOTED_PARTITION_VERDICTS = (VERDICT_GO, VERDICT_NO_GO, VERDICT_INSUFFICIENT)


def _score_is_promoted(score: dict) -> bool:
    """Promoted partition rule. Precedence: money_leak > archived > promoted.

    iterate_cross_docx deliberately avoids importing this module (see its
    header), so it carries a local twin (is_promoted); the partition-parity
    test pins the two implementations together.
    """
    return (
        score.get("lifecycle_status") == "promoted"
        and score.get("headline_verdict") in _PROMOTED_PARTITION_VERDICTS
        and not _score_is_money_leak(score)
        and not _score_is_archived(score)
    )


def _team_pause_bullet(score: dict) -> str | None:
    """Money-leak pause wording, keyed on CSV deliverability (status columns).

    None when every campaign is verifiably stopped — tail traffic is a no-op
    and the team message carries action items only.
    """
    all_stopped = score.get("ga_ads_all_stopped")
    if all_stopped is True:
        return None
    name = score.get("name") or "(unknown)"
    if all_stopped is False:
        active = sorted(
            (d.get("name") or "?")
            for d in (score.get("ga_campaign_status_detail") or [])
            if d.get("normalized") == "active"
        )
        if active:
            return (
                f"{name}: PAUSE NOW in Google Ads — {', '.join(active)} "
                "(killed MVP, campaigns still deliverable)"
            )
        return f"{name}: ads not verifiably stopped — check Google Ads and pause (killed MVP)"
    return (
        f"{name}: ads status unknown (export lacked status columns) — "
        "check Google Ads (killed MVP with recent paid traffic)"
    )


def _team_phase1_bullet(score: dict, visitors_floor: int, conv_rate_go: float) -> str:
    """One action bullet for a normal-partition phase-1 row."""
    verdict = score.get("headline_verdict")
    name = score.get("name") or "(unknown)"
    metrics = score.get("metrics") or {}
    unit = "clicks" if metrics.get("denominator_source") == "ga" else "visitors"

    if verdict == VERDICT_GO:
        conv = metrics.get("true_conv_rate")
        conv_txt = f" at {conv * 100:.1f}%" if isinstance(conv, (int, float)) else ""
        text = (
            f"GO{conv_txt} — confirm the promote proposal, then the Phase 2 playbook "
            "(fake-door → manual Phase 2 campaign → /ads-ready phase-2 → /iterate --cross --phase2)"
        )
    elif verdict == VERDICT_NO_GO:
        if metrics.get("cpc_unit_economics_fail"):
            text = (
                f"NO_GO on CPC unit economics — CPC ${metrics.get('ga_cpc_usd')} over "
                f"${metrics.get('effective_cpc_cap_usd')} cap, implied CAC "
                f"${metrics.get('implied_cac_usd')} > ${metrics.get('monthly_price_usd')}/mo; "
                "lower bids and relaunch, or record a cpc_exception"
            )
        else:
            conv = metrics.get("true_conv_rate")
            conv_txt = f"{conv * 100:.1f}%" if isinstance(conv, (int, float)) else "below-threshold"
            text = f"stop — NO_GO ({conv_txt} conv past the {visitors_floor}-{unit[:-1]} floor)"
    elif verdict == VERDICT_INSUFFICIENT:
        text = (
            f"keep running — {score.get('visitors_needed')} more {unit} "
            f"to the {visitors_floor}-{unit[:-1]} floor"
        )
    elif verdict == VERDICT_GA_NO_PH_TRACKING:
        text = (
            "fix tracking — Google Ads spends but PostHog sees zero events "
            "(check the analytics import on the ad's Final URL + PROJECT_NAME)"
        )
    else:  # VERDICT_NO_DATA and any legacy verdicts
        text = "fix tracking — no PostHog events found (tracking likely not deployed)"

    # High-severity sanity flags are the actionable diagnostics; the one flag
    # already voiced by the NO_GO CPC wording is not repeated.
    high = [
        tf["flag"]
        for tf in (score.get("tracking_sanity_flags") or [])
        if tf.get("severity") == "high" and tf.get("flag") != "cpc_unit_economics_fail"
    ]
    suffix = f" ⚠ {', '.join(high)}" if high else ""
    return f"{name}: {text}{suffix}"


def _team_teardown_bullet(obligation: dict) -> str:
    def _status(key: str) -> str:
        value = obligation.get(key)
        if isinstance(value, dict):
            value = value.get("status")
        return str(value or "unknown").upper()

    age = obligation.get("killed_age_days")
    age_txt = f" (killed {age}d ago)" if age is not None else ""
    return (
        f"{obligation.get('mvp')}: tear down — DB:{_status('db')} "
        f"HOST:{_status('hosting')} ADS:{_status('ads').lower()}{age_txt}"
    )


def emit_team_message(
    scores: list,
    thresholds: dict,
    obligations: list | None = None,
    phase: int = 1,
    doc_link: str = "<google-doc-link>",
) -> str:
    """Copy-paste team hand-off: results-doc header + per-member action items.

    Prints-to-stdout replacement for the retired on-disk chat artifact
    (operator decision 2026-07-27). Action items only — orphan
    MISSING_PROJECT_NAME rows, archived/promoted reference rows, verifiably
    stopped money-leak rows, and the universal-rule footer are all excluded;
    owners with nothing to do are omitted entirely.
    """
    if phase == 2:
        visitors_floor = int(
            thresholds.get("pay_intent_visitors_floor")
            or thresholds.get("visitors_floor", 100)
        )
        rate_go = float(thresholds.get("pay_intent_rate_go", 0.02) or 0.02)
    else:
        visitors_floor = int(thresholds.get("visitors_floor", 100) or 100)
        rate_go = float(thresholds.get("conv_rate_go", 0.06) or 0.06)

    items_by_owner: dict = {}
    paused_names: set = set()

    def _add(owner, bullet):
        items_by_owner.setdefault(owner or "unassigned", []).append(bullet)

    for s in sort_scores_by_owner(scores):
        if s.get("headline_verdict") == VERDICT_MISSING_PROJECT_NAME:
            continue  # orphan streams live in the report, not the team message
        owner = s.get("owner") or "unassigned"
        name = s.get("name") or "(unknown)"
        if phase == 1 and _score_is_money_leak(s):
            bullet = _team_pause_bullet(s)
            if bullet:
                _add(owner, bullet)
                paused_names.add(name)
            continue
        if phase == 1 and (_score_is_archived(s) or _score_is_promoted(s)):
            continue
        if phase == 2:
            metrics = s.get("metrics") or {}
            action = pay_intent_ads_stopped_action(s) or pay_intent_action_line(
                s.get("headline_verdict"),
                name,
                metrics.get("pay_intents", 0),
                s.get("visitors_needed", 0),
                visitors_floor,
                rate_go,
            )
            high = [
                tf["flag"]
                for tf in (s.get("tracking_sanity_flags") or [])
                if tf.get("severity") == "high"
            ]
            suffix = f" ⚠ {', '.join(high)}" if high else ""
            _add(owner, f"{action}{suffix}")
        else:
            _add(owner, _team_phase1_bullet(s, visitors_floor, rate_go))

    for o in obligations or []:
        owner = o.get("owner") or "unassigned"
        # still_serving rows are campaign dicts ({name, campaign_status, ...}).
        still = [
            (c.get("name") or "?") if isinstance(c, dict) else str(c)
            for c in (o.get("still_serving") or [])
        ]
        if still and o.get("mvp") not in paused_names:
            _add(
                owner,
                f"{o.get('mvp')}: PAUSE NOW in Google Ads — {', '.join(still)} "
                "(killed MVP, campaigns still deliverable)",
            )
        if o.get("teardown_state") == "due":
            _add(owner, _team_teardown_bullet(o))

    header = f"📊 Latest Phase {phase} Google Ads results: {doc_link}"
    if not items_by_owner:
        return f"{header}\n\nNo action items this run."
    owners = sorted(items_by_owner, key=lambda o: (o == "unassigned", o))
    blocks = [header]
    for owner in owners:
        blocks.append(
            f"@{owner}\n" + "\n".join(f"• {item}" for item in items_by_owner[owner])
        )
    return "\n\n".join(blocks)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compute headline verdicts and/or emit reports for /iterate --cross.",
    )
    parser.add_argument("--data", default=".runs/iterate-cross-data.json", help="Input: data + signups from x2")
    parser.add_argument("--issues", default=".runs/iterate-cross-data-issues.json", help="Input: integrity flags from x1a")
    parser.add_argument(
        "--scores",
        default=None,
        help="Optional input: pre-computed scores file. If provided, skip recomputation (used by x4 to avoid clobbering x3 output).",
    )
    parser.add_argument("--config", default="experiment/iterate-cross-config.yaml")
    parser.add_argument("--run-dir", default=".runs")
    parser.add_argument(
        "--output",
        default=None,
        help="Output: write computed scores here. If omitted (and --scores not provided), scores stay in-memory only.",
    )
    parser.add_argument(
        "--emit-team-message",
        action="store_true",
        help="Output: print the copy-paste team hand-off (header + per-member action items) to stdout.",
    )
    parser.add_argument(
        "--obligations",
        default=None,
        help="Optional input for --emit-team-message: teardown obligations JSON from x4b reconcile.",
    )
    parser.add_argument("--phase", type=int, choices=(1, 2), default=1, help="Team-message flavor: 1 = conversion actions, 2 = pay-intent actions.")
    parser.add_argument("--doc-link", default="<google-doc-link>", help="Results-doc placeholder in the team-message header (operator pastes the real link).")
    parser.add_argument("--emit-docx", default=None, help="Output: write the .docx decision report here (best-effort; needs python-docx).")
    parser.add_argument(
        "--reference-now",
        default=None,
        help="Deterministic window end for money-leak checks (ISO timestamp). Defaults to current UTC time.",
    )
    parser.add_argument(
        "--money-leak-window-days",
        type=int,
        default=None,
        help="Recent-traffic window for money-leak checks. Defaults to config money_leak_recent_days or 14.",
    )
    parser.add_argument(
        "--ledger",
        default="experiment/mvp-decision-ledger.jsonl",
        help=(
            "Previous-run decision ledger for stalled-campaign velocity "
            "(run-over-run click deltas + streak carry-forward). Missing file "
            "→ lifetime-velocity detection only; a first-ever run never escalates."
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="Compute outputs without writing score artifacts (the team message still prints — it is stdout-only).")
    args = parser.parse_args(argv)

    if not args.output and not args.emit_team_message and not args.emit_docx:
        print("ERROR: must specify at least one of --output, --emit-team-message, or --emit-docx.", file=sys.stderr)
        return 2

    config = load_config(args.config)
    thresholds = config["thresholds"]
    fx_to_usd = config.get("fx_to_usd") or {}
    max_cpc_basis = config.get("max_cpc_basis", "usd")
    window_days = config.get("window_days", 90)
    money_leak_window_days = args.money_leak_window_days
    if money_leak_window_days is None:
        money_leak_window_days = int(config.get("money_leak_recent_days", 14) or 14)

    if args.scores and os.path.exists(args.scores):
        score_data = json.load(open(args.scores))
        scores = score_data.get("mvps", [])
    else:
        data = json.load(open(args.data))
        issues_data = json.load(open(args.issues))
        issues_by_name = {m["name"]: m for m in issues_data.get("mvps", [])}
        money_leak_reference_now = (
            _parse_iso_datetime(args.reference_now)
            or _parse_iso_datetime(data.get("money_leak_reference_now"))
            or _parse_iso_datetime(data.get("window_end"))
            or datetime.now(timezone.utc)
        )

        scores = []
        for mvp in data.get("mvps", []):
            issues = issues_by_name.get(mvp["name"], {})
            scores.append(compute_headline_verdict(
                mvp,
                issues,
                thresholds,
                money_leak_reference_now=money_leak_reference_now,
                money_leak_window_days=money_leak_window_days,
                fx_to_usd=fx_to_usd,
                max_cpc_basis=max_cpc_basis,
            ))
        # INSUF futility triage: annotate each INSUFFICIENT_DATA row with the
        # sequential-futility probability + bucket. Verdicts are unchanged —
        # state-x4 folds kill_candidate rows into the operator-confirmed
        # kill-proposal flow and renders verify_data / revive_candidate lists.
        annotate_futility(scores, thresholds, reference_now=money_leak_reference_now)
        # Stalled-flow triage: zero-velocity INSUF rows (bid-capped shortfall).
        # Reads the previous ledger snapshot for run-over-run deltas + streak
        # carry-forward; verdicts unchanged — state-x4 renders the STALLED
        # worklist and folds stalled_escalated rows into the kill proposals.
        annotate_stalled(
            scores,
            thresholds,
            _read_prev_ledger(args.ledger),
            reference_now=money_leak_reference_now,
        )

    output = {
        "thresholds": thresholds,
        "window_days": window_days,
        "mvps": sort_scores_global(scores),
    }

    if args.output and not args.dry_run:
        json.dump(output, open(args.output, "w"), indent=2)
        print(f"Wrote {args.output} ({len(scores)} MVPs)")
    elif args.output:
        print(f"DRY-RUN: would write {args.output} ({len(scores)} MVPs)")

    if args.emit_team_message:
        obligations = None
        if args.obligations and os.path.exists(args.obligations):
            obligations = json.load(open(args.obligations)).get("obligations", [])
        print(emit_team_message(
            scores,
            thresholds,
            obligations=obligations,
            phase=args.phase,
            doc_link=args.doc_link,
        ))

    if args.emit_docx:
        # Best-effort: a missing python-docx (or any render error) must never break
        # the pipeline. The scores artifact is the gated output; the team message
        # prints to stdout above; the .docx is a convenience report.
        try:
            import iterate_cross_docx
            gen_date = (args.reference_now or "")[:10] or None
            ok, msg = iterate_cross_docx.emit_docx(
                scores, thresholds, args.emit_docx, dry_run=args.dry_run, gen_date=gen_date
            )
            print(msg)
        except Exception as e:  # noqa: BLE001
            print(f"WARN: .docx report generation failed ({e}); continuing.", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
