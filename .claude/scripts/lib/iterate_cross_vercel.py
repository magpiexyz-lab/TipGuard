#!/usr/bin/env python3
"""iterate_cross_vercel.py — optional Vercel resolution channel for /iterate --cross.

Solves the class of MVPs whose GitHub repo lives OUTSIDE the magpiexyz-lab org
(personal accounts) — invisible to org-repo listing and the experiment.yaml
name-index — by walking the Vercel side: project name/host match → the
project's linked git repo (`link.org/link.repo`) plus the latest production
deployment's commit author. The deploy author is a direct owner signal — the
automated equivalent of the operator's manual "who created the active branch in
Vercel" method (which surfaced tifa→chester, agentshield→taran).

Token discovery: $VERCEL_TOKEN env var, else the ~/.vercel/api-token file,
else the Vercel CLI's own auth.json (via vercel_api.read_vercel_token — covers
macOS/Linux/legacy paths). A plain `vercel login` therefore satisfies the
channel; the ~/.vercel/api-token file is an optional override for operators who
prefer a scoped web token (https://vercel.com/account/settings/tokens):

    mkdir -p ~/.vercel && echo 'YOUR_TOKEN' > ~/.vercel/api-token

Presence-only: a revoked token still resolves here and degrades mid-run like
any transport failure. The /iterate --cross auth preflight (iterate_cross_auth)
hard-stops when NO token source exists at all.

All HTTP goes through _http_get (urllib, no new deps) — the single mock surface
for tests, mirroring iterate_cross_pricing._gh.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from iterate_cross_classify import match_key  # noqa: E402

API_BASE = "https://api.vercel.com"
TOKEN_PATH = "~/.vercel/api-token"
_PAGE_LIMIT = 100
_MAX_PAGES = 20  # 2000 projects per scope — far above any real workspace


def _cli_auth_token() -> str | None:
    """Vercel CLI auth.json token via vercel_api.read_vercel_token.

    Lazy import + separate function so tests can patch this seam without the
    chain reaching the developer machine's real CLI auth.json.
    """
    try:
        from vercel_api import read_vercel_token
    except ImportError:
        return None
    return read_vercel_token()


def vercel_token() -> str | None:
    """$VERCEL_TOKEN > ~/.vercel/api-token file > CLI auth.json > None (channel off)."""
    tok = (os.environ.get("VERCEL_TOKEN") or "").strip()
    if tok:
        return tok
    try:
        file_tok = open(os.path.expanduser(TOKEN_PATH)).read().strip()
    except OSError:
        file_tok = ""
    if file_tok:
        return file_tok
    return _cli_auth_token()


def _http_get(path: str, token: str, params: dict | None = None) -> dict | None:
    """GET API_BASE+path as JSON; None on any transport/parse error (never raises)."""
    url = API_BASE + path + (f"?{urlencode(params)}" if params else "")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except (urllib.error.URLError, ValueError, OSError):
        return None


def list_teams(token: str) -> list[str]:
    data = _http_get("/v2/teams", token, {"limit": _PAGE_LIMIT}) or {}
    return [t["id"] for t in data.get("teams") or [] if isinstance(t, dict) and t.get("id")]


def _project_row(p: dict, team_id: str | None) -> dict:
    link = p.get("link") or {}
    slug = None
    if link.get("type") == "github" and link.get("org") and link.get("repo"):
        slug = f"{link['org']}/{link['repo']}"
    return {
        "id": p.get("id"),
        "name": p.get("name") or "",
        "team_id": team_id,
        "repo_slug": slug,
    }


def list_projects(token: str) -> list[dict]:
    """All projects across the personal scope and every team the token can see.

    Rows: {id, name, team_id, repo_slug} where repo_slug is `owner/repo` for
    GitHub-linked projects (None otherwise). Pagination via `pagination.next`.
    """
    out: list[dict] = []
    for team_id in [None, *list_teams(token)]:
        until = None
        for _ in range(_MAX_PAGES):
            params: dict = {"limit": _PAGE_LIMIT}
            if team_id:
                params["teamId"] = team_id
            if until:
                params["until"] = until
            data = _http_get("/v9/projects", token, params)
            if not data:
                break
            for p in data.get("projects") or []:
                if isinstance(p, dict):
                    out.append(_project_row(p, team_id))
            nxt = (data.get("pagination") or {}).get("next")
            if not nxt or nxt == until:
                break
            until = nxt
    return out


def resolve_project(name: str, projects: list[dict], deploy_host: str | None = None) -> dict | None:
    """Best project for an MVP: exact name-key match (or deploy-host key), then
    guarded containment (keys ≥ 6 chars). None when nothing matches."""
    key = match_key(name)
    host_key = match_key((deploy_host or "").split(".")[0]) if deploy_host else ""
    for p in projects:
        pkey = match_key(p.get("name") or "")
        if pkey and (pkey == key or (host_key and pkey == host_key)):
            return p
    for p in projects:
        pkey = match_key(p.get("name") or "")
        if key and pkey and len(key) >= 6 and len(pkey) >= 6 and (key in pkey or pkey in key):
            return p
    return None


def production_deploy_meta(token: str, project_id: str, team_id: str | None = None) -> dict:
    """Latest production deployment's authorship signals for a project.

    {commit_author_login, commit_ref, creator_username} — any field may be None;
    {} when no production deployment exists or the call fails.
    """
    params: dict = {"projectId": project_id, "limit": 1, "target": "production"}
    if team_id:
        params["teamId"] = team_id
    data = _http_get("/v6/deployments", token, params) or {}
    rows = data.get("deployments") or []
    if not rows or not isinstance(rows[0], dict):
        return {}
    d = rows[0]
    meta = d.get("meta") or {}
    return {
        "commit_author_login": meta.get("githubCommitAuthorLogin"),
        "commit_ref": meta.get("githubCommitRef"),
        "creator_username": (d.get("creator") or {}).get("username"),
    }
