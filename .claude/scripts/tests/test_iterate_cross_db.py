#!/usr/bin/env python3
"""Tests for .claude/scripts/lib/iterate_cross_db.py.

Pure-function units: normalize_name, fuzzy_match_projects, sanity flags.
Network code (_management_api_query) is isolated and tested by monkeypatch.

Run:
  python3 .claude/scripts/tests/test_iterate_cross_db.py
  # OR:
  python3 -m pytest .claude/scripts/tests/test_iterate_cross_db.py -v
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import iterate_cross_db as db  # noqa: E402
import iterate_cross_verdicts as verdicts  # noqa: E402


VALID_GCLID = "Cj0KCQjw" + ("a" * 40)
JUNK_GCLID = "manual-test-gclid"
REGISTRY_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "patterns", "state-registry.json")
)
FIXTURES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "fixtures", "iterate-cross"))


class FakeHTTPResponse:
    def __init__(self, status: int, body: str):
        self.status = status
        self._body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body

    def getcode(self):
        return self.status


def load_iterate_cross_verify(state_id: str) -> str:
    with open(REGISTRY_PATH) as f:
        entry = json.load(f)["iterate-cross"][state_id]
    if isinstance(entry, dict):
        return entry["verify"]
    return entry


class NormalizeNameTests(unittest.TestCase):
    def test_strips_punctuation(self):
        self.assertEqual(db.normalize_name("stylica-ai"), "stylicaai")
        self.assertEqual(db.normalize_name("agent-cost-monitor"), "agentcostmonitor")

    def test_handles_empty_and_none(self):
        self.assertEqual(db.normalize_name(""), "")
        self.assertEqual(db.normalize_name(None), "")

    def test_lowercases(self):
        self.assertEqual(db.normalize_name("DiArly"), "diarly")


class FuzzyMatchProjectsTests(unittest.TestCase):
    def setUp(self):
        self.projects = [
            {"id": "ref_stylica", "name": "stylica-ai"},
            {"id": "ref_neuralpost", "name": "neuralpost-prod"},
            {"id": "ref_diarly", "name": "diarly"},
            {"id": "ref_agentcost_v2", "name": "agent-cost-monitor"},
            {"id": "ref_staging_stylica", "name": "stylica-ai-staging"},
        ]

    def test_exact_match_wins(self):
        result = db.fuzzy_match_projects(["stylica-ai"], self.projects)
        self.assertEqual(result["stylica-ai"]["id"], "ref_stylica")
        self.assertEqual(result["stylica-ai"]["match_type"], "exact")

    def test_project_name_contains_mvp(self):
        # 'neuralpost' MVP → 'neuralpost-prod' project (only one candidate)
        result = db.fuzzy_match_projects(["neuralpost"], self.projects)
        self.assertEqual(result["neuralpost"]["id"], "ref_neuralpost")
        self.assertEqual(result["neuralpost"]["match_type"], "project_contains_mvp")

    def test_ambiguous_project_contains_mvp(self):
        # 'stylica' → both 'stylica-ai' (exact) doesn't apply here; both
        # 'stylica-ai' and 'stylica-ai-staging' CONTAIN 'stylica'.
        projects_no_exact = [
            {"id": "ref_a", "name": "stylica-ai"},
            {"id": "ref_b", "name": "stylica-ai-staging"},
        ]
        result = db.fuzzy_match_projects(["stylica"], projects_no_exact)
        self.assertEqual(result["stylica"]["match_type"], "ambiguous_project_contains_mvp")
        # Prefer shortest (less staging-likely) name
        self.assertEqual(result["stylica"]["id"], "ref_a")
        self.assertEqual(result["stylica"]["alternatives"], ["ref_b"])

    def test_mvp_contains_project(self):
        # 'agent-cost-monitor-v2' → 'agent-cost-monitor' (project name is substring of MVP)
        result = db.fuzzy_match_projects(["agent-cost-monitor-v2"], self.projects)
        self.assertEqual(result["agent-cost-monitor-v2"]["match_type"], "mvp_contains_project")
        self.assertEqual(result["agent-cost-monitor-v2"]["id"], "ref_agentcost_v2")

    def test_no_match_returns_none(self):
        result = db.fuzzy_match_projects(["unknown-mvp"], self.projects)
        self.assertIsNone(result["unknown-mvp"])

    def test_empty_mvp_name_returns_none(self):
        result = db.fuzzy_match_projects([""], self.projects)
        self.assertIsNone(result[""])


class SupabaseTokenResolutionTests(unittest.TestCase):
    def test_env_token_wins_over_file_and_keychain(self):
        with tempfile.TemporaryDirectory() as td:
            token_path = Path(td) / ".supabase" / "access-token"
            token_path.parent.mkdir(parents=True)
            token_path.write_text("file-token\n")
            with patch.dict(os.environ, {"SUPABASE_ACCESS_TOKEN": "env-token"}, clear=False), \
                 patch("iterate_cross_db.Path.home", return_value=Path(td)), \
                 patch("iterate_cross_db._read_token_from_keychain", return_value="keychain-token"):
                self.assertEqual(db._read_token(), "env-token")

    def test_file_token_wins_over_keychain_when_env_absent(self):
        with tempfile.TemporaryDirectory() as td:
            token_path = Path(td) / ".supabase" / "access-token"
            token_path.parent.mkdir(parents=True)
            token_path.write_text("file-token\n")
            with patch.dict(os.environ, {}, clear=True), \
                 patch("iterate_cross_db.Path.home", return_value=Path(td)), \
                 patch("iterate_cross_db._read_token_from_keychain", return_value="keychain-token"):
                self.assertEqual(db._read_token(), "file-token")

    def test_keychain_used_after_env_and_file_absent(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {}, clear=True), \
                 patch("iterate_cross_db.Path.home", return_value=Path(td)), \
                 patch("iterate_cross_db._read_token_from_keychain", return_value="keychain-token"):
                self.assertEqual(db._read_token(), "keychain-token")


class DiscoverSignupTablesTests(unittest.TestCase):
    """The discover_signup_tables function calls _management_api_query.
    Patch that to return canned schema rows; assert correct prioritization."""

    @patch("iterate_cross_db._management_api_query")
    def test_picks_signup_table_first(self, mock_api):
        # Catalog from a hospitica-like project: only public.signups + public.access_tokens
        mock_api.return_value = [
            {"table_name": "access_tokens", "columns": "id,token,expires_at"},
            {"table_name": "signups", "columns": "id,email,created_at"},
            {"table_name": "users", "columns": "id,email,inserted_at"},
        ]
        tables = db.discover_signup_tables("test-ref")
        names = [t["table"] for t in tables]
        # signups (priority 0) before users (priority 6)
        self.assertEqual(names[0], "signups")
        # access_tokens does not match any pattern → excluded
        self.assertNotIn("access_tokens", names)

    @patch("iterate_cross_db._management_api_query")
    def test_finds_timestamp_column(self, mock_api):
        mock_api.return_value = [
            {"table_name": "waitlist", "columns": "id,email,created_at,name"},
            {"table_name": "early_access", "columns": "id,email"},  # no ts
        ]
        tables = db.discover_signup_tables("test-ref")
        by_name = {t["table"]: t for t in tables}
        self.assertEqual(by_name["waitlist"]["timestamp_column"], "created_at")
        self.assertIsNone(by_name["early_access"]["timestamp_column"])

    @patch("iterate_cross_db._management_api_query")
    def test_excludes_known_false_positives(self, mock_api):
        mock_api.return_value = [
            {"table_name": "team_members", "columns": "id,user_id"},
            {"table_name": "team_invites", "columns": "id,email"},
            {"table_name": "billing_users", "columns": "id"},
            {"table_name": "users", "columns": "id,email,created_at"},
        ]
        tables = db.discover_signup_tables("test-ref")
        names = [t["table"] for t in tables]
        self.assertNotIn("team_members", names)
        self.assertNotIn("team_invites", names)
        self.assertNotIn("billing_users", names)
        self.assertIn("users", names)

    @patch("iterate_cross_db._management_api_query")
    def test_detects_gclid_column_name(self, mock_api):
        mock_api.return_value = [
            {"table_name": "waitlist", "columns": "id,email,created_at,gclid"},
            {"table_name": "users", "columns": "id,email,created_at,click_id"},
            {"table_name": "signups", "columns": "id,email,created_at"},
        ]
        tables = db.discover_signup_tables("test-ref")
        by_name = {t["table"]: t for t in tables}
        self.assertEqual(by_name["waitlist"]["gclid_column"], "gclid")
        self.assertEqual(by_name["users"]["gclid_column"], "click_id")
        self.assertIsNone(by_name["signups"]["gclid_column"])


class QueryMvpGroundTruthTests(unittest.TestCase):
    """End-to-end probe with mocked API responses."""

    @patch("iterate_cross_db._management_api_query")
    def test_picks_max_count_table(self, mock_api):
        """When both auth.users and public.waitlist exist, take MAX (the larger one)
        as ground truth — diarly/smelt pattern where both surfaces accept signups."""
        # Simulate the sequence of API calls:
        # 1. count_auth_users_in_window
        # 2. discover_signup_tables (schema query)
        # 3. count_signups_in_window for each candidate
        mock_api.side_effect = [
            [{"total": 30, "confirmed": 23, "first_at": "2026-04-15T00:00:00+00:00"}],  # auth.users
            [  # schema
                {"table_name": "waitlist", "columns": "id,email,created_at"},
                {"table_name": "profiles", "columns": "id,user_id,created_at"},
            ],
            [{"n": 5, "first_at": "2026-04-20T00:00:00+00:00"}],   # public.waitlist count
            [{"n": 50, "first_at": "2026-04-10T00:00:00+00:00"}],  # public.profiles count
        ]
        result = db.query_mvp_ground_truth("test-ref", window_days=90)
        # profiles (50) > auth.users.confirmed (23) > waitlist (5). Profiles wins.
        self.assertEqual(result["db_signups"], 50)
        self.assertEqual(result["db_signups_table"], "public.profiles")
        # Earliest across all tables propagates as db_first_signup_at.
        self.assertEqual(result["db_first_signup_at"], "2026-04-10T00:00:00+00:00")
        self.assertIn("auth.users.confirmed", result["db_breakdown"])
        self.assertIn("public.waitlist", result["db_breakdown"])
        self.assertIn("public.profiles", result["db_breakdown"])

    @patch("iterate_cross_db._management_api_query")
    def test_auth_users_only(self, mock_api):
        """stylica-ai pattern: auth.users is the sole signup table."""
        mock_api.side_effect = [
            [{"total": 7, "confirmed": 5, "first_at": "2026-04-13T15:08:55+00:00"}],
            [  # schema — no signup-shape tables in public
                {"table_name": "contact_messages", "columns": "id,name,message"},
                {"table_name": "generations", "columns": "id,user_id,image_url"},
            ],
        ]
        result = db.query_mvp_ground_truth("test-ref", window_days=90)
        self.assertEqual(result["db_signups"], 5)
        self.assertEqual(result["db_signups_table"], "auth.users.confirmed")

    @patch("iterate_cross_db._management_api_query")
    def test_operator_override_skips_discovery(self, mock_api):
        """When operator specifies db_signup_table, only that table is queried."""
        mock_api.side_effect = [
            [  # schema query (called by override path to find ts column)
                {"table_name": "waitlist_subscribers_only", "columns": "id,email,created_at"},
            ],
            [{"n": 17, "first_at": "2026-04-15T00:00:00+00:00"}],
        ]
        result = db.query_mvp_ground_truth(
            "test-ref",
            window_days=90,
            operator_override_table="public.waitlist_subscribers_only",
        )
        self.assertEqual(result["db_signups"], 17)
        self.assertEqual(result["db_signups_table"], "public.waitlist_subscribers_only")

    @patch("iterate_cross_db._management_api_query")
    def test_api_error_is_captured(self, mock_api):
        mock_api.return_value = {"error": "401 unauthorized"}
        result = db.query_mvp_ground_truth("test-ref", window_days=90)
        # auth.users error + schema error → fallthrough to "no tables found"
        self.assertIsNone(result["db_signups"])
        self.assertTrue(result["errors"])

    def test_management_api_http_failures_map_to_unmapped_reasons(self):
        removed_payload = open(os.path.join(FIXTURES_DIR, "supabase-resource-removed-400.json")).read()
        cases = [
            ('{"message":"forbidden"}', 403, "forbidden"),
            ('{"message":"missing"}', 404, "project_deleted"),
            (removed_payload, 400, "project_deleted"),
            ('{"message":"  resource HAS been REMOVED  "}', 400, "project_deleted"),
            ('{"message":"bad gateway"}', 502, "query_error"),
            ('{"message":"dict without error"}', 200, "query_error"),
            ('{"message":"bad request"}', 400, "query_error"),
            ('{"message":"relation \\"public.waitlist\\" does not exist"}', 400, "query_error"),
            ("", 200, "query_error"),
        ]
        for body, status, reason in cases:
            with self.subTest(reason=reason, status=status, body=body):
                with patch("iterate_cross_db.urllib.request.urlopen") as mock_urlopen:
                    mock_urlopen.return_value = FakeHTTPResponse(status, body)
                    result = db.query_mvp_ground_truth("test-ref", window_days=90, token="token")
                self.assertIsNone(result["db_signups_real"])
                self.assertEqual(result["db_unmapped_reason"], reason)

    def test_management_api_query_uses_urllib_not_subprocess_for_token(self):
        secret = "supabase-secret-token"
        with patch("iterate_cross_db.subprocess.run") as mock_run, \
             patch("iterate_cross_db.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = FakeHTTPResponse(200, '[{"n":1}]')
            result = db._management_api_query("test-ref", "select 1", token=secret)

        self.assertEqual(result, [{"n": 1}])
        mock_urlopen.assert_called_once()
        mock_run.assert_not_called()
        self.assertNotIn(secret, repr(mock_run.call_args_list))

    def test_management_api_query_sends_user_agent_header(self):
        # Supabase's Cloudflare edge 1010-blocks the default `Python-urllib/*`
        # UA; the request must carry a self-identifying User-Agent instead.
        with patch("iterate_cross_db.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = FakeHTTPResponse(200, '[{"n":1}]')
            db._management_api_query("test-ref", "select 1", token="tok")
        req = mock_urlopen.call_args[0][0]
        ua = req.get_header("User-agent")
        self.assertTrue(ua and "Python-urllib" not in ua)

    def test_probe_supabase_projects_sends_user_agent_header(self):
        with patch("iterate_cross_db.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = FakeHTTPResponse(200, "[]")
            db.probe_supabase_projects(token="tok")
        req = mock_urlopen.call_args[0][0]
        ua = req.get_header("User-agent")
        self.assertTrue(ua and "Python-urllib" not in ua)

    @patch("iterate_cross_db._management_api_query")
    def test_public_override_deleted_project_beats_no_email_column(self, mock_api):
        mock_api.return_value = {
            "error": 'http 400: {"message":"Resource has been removed"}',
            "reason": "project_deleted",
        }
        result = db.query_mvp_ground_truth(
            "deleted-ref",
            window_days=90,
            operator_override_table="public.waitlist",
            config={"email_filter": {"rules": {}}},
        )
        self.assertIsNone(result["db_signups_real"])
        self.assertEqual(result["db_unmapped_reason"], "project_deleted")

    @patch("iterate_cross_db._management_api_query")
    def test_select_signups_aliases_timestamp_columns(self, mock_api):
        mock_api.return_value = []
        for ts_col in ["created_at", "inserted_at", "signed_up_at", "submitted_at", "registered_at"]:
            with self.subTest(ts_col=ts_col):
                mock_api.reset_mock()
                db.select_signups_in_window("ref", "signups", ts_col, 45)
                sql = mock_api.call_args.args[1]
                self.assertIn(f'SELECT email, "{ts_col}" AS signup_at', sql)
                self.assertIn(f'WHERE "{ts_col}" >= now() - INTERVAL \'45 days\'', sql)
        mock_api.reset_mock()
        db.select_signups_in_window("ref", "signups", None, 45)
        sql = mock_api.call_args.args[1]
        self.assertIn("SELECT email, NULL AS signup_at", sql)
        self.assertNotIn("INTERVAL '45 days'", sql)

    @patch("iterate_cross_db._management_api_query")
    def test_auth_users_filters_confirmed_and_email_categories(self, mock_api):
        mock_api.side_effect = [
            [
                {
                    "email": "real@customer.com",
                    "signup_at": "2026-05-03T00:00:00+00:00",
                    "email_confirmed_at": "2026-05-03T00:01:00+00:00",
                },
                {
                    "email": "unconfirmed@customer.com",
                    "signup_at": "2026-05-01T00:00:00+00:00",
                    "email_confirmed_at": None,
                },
                {
                    "email": "dev@team.test",
                    "signup_at": "2026-05-02T00:00:00+00:00",
                    "email_confirmed_at": "2026-05-02T00:01:00+00:00",
                },
                {
                    "email": "fixture@example.com",
                    "signup_at": "2026-05-01T00:00:00+00:00",
                    "email_confirmed_at": "2026-05-01T00:01:00+00:00",
                },
            ],
            [],
        ]
        cfg = {"email_filter": {"rules": {"team_domains": ["team.test"]}}}
        result = db.query_mvp_ground_truth("test-ref", window_days=90, config=cfg)
        auth_sql = mock_api.call_args_list[0].args[1]
        self.assertIn("email_confirmed_at IS NOT NULL", auth_sql)
        self.assertEqual(result["db_signups_raw"], 3)
        self.assertEqual(result["db_signups_real"], 1)
        self.assertEqual(result["db_signups_team"], 1)
        self.assertEqual(result["db_signups_test"], 1)
        self.assertEqual(result["db_first_signup_at"], "2026-05-03T00:00:00+00:00")

    @patch("iterate_cross_db._management_api_query")
    def test_email_table_beats_larger_no_email_profile_table(self, mock_api):
        mock_api.side_effect = [
            [
                {"email": f"user{i}@customer.com", "signup_at": f"2026-05-0{i + 1}T00:00:00+00:00", "email_confirmed_at": "x"}
                for i in range(5)
            ],
            [{"table_name": "profiles", "columns": "id,user_id,created_at"}],
        ]
        result = db.query_mvp_ground_truth("test-ref", window_days=90, config={"email_filter": {"rules": {}}})
        self.assertEqual(result["db_signups_real"], 5)
        self.assertEqual(result["db_signups_table"], "auth.users")

    @patch("iterate_cross_db._management_api_query")
    def test_no_email_only_project_returns_no_email_column(self, mock_api):
        mock_api.side_effect = [
            [],
            [{"table_name": "profiles", "columns": "id,user_id,created_at"}],
        ]
        result = db.query_mvp_ground_truth("test-ref", window_days=90, config={"email_filter": {"rules": {}}})
        self.assertIsNone(result["db_signups_real"])
        self.assertEqual(result["db_unmapped_reason"], "no_email_column")

    @patch("iterate_cross_db._management_api_query")
    def test_first_signup_at_is_earliest_real_row_only(self, mock_api):
        mock_api.side_effect = [
            [],
            [{"table_name": "signups", "columns": "id,email,created_at"}],
            [
                {"email": "fixture@example.com", "signup_at": "2026-05-01T00:00:00+00:00"},
                {"email": "real@customer.com", "signup_at": "2026-05-03T00:00:00+00:00"},
                {"email": "another@customer.com", "signup_at": "2026-05-04T00:00:00+00:00"},
            ],
        ]
        result = db.query_mvp_ground_truth("test-ref", window_days=90, config={"email_filter": {"rules": {}}})
        self.assertEqual(result["db_signups_raw"], 3)
        self.assertEqual(result["db_signups_real"], 2)
        self.assertEqual(result["db_first_signup_at"], "2026-05-03T00:00:00+00:00")

    @patch("iterate_cross_db._management_api_query")
    def test_gclid_table_computes_paid_count_and_attribution(self, mock_api):
        mock_api.side_effect = [
            [],
            [{"table_name": "waitlist", "columns": "id,email,created_at,gclid"}],
            [
                {"email": "paid@customer.com", "signup_at": "2026-05-01T00:00:00+00:00", "gclid": VALID_GCLID},
                {"email": "organic@customer.com", "signup_at": "2026-05-02T00:00:00+00:00", "gclid": None},
                {"email": "fixture@example.com", "signup_at": "2026-05-03T00:00:00+00:00", "gclid": VALID_GCLID},
            ],
        ]
        result = db.query_mvp_ground_truth("test-ref", window_days=90, config={"email_filter": {"rules": {}}})
        self.assertEqual(result["db_signups_raw"], 3)
        self.assertEqual(result["db_signups_real"], 2)
        self.assertEqual(result["db_signups_paid"], 1)
        self.assertLessEqual(result["db_signups_paid"], result["db_signups_real"])
        self.assertEqual(result["db_attribution"], "gclid_shape")
        self.assertEqual(result["gclid_column"], "gclid")

    @patch("iterate_cross_db._management_api_query")
    def test_junk_gclid_not_counted_as_paid(self, mock_api):
        """A gclid COLUMN with no valid populated value is shape, not evidence:
        paid stays int 0 but attribution must be window so verdicts use
        db_signups_real instead of trusting paid=0 (perky false-zero class)."""
        mock_api.side_effect = [
            [],
            [{"table_name": "waitlist", "columns": "id,email,created_at,gclid"}],
            [
                {"email": "buyer@customer.com", "signup_at": "2026-05-01T00:00:00+00:00", "gclid": JUNK_GCLID},
            ],
        ]
        result = db.query_mvp_ground_truth("test-ref", window_days=90, config={"email_filter": {"rules": {}}})
        self.assertEqual(result["db_signups_real"], 1)
        self.assertEqual(result["db_signups_paid"], 0)
        self.assertEqual(result["db_attribution"], "window")

    @patch("iterate_cross_db._management_api_query")
    def test_click_id_only_table_queries_detected_column(self, mock_api):
        mock_api.side_effect = [
            [],
            [{"table_name": "waitlist", "columns": "id,email,created_at,click_id"}],
            [
                {"email": "paid@customer.com", "signup_at": "2026-05-01T00:00:00+00:00", "gclid": VALID_GCLID},
            ],
        ]
        result = db.query_mvp_ground_truth("test-ref", window_days=30, config={"email_filter": {"rules": {}}})
        select_sql = mock_api.call_args_list[2].args[1]
        self.assertIn('"click_id" AS gclid', select_sql)
        self.assertNotIn('"gclid" AS gclid', select_sql)
        self.assertEqual(result["gclid_column"], "click_id")
        self.assertEqual(result["db_signups_paid"], 1)

    @patch("iterate_cross_db._management_api_query")
    def test_no_timestamp_gclid_table_never_yields_paid_count(self, mock_api):
        mock_api.side_effect = [
            [],
            [{"table_name": "waitlist", "columns": "id,email,gclid"}],
            [
                {"email": "paid@customer.com", "signup_at": None, "gclid": VALID_GCLID},
            ],
        ]
        result = db.query_mvp_ground_truth("test-ref", window_days=30, config={"email_filter": {"rules": {}}})
        select_sql = mock_api.call_args_list[2].args[1]
        self.assertIn('"gclid" AS gclid', select_sql)
        self.assertNotIn("INTERVAL '30 days'", select_sql)
        self.assertEqual(result["db_signups_real"], 1)
        self.assertIsNone(result["db_signups_paid"])
        self.assertEqual(result["db_attribution"], "window")

    @patch("iterate_cross_db._management_api_query")
    def test_cap_never_drops_gclid_table(self, mock_api):
        mock_api.side_effect = [
            [],
            [
                {"table_name": f"signup_{i}", "columns": "id,email,created_at"}
                for i in range(5)
            ] + [
                {"table_name": "profiles", "columns": "id,email,created_at,gclid"},
            ],
            [{"email": "paid@customer.com", "signup_at": "2026-05-01T00:00:00+00:00", "gclid": VALID_GCLID}],
            *[
                [{"email": f"user{i}@customer.com", "signup_at": "2026-05-02T00:00:00+00:00"}]
                for i in range(5)
            ],
        ]
        result = db.query_mvp_ground_truth("test-ref", window_days=90, config={"email_filter": {"rules": {}}})
        queried_sql = "\n".join(call.args[1] for call in mock_api.call_args_list)
        self.assertIn('FROM public."profiles"', queried_sql)
        # The gclid table survives the probe cap and contributes its paid
        # evidence to the union; the union's top-contributor label goes to the
        # highest-priority tie (each table contributes 1 real email).
        self.assertEqual(result["db_signups_table"], "public.signup_0")
        self.assertEqual(result["db_signups_real"], 6)
        self.assertEqual(result["db_signups_paid"], 1)
        self.assertEqual(result["db_attribution"], "gclid_shape")
        self.assertEqual(len(result["db_union_tables"]), 6)

    @patch("iterate_cross_db._management_api_query")
    def test_union_merges_gclid_table_with_auth_users_handpick_shape(self, mock_api):
        """handpick shape: a working gclid waitlist AND real auth.users accounts.
        The old gclid-first winner masked the 20 auth reals behind the 12-row
        waitlist; the union counts everyone once and keeps the paid evidence."""
        mock_api.side_effect = [
            [
                {
                    "email": f"user{i}@customer.com",
                    "signup_at": "2026-05-01T00:00:00+00:00",
                    "email_confirmed_at": "2026-05-01T00:01:00+00:00",
                }
                for i in range(20)
            ],
            [{"table_name": "waitlist", "columns": "id,email,created_at,gclid"}],
            [
                {"email": f"paid{i}@customer.com", "signup_at": "2026-05-02T00:00:00+00:00", "gclid": VALID_GCLID}
                for i in range(12)
            ],
        ]
        result = db.query_mvp_ground_truth("test-ref", window_days=90, config={"email_filter": {"rules": {}}})
        self.assertEqual(result["db_signups_table"], "auth.users")
        self.assertEqual(result["db_signups_real"], 32)
        self.assertEqual(result["db_signups_paid"], 12)
        self.assertEqual(result["db_attribution"], "gclid_shape")
        self.assertEqual(result["db_union_tables"], ["auth.users", "public.waitlist"])

    @patch("iterate_cross_db._management_api_query")
    def test_count_primary_priority_tiebreak_regression(self, mock_api):
        mock_api.side_effect = [
            [],
            [
                {"table_name": "signup", "columns": "id,email,created_at"},
                {"table_name": "waitlist", "columns": "id,email,created_at"},
            ],
            [{"email": "one@customer.com", "signup_at": "2026-05-01T00:00:00+00:00"}],
            [
                {"email": f"user{i}@customer.com", "signup_at": "2026-05-02T00:00:00+00:00"}
                for i in range(12)
            ],
        ]
        result = db.query_mvp_ground_truth("test-ref", window_days=90, config={"email_filter": {"rules": {}}})
        # Union of both email tables: 1 + 12 distinct reals. The 1-row
        # "signup" table no longer beats the 12-row waitlist (f1699a88
        # regression) — and now it doesn't mask it either.
        self.assertEqual(result["db_signups_table"], "public.waitlist")
        self.assertEqual(result["db_signups_real"], 13)
        self.assertEqual(result["priority"], 0)


class UnionGroundTruthTests(unittest.TestCase):
    """Cross-table union-dedupe (fleet false-zero fix): windowed email tables
    merge into one candidate keyed on gmail-normalized email, so auth.users
    can never be masked by a gclid-bearing waitlist again."""

    @patch("iterate_cross_db._management_api_query")
    def test_union_dedupes_same_email_across_waitlist_and_auth(self, mock_api):
        mock_api.side_effect = [
            [
                {"email": "joe@gmail.com", "signup_at": "2026-05-01T00:00:00+00:00", "email_confirmed_at": "x"},
                {"email": "solo@customer.com", "signup_at": "2026-05-02T00:00:00+00:00", "email_confirmed_at": "x"},
            ],
            [{"table_name": "waitlist", "columns": "id,email,created_at"}],
            [
                # gmail dot/plus variant of joe@gmail.com — must dedupe to one person
                {"email": "J.oe+promo@gmail.com", "signup_at": "2026-04-20T00:00:00+00:00"},
                {"email": "waitonly@customer.com", "signup_at": "2026-05-03T00:00:00+00:00"},
            ],
        ]
        result = db.query_mvp_ground_truth("test-ref", window_days=90, config={"email_filter": {"rules": {}}})
        self.assertEqual(result["db_signups_real"], 3)
        self.assertEqual(result["db_signups_raw"], 3)
        self.assertIsNone(result["db_signups_paid"])  # no gclid column anywhere
        self.assertEqual(result["db_attribution"], "window")
        # 2:2 real-contribution tie → table-priority ascending puts waitlist first
        self.assertEqual(result["db_union_tables"], ["public.waitlist", "auth.users"])
        self.assertEqual(result["db_signups_table"], "public.waitlist")
        # earliest real occurrence across BOTH tables (the waitlist variant row)
        self.assertEqual(result["db_first_signup_at"], "2026-04-20T00:00:00+00:00")

    @patch("iterate_cross_db._management_api_query")
    def test_auth_reals_beat_internal_only_gclid_table_termob_shape(self, mock_api):
        """termob shape: gclid waitlist holds ONLY team/test rows (filtered to
        0 real) while auth.users has the actual customers. Old gclid-first
        winner reported 0; the union reports the 3 real accounts."""
        mock_api.side_effect = [
            [
                {"email": f"customer{i}@icloud.com", "signup_at": "2026-06-10T00:00:00+00:00", "email_confirmed_at": "x"}
                for i in range(3)
            ],
            [{"table_name": "waitlist", "columns": "id,email,created_at,gclid"}],
            [
                *[
                    {"email": f"smoke{i}@magpiexyz.io", "signup_at": "2026-06-09T00:00:00+00:00", "gclid": VALID_GCLID}
                    for i in range(6)
                ],
                *[
                    {"email": f"fixture{i}@example.com", "signup_at": "2026-06-09T00:00:00+00:00", "gclid": None}
                    for i in range(3)
                ],
            ],
        ]
        result = db.query_mvp_ground_truth(
            "test-ref", window_days=365,
            config={"email_filter": {"rules": {"team_domains": ["magpiexyz.io"]}}},
        )
        self.assertEqual(result["db_signups_real"], 3)
        self.assertEqual(result["db_signups_team"], 6)
        self.assertEqual(result["db_signups_test"], 3)
        # gclid column exists but only on team rows → paid is int 0, window
        self.assertEqual(result["db_signups_paid"], 0)
        self.assertEqual(result["db_attribution"], "window")
        self.assertEqual(result["db_signups_table"], "auth.users")
        self.assertEqual(result["db_union_tables"], ["auth.users"])

    @patch("iterate_cross_db._management_api_query")
    def test_gclid_dead_table_with_reals_unions_auth_perky_shape(self, mock_api):
        """perky shape: public.users has a gclid column that was never
        populated (5 reals, all gclid None) and auth.users holds 9 reals
        overlapping those 5. Old logic reported paid=0 as the verdict count;
        union reports 9 real with window attribution."""
        mock_api.side_effect = [
            [
                {"email": f"user{i}@customer.com", "signup_at": "2026-06-01T00:00:00+00:00", "email_confirmed_at": "x"}
                for i in range(9)
            ],
            [{"table_name": "users", "columns": "id,email,created_at,gclid"}],
            [
                {"email": f"user{i}@customer.com", "signup_at": "2026-06-01T00:00:00+00:00", "gclid": None}
                for i in range(5)
            ],
        ]
        result = db.query_mvp_ground_truth("test-ref", window_days=365, config={"email_filter": {"rules": {}}})
        self.assertEqual(result["db_signups_real"], 9)
        self.assertEqual(result["db_signups_paid"], 0)
        self.assertEqual(result["db_attribution"], "window")
        self.assertEqual(result["db_signups_table"], "auth.users")
        self.assertEqual(result["db_union_tables"], ["auth.users", "public.users"])

    @patch("iterate_cross_db._management_api_query")
    def test_legacy_no_email_competition_unchanged(self, mock_api):
        """No-downward-flip guarantee: a no-email legacy table competes with
        the union on (real, raw, -priority) exactly as before the union
        existed — a big legacy count still wins (pre-existing semantics)."""
        mock_api.side_effect = [
            [],
            [
                {"table_name": "waitlist", "columns": "id,email,created_at"},
                {"table_name": "profiles", "columns": "id,user_id,created_at"},
            ],
            [
                {"email": f"user{i}@customer.com", "signup_at": "2026-05-02T00:00:00+00:00"}
                for i in range(12)
            ],
            [{"n": 500, "first_at": "2026-01-01T00:00:00+00:00"}],
        ]
        # No email_filter → no-email tables are probed (production configs set
        # email_filter, which skips them entirely).
        result = db.query_mvp_ground_truth("test-ref", window_days=90, config={})
        self.assertEqual(result["db_signups_table"], "public.profiles")
        self.assertEqual(result["db_signups_real"], 500)
        self.assertEqual(result["db_union_tables"], [])
        self.assertEqual(result["db_breakdown"]["public.waitlist"], 12)

    @patch("iterate_cross_db._management_api_query")
    def test_legacy_synthetic_rows_never_enter_union(self, mock_api):
        """Count-shaped responses synthesize identical placeholder emails
        (legacy-N@legacy-count.invalid-real) per table. If they entered the
        union they would dedupe across tables and understate counts — they
        must stay count-only candidates."""
        mock_api.side_effect = [
            [{"confirmed": 23, "total": 25, "first_at": "2026-05-01T00:00:00+00:00"}],
            [{"table_name": "waitlist", "columns": "id,email,created_at"}],
            [{"n": 5, "first_at": "2026-05-02T00:00:00+00:00"}],
        ]
        result = db.query_mvp_ground_truth("test-ref", window_days=90, config={"email_filter": {"rules": {}}})
        self.assertEqual(result["db_union_tables"], [])
        self.assertEqual(result["db_signups_table"], "auth.users.confirmed")
        self.assertEqual(result["db_signups_real"], 23)
        self.assertEqual(result["db_breakdown"]["public.waitlist"], 5)


class RailwayFallbackPredicateTests(unittest.TestCase):
    def test_allow_railway_fallback_reason_matrix(self):
        for reason in ["no_match", "no_token", "no_email_column", "project_deleted", "ref_invalid"]:
            with self.subTest(reason=reason):
                self.assertTrue(db.allow_railway_fallback(reason))
        for reason in ["query_error", "forbidden", None]:
            with self.subTest(reason=reason):
                self.assertFalse(db.allow_railway_fallback(reason))


class ConfirmProjectDeletedTests(unittest.TestCase):
    """Query-path project_deleted must be tombstone-confirmed (the SQL
    endpoint 404s for both deleted and never-existed refs)."""

    def test_sticky_terminal_shortcuts_skip_probe(self):
        with patch.object(db, "probe_project_tombstone") as mock_probe:
            reason, rec = db.confirm_project_deleted(
                "ref-x", {"db_backend": {"status": "deleted_verified"}}, set())
            self.assertEqual((reason, rec), ("project_deleted", None))
            reason, rec = db.confirm_project_deleted(
                "ref-x", {"db_backend": {"status": "never_existed"}}, set())
            self.assertEqual((reason, rec), ("ref_invalid", None))
        mock_probe.assert_not_called()

    def test_live_list_membership_downgrades_to_query_error(self):
        with patch.object(db, "probe_project_tombstone") as mock_probe:
            reason, rec = db.confirm_project_deleted("ref-x", {}, {"ref-x"})
        mock_probe.assert_not_called()
        self.assertEqual(reason, "query_error")
        self.assertEqual(rec["status"], "alive")

    def test_probe_outcomes(self):
        cases = [
            ({"status": "deleted_verified", "http_status": 400,
              "message": "Resource has been removed"}, "project_deleted", "deleted_verified"),
            ({"status": "never_existed", "http_status": 404, "message": "Not Found"},
             "ref_invalid", "never_existed"),
            ({"status": "not_visible", "http_status": 403, "message": None},
             "forbidden", "not_visible"),
            ({"status": "alive", "http_status": 200, "message": None},
             "query_error", "alive"),
        ]
        for probe, want_reason, want_status in cases:
            with self.subTest(probe=probe):
                with patch.object(db, "probe_project_tombstone", return_value=probe):
                    reason, rec = db.confirm_project_deleted("ref-x", {}, set())
                self.assertEqual(reason, want_reason)
                self.assertEqual(rec["status"], want_status)
                self.assertIn("http", rec["evidence"])

    def test_flaky_probe_never_concludes_deletion(self):
        with patch.object(db, "probe_project_tombstone",
                          return_value={"status": None, "http_status": None,
                                        "message": "urlopen timed out"}):
            reason, rec = db.confirm_project_deleted("ref-x", {}, set())
        self.assertEqual((reason, rec), ("query_error", None))


class MergeRebuiltRefTests(unittest.TestCase):
    """Stale config ref + exact-name live project → rebuilt-ref re-match
    proposal instead of a false project_deleted (ShelfCurve incident)."""

    @patch("iterate_cross_db.list_supabase_projects")
    @patch("iterate_cross_db.query_mvp_ground_truth")
    def test_rebuilt_ref_proposed_then_persisted(self, mock_q, mock_list):
        mock_list.return_value = [{"id": "new-ref", "name": "ShelfCurve"}]
        mock_q.return_value = {
            "db_signups": 1, "db_signups_table": "auth.users",
            "db_first_signup_at": "2026-07-24", "db_breakdown": {"auth.users": 1},
            "errors": None,
        }
        with tempfile.TemporaryDirectory() as t:
            ctx_path = os.path.join(t, "ctx.json")
            cfg_path = os.path.join(t, "cfg.yaml")
            with open(ctx_path, "w") as f:
                json.dump({"window_days": 90, "mvps": [{"name": "shelfcurve"}]}, f)
            import yaml as _yaml
            with open(cfg_path, "w") as f:
                _yaml.safe_dump({"mvp_mappings": {
                    "shelfcurve": {"supabase_project_ref": "old-ref"},
                }}, f)

            # First pass (no auto_confirm): re-match is PROPOSED, nothing persists.
            result = db.merge_into_context(ctx_path, cfg_path)
            self.assertEqual(result["step"], "needs_confirm")
            row = result["needs_confirm"][0]
            self.assertEqual(row["match_type"], "rebuilt-ref")
            self.assertEqual(row["old_ref"], "old-ref")
            self.assertEqual(row["project_ref"], "new-ref")
            cfg_after = _yaml.safe_load(open(cfg_path))
            self.assertEqual(
                cfg_after["mvp_mappings"]["shelfcurve"]["supabase_project_ref"],
                "old-ref",
            )

            # Auto-confirm pass: ref updated and the query runs on the NEW ref.
            result = db.merge_into_context(ctx_path, cfg_path, auto_confirm=True)
            self.assertEqual(result["step"], "merged")
            cfg_after = _yaml.safe_load(open(cfg_path))
            self.assertEqual(
                cfg_after["mvp_mappings"]["shelfcurve"]["supabase_project_ref"],
                "new-ref",
            )
            self.assertEqual(mock_q.call_args[0][0], "new-ref")

    @patch("iterate_cross_db.list_supabase_projects")
    @patch("iterate_cross_db.query_mvp_ground_truth")
    def test_no_rematch_when_ref_alive_or_no_exact_match(self, mock_q, mock_list):
        # Ref present in the live list → no proposal even with a same-name row.
        mock_list.return_value = [{"id": "old-ref", "name": "ShelfCurve"}]
        mock_q.return_value = {
            "db_signups": 0, "db_signups_table": None,
            "db_first_signup_at": None, "db_breakdown": {}, "errors": None,
        }
        with tempfile.TemporaryDirectory() as t:
            ctx_path = os.path.join(t, "ctx.json")
            cfg_path = os.path.join(t, "cfg.yaml")
            with open(ctx_path, "w") as f:
                json.dump({"window_days": 90, "mvps": [{"name": "shelfcurve"}]}, f)
            import yaml as _yaml
            with open(cfg_path, "w") as f:
                _yaml.safe_dump({"mvp_mappings": {
                    "shelfcurve": {"supabase_project_ref": "old-ref"},
                }}, f)
            result = db.merge_into_context(ctx_path, cfg_path)
            self.assertEqual(result["step"], "merged")

    @patch("iterate_cross_db.list_supabase_projects")
    @patch("iterate_cross_db.query_mvp_ground_truth")
    def test_empty_project_list_never_mass_proposes(self, mock_q, mock_list):
        mock_list.return_value = []
        mock_q.return_value = {
            "db_signups": None, "db_signups_table": None,
            "db_first_signup_at": None, "db_breakdown": {}, "errors": None,
        }
        with tempfile.TemporaryDirectory() as t:
            ctx_path = os.path.join(t, "ctx.json")
            cfg_path = os.path.join(t, "cfg.yaml")
            with open(ctx_path, "w") as f:
                json.dump({"window_days": 90, "mvps": [{"name": "shelfcurve"}]}, f)
            import yaml as _yaml
            with open(cfg_path, "w") as f:
                _yaml.safe_dump({"mvp_mappings": {
                    "shelfcurve": {"supabase_project_ref": "old-ref"},
                }}, f)
            result = db.merge_into_context(ctx_path, cfg_path)
            self.assertEqual(result["step"], "merged")


class MergeProjectDeletedConfirmationTests(unittest.TestCase):
    """The query-path project_deleted reason is tombstone-confirmed in the
    merge before it can drive the rule-3 forced NO_GO."""

    def _run_merge(self, probe, mock_q, mock_list):
        mock_list.return_value = []
        mock_q.return_value = db._empty_ground_truth(
            "project_deleted", ["auth.users: http 404"])
        with tempfile.TemporaryDirectory() as t:
            ctx_path = os.path.join(t, "ctx.json")
            cfg_path = os.path.join(t, "cfg.yaml")
            with open(ctx_path, "w") as f:
                json.dump({"window_days": 90, "mvps": [{"name": "alpha"}]}, f)
            import yaml as _yaml
            with open(cfg_path, "w") as f:
                _yaml.safe_dump({"mvp_mappings": {
                    "alpha": {"supabase_project_ref": "ref-a"},
                }}, f)
            with patch.object(db, "probe_project_tombstone", return_value=probe):
                db.merge_into_context(ctx_path, cfg_path, auto_confirm=True)
            return json.load(open(ctx_path))["mvps"][0], _yaml.safe_load(open(cfg_path))

    @patch("iterate_cross_db.list_supabase_projects")
    @patch("iterate_cross_db.query_mvp_ground_truth")
    def test_true_tombstone_keeps_project_deleted_and_persists_sticky(self, mock_q, mock_list):
        mvp, cfg = self._run_merge(
            {"status": "deleted_verified", "http_status": 400,
             "message": "Resource has been removed"}, mock_q, mock_list)
        self.assertEqual(mvp["db_unmapped_reason"], "project_deleted")
        self.assertEqual(mvp["db_backend"]["status"], "deleted_verified")
        sticky = cfg["mvp_mappings"]["alpha"].get("db_backend") or {}
        self.assertEqual(sticky.get("status"), "deleted_verified")

    @patch("iterate_cross_db.list_supabase_projects")
    @patch("iterate_cross_db.query_mvp_ground_truth")
    def test_plain_404_downgrades_to_ref_invalid(self, mock_q, mock_list):
        mvp, cfg = self._run_merge(
            {"status": "never_existed", "http_status": 404, "message": "Not Found"},
            mock_q, mock_list)
        self.assertEqual(mvp["db_unmapped_reason"], "ref_invalid")
        sticky = cfg["mvp_mappings"]["alpha"].get("db_backend") or {}
        self.assertEqual(sticky.get("status"), "never_existed")

    @patch("iterate_cross_db.list_supabase_projects")
    @patch("iterate_cross_db.query_mvp_ground_truth")
    def test_flaky_probe_downgrades_to_query_error_no_sticky(self, mock_q, mock_list):
        mvp, cfg = self._run_merge(
            {"status": None, "http_status": None, "message": "urlopen timed out"},
            mock_q, mock_list)
        self.assertEqual(mvp["db_unmapped_reason"], "query_error")
        self.assertNotIn("db_backend", cfg["mvp_mappings"]["alpha"])


class MergeIntoContextSourceStampTests(unittest.TestCase):
    """Supabase pass must set db_source='supabase' on successful queries.

    Without this stamp, the schema is asymmetric with the Railway pass
    (which sets db_source='railway'): x4 would see db_source=None for all
    Supabase rows and read it as "unknown source" rather than the actual
    default Supabase attribution.
    """

    @patch("iterate_cross_db.list_supabase_projects")
    @patch("iterate_cross_db.query_mvp_ground_truth")
    def test_supabase_success_stamps_db_source(self, mock_q, mock_list):
        mock_list.return_value = [{"id": "ref_alpha", "name": "alpha"}]
        mock_q.return_value = {
            "db_signups": 12, "db_signups_table": "public.users",
            "db_first_signup_at": "2026-04-01", "db_breakdown": {"public.users": 12},
            "errors": None,
        }
        with tempfile.TemporaryDirectory() as t:
            ctx_path = os.path.join(t, "ctx.json")
            cfg_path = os.path.join(t, "cfg.yaml")
            with open(ctx_path, "w") as f:
                json.dump({"window_days": 90, "mvps": [
                    {"name": "alpha"},
                ]}, f)
            import yaml as _yaml
            with open(cfg_path, "w") as f:
                _yaml.safe_dump({"mvp_mappings": {
                    "alpha": {"supabase_project_ref": "ref_alpha"},
                }}, f)
            _ = db.merge_into_context(ctx_path, cfg_path, auto_confirm=True)
            updated = json.load(open(ctx_path))
            m = updated["mvps"][0]
            self.assertEqual(m["db_signups"], 12)
            self.assertEqual(m["db_source"], "supabase")

    @patch("iterate_cross_db.list_supabase_projects")
    @patch("iterate_cross_db.query_mvp_ground_truth")
    def test_killed_lifecycle_skips_supabase_query(self, mock_q, mock_list):
        mock_list.return_value = [{"id": "ref_dead", "name": "dead-mvp"}]
        with tempfile.TemporaryDirectory() as t:
            ctx_path = os.path.join(t, "ctx.json")
            cfg_path = os.path.join(t, "cfg.yaml")
            with open(ctx_path, "w") as f:
                json.dump({"window_days": 90, "mvps": [{"name": "dead-mvp"}]}, f)
            import yaml as _yaml
            with open(cfg_path, "w") as f:
                _yaml.safe_dump({"mvp_mappings": {
                    "dead-mvp": {
                        "supabase_project_ref": "ref_dead",
                        "lifecycle_status": "killed",
                        "lifecycle_status_at": "2026-06-01T00:00:00Z",
                    },
                }}, f)
            _ = db.merge_into_context(ctx_path, cfg_path, auto_confirm=True)
            updated = json.load(open(ctx_path))
            cfg_after = _yaml.safe_load(open(cfg_path))

        mock_q.assert_not_called()
        m = updated["mvps"][0]
        self.assertEqual(m["lifecycle_status"], "killed")
        self.assertEqual(m["lifecycle_status_at"], "2026-06-01T00:00:00Z")
        self.assertIsNone(m["db_signups_real"])
        # Policy skip is honestly labeled: archived_killed, NOT project_deleted
        # (that value is reserved for OBSERVED deletions).
        self.assertEqual(m["db_unmapped_reason"], "archived_killed")
        self.assertIsNone(m["db_source"])
        # ref_dead IS in the mocked org project list → membership proves the
        # backend is ALIVE (zombie case) and the sticky record is persisted.
        self.assertEqual((m.get("db_backend") or {}).get("status"), "alive")
        sticky = cfg_after["mvp_mappings"]["dead-mvp"].get("db_backend") or {}
        self.assertEqual(sticky.get("status"), "alive")
        self.assertTrue(sticky.get("checked_at"))

    @patch("iterate_cross_db.list_supabase_projects")
    @patch("iterate_cross_db.query_mvp_ground_truth")
    def test_supabase_no_signups_does_not_stamp_db_source(self, mock_q, mock_list):
        # When query returns None, don't claim Supabase as the source — there's
        # no source to attribute and the Railway fallback might fill it later.
        mock_list.return_value = [{"id": "ref_alpha", "name": "alpha"}]
        mock_q.return_value = {
            "db_signups": None, "db_signups_table": None,
            "db_first_signup_at": None, "db_breakdown": {},
            "errors": ["query failed"],
        }
        with tempfile.TemporaryDirectory() as t:
            ctx_path = os.path.join(t, "ctx.json")
            cfg_path = os.path.join(t, "cfg.yaml")
            with open(ctx_path, "w") as f:
                json.dump({"window_days": 90, "mvps": [{"name": "alpha"}]}, f)
            import yaml as _yaml
            with open(cfg_path, "w") as f:
                _yaml.safe_dump({"mvp_mappings": {
                    "alpha": {"supabase_project_ref": "ref_alpha"},
                }}, f)
            _ = db.merge_into_context(ctx_path, cfg_path, auto_confirm=True)
            updated = json.load(open(ctx_path))
            m = updated["mvps"][0]
            self.assertIsNone(m["db_signups"])
            # db_source not set — leaves the field absent so Railway can fill in.
            self.assertNotIn("db_source", m)

    @patch("iterate_cross_db.list_supabase_projects")
    @patch("iterate_cross_db.query_mvp_ground_truth")
    def test_dry_run_leaves_context_file_untouched(self, mock_q, mock_list):
        mock_list.return_value = [{"id": "ref_alpha", "name": "alpha"}]
        mock_q.return_value = {
            "db_signups": 12,
            "db_signups_raw": 12,
            "db_signups_real": 12,
            "db_signups_team": 0,
            "db_signups_test": 0,
            "db_signups_filter_audit": [],
            "db_signups_real_windowed": True,
            "db_signups_table": "public.users",
            "db_first_signup_at": "2026-04-01",
            "db_breakdown": {"public.users": 12},
            "errors": None,
        }
        original = {"window_days": 90, "mvps": [{"name": "alpha"}]}
        with tempfile.TemporaryDirectory() as t:
            ctx_path = os.path.join(t, "ctx.json")
            cfg_path = os.path.join(t, "cfg.yaml")
            with open(ctx_path, "w") as f:
                json.dump(original, f)
            import yaml as _yaml
            with open(cfg_path, "w") as f:
                _yaml.safe_dump({"mvp_mappings": {
                    "alpha": {"supabase_project_ref": "ref_alpha"},
                }}, f)

            result = db.merge_into_context(ctx_path, cfg_path, auto_confirm=True, dry_run=True)

            self.assertEqual(result["step"], "merged")
            self.assertEqual(json.load(open(ctx_path)), original)

    @patch("iterate_cross_db.list_supabase_projects")
    @patch("iterate_cross_db._management_api_query")
    def test_product_domain_filter_threads_through_supabase_merge(self, mock_api, mock_list):
        mock_list.return_value = [{"id": "ref_alpha", "name": "alpha"}]
        mock_api.side_effect = [
            [],
            [{"table_name": "waitlist", "columns": "id,email,created_at"}],
            [
                {"email": "founder@alpha.dev", "signup_at": "2026-05-01T00:00:00+00:00"},
                {"email": "buyer@customer.io", "signup_at": "2026-05-02T00:00:00+00:00"},
            ],
        ]
        with tempfile.TemporaryDirectory() as t:
            ctx_path = os.path.join(t, "ctx.json")
            cfg_path = os.path.join(t, "cfg.yaml")
            with open(ctx_path, "w") as f:
                json.dump({"window_days": 90, "mvps": [{"name": "alpha"}]}, f)
            import yaml as _yaml
            with open(cfg_path, "w") as f:
                _yaml.safe_dump({
                    "mvp_mappings": {
                        "alpha": {
                            "supabase_project_ref": "ref_alpha",
                            "deploy_domain": "alpha.dev",
                        },
                    },
                    "email_filter": {"rules": {}},
                }, f)

            result = db.merge_into_context(ctx_path, cfg_path, auto_confirm=True)
            updated = json.load(open(ctx_path))["mvps"][0]

        self.assertEqual(result["queried"], 1)
        self.assertEqual(updated["db_signups_raw"], 2)
        self.assertEqual(updated["db_signups_real"], 1)
        self.assertEqual(updated["db_signups_test"], 1)
        self.assertTrue(any(
            row.get("reason") == "product-own-domain"
            for row in updated["db_signups_filter_audit"]
        ))


class SanityFlagTests(unittest.TestCase):
    """compute_db_sanity_flags is the heart of x3's cross-check.
    Each flag has a single decisive scenario."""

    def test_no_db_signal_no_flags(self):
        flags = verdicts.compute_db_sanity_flags(
            paid_signups=5,
            db_signups=None,  # unmapped
            db_first_signup_at=None,
            first_seen=None,
            ga_clicks=100,
        )
        self.assertEqual(flags, [])

    def test_ph_attribution_broken_fires(self):
        """x-predict canonical: DB has signups, PH paid is zero."""
        flags = verdicts.compute_db_sanity_flags(
            paid_signups=0,
            db_signups=18,
            db_first_signup_at="2026-04-15T00:00:00+00:00",
            first_seen="2026-04-15T00:00:00+00:00",
            ga_clicks=2055,
        )
        self.assertTrue(any(f["flag"] == "ph_attribution_broken" for f in flags))

    def test_ph_attribution_broken_skipped_when_no_ga_spend(self):
        """No paid spend → no expectation of paid signups; suppress the flag."""
        flags = verdicts.compute_db_sanity_flags(
            paid_signups=0,
            db_signups=18,
            db_first_signup_at="2026-04-15T00:00:00+00:00",
            first_seen="2026-04-15T00:00:00+00:00",
            ga_clicks=0,
        )
        self.assertFalse(any(f["flag"] == "ph_attribution_broken" for f in flags))

    def test_ph_overcount_fires_on_activate_misclassification(self):
        """stylica-ai before the fix: PH paid=33 (signup_complete + activate), DB=6."""
        flags = verdicts.compute_db_sanity_flags(
            paid_signups=33,
            db_signups=6,
            db_first_signup_at="2026-04-13T00:00:00+00:00",
            first_seen="2026-04-13T00:00:00+00:00",
            ga_clicks=575,
        )
        self.assertTrue(any(f["flag"] == "ph_overcount" for f in flags))

    def test_ph_undercount_fires(self):
        flags = verdicts.compute_db_sanity_flags(
            paid_signups=2,
            db_signups=10,
            db_first_signup_at="2026-04-13T00:00:00+00:00",
            first_seen="2026-04-14T00:00:00+00:00",
            ga_clicks=100,
        )
        self.assertTrue(any(f["flag"] == "ph_undercount" for f in flags))

    def test_late_instrumentation_fires(self):
        """stylica-ai canonical: DB first row 2026-04-13, PH first event 2026-04-30."""
        flags = verdicts.compute_db_sanity_flags(
            paid_signups=2,
            db_signups=2,  # equal counts within window; sole signal is the timestamp gap
            db_first_signup_at="2026-04-13T15:08:55+00:00",
            first_seen="2026-04-30T04:04:06+00:00",
            ga_clicks=575,
        )
        self.assertTrue(any(f["flag"] == "late_instrumentation" for f in flags))

    def test_aligned_data_emits_no_flags(self):
        flags = verdicts.compute_db_sanity_flags(
            paid_signups=8,
            db_signups=9,
            db_first_signup_at="2026-04-15T00:00:00+00:00",
            first_seen="2026-04-15T00:00:00+00:00",
            ga_clicks=102,
        )
        self.assertEqual(flags, [])

    def test_db_union_multi_table_flag_info_severity(self):
        """≥2 contributing tables → one info flag naming them; 1/empty/None → absent."""
        flags = verdicts.compute_db_sanity_flags(
            paid_signups=8,
            db_signups=9,
            db_first_signup_at="2026-04-15T00:00:00+00:00",
            first_seen="2026-04-15T00:00:00+00:00",
            ga_clicks=102,
            db_union_tables=["auth.users", "public.waitlist"],
        )
        union_flags = [f for f in flags if f["flag"] == "db_union_multi_table"]
        self.assertEqual(len(union_flags), 1)
        self.assertEqual(union_flags[0]["severity"], "info")
        self.assertIn("auth.users", union_flags[0]["message"])
        self.assertIn("public.waitlist", union_flags[0]["message"])
        for union_tables in (["auth.users"], [], None):
            with self.subTest(db_union_tables=union_tables):
                flags = verdicts.compute_db_sanity_flags(
                    paid_signups=8,
                    db_signups=9,
                    db_first_signup_at="2026-04-15T00:00:00+00:00",
                    first_seen="2026-04-15T00:00:00+00:00",
                    ga_clicks=102,
                    db_union_tables=union_tables,
                )
                self.assertFalse(any(f["flag"] == "db_union_multi_table" for f in flags))


class VerdictIntegrationTests(unittest.TestCase):
    """End-to-end: compute_headline_verdict carries db_signups + sanity flags
    into the score record so x4's renderer can consume them."""

    def test_db_signups_propagates_to_score(self):
        mvp = {
            "name": "stylica-ai",
            "gclid_visitors": 201,
            "ga_clicks": 575,
            "signups": 33,
            "signup_events": ["signup_complete", "activate"],
            "db_signups": 6,
            "db_first_signup_at": "2026-04-13T15:08:55+00:00",
            "first_seen": "2026-04-30T04:04:06+00:00",
        }
        issues = {}
        thresholds = {"signups_go": 3, "visitors_floor": 50}
        score = verdicts.compute_headline_verdict(mvp, issues, thresholds)
        self.assertEqual(score["metrics"]["db_signups"], 6)
        flags = score["tracking_sanity_flags"]
        # Two high-severity flags should fire: overcount + late_instrumentation
        flag_names = {f["flag"] for f in flags}
        self.assertIn("ph_overcount", flag_names)
        self.assertIn("late_instrumentation", flag_names)

    def test_gclid_dead_union_lands_db_real_with_union_flag(self):
        """perky end-to-end: gclid column present but never populated →
        producer emits paid=0/window; the verdict must use the union real
        count (source db_real), NOT trust paid=0, and surface the union flag."""
        mvp = {
            "name": "perky-shape",
            "gclid_visitors": 120,
            "ga_clicks": 122,
            "signups": 3,
            "ph_signups": 3,
            "ph_signups_available": True,
            "signup_events": ["signup_complete"],
            "db_signups": 23,
            "db_signups_raw": 23,
            "db_signups_real": 9,
            "db_signups_paid": 0,
            "db_attribution": "window",
            "db_signups_real_windowed": True,
            "db_source": "supabase",
            "db_unmapped_reason": None,
            "db_union_tables": ["auth.users", "public.users"],
            "db_first_signup_at": "2026-06-10T00:00:00+00:00",
            "first_seen": "2026-06-08T00:00:00+00:00",
        }
        score = verdicts.compute_headline_verdict(mvp, {}, {"signups_go": 3, "visitors_floor": 50})
        self.assertEqual(score["metrics"]["signup_source"], "db_real")
        self.assertEqual(score["metrics"]["effective_signups"], 9)
        self.assertTrue(
            any(f["flag"] == "db_union_multi_table" for f in score["tracking_sanity_flags"])
        )


class EmptyGroundTruthSchemaTests(unittest.TestCase):
    """_empty_ground_truth is the canonical null-DB schema reused by state-x0b's
    no-DB-auth degraded path (require_db_ground_truth: false). It must emit every
    field x0b VERIFY requires and satisfy the real/reason invariant."""

    REQUIRED = [
        "db_signups", "db_signups_raw", "db_signups_real", "db_signups_team",
        "db_signups_test", "db_signups_paid", "db_attribution",
        "db_signups_filter_audit", "db_signups_real_windowed", "db_first_signup_at",
        "db_unmapped_reason",
    ]

    def test_has_all_x0b_verify_fields(self):
        d = db._empty_ground_truth("no_token")
        self.assertEqual([k for k in self.REQUIRED if k not in d], [])

    def test_satisfies_real_reason_invariant(self):
        for reason in ("no_token", "no_match", "orphan", "no_match_neither"):
            d = db._empty_ground_truth(reason)
            # x0b invariant: (real is None) iff (reason is not None)
            self.assertEqual(
                d["db_signups_real"] is None,
                d["db_unmapped_reason"] is not None,
                f"invariant failed for reason={reason}",
            )

    def test_reason_is_stored(self):
        self.assertEqual(db._empty_ground_truth("orphan")["db_unmapped_reason"], "orphan")


class IterateCrossVerifyPaidBoundsTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmpdir, ".runs"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _artifact(self, paid: int, real: int, attribution: str = "gclid_shape") -> dict:
        record = {
            "name": "bad-paid-bound",
            "gclid_visitors": 0,
            "total_events_count": 0,
            "event_catalog": [],
            "ga_clicks": 0,
            "ga_clicks_phase2": 0,
            "db_signups": real,
            "db_signups_raw": real,
            "db_signups_real": real,
            "db_signups_paid": paid,
            "db_attribution": attribution,
            "db_signups_team": 0,
            "db_signups_test": 0,
            "db_signups_filter_audit": {},
            "db_signups_real_windowed": True,
            "db_first_signup_at": None,
            "db_unmapped_reason": None,
            "lifecycle_status": "active",
        }
        return {
            "mvps": [record],
            "_x1_catalog_batches_status": {"complete": True},
        }

    def _run_verify(self, state_id: str, paid: int, real: int, attribution: str = "gclid_shape") -> subprocess.CompletedProcess:
        filename = "iterate-cross-context.json" if state_id == "x0b" else "iterate-cross-data.json"
        path = os.path.join(self.tmpdir, ".runs", filename)
        with open(path, "w") as f:
            json.dump(self._artifact(paid=paid, real=real, attribution=attribution), f)
        return subprocess.run(
            ["bash", "-c", load_iterate_cross_verify(state_id)],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
        )

    def test_x0b_and_x1_verify_reject_paid_greater_than_real(self):
        for state_id in ("x0b", "x1"):
            with self.subTest(state_id=state_id):
                valid = self._run_verify(state_id, paid=1, real=1)
                self.assertEqual(valid.returncode, 0, valid.stderr)

                invalid = self._run_verify(state_id, paid=2, real=1)
                self.assertNotEqual(invalid.returncode, 0)
                self.assertIn("db_signups_paid bounds invariant failed", invalid.stderr)

    def test_x0b_and_x1_verify_reject_paid_zero_with_gclid_shape(self):
        """Evidence-based attribution invariant: gclid_shape without a
        positive paid count is the exact artifact shape that produced the
        perky/termob false zeros — the gates must reject it."""
        for state_id in ("x0b", "x1"):
            with self.subTest(state_id=state_id):
                invalid = self._run_verify(state_id, paid=0, real=1, attribution="gclid_shape")
                self.assertNotEqual(invalid.returncode, 0)
                self.assertIn("db_attribution/db_signups_paid invariant failed", invalid.stderr)

    def test_x0b_and_x1_verify_accept_paid_zero_with_window(self):
        """paid=0 is legal when attribution is window (gclid column present
        but never populated — the gclid-dead table shape)."""
        for state_id in ("x0b", "x1"):
            with self.subTest(state_id=state_id):
                valid = self._run_verify(state_id, paid=0, real=1, attribution="window")
                self.assertEqual(valid.returncode, 0, valid.stderr)


class TestRelaunchWindow(unittest.TestCase):
    """Phase-1 relaunch date must raise the SQL lower bound on the windowed
    signup/auth queries, and leave them unchanged when absent."""

    @patch("iterate_cross_db._management_api_query")
    def test_signups_query_carries_relaunch_bound(self, mock_api):
        mock_api.return_value = [{"email": "a@b.com", "signup_at": "2026-07-26"}]
        db.select_signups_in_window(
            "ref", "leads", "created_at", 365, relaunch_at="2026-07-25"
        )
        sql = mock_api.call_args[0][1]
        self.assertIn("greatest(", sql)
        self.assertIn("timestamptz '2026-07-25'", sql)

    @patch("iterate_cross_db._management_api_query")
    def test_signups_query_without_relaunch_is_plain_window(self, mock_api):
        mock_api.return_value = [{"email": "a@b.com", "signup_at": "2026-07-26"}]
        db.select_signups_in_window("ref", "leads", "created_at", 365)
        sql = mock_api.call_args[0][1]
        self.assertNotIn("greatest(", sql)
        self.assertIn("now() - INTERVAL '365 days'", sql)

    @patch("iterate_cross_db._management_api_query")
    def test_auth_query_carries_relaunch_bound(self, mock_api):
        mock_api.return_value = [{"email": "a@b.com", "signup_at": "2026-07-26", "email_confirmed_at": "x"}]
        db.select_auth_users_in_window("ref", 365, relaunch_at="2026-07-25")
        sql = mock_api.call_args[0][1]
        self.assertIn("greatest(", sql)
        self.assertIn("email_confirmed_at IS NOT NULL", sql)

    @patch("iterate_cross_db._management_api_query")
    def test_count_query_carries_relaunch_bound(self, mock_api):
        mock_api.return_value = [{"n": 3, "first_at": "2026-07-26"}]
        db.count_signups_in_window("ref", "leads", "created_at", 365, relaunch_at="2026-07-25")
        sql = mock_api.call_args[0][1]
        self.assertIn("greatest(", sql)


class TestLeadsTablePattern(unittest.TestCase):
    """pagoo false-zero regression: email captures in public.leads must be
    discoverable, but only as the lowest-priority pattern so existing fleet
    table selections are unchanged."""

    def test_leads_is_lowest_priority_pattern(self):
        self.assertIn("leads", db.SIGNUP_TABLE_PATTERNS)
        self.assertEqual(db.SIGNUP_TABLE_PATTERNS[-1], "leads")

    def test_leads_table_becomes_candidate(self):
        catalog = [
            {"table_name": "leads", "columns": "id,email,created_at,valid"},
            {"table_name": "track_jobs", "columns": "id,status,created_at"},
        ]
        cands = db._signup_candidates_from_catalog(catalog)
        self.assertEqual([c["table"] for c in cands], ["leads"])
        self.assertEqual(cands[0]["timestamp_column"], "created_at")

    def test_leads_never_outranks_other_signup_tables(self):
        catalog = [
            {"table_name": "leads", "columns": "id,email,created_at"},
            {"table_name": "waitlist", "columns": "id,email,created_at"},
            {"table_name": "users", "columns": "id,email,created_at"},
        ]
        cands = db._signup_candidates_from_catalog(catalog)
        self.assertEqual([c["table"] for c in cands], ["waitlist", "users", "leads"])


class BackendVerificationTests(unittest.TestCase):
    """Killed-MVP backend verification: tombstone probe + sticky db_backend."""

    def _probe(self, status, body):
        with patch("iterate_cross_db._urlopen_text", return_value=(status, json.dumps(body), None)):
            return db.probe_project_tombstone("ref_x", token="t")

    def test_tombstone_probe_status_mapping(self):
        # Live-verified mapping (2026-07-21): 200 alive; 400 removed-body =
        # deleted tombstone; 404 plain = never existed; 403 = not visible.
        self.assertEqual(self._probe(200, {"name": "x"})["status"], "alive")
        self.assertEqual(
            self._probe(400, {"message": "Resource has been removed"})["status"],
            "deleted_verified",
        )
        self.assertEqual(self._probe(404, {"message": "Not Found"})["status"], "never_existed")
        self.assertEqual(self._probe(403, {"message": "forbidden"})["status"], "not_visible")
        # Removal message wins over the bare-404 branch (SQL-endpoint variant).
        self.assertEqual(
            self._probe(404, {"message": "Project not found"})["status"],
            "deleted_verified",
        )
        # Flaky evidence never yields a status.
        self.assertIsNone(self._probe(500, {"message": "oops"})["status"])
        with patch("iterate_cross_db._urlopen_text", return_value=(None, "", "urlopen timed out")):
            self.assertIsNone(db.probe_project_tombstone("ref_x", token="t")["status"])

    def test_resolve_no_ref_is_never_located(self):
        writes: dict = {}
        rec = db.resolve_backend_state("m", {}, set(), token="t", backend_writes=writes)
        self.assertEqual(rec["status"], "never_located")
        self.assertIn("m", writes)

    def test_resolve_railway_backed_row_is_left_alone(self):
        writes: dict = {}
        rec = db.resolve_backend_state(
            "m", {"railway_project_id": "uuid"}, set(), token="t", backend_writes=writes,
        )
        self.assertIsNone(rec)
        self.assertEqual(writes, {})

    def test_resolve_membership_proves_alive_without_probe(self):
        writes: dict = {}
        with patch("iterate_cross_db.probe_project_tombstone") as mock_probe:
            rec = db.resolve_backend_state(
                "m", {"supabase_project_ref": "ref_a"}, {"ref_a"},
                token="t", backend_writes=writes,
            )
        mock_probe.assert_not_called()
        self.assertEqual(rec["status"], "alive")
        self.assertEqual(writes["m"]["status"], "alive")

    def test_resolve_terminal_sticky_is_never_reprobed(self):
        sticky = {"status": "deleted_verified", "checked_at": "2026-07-21T00:00:00Z"}
        writes: dict = {}
        with patch("iterate_cross_db.probe_project_tombstone") as mock_probe:
            rec = db.resolve_backend_state(
                "m", {"supabase_project_ref": "ref_a", "db_backend": sticky}, set(),
                token="t", backend_writes=writes,
            )
        mock_probe.assert_not_called()
        self.assertEqual(rec, sticky)
        self.assertEqual(writes, {})

    def test_resolve_flaky_probe_never_persists(self):
        writes: dict = {}
        with patch(
            "iterate_cross_db.probe_project_tombstone",
            return_value={"status": None, "http_status": 500, "message": "oops"},
        ):
            rec = db.resolve_backend_state(
                "m", {"supabase_project_ref": "ref_a"}, set(),
                token="t", backend_writes=writes,
            )
        self.assertIsNone(rec)
        self.assertEqual(writes, {})

    def test_resolve_unchanged_status_with_checked_at_not_requeued(self):
        sticky = {"status": "alive", "checked_at": "2026-07-20T00:00:00Z"}
        writes: dict = {}
        rec = db.resolve_backend_state(
            "m", {"supabase_project_ref": "ref_a", "db_backend": sticky}, {"ref_a"},
            token="t", backend_writes=writes,
        )
        self.assertEqual(rec["status"], "alive")
        self.assertEqual(writes, {})  # idempotent: no rewrite churn

    @patch("iterate_cross_db.list_supabase_projects")
    @patch("iterate_cross_db.query_mvp_ground_truth")
    def test_merge_killed_absent_ref_probes_tombstone_and_persists(self, mock_q, mock_list):
        mock_list.return_value = [{"id": "ref_other", "name": "other"}]
        with tempfile.TemporaryDirectory() as t:
            ctx_path = os.path.join(t, "ctx.json")
            cfg_path = os.path.join(t, "cfg.yaml")
            with open(ctx_path, "w") as f:
                json.dump({"window_days": 90, "mvps": [{"name": "dead-mvp"}]}, f)
            import yaml as _yaml
            with open(cfg_path, "w") as f:
                _yaml.safe_dump({"mvp_mappings": {
                    "dead-mvp": {
                        "supabase_project_ref": "ref_dead",
                        "lifecycle_status": "killed",
                    },
                }}, f)
            with patch(
                "iterate_cross_db.probe_project_tombstone",
                return_value={"status": "deleted_verified", "http_status": 400,
                              "message": "Resource has been removed"},
            ):
                _ = db.merge_into_context(ctx_path, cfg_path, auto_confirm=True)
            updated = json.load(open(ctx_path))
            cfg_after = _yaml.safe_load(open(cfg_path))

        mock_q.assert_not_called()
        m = updated["mvps"][0]
        self.assertEqual(m["db_unmapped_reason"], "archived_killed")
        self.assertEqual((m.get("db_backend") or {}).get("status"), "deleted_verified")
        sticky = cfg_after["mvp_mappings"]["dead-mvp"]["db_backend"]
        self.assertEqual(sticky["status"], "deleted_verified")
        self.assertIn("http 400", sticky["evidence"])

    @patch("iterate_cross_db.list_supabase_projects")
    def test_verify_backends_summary_and_dry_run(self, mock_list):
        mock_list.return_value = [{"id": "ref_alive", "name": "alive-mvp"}]
        with tempfile.TemporaryDirectory() as t:
            cfg_path = os.path.join(t, "cfg.yaml")
            import yaml as _yaml
            with open(cfg_path, "w") as f:
                _yaml.safe_dump({"mvp_mappings": {
                    "alive-mvp": {"supabase_project_ref": "ref_alive", "lifecycle_status": "killed"},
                    "gone-mvp": {"supabase_project_ref": "ref_gone", "lifecycle_status": "killed"},
                    "lost-mvp": {"lifecycle_status": "killed"},
                    "active-mvp": {"supabase_project_ref": "ref_x", "lifecycle_status": "active"},
                    "__orphan_x__": {"lifecycle_status": "killed"},
                }}, f)
            with patch(
                "iterate_cross_db.probe_project_tombstone",
                return_value={"status": "deleted_verified", "http_status": 400,
                              "message": "Resource has been removed"},
            ):
                dry = db.verify_backends(cfg_path, token="t", dry_run=True)
                cfg_mid = _yaml.safe_load(open(cfg_path))
                wet = db.verify_backends(cfg_path, token="t", dry_run=False)
                cfg_after = _yaml.safe_load(open(cfg_path))

        # active + orphan rows are excluded; 3 killed rows classified.
        self.assertEqual(dry["killed_rows"], 3)
        self.assertEqual(dry["would_write"], 3)
        self.assertEqual(dry["written"], 0)
        # Dry-run must not touch the config.
        self.assertNotIn("db_backend", cfg_mid["mvp_mappings"]["alive-mvp"])
        self.assertEqual(wet["written"], 3)
        self.assertEqual(wet["by_status"], {
            "alive": 1, "deleted_verified": 1, "never_located": 1,
        })
        self.assertEqual(cfg_after["mvp_mappings"]["alive-mvp"]["db_backend"]["status"], "alive")
        self.assertEqual(cfg_after["mvp_mappings"]["gone-mvp"]["db_backend"]["status"], "deleted_verified")
        self.assertEqual(cfg_after["mvp_mappings"]["lost-mvp"]["db_backend"]["status"], "never_located")


if __name__ == "__main__":
    unittest.main()
