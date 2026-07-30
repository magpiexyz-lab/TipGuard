"""Vercel API helper using the operator's CLI auth.

Reads token from operator-controlled paths; falls back to VERCEL_TOKEN env.
All HTTP calls use subprocess + curl to match the template's script
conventions and avoid adding a dependency.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Union
from urllib.parse import urlencode


def read_vercel_token() -> str | None:
    """Return the Vercel CLI access token, or None if not authenticated.

    Discovery order:
      1. VERCEL_TOKEN env var
      2. macOS: ~/Library/Application Support/com.vercel.cli/auth.json
      3. Linux XDG: ~/.local/share/com.vercel.cli/auth.json
      4. Legacy: ~/.vercel/auth.json
    """
    env_token = os.environ.get("VERCEL_TOKEN")
    if env_token:
        return env_token

    candidates: list[Path] = []
    if sys.platform == "darwin":
        candidates.append(
            Path.home()
            / "Library"
            / "Application Support"
            / "com.vercel.cli"
            / "auth.json"
        )
    candidates.extend(
        [
            Path.home() / ".local" / "share" / "com.vercel.cli" / "auth.json",
            Path.home() / ".vercel" / "auth.json",
        ]
    )

    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            with candidate.open() as fh:
                token = json.load(fh).get("token")
            if token:
                return token
        except Exception:
            continue
    return None


def read_project_link() -> dict[str, str | None] | None:
    """Read .vercel/project.json created by `vercel link`."""
    path = Path(".vercel") / "project.json"
    if not path.exists():
        return None
    try:
        with path.open() as fh:
            data = json.load(fh)
    except Exception:
        return None
    return {"projectId": data.get("projectId"), "orgId": data.get("orgId")}


def _curl_json(token: str, url: str) -> Any:
    r = subprocess.run(
        ["curl", "-s", "-H", f"Authorization: Bearer {token}", url],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        raise RuntimeError(f"Vercel API failed: {r.stderr[:200]}")
    return json.loads(r.stdout)


def list_team_projects(token: str, team_id: str | None = None) -> list[dict[str, Any]]:
    """Return all projects accessible by the operator's auth.

    Vercel /v10/projects is paginated via pagination.next and the next request
    uses from=<cursor>. This intentionally does not use the older until cursor.
    """
    projects: list[dict[str, Any]] = []
    next_cursor: str | None = None

    while True:
        params: dict[str, str | int] = {"limit": 100}
        if team_id:
            params["teamId"] = team_id
        if next_cursor:
            params["from"] = next_cursor
        url = f"https://api.vercel.com/v10/projects?{urlencode(params)}"
        body = _curl_json(token, url)

        if isinstance(body, list):
            projects.extend(body)
            break
        if not isinstance(body, dict):
            break

        page_projects = body.get("projects", [])
        if isinstance(page_projects, list):
            projects.extend(page_projects)
        pagination = body.get("pagination") or {}
        next_cursor = pagination.get("next") if isinstance(pagination, dict) else None
        if not next_cursor:
            break

    return projects


@dataclass
class EnvResultFound:
    value: str


@dataclass
class EnvResultAbsent:
    pass


@dataclass
class EnvResultError:
    reason: str


EnvResult = Union[EnvResultFound, EnvResultAbsent, EnvResultError]


def _target_matches(value: object, target: str) -> bool:
    if isinstance(value, list):
        return target in value
    if isinstance(value, str):
        return value == target
    return False


def get_vercel_env_var(
    token: str,
    project_id: str,
    team_id: str | None,
    key: str,
    target: str = "production",
) -> EnvResult:
    """Fetch a single decrypted Vercel env var value for a target.

    Returns:
      - EnvResultFound(value): key is set, and value may be an empty string.
      - EnvResultAbsent(): key is confirmed absent from the env list.
      - EnvResultError(reason): curl, HTTP, or JSON parsing failed.
    """
    params: dict[str, str] = {"decrypt": "true"}
    if team_id:
        params["teamId"] = team_id
    url = f"https://api.vercel.com/v10/projects/{project_id}/env?{urlencode(params)}"

    r = subprocess.run(
        [
            "curl",
            "-s",
            "-o",
            "-",
            "-w",
            "\n__HTTP_STATUS:%{http_code}",
            "-H",
            f"Authorization: Bearer {token}",
            url,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        return EnvResultError(f"curl failed (exit {r.returncode}): {r.stderr[:200]}")

    body, _, status_line = r.stdout.rpartition("__HTTP_STATUS:")
    status = status_line.strip()
    if status != "200":
        return EnvResultError(f"Vercel API returned HTTP {status}")

    try:
        payload = json.loads(body)
    except Exception as exc:
        return EnvResultError(f"malformed Vercel response: {exc}")

    envs = payload.get("envs", []) if isinstance(payload, dict) else []
    for env in envs:
        if not isinstance(env, dict):
            continue
        if env.get("key") == key and _target_matches(env.get("target"), target):
            value = env.get("value")
            return EnvResultFound(value if isinstance(value, str) else "")
    return EnvResultAbsent()


def find_project(
    token: str,
    team_id: str | None,
    project_id_or_name: str,
) -> dict[str, Any] | None:
    """Find a project by ID first, then by name."""
    projects = list_team_projects(token, team_id=team_id)
    for project in projects:
        if project.get("id") == project_id_or_name:
            return project
    for project in projects:
        if project.get("name") == project_id_or_name:
            return project
    return None


def latest_production_deployment_url(
    token: str,
    project_id: str,
    team_id: str | None = None,
) -> str | None:
    """Return the latest production deployment URL for a project, or None."""
    params: dict[str, str | int] = {
        "projectId": project_id,
        "target": "production",
        "limit": 1,
    }
    if team_id:
        params["teamId"] = team_id
    url = f"https://api.vercel.com/v6/deployments?{urlencode(params)}"

    try:
        body = _curl_json(token, url)
    except Exception:
        return None
    deployments = body.get("deployments", []) if isinstance(body, dict) else []
    if not deployments:
        return None
    deployment_url = deployments[0].get("url") if isinstance(deployments[0], dict) else None
    if not deployment_url:
        return None
    return f"https://{deployment_url}"


def get_project_domains(
    token: str,
    project_id: str,
    team_id: str | None = None,
) -> list[str]:
    """Return domain names assigned to a Vercel project."""
    params: dict[str, str] = {}
    if team_id:
        params["teamId"] = team_id
    query = f"?{urlencode(params)}" if params else ""
    url = f"https://api.vercel.com/v9/projects/{project_id}/domains{query}"

    body = _curl_json(token, url)
    raw_domains = body.get("domains", []) if isinstance(body, dict) else body
    if not isinstance(raw_domains, list):
        return []

    domains: list[str] = []
    for item in raw_domains:
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = str(item.get("name") or item.get("domain") or "")
        else:
            name = ""
        name = name.strip()
        if name:
            domains.append(name)
    return domains
