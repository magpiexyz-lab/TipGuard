#!/usr/bin/env python3
"""Teardown-obligation reconciliation for /iterate --cross state-x4b.

NO-GO/killed MVPs routinely never get torn down — cloud resources keep
costing money and holding PII. This module drives the weekly reconcile:
for every killed MVP in config, gather three independent evidence lines
(DB / hosting / ads), apply the single close-out rule, stamp the durable
decision ledger (without unfreezing archived rows), and render the
report + per-owner team-message items. Never deletes anything itself.

Evidence lines
--------------
  db      — from the sticky mvp_mappings.<name>.db_backend record written by
            state-x0b / verify-backends (iterate_cross_db). NEVER the
            synthesized db_unmapped_reason (circular). alive → LIVE;
            deleted_verified / never_existed → GONE; never_located → N/A
            (nothing to tear down); not_visible → UNVERIFIABLE; absent →
            UNKNOWN (run verify-backends).
  hosting — zero-credential HTTP probe of https://<name>.draftlabs.org.
            Edge-layer WEAK evidence by design (custom domains and suffixed
            deploys probe wrong); 5xx counts as live (something is deployed).
  ads     — operator keyed confirmation (confirm-ads subcommand, persisted in
            the ledger) OR csv_paused (every campaign verifiably stopped per
            the GA CSV status columns, and no unattributable unmatched campaign
            is still live) OR auto-satisfied when the current cross run shows
            no GA campaigns for the MVP (the CSV covers the full window) and
            no dropped campaign is still deliverable.

Close-out rule (the ONLY place it exists):
  waived    ⇔ active backend_keep waiver in config
  verified  ⇔ db ∈ {gone, n/a} AND hosting = surface_gone AND
              ads ∈ {confirmed_paused, csv_paused, none_in_window}
  due       ⇔ anything else (reminders escalate; never auto-closes)

STILL_SERVING: independently of close-out state (INCLUDING waived — the
backend_keep waiver waives the backend, not the ads), any killed MVP with a
campaign whose CSV status normalizes to 'active' is surfaced with per-campaign
pause instructions. This is the only line that catches a re-enabled campaign
after a sticky confirmed_paused.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import yaml
except ImportError:
    yaml = None

_UA = "mvp-template-iterate-cross-teardown/1.0 (+hosting-probe)"

DEFAULT_OVERDUE_AGE_DAYS = 14

DB_GONE = "gone"
DB_LIVE = "live"
DB_NA = "n/a"
DB_UNVERIFIABLE = "unverifiable"
DB_UNKNOWN = "unknown"

_DB_STATUS_MAP = {
    "alive": DB_LIVE,
    "deleted_verified": DB_GONE,
    "never_existed": DB_GONE,
    "never_located": DB_NA,
    "not_visible": DB_UNVERIFIABLE,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value):
    if not value:
        return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def db_evidence(mapping: dict) -> dict:
    backend = mapping.get("db_backend") or {}
    status = _DB_STATUS_MAP.get(backend.get("status"), DB_UNKNOWN)
    evidence = backend.get("evidence") or (
        "no db_backend record — run iterate_cross_db.py verify-backends"
    )
    return {"status": status, "evidence": evidence,
            "checked_at": backend.get("checked_at")}


def hosting_probe(name: str, timeout: int = 8) -> dict:
    """Zero-credential edge probe. WEAK evidence — labeled as such."""
    host = name if "." in name else f"{name}.draftlabs.org"
    url = f"https://{host}"
    req = urllib.request.Request(url, headers={"User-Agent": _UA}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
    except urllib.error.HTTPError as e:
        status = e.code
    except Exception as e:  # DNS failure, TLS, timeout — surface gone (weak)
        return {"status": "surface_gone",
                "evidence": f"probe {url}: {type(e).__name__} (weak edge evidence)"}
    if status == 404:
        return {"status": "surface_gone",
                "evidence": f"probe {url}: http 404 (weak edge evidence)"}
    # 200/3xx = serving; 5xx = something is deployed and erroring — still live.
    return {"status": "live", "evidence": f"probe {url}: http {status}"}


def ads_evidence(
    name: str,
    scores_by_name: dict,
    ledger_row: dict | None,
    unmatched_active: int | None = None,
) -> dict:
    """Ads evidence line. Priority: sticky operator confirmation →
    none_in_window → csv_paused (GA CSV status columns) → unknown.

    unmatched_active is the run-level count of UNATTRIBUTABLE unmatched
    campaigns (placeholder/unmatched reasons — pre-relaunch rows are attributed
    and covered per-MVP) that are not verifiably stopped. csv_paused requires
    exactly 0; None means "no unmatched info" (old-format file, standalone run)
    and conservatively blocks csv_paused, falling back to confirm-ads.
    """
    sticky = ((ledger_row or {}).get("teardown_evidence") or {}).get("ads") or {}
    if sticky.get("status") == "confirmed_paused":
        return {"status": "confirmed_paused",
                "evidence": f"operator confirmed {sticky.get('confirmed_at')}"}
    score = scores_by_name.get(name) or {}
    campaigns = score.get("ga_campaigns") or []
    detail = score.get("ga_campaign_status_detail") or []
    active = [d for d in detail if d.get("normalized") == "active"]
    if not campaigns and not active:
        return {"status": "none_in_window",
                "evidence": "no GA campaigns bucketed to this MVP in the window"}
    if not campaigns and active:
        # Every campaign left the analysis window (pre-relaunch drop) but the
        # CSV says at least one is still deliverable — never auto-close.
        names = ", ".join(sorted(d.get("name") or "?" for d in active))
        return {"status": "unknown",
                "evidence": f"no campaigns in analysis window but still deliverable per CSV: {names} — pause, then confirm-ads"}
    if score.get("ga_ads_all_stopped") is True and unmatched_active == 0:
        summary = ", ".join(
            f"{d.get('name')}: {d.get('campaign_status') or '?'}/{d.get('serving_status') or '?'}"
            for d in detail
        )
        return {"status": "csv_paused",
                "evidence": f"all campaigns stopped per GA CSV ({summary})"}
    return {"status": "unknown",
            "evidence": f"campaigns in window: {', '.join(campaigns)} — confirm paused via confirm-ads"}


def _waiver_active(mapping: dict, reference_now) -> bool:
    keep = mapping.get("backend_keep")
    if not isinstance(keep, dict):
        return False
    exp = _parse_iso(keep.get("expires_at"))
    ref = _parse_iso(reference_now)
    if exp is not None and ref is not None and exp <= ref:
        return False
    return True


def closeout(db: dict, hosting: dict, ads: dict, waived: bool) -> str:
    if waived:
        return "waived"
    if (
        db["status"] in (DB_GONE, DB_NA)
        and hosting["status"] == "surface_gone"
        and ads["status"] in ("confirmed_paused", "csv_paused", "none_in_window")
    ):
        return "verified"
    return "due"


def build_obligations(
    config: dict,
    scores: dict | None,
    ledger_rows: dict[str, dict],
    reference_now: str,
    probe=hosting_probe,
    unmatched_active: int | None = None,
) -> list[dict]:
    mappings = (config or {}).get("mvp_mappings") or {}
    roster = (config or {}).get("team_roster") or {}
    scores_by_name = {s.get("name"): s for s in (scores or {}).get("mvps", [])}
    ref = _parse_iso(reference_now)

    obligations = []
    for name, mapping in sorted(mappings.items()):
        if not isinstance(mapping, dict) or name.startswith("__orphan"):
            continue
        if mapping.get("lifecycle_status") != "killed":
            continue

        owner = mapping.get("owner") or (scores_by_name.get(name) or {}).get("owner")
        member = roster.get(owner) if owner else None
        if not owner or (isinstance(member, dict) and member.get("status") == "departed"):
            owner = "alan"  # operator inherits unowned + departed members' items

        killed_at = _parse_iso(mapping.get("lifecycle_status_at"))
        age_days = (ref - killed_at).days if (ref and killed_at) else None

        db = db_evidence(mapping)
        # Backend verifiably gone → no hosting/ads probe needed to know the DB
        # line; hosting still probed (a Vercel deploy can outlive its DB).
        hosting = probe(name)
        ads = ads_evidence(
            name, scores_by_name, ledger_rows.get(name),
            unmatched_active=unmatched_active,
        )
        if ads.get("status") == "csv_paused":
            ads["checked_at"] = reference_now
        waived = _waiver_active(mapping, reference_now)
        state = closeout(db, hosting, ads, waived)
        money_leak = bool(((scores_by_name.get(name) or {}).get("metrics") or {}).get("money_leak"))
        # still_serving is computed for EVERY killed row including waived ones:
        # backend_keep waives the backend, not the ads — and a sticky
        # confirmed_paused never reopens, so this is the only line that
        # surfaces a re-enabled campaign.
        detail = (scores_by_name.get(name) or {}).get("ga_campaign_status_detail") or []
        still_serving = [
            {"name": d.get("name"),
             "campaign_status": d.get("campaign_status"),
             "serving_status": d.get("serving_status")}
            for d in detail if d.get("normalized") == "active"
        ]

        obligations.append({
            "mvp": name,
            "owner": owner,
            "killed_at": mapping.get("lifecycle_status_at"),
            "killed_age_days": age_days,
            "money_leak": money_leak,
            "db": db,
            "hosting": hosting,
            "ads": ads,
            "still_serving": still_serving,
            "waived": waived,
            "teardown_state": state,
        })
    return obligations


def stamp_teardown_fields(ledger_path: str, obligations: list[dict], run_date: str) -> dict:
    """Write teardown_* fields onto ledger rows WITHOUT unfreezing them.

    upsert_row starts from dict(existing), so these fields survive later x4a
    upserts untouched. archived_at / current / verdict_history / sticky fields
    are never modified here.
    """
    rows = []
    by_mvp: dict[str, dict] = {}
    if os.path.exists(ledger_path):
        with open(ledger_path) as fh:
            for line in fh:
                if not line.strip():
                    continue
                row = json.loads(line)
                rows.append(row)
                by_mvp[row.get("mvp")] = row

    stamped = 0
    missing = []
    for ob in obligations:
        row = by_mvp.get(ob["mvp"])
        if row is None:
            missing.append(ob["mvp"])
            continue
        state = ob["teardown_state"]
        row["teardown_state"] = state
        evidence = row.setdefault("teardown_evidence", {})
        evidence["db"] = ob["db"]
        evidence["hosting"] = ob["hosting"]
        # ads: keep a sticky operator confirmation; otherwise record this run's.
        if (evidence.get("ads") or {}).get("status") != "confirmed_paused":
            evidence["ads"] = ob["ads"]
        if state == "due":
            row.setdefault("teardown_first_due_at", run_date)
            row["teardown_reminder_count"] = int(row.get("teardown_reminder_count") or 0) + 1
        elif state == "verified" and not row.get("teardown_verified_at"):
            row["teardown_verified_at"] = run_date
        stamped += 1

    tmp = f"{ledger_path}.tmp.{os.getpid()}"
    with open(tmp, "w") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n")
    os.replace(tmp, ledger_path)
    return {"stamped": stamped, "missing_ledger_rows": missing}


def confirm_ads_paused(ledger_path: str, name: str, run_date: str) -> bool:
    """Operator keyed confirmation that the MVP's campaigns are paused."""
    rows = []
    found = False
    with open(ledger_path) as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("mvp") == name:
                evidence = row.setdefault("teardown_evidence", {})
                evidence["ads"] = {"status": "confirmed_paused", "confirmed_at": run_date}
                found = True
            rows.append(row)
    if not found:
        return False
    tmp = f"{ledger_path}.tmp.{os.getpid()}"
    with open(tmp, "w") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n")
    os.replace(tmp, ledger_path)
    return True


def _fmt_line(ob: dict) -> str:
    age = f"killed {ob['killed_age_days']}d ago" if ob["killed_age_days"] is not None else "killed (age unknown)"
    return (
        f"{ob['mvp']} — {age} · DB:{ob['db']['status'].upper()} "
        f"HOST:{ob['hosting']['status'].upper()} ADS:{ob['ads']['status']}"
    )


def render_report(obligations: list[dict], overdue_age_days: int = DEFAULT_OVERDUE_AGE_DAYS) -> str:
    leaks = [o for o in obligations if o["money_leak"] and o["teardown_state"] == "due"]
    overdue = [
        o for o in obligations
        if o["teardown_state"] == "due" and not o["money_leak"]
        and o["killed_age_days"] is not None and o["killed_age_days"] >= overdue_age_days
    ]
    due = [
        o for o in obligations
        if o["teardown_state"] == "due" and o not in leaks and o not in overdue
    ]
    verified = [o for o in obligations if o["teardown_state"] == "verified"]
    waived = [o for o in obligations if o["teardown_state"] == "waived"]

    lines = ["=== TEARDOWN RECONCILE ==="]
    # STILL_SERVING cuts across close-out states (waived included): the ONLY
    # rows where a human must act in Google Ads right now.
    serving = [o for o in obligations if (o.get("still_serving") or [])]
    if serving:
        lines.append("📣 STILL_SERVING (killed but ads deliverable — pause these in Google Ads NOW):")
        for o in serving:
            waived_tag = " [backend_keep waived]" if o.get("teardown_state") == "waived" else ""
            for c in (o.get("still_serving") or []):
                lines.append(
                    f"  {o['mvp']} — {c.get('name')} "
                    f"({c.get('campaign_status') or '?'}/{c.get('serving_status') or '?'})"
                    f"{waived_tag} → {o.get('owner')}"
                )
    if leaks:
        lines.append("🔥 MONEY_LEAK (recent paid traffic to a dead funnel):")
        lines += [f"  {_fmt_line(o)} → {o['owner']}" for o in leaks]
    if overdue:
        lines.append(f"🚨 OVERDUE (due ≥ {overdue_age_days}d):")
        lines += [f"  {_fmt_line(o)} → {o['owner']}" for o in overdue]
    if due:
        lines.append("⏳ DUE:")
        lines += [f"  {_fmt_line(o)} → {o['owner']}" for o in due]
    if verified:
        lines.append("✅ VERIFIED (closed on evidence):")
        lines += [f"  {o['mvp']}" for o in verified]
    if waived:
        lines.append("🤝 WAIVED (backend_keep):")
        lines += [f"  {o['mvp']}" for o in waived]
    if len(lines) == 1:
        lines.append("No teardown obligations — fleet is clean.")
    return "\n".join(lines)


def reconcile(
    config_path: str,
    scores_path: str | None,
    ledger_path: str,
    output_path: str,
    reference_now: str | None = None,
    dry_run: bool = False,
    probe=hosting_probe,
    unmatched_path: str | None = None,
) -> dict:
    if yaml is None:
        raise SystemExit("ERROR: PyYAML required (pip install pyyaml)")
    config = yaml.safe_load(open(config_path)) if os.path.exists(config_path) else {}
    scores = None
    if scores_path and os.path.exists(scores_path):
        scores = json.load(open(scores_path))
    ledger_rows: dict[str, dict] = {}
    if os.path.exists(ledger_path):
        with open(ledger_path) as fh:
            for line in fh:
                if line.strip():
                    row = json.loads(line)
                    ledger_rows[row.get("mvp")] = row

    now = reference_now or _now_iso()
    thresholds = (config or {}).get("thresholds") or {}
    overdue_days = int(thresholds.get("teardown_overdue_days", DEFAULT_OVERDUE_AGE_DAYS))

    # Run-level csv_paused gate: count unattributable unmatched campaigns that
    # are not verifiably stopped. None (file absent/unreadable/old-format
    # entries missing status) conservatively blocks csv_paused in ads_evidence.
    unmatched_active = None
    if unmatched_path and os.path.exists(unmatched_path):
        try:
            entries = json.load(open(unmatched_path))
        except (json.JSONDecodeError, OSError):
            entries = None
        if isinstance(entries, list):
            unmatched_active = sum(
                1 for u in entries
                if isinstance(u, dict)
                and u.get("reason") != "pre-relaunch"
                and u.get("status_normalized") != "stopped"
            )
            ref_dt = _parse_iso(now)
            try:
                mtime = datetime.fromtimestamp(
                    os.path.getmtime(unmatched_path), tz=timezone.utc
                )
            except OSError:
                mtime = None
            if ref_dt and mtime and (ref_dt - mtime).total_seconds() > 48 * 3600:
                print(
                    f"WARN: {unmatched_path} is >48h older than the reference time — "
                    "csv ads evidence may be stale; re-run /iterate --cross (x0a).",
                    file=sys.stderr,
                )

    obligations = build_obligations(
        config, scores, ledger_rows, now, probe=probe,
        unmatched_active=unmatched_active,
    )
    payload = {
        "reference_now": now,
        "overdue_age_days": overdue_days,
        "unmatched_active": unmatched_active,
        "counts": {
            "due": sum(1 for o in obligations if o["teardown_state"] == "due"),
            "verified": sum(1 for o in obligations if o["teardown_state"] == "verified"),
            "waived": sum(1 for o in obligations if o["teardown_state"] == "waived"),
        },
        "obligations": obligations,
    }
    stamp_result = {"stamped": 0, "missing_ledger_rows": []}
    if not dry_run:
        with open(output_path, "w") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        stamp_result = stamp_teardown_fields(ledger_path, obligations, now[:10])
    payload["ledger"] = stamp_result
    print(render_report(obligations, overdue_days))
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_rec = sub.add_parser("reconcile")
    p_rec.add_argument("--config", default="experiment/iterate-cross-config.yaml")
    p_rec.add_argument("--scores", default=".runs/iterate-cross-scores.json")
    p_rec.add_argument("--ledger", default="experiment/mvp-decision-ledger.jsonl")
    p_rec.add_argument("--output", default=".runs/iterate-cross-teardown-obligations.json")
    p_rec.add_argument("--reference-now", default=None)
    p_rec.add_argument("--dry-run", action="store_true")
    # Default path lives ONLY here (not on reconcile()) so library callers and
    # tests never silently read the repo's real triage file.
    p_rec.add_argument("--unmatched", default=".runs/_iterate-cross-ga-unmatched.json",
                       help="x0a unmatched-campaign triage file; gates csv_paused ads evidence.")

    p_ads = sub.add_parser("confirm-ads")
    p_ads.add_argument("--ledger", default="experiment/mvp-decision-ledger.jsonl")
    p_ads.add_argument("--name", required=True)
    p_ads.add_argument("--confirm", action="store_true")

    args = parser.parse_args(argv)

    if args.cmd == "reconcile":
        result = reconcile(
            args.config, args.scores, args.ledger, args.output,
            reference_now=args.reference_now, dry_run=args.dry_run,
            unmatched_path=args.unmatched,
        )
        print(json.dumps({"counts": result["counts"], "ledger": result["ledger"]}, indent=2))
        return 0

    if args.cmd == "confirm-ads":
        if not args.confirm:
            print("confirm-ads requires --confirm; nothing written.", file=sys.stderr)
            return 2
        ok = confirm_ads_paused(args.ledger, args.name, _now_iso()[:10])
        print(f"confirm-ads: {'recorded' if ok else 'MVP not found in ledger'} for {args.name}")
        return 0 if ok else 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
