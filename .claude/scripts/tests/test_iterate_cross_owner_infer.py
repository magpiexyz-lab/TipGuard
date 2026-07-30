#!/usr/bin/env python3
"""Tests for .claude/scripts/lib/iterate_cross_owner_infer.py (x4 owner backfill).

Run:
  python3 -m pytest .claude/scripts/tests/test_iterate_cross_owner_infer.py -v
  # OR (no pytest dependency):
  python3 .claude/scripts/tests/test_iterate_cross_owner_infer.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

# Direct-run isolation (pytest gets the same via conftest.py): keep the gh
# name-index cache out of the production .runs/ artifact.
os.environ.setdefault(
    "ITERATE_CROSS_NAME_INDEX_CACHE",
    os.path.join(tempfile.gettempdir(), "gh-name-index-test.json"),
)

import iterate_cross_owner_infer as O  # noqa: E402
import iterate_cross_pricing as P  # noqa: E402
import iterate_cross_vercel as V  # noqa: E402


ROSTER = {
    "_meta": {"note": "test roster"},
    "radlin": {"tg": "@Radlin_BD", "github": "Radz112", "email": "radlin@magpiexyz.io"},
    "lee": {"tg": "@Kol520", "github": "balflee", "email": "lee@magpiexyz.io",
            "github_aliases": ["balflee", "balflearlee"]},
    "lego": {"github": "LEGO-BP", "email": None},
    "priyanshu": {"github": "pcentric", "email": None, "status": "departed"},
    "parth": {"github": "parthmagpie", "email": None, "status": "departed"},
    "alan": {"github": "alanmagpie", "email": "alan@magpiexyz.io", "note": "operator"},
}

IDX = O.build_roster_index(ROSTER)


def _c(login, email=None, name=None, date="2026-01-01T00:00:00Z"):
    return {"login": login, "email": email, "name": name, "date": date}


def _fake_gh(repos=(), commit_pages=None, auth_rc=0):
    """commit_pages: {repo: [page1_rows, page2_rows, ...]} (newest-first overall).

    Unknown repo → 404. Empty-list-of-pages repo → HTTP 409 empty-repo error.
    """
    commit_pages = commit_pages or {}

    def gh(args, timeout=30):
        if args[:2] == ["auth", "status"]:
            return auth_rc, "", "" if auth_rc == 0 else "not logged in"
        if args[:2] == ["repo", "list"]:
            return 0, json.dumps([{"name": r} for r in repos]), ""
        if args and args[0] == "api" and "/commits?" in args[1]:
            endpoint = args[1]  # repos/ORG/REPO/commits?per_page=N&page=M
            repo = endpoint.split("/")[2]
            if repo not in commit_pages:
                return 1, "", "gh: Not Found (HTTP 404)"
            pages = commit_pages[repo]
            if pages == []:
                return 1, "", "HTTP 409: Git Repository is empty"
            page = int(endpoint.split("page=")[-1])
            rows = pages[page - 1] if page <= len(pages) else []
            return 0, json.dumps(rows), ""
        return 1, "", "unknown"
    return gh


# ---------- pure helpers ----------

def test_roster_index_logins_aliases_emails():
    assert O.map_author("radz112", None, IDX) == "radlin"          # case-insensitive login
    assert O.map_author("BALFLEE", None, IDX) == "lee"             # github + alias
    assert O.map_author("balflearlee", None, IDX) == "lee"         # second alias
    assert O.map_author(None, "Lee@magpiexyz.io", IDX) == "lee"    # email, case-insensitive
    assert O.map_author("pcentric", None, IDX) == "priyanshu"      # departed IS indexed
    assert "_meta" not in IDX["logins"].values()
    assert O.map_author("someone-else", None, IDX) is None


def test_excluded_identities():
    assert O.is_excluded_identity("magpiexyz", None) is True
    assert O.is_excluded_identity("AlanMagpie", None) is True
    assert O.is_excluded_identity(None, "admin@magpiexyz.io") is True
    assert O.is_excluded_identity(None, "105221001+magpiexyz@users.noreply.github.com") is True
    assert O.is_excluded_identity(None, "105267417+alanmagpie@users.noreply.github.com") is True
    assert O.is_excluded_identity(None, "noreply@github.com") is True
    assert O.is_excluded_identity("dependabot[bot]", None) is True
    assert O.is_excluded_identity(None, None, "github-actions[bot]") is True
    assert O.is_excluded_identity("Radz112", "radlin@magpiexyz.io") is False


def test_map_author_login_precedence_over_email():
    assert O.map_author("Radz112", "lee@magpiexyz.io", IDX) == "radlin"
    assert O.map_author(None, "lee@magpiexyz.io", IDX) == "lee"
    assert O.map_author("nobody", "nobody@x.io", IDX) is None


def test_confidence_high_first_equals_majority():
    owner, conf, runner = O.classify_confidence("radlin", {"radlin": 5, "lee": 1})
    assert (owner, conf, runner) == ("radlin", "high", None)


def test_confidence_medium_disagreement_first_wins():
    owner, conf, runner = O.classify_confidence("lee", {"radlin": 5, "lee": 2})
    assert (owner, conf, runner) == ("lee", "medium", "radlin")


def test_confidence_medium_single_signal():
    # (a) majority only (first commit unmapped/truncated)
    owner, conf, runner = O.classify_confidence(None, {"radlin": 5, "lee": 1})
    assert (owner, conf, runner) == ("radlin", "medium", "lee")
    # (b) first signal with tied counts
    owner, conf, runner = O.classify_confidence("lee", {"radlin": 3, "lee": 3})
    assert owner == "lee" and conf == "medium" and runner == "radlin"


def test_confidence_low_tie_without_first():
    owner, conf, runner = O.classify_confidence(
        None, {"radlin": 3, "lee": 3},
        first_dates={"lee": "2026-01-01", "radlin": "2026-02-01"},
    )
    assert (owner, conf, runner) == ("lee", "low", "radlin")  # earliest commit breaks tie


def test_analyze_commits_first_author_needs_complete_history():
    commits = [_c("Radz112"), _c("balflee", date="2025-12-01T00:00:00Z")]
    full = O.analyze_commits(commits, IDX, history_complete=True)
    assert full["first_author"] == "lee"  # oldest = last element
    truncated = O.analyze_commits(commits, IDX, history_complete=False)
    assert truncated["first_author"] is None
    assert truncated["counts"] == {"radlin": 1, "lee": 1}


# ---------- gh I/O (mocked transport) ----------

def test_fetch_commits_pagination_complete_and_truncated():
    page1 = [_c("Radz112", date=f"2026-06-{28 - i % 27:02d}T00:00:00Z") for i in range(100)]
    page2 = [_c("balflee", date="2025-01-01T00:00:00Z")] * 40
    fake = _fake_gh(repos=("app",), commit_pages={"app": [page1, page2]})
    with patch.object(P, "_gh", fake):
        commits, complete, err = O.fetch_commits("app")
        assert err is None and complete is True and len(commits) == 140
        assert commits[-1]["login"] == "balflee"  # oldest = last
        commits, complete, err = O.fetch_commits("app", max_pages=1)
        assert err is None and complete is False and len(commits) == 100


def test_fetch_commits_empty_and_deleted_repo():
    fake = _fake_gh(repos=("empty",), commit_pages={"empty": []})
    with patch.object(P, "_gh", fake):
        commits, complete, err = O.fetch_commits("empty")
        assert (commits, complete, err) == ([], True, "no_commits")
        commits, complete, err = O.fetch_commits("gone")
        assert (commits, complete, err) == ([], True, "repo_deleted")


# ---------- propose end-to-end ----------

def _write_cfg(td, mappings):
    try:
        import yaml
    except ImportError:
        return None
    cfg_p = os.path.join(td, "cfg.yaml")
    yaml.safe_dump({"mvp_mappings": mappings, "team_roster": ROSTER}, open(cfg_p, "w"))
    return cfg_p


def _run_propose(cfg_p, out_p, fake, extra=None, vercel_token=None, vercel_projects=None,
                 vercel_deploy_meta=None):
    """Propose with hermetic transports: gh via `fake`, Vercel patched off by
    default (token None) so tests never hit the real API even on machines with
    a ~/.vercel/api-token."""
    argv = ["propose", "--config", cfg_p, "--output", out_p, "--now", "2026-07-22T00:00:00Z"]
    argv += extra or []
    with patch.object(P, "_gh", fake), \
         patch.object(V, "vercel_token", lambda: vercel_token), \
         patch.object(V, "list_projects", lambda tok: list(vercel_projects or [])), \
         patch.object(V, "production_deploy_meta",
                      lambda tok, pid, team_id=None: dict(vercel_deploy_meta or {})):
        rc = O.main(argv)
    assert rc == 0
    return json.load(open(out_p))


def test_propose_end_to_end_schema():
    mappings = {
        "a-app": {"signup_events": []},                    # unowned, repo resolves
        "b-app": {"signup_events": []},                    # unowned, repo missing
        "c-app": {"signup_events": [], "owner": "lee"},    # owned → not a default target
        "__orphan_x": {"signup_events": []},               # orphan → never a target
    }
    fake = _fake_gh(
        repos=("a-app", "c-app"),
        commit_pages={
            "a-app": [[_c("Radz112", date="2026-03-01T00:00:00Z"),
                       _c("magpiexyz", date="2026-02-01T00:00:00Z"),
                       _c("Radz112", date="2026-01-01T00:00:00Z")]],
            "c-app": [[_c("balflee")]],
        },
    )
    with tempfile.TemporaryDirectory() as td:
        cfg_p = _write_cfg(td, mappings)
        if cfg_p is None:
            return
        out = _run_propose(cfg_p, os.path.join(td, "props.json"), fake)
        assert out["generated_at"] == "2026-07-22T00:00:00Z"
        assert out["gh_unavailable"] is False
        assert out["target_count"] == 2
        by_name = {u["name"]: u for u in out["updates"]}
        assert set(by_name) == {"a-app", "b-app"}
        a = by_name["a-app"]
        assert a["owner"] == "radlin" and a["confidence"] == "high"
        assert a["evidence"]["commit_counts"] == {"radlin": 2}
        assert a["evidence"]["excluded_commits"] == 1  # magpiexyz filtered
        assert a["evidence"]["history_complete"] is True
        assert "inferred from a-app commit history" in a["owner_note"]
        b = by_name["b-app"]
        assert b["owner"] == "alan" and b["confidence"] == "fallback"
        assert b["fallback_reason"] == "repo_unresolved"

        out = _run_propose(cfg_p, os.path.join(td, "p2.json"), fake, ["--limit", "1"])
        assert [u["name"] for u in out["updates"]] == ["a-app"]

        out = _run_propose(cfg_p, os.path.join(td, "p3.json"), fake, ["--only", "c-app"])
        row = out["updates"][0]
        assert row["validation_only"] is True
        assert row["current_owner"] == "lee"
        assert row["owner"] == "lee"  # inference agrees with the known owner


def test_departed_remap_sets_inferred_original():
    mappings = {"d-app": {"signup_events": []}}
    fake = _fake_gh(repos=("d-app",), commit_pages={"d-app": [[_c("pcentric"), _c("pcentric")]]})
    with tempfile.TemporaryDirectory() as td:
        cfg_p = _write_cfg(td, mappings)
        if cfg_p is None:
            return
        out = _run_propose(cfg_p, os.path.join(td, "props.json"), fake)
        row = out["updates"][0]
        assert row["owner"] == "alan"
        assert row["inferred_original"] == "priyanshu"
        assert "reassigned to alan (departed)" in row["owner_note"]


def test_select_targets_includes_score_names_without_mapping_row():
    """The echo class: a score-row MVP with NO mapping row becomes a target;
    orphans and already-mapped names never duplicate."""
    mappings = {
        "a-app": {"signup_events": []},                  # unowned mapping row → target
        "c-app": {"signup_events": [], "owner": "lee"},  # owned → not a target
    }
    rows = O.select_targets(
        mappings,
        score_names=["echo", "c-app", "a-app", "__orphan_x__", "", None],
    )
    assert [r["name"] for r in rows] == ["a-app", "echo"]
    # Without the scores channel, echo is structurally unreachable.
    assert [r["name"] for r in O.select_targets(mappings)] == ["a-app"]


def test_select_targets_only_accepts_name_without_mapping_row():
    """--only <name> with no mapping row is a plain target (the row is born at
    persist time), not silently skipped."""
    rows = O.select_targets({}, only=["echo"])
    assert rows == [{"name": "echo"}]


def test_propose_scores_channel_infers_departed_author_to_operator():
    """End-to-end echo shape: scores JSON supplies the unmapped name, repo
    'Echo' resolves via exact-name (match_key case-fold), commits by a
    departed member remap to the operator with inferred_original."""
    mappings = {"a-app": {"signup_events": [], "owner": "lee"}}  # no targets from config
    fake = _fake_gh(
        repos=("Echo", "a-app"),
        commit_pages={"Echo": [[_c("parthmagpie"), _c("parthmagpie")]]},
    )
    with tempfile.TemporaryDirectory() as td:
        cfg_p = _write_cfg(td, mappings)
        if cfg_p is None:
            return
        scores_p = os.path.join(td, "scores.json")
        json.dump(
            {"mvps": [
                {"name": "echo", "ga_only": True},
                {"name": "a-app"},
                {"name": "__orphan_deadhost__"},
            ]},
            open(scores_p, "w"),
        )
        out = _run_propose(
            cfg_p, os.path.join(td, "props.json"), fake, ["--scores", scores_p]
        )
        assert out["target_count"] == 1
        row = out["updates"][0]
        assert row["name"] == "echo"
        assert row["repo"] == "Echo"
        assert row["owner"] == "alan"
        assert row["inferred_original"] == "parth"
        assert "reassigned to alan (departed)" in row["owner_note"]


def test_propose_scores_missing_file_degrades_to_config_only():
    mappings = {"a-app": {"signup_events": []}}
    fake = _fake_gh(repos=("a-app",), commit_pages={"a-app": [[_c("Radz112")]]})
    with tempfile.TemporaryDirectory() as td:
        cfg_p = _write_cfg(td, mappings)
        if cfg_p is None:
            return
        out = _run_propose(
            cfg_p, os.path.join(td, "props.json"), fake,
            ["--scores", os.path.join(td, "absent.json")],
        )
        assert out["target_count"] == 1
        assert out["updates"][0]["name"] == "a-app"


def test_all_operator_history_falls_back():
    mappings = {"e-app": {"signup_events": []}}
    fake = _fake_gh(repos=("e-app",), commit_pages={"e-app": [[_c("magpiexyz"), _c("alanmagpie")]]})
    with tempfile.TemporaryDirectory() as td:
        cfg_p = _write_cfg(td, mappings)
        if cfg_p is None:
            return
        out = _run_propose(cfg_p, os.path.join(td, "props.json"), fake)
        row = out["updates"][0]
        assert row["owner"] == "alan" and row["confidence"] == "fallback"
        assert row["fallback_reason"] == "no_teammate_history"


def test_unmapped_authors_go_to_needs_roster():
    mappings = {"f-app": {"signup_events": []}}
    fake = _fake_gh(
        repos=("f-app",),
        commit_pages={"f-app": [[_c("someuser"), _c("someuser"), _c(None, "ghost@x.io")]]},
    )
    with tempfile.TemporaryDirectory() as td:
        cfg_p = _write_cfg(td, mappings)
        if cfg_p is None:
            return
        out = _run_propose(cfg_p, os.path.join(td, "props.json"), fake)
        assert out["updates"] == []
        assert len(out["needs_roster"]) == 1
        nr = out["needs_roster"][0]
        assert nr["name"] == "f-app"
        assert {a["login"] for a in nr["unmapped_authors"]} == {"someuser", None}
        assert nr["unmapped_authors"][0]["commits"] == 2
        rollup = {r.get("login") or r.get("email"): r for r in out["unmapped_authors"]}
        assert rollup["someuser"]["repos"] == ["f-app"]


def test_propose_gh_unavailable_degrades():
    mappings = {"g-app": {"signup_events": []}}
    fake = _fake_gh(auth_rc=1)
    with tempfile.TemporaryDirectory() as td:
        cfg_p = _write_cfg(td, mappings)
        if cfg_p is None:
            return
        out = _run_propose(cfg_p, os.path.join(td, "props.json"), fake)
        assert out["gh_unavailable"] is True
        assert out["updates"] == [] and out["needs_roster"] == []
        assert out["target_count"] == 1


# ---------- Vercel channel (repos outside the org) ----------

def test_vercel_link_resolves_outside_org_repo():
    """Org listing misses the repo; Vercel link supplies a cross-org slug whose
    commit history then drives normal inference."""
    mappings = {"tifa-x": {"signup_events": []}}
    fake = _fake_gh(
        repos=(),  # not in the org
        commit_pages={"tifa-x": [[_c("Radz112"), _c("Radz112")]]},  # keyed by slug basename
    )
    projects = [{"id": "p1", "name": "tifa-x", "team_id": None, "repo_slug": "someone/tifa-x"}]
    with tempfile.TemporaryDirectory() as td:
        cfg_p = _write_cfg(td, mappings)
        if cfg_p is None:
            return
        out = _run_propose(cfg_p, os.path.join(td, "props.json"), fake,
                           vercel_token="tok", vercel_projects=projects)
        assert out["vercel_channel"] is True
        row = out["updates"][0]
        assert row["owner"] == "radlin" and row["confidence"] == "high"
        assert row["repo"] == "someone/tifa-x"
        assert row["evidence"]["resolution_method"] == "vercel-link"


def test_vercel_deploy_author_direct_signal_when_repo_unreachable():
    """Linked repo 404s for gh (private personal repo) → the production deploy
    author becomes a direct medium-confidence owner signal."""
    mappings = {"ghost-app": {"signup_events": []}}
    fake = _fake_gh(repos=(), commit_pages={})  # slug fetch → 404
    projects = [{"id": "p2", "name": "ghost-app", "team_id": "t1", "repo_slug": "someone/ghost-app"}]
    meta = {"commit_author_login": "Radz112", "commit_ref": "main", "creator_username": None}
    with tempfile.TemporaryDirectory() as td:
        cfg_p = _write_cfg(td, mappings)
        if cfg_p is None:
            return
        out = _run_propose(cfg_p, os.path.join(td, "props.json"), fake,
                           vercel_token="tok", vercel_projects=projects, vercel_deploy_meta=meta)
        row = out["updates"][0]
        assert row["owner"] == "radlin" and row["confidence"] == "medium"
        assert row["evidence"]["resolution_method"] == "vercel-deploy-author"
        assert "Vercel production deploy author @Radz112" in row["owner_note"]


def test_vercel_deploy_author_departed_remaps():
    mappings = {"old-app": {"signup_events": []}}
    fake = _fake_gh(repos=(), commit_pages={})
    projects = [{"id": "p3", "name": "old-app", "team_id": None, "repo_slug": None}]
    meta = {"commit_author_login": "pcentric", "commit_ref": "main", "creator_username": None}
    with tempfile.TemporaryDirectory() as td:
        cfg_p = _write_cfg(td, mappings)
        if cfg_p is None:
            return
        out = _run_propose(cfg_p, os.path.join(td, "props.json"), fake,
                           vercel_token="tok", vercel_projects=projects, vercel_deploy_meta=meta)
        row = out["updates"][0]
        assert row["owner"] == "alan"
        assert row["inferred_original"] == "priyanshu"
        assert "reassigned to alan (departed)" in row["owner_note"]


def test_vercel_author_unmapped_goes_to_needs_roster():
    mappings = {"mystery-app": {"signup_events": []}}
    fake = _fake_gh(repos=(), commit_pages={})
    projects = [{"id": "p4", "name": "mystery-app", "team_id": None, "repo_slug": None}]
    meta = {"commit_author_login": "stranger-dev", "commit_ref": "main", "creator_username": None}
    with tempfile.TemporaryDirectory() as td:
        cfg_p = _write_cfg(td, mappings)
        if cfg_p is None:
            return
        out = _run_propose(cfg_p, os.path.join(td, "props.json"), fake,
                           vercel_token="tok", vercel_projects=projects, vercel_deploy_meta=meta)
        assert out["updates"] == []
        assert out["needs_roster"][0]["name"] == "mystery-app"
        assert out["needs_roster"][0]["unmapped_authors"][0]["login"] == "stranger-dev"


def test_vercel_project_without_signals_falls_back_unlinked():
    mappings = {"linkless-app": {"signup_events": []}}
    fake = _fake_gh(repos=(), commit_pages={})
    projects = [{"id": "p5", "name": "linkless-app", "team_id": None, "repo_slug": None}]
    with tempfile.TemporaryDirectory() as td:
        cfg_p = _write_cfg(td, mappings)
        if cfg_p is None:
            return
        out = _run_propose(cfg_p, os.path.join(td, "props.json"), fake,
                           vercel_token="tok", vercel_projects=projects,
                           vercel_deploy_meta={})
        row = out["updates"][0]
        assert row["confidence"] == "fallback"
        assert row["fallback_reason"] == "vercel_project_unlinked"


def test_no_vercel_token_keeps_plain_fallback():
    mappings = {"b-app": {"signup_events": []}}
    fake = _fake_gh(repos=())
    with tempfile.TemporaryDirectory() as td:
        cfg_p = _write_cfg(td, mappings)
        if cfg_p is None:
            return
        out = _run_propose(cfg_p, os.path.join(td, "props.json"), fake)
        assert out["vercel_channel"] is False
        row = out["updates"][0]
        assert row["fallback_reason"] == "repo_unresolved"


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
