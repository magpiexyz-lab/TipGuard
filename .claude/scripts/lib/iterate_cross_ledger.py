#!/usr/bin/env python3
"""Persist each MVP's verdict + metrics + description + tags to a durable git
ledger (state x4a), so portfolio outcome data survives infra teardown.

When an MVP is judged NO_GO, its Supabase/Railway/Vercel infra is often deleted to
save cost — which destroys the PostHog/DB ground truth. This module captures, BEFORE
deletion and committed to git, what each MVP did and how it performed, building a
reusable dataset for brainstorming and pre-judging new ideas.

Design (operator-confirmed):
  - Non-destructive UPSERT keyed by canonical MVP name (one row per MVP).
  - `current` verdict+metrics overwritten each run; `verdict_history` appends a
    compact {date,verdict,why} only when the verdict/why changed (bounded by a cap).
  - `what_it_does` (mechanically parsed from the repo's experiment.yaml) and `tags`
    (lead-proposed enums) are STICKY — never overwritten with empty; the repo may be
    gone on a later run.
  - A row freezes (`archived_at` set) when the backend is killed or DB-deleted, so
    the pre-teardown snapshot is locked. Freeze is REVERSIBLE: if trusted live DB
    ground truth reappears, the row un-freezes and resumes updating.
  - Orphans are skipped (no canonical identity, no repo); ga_only MVPs are included.

Mirrors iterate_cross_pricing.py (x0c) prepare → lead-extract → persist shape and
reuses resolve_repo / fetch_file / match_key / load_yaml / dump_yaml.

Subcommands:
  prepare  --scores --data --ledger --config [--enrich-all] --output
           select MVPs needing description/tags, fetch + mechanically parse each
           repo's experiment.yaml, write the bundle the lead reads for tag proposals.
  persist  --scores --data --ledger --input --proposals [--now]
           non-destructive upsert of every scored MVP into the jsonl ledger.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from iterate_cross_classify import load_yaml, match_key  # noqa: E402
from iterate_cross_pricing import (  # noqa: E402
    fetch_file,
    list_org_repo_records,
    load_or_refresh_name_index,
    resolve_repo_layered,
)

HISTORY_CAP = 12

# Fixed enum vocab for classification tags. Constrained so post-teardown analysis
# can compare apples-to-apples. Operator can override via config `ledger_tag_vocab`.
DEFAULT_TAG_VOCAB = {
    "vertical": [
        "ai-content", "dev-tools", "agent-infra", "fintech", "ecommerce-ops",
        "compliance-legal", "creator-tools", "prosumer-productivity",
        "vertical-saas", "marketing-adtech", "data-analytics", "other",
    ],
    "gtm": ["waitlist", "self-serve-signup", "demo-led", "free-tool", "marketplace", "api-access"],
    "pricing_model": ["subscription", "one-time", "usage-based", "freemium", "none-waitlist"],
}

# experiment.yaml scalar fields copied verbatim into what_it_does (mechanical, no LLM).
DESC_FIELDS = ("thesis", "target_user", "description", "problem")


# ---------- pure helpers (unit-testable, no I/O) ----------

def _m(score: dict) -> dict:
    return score.get("metrics") or {}


def is_orphan(score: dict) -> bool:
    name = score.get("name") or ""
    return name.startswith("__orphan_") or score.get("db_unmapped_reason") == "orphan"


def build_alias_index(aliases: dict) -> dict:
    """Reverse {canonical: [alias,...]} into {alias: canonical}, failing loudly on
    a collision (same alias under two canonicals) — mirrors merge_mvp_aliases."""
    reverse: dict[str, str] = {}
    for canonical, alias_list in (aliases or {}).items():
        for alias in (alias_list or []):
            if alias in reverse and reverse[alias] != canonical:
                raise ValueError(
                    f"ledger alias {alias!r} listed under both {reverse[alias]!r} "
                    f"and {canonical!r} — pick one canonical."
                )
            reverse[alias] = canonical
    return reverse


def canonical_name(score: dict, alias_index: dict) -> str | None:
    """Canonical ledger key for a score. None for orphans (skipped upstream).

    An alias name (e.g. `split-share-neon`) collapses to its canonical
    (`splitshare`). The cross pipeline already merges alias *rows* in x0,
    so this is a defensive collapse for any that slipped through.
    """
    if is_orphan(score):
        return None
    name = score.get("name")
    if not name:
        return None
    return alias_index.get(name, name)


def is_live_ground_truth(score: dict) -> bool:
    """True when the score carries trusted live DB ground truth — used to UN-FREEZE
    a previously-archived row (guards against a transient DB-ref break or a kill
    that was later reversed)."""
    if is_deleted(score):
        return False
    return bool(score.get("db_source")) and isinstance(_m(score).get("db_signups_real"), int)


def is_deleted(score: dict) -> bool:
    return (
        score.get("db_unmapped_reason") in ("project_deleted", "archived_killed")
        or score.get("lifecycle_status") == "killed"
    )


def current_snapshot(score: dict, why: str, run_date: str) -> dict:
    m = _m(score)
    return {
        "verdict": score.get("headline_verdict"),
        "why": why,
        # Operator lifecycle decision (active/killed/promoted). The ledger is
        # the long-lived post-teardown dataset, so the decision state must be
        # queryable here, not only in the operator config.
        "lifecycle_status": score.get("lifecycle_status") or "active",
        "ga_clicks": m.get("ga_clicks") or 0,
        # Phase-1 slice of the clicks (blended minus %phase2% campaigns) — the
        # denominator behind true_conv_rate. Defensive: None on pre-split rows.
        "ga_clicks_phase1": m.get("ga_clicks_phase1"),
        "ph_signups": m.get("ph_signups"),
        "db_signups_real": m.get("db_signups_real"),
        "db_signups_paid": m.get("db_signups_paid"),
        "conv_rate": m.get("conv_rate"),
        "true_conv_rate": m.get("true_conv_rate"),
        "signup_source": m.get("signup_source"),
        "db_source": score.get("db_source"),
        "monthly_price_usd": m.get("monthly_price_usd"),
        # Stalled-flow triage (state-x3 annotate_stalled). Persisted so the
        # NEXT run's x3 can compute run-over-run click deltas and carry the
        # stalled_since/streak state forward. Old rows read back None → fresh.
        "ga_impressions": m.get("ga_impressions"),
        "stalled_bucket": m.get("stalled_bucket"),
        "stalled_cause": m.get("stalled_cause"),
        "stalled_since": m.get("stalled_since"),
        "stalled_streak": m.get("stalled_streak"),
        "last_run": run_date,
    }


def stalled_why(score: dict) -> str:
    """Constant `why` for stalled-escalated INSUF rows.

    Written while the row is still INSUFFICIENT_DATA so the durable ledger
    records the channel-level story BEFORE an operator-confirmed kill flips
    the row to the generic archived NO_GO. Constant per cause (no numbers) —
    append_history dedups on exact verdict+why, so any varying text would
    append a history row every run.
    """
    m = _m(score)
    if not m.get("stalled_escalated"):
        return ""
    cause = m.get("stalled_cause")
    if cause == "weak_demand":
        return (
            "stalled at the CPC cap with healthy impressions but ~zero CTR — "
            "a real weak-demand signal"
        )
    if cause == "zero_serve":
        return (
            "bid-capped stall (zero_serve) at the CPC cap — channel infeasible, "
            "NOT a product NO-GO"
        )
    return (
        "stalled: zero click growth at the CPC cap — channel infeasible, "
        "NOT a product NO-GO"
    )


def append_history(history: list, entry: dict, cap: int = HISTORY_CAP) -> list:
    """Append {date,verdict,why} only when verdict OR why changed vs the last
    entry (dedups consecutive identical runs), then cap to the last `cap`."""
    history = list(history or [])
    if history:
        last = history[-1]
        if last.get("verdict") == entry.get("verdict") and last.get("why") == entry.get("why"):
            return history  # no change → no new row (bounds growth)
    history.append(entry)
    if len(history) > cap:
        history = history[-cap:]
    return history


def merge_sticky(old: dict | None, new: dict | None, force: bool = False) -> dict:
    """Field-by-field sticky merge. Keep old unless old is empty and new is
    non-empty (or force). NEVER null-out a populated field."""
    old = dict(old or {})
    for k, v in (new or {}).items():
        if v in (None, "", [], {}):
            continue  # never overwrite with empty
        if force or not old.get(k):
            old[k] = v
    return old


def validate_tags(tags: dict | None, vocab: dict) -> tuple[dict, list[str]]:
    """Drop out-of-vocab tag values (warn). Returns (clean_tags, warnings)."""
    clean, warnings = {}, []
    for dim, val in (tags or {}).items():
        allowed = vocab.get(dim)
        if allowed is None:
            warnings.append(f"unknown tag dimension {dim!r}")
            continue
        if val in (None, ""):
            continue
        if val not in allowed:
            warnings.append(f"{dim}={val!r} not in vocab")
            continue
        clean[dim] = val
    return clean, warnings


def parse_description(experiment_yaml_text: str | None) -> dict:
    """Mechanically pull what_it_does scalars from a repo's experiment.yaml.
    No LLM. Returns {} on parse failure / missing file."""
    if not experiment_yaml_text:
        return {}
    try:
        import yaml
    except ImportError:
        return {}
    try:
        data = yaml.safe_load(experiment_yaml_text) or {}
    except Exception:  # noqa: BLE001 - malformed YAML → no description
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for field in DESC_FIELDS:
        val = data.get(field)
        if isinstance(val, str) and val.strip():
            out[field] = " ".join(val.split())[:600]
    return out


def upsert_row(existing: dict | None, score: dict, alias_index: dict, run_date: str,
               parsed_desc: dict | None, tags: dict | None, repo: str | None,
               why: str, force_enrich: bool = False) -> dict:
    """The non-destructive upsert for one MVP. See module docstring for semantics."""
    canon = canonical_name(score, alias_index)
    row = dict(existing or {})
    row["mvp"] = canon
    row.setdefault("phase", "phase-1")
    row.setdefault("archived_at", None)  # key always present (None = not frozen)
    if row.get("first_seen_in_ledger") is None:
        row["first_seen_in_ledger"] = run_date
    row["last_seen_in_ledger"] = run_date
    if repo and not row.get("repo"):
        row["repo"] = repo
    if score.get("owner") and not row.get("owner"):
        row["owner"] = score.get("owner")

    frozen = bool(existing and existing.get("archived_at"))

    # Un-freeze when trusted live DB ground truth reappears.
    if frozen and is_live_ground_truth(score):
        row["archived_at"] = None
        frozen = False

    if not frozen:
        # Operator-decision transition event: active→promoted is recorded once,
        # detected on the run AFTER the operator confirms (x4 persist-lifecycle
        # writes config; the next run's scores carry the new status — a
        # documented one-run lag; the config itself is the authoritative record
        # at confirm time). Edge-triggered: subsequent runs see the stored
        # snapshot already promoted. Promoted rows never freeze (is_deleted is
        # killed/deleted-only), so the row keeps updating while in Phase 2.
        prev_status = (row.get("current") or {}).get("lifecycle_status") or "active"
        incoming_status = score.get("lifecycle_status") or "active"
        if incoming_status == "promoted" and prev_status != "promoted":
            promoted_at = score.get("lifecycle_status_at") or run_date
            row["verdict_history"] = append_history(
                row.get("verdict_history"),
                {"date": run_date, "verdict": "PROMOTED",
                 "why": f"operator confirmed promote to Phase 2 (lifecycle_status_at={promoted_at})"},
            )
        row["current"] = current_snapshot(score, why, run_date)
        row["verdict_history"] = append_history(
            row.get("verdict_history"),
            {"date": run_date, "verdict": score.get("headline_verdict"), "why": why},
        )
        row["what_it_does"] = merge_sticky(row.get("what_it_does"), parsed_desc, force=force_enrich)
        row["tags"] = merge_sticky(row.get("tags"), tags, force=force_enrich)
        # Freeze AFTER snapshotting, so the locked-in current/history is the
        # pre-teardown state.
        if not row.get("archived_at") and is_deleted(score):
            row["archived_at"] = run_date
    else:
        # Frozen: leave current/history/sticky untouched (pre-teardown ground truth).
        row.setdefault("current", current_snapshot(score, why, run_date))
        row.setdefault("verdict_history", [])
        row.setdefault("what_it_does", {})
        row.setdefault("tags", {})
        row.setdefault("archived_at", existing.get("archived_at") if existing else run_date)

    return row


def _read_ledger(path: str) -> dict:
    """Read the jsonl ledger into {mvp: row}. Empty dict if absent."""
    by_canon: dict[str, dict] = {}
    if not os.path.exists(path):
        return by_canon
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            by_canon[row["mvp"]] = row
    return by_canon


def _write_ledger(path: str, by_canon: dict) -> None:
    """Atomic write: one JSON object per line, sorted by mvp for clean diffs."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        for mvp in sorted(by_canon):
            f.write(json.dumps(by_canon[mvp], sort_keys=True) + "\n")
    os.replace(tmp, path)


def _needs_enrichment(existing: dict | None) -> bool:
    """True when a row is missing sticky description or tags (incremental scope)."""
    if not existing:
        return True
    wid = existing.get("what_it_does") or {}
    tags = existing.get("tags") or {}
    return not wid or not tags


# ---------- subcommands ----------

def cmd_prepare(scores_path: str, data_path: str, ledger_path: str, config_path: str,
                enrich_all: bool, output_path: str) -> int:
    scores = json.load(open(scores_path)).get("mvps", [])
    config = load_yaml(config_path)
    alias_index = build_alias_index(config.get("mvp_aliases"))
    mappings = config.get("mvp_mappings") or {}
    repo_aliases = config.get("repo_aliases") or {}
    by_canon = _read_ledger(ledger_path)

    # Which canonical MVPs need a repo fetch this run?
    targets: list[tuple[str, dict]] = []  # (canon, score)
    seen_canon: set[str] = set()
    for s in scores:
        canon = canonical_name(s, alias_index)
        if not canon or canon in seen_canon:
            continue
        seen_canon.add(canon)
        existing = by_canon.get(canon)
        if existing and existing.get("archived_at"):
            continue  # frozen → don't re-fetch
        if enrich_all or _needs_enrichment(existing):
            targets.append((canon, s))

    records = list_org_repo_records() if targets else []
    name_index = load_or_refresh_name_index(records) if records else {}
    to_enrich, desc_only = [], []
    for canon, s in targets:
        repo, _method = resolve_repo_layered(canon, records, mappings, repo_aliases, name_index)
        parsed_desc = {}
        if repo:
            parsed_desc = parse_description(fetch_file(repo, "experiment/experiment.yaml"))
        entry = {
            "mvp": canon,
            "repo": repo,
            "parsed_desc": parsed_desc,
            # A compact prompt the lead uses to pick enum tags.
            "snippet_for_tags": {
                "thesis": parsed_desc.get("thesis"),
                "target_user": parsed_desc.get("target_user"),
                "signup_events": s.get("signup_events"),
                "monthly_price_usd": _m(s).get("monthly_price_usd"),
            },
        }
        # Rows that already have tags only need their (possibly refreshed) desc.
        existing = by_canon.get(canon)
        if existing and (existing.get("tags") or {}) and not enrich_all:
            desc_only.append(entry)
        else:
            to_enrich.append(entry)

    out = {
        "to_enrich": to_enrich,
        "desc_only": desc_only,
        "tag_vocab": config.get("ledger_tag_vocab") or DEFAULT_TAG_VOCAB,
        "target_count": len(targets),
    }
    with open(output_path, "w") as f:
        json.dump(out, f, indent=2)
    print(
        f"ledger-prepare: {len(targets)} MVP(s) to enrich "
        f"({len(to_enrich)} need tags, {len(desc_only)} desc-only) → {output_path}"
    )
    return 0


def cmd_persist(scores_path: str, data_path: str, ledger_path: str, input_path: str,
                proposals_path: str, now_iso: str | None = None, config_path: str | None = None) -> int:
    run_date = (now_iso or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"))[:10]
    score_doc = json.load(open(scores_path))
    scores = score_doc.get("mvps", [])
    thresholds = score_doc.get("thresholds") or {}
    config = load_yaml(config_path) if config_path else {}
    alias_index = build_alias_index(config.get("mvp_aliases"))
    vocab = config.get("ledger_tag_vocab") or DEFAULT_TAG_VOCAB

    bundle = {}
    if input_path and os.path.exists(input_path):
        bundle = json.load(open(input_path)) or {}
    desc_by_canon: dict[str, dict] = {}
    repo_by_canon: dict[str, str] = {}
    for entry in (bundle.get("to_enrich", []) + bundle.get("desc_only", [])):
        desc_by_canon[entry["mvp"]] = entry.get("parsed_desc") or {}
        if entry.get("repo"):
            repo_by_canon[entry["mvp"]] = entry["repo"]

    proposals = []
    if proposals_path and os.path.exists(proposals_path):
        proposals = json.load(open(proposals_path)) or []
    tags_by_canon: dict[str, dict] = {}
    for p in proposals:
        name = p.get("mvp") or p.get("name")
        if not name:
            continue
        clean, warnings = validate_tags(
            {"vertical": p.get("vertical"), "gtm": p.get("gtm"), "pricing_model": p.get("pricing_model")},
            vocab,
        )
        for w in warnings:
            print(f"WARN: ledger tags for {name}: {w}", file=sys.stderr)
        canon = alias_index.get(name, name)
        tags_by_canon[canon] = clean

    enrich_all = bool(bundle.get("enrich_all"))  # informational; force handled per-field
    by_canon = _read_ledger(ledger_path)

    upserted = 0
    frozen_n = 0
    seen_canon: set[str] = set()
    # Import here to avoid a hard dep cycle; the reason text mirrors the docx WHY.
    from iterate_cross_docx import no_go_reason
    for s in scores:
        canon = canonical_name(s, alias_index)
        if not canon or canon in seen_canon:
            continue
        seen_canon.add(canon)
        # NO_GO rows carry the demand/economics reason; stalled-escalated INSUF
        # rows carry the channel-infeasible story (recorded pre-kill — see
        # stalled_why); everything else stays reason-less.
        why = no_go_reason(s, thresholds) if s.get("headline_verdict") == "NO_GO" else stalled_why(s)
        row = upsert_row(
            by_canon.get(canon), s, alias_index, run_date,
            parsed_desc=desc_by_canon.get(canon),
            tags=tags_by_canon.get(canon),
            repo=repo_by_canon.get(canon),
            why=why,
            force_enrich=False,
        )
        by_canon[canon] = row
        upserted += 1
        if row.get("archived_at"):
            frozen_n += 1

    _write_ledger(ledger_path, by_canon)
    print(
        f"ledger-persist: upserted {upserted} MVP(s), {frozen_n} frozen (archived), "
        f"{len(by_canon)} total rows → {ledger_path}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="x4a: persist MVP verdicts to the durable decision ledger")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("prepare")
    pp.add_argument("--scores", required=True)
    pp.add_argument("--data", default=None)
    pp.add_argument("--ledger", required=True)
    pp.add_argument("--config", required=True)
    pp.add_argument("--enrich-all", action="store_true")
    pp.add_argument("--output", required=True)

    ps = sub.add_parser("persist")
    ps.add_argument("--scores", required=True)
    ps.add_argument("--data", default=None)
    ps.add_argument("--ledger", required=True)
    ps.add_argument("--input", required=True)
    ps.add_argument("--proposals", required=True)
    ps.add_argument("--config", default=None)
    ps.add_argument("--now", default=None)

    args = ap.parse_args(argv)
    if args.cmd == "prepare":
        return cmd_prepare(args.scores, args.data, args.ledger, args.config, args.enrich_all, args.output)
    if args.cmd == "persist":
        return cmd_persist(args.scores, args.data, args.ledger, args.input, args.proposals, args.now, args.config)
    return 2


if __name__ == "__main__":
    sys.exit(main())
