#!/usr/bin/env python3
"""Tests for .claude/scripts/lib/ads_ready_static_helpers.py."""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import ads_ready_static_helpers as H  # noqa: E402


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ads_ready"
CLEAN = FIXTURES / "clean_mvp"


def fixture_ctx(name: str = "clean_mvp") -> dict:
    return {"mvp_root": str(FIXTURES / name)}


@contextlib.contextmanager
def repo(files: dict[str, str]):
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for rel, content in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        yield root


def experiment_yaml(
    name: str = "alpha",
    stack: str = "stack:\n  analytics: posthog\n",
    extra: str = "",
) -> str:
    return f"name: {name}\ntype: web-app\n{stack}{extra}"


def analytics_ts(name: str = "alpha", key: str = "phc_REAL_KEY") -> str:
    return (
        f'export const PROJECT_NAME = "{name}";\n'
        f'const POSTHOG_PLACEHOLDER = "phc_TEAM_KEY";\n'
        f'export const POSTHOG_KEY = process.env.NEXT_PUBLIC_POSTHOG_KEY ?? "{key}";\n'
        "export function track(e: string) { return e; }\n"
        "export function identify(id: string) { return id; }\n"
    )


def events_yaml(events: str) -> str:
    return "events:\n" + events


def phase2_fixture_files(overrides: dict[str, str] | None = None) -> dict[str, str]:
    files = {
        "experiment/experiment.yaml": experiment_yaml("alpha"),
        "experiment/EVENTS.yaml": events_yaml(
            "  pay_intent:\n"
            "    funnel_stage: monetize\n"
            "    properties:\n"
            "      plan: { type: string, required: true }\n"
            "      price_cents: { type: number, required: true }\n"
            "      gclid: { type: string, required: false }\n"
            "      utm_campaign: { type: string, required: true }\n"
        ),
        "tsconfig.json": '{"compilerOptions":{"paths":{"@/*":["src/*"]}}}',
        "src/lib/analytics.ts": "export function track(_event: string, _props?: unknown) {}\n",
        "src/lib/events.ts": (
            'import { track } from "./analytics";\n'
            "export function trackPayIntent(props: { plan: string; price_cents: number; gclid?: string; utm_campaign: string }) {\n"
            '  track("pay_intent", { ...props, funnel_stage: "monetize" });\n'
            "}\n"
        ),
        "src/lib/supabase/server.ts": "export function createClient() { return { from: () => ({ insert: async () => null }) }; }\n",
        "src/components/UpgradeCTA.tsx": (
            'import { trackPayIntent } from "@/lib/events";\n'
            "export function UpgradeCTA({ user, hasActivated, gclid, utm_campaign }) {\n"
            "  const canUpgrade = user && hasActivated;\n"
            "  if (!canUpgrade) return null;\n"
            "  async function onClick() {\n"
            '    trackPayIntent({ plan: "pro", price_cents: 1900, gclid, utm_campaign });\n'
            '    await fetch("/api/pay-intent", { method: "POST", body: JSON.stringify({ gclid, utm_campaign }) });\n'
            "  }\n"
            "  return <button onClick={onClick}>Upgrade to Pro</button>;\n"
            "}\n"
        ),
        "src/app/api/pay-intent/route.ts": (
            'import { createClient } from "@/lib/supabase/server";\n'
            "export async function POST(request: Request) {\n"
            "  const { gclid, utm_campaign } = await request.json();\n"
            "  const supabase = createClient();\n"
            '  await supabase.from("pay_intent").insert({ user_id: "user_1", gclid, utm_campaign });\n'
            "  return Response.json({ ok: true });\n"
            "}\n"
        ),
        "supabase/migrations/20260601000000_pay_intent.sql": (
            "create table public.pay_intent (\n"
            "  id uuid primary key,\n"
            "  user_id uuid references auth.users(id),\n"
            "  gclid text,\n"
            "  utm_campaign text,\n"
            "  created_at timestamptz default now()\n"
            ");\n"
            "alter table public.pay_intent enable row level security;\n"
        ),
    }
    if overrides:
        files.update(overrides)
    return files


def team_config(**overrides) -> dict:
    config = {
        "team": {
            "posthog": {
                "project_ids": [1, 2],
                "project_api_tokens": ["phc_CLIENT"],
            },
            "supabase": {"organization_ids": ["org_team"]},
            "railway": {"workspace_ids": ["ws_team"]},
            "vercel": {"team_ids": ["team_clean"]},
            "stripe": {"account_ids": ["acct_team"]},
        }
    }
    for provider, section in overrides.items():
        config["team"][provider] = section
    return config


PROVIDER_FIELDS = (
    ("posthog", "project_api_tokens"),
    ("supabase", "organization_ids"),
    ("railway", "workspace_ids"),
    ("vercel", "team_ids"),
    ("stripe", "account_ids"),
)


class TeamConfigRealFileTests(unittest.TestCase):
    def _repo_with_team_config(self, team_config_text: str | None):
        files = {
            "experiment/experiment.yaml": experiment_yaml("alpha"),
            ".vercel/project.json": '{"projectId":"prj_clean","orgId":"team_clean"}',
        }
        if team_config_text is not None:
            files[".claude/team-config.yaml"] = team_config_text
        return repo(files)

    def _values_from(self, root: Path, provider: str, field: str):
        return H._team_values_or_failure({"mvp_root": str(root)}, provider, field)

    def test_explicit_mvp_root_missing_file_fails_with_path(self):
        with self._repo_with_team_config(None) as root:
            passed, details, fix = H.check_vercel_team_account({"mvp_root": str(root)})
        self.assertFalse(passed)
        self.assertIn(str(root / ".claude" / "team-config.yaml"), details)
        self.assertIn("Add", fix)

    def test_yaml_syntax_error_fails_with_parse_message(self):
        with self._repo_with_team_config("team:\n  vercel: [\n") as root:
            passed, details, fix = H.check_vercel_team_account({"mvp_root": str(root)})
        self.assertFalse(passed)
        self.assertIn("parse error", details)
        self.assertIn(str(root / ".claude" / "team-config.yaml"), details)
        self.assertIn("Fix YAML syntax", fix)

    def test_team_section_missing_fails(self):
        with self._repo_with_team_config("not_team: {}\n") as root:
            _values, failure = self._values_from(root, "vercel", "team_ids")
        self.assertIsNotNone(failure)
        self.assertFalse(failure[0])
        self.assertIn("team section", failure[1])

    def test_provider_sections_missing_fail(self):
        for provider, field in PROVIDER_FIELDS:
            with self.subTest(provider=provider):
                with self._repo_with_team_config("team: {}\n") as root:
                    _values, failure = self._values_from(root, provider, field)
                self.assertIsNotNone(failure)
                self.assertFalse(failure[0])
                self.assertIn(f"team.{provider} section", failure[1])

    def test_provider_lists_empty_fail(self):
        for provider, field in PROVIDER_FIELDS:
            with self.subTest(provider=provider):
                config = f"team:\n  {provider}:\n    {field}: []\n"
                with self._repo_with_team_config(config) as root:
                    _values, failure = self._values_from(root, provider, field)
                self.assertIsNotNone(failure)
                self.assertFalse(failure[0])
                self.assertIn(f"team.{provider}.{field}", failure[1])

    def test_provider_lists_match_single_multiple_and_whitespace_values(self):
        cases = [
            ("single", ['"one"'], ["one"]),
            ("multiple", ['"one"', '"two"'], ["one", "two"]),
            ("whitespace", ['" one "', '"two  "'], ["one", "two"]),
        ]
        for provider, field in PROVIDER_FIELDS:
            for label, raw_values, expected in cases:
                with self.subTest(provider=provider, case=label):
                    items = "\n".join(f"      - {value}" for value in raw_values)
                    config = f"team:\n  {provider}:\n    {field}:\n{items}\n"
                    with self._repo_with_team_config(config) as root:
                        values, failure = self._values_from(root, provider, field)
                    self.assertIsNone(failure)
                    self.assertEqual(values, expected)


class Check1ProjectNameTests(unittest.TestCase):
    def test_passes_clean_fixture(self):
        passed, _, _ = H.check_project_name_drift(fixture_ctx())
        self.assertTrue(passed)

    def test_fails_on_project_name_drift(self):
        with repo(
            {
                "experiment/experiment.yaml": experiment_yaml("alpha"),
                "src/lib/analytics.ts": analytics_ts("beta"),
            }
        ) as root:
            passed, details, fix = H.check_project_name_drift({"mvp_root": str(root)})
        self.assertFalse(passed)
        self.assertIn("drift", details)
        self.assertIn("PROJECT_NAME drift", fix)

    def test_exit_2_environmental_error_is_failure(self):
        with repo({}) as root:
            passed, details, fix = H.check_project_name_drift({"mvp_root": str(root)})
        self.assertFalse(passed)
        self.assertIn("exit 2", details)
        self.assertIn("environmental", fix)


class Check2PlaceholderTests(unittest.TestCase):
    @patch("ads_ready_static_helpers.resolve_production_posthog_key")
    def test_vercel_env_real_key_passes(self, mock_resolve):
        mock_resolve.return_value = ("phc_REAL", "vercel_env_set", None)
        passed, details, _ = H.check_no_posthog_placeholder(fixture_ctx())
        self.assertTrue(passed)
        self.assertIn("vercel_env_set", details)

    @patch("ads_ready_static_helpers.resolve_production_posthog_key")
    def test_source_placeholder_fails(self, mock_resolve):
        mock_resolve.return_value = ("phc_TEAM_KEY", "source_fallback", "src/lib/analytics.ts")
        passed, details, fix = H.check_no_posthog_placeholder(fixture_ctx())
        self.assertFalse(passed)
        self.assertIn("placeholder", details)
        self.assertIn("src/lib/analytics.ts", fix)

    @patch("ads_ready_static_helpers.resolve_production_posthog_key")
    def test_source_inconsistent_fails(self, mock_resolve):
        mock_resolve.return_value = (None, "source_fallback_inconsistent", None)
        passed, details, fix = H.check_no_posthog_placeholder(fixture_ctx())
        self.assertFalse(passed)
        self.assertIn("disagree", details)
        self.assertIn("Sync", fix)


class Check3AnalyticsWiredTests(unittest.TestCase):
    def test_clean_fixture_passes_via_bfs_alias_import(self):
        passed, details, _ = H.check_analytics_module_wired(fixture_ctx())
        self.assertTrue(passed)
        self.assertIn("LandingHero", details)

    def test_broken_no_import_fixture_fails(self):
        passed, details, fix = H.check_analytics_module_wired(
            fixture_ctx("broken_no_analytics_import")
        )
        self.assertFalse(passed)
        self.assertIn("No reachable", details)
        self.assertIn("BFS", fix)

    def test_relative_import_resolves_to_events_module(self):
        with repo(
            {
                "experiment/experiment.yaml": experiment_yaml("alpha"),
                "src/app/page.tsx": (
                    'import { trackLandingViewed } from "../lib/events";\n'
                    "export default function Page() { trackLandingViewed(); return null; }\n"
                ),
                "src/lib/events.ts": "export function trackLandingViewed() {}\n",
            }
        ) as root:
            passed, details, _ = H.check_analytics_module_wired({"mvp_root": str(root)})
        self.assertTrue(passed)
        self.assertIn("src/lib/events.ts", details)


class Check4RawCaptureTests(unittest.TestCase):
    def test_clean_fixture_passes(self):
        passed, _, _ = H.check_no_raw_capture(fixture_ctx())
        self.assertTrue(passed)

    def test_broken_raw_capture_fixture_fails(self):
        passed, details, fix = H.check_no_raw_capture(fixture_ctx("broken_raw_capture"))
        self.assertFalse(passed)
        self.assertIn("src/app/page.tsx", details)
        self.assertIn("Replace raw", fix)

    def test_exclusion_paths_do_not_fail(self):
        with repo(
            {
                "experiment/experiment.yaml": experiment_yaml("alpha"),
                "src/lib/analytics.ts": "posthog.capture('ok here');\n",
                "src/lib/analytics-server.ts": "posthog.identify('ok here');\n",
                "src/app/page.test.ts": "posthog.capture('test');\n",
                "src/app/Button.stories.tsx": "posthog.capture('story');\n",
                "src/app/page.tsx": "export default function Page() { return null; }\n",
            }
        ) as root:
            passed, _, _ = H.check_no_raw_capture({"mvp_root": str(root)})
        self.assertTrue(passed)


class Check5SignupEventsTests(unittest.TestCase):
    def test_clean_fixture_signup_event_implemented(self):
        passed, _, _ = H.check_signup_events_implemented(fixture_ctx())
        self.assertTrue(passed)

    def test_missing_signup_event_fails(self):
        with repo(
            {
                "experiment/experiment.yaml": experiment_yaml("alpha"),
                "experiment/iterate-cross-config.yaml": (
                    "mvp_mappings:\n  alpha:\n    signup_events: [signup_complete]\n"
                ),
                "src/app/page.tsx": "export default function Page() { return null; }\n",
            }
        ) as root:
            passed, details, fix = H.check_signup_events_implemented({"mvp_root": str(root)})
        self.assertFalse(passed)
        self.assertIn("signup_complete", details)
        self.assertIn("trackSignupComplete", fix)

    def test_raw_track_call_satisfies_signup_event(self):
        with repo(
            {
                "experiment/experiment.yaml": experiment_yaml("alpha"),
                "experiment/iterate-cross-config.yaml": (
                    "mvp_mappings:\n  alpha:\n    signup_events: [signup_complete]\n"
                ),
                "src/app/page.tsx": "track('signup_complete');\n",
            }
        ) as root:
            passed, _, _ = H.check_signup_events_implemented({"mvp_root": str(root)})
        self.assertTrue(passed)


class Check6PostHogTeamKeyTests(unittest.TestCase):
    def _vercel_ctx(self) -> dict:
        ctx = fixture_ctx()
        ctx.update(
            {
                "vercel_token": "tok",
                "vercel_project_id": "prj_clean",
                "vercel_team_id": "team_clean",
            }
        )
        return ctx

    def _run_check6(
        self,
        key: str = "phc_CLIENT",
        source: str = "vercel_env_set",
        resolved_file=None,
        server_result=None,
    ):
        if server_result is None:
            server_result = H.vercel_api.EnvResultAbsent()
        with patch(
            "ads_ready_static_helpers.resolve_production_posthog_key",
            return_value=(key, source, resolved_file),
        ), patch(
            "ads_ready_static_helpers.load_team_config", return_value=team_config()
        ), patch(
            "ads_ready_static_helpers.vercel_api.get_vercel_env_var",
            return_value=server_result,
        ):
            result = H.check_posthog_team_key(self._vercel_ctx())
        return result

    def test_matching_team_key_passes(self):
        passed, details, _ = self._run_check6()
        self.assertTrue(passed)
        self.assertEqual(
            details,
            "MVP NEXT_PUBLIC_POSTHOG_KEY matches team-config.yaml.team.posthog.project_api_tokens",
        )

    @patch("ads_ready_static_helpers.resolve_production_posthog_key")
    @patch("ads_ready_static_helpers.load_team_config")
    def test_mvp_key_not_in_team_config_fails(self, mock_config, mock_resolve):
        mock_resolve.return_value = ("phc_MISSING", "vercel_env_set", None)
        mock_config.return_value = team_config()
        passed, details, fix = H.check_posthog_team_key(fixture_ctx())
        self.assertFalse(passed)
        self.assertIn("team-config", details)
        self.assertIn("actual=phc_MI...SING", fix)
        self.assertIn("team.posthog.project_ids=[1, 2]", details)
        self.assertIn("team.posthog.project_api_tokens count=1", details)

    @patch("ads_ready_static_helpers.resolve_production_posthog_key")
    @patch("ads_ready_static_helpers.load_team_config", return_value=team_config())
    def test_source_fallback_key_passes_without_posthog_api_key(
        self,
        _config,
        mock_resolve,
    ):
        mock_resolve.return_value = ("phc_CLIENT", "source_fallback", "src/lib/analytics.ts")
        with patch(
            "ads_ready_static_helpers.vercel_api.get_vercel_env_var",
            return_value=H.vercel_api.EnvResultAbsent(),
        ):
            passed, details, fix = H.check_posthog_team_key(self._vercel_ctx())
        self.assertTrue(passed)
        self.assertIn("team-config.yaml.team.posthog.project_api_tokens", details)
        self.assertIsNone(fix)

    @patch("ads_ready_static_helpers.resolve_production_posthog_key")
    @patch("ads_ready_static_helpers.load_team_config", return_value={})
    def test_missing_team_config_fails(self, _config, mock_resolve):
        mock_resolve.return_value = ("phc_CLIENT", "vercel_env_set", None)
        passed, details, _fix = H.check_posthog_team_key(fixture_ctx())
        self.assertFalse(passed)
        self.assertIn("Team config not found", details)

    @patch("ads_ready_static_helpers.resolve_production_posthog_key")
    @patch("ads_ready_static_helpers.load_team_config", return_value=team_config())
    def test_check6_does_not_call_posthog_api(self, _config, mock_resolve):
        mock_resolve.return_value = ("phc_CLIENT", "vercel_env_set", None)
        with patch(
            "ads_ready_static_helpers.vercel_api.get_vercel_env_var",
            return_value=H.vercel_api.EnvResultAbsent(),
        ), patch("ads_ready_static_helpers._read_posthog_api_key") as mock_read, patch(
            "ads_ready_static_helpers._list_posthog_projects"
        ) as mock_projects, patch("ads_ready_static_helpers.subprocess.run") as mock_run:
            passed, _, _ = H.check_posthog_team_key(self._vercel_ctx())
        self.assertTrue(passed)
        mock_read.assert_not_called()
        mock_projects.assert_not_called()
        mock_run.assert_not_called()

    def test_server_key_absent_passes(self):
        passed, details, fix = self._run_check6(
            server_result=H.vercel_api.EnvResultAbsent()
        )
        self.assertTrue(passed)
        self.assertIn("NEXT_PUBLIC_POSTHOG_KEY", details)
        self.assertIsNone(fix)

    def test_server_key_same_as_client_passes(self):
        passed, details, fix = self._run_check6(
            server_result=H.vercel_api.EnvResultFound("phc_CLIENT")
        )
        self.assertTrue(passed)
        self.assertIn("NEXT_PUBLIC_POSTHOG_KEY", details)
        self.assertIsNone(fix)

    def test_server_key_empty_string_fails(self):
        passed, details, fix = self._run_check6(
            server_result=H.vercel_api.EnvResultFound("")
        )
        self.assertFalse(passed)
        self.assertIn("POSTHOG_SERVER_KEY is set to empty string", details)
        self.assertIn("JS ?? does NOT fall through", details)
        self.assertIn("Unset POSTHOG_SERVER_KEY", fix)

    def test_server_key_placeholder_fails(self):
        passed, details, fix = self._run_check6(
            server_result=H.vercel_api.EnvResultFound("phc_TEAM_KEY")
        )
        self.assertFalse(passed)
        self.assertIn("placeholder phc_TEAM_KEY", details)
        self.assertIn("no-op project", details)
        self.assertIn("Unset POSTHOG_SERVER_KEY", fix)

    def test_server_key_different_project_fails(self):
        passed, details, fix = self._run_check6(
            server_result=H.vercel_api.EnvResultFound("phc_OTHER")
        )
        self.assertFalse(passed)
        self.assertIn("different PostHog project", details)
        self.assertIn("same value as NEXT_PUBLIC_POSTHOG_KEY", details)
        self.assertIn("same value as NEXT_PUBLIC_POSTHOG_KEY", fix)

    def test_server_key_vercel_error_fails(self):
        passed, details, fix = self._run_check6(
            server_result=H.vercel_api.EnvResultError("HTTP 500")
        )
        self.assertFalse(passed)
        self.assertEqual(
            details,
            "Could not verify Vercel POSTHOG_SERVER_KEY: HTTP 500. Fix Vercel auth and retry.",
        )
        self.assertEqual(fix, "Fix Vercel auth and retry.")


class Check7SupabaseTests(unittest.TestCase):
    def test_project_ref_accessible_passes(self):
        with repo(
            {
                "experiment/experiment.yaml": experiment_yaml("alpha", "stack:\n  database: supabase\n"),
                ".env.local": "NEXT_PUBLIC_SUPABASE_URL=https://personal.supabase.co\n",
                ".vercel/project.json": '{"projectId":"prj_supabase","orgId":"team_clean"}',
            }
        ) as root, patch("ads_ready_static_helpers.load_team_config", return_value=team_config()), patch(
            "ads_ready_static_helpers.vercel_api.read_vercel_token", return_value="vercel-token"
        ), patch(
            "ads_ready_static_helpers.vercel_api.get_vercel_env_var",
            return_value=H.vercel_api.EnvResultFound("https://abc123.supabase.co"),
        ) as mock_env, patch(
            "ads_ready_static_helpers._read_token", return_value="tok"
        ), patch(
            "ads_ready_static_helpers._get_supabase_project",
            return_value={"id": "abc123", "organization_id": "org_team"},
        ):
            passed, _, _ = H.check_supabase_team_org({"mvp_root": str(root)})
        self.assertTrue(passed)
        mock_env.assert_called_with(
            "vercel-token",
            "prj_supabase",
            "team_clean",
            "NEXT_PUBLIC_SUPABASE_URL",
            target="production",
        )

    def test_missing_supabase_url_fails(self):
        with repo(
            {
                "experiment/experiment.yaml": experiment_yaml("alpha", "stack:\n  database: supabase\n"),
                ".vercel/project.json": '{"projectId":"prj_supabase","orgId":"team_clean"}',
            }
        ) as root, patch(
            "ads_ready_static_helpers.load_team_config", return_value=team_config()
        ), patch(
            "ads_ready_static_helpers.vercel_api.read_vercel_token", return_value="vercel-token"
        ), patch(
            "ads_ready_static_helpers.vercel_api.get_vercel_env_var",
            return_value=H.vercel_api.EnvResultAbsent(),
        ):
            passed, details, fix = H.check_supabase_team_org({"mvp_root": str(root)})
        self.assertFalse(passed)
        self.assertIn("absent from Vercel production env", details)
        self.assertIn("NEXT_PUBLIC_SUPABASE_URL", fix)

    def test_wrong_team_org_fails(self):
        with repo(
            {
                "experiment/experiment.yaml": experiment_yaml("alpha", "stack:\n  database: supabase\n"),
                ".vercel/project.json": '{"projectId":"prj_supabase","orgId":"team_clean"}',
            }
        ) as root, patch("ads_ready_static_helpers.load_team_config", return_value=team_config()), patch(
            "ads_ready_static_helpers.vercel_api.read_vercel_token", return_value="vercel-token"
        ), patch(
            "ads_ready_static_helpers.vercel_api.get_vercel_env_var",
            return_value=H.vercel_api.EnvResultFound("https://abc123.supabase.co"),
        ), patch(
            "ads_ready_static_helpers._read_token", return_value="tok"
        ), patch(
            "ads_ready_static_helpers._get_supabase_project",
            return_value={"id": "abc123", "organization_id": "org_personal"},
        ):
            passed, details, fix = H.check_supabase_team_org({"mvp_root": str(root)})
        self.assertFalse(passed)
        self.assertIn("org_personal", details)
        self.assertIn("org_team", fix)

    @patch("ads_ready_static_helpers.vercel_api.read_vercel_token", return_value="vercel-token")
    @patch("ads_ready_static_helpers.vercel_api.get_vercel_env_var")
    def test_vercel_supabase_url_passes(self, mock_env, _token):
        mock_env.return_value = H.vercel_api.EnvResultFound("https://abc123.supabase.co")
        with repo({"experiment/experiment.yaml": experiment_yaml("alpha", "stack:\n  database: supabase\n")}) as root, patch(
            "ads_ready_static_helpers.load_team_config", return_value=team_config()
        ), patch("ads_ready_static_helpers._read_token", return_value="tok"), patch(
            "ads_ready_static_helpers._get_supabase_project",
            return_value={"id": "abc123", "organization_id": "org_team"},
        ):
            passed, _, _ = H.check_supabase_team_org({"mvp_root": str(root), "vercel_project_id": "prj"})
        self.assertTrue(passed)

    @patch("ads_ready_static_helpers.load_team_config", return_value=team_config())
    @patch("ads_ready_static_helpers.vercel_api.read_vercel_token", return_value="vercel-token")
    @patch("ads_ready_static_helpers.vercel_api.get_vercel_env_var", return_value=H.vercel_api.EnvResultFound(""))
    def test_empty_vercel_supabase_url_fails(self, _env, _token, _config):
        with repo(
            {
                "experiment/experiment.yaml": experiment_yaml("alpha", "stack:\n  database: supabase\n"),
                ".env.local": "NEXT_PUBLIC_SUPABASE_URL=https://abc123.supabase.co\n",
                ".vercel/project.json": '{"projectId":"prj_supabase","orgId":"team_clean"}',
            }
        ) as root:
            passed, details, fix = H.check_supabase_team_org({"mvp_root": str(root)})
        self.assertFalse(passed)
        self.assertIn("empty string", details)
        self.assertIn("Vercel production env", fix)

    @patch("ads_ready_static_helpers.load_team_config", return_value={})
    def test_missing_team_config_fails(self, _config):
        with repo(
            {
                "experiment/experiment.yaml": experiment_yaml("alpha", "stack:\n  database: supabase\n"),
                ".env.local": "NEXT_PUBLIC_SUPABASE_URL=https://abc123.supabase.co\n",
            }
        ) as root:
            passed, details, _fix = H.check_supabase_team_org({"mvp_root": str(root)})
        self.assertFalse(passed)
        self.assertIn("Team config not found", details)


class Check8RailwayTests(unittest.TestCase):
    @patch("ads_ready_static_helpers.load_team_config", return_value=team_config())
    @patch("ads_ready_static_helpers._check_railway_auth", return_value="login required")
    def test_auth_missing_fails(self, _auth, _config):
        passed, details, fix = H.check_railway_team_workspace(fixture_ctx())
        self.assertFalse(passed)
        self.assertIn("login required", details)
        self.assertIn("railway login", fix)

    @patch("ads_ready_static_helpers.load_team_config", return_value=team_config())
    @patch("ads_ready_static_helpers._check_railway_auth", return_value=None)
    @patch("ads_ready_static_helpers.list_railway_projects")
    def test_project_id_match_passes(self, mock_projects, _auth, _config):
        mock_projects.return_value = [{"id": "rp_1", "name": "alpha", "workspace_id": "ws_team"}]
        with repo(
            {
                "experiment/experiment.yaml": experiment_yaml("alpha", "stack:\n  database: railway\n"),
                "railway.json": '{"projectId":"rp_1"}',
            }
        ) as root:
            passed, _, _ = H.check_railway_team_workspace({"mvp_root": str(root)})
        self.assertTrue(passed)

    @patch("ads_ready_static_helpers.load_team_config", return_value=team_config())
    @patch("ads_ready_static_helpers._check_railway_auth", return_value=None)
    @patch("ads_ready_static_helpers.list_railway_projects", return_value=[])
    def test_no_matching_project_fails(self, _projects, _auth, _config):
        with repo(
            {
                "experiment/experiment.yaml": experiment_yaml("alpha", "stack:\n  database: railway\n"),
                "railway.json": '{"projectId":"rp_1"}',
            }
        ) as root:
            passed, details, fix = H.check_railway_team_workspace({"mvp_root": str(root)})
        self.assertFalse(passed)
        self.assertIn("not accessible", details)
        self.assertIn("team project", fix)

    @patch("ads_ready_static_helpers.load_team_config", return_value=team_config())
    @patch("ads_ready_static_helpers._check_railway_auth", return_value=None)
    @patch("ads_ready_static_helpers.list_railway_projects")
    def test_wrong_workspace_fails(self, mock_projects, _auth, _config):
        mock_projects.return_value = [{"id": "rp_1", "name": "alpha", "workspace_id": "ws_personal"}]
        with repo(
            {
                "experiment/experiment.yaml": experiment_yaml("alpha", "stack:\n  database: railway\n"),
                "railway.json": '{"projectId":"rp_1"}',
            }
        ) as root:
            passed, details, fix = H.check_railway_team_workspace({"mvp_root": str(root)})
        self.assertFalse(passed)
        self.assertIn("ws_personal", details)
        self.assertIn("ws_team", fix)

    @patch("ads_ready_static_helpers.load_team_config", return_value={})
    def test_missing_team_config_fails(self, _config):
        passed, details, _fix = H.check_railway_team_workspace(fixture_ctx())
        self.assertFalse(passed)
        self.assertIn("Team config not found", details)


class Check9VercelTests(unittest.TestCase):
    def test_linked_project_found_passes(self):
        with patch("ads_ready_static_helpers.load_team_config", return_value=team_config()), patch(
            "ads_ready_static_helpers.vercel_api.read_vercel_token", return_value="vercel-token"
        ), patch(
            "ads_ready_static_helpers.vercel_api.find_project", return_value={"id": "prj_clean"}
        ) as mock_find:
            passed, details, _ = H.check_vercel_team_account(fixture_ctx())
        self.assertTrue(passed)
        self.assertIn("API-accessible", details)
        mock_find.assert_called_with(
            "vercel-token", team_id="team_clean", project_id_or_name="prj_clean"
        )

    @patch(
        "ads_ready_static_helpers.load_team_config",
        return_value=team_config(vercel={"team_ids": ["team_other"]}),
    )
    def test_wrong_team_project_fails(self, _config):
        passed, details, fix = H.check_vercel_team_account(fixture_ctx())
        self.assertFalse(passed)
        self.assertIn("prj_clean", details)
        self.assertIn("team_other", fix)
        self.assertIn("Transfer", fix)

    @patch("ads_ready_static_helpers.load_team_config", return_value=team_config())
    def test_missing_project_link_fails(self, _config):
        with repo({"experiment/experiment.yaml": experiment_yaml("alpha", "stack:\n  services:\n    - hosting: vercel\n")}) as root:
            passed, details, fix = H.check_vercel_team_account({"mvp_root": str(root)})
        self.assertFalse(passed)
        self.assertIn("orgId", details)
        self.assertIn("vercel link", fix)

    @patch("ads_ready_static_helpers.load_team_config", return_value={})
    def test_missing_team_config_fails(self, _config):
        passed, details, _fix = H.check_vercel_team_account(fixture_ctx())
        self.assertFalse(passed)
        self.assertIn("Team config not found", details)

    @patch("ads_ready_static_helpers.load_team_config", return_value=team_config())
    @patch("ads_ready_static_helpers.vercel_api.read_vercel_token", return_value=None)
    def test_missing_vercel_token_fails(self, _token, _config):
        passed, details, fix = H.check_vercel_team_account(fixture_ctx())
        self.assertFalse(passed)
        self.assertIn("Vercel token is missing", details)
        self.assertIn("vercel login", fix)

    @patch("ads_ready_static_helpers.load_team_config", return_value=team_config())
    @patch("ads_ready_static_helpers.vercel_api.read_vercel_token", return_value="vercel-token")
    @patch("ads_ready_static_helpers.vercel_api.find_project", return_value=None)
    def test_project_link_must_be_api_accessible(self, _find, _token, _config):
        passed, details, fix = H.check_vercel_team_account(fixture_ctx())
        self.assertFalse(passed)
        self.assertIn("not accessible", details)
        self.assertIn("Re-link", fix)

    def test_project_id_matching_existing_project_name_fails(self):
        with repo(
            {
                "experiment/experiment.yaml": experiment_yaml(
                    "alpha", "stack:\n  services:\n    - hosting: vercel\n"
                ),
                ".vercel/project.json": '{"projectId":"stale-project-name","orgId":"team_clean"}',
            }
        ) as root, patch(
            "ads_ready_static_helpers.load_team_config", return_value=team_config()
        ), patch(
            "ads_ready_static_helpers.vercel_api.read_vercel_token", return_value="vercel-token"
        ), patch(
            "ads_ready_static_helpers.vercel_api.find_project",
            return_value={"id": "prj_actual", "name": "stale-project-name"},
        ):
            passed, details, fix = H.check_vercel_team_account({"mvp_root": str(root)})
        self.assertFalse(passed)
        self.assertIn("stale-project-name", details)
        self.assertIn("does not match any team project by ID", details)
        self.assertIn("matching by name is not strict-safe", details)
        self.assertIn("vercel link", fix)


class Check10StripeTests(unittest.TestCase):
    @patch("ads_ready_static_helpers.load_team_config", return_value=team_config())
    @patch("ads_ready_static_helpers.vercel_api.read_vercel_token", return_value=None)
    def test_missing_mvp_key_fails(self, _token, _config):
        with repo({"experiment/experiment.yaml": experiment_yaml("alpha", "stack:\n  payment: stripe\n")}) as root:
            passed, details, fix = H.check_stripe_team_account({"mvp_root": str(root)})
        self.assertFalse(passed)
        self.assertIn("STRIPE_SECRET_KEY", details)
        self.assertIn("STRIPE_SECRET_KEY", fix)

    @patch("ads_ready_static_helpers.load_team_config", return_value=team_config())
    @patch("ads_ready_static_helpers.stripe_api.get_account_id")
    @patch("ads_ready_static_helpers.vercel_api.read_vercel_token", return_value="vercel-token")
    @patch(
        "ads_ready_static_helpers.vercel_api.get_vercel_env_var",
        return_value=H.vercel_api.EnvResultFound("sk_mvp"),
    )
    def test_matching_account_passes(self, mock_env, _token, mock_account, _config):
        mock_account.return_value = "acct_team"
        with repo(
            {
                "experiment/experiment.yaml": experiment_yaml("alpha", "stack:\n  payment: stripe\n"),
                ".env.local": "STRIPE_SECRET_KEY=sk_personal\n",
                ".vercel/project.json": '{"projectId":"prj_stripe","orgId":"team_clean"}',
            }
        ) as root:
            passed, _, _ = H.check_stripe_team_account({"mvp_root": str(root)})
        self.assertTrue(passed)
        mock_env.assert_called_with(
            "vercel-token",
            "prj_stripe",
            "team_clean",
            "STRIPE_SECRET_KEY",
            target="production",
        )
        mock_account.assert_called_with("sk_mvp")

    @patch("ads_ready_static_helpers.load_team_config", return_value=team_config())
    @patch("ads_ready_static_helpers.stripe_api.get_account_id")
    @patch("ads_ready_static_helpers.vercel_api.read_vercel_token", return_value="vercel-token")
    @patch(
        "ads_ready_static_helpers.vercel_api.get_vercel_env_var",
        return_value=H.vercel_api.EnvResultFound("sk_mvp"),
    )
    def test_mismatched_account_fails(self, _env, _token, mock_account, _config):
        mock_account.return_value = "acct_personal"
        with repo(
            {
                "experiment/experiment.yaml": experiment_yaml("alpha", "stack:\n  payment: stripe\n"),
                ".vercel/project.json": '{"projectId":"prj_stripe","orgId":"team_clean"}',
            }
        ) as root:
            passed, details, fix = H.check_stripe_team_account({"mvp_root": str(root)})
        self.assertFalse(passed)
        self.assertIn("acct_personal", details)
        self.assertIn("acct_team", fix)

    @patch("ads_ready_static_helpers.load_team_config", return_value=team_config())
    @patch("ads_ready_static_helpers.vercel_api.read_vercel_token", return_value="vercel-token")
    @patch("ads_ready_static_helpers.vercel_api.get_vercel_env_var", return_value=H.vercel_api.EnvResultAbsent())
    @patch("ads_ready_static_helpers.stripe_api.get_account_id")
    def test_local_stripe_key_does_not_satisfy_check(self, mock_account, _env, _token, _config):
        with repo(
            {
                "experiment/experiment.yaml": experiment_yaml("alpha", "stack:\n  payment: stripe\n"),
                ".env.local": "STRIPE_SECRET_KEY=sk_mvp\n",
                ".vercel/project.json": '{"projectId":"prj_stripe","orgId":"team_clean"}',
            }
        ) as root:
            passed, details, fix = H.check_stripe_team_account({"mvp_root": str(root)})
        self.assertFalse(passed)
        self.assertIn("diagnostic only", details)
        self.assertIn("Vercel production env", fix)
        mock_account.assert_not_called()

    @patch("ads_ready_static_helpers.load_team_config", return_value={})
    def test_missing_team_config_fails(self, _config):
        passed, details, _fix = H.check_stripe_team_account(fixture_ctx())
        self.assertFalse(passed)
        self.assertIn("Team config not found", details)


class Check11EventsImplementedTests(unittest.TestCase):
    def test_clean_fixture_passes(self):
        passed, _, _ = H.check_events_yaml_all_implemented(fixture_ctx())
        self.assertTrue(passed)

    def test_missing_event_impl_fixture_fails(self):
        passed, details, fix = H.check_events_yaml_all_implemented(
            fixture_ctx("broken_events_yaml_missing_impl")
        )
        self.assertFalse(passed)
        self.assertIn("signup_complete", details)
        self.assertIn("EVENTS.yaml", fix)

    def test_requires_filter_skips_non_applicable_event(self):
        with repo(
            {
                "experiment/experiment.yaml": experiment_yaml("alpha"),
                "experiment/EVENTS.yaml": events_yaml(
                    "  paid_signup:\n    funnel_stage: monetize\n    requires: [payment]\n"
                ),
                "src/app/page.tsx": "export default function Page() { return null; }\n",
            }
        ) as root:
            passed, _, _ = H.check_events_yaml_all_implemented({"mvp_root": str(root)})
        self.assertTrue(passed)

    def test_unknown_requires_value_fails_as_typo(self):
        with repo(
            {
                "experiment/experiment.yaml": experiment_yaml("alpha"),
                "experiment/EVENTS.yaml": events_yaml(
                    "  paid_signup:\n    funnel_stage: monetize\n    requires: [paymnt]\n"
                ),
                "src/app/page.tsx": "export default function Page() { return null; }\n",
            }
        ) as root:
            passed, details, fix = H.check_events_yaml_all_implemented({"mvp_root": str(root)})
        self.assertFalse(passed)
        self.assertIn("paid_signup", details)
        self.assertIn("paymnt", details)
        self.assertIn("typo", fix)

    def test_unknown_archetypes_value_fails_as_typo(self):
        with repo(
            {
                "experiment/experiment.yaml": experiment_yaml("alpha"),
                "experiment/EVENTS.yaml": events_yaml(
                    "  landing_viewed:\n    funnel_stage: landing\n    archetypes: [webap]\n"
                ),
                "src/app/page.tsx": "export default function Page() { return null; }\n",
            }
        ) as root:
            passed, details, fix = H.check_events_yaml_all_implemented({"mvp_root": str(root)})
        self.assertFalse(passed)
        self.assertIn("landing_viewed", details)
        self.assertIn("webap", details)
        self.assertIn("known archetypes", details)
        self.assertIn("web-app", details)
        self.assertIn("typo", fix)


class Phase2StaticChecksTests(unittest.TestCase):
    def test_p2_a_clean_fixture_passes(self):
        with repo(phase2_fixture_files()) as root:
            passed, details, _ = H.check_phase2_pay_intent_event_and_callsite({"mvp_root": str(root)})
        self.assertTrue(passed)
        self.assertIn("utm_campaign", details)
        self.assertIn("price_cents", details)

    def test_p2_a_missing_price_cents_event_property_fails(self):
        with repo(
            phase2_fixture_files(
                {
                    "experiment/EVENTS.yaml": events_yaml(
                        "  pay_intent:\n"
                        "    funnel_stage: monetize\n"
                        "    properties:\n"
                        "      plan: { type: string, required: true }\n"
                        "      gclid: { type: string, required: false }\n"
                        "      utm_campaign: { type: string, required: true }\n"
                    )
                }
            )
        ) as root:
            passed, details, fix = H.check_phase2_pay_intent_event_and_callsite({"mvp_root": str(root)})
        self.assertFalse(passed)
        self.assertIn("price_cents", details)
        self.assertIn("required", details)
        self.assertIn("price_cents", fix)

    def test_p2_a_price_cents_string_type_fails(self):
        with repo(
            phase2_fixture_files(
                {
                    "experiment/EVENTS.yaml": events_yaml(
                        "  pay_intent:\n"
                        "    funnel_stage: monetize\n"
                        "    properties:\n"
                        "      plan: { type: string, required: true }\n"
                        "      price_cents: { type: string, required: true }\n"
                        "      gclid: { type: string, required: false }\n"
                        "      utm_campaign: { type: string, required: true }\n"
                    )
                }
            )
        ) as root:
            passed, details, fix = H.check_phase2_pay_intent_event_and_callsite({"mvp_root": str(root)})
        self.assertFalse(passed)
        self.assertIn("price_cents.type", details)
        self.assertIn("number", details)
        self.assertIn("type: number", fix)

    def test_p2_a_missing_utm_campaign_call_arg_fails(self):
        with repo(
            phase2_fixture_files(
                {
                    "src/components/UpgradeCTA.tsx": (
                        'import { trackPayIntent } from "@/lib/events";\n'
                        "export function UpgradeCTA({ user, hasActivated, gclid, utm_campaign }) {\n"
                        "  const canUpgrade = user && hasActivated;\n"
                        "  if (!canUpgrade) return null;\n"
                        '  trackPayIntent({ plan: "pro", price_cents: 1900, gclid });\n'
                        "  return <button>Upgrade to Pro</button>;\n"
                        "}\n"
                    )
                }
            )
        ) as root:
            passed, details, fix = H.check_phase2_pay_intent_event_and_callsite({"mvp_root": str(root)})
        self.assertFalse(passed)
        self.assertIn("utm_campaign", details)
        self.assertIn("trackPayIntent", fix)

    def test_p2_a_missing_price_cents_call_arg_fails(self):
        with repo(
            phase2_fixture_files(
                {
                    "src/components/UpgradeCTA.tsx": (
                        'import { trackPayIntent } from "@/lib/events";\n'
                        "export function UpgradeCTA({ user, hasActivated, gclid, utm_campaign }) {\n"
                        "  const canUpgrade = user && hasActivated;\n"
                        "  if (!canUpgrade) return null;\n"
                        '  trackPayIntent({ plan: "pro", gclid, utm_campaign });\n'
                        "  return <button>Upgrade to Pro</button>;\n"
                        "}\n"
                    )
                }
            )
        ) as root:
            passed, details, fix = H.check_phase2_pay_intent_event_and_callsite({"mvp_root": str(root)})
        self.assertFalse(passed)
        self.assertIn("price_cents", details)
        self.assertIn("price_cents", fix)

    def test_p2_b_clean_fixture_passes(self):
        with repo(phase2_fixture_files()) as root:
            passed, details, _ = H.check_phase2_pay_intent_route({"mvp_root": str(root)})
        self.assertTrue(passed)
        self.assertIn("/api/pay-intent", details)

    def test_p2_b_missing_utm_campaign_row_value_fails(self):
        with repo(
            phase2_fixture_files(
                {
                    "src/app/api/pay-intent/route.ts": (
                        "export async function POST(request: Request) {\n"
                        "  const { gclid } = await request.json();\n"
                        '  await supabase.from("pay_intent").insert({ user_id: "user_1", gclid });\n'
                        "  return Response.json({ ok: true });\n"
                        "}\n"
                    )
                }
            )
        ) as root:
            passed, details, fix = H.check_phase2_pay_intent_route({"mvp_root": str(root)})
        self.assertFalse(passed)
        self.assertIn("utm_campaign", details)
        self.assertIn("insert", fix)

    def test_p2_c_clean_fixture_passes(self):
        with repo(phase2_fixture_files()) as root:
            passed, details, _ = H.check_phase2_pay_intent_migration({"mvp_root": str(root)})
        self.assertTrue(passed)
        self.assertIn("auth.users", details)

    def test_p2_c_missing_rls_fails(self):
        with repo(
            phase2_fixture_files(
                {
                    "supabase/migrations/20260601000000_pay_intent.sql": (
                        "create table public.pay_intent (\n"
                        "  id uuid primary key,\n"
                        "  user_id uuid references auth.users(id),\n"
                        "  gclid text,\n"
                        "  utm_campaign text\n"
                        ");\n"
                    )
                }
            )
        ) as root:
            passed, details, fix = H.check_phase2_pay_intent_migration({"mvp_root": str(root)})
        self.assertFalse(passed)
        self.assertIn("RLS", details)
        self.assertIn("row level security", fix)

    def test_p2_d_clean_fixture_passes(self):
        with repo(phase2_fixture_files()) as root:
            passed, details, _ = H.check_phase2_upgrade_cta_guard({"mvp_root": str(root)})
        self.assertTrue(passed)
        self.assertIn("guards", details)

    def test_p2_d_unconditional_upgrade_fails(self):
        with repo(
            phase2_fixture_files(
                {
                    "src/components/UpgradeCTA.tsx": (
                        'import { trackPayIntent } from "@/lib/events";\n'
                        "export function UpgradeCTA({ gclid, utm_campaign }) {\n"
                        '  trackPayIntent({ plan: "pro", price_cents: 1900, gclid, utm_campaign });\n'
                        "  return <button>Upgrade to Pro</button>;\n"
                        "}\n"
                    )
                }
            )
        ) as root:
            passed, details, fix = H.check_phase2_upgrade_cta_guard({"mvp_root": str(root)})
        self.assertFalse(passed)
        self.assertIn("render guard", details)
        self.assertIn("authenticated", fix)

    def test_p2_e_clean_fixture_passes(self):
        with repo(phase2_fixture_files({"src/lib/unrelated-billing.ts": 'import Stripe from "stripe";\n'})) as root:
            passed, details, _ = H.check_phase2_no_payment_provider_on_fake_door_path(
                {"mvp_root": str(root)}
            )
        self.assertTrue(passed)
        self.assertIn("No payment provider import", details)

    def test_p2_e_reachable_stripe_import_fails(self):
        with repo(
            phase2_fixture_files(
                {
                    "src/lib/checkout.ts": 'import Stripe from "stripe";\nexport const stripe = Stripe;\n',
                    "src/app/api/pay-intent/route.ts": (
                        'import { stripe } from "@/lib/checkout";\n'
                        "export async function POST(request: Request) {\n"
                        "  const { gclid, utm_campaign } = await request.json();\n"
                        "  void stripe;\n"
                        '  await supabase.from("pay_intent").insert({ user_id: "user_1", gclid, utm_campaign });\n'
                        "  return Response.json({ ok: true });\n"
                        "}\n"
                    ),
                }
            )
        ) as root:
            passed, details, fix = H.check_phase2_no_payment_provider_on_fake_door_path(
                {"mvp_root": str(root)}
            )
        self.assertFalse(passed)
        self.assertIn("stripe", details.lower())
        self.assertIn("Remove", fix)

    def test_phase2_predicate(self):
        self.assertFalse(H.applies_if_phase_2({"phase_2": False}))
        self.assertTrue(H.applies_if_phase_2({"phase_2": True}))


class Check12UnauthorizedTrackTests(unittest.TestCase):
    def test_clean_fixture_passes(self):
        passed, _, _ = H.check_no_unauthorized_track_calls(fixture_ctx())
        self.assertTrue(passed)

    def test_raw_unknown_track_fails(self):
        with repo(
            {
                "experiment/experiment.yaml": experiment_yaml("alpha"),
                "experiment/EVENTS.yaml": events_yaml(
                    "  landing_viewed:\n    funnel_stage: landing\n"
                ),
                "src/app/page.tsx": "track('mystery_event');\n",
            }
        ) as root:
            passed, details, fix = H.check_no_unauthorized_track_calls({"mvp_root": str(root)})
        self.assertFalse(passed)
        self.assertIn("mystery_event", details)
        self.assertIn("Add it to EVENTS.yaml", fix)

    def test_unknown_wrapper_track_fails(self):
        with repo(
            {
                "experiment/experiment.yaml": experiment_yaml("alpha"),
                "experiment/EVENTS.yaml": events_yaml("{}\n"),
                "src/app/page.tsx": "trackMysteryEvent();\n",
            }
        ) as root:
            passed, details, _ = H.check_no_unauthorized_track_calls({"mvp_root": str(root)})
        self.assertFalse(passed)
        self.assertIn("mystery_event", details)


class Check13IdentifyTests(unittest.TestCase):
    def test_clean_fixture_passes_direct_identify(self):
        passed, details, _ = H.check_identify_in_signup(fixture_ctx())
        self.assertTrue(passed)
        self.assertIn("identify", details)

    def test_signup_without_identify_fixture_fails(self):
        passed, details, fix = H.check_identify_in_signup(
            fixture_ctx("broken_signup_no_identify")
        )
        self.assertFalse(passed)
        self.assertIn("signup_complete", details)
        self.assertIn("identify", fix)

    def test_transitive_auth_utility_identify_passes(self):
        with repo(
            {
                "experiment/experiment.yaml": experiment_yaml("alpha"),
                "src/app/page.tsx": (
                    'import { onSignup } from "@/lib/auth-client";\n'
                    "export default function Page() { trackSignupComplete(); onSignup(); return null; }\n"
                ),
                "src/lib/auth-client.ts": "export function onSignup() { identify('user_1'); }\n",
            }
        ) as root:
            passed, details, _ = H.check_identify_in_signup({"mvp_root": str(root)})
        self.assertTrue(passed)
        self.assertIn("auth-client", details)


class ResolveProductionPostHogKeyTests(unittest.TestCase):
    @patch("ads_ready_static_helpers.vercel_api.read_vercel_token", return_value="tok")
    @patch("ads_ready_static_helpers.vercel_api.get_vercel_env_var")
    def test_vercel_env_set_source_tag(self, mock_env, _token):
        mock_env.return_value = H.vercel_api.EnvResultFound("phc_ENV")
        with repo({"experiment/experiment.yaml": experiment_yaml("alpha")}) as root:
            key, source, file = H.resolve_production_posthog_key(
                {"mvp_root": str(root), "vercel_project_id": "prj"}
            )
        self.assertEqual((key, source, file), ("phc_ENV", "vercel_env_set", None))

    @patch("ads_ready_static_helpers.vercel_api.read_vercel_token", return_value="tok")
    @patch("ads_ready_static_helpers.vercel_api.get_vercel_env_var")
    def test_vercel_env_empty_or_placeholder_source_tag(self, mock_env, _token):
        mock_env.return_value = H.vercel_api.EnvResultFound("")
        with repo({"experiment/experiment.yaml": experiment_yaml("alpha")}) as root:
            key, source, file = H.resolve_production_posthog_key(
                {"mvp_root": str(root), "vercel_project_id": "prj"}
            )
        self.assertEqual((key, source, file), ("", "vercel_env_empty_or_placeholder", None))

    @patch("ads_ready_static_helpers.vercel_api.read_vercel_token", return_value="tok")
    @patch("ads_ready_static_helpers.vercel_api.get_vercel_env_var")
    def test_vercel_env_error_source_tag(self, mock_env, _token):
        mock_env.return_value = H.vercel_api.EnvResultError("HTTP 500")
        with repo({"experiment/experiment.yaml": experiment_yaml("alpha")}) as root:
            key, source, file = H.resolve_production_posthog_key(
                {"mvp_root": str(root), "vercel_project_id": "prj"}
            )
        self.assertEqual((key, source, file), (None, "vercel_env_error", None))

    @patch("ads_ready_static_helpers.vercel_api.read_vercel_token", return_value=None)
    def test_source_fallback_single_file_pass(self, _token):
        with repo({"src/lib/analytics.ts": analytics_ts("alpha", "phc_SOURCE")}) as root:
            key, source, file = H.resolve_production_posthog_key({"mvp_root": str(root)})
        self.assertEqual((key, source, file), ("phc_SOURCE", "source_fallback", "src/lib/analytics.ts"))

    @patch("ads_ready_static_helpers.vercel_api.read_vercel_token", return_value=None)
    def test_source_fallback_multiple_identical_pass(self, _token):
        with repo(
            {
                "src/lib/analytics.ts": analytics_ts("alpha", "phc_SAME"),
                "src/lib/analytics-server.ts": analytics_ts("alpha", "phc_SAME"),
            }
        ) as root:
            key, source, file = H.resolve_production_posthog_key({"mvp_root": str(root)})
        self.assertEqual((key, source, file), ("phc_SAME", "source_fallback", "src/lib/analytics.ts"))

    @patch("ads_ready_static_helpers.vercel_api.read_vercel_token", return_value=None)
    def test_source_fallback_placeholder_fails_with_source_tag(self, _token):
        with repo({"src/lib/analytics.ts": analytics_ts("alpha", "phc_TEAM_KEY")}) as root:
            key, source, file = H.resolve_production_posthog_key({"mvp_root": str(root)})
        self.assertEqual((key, source, file), ("phc_TEAM_KEY", "source_fallback", "src/lib/analytics.ts"))

    @patch("ads_ready_static_helpers.vercel_api.read_vercel_token", return_value=None)
    def test_source_fallback_inconsistent_fails(self, _token):
        with repo(
            {
                "src/lib/analytics.ts": analytics_ts("alpha", "phc_ONE"),
                "src/lib/analytics-server.ts": analytics_ts("alpha", "phc_TWO"),
            }
        ) as root:
            key, source, file = H.resolve_production_posthog_key({"mvp_root": str(root)})
        self.assertEqual((key, source, file), (None, "source_fallback_inconsistent", None))

    @patch("ads_ready_static_helpers.vercel_api.read_vercel_token", return_value=None)
    def test_missing_source_tag(self, _token):
        with repo({}) as root:
            key, source, file = H.resolve_production_posthog_key({"mvp_root": str(root)})
        self.assertEqual((key, source, file), (None, "missing", None))


class AppliesPredicateTests(unittest.TestCase):
    def test_iterate_cross_signup_events_predicate(self):
        self.assertTrue(H.applies_if_iterate_cross_config_has_signup_events(fixture_ctx()))
        with repo({"experiment/experiment.yaml": experiment_yaml("alpha")}) as root:
            self.assertFalse(
                H.applies_if_iterate_cross_config_has_signup_events({"mvp_root": str(root)})
            )

    def test_stack_predicates(self):
        with repo(
            {
                "experiment/experiment.yaml": experiment_yaml(
                    "alpha",
                    "stack:\n  database: supabase\n  payment: stripe\n  services:\n    - hosting: vercel\n",
                )
            }
        ) as root:
            ctx = {"mvp_root": str(root)}
            self.assertTrue(H.applies_if_stack_database_supabase(ctx))
            self.assertFalse(H.applies_if_stack_database_railway(ctx))
            self.assertTrue(H.applies_if_stack_hosting_vercel(ctx))
            self.assertTrue(H.applies_if_stack_payment_stripe(ctx))

    def test_provider_predicates_fall_back_to_artifacts_when_stack_has_typos(self):
        with repo(
            {
                "experiment/experiment.yaml": experiment_yaml(
                    "alpha",
                    "stack:\n"
                    "  database: supabsae\n"
                    "  payment: striep\n"
                    "  services:\n"
                    "    - hosting: vecel\n",
                ),
                ".env.local": (
                    "NEXT_PUBLIC_SUPABASE_URL=https://abc123.supabase.co\n"
                    "DATABASE_URL=postgres://user:pass@containers-us-west-1.railway.app:5432/db\n"
                    "STRIPE_SECRET_KEY=sk_test_local\n"
                ),
                ".vercel/project.json": '{"projectId":"prj_artifacts","orgId":"team_clean"}',
            }
        ) as root:
            ctx = {"mvp_root": str(root)}
            self.assertTrue(H.applies_if_stack_database_supabase(ctx))
            self.assertTrue(H.applies_if_stack_database_railway(ctx))
            self.assertTrue(H.applies_if_stack_hosting_vercel(ctx))
            self.assertTrue(H.applies_if_stack_payment_stripe(ctx))

    @patch("ads_ready_static_helpers.stripe_api.get_account_id", return_value="acct_team")
    @patch("ads_ready_static_helpers.vercel_api.read_vercel_token", return_value="vercel-token")
    @patch(
        "ads_ready_static_helpers.vercel_api.get_vercel_env_var",
        return_value=H.vercel_api.EnvResultFound("sk_test_mvp"),
    )
    @patch("ads_ready_static_helpers.load_team_config", return_value=team_config())
    def test_stripe_check_applies_and_runs_when_stack_payment_has_typo_but_env_has_key(
        self,
        _config,
        _env,
        _token,
        _account,
    ):
        with repo(
            {
                "experiment/experiment.yaml": experiment_yaml(
                    "alpha",
                    "stack:\n  payment: striep\n",
                ),
                ".env.local": "STRIPE_SECRET_KEY=sk_test_local\n",
                ".vercel/project.json": '{"projectId":"prj_stripe","orgId":"team_clean"}',
            }
        ) as root:
            ctx = {"mvp_root": str(root)}
            self.assertTrue(H.applies_if_stack_payment_stripe(ctx))
            passed, details, _fix = H.check_10(ctx)

        self.assertTrue(passed)
        self.assertIn("acct_team", details)

    def test_events_yaml_predicate(self):
        self.assertTrue(H.applies_if_events_yaml_exists(fixture_ctx()))
        self.assertFalse(H.applies_if_events_yaml_exists(fixture_ctx("broken_no_analytics_import")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
