#!/usr/bin/env python3
"""Propagate iterate-cross context into data.json for state x1."""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from iterate_cross_relaunch import parse_relaunch_at  # noqa: E402


DB_FIELDS = [
    "db_signups", "db_signups_raw", "db_signups_real", "db_signups_team",
    "db_signups_test", "db_signups_paid", "db_attribution",
    "db_signups_filter_audit", "db_signups_real_windowed", "db_signups_table",
    "db_union_tables",
    "db_first_signup_at", "db_unmapped_reason", "db_source",
    "db_backend",
    "lifecycle_status", "lifecycle_status_at",
    "supabase_project_ref", "railway_project_id", "railway_project_name",
    "railway_service_name",
]


def build_records(
    ctx: dict,
    catalog_rows: list[list] | None = None,
    batch_status: dict | None = None,
    mvp_mappings: dict | None = None,
) -> dict:
    if batch_status is None:
        raise RuntimeError("_x1_catalog_batches_status missing from catalog raw JSON — run_union_batches() must produce it")
    mvp_mappings = mvp_mappings or {}

    catalog_by_mvp: dict[str, list[dict]] = {}
    for row in catalog_rows or []:
        if len(row) < 6:
            continue
        mvp_key, event_name, stage, event_count, unique_users, gclid_users = row[:6]
        catalog_by_mvp.setdefault(mvp_key, []).append({
            "event": event_name,
            "event_count": event_count,
            "unique_users": unique_users,
            "gclid_users": gclid_users,
            "sample_stage": stage if stage else None,
        })

    records = []
    for m in ctx.get("mvps", []):
        name = m.get("name")
        catalog = sorted(catalog_by_mvp.get(name, []), key=lambda e: -(e.get("gclid_users") or 0))
        rec = {
            "name": name,
            "owner": m.get("owner"),
            "gclid_visitors": m.get("gclid_visitors", 0),
            "total_events_count": sum(e.get("event_count", 0) or 0 for e in catalog),
            "first_seen": m.get("first_seen"),
            "last_seen": m.get("last_seen"),
            "sample_utm_campaign": m.get("sample_utm_campaign"),
            "event_catalog": catalog[:30],
            "orphan": bool(m.get("orphan")),
            "ga_clicks": m.get("ga_clicks", 0),
            "ga_only": bool(m.get("ga_only")),
            "ga_campaigns": m.get("ga_campaigns") or [],
            # Campaign deliverability (state-x0a status-column ingest). Hand-listed
            # like every ga_* field. ga_ads_all_stopped None ⇔ the operator's CSV
            # omitted the status columns — x4b then keeps the manual confirm-ads
            # path instead of csv_paused auto-evidence.
            "ga_campaign_status_detail": m.get("ga_campaign_status_detail") or [],
            "ga_ads_all_stopped": m.get("ga_ads_all_stopped"),
            # Phase-2 split (state-x0a --phase-exclude). Hand-listed like every
            # ga_* field — dropping these from this whitelist silently re-blends
            # the Phase-1 denominator (x3 defaults the missing key to 0), so the
            # x1 VERIFY asserts ga_clicks_phase2 presence on every record.
            "ga_clicks_phase2": m.get("ga_clicks_phase2", 0),
            "ga_cost_phase2": m.get("ga_cost_phase2"),
            "ga_campaigns_phase2": m.get("ga_campaigns_phase2") or [],
            "partial_tracking_pct": m.get("partial_tracking_pct"),
            # GA cost-discipline fields (state-x0a merge). Hand-listed here with the
            # other ga_* fields, NOT in DB_FIELDS. ga_cpc/ga_cost are None/0 when the
            # operator's CSV omitted the Cost column (CPC flags then don't compute).
            "ga_cost": m.get("ga_cost", 0.0),
            "ga_cpc": m.get("ga_cpc"),
            # Stalled-cause diagnosis (state-x3 annotate_stalled). None = the
            # operator's CSV omitted the Impr. column (renders "no telemetry").
            "ga_impressions": m.get("ga_impressions"),
            "ga_currency": m.get("ga_currency"),
            "campaign_first_date": m.get("campaign_first_date"),
            # CPC unit-economics pricing (state-x0c). monthly_price_usd is the gate
            # denominator (also overlaid from config below — config is authoritative);
            # price_source / price_unmapped_reason are provenance for x4 rendering.
            "monthly_price_usd": m.get("monthly_price_usd"),
            "price_source": m.get("price_source"),
            "price_unmapped_reason": m.get("price_unmapped_reason"),
        }
        for field in DB_FIELDS:
            if field in m:
                rec[field] = m.get(field)
        # Operator overrides (cpc_exception / channel_waiver) live in config
        # mvp_mappings, NOT on the context record. Overlay them here — the single
        # point that always runs in x1 — so they survive even when the DB stage
        # (x0b) is skipped (no Supabase/Railway auth). compute_cpc_flags reads
        # these off the record to suppress cpc_over_cap / channel_starved.
        mapping = mvp_mappings.get(name) or {}
        for ov in ("cpc_exception", "channel_waiver", "backend_keep"):
            if mapping.get(ov):
                rec[ov] = mapping.get(ov)
        # db_backend is the sticky backend-knowledge record. The x0b merge
        # stamps it on the context record too, but config is authoritative
        # (it survives x0b skip paths — no-token branch, embed skips).
        if mapping.get("db_backend"):
            rec["db_backend"] = mapping.get("db_backend")
        # monthly_price_usd feeds the CPC unit-economics gate (compute_cpc_flags).
        # Copy when explicitly set (a numeric price; 0 is meaningless but harmless).
        if mapping.get("monthly_price_usd") is not None:
            rec["monthly_price_usd"] = mapping.get("monthly_price_usd")
        # Per-MVP Phase-1 relaunch date (state-x0a GA merge + x0b DB + x2 signup
        # scope the window to max(window, relaunch); carried here so x4 renders a
        # "relaunch <date>" marker and notes gclid_visitors still spans the old flight).
        _relaunch = parse_relaunch_at(mapping.get("phase1_relaunch_at"))
        if _relaunch:
            rec["phase1_relaunch_at"] = _relaunch
        # Owner backstop: records created outside state-x0 (ga_only auto-creates,
        # future creation paths) may lack the operator-mapped owner. Config is
        # authoritative for attribution; a record's existing owner is never
        # overwritten (x0 already read it from the same mapping).
        if not rec.get("owner") and mapping.get("owner"):
            rec["owner"] = mapping.get("owner")
        rec.setdefault("db_signups", None)
        rec.setdefault("db_signups_raw", rec.get("db_signups"))
        rec.setdefault("db_signups_real", rec.get("db_signups"))
        rec.setdefault("db_signups_paid", None)
        rec.setdefault("db_attribution", "window" if rec.get("db_signups_real") is not None else None)
        rec.setdefault("db_signups_team", 0)
        rec.setdefault("db_signups_test", 0)
        rec.setdefault("db_signups_filter_audit", [])
        rec.setdefault("db_signups_real_windowed", None)
        rec.setdefault("db_union_tables", [])
        rec.setdefault("lifecycle_status", "active")
        records.append(rec)

    return {
        "mvps": records,
        "_x1_catalog_batches_status": batch_status,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--context", default=".runs/iterate-cross-context.json")
    p.add_argument("--config", default="experiment/iterate-cross-config.yaml")
    p.add_argument("--run-dir", default=".runs")
    p.add_argument("--catalog-raw", default=None)
    p.add_argument("--output", default=".runs/iterate-cross-data.json")
    p.add_argument("--dry-run", action="store_true", help="Compute and print summary without writing output.")
    args = p.parse_args(argv)

    ctx = json.load(open(args.context))
    mvp_mappings = {}
    if args.config and os.path.exists(args.config):
        try:
            import yaml
            cfg = yaml.safe_load(open(args.config)) or {}
            mvp_mappings = cfg.get("mvp_mappings") or {}
        except Exception:
            mvp_mappings = {}
    raw_path = args.catalog_raw or os.path.join(args.run_dir, "_iterate-cross-catalog-raw.json")
    rows = []
    if os.path.exists(raw_path):
        raw = json.load(open(raw_path))
        rows = raw.get("results") or []
        batch_status = raw.get("_x1_catalog_batches_status")
    else:
        batch_status = None
    payload = build_records(ctx, rows, batch_status, mvp_mappings=mvp_mappings)
    if args.dry_run:
        print(f"DRY-RUN: would write {args.output} ({len(payload['mvps'])} MVPs)")
        return 0
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    json.dump(payload, open(args.output, "w"), indent=2)
    print(f"Wrote {args.output} ({len(payload['mvps'])} MVPs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
