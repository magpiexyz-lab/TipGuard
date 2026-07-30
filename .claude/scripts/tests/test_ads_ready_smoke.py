#!/usr/bin/env python3
"""Tests for .claude/scripts/lib/ads_ready_smoke.py."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import ads_ready_smoke as S  # noqa: E402
from gclid_filter import SYNTHETIC_GCLID_PREFIX  # noqa: E402


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def make_root(
    root: Path,
    *,
    playwright: bool = True,
    events: str | None = None,
    hosting: str = "vercel",
) -> None:
    if playwright:
        (root / "node_modules" / "@playwright" / "test").mkdir(parents=True)
    (root / "experiment").mkdir(parents=True, exist_ok=True)
    (root / "experiment" / "experiment.yaml").write_text(
        "name: alpha\n"
        "type: web-app\n"
        "stack:\n"
        "  analytics: posthog\n"
        "  services:\n"
        "    - name: app\n"
        f"      hosting: {hosting}\n",
        encoding="utf-8",
    )
    if events is not None:
        (root / "experiment" / "EVENTS.yaml").write_text(events, encoding="utf-8")


def write_vercel_link(root: Path, project_id: str = "prj_alpha", org_id: str = "team_clean") -> None:
    write_json(root / ".vercel" / "project.json", {"projectId": project_id, "orgId": org_id})


class AdsReadySmokeOrchestratorTests(unittest.TestCase):
    def run_smoke(self, ctx: dict, static_result: dict | None = None):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            context = base / "context.json"
            static_path = base / "static.json"
            output = base / "smoke.json"
            write_json(context, ctx)
            write_json(static_path, static_result or {"overall_pass": True})
            with patch.object(S, "_git_head", return_value="test-head"), patch(
                "sys.stderr", new=io.StringIO()
            ):
                rc = S.main(
                    [
                        "--context",
                        str(context),
                        "--static-result",
                        str(static_path),
                        "--output",
                        str(output),
                    ]
                )
            return rc, json.loads(output.read_text(encoding="utf-8"))

    @patch("ads_ready_smoke.validate_operator_deploy_url", return_value="https://alpha.example")
    def test_playwright_not_installed_hard_fails(self, _validate):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            make_root(root, playwright=False)
            write_vercel_link(root)
            rc, result = self.run_smoke({"mvp_root": str(root), "deploy_url": "https://alpha.example"})

        self.assertEqual(rc, 0)
        self.assertFalse(result["overall_pass"])
        self.assertEqual(result["failed_count"], 1)
        self.assertIn("Playwright is required", result["checks"][0]["details"])
        self.assertIn("npm install --save-dev @playwright/test", result["checks"][0]["fix"])

    @patch("ads_ready_smoke.autodetect_vercel_deploy_url", return_value=None)
    def test_no_deploy_url_hard_fails(self, _mock_autodetect):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            make_root(root, playwright=True)
            write_vercel_link(root)
            rc, result = self.run_smoke({"mvp_root": str(root), "deploy_url": ""})

        self.assertEqual(rc, 0)
        self.assertFalse(result["overall_pass"])
        self.assertEqual(result["phase"], "phase-1")
        self.assertEqual(result["git_head"], "test-head")
        self.assertIn("Could not determine deployed URL", result["checks"][0]["details"])
        self.assertIn("vercel login", result["checks"][0]["fix"])

    @patch("ads_ready_smoke.vercel_api.read_vercel_token", return_value="vercel-token")
    @patch(
        "ads_ready_smoke.vercel_api.latest_production_deployment_url",
        return_value="https://alpha-prod.vercel.app",
    )
    @patch("ads_ready_smoke.vercel_api.get_project_domains", return_value=["alpha.example.com"])
    def test_operator_url_unknown_host_fails(self, _domains, _latest, _token):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            make_root(root, playwright=True)
            write_vercel_link(root)
            rc, result = self.run_smoke(
                {"mvp_root": str(root), "deploy_url": "https://personal.example.com"}
            )

        self.assertEqual(rc, 0)
        self.assertFalse(result["overall_pass"])
        self.assertIn(
            "URL https://personal.example.com is not a known production deployment or domain",
            result["checks"][0]["details"],
        )
        self.assertIn("verified Vercel project prj_alpha", result["checks"][0]["details"])
        self.assertIn("https://alpha-prod.vercel.app", result["checks"][0]["details"])

    @patch("ads_ready_smoke.vercel_api.read_vercel_token", return_value=None)
    def test_operator_url_without_vercel_auth_fails(self, _token):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            make_root(root, playwright=True)
            write_vercel_link(root)
            rc, result = self.run_smoke(
                {"mvp_root": str(root), "deploy_url": "https://alpha.example.com"}
            )

        self.assertEqual(rc, 0)
        self.assertFalse(result["overall_pass"])
        self.assertIn("Vercel auth is missing", result["checks"][0]["details"])

    @patch("ads_ready_smoke.vercel_api.read_vercel_token", return_value="vercel-token")
    @patch(
        "ads_ready_smoke.vercel_api.latest_production_deployment_url",
        return_value="https://alpha-prod.vercel.app",
    )
    @patch("ads_ready_smoke.vercel_api.get_project_domains", return_value=["alpha.example.com"])
    def test_operator_url_known_project_domain_passes_validation(self, _domains, _latest, _token):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            make_root(root, playwright=True)
            write_vercel_link(root)
            self.assertEqual(
                S.resolve_deploy_url(
                    {"mvp_root": str(root), "deploy_url": "https://alpha.example.com/pricing"}
                ),
                "https://alpha.example.com/pricing",
            )

    @patch("ads_ready_smoke.vercel_api.read_vercel_token", return_value="vercel-token")
    @patch(
        "ads_ready_smoke.vercel_api.latest_production_deployment_url",
        return_value="https://alpha-personal.vercel.app",
    )
    @patch("ads_ready_smoke.vercel_api.get_project_domains", return_value=["alpha-personal.vercel.app"])
    def test_hosting_typo_without_vercel_link_blocks_personal_matching_project(
        self,
        mock_domains,
        mock_latest,
        mock_token,
    ):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            make_root(root, playwright=True, hosting="vecel")
            static_result = {
                "overall_pass": True,
                "checks": [
                    {
                        "id": 9,
                        "name": "Vercel deployment in team account",
                        "applicable": False,
                        "passed": None,
                        "details": "N/A (not applicable to this MVP)",
                        "fix": None,
                    }
                ],
            }
            rc, result = self.run_smoke(
                {"mvp_root": str(root), "deploy_url": "https://alpha-personal.vercel.app"},
                static_result=static_result,
            )

        self.assertEqual(rc, 0)
        self.assertFalse(result["overall_pass"])
        self.assertIn("Layer A Check 9", result["checks"][0]["details"])
        self.assertIn(".vercel/project.json", result["checks"][0]["details"])
        self.assertIn("vercel link", result["checks"][0]["fix"])
        mock_token.assert_not_called()
        mock_latest.assert_not_called()
        mock_domains.assert_not_called()

    @patch("ads_ready_smoke.validate_operator_deploy_url", return_value="https://alpha.example")
    @patch("ads_ready_smoke.time.sleep")
    @patch("ads_ready_smoke.secrets.token_urlsafe", return_value="TOKEN")
    @patch("ads_ready_smoke.run_playwright_smoke", return_value=Path("captured-events.json"))
    @patch("ads_ready_smoke._read_posthog_api_key", return_value="phx_api")
    @patch("ads_ready_smoke.H.resolve_production_posthog_key", return_value=("phc_REAL", "vercel_env_set", None))
    @patch(
        "ads_ready_smoke.H.load_team_config",
        return_value={"team": {"posthog": {"project_ids": [2], "project_api_tokens": ["phc_REAL"]}}},
    )
    @patch("ads_ready_smoke._posthog_query")
    @patch("ads_ready_smoke._posthog_get")
    def test_playwright_and_hogql_success(
        self,
        mock_posthog_get,
        mock_posthog_query,
        _mock_team_config,
        _mock_resolve,
        _mock_read_key,
        _mock_playwright,
        _mock_token,
        _mock_sleep,
        _mock_validate,
    ):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            make_root(
                root,
                playwright=True,
                events="events:\n  visit_landing:\n    funnel_stage: landing\n",
            )
            write_vercel_link(root)
            mock_posthog_get.side_effect = [
                {"results": [{"id": 2, "name": "Team", "api_token": "phc_REAL"}], "next": None},
            ]
            mock_posthog_query.side_effect = [
                {"results": [["visit_landing", "alpha", SYNTHETIC_GCLID_PREFIX + "TOKEN", S.SYNTHETIC_UTM_CAMPAIGN]]},
                {"results": [["visit_landing", "alpha", SYNTHETIC_GCLID_PREFIX + "TOKEN", S.SYNTHETIC_UTM_CAMPAIGN]]},
                {"results": [["visit_landing", 1]]},
            ]
            rc, result = self.run_smoke(
                {"mvp_root": str(root), "deploy_url": "https://alpha.example", "phase": "phase-2"}
            )

        self.assertEqual(rc, 0)
        self.assertTrue(result["overall_pass"])
        self.assertEqual(result["phase"], "phase-2")
        self.assertEqual(result["git_head"], "test-head")
        self.assertEqual(result["passed_count"], 5)
        self.assertEqual(result["failed_count"], 0)
        self.assertTrue(result["synthetic_gclid"].startswith(SYNTHETIC_GCLID_PREFIX))
        self.assertEqual(mock_posthog_query.call_count, 3)
        self.assertEqual(mock_posthog_get.call_count, 1)

    @patch("ads_ready_smoke.time.sleep")
    @patch("ads_ready_smoke.secrets.token_urlsafe", return_value="TOKEN")
    @patch("ads_ready_smoke.run_playwright_smoke", return_value=Path("captured-events.json"))
    @patch(
        "ads_ready_smoke.discover_posthog_project",
        return_value={"project_id": "2", "api_key": "phx_api", "expected_project_name": "alpha"},
    )
    @patch("ads_ready_smoke.validate_operator_deploy_url", return_value="https://alpha.example")
    @patch("ads_ready_smoke._posthog_query")
    def test_check_24_fails_when_auto_event_lacks_project_name(
        self,
        mock_posthog_query,
        _mock_validate,
        _mock_discover,
        _mock_playwright,
        _mock_token,
        _mock_sleep,
    ):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            make_root(
                root,
                playwright=True,
                events="events:\n  visit_landing:\n    funnel_stage: landing\n",
            )
            write_vercel_link(root)
            # visit_landing carries project_name (track() enrichment) but the
            # SDK auto-event $pageleave arrives with an empty pn — Check 20's
            # membership test passes while Check 24 must fail.
            probe_rows = [
                ["visit_landing", "alpha", SYNTHETIC_GCLID_PREFIX + "TOKEN", S.SYNTHETIC_UTM_CAMPAIGN],
                ["$pageleave", "", SYNTHETIC_GCLID_PREFIX + "TOKEN", S.SYNTHETIC_UTM_CAMPAIGN],
            ]
            mock_posthog_query.side_effect = [
                {"results": probe_rows},
                {"results": probe_rows},
                {"results": [["visit_landing", 1]]},
            ]
            rc, result = self.run_smoke({"mvp_root": str(root), "deploy_url": "https://alpha.example"})

        self.assertEqual(rc, 0)
        self.assertFalse(result["overall_pass"])
        by_id = {check["id"]: check for check in result["checks"]}
        self.assertTrue(by_id[20]["passed"])
        self.assertFalse(by_id[24]["passed"])
        self.assertIn("$pageleave", by_id[24]["details"])
        self.assertIn("register_for_session", by_id[24]["fix"])
        self.assertIn("#1828", by_id[24]["fix"])

    @patch("ads_ready_smoke.H.resolve_production_posthog_key", return_value=("phc_REAL", "vercel_env_set", None))
    @patch("ads_ready_smoke.H.load_team_config", return_value={})
    def test_discover_posthog_project_missing_team_config_fails(self, _config, _resolve):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            make_root(root, playwright=True)
            with self.assertRaises(S.SmokeSetupError) as raised:
                S.discover_posthog_project({"mvp_root": str(root)})
        self.assertIn("Team config not found", str(raised.exception))

    @patch("ads_ready_smoke.time.sleep")
    @patch("ads_ready_smoke.secrets.token_urlsafe", return_value="TOKEN")
    @patch("ads_ready_smoke.run_playwright_smoke", return_value=Path("captured-events.json"))
    @patch(
        "ads_ready_smoke.discover_posthog_project",
        return_value={"project_id": "2", "api_key": "phx_api", "expected_project_name": "alpha"},
    )
    @patch("ads_ready_smoke.validate_operator_deploy_url", return_value="https://alpha.example")
    @patch("ads_ready_smoke._posthog_query")
    def test_hogql_timeout_retries_then_fails(
        self,
        mock_posthog_query,
        _mock_validate,
        _mock_discover,
        _mock_playwright,
        _mock_token,
        mock_sleep,
    ):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            make_root(
                root,
                playwright=True,
                events="events:\n  visit_landing:\n    funnel_stage: landing\n",
            )
            write_vercel_link(root)
            mock_posthog_query.side_effect = [
                {"results": []},
                {"results": []},
                {"results": []},
                {"results": []},
            ]
            rc, result = self.run_smoke({"mvp_root": str(root), "deploy_url": "https://alpha.example"})

        self.assertEqual(rc, 0)
        self.assertFalse(result["overall_pass"])
        self.assertGreaterEqual(result["failed_count"], 1)
        self.assertIn("90s timeout", result["checks"][0]["details"])
        self.assertEqual(mock_sleep.call_count, 2)
        self.assertEqual(mock_posthog_query.call_count, 4)

    def test_static_only_writes_five_skipped_checks(self):
        rc, result = self.run_smoke({"static_only": True, "phase": "phase-2", "phase_2": True})

        self.assertEqual(rc, 0)
        self.assertTrue(result["skipped"])
        self.assertIsNone(result["overall_pass"])
        self.assertEqual(result["phase"], "phase-2")
        self.assertEqual(result["git_head"], "test-head")
        self.assertEqual(result["skipped_count"], 5)
        self.assertEqual([check["id"] for check in result["checks"]], [20, 21, 22, 23, 24])
        self.assertTrue(all(check["skipped"] for check in result["checks"]))


if __name__ == "__main__":
    unittest.main()
