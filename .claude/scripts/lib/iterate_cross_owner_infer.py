#!/usr/bin/env python3
"""iterate_cross_owner_infer.py — Owner-backfill proposals from repo commit history for /iterate --cross x4.

Subcommands:
  propose    Read config → for each mvp_mappings row missing `owner` (plus, with
             --scores, each score-row MVP that has no mapping row at all — the
             ga_only class x2 never births a row for), resolve the MVP's GitHub
             repo (magpiexyz-lab), fetch commit history via `gh api`, infer the
             owner (first-commit author > majority author; operator + bots
             excluded; roster login/alias/email matching; departed members
             remap to the operator), and write a proposals JSON for the x4
             confirm flow. Proposals only — persistence happens exclusively via
             `iterate_cross_classify.py persist-owner --confirm` (which creates
             the mapping row when absent).

Why a helper script (not inline state-file Python):

1. Identity exclusion is a code guard, not an LLM instruction. The operator's org
   account is the sole author in some MVP repo histories (config owner_note
   evidence: "repo history shows only org account") — a prose rule would
   eventually attribute those repos to the operator.
2. Confidence classification and roster alias matching are pure functions with
   real edge cases (ties, truncated history, departed members) — they belong
   under unit tests.
3. Repo resolution reuses iterate_cross_pricing (resolve_repo_layered /
   list_org_repo_records / load_or_refresh_name_index / _gh) per the README
   Stack Knowledge entry `iterate-cross-github-repo-fetch`; this module adds
   only the commits endpoint on the same mockable transport, plus the optional
   Vercel channel (iterate_cross_vercel) for repos outside the org: project
   link → cross-org repo slug, and the production deploy author as a direct
   owner signal when the repo itself is unreachable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from iterate_cross_classify import load_yaml  # noqa: E402
import iterate_cross_pricing as pricing  # noqa: E402
import iterate_cross_vercel as vercel  # noqa: E402
from iterate_cross_pricing import GH_ORG  # noqa: E402


DEFAULT_OWNER = "alan"  # operator inherits unowned items (mirrors iterate_cross_teardown)
OPERATOR_LOGINS = {"magpiexyz", "alanmagpie", "alan"}
OPERATOR_EMAILS = {
    "alan@magpiexyz.io",
    "admin@magpiexyz.io",
    "noreply@github.com",
    "105221001+magpiexyz@users.noreply.github.com",
    "105267417+alanmagpie@users.noreply.github.com",
}
PER_PAGE = 100
DEFAULT_MAX_PAGES = 10
DEFAULT_OUTPUT = ".runs/_iterate-cross-owner-proposals.json"


# ---------- pure helpers (unit-testable, no I/O) ----------

def _lc(value: str | None) -> str:
    return (value or "").strip().lower()


def build_roster_index(roster: dict) -> dict:
    """Index team_roster for author matching: {"logins": {lc: member}, "emails": {lc: member}}.

    Departed members ARE indexed — their commits must map so the departed
    remap (not the unmapped bucket) handles them.
    """
    logins: dict = {}
    emails: dict = {}
    for member, info in (roster or {}).items():
        if member == "_meta" or not isinstance(info, dict):
            continue
        if info.get("github"):
            logins[_lc(str(info["github"]))] = member
        for alias in info.get("github_aliases") or []:
            if alias:
                logins[_lc(str(alias))] = member
        if info.get("email"):
            emails[_lc(str(info["email"]))] = member
    return {"logins": logins, "emails": emails}


def is_excluded_identity(login: str | None, email: str | None, name: str | None = None) -> bool:
    """True for operator accounts and bots — their commits carry no ownership signal."""
    if _lc(login) in OPERATOR_LOGINS or _lc(email) in OPERATOR_EMAILS:
        return True
    for ident in (login, name):
        if _lc(ident).endswith("[bot]"):
            return True
    return False


def map_author(login: str | None, email: str | None, idx: dict) -> str | None:
    """Roster member for a commit identity: login lookup first, then email."""
    member = idx["logins"].get(_lc(login)) if login else None
    if member:
        return member
    if email:
        return idx["emails"].get(_lc(email))
    return None


def analyze_commits(commits: list[dict], idx: dict, history_complete: bool) -> dict:
    """Aggregate a newest-first commit list into ownership signals.

    Returns {first_author, counts, first_dates, total, excluded, unmapped_authors,
    history_complete}. `first_author` (oldest mapped commit author) is only
    trusted when the full history was fetched AND the oldest commit maps.
    """
    counts: dict = {}
    first_dates: dict = {}  # member -> earliest commit date seen (for tie-breaks)
    unmapped: dict = {}
    excluded = 0
    for c in commits:
        login, email, name = c.get("login"), c.get("email"), c.get("name")
        if is_excluded_identity(login, email, name):
            excluded += 1
            continue
        member = map_author(login, email, idx)
        if member is None:
            key = _lc(login) or _lc(email) or _lc(name) or "unknown"
            row = unmapped.setdefault(key, {"login": login, "email": email, "commits": 0})
            row["commits"] += 1
            continue
        counts[member] = counts.get(member, 0) + 1
        date = c.get("date") or ""
        if member not in first_dates or (date and date < first_dates[member]):
            first_dates[member] = date

    first_author = None
    if history_complete and commits:
        oldest = commits[-1]
        if not is_excluded_identity(oldest.get("login"), oldest.get("email"), oldest.get("name")):
            first_author = map_author(oldest.get("login"), oldest.get("email"), idx)

    return {
        "first_author": first_author,
        "counts": counts,
        "first_dates": first_dates,
        "total": len(commits),
        "excluded": excluded,
        "unmapped_authors": sorted(unmapped.values(), key=lambda r: -r["commits"]),
        "history_complete": history_complete,
    }


def classify_confidence(
    first_author: str | None,
    counts: dict,
    first_dates: dict | None = None,
) -> tuple[str | None, str | None, str | None]:
    """(owner, confidence, runner_up) from the two signals.

    first == majority          → high
    both present, disagree     → (first, medium, majority)   # first-commit signal wins
    one signal only            → (that owner, medium, next-ranked)
    tie without first signal   → (earliest-commit tie-break, low, other)
    no signal at all           → (None, None, None)
    """
    first_dates = first_dates or {}
    ranked = sorted(counts, key=lambda m: (-counts[m], first_dates.get(m) or "9999", m))
    majority = None
    if ranked and (len(ranked) == 1 or counts[ranked[0]] > counts[ranked[1]]):
        majority = ranked[0]
    runner_up = ranked[1] if len(ranked) >= 2 else None

    if not ranked and not first_author:
        return None, None, None
    if first_author and majority:
        if first_author == majority:
            return first_author, "high", None
        return first_author, "medium", majority
    if first_author:  # counts tied or empty — first-commit signal decides
        alt = next((m for m in ranked if m != first_author), None)
        return first_author, "medium", alt
    if majority:
        return majority, "medium", runner_up
    return ranked[0], "low", runner_up


def apply_departed_remap(owner: str, roster: dict) -> tuple[str, str | None]:
    """Departed member → (DEFAULT_OWNER, original); active member → (owner, None)."""
    info = (roster or {}).get(owner)
    if isinstance(info, dict) and info.get("status") == "departed":
        return DEFAULT_OWNER, owner
    return owner, None


def _signal_desc(first_author: str | None, owner: str, confidence: str) -> str:
    if confidence == "high":
        return "first+majority"
    if first_author == owner and first_author is not None:
        return "first-commit"
    return "majority"


def owner_note_text(
    repo: str | None,
    confidence: str,
    today: str,
    first_author: str | None = None,
    owner: str | None = None,
    inferred_original: str | None = None,
    fallback_reason: str | None = None,
) -> str:
    """Provenance prose for mvp_mappings.<name>.owner_note (mirrors existing precedents)."""
    if fallback_reason:
        return f"defaulted to operator ({fallback_reason}, {today})"
    if inferred_original:
        return (
            f"inferred {inferred_original} from {repo} commit history "
            f"({confidence} confidence, {today}); reassigned to {DEFAULT_OWNER} (departed)"
        )
    desc = _signal_desc(first_author, owner or "", confidence)
    return f"inferred from {repo} commit history ({desc}, {confidence} confidence, {today})"


def select_targets(
    mappings: dict,
    only: list[str] | None = None,
    limit: int | None = None,
    score_names: list[str] | None = None,
) -> list[dict]:
    """Rows to run inference on.

    Default: real (non-__orphan_) rows missing a truthy `owner`, sorted by name.
    `score_names` widens the domain beyond config: score-row MVP names with NO
    mapping row at all (ga_only auto-creates — zero PostHog events means x2
    never births their row) become targets too; persist_owner_updates already
    creates the new row on confirm. Without this, an unmapped MVP is
    structurally unreachable by owner inference (the echo class).
    --only: exactly those names even when owned (validation_only rows) — enables
    smoke-testing inference against MVPs whose owner is already known. A name
    with no mapping row is a plain target (not skipped): the row is born at
    persist time.
    """
    rows = []
    if only:
        for name in only:
            entry = mappings.get(name)
            row = {"name": name}
            if isinstance(entry, dict) and entry.get("owner"):
                row["validation_only"] = True
                row["current_owner"] = entry["owner"]
            rows.append(row)
    else:
        for name in sorted(mappings):
            entry = mappings.get(name)
            if name.startswith("__orphan_") or not isinstance(entry, dict):
                continue
            if entry.get("owner"):
                continue
            rows.append({"name": name})
        for name in sorted({n for n in (score_names or []) if n}):
            if name.startswith("__orphan_") or name in mappings:
                continue
            rows.append({"name": name})
    if limit is not None:
        rows = rows[:limit]
    return rows


# ---------- gh I/O (transport via pricing._gh — single mock surface) ----------

_COMMITS_JQ = "[.[] | {login: .author.login, email: .commit.author.email, name: .commit.author.name, date: .commit.author.date}]"


def fetch_commit_page(
    repo: str, page: int, org: str = GH_ORG, per_page: int = PER_PAGE
) -> tuple[list[dict] | None, str]:
    """One page of commits (newest-first). (rows, "") on success; (None, reason) on error.

    `repo` may be a bare org-repo name or a full `owner/repo` slug (repos outside
    the org, resolved via the Vercel link channel)."""
    slug = repo if "/" in repo else f"{org}/{repo}"
    rc, out, err = pricing._gh(
        ["api", f"repos/{slug}/commits?per_page={per_page}&page={page}", "--jq", _COMMITS_JQ],
        timeout=60,
    )
    if rc != 0:
        return None, err or "gh_error"
    try:
        rows = json.loads(out or "[]")
        if not isinstance(rows, list):
            return None, "parse_error"
        return rows, ""
    except ValueError:
        return None, "parse_error"


def fetch_commits(
    repo: str, org: str = GH_ORG, max_pages: int = DEFAULT_MAX_PAGES
) -> tuple[list[dict], bool, str | None]:
    """All commits up to max_pages. Returns (commits newest-first, history_complete, error_reason).

    error_reason is set only when page 1 fails: no_commits (empty repo),
    repo_deleted (404), or fetch_error. Later-page failures return the partial
    list with history_complete=False. Never raises.
    """
    commits: list[dict] = []
    for page in range(1, max_pages + 1):
        rows, err = fetch_commit_page(repo, page, org=org)
        if rows is None:
            if page == 1:
                low = err.lower()
                if "409" in low or "empty" in low:
                    return [], True, "no_commits"
                if "404" in low or "not found" in low:
                    return [], True, "repo_deleted"
                return [], True, "fetch_error"
            return commits, False, None
        commits.extend(rows)
        if len(rows) < PER_PAGE:
            return commits, True, None
    return commits, False, None


# ---------- Subcommand: propose ----------

def _fallback_row(name: str, repo: str | None, reason: str, today: str) -> dict:
    return {
        "name": name,
        "owner": DEFAULT_OWNER,
        "confidence": "fallback",
        "fallback_reason": reason,
        "repo": repo,
        "owner_note": owner_note_text(repo, "fallback", today, fallback_reason=reason),
    }


def vercel_author_row(
    name: str,
    project: dict,
    meta: dict,
    idx: dict,
    roster: dict,
    today: str,
) -> dict | str | None:
    """Owner row from a Vercel production-deploy author (direct signal).

    Returns the proposal row when the author maps to a roster member; the raw
    login string when it does NOT map (caller routes to needs_roster); None when
    the deployment carries no authorship at all.
    """
    login = (meta or {}).get("commit_author_login") or (meta or {}).get("creator_username")
    if not login:
        return None
    member = map_author(login, None, idx)
    if member is None:
        return str(login)
    owner, inferred_original = apply_departed_remap(member, roster)
    note = (
        f"inferred {inferred_original or owner} from Vercel production deploy author @{login} "
        f"(project {project.get('name')}, medium confidence, {today})"
    )
    if inferred_original:
        note += f"; reassigned to {DEFAULT_OWNER} (departed)"
    return {
        "name": name,
        "owner": owner,
        "confidence": "medium",
        "repo": project.get("repo_slug"),
        "runner_up": None,
        "inferred_original": inferred_original,
        "owner_note": note,
        "evidence": {
            "resolution_method": "vercel-deploy-author",
            "vercel_project": project.get("name"),
            "vercel_deploy": dict(meta or {}),
        },
    }


def _load_score_names(scores_path: str | None) -> list[str]:
    """MVP names from a scores/data artifact (optional --scores input).

    Defensive read: absent path / unreadable file / unexpected shape all
    degrade to [] — the scores channel only ever widens the target set.
    """
    if not scores_path or not os.path.exists(scores_path):
        return []
    try:
        doc = json.load(open(scores_path))
    except Exception:
        return []
    rows = doc.get("mvps") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        return []
    return [r.get("name") for r in rows if isinstance(r, dict) and r.get("name")]


def cmd_propose(args) -> int:
    config = load_yaml(args.config)
    mappings = config.get("mvp_mappings") or {}
    roster = config.get("team_roster") or {}
    repo_aliases = config.get("repo_aliases") or {}
    score_names = _load_score_names(getattr(args, "scores", None))
    targets = select_targets(
        mappings, only=args.only, limit=args.limit, score_names=score_names
    )
    now = args.now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    today = now[:10]

    result = {
        "generated_at": now,
        "gh_unavailable": False,
        "target_count": len(targets),
        "updates": [],
        "needs_roster": [],
        "unmapped_authors": [],
    }

    if not pricing.gh_available():
        result["gh_unavailable"] = True
        result["reason"] = "gh auth unavailable"
        json.dump(result, open(args.output, "w"), indent=2)
        print("owner-propose: gh unavailable — wrote empty proposals (0 updates)")
        return 0

    records = pricing.list_org_repo_records()
    name_index = pricing.load_or_refresh_name_index(records) if records else {}
    vc_token = vercel.vercel_token()
    vc_projects = vercel.list_projects(vc_token) if vc_token else []
    result["vercel_channel"] = bool(vc_token)
    idx = build_roster_index(roster)
    rollup: dict = {}  # identity key -> {login, email, commits, repos}
    tallies = {"high": 0, "medium": 0, "low": 0, "fallback": 0}

    def _try_vercel_author(name: str, project: dict, meta: dict) -> bool:
        """Append a deploy-author proposal (or needs_roster entry). True when handled."""
        row = vercel_author_row(name, project, meta, idx, roster, today)
        if isinstance(row, dict):
            result["updates"].append(row)
            tallies["medium"] += 1
            return True
        if isinstance(row, str):
            result["needs_roster"].append({
                "name": name,
                "repo": project.get("repo_slug"),
                "unmapped_authors": [{"login": row, "email": None, "commits": 1}],
                "note": "Vercel deploy author not in team_roster — add github/github_aliases, then re-run propose",
            })
            return True
        return False

    for target in targets:
        name = target["name"]
        repo, method = pricing.resolve_repo_layered(
            name, records, mappings, repo_aliases, name_index
        )
        vc_project = None
        vc_meta: dict = {}
        if repo is None and vc_projects:
            vc_project = vercel.resolve_project(name, vc_projects)
            if vc_project:
                vc_meta = vercel.production_deploy_meta(
                    vc_token, vc_project.get("id"), vc_project.get("team_id")
                )
                if vc_project.get("repo_slug"):
                    repo, method = vc_project["repo_slug"], "vercel-link"

        if repo is None:
            if vc_project and _try_vercel_author(name, vc_project, vc_meta):
                continue
            reason = "vercel_project_unlinked" if vc_project else "repo_unresolved"
            result["updates"].append(_fallback_row(name, None, reason, today))
            tallies["fallback"] += 1
            continue

        commits, complete, err = fetch_commits(repo, max_pages=args.max_pages)
        if err is not None:
            # An outside-org slug can 404 for gh (private personal repo) even
            # though Vercel proved the deploy exists — fall back to the deploy
            # author before giving up on a real owner.
            if vc_project and _try_vercel_author(name, vc_project, vc_meta):
                continue
            result["updates"].append(_fallback_row(name, repo, err, today))
            tallies["fallback"] += 1
            continue

        analysis = analyze_commits(commits, idx, complete)
        for row in analysis["unmapped_authors"]:
            key = _lc(row.get("login")) or _lc(row.get("email")) or "unknown"
            agg = rollup.setdefault(
                key, {"login": row.get("login"), "email": row.get("email"), "commits": 0, "repos": []}
            )
            agg["commits"] += row["commits"]
            if repo not in agg["repos"]:
                agg["repos"].append(repo)

        owner, confidence, runner_up = classify_confidence(
            analysis["first_author"], analysis["counts"], analysis["first_dates"]
        )
        if owner is None:
            if analysis["unmapped_authors"]:
                result["needs_roster"].append({
                    "name": name,
                    "repo": repo,
                    "unmapped_authors": analysis["unmapped_authors"],
                    "note": "add github_aliases/email to team_roster, then re-run propose",
                })
            else:
                result["updates"].append(_fallback_row(name, repo, "no_teammate_history", today))
                tallies["fallback"] += 1
            continue

        owner, inferred_original = apply_departed_remap(owner, roster)
        oldest = commits[-1] if commits else {}
        row = {
            "name": name,
            "owner": owner,
            "confidence": confidence,
            "repo": repo,
            "runner_up": runner_up,
            "inferred_original": inferred_original,
            "owner_note": owner_note_text(
                repo, confidence, today,
                first_author=analysis["first_author"],
                owner=inferred_original or owner,
                inferred_original=inferred_original,
            ),
            "evidence": {
                "resolution_method": method,
                "first_commit_author": {
                    "login": oldest.get("login"),
                    "date": oldest.get("date"),
                    "mapped": analysis["first_author"],
                } if commits else None,
                "commit_counts": analysis["counts"],
                "total_commits": analysis["total"],
                "excluded_commits": analysis["excluded"],
                "history_complete": analysis["history_complete"],
                "unmapped_authors": analysis["unmapped_authors"],
            },
        }
        if target.get("validation_only"):
            row["validation_only"] = True
            row["current_owner"] = target.get("current_owner")
        result["updates"].append(row)
        tallies[confidence] += 1

    result["unmapped_authors"] = sorted(rollup.values(), key=lambda r: -r["commits"])
    json.dump(result, open(args.output, "w"), indent=2)

    inferred = tallies["high"] + tallies["medium"] + tallies["low"]
    print(
        f"owner-propose: {len(targets)} targets → {inferred} inferred "
        f"({tallies['high']} high / {tallies['medium']} medium / {tallies['low']} low), "
        f"{tallies['fallback']} fallback→{DEFAULT_OWNER}, {len(result['needs_roster'])} need roster"
    )
    return 0


# ---------- CLI ----------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_prop = sub.add_parser(
        "propose",
        help="Infer owners for mvp_mappings rows missing `owner`; write proposals JSON.",
    )
    p_prop.add_argument("--config", default="experiment/iterate-cross-config.yaml")
    p_prop.add_argument("--output", default=DEFAULT_OUTPUT)
    p_prop.add_argument("--only", action="append", default=None,
                        help="Restrict to this MVP name (repeatable; owned rows become validation_only; "
                             "a name with no mapping row is a plain target — the row is born at persist).")
    p_prop.add_argument("--scores", default=None,
                        help="Optional scores/data JSON; score-row names with no mapping row "
                             "(ga_only auto-creates) join the target set.")
    p_prop.add_argument("--limit", type=int, default=None)
    p_prop.add_argument("--max-pages", dest="max_pages", type=int, default=DEFAULT_MAX_PAGES,
                        help=f"Commit pages per repo, {PER_PAGE}/page (default {DEFAULT_MAX_PAGES}).")
    p_prop.add_argument("--now", default=None, help="ISO timestamp override (tests).")
    p_prop.set_defaults(func=cmd_propose)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
