#!/usr/bin/env python3
"""Stack Knowledge nightly audit — file GitHub issues for knowledge-base hygiene.

Run by `.claude/scripts/stack-knowledge-audit.sh` on a cron schedule (see
`.github/workflows/stack-knowledge-nightly.yml`). Guard: the workflow only
runs on the template repo (magpiexyz-lab/mvp-template); downstream forks
skip via `if: github.repository == ...` conditional.

This module NEVER mutates stack files. It only files issues via `gh` for
maintainer action. Issue dedup across runs is keyed by a fingerprint stored
in `.runs/stack-knowledge-audit-filed.json`.

Responsibilities (per plan Phase 3):
  1. Dedup reconciliation — cluster open `pattern-proposal` issues by
     composite_identity_hash; keep earliest, close others with cross-ref.
  2. Family candidate — groups of ≥5 entries sharing
     (stack_scope, root_cause_class) → file `pattern-family-candidate`.
  3. Archive candidate — per-entry:
       days_since_last_seen > 90 AND occurrence_count ≤ 2
       AND confidence_score < 0.5
     → file `pattern-archive-candidate`.
  4. raw → stable — per-entry:
       occurrence_count ≥ 5 AND confidence_score > 0.8 AND no oscillation 90d
     → file `pattern-graduation-stable`.
  5. stable → canonical — per-entry:
       days_since_first_seen ≥ 60 AND no regression linking back
     → file `pattern-graduation-canonical`.

Signals: oscillation-in-last-90d comes from `.runs/convergence-history.jsonl`
if present; otherwise from `gh api search/issues?q=label:resolve-oscillation`
containing the entry's composite_identity_hash. If BOTH are unavailable, the
audit skips maturity-promotion candidates (steps 4+5) with a log line —
false promotion is costlier than a skipped night.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))

sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
from lib.stack_knowledge_parser import (  # noqa: E402
    iter_stack_knowledge_files,
    parse_stack_knowledge_file,
)

HISTORY_PATH = os.path.join(REPO_ROOT, ".runs", "convergence-history.jsonl")
FILED_STATE_PATH = os.path.join(REPO_ROOT, ".runs", "stack-knowledge-audit-filed.json")

FAMILY_CLUSTER_MIN = 5
ARCHIVE_DAYS_SINCE_LAST_SEEN = 90
ARCHIVE_MAX_OCCURRENCE = 2
ARCHIVE_MAX_CONFIDENCE = 0.5
RAW_TO_STABLE_MIN_OCCURRENCE = 5
RAW_TO_STABLE_MIN_CONFIDENCE = 0.8
OSCILLATION_WINDOW_DAYS = 90
STABLE_TO_CANONICAL_MIN_DAYS = 60


def _today_utc() -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _parse_ymd(s: Any) -> datetime | None:
    """Accept a string 'YYYY-MM-DD' or a datetime.date (PyYAML auto-parses)."""
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    if isinstance(s, date):
        return datetime(s.year, s.month, s.day, tzinfo=timezone.utc)
    if not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_iso(s: Any) -> datetime | None:
    if not isinstance(s, str):
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def load_all_entries() -> list[tuple[str, dict]]:
    """Load every (path, entry) pair across every Stack Knowledge file.

    Source of truth: `iter_stack_knowledge_files()` (currently
    `.claude/stacks/**/*.md` plus `.claude/scripts/lib/README.md`, with
    TEMPLATE.md and *.archive.md excluded).
    """
    out: list[tuple[str, dict]] = []
    for path in iter_stack_knowledge_files(REPO_ROOT):
        for entry in parse_stack_knowledge_file(path):
            out.append((path, entry))
    return out


def load_convergence_history() -> list[dict]:
    if not os.path.exists(HISTORY_PATH):
        return []
    out: list[dict] = []
    with open(HISTORY_PATH) as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                out.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
    return out


def oscillation_signal_available(history: list[dict], gh_cmd: str | None) -> bool:
    """True when we have SOME way to detect oscillation in the last 90d."""
    return bool(history) or gh_cmd is not None


def has_oscillation_for_entry(
    entry: dict,
    history: list[dict],
    gh_cmd: str | None,
) -> bool:
    """True if entry's id appears in a recent halted or oscillation-tagged run."""
    cutoff = _today_utc() - timedelta(days=OSCILLATION_WINDOW_DAYS)
    entry_id = entry.get("id", "")
    composite_hash = entry.get("composite_identity_hash", "")

    for h in history:
        ts = _parse_iso(h.get("timestamp", ""))
        if ts is None or ts < cutoff:
            continue
        patterns = h.get("patterns_matched") or []
        halted = bool(h.get("halted"))
        osc_sum = int(h.get("oscillation_count_sum") or 0)
        if (entry_id in patterns) and (halted or osc_sum > 0):
            return True

    if gh_cmd and composite_hash:
        try:
            r = subprocess.run(
                [
                    gh_cmd, "api",
                    "-X", "GET", "search/issues",
                    "-f", f"q=label:resolve-oscillation {composite_hash} in:body",
                    "--jq", ".total_count",
                ],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0 and r.stdout.strip().isdigit():
                return int(r.stdout.strip()) > 0
        except (subprocess.SubprocessError, OSError):
            pass
    return False


def load_filed_state() -> dict:
    if not os.path.exists(FILED_STATE_PATH):
        return {"filed_hashes": []}
    try:
        with open(FILED_STATE_PATH) as f:
            data = json.load(f)
        if not isinstance(data.get("filed_hashes"), list):
            return {"filed_hashes": []}
        return data
    except (OSError, json.JSONDecodeError):
        return {"filed_hashes": []}


def save_filed_state(state: dict) -> None:
    os.makedirs(os.path.dirname(FILED_STATE_PATH), exist_ok=True)
    with open(FILED_STATE_PATH, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)


FINGERPRINT_MARKER = "audit-fingerprint"
FINGERPRINT_LABELS = (
    "pattern-family-candidate",
    "pattern-archive-candidate",
    "pattern-graduation-stable",
    "pattern-graduation-canonical",
)


def _fingerprint(kind: str, key: str) -> str:
    return hashlib.sha1(f"{kind}:{key}".encode("utf-8")).hexdigest()[:12]


def _render_body_with_fingerprint(body: str, fp: str) -> str:
    """Append an HTML-comment fingerprint marker so future runs can dedup."""
    return f"{body.rstrip()}\n\n<!-- {FINGERPRINT_MARKER}: {fp} -->\n"


def _parse_fingerprint_from_body(body: str) -> str | None:
    if not isinstance(body, str) or not body:
        return None
    import re
    m = re.search(rf"<!--\s*{FINGERPRINT_MARKER}:\s*([0-9a-f]{{12}})\s*-->", body)
    return m.group(1) if m else None


def load_github_filed_fingerprints(gh_cmd: str | None) -> set[str]:
    """Query GitHub for all audit-filed issues (any state) across audit labels,
    parse the fingerprint marker from each body, and return the set.

    This is the SOURCE OF TRUTH for cross-run idempotency — the local
    `.runs/stack-knowledge-audit-filed.json` cache augments this but is
    never required (it's gitignored and absent on fresh CI checkouts).
    """
    if gh_cmd is None:
        return set()
    out: set[str] = set()
    for label in FINGERPRINT_LABELS:
        try:
            r = subprocess.run(
                [
                    gh_cmd, "issue", "list",
                    "--label", label,
                    "--state", "all",
                    "--limit", "500",
                    "--json", "body",
                ],
                capture_output=True, text=True, timeout=30,
            )
            if r.returncode != 0:
                continue
            data = json.loads(r.stdout)
            for iss in data:
                fp = _parse_fingerprint_from_body(iss.get("body") or "")
                if fp:
                    out.add(fp)
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError):
            continue
    return out


def gh_issue_create(
    gh_cmd: str,
    title: str,
    body: str,
    labels: list[str],
    dry_run: bool,
) -> int:
    """File a GitHub issue. Returns 0 on success (including dry-run)."""
    if dry_run:
        print(f"[dry-run] gh issue create --title {title!r} --label {','.join(labels)!r}")
        return 0
    args = [gh_cmd, "issue", "create", "--title", title, "--body", body]
    for lab in labels:
        args.extend(["--label", lab])
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            print(f"gh issue create failed: {r.stderr.strip()}", file=sys.stderr)
        else:
            print(f"filed: {title}  ({r.stdout.strip()})")
        return r.returncode
    except (subprocess.SubprocessError, OSError) as e:
        print(f"gh issue create error: {e}", file=sys.stderr)
        return 1


def gh_issue_close(gh_cmd: str, number: int, comment: str, dry_run: bool) -> int:
    if dry_run:
        print(f"[dry-run] gh issue close #{number}")
        return 0
    try:
        r = subprocess.run(
            [gh_cmd, "issue", "close", str(number), "--comment", comment],
            capture_output=True, text=True, timeout=30,
        )
        return r.returncode
    except (subprocess.SubprocessError, OSError):
        return 1


def list_open_pattern_proposals(gh_cmd: str | None) -> list[dict]:
    """Return open issues with label=pattern-proposal, parsed from gh."""
    if not gh_cmd:
        return []
    try:
        r = subprocess.run(
            [
                gh_cmd, "issue", "list",
                "--label", "pattern-proposal",
                "--state", "open",
                "--limit", "200",
                "--json", "number,title,body,createdAt",
            ],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return []
        return json.loads(r.stdout)
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError):
        return []


def _extract_hash_from_issue(issue: dict) -> str | None:
    """Pattern-proposal issues embed the 12-char composite_identity_hash in
    their TITLE as `[pattern-proposal:<HASH>] <summary>` — see the format
    written by .claude/skills/resolve/state-9-save-patterns.md. The hash may
    also appear in the body for robustness; try both."""
    import re
    title = issue.get("title") or ""
    m = re.search(r"\[pattern-proposal:([0-9a-f]{12})\]", title)
    if m:
        return m.group(1)
    body = issue.get("body") or ""
    m = re.search(r"composite_identity_hash[:\s]+([0-9a-f]{12})", body)
    return m.group(1) if m else None


def dedup_reconcile(
    gh_cmd: str | None,
    dry_run: bool,
) -> int:
    """Cluster open pattern-proposal issues by composite_identity_hash;
    keep earliest, close others."""
    issues = list_open_pattern_proposals(gh_cmd)
    if not issues:
        print("dedup: no open pattern-proposal issues")
        return 0

    by_hash: dict[str, list[dict]] = {}
    for iss in issues:
        h = _extract_hash_from_issue(iss)
        if not h:
            continue
        by_hash.setdefault(h, []).append(iss)

    closed = 0
    for h, group in by_hash.items():
        if len(group) < 2:
            continue
        group.sort(key=lambda i: i.get("createdAt", ""))
        winner = group[0]
        for loser in group[1:]:
            msg = (
                f"Duplicate of #{winner['number']} "
                f"(composite_identity_hash={h}). "
                "Closed by nightly stack-knowledge-audit."
            )
            if gh_cmd is None:
                continue
            rc = gh_issue_close(gh_cmd, loser["number"], msg, dry_run)
            if rc == 0:
                closed += 1
    print(f"dedup: closed {closed} duplicate issue(s)")
    return closed


def find_family_candidates(entries: list[tuple[str, dict]]) -> list[dict]:
    """Group by (stack_scope, root_cause_class); surface clusters >= FAMILY_CLUSTER_MIN."""
    groups: dict[tuple[str, str], list[tuple[str, dict]]] = {}
    for path, e in entries:
        ci = e.get("composite_identity") or {}
        stack_scope = str(ci.get("stack_scope") or "")
        root_cause_class = str(ci.get("root_cause_class") or "")
        if not stack_scope or not root_cause_class:
            continue
        key = (stack_scope, root_cause_class)
        groups.setdefault(key, []).append((path, e))

    out: list[dict] = []
    for (stack_scope, root_cause_class), members in groups.items():
        if len(members) >= FAMILY_CLUSTER_MIN:
            out.append({
                "stack_scope": stack_scope,
                "root_cause_class": root_cause_class,
                "children": [
                    {"source": p, "id": ent.get("id"), "hash": ent.get("composite_identity_hash")}
                    for p, ent in members
                ],
            })
    return out


def find_archive_candidates(entries: list[tuple[str, dict]], today: datetime) -> list[dict]:
    out: list[dict] = []
    for path, e in entries:
        ls = _parse_ymd(e.get("last_seen"))
        if ls is None:
            continue
        days_since = (today - ls).days
        occ = int(e.get("occurrence_count") or 0)
        conf = float(e.get("confidence_score") or 0.0)
        if (
            days_since > ARCHIVE_DAYS_SINCE_LAST_SEEN
            and occ <= ARCHIVE_MAX_OCCURRENCE
            and conf < ARCHIVE_MAX_CONFIDENCE
        ):
            out.append({
                "source": path,
                "id": e.get("id"),
                "hash": e.get("composite_identity_hash"),
                "days_since_last_seen": days_since,
                "occurrence_count": occ,
                "confidence_score": conf,
            })
    return out


def find_raw_to_stable_candidates(
    entries: list[tuple[str, dict]],
    history: list[dict],
    gh_cmd: str | None,
) -> list[dict]:
    out: list[dict] = []
    for path, e in entries:
        if e.get("maturity") != "raw":
            continue
        occ = int(e.get("occurrence_count") or 0)
        conf = float(e.get("confidence_score") or 0.0)
        if occ < RAW_TO_STABLE_MIN_OCCURRENCE or conf <= RAW_TO_STABLE_MIN_CONFIDENCE:
            continue
        if has_oscillation_for_entry(e, history, gh_cmd):
            continue
        out.append({
            "source": path,
            "id": e.get("id"),
            "hash": e.get("composite_identity_hash"),
            "occurrence_count": occ,
            "confidence_score": conf,
        })
    return out


def find_stable_to_canonical_candidates(
    entries: list[tuple[str, dict]],
    history: list[dict],
    gh_cmd: str | None,
    today: datetime,
) -> list[dict]:
    out: list[dict] = []
    for path, e in entries:
        if e.get("maturity") != "stable":
            continue
        fs = _parse_ymd(e.get("first_seen"))
        if fs is None:
            continue
        days = (today - fs).days
        if days < STABLE_TO_CANONICAL_MIN_DAYS:
            continue
        if has_oscillation_for_entry(e, history, gh_cmd):
            continue
        out.append({
            "source": path,
            "id": e.get("id"),
            "hash": e.get("composite_identity_hash"),
            "days_since_first_seen": days,
        })
    return out


def _issue_body_family(cand: dict) -> str:
    lines = [
        "## Family candidate — pattern cluster >= 5",
        "",
        f"**stack_scope**: `{cand['stack_scope']}`",
        f"**root_cause_class**: `{cand['root_cause_class']}`",
        f"**cluster size**: {len(cand['children'])}",
        "",
        "### Children",
        "",
    ]
    for c in cand["children"]:
        lines.append(f"- `{c['id']}` (hash `{c['hash']}`) — {c['source']}")
    lines.append("")
    lines.append(
        "Consider collapsing these into a single meta-rule (validator, hook, "
        "or CLAUDE.md rule) via `/resolve`. Once collapsed, the individual "
        "Stack Knowledge entries become redundant and can graduate."
    )
    return "\n".join(lines)


def _issue_body_archive(cand: dict) -> str:
    return (
        "## Archive candidate — entry is stale\n\n"
        f"**id**: `{cand['id']}`\n"
        f"**hash**: `{cand['hash']}`\n"
        f"**source**: {cand['source']}\n\n"
        f"- days_since_last_seen: {cand['days_since_last_seen']} (> {ARCHIVE_DAYS_SINCE_LAST_SEEN})\n"
        f"- occurrence_count: {cand['occurrence_count']} (<= {ARCHIVE_MAX_OCCURRENCE})\n"
        f"- confidence_score: {cand['confidence_score']} (< {ARCHIVE_MAX_CONFIDENCE})\n\n"
        "To archive: rename the file to `*.archive.md` or move the entry to an "
        "archive-suffixed file. Archived entries are skipped by all skill readers."
    )


def _issue_body_graduation_stable(cand: dict) -> str:
    return (
        "## Graduation candidate — raw → stable\n\n"
        f"**id**: `{cand['id']}`\n"
        f"**hash**: `{cand['hash']}`\n"
        f"**source**: {cand['source']}\n\n"
        f"- occurrence_count: {cand['occurrence_count']} (>= {RAW_TO_STABLE_MIN_OCCURRENCE})\n"
        f"- confidence_score: {cand['confidence_score']} (> {RAW_TO_STABLE_MIN_CONFIDENCE})\n"
        f"- no oscillation in last {OSCILLATION_WINDOW_DAYS} days\n\n"
        "Promoting to `stable` makes this entry active during /change and /bootstrap. "
        "Use `/resolve` to update the `maturity` field."
    )


def _issue_body_graduation_canonical(cand: dict) -> str:
    return (
        "## Graduation candidate — stable → canonical\n\n"
        f"**id**: `{cand['id']}`\n"
        f"**hash**: `{cand['hash']}`\n"
        f"**source**: {cand['source']}\n\n"
        f"- days_since_first_seen: {cand['days_since_first_seen']} (>= {STABLE_TO_CANONICAL_MIN_DAYS})\n"
        f"- no oscillation in last {OSCILLATION_WINDOW_DAYS} days\n\n"
        "Promoting to `canonical` makes this entry a hard constraint for /change. "
        "Consider whether it should also graduate to a validator/hook/rule via a "
        "graduation PR (enforced atomically by `stack-knowledge-graduation.yml`)."
    )


def run_audit(gh_cmd: str | None, dry_run: bool) -> int:
    entries = load_all_entries()
    history = load_convergence_history()
    today = _today_utc()

    # Idempotency: GitHub is the source of truth because .runs/ is gitignored
    # and absent on fresh CI checkouts. Local filed-state cache augments but
    # never replaces the GitHub-derived set.
    github_fingerprints = load_github_filed_fingerprints(gh_cmd)
    filed_state = load_filed_state()
    filed_set = set(filed_state.get("filed_hashes") or []) | github_fingerprints

    print(f"audit: {len(entries)} live entries scanned")
    print(f"audit: {len(github_fingerprints)} prior fingerprint(s) from GitHub; "
          f"{len(filed_set)} total dedup set")
    if history:
        print(f"audit: convergence-history.jsonl loaded ({len(history)} rows)")
    elif gh_cmd:
        print("audit: no convergence history; oscillation signal from gh fallback")
    else:
        print("audit: no oscillation signal available; skipping maturity promotions")

    to_file: list[tuple[str, str, list[str], str]] = []

    dedup_reconcile(gh_cmd, dry_run)

    for cand in find_family_candidates(entries):
        fp = _fingerprint("family", f"{cand['stack_scope']}|{cand['root_cause_class']}")
        if fp in filed_set:
            continue
        title = (
            f"[audit] pattern-family-candidate: {cand['root_cause_class']} "
            f"in {cand['stack_scope']} (x{len(cand['children'])})"
        )
        to_file.append((title, _issue_body_family(cand), ["pattern-family-candidate"], fp))

    for cand in find_archive_candidates(entries, today):
        fp = _fingerprint("archive", cand["hash"] or cand["id"] or "")
        if fp in filed_set:
            continue
        title = f"[audit] pattern-archive-candidate: {cand['id']}"
        to_file.append((title, _issue_body_archive(cand), ["pattern-archive-candidate"], fp))

    if oscillation_signal_available(history, gh_cmd):
        for cand in find_raw_to_stable_candidates(entries, history, gh_cmd):
            fp = _fingerprint("graduation-stable", cand["hash"] or cand["id"] or "")
            if fp in filed_set:
                continue
            title = f"[audit] pattern-graduation-stable: {cand['id']}"
            to_file.append((
                title, _issue_body_graduation_stable(cand),
                ["pattern-graduation-stable"], fp,
            ))

        for cand in find_stable_to_canonical_candidates(entries, history, gh_cmd, today):
            fp = _fingerprint("graduation-canonical", cand["hash"] or cand["id"] or "")
            if fp in filed_set:
                continue
            title = f"[audit] pattern-graduation-canonical: {cand['id']}"
            to_file.append((
                title, _issue_body_graduation_canonical(cand),
                ["pattern-graduation-canonical"], fp,
            ))

    filed_count = 0
    for title, body, labels, fp in to_file:
        if gh_cmd is None and not dry_run:
            print(f"skip (no gh): {title}")
            continue
        body_with_fp = _render_body_with_fingerprint(body, fp)
        rc = gh_issue_create(gh_cmd or "gh", title, body_with_fp, labels, dry_run)
        if rc == 0:
            filed_set.add(fp)
            filed_count += 1

    filed_state["filed_hashes"] = sorted(filed_set)
    filed_state["last_run"] = datetime.now(timezone.utc).isoformat()
    save_filed_state(filed_state)

    print(f"audit: filed {filed_count} new issue(s); state saved to {FILED_STATE_PATH}")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    p.add_argument("--dry-run", action="store_true", help="Log what would be filed without calling gh.")
    p.add_argument("--no-gh", action="store_true", help="Do not call gh at all (offline mode).")
    args = p.parse_args(argv[1:])

    gh_cmd: str | None = None
    if not args.no_gh:
        gh_cmd = shutil.which("gh")
        if gh_cmd is None:
            print("WARN: gh CLI not found in PATH; running in gh-less mode", file=sys.stderr)
    return run_audit(gh_cmd, args.dry_run)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
