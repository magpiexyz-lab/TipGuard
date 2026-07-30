#!/usr/bin/env python3
"""Tests for .claude/scripts/lib/iterate_cross_vercel.py (optional Vercel channel).

Run:
  python3 -m pytest .claude/scripts/tests/test_iterate_cross_vercel.py -v
  # OR (no pytest dependency):
  python3 .claude/scripts/tests/test_iterate_cross_vercel.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import iterate_cross_vercel as V  # noqa: E402


# ---------- token discovery ----------

def test_token_env_wins_over_file():
    with tempfile.TemporaryDirectory() as td:
        tok_file = os.path.join(td, "api-token")
        open(tok_file, "w").write("file-token\n")
        with patch.object(V, "TOKEN_PATH", tok_file):
            with patch.dict(os.environ, {"VERCEL_TOKEN": "env-token"}):
                assert V.vercel_token() == "env-token"
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("VERCEL_TOKEN", None)
                assert V.vercel_token() == "file-token"


def test_token_absent_returns_none():
    with tempfile.TemporaryDirectory() as td:
        # _cli_auth_token patched too: without it the chain would read the
        # developer machine's real Vercel CLI auth.json and flake.
        with patch.object(V, "TOKEN_PATH", os.path.join(td, "missing")), \
             patch.object(V, "_cli_auth_token", lambda: None):
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("VERCEL_TOKEN", None)
                assert V.vercel_token() is None


def test_token_falls_back_to_cli_auth():
    with tempfile.TemporaryDirectory() as td:
        with patch.object(V, "TOKEN_PATH", os.path.join(td, "missing")), \
             patch.object(V, "_cli_auth_token", lambda: "cli-token"):
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("VERCEL_TOKEN", None)
                assert V.vercel_token() == "cli-token"


# ---------- project listing (mocked _http_get) ----------

def _project(pid, name, org=None, repo=None, link_type="github"):
    p = {"id": pid, "name": name}
    if org and repo:
        p["link"] = {"type": link_type, "org": org, "repo": repo}
    return p


def test_list_projects_paginates_and_spans_teams():
    responses = {
        ("/v2/teams", None): {"teams": [{"id": "team_1"}]},
        # personal scope: two pages
        ("/v9/projects", None): {"projects": [_project("p1", "alpha", "someone", "alpha-repo")],
                                 "pagination": {"next": 111}},
        ("/v9/projects", 111): {"projects": [_project("p2", "beta")], "pagination": {"next": None}},
        # team scope: one page; non-github link ignored for slug
        ("/v9/projects", "team_1"): {"projects": [_project("p3", "gamma", "x", "y", link_type="gitlab")],
                                     "pagination": {}},
    }

    def http_get(path, token, params=None):
        params = params or {}
        if path == "/v2/teams":
            return responses[("/v2/teams", None)]
        key = params.get("until") or params.get("teamId")
        return responses.get((path, key))

    with patch.object(V, "_http_get", http_get):
        rows = V.list_projects("tok")
    by_id = {r["id"]: r for r in rows}
    assert set(by_id) == {"p1", "p2", "p3"}
    assert by_id["p1"]["repo_slug"] == "someone/alpha-repo"
    assert by_id["p2"]["repo_slug"] is None          # no link
    assert by_id["p3"]["repo_slug"] is None          # non-github link
    assert by_id["p3"]["team_id"] == "team_1"


def test_list_projects_transport_failure_degrades_empty():
    with patch.object(V, "_http_get", lambda *a, **k: None):
        assert V.list_projects("tok") == []


# ---------- project matching ----------

def test_resolve_project_exact_host_and_containment():
    projects = [
        {"id": "p1", "name": "tifa-x", "team_id": None, "repo_slug": None},
        {"id": "p2", "name": "income-flow-three", "team_id": None, "repo_slug": None},
        {"id": "p3", "name": "agentshield-live", "team_id": None, "repo_slug": None},
    ]
    # exact key match (hyphen-insensitive)
    assert V.resolve_project("tifa-x", projects)["id"] == "p1"
    # deploy-host key match
    assert V.resolve_project("income-flow", projects,
                             deploy_host="income-flow-three.vercel.app")["id"] == "p2"
    # guarded containment (>= 6 chars both sides)
    assert V.resolve_project("agentshield", projects)["id"] == "p3"
    # short keys never containment-match
    assert V.resolve_project("app", projects) is None
    assert V.resolve_project("nothing-here", projects) is None


# ---------- deployment authorship ----------

def test_production_deploy_meta_parses_and_degrades():
    payload = {"deployments": [{
        "meta": {"githubCommitAuthorLogin": "Radz112", "githubCommitRef": "main"},
        "creator": {"username": "radlin-v"},
    }]}
    with patch.object(V, "_http_get", lambda *a, **k: payload):
        meta = V.production_deploy_meta("tok", "p1")
    assert meta == {"commit_author_login": "Radz112", "commit_ref": "main",
                    "creator_username": "radlin-v"}
    with patch.object(V, "_http_get", lambda *a, **k: {"deployments": []}):
        assert V.production_deploy_meta("tok", "p1") == {}
    with patch.object(V, "_http_get", lambda *a, **k: None):
        assert V.production_deploy_meta("tok", "p1") == {}


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
