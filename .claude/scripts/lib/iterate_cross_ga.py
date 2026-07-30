#!/usr/bin/env python3
"""iterate_cross_ga.py — Bucket Google Ads campaigns into MVP records and merge clicks
into the iterate-cross context.

State-x0a runs this after the operator exports a CSV from Google Ads UI and saves it
at .runs/iterate-cross-ga-clicks.csv. It folds `ga_clicks` into the per-MVP records
produced by state-x0, creates `ga_only` records for campaigns with no PostHog MVP,
and emits warnings for genuinely unmatched campaigns.

Browser scraping was removed (PR fix/iterate-cross-csv-blocking). Rationale:
the scraper was brittle to Google Ads UI changes (column-position drift, render
timing, virtualization, anti-automation fallback page) and failed silently —
producing zero or junk `ga_clicks` values that masqueraded as real data. CSV
export is the only supported source; state-x0a halts loudly if the file is
missing or malformed.

Input shape (CSV at .runs/iterate-cross-ga-clicks.csv):
  Header row required. Required columns (case-insensitive substring match):
    Campaign, Clicks
  Optional columns: Account, Conversions (or Conv.), Impressions / Impr.,
    Campaign status / Status / Status reasons (EXACT header match only —
    campaign deliverability; feeds ga_ads_all_stopped and x4b csv_paused)
  Column order is irrelevant — the parser indexes by header.
  Thousands separators (1,082) are stripped.
  Encoding/delimiter are auto-detected: Google Ads exports default to UTF-16 LE
  (BOM) + TAB-delimited with 1-2 preamble lines; hand-saved UTF-8/comma CSVs also
  work. Summary rows are skipped whether the "Total:" marker is in the Campaign
  cell or the Campaign-status column (Campaign cell shows the "--" placeholder).

Subcommands:
  validate-csv — verify the CSV has required columns + at least one data row.
                 State-x0a calls this BEFORE merge to fail-fast with a clear
                 diagnostic when the operator's export is missing columns.
  merge        — fold CSV clicks into .runs/iterate-cross-context.json.

Bucketing algorithm (unchanged):
  1. Compute campaign-MVP-name by stripping ad-naming suffixes
     (-search-v1, _Search_V1, etc.).
  2. Try substring match of stripped name's match_key against existing MVP keys.
  3. If no PH match, check operator-declared `ga_campaign_aliases` in config
     (keyed by match_key of campaign name).
  4. If still no match AND the stripped name is alphabetic (not "Campaign #1"),
     auto-create a `ga_only` MVP record.
  5. Otherwise: stderr warning + emit to unmatched-out file.

Why match_key (alphanumeric-only normalizer): reused from iterate_cross_classify.py.
Operator-declared kebab/snake/camel variants of the same MVP-name all collapse to
one key. Same matcher used for the orphan-host merge in state-x0.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys

# Reuse the existing matcher to avoid drift between orphan-host merge and GA bucket logic.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from iterate_cross_classify import match_key  # noqa: E402


# Patterns we strip from a GA campaign name to recover its MVP prefix.
# Stripped left-to-right; longest patterns first to avoid partial matches
# leaving residue (e.g., "search-v1" left over after stripping "v1").
#
# Separator class `[SEP]` covers whitespace, underscore, hyphen, em-dash,
# and en-dash (Google Ads name editor produces all four; the em-dash form
# appears in "NeuralPost — Phase 1 — Search").
_SEP = r"[\s_\-–—]"
_AD_SUFFIX_PATTERNS = [
    # Date-suffixed campaign variants (NeuralPost_5Day_Apr2026, etc.)
    rf"{_SEP}+\d+{_SEP}*day{_SEP}+\w{{3}}\d{{4}}\b.*",  # e.g. "_5Day_Apr2026"
    # Phase / Search / v-numbered suffixes
    rf"{_SEP}+search{_SEP}+validation{_SEP}+v\d+\b.*",   # "_Search_Validation_V1"
    rf"{_SEP}+search{_SEP}+v\d+(?:{_SEP}+\w+)?\b.*",      # "-search-v1", "_Search_V1", "-search-v1-manual"
    rf"{_SEP}+phase{_SEP}+\d+{_SEP}+search\b.*",          # "— Phase 1 — Search"
    rf"{_SEP}+search\b.*",                                # "-Search" (trailing)
    rf"{_SEP}+v\d+\b.*",                                   # bare "-v1"
    rf"{_SEP}+#\d+\b.*",                                   # "#1", "#2"
    # Trailing owner-suffix tokens (Lumen-Parth, StaylicaAi-Lew). These come AFTER
    # the prefix patterns above so they don't strip mid-name tokens.
    rf"{_SEP}+(?:parth|lew|lego|lee|radlin|anurag|karan|taran|pcentric|lathiya)\b.*",
    # Dubai-style geographic suffix (Handpick - Dubai Search)
    rf"{_SEP}+dubai\b.*",
    # Performance-max viral-traffic markers
    rf"{_SEP}*[—\-]{_SEP}+pmax\b.*",
]


def extract_mvp_name(campaign_name: str) -> str:
    """Strip GA suffix patterns to recover the underlying MVP name.

    Returns the stripped name (still original case + punctuation). Caller
    typically pipes through `match_key()` before comparison.
    """
    name = (campaign_name or "").strip()
    for pat in _AD_SUFFIX_PATTERNS:
        name = re.sub(pat, "", name, flags=re.IGNORECASE)
    return name.strip(" -_")


def is_placeholder_campaign(campaign_name: str) -> bool:
    """True when the campaign name is a generic Google Ads placeholder (no MVP signal).

    `Campaign #1`, `Campaign #2`, etc. are created by Google Ads as default names
    for new campaigns. Without a real name, we cannot bucket — operator must rename
    or add an alias.

    Also matches placeholder names with a trailing parenthetical disambiguator
    (e.g. "Campaign #1 (Parth)") — those are placeholders that operators have
    annotated with the owner's name but never renamed properly.
    """
    if not campaign_name:
        return True
    return bool(
        re.match(
            r"^\s*campaign\s*#?\d+(\s*\([^)]*\))?\s*$",
            campaign_name,
            flags=re.IGNORECASE,
        )
    )


# Campaign deliverability normalization — the single source of truth for "can
# this campaign still spend money?". state-x4b's csv_paused evidence and the
# money-leak wording consume it; the state-c2 unpause guard (#1878) should
# import it rather than re-deriving Ended/Paused semantics.
#
# Google Ads exposes TWO status columns: "Campaign status" is the on/off switch
# (Enabled/Paused/Removed); "Status" is the serving state (Eligible, Eligible
# (Limited), Eligible (Learning), Ended, Paused, Removed, Pending, ...).
# Enabled+Ended does NOT deliver (past its end date) — the switch column alone
# misclassifies it as live, so "stopped" checks BOTH columns.
_STOPPED_CAMPAIGN_STATUS = {"paused", "removed"}
_STOPPED_SERVING_STATUS = {"ended", "paused", "removed"}


def normalize_campaign_status(
    campaign_status: str | None, serving_status: str | None
) -> str:
    """Return 'stopped' | 'active' | 'unknown' for one campaign row.

    stopped — whitelist only: switch ∈ {Paused, Removed} or serving ∈ {Ended,
              Paused, Removed}. Only these values may contribute to
              ga_ads_all_stopped=True.
    active  — Enabled switch with any other serving value (Eligible*, Pending,
              unrecognized): the campaign can spend money.
    unknown — no usable data (columns absent, empty cells, localized UI
              values). Every consumer treats it like active — the failure
              direction is an extra reminder, never a silent close-out.
    """
    cs = (campaign_status or "").strip().lower()
    sv = (serving_status or "").strip().lower()
    if cs in _STOPPED_CAMPAIGN_STATUS or sv in _STOPPED_SERVING_STATUS:
        return "stopped"
    if cs == "enabled":
        return "active"
    return "unknown"


def _derive_all_stopped(detail: list[dict]) -> bool | None:
    """Tri-state ga_ads_all_stopped from a bucket's status detail.

    None ⇔ no status data at all (export lacked the columns) — downstream then
    behaves exactly as before this field existed. True ⇔ every campaign is
    verifiably stopped. False otherwise (any active OR unknown row: judging
    "stopped" is the whitelist, "alive" is the default)."""
    if not detail:
        return None
    if all(
        d.get("campaign_status") is None and d.get("serving_status") is None
        for d in detail
    ):
        return None
    return all(d.get("normalized") == "stopped" for d in detail)


def bucket_campaign(
    campaign_name: str,
    mvp_keys: set[str],
    aliases: dict[str, str] | None = None,
) -> tuple[str | None, str]:
    """Return (mvp_name, reason) for a single campaign.

    - mvp_name: the canonical MVP key this campaign belongs to (None if unmatched).
    - reason: short tag describing how the match was made
              ("ph-substring", "alias", "ga-only-auto", "unmatched", "placeholder").

    Strategy:
      1. If campaign is a placeholder ("Campaign #1") → unmatched.
      2. Extract candidate MVP-name by stripping ad suffixes.
      3. Substring match against existing PH MVP match_keys (longest match wins).
      4. Check operator-declared aliases (keyed by full campaign match_key).
      5. Otherwise auto-create a ga_only MVP using the stripped name.
    """
    aliases = aliases or {}

    if is_placeholder_campaign(campaign_name):
        return None, "placeholder"

    candidate = extract_mvp_name(campaign_name)
    candidate_key = match_key(candidate)

    # Step 1: substring match — longest match wins. Reverse-sorted by length so
    # "stylica-ai" matches before "stylica" (if both happened to exist).
    mvp_match_keys = sorted(
        ((k, match_key(k)) for k in mvp_keys if k and not k.startswith("__")),
        key=lambda kv: -len(kv[1]),
    )
    for k, mk in mvp_match_keys:
        if not mk:
            continue
        if mk in candidate_key:
            return k, "ph-substring"

    # Step 2: operator alias on the full (un-stripped) campaign name.
    full_key = match_key(campaign_name)
    if full_key in aliases:
        return aliases[full_key], "alias"

    # Also try the stripped key against aliases.
    if candidate_key in aliases:
        return aliases[candidate_key], "alias"

    # Step 3: auto-create ga_only MVP from the stripped candidate.
    if candidate_key and candidate_key.isalnum():
        # Use the stripped candidate (lowercased, hyphenated) as the new MVP name.
        # Don't kebab-case here — preserve a recognizable form.
        ga_only_name = re.sub(r"[\s_]+", "-", candidate).lower().strip("-")
        if ga_only_name:
            return ga_only_name, "ga-only-auto"

    return None, "unmatched"


def _read_csv_text(path: str) -> str:
    """Decode a Google Ads CSV export to text, BOM/encoding-aware.

    Google Ads "Campaign report" exports default to UTF-16 LE (with BOM) and are
    TAB-delimited; some hand-saved files are UTF-8. Detect the UTF-16 BOM and
    decode accordingly, else utf-8-sig (handles UTF-8 with or without BOM).
    """
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


def _sniff_delimiter(text: str) -> str:
    """Pick TAB vs comma by the densest delimiter line in the preamble/header.

    Google Ads TSV has a tab-rich header (~28 columns); hand-saved CSVs use
    commas. Scanning the first lines for the max single-line delimiter count is
    robust to the 1-2 preamble lines ("Campaign report", "All time") that carry
    no delimiters at all.
    """
    best_delim, best_count = ",", 0
    for line in text.splitlines()[:10]:
        for delim in ("\t", ","):
            n = line.count(delim)
            if n > best_count:
                best_delim, best_count = delim, n
    return best_delim


def _csv_rows(text: str) -> list[list[str]]:
    """Parse decoded CSV/TSV text into rows, BOM- and delimiter-aware."""
    if text.startswith("﻿"):
        text = text[1:]  # defensive; utf-16/utf-8-sig decode usually strips this
    return list(csv.reader(io.StringIO(text), delimiter=_sniff_delimiter(text)))


def parse_ga_csv(csv_text: str) -> list[dict]:
    """Parse Google Ads CSV export.

    Header row REQUIRED. Columns matched by case-insensitive substring on header:
      - Campaign (required)
      - Clicks (required)
      - Conversions / Conv. (optional, defaults to 0)
      - Impressions / Impr. (optional; None when the column is absent — only the
        plain count column counts, percentage variants like "Impr. (Top) %" are
        ignored so they can't masquerade as counts)
      - Account (optional, defaults to empty string)
      - Campaign status / Status / Status reasons (optional, EXACT header match
        only — a substring pass would bind "status" to "Campaign status", the
        #1482 collision surface; None when the column is absent, so downstream
        ga_ads_all_stopped stays None and x4b keeps the manual confirm-ads path)
    Column ORDER does not matter — the parser indexes by header position.

    Tolerances:
      - UTF-8 BOM at file start is stripped.
      - Summary footer rows (first cell starts with "Total") are skipped.
      - Thousands separators in numeric cells (1,082) are stripped.
      - Empty / whitespace-only rows are skipped.
      - Rows whose Campaign cell is empty are skipped.

    Returns an empty list when required columns are absent — state-x0a's
    `validate-csv` subcommand fails the gate before this is called, so
    reaching this path implies CSV is valid; the empty-list return is a
    defensive fallback.
    """
    rows = _csv_rows(csv_text)
    if not rows:
        return []
    header_idx = _find_header_row(rows)
    if header_idx is None:
        return []
    header = [(h or "").strip().lower() for h in rows[header_idx]]

    def find(*keys: str) -> int | None:
        exact = {k.lower().strip() for k in keys}
        for i, h in enumerate(header):
            if h in exact:
                return i
        for i, h in enumerate(header):
            for k in exact:
                if k in h:
                    return i
        return None

    def find_exact(*keys: str) -> int | None:
        exact = {k.lower().strip() for k in keys}
        for i, h in enumerate(header):
            if h in exact:
                return i
        return None

    i_name = find("campaign")
    i_clicks = find("clicks")
    if i_name is None or i_clicks is None:
        return []
    i_conv = find("conversions", "conv.")
    i_account = find("account")
    # Optional CPC-discipline columns (added for cpc_over_cap / channel_starved).
    # All optional: Campaign + Clicks remain the only required columns, so old
    # exports keep parsing. When Cost is absent, ga_cpc downstream stays None and
    # the CPC flags simply do not compute (graceful).
    i_cost = find("cost")
    i_currency = find("currency code", "currency")
    i_start = find("start date", "start")
    # Impressions feed the stalled-cause triage (zero_serve vs weak_demand).
    # Substring matching can bind to "Impr. (Top) %" when the plain count
    # column is absent — a rate, not a count — so reject %-headers.
    i_impr = find("impressions", "impr.")
    if i_impr is not None and "%" in header[i_impr]:
        i_impr = None
    # Campaign deliverability columns. EXACT-only: substring matching would
    # bind "status" to the FIRST matching header ("Campaign status") and
    # "status reasons" collides the same way — the #1482 surface.
    i_campaign_status = find_exact("campaign status")
    i_serving_status = find_exact("status")
    i_status_reasons = find_exact("status reasons")

    def _opt_text(idx: int | None, row: list[str]) -> str | None:
        # None ⇔ the column is absent from the export; "" = present-but-empty
        # cell (mirrors the cost None-vs-0.0 convention).
        if idx is None:
            return None
        return (row[idx] or "").strip() if idx < len(row) else ""

    def _num(idx: int | None, row: list[str]) -> float:
        if idx is None or idx >= len(row):
            return 0.0
        try:
            return float((row[idx] or "0").strip().replace(",", "") or 0)
        except ValueError:
            return 0.0

    out: list[dict] = []
    for row in rows[header_idx + 1:]:
        if not row or i_name >= len(row):
            continue
        name = (row[i_name] or "").strip()
        if not name:
            continue
        # Skip Google Ads summary rows. The total marker may appear in the
        # Campaign cell ("Total: ...") OR — in multi-section exports — as a
        # "Total: Campaigns/Account/..." label in the FIRST column (Campaign
        # status) while the Campaign cell shows the "--" placeholder.
        if name == "--" or name.lower().startswith("total"):
            continue  # skip summary footer
        if row and (row[0] or "").strip().lower().startswith("total:"):
            continue  # summary marker in the Campaign status column
        try:
            clicks_raw = (row[i_clicks] or "0").strip().replace(",", "") if i_clicks < len(row) else "0"
            clicks = int(clicks_raw or 0)
        except (ValueError, IndexError):
            continue
        conv = 0.0
        if i_conv is not None and i_conv < len(row):
            try:
                conv = float((row[i_conv] or "0").strip().replace(",", "") or 0)
            except ValueError:
                pass
        account = (row[i_account] or "").strip() if i_account is not None and i_account < len(row) else ""
        # cost is None when the Cost column is ABSENT (so downstream ga_cpc stays
        # None and CPC flags don't compute) vs 0.0 when present-but-empty.
        cost = _num(i_cost, row) if i_cost is not None else None
        currency = (row[i_currency] or "").strip() if i_currency is not None and i_currency < len(row) else ""
        start_date = (row[i_start] or "").strip() if i_start is not None and i_start < len(row) else ""
        # impressions is None when the column is ABSENT (downstream stalled
        # triage reads that as no_telemetry) vs 0 when present-but-zero.
        impressions = int(_num(i_impr, row)) if i_impr is not None else None
        campaign_status = _opt_text(i_campaign_status, row)
        serving_status = _opt_text(i_serving_status, row)
        status_reasons = _opt_text(i_status_reasons, row)
        out.append({
            "name": name, "account": account, "type": "", "clicks": clicks, "conv": conv,
            "cost": cost, "currency": currency, "start_date": start_date,
            "impressions": impressions,
            "campaign_status": campaign_status,
            "serving_status": serving_status,
            "status_reasons": status_reasons,
            "status_normalized": normalize_campaign_status(campaign_status, serving_status),
        })
    return out


def _like_pattern_to_regex(pattern: str) -> re.Pattern:
    """Translate a SQL LIKE pattern into a case-insensitive regex."""
    out = []
    for ch in pattern:
        if ch == "%":
            out.append(".*")
        elif ch == "_":
            out.append(".")
        else:
            out.append(re.escape(ch))
    return re.compile("^" + "".join(out) + "$", flags=re.IGNORECASE)


def campaign_matches_phase_filter(campaign_name: str, phase_filter: str | None) -> bool:
    """Return true when a GA campaign name matches the optional phase filter.

    x0a passes no filter and retains legacy behavior. x5 passes the resolved
    `phase2.utm_campaign_like` value; campaign names mirror `utm_campaign` for
    the manual Phase 2 playbook, so the same LIKE pattern scopes the denominator.
    """
    if not phase_filter:
        return True
    phase_filter = str(phase_filter).strip()
    if not phase_filter:
        return True
    return bool(_like_pattern_to_regex(phase_filter).match(campaign_name or ""))


def filter_campaigns_by_phase(campaigns: list[dict], phase_filter: str | None) -> list[dict]:
    if not phase_filter or not str(phase_filter).strip():
        return campaigns
    return [
        c for c in campaigns
        if campaign_matches_phase_filter(c.get("name", ""), phase_filter)
    ]


def campaign_matches_phase_exclude(campaign_name: str, phase_exclude: str | None) -> bool:
    """Return true when a GA campaign name matches the exclusion pattern.

    EXCLUDE semantics deliberately invert the empty-pattern default of
    campaign_matches_phase_filter: an empty/blank pattern matches NOTHING
    (nothing gets excluded). Reusing the include helper here would make an
    empty pattern exclude every campaign — zeroing the Phase-1 denominator
    fleet-wide.

    x0a passes the resolved `phase2.utm_campaign_like` value so the Phase-1
    denominator excludes exactly the campaigns x5 includes — the two phases
    partition the paid clicks instead of double-counting the phase2 slice.
    """
    if not phase_exclude:
        return False
    phase_exclude = str(phase_exclude).strip()
    if not phase_exclude:
        return False
    return bool(_like_pattern_to_regex(phase_exclude).match(campaign_name or ""))


def _find_header_row(rows: list[list[str]]) -> int | None:
    for idx, row in enumerate(rows):
        header = [(h or "").strip().lower() for h in row]
        has_campaign = "campaign" in header or any(h == "campaign name" for h in header)
        has_clicks = "clicks" in header
        if not has_campaign:
            has_campaign = any(h == "campaign" or h.endswith(" campaign") for h in header)
        if has_campaign and has_clicks:
            return idx
    return None


def merge_ga_clicks(
    campaigns: list[dict],
    mvp_records: list[dict],
    aliases: dict[str, str] | None = None,
    phase_exclude: str | None = None,
    phase_exclude_exempt: list[str] | None = None,
    relaunch_by_mvp: dict[str, str] | None = None,
    owner_by_mvp: dict[str, str] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Fold GA clicks into MVP records.

    Returns (updated_mvps, unmatched).
      - updated_mvps: original list + any new ga_only MVPs, with ga_clicks set on each.
      - unmatched: list of campaign records that could not be bucketed (placeholder
        or below-threshold). Each entry: {name, clicks, account, reason}.

    ga_impressions: blended sum across the bucket's campaigns; None when the CSV
    had no Impressions column (downstream stalled triage reads None as
    no_telemetry, 0 as present-but-zero).

    Deliverability (status columns): every MVP gets `ga_campaign_status_detail`
    (per-campaign switch/serving/reasons + normalized stopped|active|unknown)
    and `ga_ads_all_stopped` (True = every campaign verifiably stopped; None =
    export lacked the status columns; False otherwise). Status is collected
    BEFORE the pre-relaunch drop — a dropped first flight leaves the analysis
    denominator but can still spend money. x4b's csv_paused evidence and the
    money-leak wording consume these fields.

    Phase-2 split (x0a Phase-1 denominator scoping): when `phase_exclude` is a
    non-empty LIKE pattern, campaigns matching it are still summed into the
    blended ga_clicks/ga_cost (back-compat: capture_rate and account-hygiene
    flags keep the full paid picture) but ALSO accumulate into
    ga_clicks_phase2 / ga_cost_phase2 / ga_campaigns_phase2 so state-x3 can
    use (ga_clicks - ga_clicks_phase2) as the Phase-1 conversion denominator.
    Campaign names listed in `phase_exclude_exempt` (exact match) never count
    as phase2 — the operator escape hatch for a Phase-1 campaign whose name
    happens to contain the phase2 token.

    Phase-1 relaunch scoping: `relaunch_by_mvp` maps an MVP name to its
    `phase1_relaunch_at` ISO date. A campaign bucketed to a relaunched MVP is
    DROPPED (not counted in any total) when its Start date sorts before the
    relaunch cut — so the failed first flight's clicks/cost no longer pollute
    the re-test denominator. Dropped campaigns are reported as unmatched with
    reason=`pre-relaunch` for operator visibility. See iterate_cross_relaunch.

    Owner attribution: `owner_by_mvp` maps MVP name → operator-mapped owner
    (from mvp_mappings). ga_only auto-created records inherit it, mirroring
    state-x0's canonical-record rule; absent map keeps owner None.

    Idempotent: re-applying with the same input produces the same output.
    Existing `ga_clicks` values are OVERWRITTEN (not accumulated) so re-runs
    reflect the latest scrape.
    """
    from iterate_cross_relaunch import campaign_passes_relaunch

    aliases = aliases or {}
    exempt = set(phase_exclude_exempt or [])
    relaunch_by_mvp = relaunch_by_mvp or {}
    owner_by_mvp = owner_by_mvp or {}
    # Include MVP keys for substring matching but also build a parallel index
    # of orphan-host match_keys so a GA auto-create whose name collides with an
    # existing orphan (e.g. campaign "Hospitica-search-v2" while PH has
    # `__orphan_hospitica__`) attributes clicks to the orphan record, not a
    # parallel ga_only duplicate.
    real_keys = {
        m.get("name") or ""
        for m in mvp_records
        if isinstance(m, dict) and not (m.get("name") or "").startswith("__orphan_")
    }
    orphan_index: dict[str, str] = {}
    for m in mvp_records:
        if not isinstance(m, dict):
            continue
        name = m.get("name") or ""
        if name.startswith("__orphan_") and name.endswith("__"):
            host = name[len("__orphan_"):-len("__")]
            orphan_index[match_key(host)] = name

    bucket_totals: dict[str, dict] = {}
    status_by_bucket: dict[str, list[dict]] = {}
    unmatched: list[dict] = []

    for c in campaigns:
        bucket, reason = bucket_campaign(c["name"], real_keys, aliases)
        if bucket is None:
            unmatched.append({**c, "reason": reason})
            continue
        # ga-only-auto: check if it collides with an orphan record before creating
        # a separate ga_only MVP. Orphan record means "PH did see traffic for this
        # deploy but it had NULL project_name" — strictly more PH presence than
        # ga_only (which is "PH saw nothing"), so the orphan record absorbs the
        # ga_clicks signal.
        if reason == "ga-only-auto":
            if c["clicks"] == 0:
                continue  # skip noise
            cand_key = match_key(bucket)
            if cand_key in orphan_index:
                bucket = orphan_index[cand_key]
                reason = "orphan-via-ga"
        # Deliverability status is collected BEFORE the pre-relaunch drop just
        # below: a dropped first flight leaves the analysis denominator but can
        # still be spending money — x4b's ads evidence must keep seeing it.
        # Fields are read via .get() and normalized fresh here (callers may
        # pass synthetic campaign dicts without the status keys).
        status_by_bucket.setdefault(bucket, []).append({
            "name": c.get("name"),
            "campaign_status": c.get("campaign_status"),
            "serving_status": c.get("serving_status"),
            "status_reasons": c.get("status_reasons"),
            "normalized": normalize_campaign_status(
                c.get("campaign_status"), c.get("serving_status")
            ),
        })
        # Phase-1 relaunch: drop campaigns that predate the MVP's relaunch cut so
        # the failed first flight does not re-pollute the re-test denominator.
        rel = relaunch_by_mvp.get(bucket)
        if rel and not campaign_passes_relaunch(c.get("start_date"), rel):
            unmatched.append({**c, "reason": "pre-relaunch"})
            continue
        if bucket not in bucket_totals:
            bucket_totals[bucket] = {
                "clicks": 0,
                "conv": 0.0,
                "cost": 0.0,
                "cost_present": False,
                "impressions": 0,
                "impressions_present": False,
                "clicks_phase2": 0,
                "cost_phase2": 0.0,
                "cost_phase2_present": False,
                "campaigns_phase2": [],
                "currency": None,
                "start_date_min": None,
                "campaigns": [],
                "reason": reason,
            }
        bucket_totals[bucket]["clicks"] += c["clicks"]
        bucket_totals[bucket]["conv"] += c["conv"]
        if c.get("cost") is not None:
            bucket_totals[bucket]["cost"] += c["cost"]
            bucket_totals[bucket]["cost_present"] = True
        if c.get("impressions") is not None:
            bucket_totals[bucket]["impressions"] += c["impressions"]
            bucket_totals[bucket]["impressions_present"] = True
        # Phase-2 split: matched campaigns count in BOTH the blended totals above
        # and the phase2 slice below (state-x3 subtracts, never this function).
        if (
            c["name"] not in exempt
            and campaign_matches_phase_exclude(c["name"], phase_exclude)
        ):
            bucket_totals[bucket]["clicks_phase2"] += c["clicks"]
            if c.get("cost") is not None:
                bucket_totals[bucket]["cost_phase2"] += c["cost"]
                bucket_totals[bucket]["cost_phase2_present"] = True
            bucket_totals[bucket]["campaigns_phase2"].append(c["name"])
        # First non-empty currency wins (campaigns in one MVP share an account).
        if not bucket_totals[bucket]["currency"] and c.get("currency"):
            bucket_totals[bucket]["currency"] = c.get("currency")
        # Earliest campaign start across the bucket (GA exports "Start date" as
        # ISO YYYY-MM-DD, so lexical min == chronological min).
        cstart = (c.get("start_date") or "").strip()
        if cstart:
            cur = bucket_totals[bucket]["start_date_min"]
            bucket_totals[bucket]["start_date_min"] = cstart if cur is None else min(cur, cstart)
        bucket_totals[bucket]["campaigns"].append(c["name"])

    def _cpc(cost: float, clicks: int) -> float | None:
        return round(cost / clicks, 4) if clicks else None

    # Apply totals to existing MVP records (in place).
    by_name = {m.get("name"): m for m in mvp_records if isinstance(m, dict)}
    for m in mvp_records:
        m["ga_clicks"] = 0
        m["ga_conv"] = 0.0
        m["ga_cost"] = 0.0
        m["ga_cpc"] = None
        m["ga_impressions"] = None
        m["ga_currency"] = None
        m["campaign_first_date"] = None
        m["ga_campaigns"] = []
        m["ga_clicks_phase2"] = 0
        m["ga_cost_phase2"] = None
        m["ga_campaigns_phase2"] = []
        m["ga_campaign_status_detail"] = []
        m["ga_ads_all_stopped"] = None

    new_records: list[dict] = []
    # Iterate the union: a bucket whose EVERY campaign was dropped pre-relaunch
    # exists only in status_by_bucket (no click totals) — its deliverability
    # detail must still land on the record. Order preserves bucket_totals
    # insertion, then status-only buckets.
    ordered_buckets = list(bucket_totals)
    ordered_buckets += [b for b in status_by_bucket if b not in bucket_totals]
    for bucket in ordered_buckets:
        detail = sorted(
            status_by_bucket.get(bucket, []), key=lambda d: d.get("name") or ""
        )
        all_stopped = _derive_all_stopped(detail)
        totals = bucket_totals.get(bucket)
        if totals is None:
            target = by_name.get(bucket)
            if target is not None:
                target["ga_campaign_status_detail"] = detail
                target["ga_ads_all_stopped"] = all_stopped
            continue
        if bucket in by_name:
            target = by_name[bucket]
            cost_present = totals["cost_present"]
            target["ga_clicks"] = totals["clicks"]
            target["ga_conv"] = totals["conv"]
            target["ga_cost"] = round(totals["cost"], 4) if cost_present else None
            target["ga_cpc"] = _cpc(totals["cost"], totals["clicks"]) if cost_present else None
            target["ga_impressions"] = (
                int(totals["impressions"]) if totals["impressions_present"] else None
            )
            target["ga_currency"] = totals["currency"]
            target["campaign_first_date"] = totals["start_date_min"]
            target["ga_campaigns"] = sorted(totals["campaigns"])
            target["ga_clicks_phase2"] = totals["clicks_phase2"]
            target["ga_cost_phase2"] = (
                round(totals["cost_phase2"], 4) if totals["cost_phase2_present"] else None
            )
            target["ga_campaigns_phase2"] = sorted(totals["campaigns_phase2"])
            target["ga_campaign_status_detail"] = detail
            target["ga_ads_all_stopped"] = all_stopped
        else:
            # ga_only MVP — create a synthetic record using the same shape state-x0 produces.
            new_records.append({
                "name": bucket,
                "gclid_visitors": 0,
                "first_seen": None,
                "last_seen": None,
                "sample_utm_campaign": None,
                "owner": owner_by_mvp.get(bucket),
                "deploy_domain": None,
                "phase_match": None,
                "orphan": False,
                "partial_tracking_pct": None,
                "ga_clicks": totals["clicks"],
                "ga_conv": totals["conv"],
                "ga_cost": round(totals["cost"], 4) if totals["cost_present"] else None,
                "ga_cpc": _cpc(totals["cost"], totals["clicks"]) if totals["cost_present"] else None,
                "ga_impressions": (
                    int(totals["impressions"]) if totals["impressions_present"] else None
                ),
                "ga_currency": totals["currency"],
                "campaign_first_date": totals["start_date_min"],
                "ga_campaigns": sorted(totals["campaigns"]),
                "ga_clicks_phase2": totals["clicks_phase2"],
                "ga_cost_phase2": (
                    round(totals["cost_phase2"], 4) if totals["cost_phase2_present"] else None
                ),
                "ga_campaigns_phase2": sorted(totals["campaigns_phase2"]),
                "ga_campaign_status_detail": detail,
                "ga_ads_all_stopped": all_stopped,
                "ga_only": True,
            })

    return mvp_records + new_records, unmatched


def compute_foreign_campaign_flags(
    campaign_rows: list[list],
    mvps: list[dict],
    aliases: dict[str, str] | None = None,
    whitelist: list[str] | None = None,
) -> tuple[dict[str, list[dict]], list[dict]]:
    """Detect MVP X receiving paid traffic tagged with MVP Y's campaign.

    That shape means campaign Y's ad Final URL or a sitelink asset points at
    X's site: Y's budget buys clicks that can never convert for Y and are
    invisible to every per-MVP check (an /ads-ready probe only visits its own
    domain). Inputs:
      - campaign_rows: [receiving_mvp_name, utm_campaign, visitors] from a
        phase-scoped GROUP BY (project_name, utm_campaign) events query
      - mvps: the run's MVP records (names + orphan flags)
      - aliases: match_key-normalized ga_campaign_aliases (see _load_aliases)
      - whitelist: `cross_campaign_whitelist` config — match_key-compared
        against the utm_campaign, the paying name, and the receiving name

    Returns (flags_by_mvp_name, audit_rows). Flags are two-sided: the PAYING
    MVP gets severity=high (its money leaks), the receiving MVP severity=info.
    Rows whose campaign resolves to an unknown owner, to an orphan receiver,
    or to a whitelisted pair land in audit_rows only — never as flags and
    never as new MVP records (the DB-triage set must stay equal to the ctx
    set). Diagnostic only: flags never change headline verdicts.
    """
    aliases = aliases or {}
    wl_keys = {match_key(str(w)) for w in (whitelist or []) if str(w).strip()}
    real_names = [
        str(m.get("name"))
        for m in mvps
        if m.get("name") and not m.get("orphan") and not str(m.get("name")).startswith("__")
    ]
    real_by_key = {match_key(n): n for n in real_names}

    audit: list[dict] = []
    pair_totals: dict[tuple[str, str], dict] = {}

    for row in campaign_rows:
        if not row or len(row) < 2:
            continue
        receiver = str(row[0] or "")
        utm = str(row[1] or "")
        visitors = int(row[2] or 0) if len(row) > 2 else 0
        if not receiver or not utm:
            continue
        if receiver.startswith("__") or receiver not in real_by_key.values():
            audit.append({"receiver": receiver, "utm_campaign": utm, "visitors": visitors,
                          "action": "skipped-orphan-or-unknown-receiver"})
            continue

        resolved, reason = bucket_campaign(utm, set(real_names), aliases)
        if resolved is None:
            audit.append({"receiver": receiver, "utm_campaign": utm, "visitors": visitors,
                          "action": f"skipped-{reason}"})
            continue
        payer = real_by_key.get(match_key(resolved))
        if payer is None:
            audit.append({"receiver": receiver, "utm_campaign": utm, "visitors": visitors,
                          "resolved": resolved, "action": "skipped-unknown-owner"})
            continue
        if match_key(payer) == match_key(receiver):
            continue
        if wl_keys & {match_key(utm), match_key(payer), match_key(receiver)}:
            audit.append({"receiver": receiver, "utm_campaign": utm, "visitors": visitors,
                          "payer": payer, "action": "whitelisted"})
            continue

        totals = pair_totals.setdefault(
            (payer, receiver),
            {"visitors": 0, "campaigns": set()},
        )
        totals["visitors"] += visitors
        totals["campaigns"].add(utm)

    flags_by_name: dict[str, list[dict]] = {}
    for (payer, receiver), totals in sorted(pair_totals.items()):
        campaigns = ", ".join(sorted(totals["campaigns"]))
        visitors = totals["visitors"]
        flags_by_name.setdefault(payer, []).append({
            "flag": "foreign_campaign_traffic",
            "severity": "high",
            "message": (
                f"Campaign(s) '{campaigns}' (owned by {payer}) sent {visitors} phase-scoped paid "
                f"visitor(s) to {receiver}'s site — {payer}'s budget buying traffic that can never "
                f"convert. Check the campaign's ad Final URLs and sitelink assets in Google Ads."
            ),
        })
        flags_by_name.setdefault(receiver, []).append({
            "flag": "foreign_campaign_traffic",
            "severity": "info",
            "message": (
                f"Received {visitors} paid visitor(s) tagged with {payer}'s campaign(s) "
                f"'{campaigns}' (ad Final URL/sitelink misconfig on {payer}'s side). These visitors "
                f"are in {payer}'s GA click denominator, not {receiver}'s."
            ),
        })
        audit.append({"payer": payer, "receiver": receiver, "visitors": visitors,
                      "campaigns": sorted(totals["campaigns"]), "action": "flagged"})

    return flags_by_name, audit


# ---------- CLI ----------

def _load_csv(args: argparse.Namespace) -> list[dict]:
    """Resolve the campaigns list from --ga-csv. Returns [] if missing or unreadable."""
    if args.ga_csv and os.path.exists(args.ga_csv):
        campaigns = parse_ga_csv(_read_csv_text(args.ga_csv))
        return filter_campaigns_by_phase(campaigns, getattr(args, "phase_filter", None))
    return []


def _load_aliases(config_path: str | None) -> dict[str, str]:
    """Read `ga_campaign_aliases` from iterate-cross-config.yaml."""
    if not config_path or not os.path.exists(config_path):
        return {}
    try:
        import yaml
    except ImportError:
        return {}
    cfg = yaml.safe_load(open(config_path)) or {}
    aliases = cfg.get("ga_campaign_aliases") or {}
    # Normalize keys via match_key so operator can write them in any case/punct form.
    return {match_key(k): v for k, v in aliases.items() if v}


def _load_relaunch_map(config_path: str | None) -> dict[str, str]:
    """Read per-MVP `phase1_relaunch_at` dates from iterate-cross-config.yaml.

    Returns {mvp_name: 'YYYY-MM-DD'} for every mapping that sets a valid
    relaunch date. Malformed values raise (via parse_relaunch_at) so a typo
    surfaces at merge time rather than silently disabling the relaunch window.
    """
    if not config_path or not os.path.exists(config_path):
        return {}
    try:
        import yaml
    except ImportError:
        return {}
    from iterate_cross_relaunch import parse_relaunch_at

    cfg = yaml.safe_load(open(config_path)) or {}
    out: dict[str, str] = {}
    for name, mapping in (cfg.get("mvp_mappings") or {}).items():
        if not isinstance(mapping, dict):
            continue
        rel = parse_relaunch_at(mapping.get("phase1_relaunch_at"))
        if rel:
            out[name] = rel
    return out


def _load_owner_map(config_path: str | None) -> dict[str, str]:
    """Read per-MVP `owner` from iterate-cross-config.yaml mvp_mappings.

    Returns {mvp_name: owner} for every mapping that sets a truthy owner, so
    ga_only auto-created records inherit the operator's owner attribution the
    same way state-x0 canonical records do (a ga_only record with a mapped
    owner must not render as @unassigned in the team message).
    """
    if not config_path or not os.path.exists(config_path):
        return {}
    try:
        import yaml
    except ImportError:
        return {}
    cfg = yaml.safe_load(open(config_path)) or {}
    out: dict[str, str] = {}
    for name, mapping in (cfg.get("mvp_mappings") or {}).items():
        if not isinstance(mapping, dict):
            continue
        owner = mapping.get("owner")
        if owner:
            out[name] = str(owner)
    return out


def _load_phase_exclude_exempt(config_path: str | None) -> list[str]:
    """Read `phase2.exclude_exempt_campaigns` from iterate-cross-config.yaml.

    Operator escape hatch for Phase-1 campaigns whose names contain the phase2
    token (exact campaign-name match, defensive read, default empty).
    """
    if not config_path or not os.path.exists(config_path):
        return []
    try:
        import yaml
    except ImportError:
        return []
    cfg = yaml.safe_load(open(config_path)) or {}
    phase2 = cfg.get("phase2") or {}
    exempt = phase2.get("exclude_exempt_campaigns") or []
    if not isinstance(exempt, list):
        return []
    return [str(e) for e in exempt if e]


def cmd_validate_csv(args: argparse.Namespace) -> int:
    """Verify the CSV has required header columns. Exit non-zero on failure.

    Called by state-x0a Step 0 BEFORE merge to fail-fast with a clear diagnostic
    when the operator's export is missing columns. Soft-warns (still exits 0)
    on header-only CSV — that case can legitimately happen if the date window
    captured zero paid clicks.
    """
    if not args.ga_csv or not os.path.exists(args.ga_csv):
        print(f"ERROR: CSV not found at {args.ga_csv}", file=sys.stderr)
        return 2
    text = _read_csv_text(args.ga_csv)
    if not text.strip():
        print(f"ERROR: CSV is empty: {args.ga_csv}", file=sys.stderr)
        return 2
    rows = _csv_rows(text)
    if not rows:
        print(f"ERROR: CSV has no rows: {args.ga_csv}", file=sys.stderr)
        return 2
    header_idx = _find_header_row(rows)
    if header_idx is None:
        print(
            f"ERROR: CSV missing required columns: ['campaign', 'clicks']. "
            f"Could not find a header row in {args.ga_csv}.",
            file=sys.stderr,
        )
        return 2
    header = [(h or "").strip().lower() for h in rows[header_idx]]
    required = {"campaign": False, "clicks": False}
    for col in header:
        for key in required:
            if key in col:
                required[key] = True
    missing = [k for k, v in required.items() if not v]
    if missing:
        print(
            f"ERROR: CSV missing required columns: {missing}. "
            f"Header was: {rows[header_idx]}. "
            f"Re-export from Google Ads UI with at least Campaign and Clicks columns.",
            file=sys.stderr,
        )
        return 2
    parsed_all = parse_ga_csv(text)
    parsed = filter_campaigns_by_phase(parsed_all, getattr(args, "phase_filter", None))
    if not parsed:
        if parsed_all and getattr(args, "phase_filter", None):
            print(
                f"WARN: CSV has {len(parsed_all)} data row(s), but none match "
                f"phase filter {args.phase_filter!r}. Proceeding with phase-scoped "
                f"ga_clicks=0.",
                file=sys.stderr,
            )
            return 0
        if getattr(args, "context", None) and os.path.exists(args.context):
            ctx = json.load(open(args.context))
            has_paid_traffic = any((m.get("gclid_visitors", 0) or 0) > 0 for m in ctx.get("mvps", []))
            if has_paid_traffic:
                print(
                    "ERROR: CSV has no data rows but context already has gclid traffic. "
                    "Re-export the active Google Ads campaign report.",
                    file=sys.stderr,
                )
                return 2
        # Header-only: legitimate when the window has zero paid clicks. Warn only.
        print(
            f"WARN: CSV has header but zero data rows. If your date range had "
            f"zero paid clicks that is correct; otherwise re-export. Skill will "
            f"proceed with ga_clicks=0 on every MVP.",
            file=sys.stderr,
        )
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    phase_filter = getattr(args, "phase_filter", None)
    phase_exclude = getattr(args, "phase_exclude", None)
    if phase_filter and str(phase_filter).strip() and phase_exclude and str(phase_exclude).strip():
        # x5 include-scopes with --phase-filter; x0a exclude-splits with
        # --phase-exclude. Combining them silently empties or double-scopes the
        # denominator, so refuse outright.
        print(
            "ERROR: --phase-filter and --phase-exclude are mutually exclusive "
            "(include-scoping is the x5 path, exclude-splitting is the x0a path).",
            file=sys.stderr,
        )
        return 2
    all_campaigns = []
    if args.ga_csv and os.path.exists(args.ga_csv):
        all_campaigns = parse_ga_csv(_read_csv_text(args.ga_csv))
    campaigns = filter_campaigns_by_phase(all_campaigns, phase_filter)
    if not campaigns:
        # Reached only when the operator's CSV is header-only or has no rows the
        # parser could decode. state-x0a's validate-csv subcommand should have
        # warned upstream; this is the merge-side noop path. Every existing MVP
        # gets ga_clicks=0 set so the POSTCONDITION still holds.
        if all_campaigns and phase_filter:
            print(
                f"merge: CSV has zero campaigns matching phase filter {phase_filter!r}; "
                "setting ga_clicks=0 on every MVP.",
                file=sys.stderr,
            )
        else:
            print("merge: CSV has zero parseable rows; setting ga_clicks=0 on every MVP.", file=sys.stderr)
    elif phase_filter:
        print(
            f"merge: phase filter {phase_filter!r} retained "
            f"{len(campaigns)} of {len(all_campaigns)} campaign rows.",
            file=sys.stderr,
        )

    aliases = _load_aliases(args.config)
    exempt = _load_phase_exclude_exempt(args.config) if phase_exclude else []
    relaunch_by_mvp = _load_relaunch_map(args.config)
    owner_by_mvp = _load_owner_map(args.config)
    if relaunch_by_mvp and phase_filter and str(phase_filter).strip():
        # x5 include-scopes the denominator by the phase2 utm token; the
        # Phase-1 relaunch time-cut is a different axis and must not apply.
        # The x5 CSV export only requires Campaign+Clicks columns, so an
        # active relaunch date would conservatively drop Start-date-less
        # phase2 campaigns (reason=pre-relaunch) and zero the denominator.
        # Loaded-then-blanked so malformed phase1_relaunch_at values still
        # raise (the _load_relaunch_map typo-surfacing contract).
        print(
            f"merge: --phase-filter active; ignoring phase1_relaunch_at for "
            f"{sorted(relaunch_by_mvp)} (the Phase-1 relaunch cut never "
            f"scopes the phase2 denominator).",
            file=sys.stderr,
        )
        relaunch_by_mvp = {}

    # Load target context (state-x0 output)
    if not os.path.exists(args.context):
        print(f"ERROR: --context path does not exist: {args.context}", file=sys.stderr)
        return 2
    ctx = json.load(open(args.context))
    mvps = ctx.get("mvps") or []

    merged, unmatched = merge_ga_clicks(
        campaigns,
        mvps,
        aliases,
        phase_exclude=phase_exclude,
        phase_exclude_exempt=exempt,
        relaunch_by_mvp=relaunch_by_mvp,
        owner_by_mvp=owner_by_mvp,
    )
    dropped = [u for u in unmatched if u.get("reason") == "pre-relaunch"]
    for u in dropped:
        print(
            f"relaunch: dropped pre-relaunch campaign {u.get('name')!r} "
            f"(start {u.get('start_date') or '—'}, {u.get('clicks')} clicks) "
            f"from a relaunched MVP's denominator.",
            file=sys.stderr,
        )
    # Deliverability summary. unmatched_active counts unattributable campaigns
    # (placeholder/unmatched — NOT pre-relaunch, which are attributed above)
    # that are not verifiably stopped; x4b's csv_paused gate requires it be 0.
    status_counts = {"active": 0, "stopped": 0, "unknown": 0}
    for c in campaigns:
        status_counts[
            normalize_campaign_status(c.get("campaign_status"), c.get("serving_status"))
        ] += 1
    unmatched_active = sum(
        1 for u in unmatched
        if u.get("reason") != "pre-relaunch" and u.get("status_normalized") != "stopped"
    )
    print(
        f"ads-status: {status_counts['active']} active / "
        f"{status_counts['stopped']} stopped / {status_counts['unknown']} unknown; "
        f"unmatched_active={unmatched_active}",
        file=sys.stderr,
    )
    ctx["mvps"] = merged
    # Record the CSV file's mtime as the data freshness stamp.
    ctx["ga_scraped_at"] = (
        __import__("datetime").datetime.fromtimestamp(
            os.path.getmtime(args.ga_csv),
            tz=__import__("datetime").timezone.utc,
        ).isoformat()
        if args.ga_csv and os.path.exists(args.ga_csv)
        else None
    )
    # Stamp the applied exclusion pattern so state-x0a's VERIFY can assert the
    # Phase-1 run actually excluded phase2 campaigns (guards against the merge
    # invocation silently dropping --phase-exclude in a future edit).
    ctx["ga_phase_exclude_applied"] = (phase_exclude or "").strip()

    json.dump(ctx, open(args.context, "w"), indent=2)

    # Operator-facing exclusion summary (one line per MVP with a phase2 slice).
    for m in merged:
        if m.get("ga_clicks_phase2"):
            print(
                f"phase-exclude: {m.get('name')} excluded {m['ga_clicks_phase2']} clicks "
                f"from {m.get('ga_campaigns_phase2')} (Phase-1 denominator = "
                f"{(m.get('ga_clicks', 0) or 0) - m['ga_clicks_phase2']})",
                file=sys.stderr,
            )

    if args.unmatched_out:
        json.dump(unmatched, open(args.unmatched_out, "w"), indent=2)

    # Warn on stderr for the operator's attention.
    for u in unmatched:
        print(f"WARN: unmatched GA campaign '{u['name']}' ({u['clicks']} clicks, reason={u['reason']})", file=sys.stderr)

    ga_only_count = sum(1 for m in merged if m.get("ga_only"))
    augmented_count = sum(
        1 for m in merged if not m.get("ga_only") and m.get("ga_clicks", 0) > 0
    )
    print(
        f"merge: {len(campaigns)} campaigns → "
        f"{augmented_count} PH MVPs augmented, "
        f"{ga_only_count} ga_only MVPs added, "
        f"{len(unmatched)} unmatched."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bucket and merge Google Ads click data into /iterate --cross context.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_validate = sub.add_parser("validate-csv", help="Verify the GA CSV has required columns and at least one data row.")
    p_validate.add_argument("--ga-csv", default=".runs/iterate-cross-ga-clicks.csv", help="Input: operator-supplied CSV export from Google Ads.")
    p_validate.add_argument("--context", default=None, help="Optional iterate-cross context for header-only validation.")
    p_validate.add_argument("--phase-filter", default=None, help="Optional SQL LIKE pattern for phase-scoped campaign rows.")
    p_validate.set_defaults(func=cmd_validate_csv)

    p_merge = sub.add_parser("merge", help="Fold GA clicks into iterate-cross-context.json.")
    p_merge.add_argument("--ga-csv", default=".runs/iterate-cross-ga-clicks.csv", help="Input: operator-supplied CSV export from Google Ads.")
    p_merge.add_argument("--context", default=".runs/iterate-cross-context.json", help="Target: state-x0 output to mutate.")
    p_merge.add_argument("--config", default="experiment/iterate-cross-config.yaml")
    p_merge.add_argument("--unmatched-out", default=".runs/_iterate-cross-ga-unmatched.json", help="Output: unmatched campaigns for operator triage.")
    p_merge.add_argument("--phase-filter", default=None, help="Optional SQL LIKE pattern for phase-scoped campaign rows.")
    p_merge.add_argument(
        "--phase-exclude",
        default=None,
        help=(
            "Optional SQL LIKE pattern; matching campaigns still count in the blended "
            "ga_clicks but also accumulate into ga_clicks_phase2 so x3 can scope the "
            "Phase-1 denominator. Mutually exclusive with --phase-filter. Empty pattern "
            "excludes nothing."
        ),
    )
    p_merge.set_defaults(func=cmd_merge)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
