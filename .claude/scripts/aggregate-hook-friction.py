#!/usr/bin/env python3
"""Aggregate .runs/hook-friction.jsonl into .runs/hook-friction-summary.json.

Per-hook block counts + sample reasons (max 3 unique). STRICTLY scoped to the
current run_id resolved from .runs/<skill>-context.json (#1895): rows whose
run_id differs — including EMPTY run_id (orphan rows from hook self-tests,
between-runs friction, pre-init denials) — never enter the summary. When no
active run is resolvable at all, an explicit empty summary with run_id null
is written; the persistent jsonl is NEVER aggregated unscoped.

The summary carries `aggregated_at` (UTC ISO) so consumers can tell tail
truncation from genuine quiet: friction rows time-stamped after
`aggregated_at` (e.g. the observer agent's own spawn passing
skill-agent-gate.sh) are structurally invisible to this snapshot —
check-observation-artifacts.sh surfaces them as rows_after_cutoff.
Invoked at lifecycle-finalize.sh Step 2.6 (first pass) and re-run by
observation-phase.md Step 2d (epilogue tail refresh); idempotent — each
invocation rebuilds the summary from scratch.

Used as Step 5a Q2 evidence (#1128 Layer 6). The summary is what the
Step 5a evaluator reads; the raw .jsonl stays as audit trail.

#1255 (round-2 critic Concern 6): also produces `normalized_groups` keyed
by (hook, normalized_reason) where normalized_reason has paths/IDs/
timestamps/line-numbers stripped — this catches hooks whose denial
messages vary per call site (would never reach count>=3 under raw key).

When a normalized group reaches `count >= 3`, this script invokes
file-retrospective-finding.py to auto-file an [observe] issue (no LLM
evaluation needed — pure friction signal). Per-run cap = 5 auto-files
to prevent cascade.

Fail-open: missing/empty input → empty summary written; never raises.
"""
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone

# Round-2 Concern 6: normalize denial reasons before grouping
_NORMALIZE_PATTERNS = [
    (re.compile(r"/[\w./_-]+"), "<PATH>"),                    # filesystem paths
    (re.compile(r"#\d+"), "<ISSUE>"),                          # issue refs
    (re.compile(r"\b[0-9a-f]{6,40}\b"), "<HASH>"),              # SHAs / hashes
    (re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"), "<TIMESTAMP>"),
    (re.compile(r":\d+\b"), ":<LINE>"),                         # :12 line refs
    (re.compile(r"\b\d{4,}\b"), "<NUM>"),                       # large numbers
]

AUTO_FILE_THRESHOLD = 3
AUTO_FILE_CAP_PER_RUN = 5
PENDING_PATH = ".runs/retrospective-pending-findings.json"


def _normalize_reason(reason: str) -> str:
    """Strip paths, IDs, timestamps, line numbers — yields stable group key."""
    if not reason:
        return ""
    out = reason
    for pattern, repl in _NORMALIZE_PATTERNS:
        out = pattern.sub(repl, out)
    return out[:200]


def _active_run_id():
    best = None
    best_ts = ''
    try:
        for f in glob.glob('.runs/*-context.json'):
            if 'epilogue' in f:
                continue
            try:
                d = json.load(open(f))
            except Exception:
                continue
            if d.get('completed') is True:
                continue
            ts = d.get('timestamp') or ''
            if ts >= best_ts:
                best = d
                best_ts = ts
    except Exception:
        pass
    return (best or {}).get('run_id', '')


def _try_auto_file(group_key: tuple, info: dict, run_id: str) -> bool:
    """Auto-file a [observe] issue for a high-frequency normalized group.

    Returns True on file (or successful no-op), False on error. Idempotent
    via candidate_id derived from the group key.
    """
    hook_name, normalized_reason = group_key
    candidate_id = hashlib.sha256(
        f"hook-friction:{hook_name}:{normalized_reason}".encode()
    ).hexdigest()[:12]

    title = (
        f"hook-friction recurrence: {hook_name} fired {info['count']}x with "
        f"normalized reason — investigate template-rooted cause"
    )
    body_parts = [
        "## Auto-filed observation",
        "",
        f"**Hook:** `{hook_name}`",
        f"**Count this run:** {info['count']}",
        f"**Normalized reason:** `{normalized_reason}`",
        "",
        "## Sample raw denial messages",
        "",
    ]
    for raw in info.get("sample_raw_reasons", [])[:3]:
        body_parts.append(f"- `{raw[:200]}`")
    body_parts.extend([
        "",
        "## Why this was auto-filed",
        "",
        (
            "Issue #1255 (round-2 Concern 6): hook denial reasons that vary per "
            "call site (paths/IDs/line numbers) are normalized so recurring "
            "patterns can be detected. This pattern fired ≥3 times — likely a "
            "template-rooted issue worth investigating without LLM evaluation."
        ),
        "",
        f"**Auto-file candidate_id:** `{candidate_id}`",
        f"**Run:** `{run_id}`",
    ])
    body = "\n".join(body_parts)

    # Insert candidate into pending findings (so file-retrospective-finding.py validates)
    pending: dict = {"run_id": run_id, "schema_version": 2, "candidates": []}
    if os.path.isfile(PENDING_PATH):
        try:
            pending = json.load(open(PENDING_PATH))
        except Exception:
            pass
    cands = pending.setdefault("candidates", [])
    if not any(c.get("candidate_id") == candidate_id for c in cands):
        cands.append({
            "candidate_id": candidate_id,
            "kind": "hook-friction",
            "confidence": "high",
            "key": f"hook:{hook_name}:{normalized_reason}",
            "evidence": {
                "hook": hook_name,
                "count": info["count"],
                "normalized_reason": normalized_reason,
                "sample_raw_reasons": info.get("sample_raw_reasons", []),
            },
            "source_files": [".runs/hook-friction.jsonl"],
        })
        try:
            with open(PENDING_PATH, "w") as f:
                json.dump(pending, f, indent=2)
        except Exception:
            pass

    # Invoke file-retrospective-finding.py (idempotent on candidate_id)
    try:
        r = subprocess.run(
            [
                "python3", ".claude/scripts/file-retrospective-finding.py",
                "--candidate-id", candidate_id,
                "--title", title,
                "--body", body,
                "--auto-filed",
            ],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            print(f"WARN: auto-file failed for {hook_name} ({normalized_reason[:50]}): {r.stderr[:200]}", file=sys.stderr)
            return False
        return True
    except Exception as e:
        print(f"WARN: auto-file exception: {e}", file=sys.stderr)
        return False


# #1393 r3 — closed enum mirroring append-hook-friction.py VALID_ACTION_TYPES.
# Rows missing the field (legacy / pre-PR-1402 entries) classify as "block".
VALID_ACTION_TYPES = (
    "block",
    "warn-mode-bypass",
    "manual-write-sanctioned",
    "manual-write-deviation",
)


def main():
    rid = _active_run_id()
    aggregated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    summary = defaultdict(lambda: {"count": 0, "sample_reasons": [], "_seen": set()})
    normalized = defaultdict(lambda: {"count": 0, "sample_raw_reasons": [], "_seen_raw": set()})
    # #1393 r3 — surface action_type discrimination at the consumer layer so
    # observer + compliance-audit can distinguish deviations from sanctioned
    # writes / warn-mode bypasses / blocks. Without this, the action_type
    # field in raw .jsonl rows is invisible to downstream consumers — the
    # framework declared a channel but no consumer can read the discriminator.
    action_type_counts = {at: 0 for at in VALID_ACTION_TYPES}
    path = '.runs/hook-friction.jsonl'
    out_path = '.runs/hook-friction-summary.json'

    def _write_empty():
        try:
            os.makedirs('.runs', exist_ok=True)
            with open(out_path, 'w') as f:
                json.dump({
                    "run_id": rid or None, "hooks": {}, "total": 0,
                    "normalized_groups": {},
                    "action_type_counts": action_type_counts,
                    "aggregated_at": aggregated_at,
                }, f, indent=2)
        except Exception:
            pass

    if not os.path.isfile(path):
        _write_empty()
        return 0

    if not rid:
        # #1895: no active run resolvable (between runs, post advance-state 99,
        # corrupted contexts). The jsonl is a persistent cross-run trail — an
        # unscoped pass would count every historical run's rows, so write an
        # explicit empty summary instead of aggregating everything.
        _write_empty()
        return 0

    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                # #1895: STRICT run scoping. Empty run_id rows (hook self-tests,
                # between-runs friction) previously slipped past the truthiness
                # guard and inflated every run's total.
                if e.get('run_id') != rid:
                    continue
                h = e.get('hook', 'unknown')
                r = (e.get('reason') or '')[:300]
                # #1393 r3 — classify by action_type (legacy missing → "block").
                at = e.get('action_type') or 'block'
                if at not in VALID_ACTION_TYPES:
                    at = 'block'
                action_type_counts[at] += 1
                summary[h]["count"] += 1
                if r and r not in summary[h]["_seen"] and len(summary[h]["sample_reasons"]) < 3:
                    summary[h]["sample_reasons"].append(r)
                    summary[h]["_seen"].add(r)

                # Normalized grouping (#1255)
                norm_r = _normalize_reason(r)
                key = (h, norm_r)
                normalized[key]["count"] += 1
                if r and r not in normalized[key]["_seen_raw"] and len(normalized[key]["sample_raw_reasons"]) < 3:
                    normalized[key]["sample_raw_reasons"].append(r)
                    normalized[key]["_seen_raw"].add(r)
    except Exception:
        pass

    out = {
        "run_id": rid, "hooks": {}, "total": 0,
        "normalized_groups": {},
        # #1393 r3 — top-level breakdown so consumers don't need to re-parse raw .jsonl.
        "action_type_counts": action_type_counts,
        # #1895: snapshot cutoff — rows appended after this instant are not in
        # this summary (check-observation-artifacts.sh reports them).
        "aggregated_at": aggregated_at,
    }
    for h, v in summary.items():
        out["hooks"][h] = {"count": v["count"], "sample_reasons": v["sample_reasons"]}
        out["total"] += v["count"]

    # Serialize normalized groups with composite key
    for (h, norm_r), info in normalized.items():
        composite_key = f"{h}::{norm_r}"
        out["normalized_groups"][composite_key] = {
            "hook": h,
            "normalized_reason": norm_r,
            "count": info["count"],
            "sample_raw_reasons": info["sample_raw_reasons"],
        }

    try:
        os.makedirs('.runs', exist_ok=True)
        with open(out_path, 'w') as f:
            json.dump(out, f, indent=2)
    except Exception:
        pass

    # Auto-file (#1255): groups at threshold trigger file-retrospective-finding.py
    # GUARDS:
    #   - dry-run DEFAULTS TO 1 during rollout window (matches MODE=warn
    #     convention used by the 5 hard-block validators). Set
    #     AGGREGATE_HOOK_FRICTION_DRY_RUN=0 to enable real auto-file once
    #     1-2 real skill cycles confirm zero false positives.
    #   - schema_version cutoff: only fire when run_id is post-cutoff
    #     (prevents auto-file on pre-cutoff runs that the new contract was
    #     never designed to enforce)
    auto_filed_this_run = 0
    dry_run = os.environ.get("AGGREGATE_HOOK_FRICTION_DRY_RUN", "1") != "0"
    if rid and not dry_run:
        # Cutoff guard
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        try:
            from lib.schema_version_gate import required_schema_version  # type: ignore
            cutoff_active = required_schema_version(rid) >= 2
        except Exception:
            cutoff_active = False
        if cutoff_active:
            groups_sorted = sorted(
                normalized.items(), key=lambda kv: -kv[1]["count"]
            )
            for (h, norm_r), info in groups_sorted:
                if auto_filed_this_run >= AUTO_FILE_CAP_PER_RUN:
                    break
                if info["count"] < AUTO_FILE_THRESHOLD:
                    continue
                ok = _try_auto_file((h, norm_r), info, rid)
                if ok:
                    auto_filed_this_run += 1
    elif dry_run:
        # Compute would-have-filed count for visibility
        would_file = sum(
            1 for info in normalized.values() if info["count"] >= AUTO_FILE_THRESHOLD
        )
        would_file = min(would_file, AUTO_FILE_CAP_PER_RUN)
        print(f"  [DRY_RUN] would have auto-filed {would_file} groups", file=sys.stderr)

    print(
        f"aggregate-hook-friction: {out['total']} entries across {len(out['hooks'])} hooks; "
        f"{len(out['normalized_groups'])} normalized groups; auto_filed={auto_filed_this_run}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
