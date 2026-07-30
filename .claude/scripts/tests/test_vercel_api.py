#!/usr/bin/env python3
"""Tests for .claude/scripts/lib/vercel_api.py."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import vercel_api  # noqa: E402


def _completed(stdout: str, returncode: int = 0, stderr: str = ""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


class VercelApiTests(unittest.TestCase):
    def test_read_vercel_token_env_priority(self):
        with patch.dict(os.environ, {"VERCEL_TOKEN": "env-token"}, clear=True):
            self.assertEqual(vercel_api.read_vercel_token(), "env-token")

    def test_read_vercel_token_macos_linux_legacy_and_none(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            mac_path = (
                home
                / "Library"
                / "Application Support"
                / "com.vercel.cli"
                / "auth.json"
            )
            _write_json(mac_path, {"token": "mac-token"})
            with patch.dict(os.environ, {}, clear=True):
                with patch("vercel_api.sys.platform", "darwin"):
                    with patch("vercel_api.Path.home", return_value=home):
                        self.assertEqual(vercel_api.read_vercel_token(), "mac-token")

        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            linux_path = home / ".local" / "share" / "com.vercel.cli" / "auth.json"
            _write_json(linux_path, {"token": "linux-token"})
            with patch.dict(os.environ, {}, clear=True):
                with patch("vercel_api.sys.platform", "linux"):
                    with patch("vercel_api.Path.home", return_value=home):
                        self.assertEqual(vercel_api.read_vercel_token(), "linux-token")

        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            legacy_path = home / ".vercel" / "auth.json"
            _write_json(legacy_path, {"token": "legacy-token"})
            with patch.dict(os.environ, {}, clear=True):
                with patch("vercel_api.sys.platform", "linux"):
                    with patch("vercel_api.Path.home", return_value=home):
                        self.assertEqual(vercel_api.read_vercel_token(), "legacy-token")

        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            with patch.dict(os.environ, {}, clear=True):
                with patch("vercel_api.sys.platform", "linux"):
                    with patch("vercel_api.Path.home", return_value=home):
                        self.assertIsNone(vercel_api.read_vercel_token())

    def test_read_project_link_file_and_missing(self):
        old_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as td:
            try:
                os.chdir(td)
                self.assertIsNone(vercel_api.read_project_link())
                _write_json(
                    Path(".vercel") / "project.json",
                    {"projectId": "prj_123", "orgId": "team_123"},
                )
                self.assertEqual(
                    vercel_api.read_project_link(),
                    {"projectId": "prj_123", "orgId": "team_123"},
                )
            finally:
                os.chdir(old_cwd)

    @patch("vercel_api.subprocess.run")
    def test_list_team_projects_accepts_array_and_dict_shapes(self, mock_run):
        mock_run.return_value = _completed(json.dumps([{"id": "a"}]))
        self.assertEqual(vercel_api.list_team_projects("tok"), [{"id": "a"}])

        mock_run.reset_mock()
        mock_run.return_value = _completed(
            json.dumps({"projects": [{"id": "b"}], "pagination": {}})
        )
        self.assertEqual(vercel_api.list_team_projects("tok"), [{"id": "b"}])

    @patch("vercel_api.subprocess.run")
    def test_list_team_projects_paginates_with_from_cursor_and_team_id(self, mock_run):
        mock_run.side_effect = [
            _completed(
                json.dumps(
                    {"projects": [{"id": "a"}], "pagination": {"next": "cursor_2"}}
                )
            ),
            _completed(json.dumps({"projects": [{"id": "b"}], "pagination": {}})),
        ]

        projects = vercel_api.list_team_projects("tok", team_id="team_123")

        self.assertEqual(projects, [{"id": "a"}, {"id": "b"}])
        first_url = mock_run.call_args_list[0][0][0][-1]
        second_url = mock_run.call_args_list[1][0][0][-1]
        self.assertIn("teamId=team_123", first_url)
        self.assertNotIn("from=", first_url)
        self.assertIn("teamId=team_123", second_url)
        self.assertIn("from=cursor_2", second_url)

    def test_find_project_by_id_name_and_missing(self):
        projects = [
            {"id": "prj_1", "name": "alpha"},
            {"id": "prj_2", "name": "beta"},
        ]
        with patch("vercel_api.list_team_projects", return_value=projects):
            self.assertEqual(
                vercel_api.find_project("tok", "team_1", "prj_2"),
                {"id": "prj_2", "name": "beta"},
            )
            self.assertEqual(
                vercel_api.find_project("tok", "team_1", "alpha"),
                {"id": "prj_1", "name": "alpha"},
            )
            self.assertIsNone(vercel_api.find_project("tok", "team_1", "missing"))

    def test_latest_production_deployment_url_present_and_absent(self):
        with patch(
            "vercel_api._curl_json",
            return_value={"deployments": [{"url": "prod.example.vercel.app"}]},
        ):
            self.assertEqual(
                vercel_api.latest_production_deployment_url("tok", "prj", "team"),
                "https://prod.example.vercel.app",
            )

        with patch("vercel_api._curl_json", return_value={"deployments": []}):
            self.assertIsNone(
                vercel_api.latest_production_deployment_url("tok", "prj", "team")
            )

    def test_get_project_domains_parses_names_and_team_id(self):
        payload = {
            "domains": [
                {"name": "app.example.com"},
                {"domain": "legacy.example.com"},
                "string.example.com",
                {"name": ""},
            ]
        }
        with patch("vercel_api._curl_json", return_value=payload) as mock_curl:
            self.assertEqual(
                vercel_api.get_project_domains("tok", "prj", "team_123"),
                ["app.example.com", "legacy.example.com", "string.example.com"],
            )

        url = mock_curl.call_args[0][1]
        self.assertIn("/v9/projects/prj/domains", url)
        self.assertIn("teamId=team_123", url)

    @patch("vercel_api.subprocess.run")
    def test_get_vercel_env_var_found_filters_target_empty_and_teamid(self, mock_run):
        payload = {
            "envs": [
                {"key": "NEXT_PUBLIC_POSTHOG_KEY", "target": ["preview"], "value": "phc_prev"},
                {
                    "key": "NEXT_PUBLIC_POSTHOG_KEY",
                    "target": ["production"],
                    "value": "phc_prod",
                },
                {"key": "EMPTY_KEY", "target": ["production"], "value": ""},
            ]
        }
        mock_run.return_value = _completed(json.dumps(payload) + "\n__HTTP_STATUS:200")

        result = vercel_api.get_vercel_env_var(
            "tok", "prj", "team_123", "NEXT_PUBLIC_POSTHOG_KEY"
        )

        self.assertIsInstance(result, vercel_api.EnvResultFound)
        self.assertEqual(result.value, "phc_prod")
        url = mock_run.call_args[0][0][-1]
        self.assertIn("decrypt=true", url)
        self.assertIn("teamId=team_123", url)

        empty = vercel_api.get_vercel_env_var("tok", "prj", None, "EMPTY_KEY")
        self.assertIsInstance(empty, vercel_api.EnvResultFound)
        self.assertEqual(empty.value, "")

    @patch("vercel_api.subprocess.run")
    def test_get_vercel_env_var_absent_and_errors(self, mock_run):
        mock_run.return_value = _completed('{"envs":[]}\n__HTTP_STATUS:200')
        absent = vercel_api.get_vercel_env_var("tok", "prj", None, "MISSING")
        self.assertIsInstance(absent, vercel_api.EnvResultAbsent)

        mock_run.return_value = _completed("not-json\n__HTTP_STATUS:200")
        malformed = vercel_api.get_vercel_env_var("tok", "prj", None, "KEY")
        self.assertIsInstance(malformed, vercel_api.EnvResultError)
        self.assertIn("malformed Vercel response", malformed.reason)

        mock_run.return_value = _completed('{"error":"no"}\n__HTTP_STATUS:401')
        http_error = vercel_api.get_vercel_env_var("tok", "prj", None, "KEY")
        self.assertIsInstance(http_error, vercel_api.EnvResultError)
        self.assertIn("HTTP 401", http_error.reason)

        mock_run.return_value = _completed("", returncode=7, stderr="offline")
        curl_error = vercel_api.get_vercel_env_var("tok", "prj", None, "KEY")
        self.assertIsInstance(curl_error, vercel_api.EnvResultError)
        self.assertIn("curl failed (exit 7)", curl_error.reason)


if __name__ == "__main__":
    unittest.main()
