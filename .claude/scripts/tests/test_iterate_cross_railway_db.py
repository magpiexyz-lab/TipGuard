#!/usr/bin/env python3
"""Tests for .claude/scripts/lib/iterate_cross_railway_db.py.

Network-touching calls (railway CLI, psql) are isolated in named module
functions and monkeypatched. Pure-function units (table discovery, ground
truth aggregation) get direct coverage.

Run:
  python3 .claude/scripts/tests/test_iterate_cross_railway_db.py
  # OR:
  python3 -m pytest .claude/scripts/tests/test_iterate_cross_railway_db.py -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import iterate_cross_railway_db as rw  # noqa: E402


VALID_GCLID = "Cj0KCQjw" + ("a" * 40)
JUNK_GCLID = "manual-test-gclid"


class ProjectsWithPostgresTests(unittest.TestCase):
    def test_filters_postgres_only(self):
        projs = [
            {
                "id": "p1", "name": "alpha", "workspace": "w",
                "services": [{"id": "s1", "name": "api"}, {"id": "s2", "name": "Postgres"}],
            },
            {
                "id": "p2", "name": "beta", "workspace": "w",
                "services": [{"id": "s3", "name": "Redis"}],
            },
            {
                "id": "p3", "name": "gamma", "workspace": "w",
                "services": [{"id": "s4", "name": "Postgres-5HUP"}, {"id": "s5", "name": "Postgres"}],
            },
        ]
        out = rw.projects_with_postgres(projs)
        self.assertEqual({p["name"] for p in out}, {"alpha", "gamma"})
        # gamma should expose both Postgres services
        gamma = next(p for p in out if p["name"] == "gamma")
        self.assertEqual(len(gamma["postgres_services"]), 2)

    def test_case_insensitive_match(self):
        projs = [
            {"id": "p", "name": "x", "workspace": "w",
             "services": [{"id": "s", "name": "POSTGRES"}]},
        ]
        self.assertEqual(len(rw.projects_with_postgres(projs)), 1)

    def test_excludes_database_word_alone(self):
        # 'Database' service name doesn't imply Postgres — could be Mongo/MySQL.
        # We only claim Postgres-shape services.
        projs = [
            {"id": "p", "name": "x", "workspace": "w",
             "services": [{"id": "s", "name": "Database"}]},
        ]
        self.assertEqual(rw.projects_with_postgres(projs), [])


class DiscoverSignupTablesPgTests(unittest.TestCase):
    @patch("iterate_cross_railway_db._psql_query")
    def test_prioritizes_signup_over_users(self, mock_psql):
        # Same shape as Supabase test — verifies pattern reuse.
        mock_psql.return_value = {
            "rows": [
                ["access_tokens", "id,token,expires_at"],
                ["signups", "id,email,created_at"],
                ["users", "id,email,inserted_at"],
            ],
            "error": None,
        }
        tables = rw.discover_signup_tables_pg("postgresql://fake")
        names = [t["table"] for t in tables]
        self.assertEqual(names[0], "signups")  # priority 0 wins
        self.assertNotIn("access_tokens", names)  # no pattern match

    @patch("iterate_cross_railway_db._psql_query")
    def test_handles_psql_error(self, mock_psql):
        mock_psql.return_value = {"rows": [], "error": "FATAL: connection refused"}
        self.assertEqual(rw.discover_signup_tables_pg("postgresql://bad"), [])

    @patch("iterate_cross_railway_db._psql_query")
    def test_excludes_known_false_positives(self, mock_psql):
        mock_psql.return_value = {
            "rows": [
                ["team_members", "id,user_id"],
                ["billing_users", "id,plan"],
                ["users", "id,email,created_at"],
            ],
            "error": None,
        }
        tables = rw.discover_signup_tables_pg("postgresql://fake")
        names = [t["table"] for t in tables]
        self.assertIn("users", names)
        self.assertNotIn("team_members", names)
        self.assertNotIn("billing_users", names)

    @patch("iterate_cross_railway_db._psql_query")
    def test_detects_gclid_column_name(self, mock_psql):
        mock_psql.return_value = {
            "rows": [
                ["waitlist", "id,email,created_at,gclid"],
                ["users", "id,email,created_at,click_id"],
                ["signups", "id,email,created_at"],
            ],
            "error": None,
        }
        tables = rw.discover_signup_tables_pg("postgresql://fake")
        by_name = {t["table"]: t for t in tables}
        self.assertEqual(by_name["waitlist"]["gclid_column"], "gclid")
        self.assertEqual(by_name["users"]["gclid_column"], "click_id")
        self.assertIsNone(by_name["signups"]["gclid_column"])


class QueryMvpGroundTruthRailwayTests(unittest.TestCase):
    @patch("iterate_cross_railway_db._psql_query")
    def test_picks_max_count_table_and_prefixes_railway(self, mock_psql):
        # schema query, then per-table counts.
        mock_psql.side_effect = [
            {"rows": [
                ["waitlist", "id,email,created_at"],
                ["users", "id,email,inserted_at"],
            ], "error": None},
            {"rows": [["12", "2026-04-10T00:00:00+00:00"]], "error": None},  # waitlist
            {"rows": [["45", "2026-04-05T00:00:00+00:00"]], "error": None},  # users
        ]
        result = rw.query_mvp_ground_truth_railway("postgresql://fake", window_days=90)
        self.assertEqual(result["db_signups"], 45)
        # Prefix tells x3/x4 the number came from Railway, not Supabase
        self.assertEqual(result["db_signups_table"], "railway:public.users")
        # Earliest across all tables wins
        self.assertEqual(result["db_first_signup_at"], "2026-04-05T00:00:00+00:00")

    @patch("iterate_cross_railway_db._psql_query")
    def test_returns_none_when_no_tables(self, mock_psql):
        mock_psql.return_value = {"rows": [], "error": None}
        result = rw.query_mvp_ground_truth_railway("postgresql://fake", 90)
        self.assertIsNone(result["db_signups"])
        self.assertIn("no signup-shape tables", result["errors"][0])

    @patch("iterate_cross_railway_db._psql_query")
    def test_operator_override_only_queries_one_table(self, mock_psql):
        mock_psql.side_effect = [
            # discover schema (to find ts col for override path)
            {"rows": [["waitlist_only", "id,email,created_at"]], "error": None},
            # count on the override table
            {"rows": [["17", "2026-04-15T00:00:00+00:00"]], "error": None},
        ]
        result = rw.query_mvp_ground_truth_railway(
            "postgresql://fake", window_days=90,
            operator_override_table="public.waitlist_only",
        )
        self.assertEqual(result["db_signups"], 17)
        self.assertEqual(result["db_signups_table"], "railway:public.waitlist_only")

    @patch("iterate_cross_railway_db._psql_query")
    def test_count_errors_get_captured(self, mock_psql):
        mock_psql.side_effect = [
            {"rows": [["users", "id,email,created_at"]], "error": None},
            {"rows": [], "error": "permission denied for table users"},
        ]
        result = rw.query_mvp_ground_truth_railway("postgresql://fake", 90)
        self.assertIsNone(result["db_signups"])
        self.assertTrue(any("permission denied" in e for e in result["errors"]))

    def test_auth_schema_override_rejected_clearly(self):
        # Operator copies a Supabase-style override onto a Railway MVP. Silent
        # rewrite to public.<X> would query the wrong table — must reject.
        result = rw.query_mvp_ground_truth_railway(
            "postgresql://fake", window_days=90,
            operator_override_table="auth.users",
        )
        self.assertIsNone(result["db_signups"])
        self.assertTrue(result["errors"], "must surface an error")
        msg = result["errors"][0]
        self.assertIn("auth.users", msg)
        self.assertIn("public.", msg)  # fix-it guidance
        # Sentinel table value still set so downstream can see what operator wrote
        self.assertEqual(result["db_signups_table"], "railway:auth.users")

    @patch("iterate_cross_railway_db._psql_query")
    def test_select_signups_aliases_timestamp_columns_with_window(self, mock_psql):
        mock_psql.return_value = {"rows": [], "error": None}
        for ts_col in ["created_at", "inserted_at", "signed_up_at", "submitted_at", "registered_at"]:
            with self.subTest(ts_col=ts_col):
                mock_psql.reset_mock()
                rw.select_signups_in_window_pg("postgresql://fake", "signups", ts_col, 30)
                sql = mock_psql.call_args.args[1]
                self.assertIn(f'SELECT email, "{ts_col}"::text AS signup_at', sql)
                self.assertIn(f'WHERE "{ts_col}" >= now() - INTERVAL \'30 days\'', sql)
        mock_psql.reset_mock()
        rw.select_signups_in_window_pg("postgresql://fake", "signups", None, 30)
        sql = mock_psql.call_args.args[1]
        self.assertIn("SELECT email, NULL::text AS signup_at", sql)
        self.assertNotIn("INTERVAL '30 days'", sql)

    @patch("iterate_cross_railway_db._psql_query")
    def test_query_applies_email_filter_and_uses_real_first_timestamp(self, mock_psql):
        mock_psql.side_effect = [
            {"rows": [["users", "id,email,registered_at"]], "error": None},
            {"rows": [
                ["fixture@example.com", "2026-05-01T00:00:00+00:00"],
                ["real@customer.com", "2026-05-03T00:00:00+00:00"],
                ["dev@team.test", "2026-05-02T00:00:00+00:00"],
            ], "error": None},
        ]
        cfg = {"email_filter": {"rules": {"team_domains": ["team.test"]}}}
        result = rw.query_mvp_ground_truth_railway("postgresql://fake", 60, config=cfg)
        select_sql = mock_psql.call_args_list[1].args[1]
        self.assertIn('"registered_at" >= now() - INTERVAL \'60 days\'', select_sql)
        self.assertEqual(result["db_signups_raw"], 3)
        self.assertEqual(result["db_signups_real"], 1)
        self.assertEqual(result["db_signups_team"], 1)
        self.assertEqual(result["db_signups_test"], 1)
        self.assertEqual(result["db_first_signup_at"], "2026-05-03T00:00:00+00:00")

    @patch("iterate_cross_railway_db._psql_query")
    def test_gclid_table_computes_paid_count_and_attribution(self, mock_psql):
        mock_psql.side_effect = [
            {"rows": [["waitlist", "id,email,created_at,gclid"]], "error": None},
            {"rows": [
                ["paid@customer.com", "2026-05-01T00:00:00+00:00", VALID_GCLID],
                ["organic@customer.com", "2026-05-02T00:00:00+00:00", ""],
                ["fixture@example.com", "2026-05-03T00:00:00+00:00", VALID_GCLID],
            ], "error": None},
        ]
        result = rw.query_mvp_ground_truth_railway(
            "postgresql://fake", 90, config={"email_filter": {"rules": {}}},
        )
        self.assertEqual(result["db_signups_raw"], 3)
        self.assertEqual(result["db_signups_real"], 2)
        self.assertEqual(result["db_signups_paid"], 1)
        self.assertEqual(result["db_attribution"], "gclid_shape")
        self.assertEqual(result["gclid_column"], "gclid")

    @patch("iterate_cross_railway_db._psql_query")
    def test_click_id_only_table_queries_detected_column(self, mock_psql):
        mock_psql.side_effect = [
            {"rows": [["waitlist", "id,email,created_at,click_id"]], "error": None},
            {"rows": [["paid@customer.com", "2026-05-01T00:00:00+00:00", VALID_GCLID]], "error": None},
        ]
        result = rw.query_mvp_ground_truth_railway(
            "postgresql://fake", 30, config={"email_filter": {"rules": {}}},
        )
        select_sql = mock_psql.call_args_list[1].args[1]
        self.assertIn('"click_id"', select_sql)
        self.assertNotIn('"gclid"', select_sql)
        self.assertEqual(result["gclid_column"], "click_id")
        self.assertEqual(result["db_signups_paid"], 1)

    @patch("iterate_cross_railway_db._psql_query")
    def test_no_timestamp_gclid_table_never_yields_paid_count(self, mock_psql):
        mock_psql.side_effect = [
            {"rows": [["waitlist", "id,email,gclid"]], "error": None},
            {"rows": [["paid@customer.com", "", VALID_GCLID]], "error": None},
        ]
        result = rw.query_mvp_ground_truth_railway(
            "postgresql://fake", 30, config={"email_filter": {"rules": {}}},
        )
        select_sql = mock_psql.call_args_list[1].args[1]
        self.assertIn('"gclid"', select_sql)
        self.assertNotIn("INTERVAL '30 days'", select_sql)
        self.assertEqual(result["db_signups_real"], 1)
        self.assertIsNone(result["db_signups_paid"])
        self.assertEqual(result["db_attribution"], "window")

    @patch("iterate_cross_railway_db._psql_query")
    def test_junk_gclid_not_counted_as_paid(self, mock_psql):
        mock_psql.side_effect = [
            {"rows": [["waitlist", "id,email,created_at,gclid"]], "error": None},
            {"rows": [["buyer@customer.com", "2026-05-01T00:00:00+00:00", JUNK_GCLID]], "error": None},
        ]
        result = rw.query_mvp_ground_truth_railway(
            "postgresql://fake", 90, config={"email_filter": {"rules": {}}},
        )
        self.assertEqual(result["db_signups_real"], 1)
        self.assertEqual(result["db_signups_paid"], 0)
        # Evidence-based attribution: junk gclid = no proof, stays window.
        self.assertEqual(result["db_attribution"], "window")

    @patch("iterate_cross_railway_db._psql_query")
    def test_cap_never_drops_gclid_table(self, mock_psql):
        mock_psql.side_effect = [
            {"rows": [
                *[[f"signup_{i}", "id,email,created_at"] for i in range(5)],
                ["profiles", "id,email,created_at,gclid"],
            ], "error": None},
            {"rows": [["paid@customer.com", "2026-05-01T00:00:00+00:00", VALID_GCLID]], "error": None},
            *[
                {"rows": [[f"user{i}@customer.com", "2026-05-02T00:00:00+00:00"]], "error": None}
                for i in range(5)
            ],
        ]
        result = rw.query_mvp_ground_truth_railway(
            "postgresql://fake", 90, config={"email_filter": {"rules": {}}},
        )
        queried_sql = "\n".join(call.args[1] for call in mock_psql.call_args_list)
        self.assertIn('FROM public."profiles"', queried_sql)
        # gclid table survives the cap and feeds paid into the union; the
        # top-contributor label goes to the highest-priority 1-real tie.
        self.assertEqual(result["db_signups_table"], "railway:public.signup_0")
        self.assertEqual(result["db_signups_real"], 6)
        self.assertEqual(result["db_signups_paid"], 1)
        self.assertEqual(result["db_attribution"], "gclid_shape")

    @patch("iterate_cross_railway_db._psql_query")
    def test_gclid_table_beats_larger_non_gclid_table(self, mock_psql):
        mock_psql.side_effect = [
            {"rows": [
                ["signups", "id,email,created_at"],
                ["waitlist", "id,email,created_at,gclid"],
            ], "error": None},
            {"rows": [
                ["paid@customer.com", "2026-05-01T00:00:00+00:00", VALID_GCLID],
            ], "error": None},
            {"rows": [
                [f"user{i}@customer.com", "2026-05-02T00:00:00+00:00"]
                for i in range(20)
            ], "error": None},
        ]
        result = rw.query_mvp_ground_truth_railway(
            "postgresql://fake", 90, config={"email_filter": {"rules": {}}},
        )
        # Union: 20 signups reals + 1 waitlist paid real = 21; paid evidence
        # survives, top contributor labels the row.
        self.assertEqual(result["db_signups_table"], "railway:public.signups")
        self.assertEqual(result["db_signups_real"], 21)
        self.assertEqual(result["db_signups_paid"], 1)
        self.assertEqual(result["db_attribution"], "gclid_shape")

    @patch("iterate_cross_railway_db._psql_query")
    def test_count_primary_priority_tiebreak_regression(self, mock_psql):
        mock_psql.side_effect = [
            {"rows": [
                ["signup", "id,email,created_at"],
                ["waitlist", "id,email,created_at"],
            ], "error": None},
            {"rows": [["one@customer.com", "2026-05-01T00:00:00+00:00"]], "error": None},
            {"rows": [
                [f"user{i}@customer.com", "2026-05-02T00:00:00+00:00"]
                for i in range(12)
            ], "error": None},
        ]
        result = rw.query_mvp_ground_truth_railway(
            "postgresql://fake", 90, config={"email_filter": {"rules": {}}},
        )
        # Union of both tables (1 + 12 reals); top contributor labels the row.
        self.assertEqual(result["db_signups_table"], "railway:public.waitlist")
        self.assertEqual(result["db_signups_real"], 13)
        self.assertEqual(result["priority"], 0)

    @patch("iterate_cross_railway_db._psql_query")
    def test_select_signups_pg_marks_legacy_count(self, mock_psql):
        """Aggregate (count-shaped) responses must carry the legacy_count
        marker (mirrors the Supabase twins) so the union path can exclude
        their synthetic placeholder rows."""
        mock_psql.return_value = {"rows": [["7", "2026-05-01T00:00:00+00:00"]], "error": None}
        result = rw.select_signups_in_window_pg("postgresql://fake", "waitlist", "created_at", 90)
        self.assertEqual(result["legacy_count"], 7)
        self.assertEqual(result["legacy_first_at"], "2026-05-01T00:00:00+00:00")
        self.assertEqual(len(result["rows"]), 7)

    @patch("iterate_cross_railway_db._psql_query")
    def test_union_dedupes_same_email_across_two_tables(self, mock_psql):
        mock_psql.side_effect = [
            {"rows": [
                ["waitlist", "id,email,created_at"],
                ["users", "id,email,created_at"],
            ], "error": None},
            {"rows": [
                ["J.oe+promo@gmail.com", "2026-04-20T00:00:00+00:00"],
                ["waitonly@customer.com", "2026-05-03T00:00:00+00:00"],
            ], "error": None},
            {"rows": [
                ["joe@gmail.com", "2026-05-01T00:00:00+00:00"],
                ["solo@customer.com", "2026-05-02T00:00:00+00:00"],
            ], "error": None},
        ]
        result = rw.query_mvp_ground_truth_railway(
            "postgresql://fake", 90, config={"email_filter": {"rules": {}}},
        )
        # gmail dot/plus variant dedupes: 4 rows → 3 distinct people
        self.assertEqual(result["db_signups_real"], 3)
        self.assertIsNone(result["db_signups_paid"])
        self.assertEqual(result["db_attribution"], "window")
        self.assertEqual(result["db_union_tables"], ["public.waitlist", "public.users"])
        self.assertEqual(result["db_signups_table"], "railway:public.waitlist")

    @patch("iterate_cross_railway_db._psql_query")
    def test_gclid_dead_table_with_reals_unions_second_table_perky_shape(self, mock_psql):
        """gclid column present but never populated: paid must be int 0 with
        window attribution, and the second table's reals must not be masked."""
        mock_psql.side_effect = [
            {"rows": [
                ["users", "id,email,created_at,gclid"],
                ["waitlist", "id,email,created_at"],
            ], "error": None},
            # gclid table ranks first in the probe order; all gclids empty
            {"rows": [
                [f"user{i}@customer.com", "2026-06-01T00:00:00+00:00", ""]
                for i in range(5)
            ], "error": None},
            {"rows": [
                [f"user{i}@customer.com", "2026-06-01T00:00:00+00:00"]
                for i in range(9)
            ], "error": None},
        ]
        result = rw.query_mvp_ground_truth_railway(
            "postgresql://fake", 365, config={"email_filter": {"rules": {}}},
        )
        self.assertEqual(result["db_signups_real"], 9)
        self.assertEqual(result["db_signups_paid"], 0)
        self.assertEqual(result["db_attribution"], "window")
        self.assertEqual(result["db_signups_table"], "railway:public.waitlist")
        self.assertEqual(result["db_union_tables"], ["public.waitlist", "public.users"])

    @patch("iterate_cross_railway_db._psql_query")
    def test_legacy_synthetic_rows_never_enter_union(self, mock_psql):
        """Count-shaped responses from BOTH tables: their identical synthetic
        emails must not dedupe against each other via the union."""
        mock_psql.side_effect = [
            {"rows": [
                ["waitlist", "id,email,created_at"],
                ["users", "id,email,created_at"],
            ], "error": None},
            {"rows": [["5", "2026-05-02T00:00:00+00:00"]], "error": None},
            {"rows": [["23", "2026-05-01T00:00:00+00:00"]], "error": None},
        ]
        result = rw.query_mvp_ground_truth_railway(
            "postgresql://fake", 90, config={"email_filter": {"rules": {}}},
        )
        self.assertEqual(result["db_union_tables"], [])
        self.assertEqual(result["db_signups_table"], "railway:public.users")
        self.assertEqual(result["db_signups_real"], 23)
        self.assertEqual(result["db_breakdown"]["public.waitlist"], 5)


class CheckPsqlAvailableTests(unittest.TestCase):
    @patch("iterate_cross_railway_db.subprocess.run")
    def test_returns_none_when_psql_present(self, mock_run):
        from unittest.mock import MagicMock
        mock_run.return_value = MagicMock(returncode=0, stdout="psql (PostgreSQL) 14.13", stderr="")
        self.assertIsNone(rw._check_psql_available())

    @patch("iterate_cross_railway_db.subprocess.run", side_effect=FileNotFoundError())
    def test_returns_install_hint_when_missing(self, _mock_run):
        msg = rw._check_psql_available()
        self.assertIsNotNone(msg)
        self.assertIn("psql", msg.lower())
        self.assertIn("install", msg.lower())

    @patch("iterate_cross_railway_db.subprocess.run")
    def test_returns_error_when_psql_broken(self, mock_run):
        from unittest.mock import MagicMock
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="libpq missing")
        msg = rw._check_psql_available()
        self.assertIsNotNone(msg)
        self.assertIn("returned 1", msg)


class CheckRailwayAuthMissingCliTests(unittest.TestCase):
    @patch("iterate_cross_railway_db.subprocess.run", side_effect=FileNotFoundError())
    def test_returns_install_hint_when_cli_missing(self, _mock_run):
        msg = rw._check_railway_auth()
        self.assertIsNotNone(msg)
        self.assertIn("Railway CLI not installed", msg)


class MergeIntoContextPsqlMissingTests(unittest.TestCase):
    """Verify merge_into_context returns skipped_no_psql when psql absent."""

    def _write_context(self, tmpdir, mvps):
        path = os.path.join(tmpdir, "ctx.json")
        with open(path, "w") as f:
            json.dump({"window_days": 90, "mvps": mvps}, f)
        return path

    def _write_config(self, tmpdir):
        import yaml as _yaml
        path = os.path.join(tmpdir, "cfg.yaml")
        with open(path, "w") as f:
            _yaml.safe_dump({"mvp_mappings": {}}, f)
        return path

    @patch("iterate_cross_railway_db._check_railway_auth", return_value=None)
    @patch("iterate_cross_railway_db._check_psql_available")
    def test_skips_when_psql_missing(self, mock_psql, _mock_auth):
        mock_psql.return_value = "psql not installed"
        with tempfile.TemporaryDirectory() as t:
            ctx = self._write_context(t, [{"name": "alpha", "db_signups": None, "db_unmapped_reason": "no_match"}])
            cfg = self._write_config(t)
            result = rw.merge_into_context(ctx, cfg, auto_confirm=True)
        self.assertEqual(result["step"], "skipped_no_psql")
        self.assertIn("psql", result["reason"])

    @patch("iterate_cross_railway_db._check_railway_auth", return_value=None)
    @patch("iterate_cross_railway_db._check_psql_available", return_value=None)
    @patch("iterate_cross_railway_db.list_railway_projects")
    @patch("iterate_cross_railway_db.get_database_url")
    @patch("iterate_cross_railway_db.query_mvp_ground_truth_railway")
    def test_success_sets_db_source_railway(self, mock_q, mock_url, mock_list, *_):
        # Verify db_source='railway' flows through on success.
        mock_list.return_value = [
            {"id": "rp1", "name": "alpha", "workspace": "w",
             "services": [{"id": "s", "name": "Postgres"}]},
        ]
        mock_url.return_value = {"url": "postgresql://fake", "error": None}
        mock_q.return_value = {
            "db_signups": 12, "db_signups_table": "railway:public.users",
            "db_first_signup_at": None, "db_breakdown": {"public.users": 12}, "errors": None,
        }
        with tempfile.TemporaryDirectory() as t:
            ctx = self._write_context(t, [
                {"name": "alpha", "db_signups": None, "db_unmapped_reason": "no_match"},
            ])
            cfg = self._write_config(t)
            rw.merge_into_context(ctx, cfg, auto_confirm=True)
            updated = json.load(open(ctx))
            m = updated["mvps"][0]
            self.assertEqual(m["db_source"], "railway")


class MergeIntoContextTests(unittest.TestCase):
    """Orchestrator-level tests: context I/O, candidate filtering, persistence."""

    def _write_context(self, tmpdir, mvps):
        path = os.path.join(tmpdir, "ctx.json")
        with open(path, "w") as f:
            json.dump({"window_days": 90, "mvps": mvps}, f)
        return path

    def _write_config(self, tmpdir, mappings=None):
        path = os.path.join(tmpdir, "cfg.yaml")
        import yaml as _yaml
        with open(path, "w") as f:
            _yaml.safe_dump({"mvp_mappings": mappings or {}}, f)
        return path

    @patch("iterate_cross_railway_db._check_railway_auth")
    def test_skips_when_not_authed(self, mock_auth):
        mock_auth.return_value = "Run railway login first"
        with tempfile.TemporaryDirectory() as t:
            ctx = self._write_context(t, [{"name": "alpha", "db_signups": None, "db_unmapped_reason": "no_match"}])
            cfg = self._write_config(t)
            result = rw.merge_into_context(ctx, cfg, auto_confirm=True)
        self.assertEqual(result["step"], "skipped_auth")

    @patch("iterate_cross_railway_db._check_railway_auth", return_value=None)
    @patch("iterate_cross_railway_db.list_railway_projects")
    def test_no_postgres_projects(self, mock_list, _mock_auth):
        # Workspace has projects but none with Postgres → graceful exit.
        mock_list.return_value = [
            {"id": "p", "name": "x", "workspace": "w",
             "services": [{"id": "s", "name": "Redis"}]},
        ]
        with tempfile.TemporaryDirectory() as t:
            ctx = self._write_context(t, [
                {"name": "alpha", "db_signups": None, "db_unmapped_reason": "no_match"},
            ])
            cfg = self._write_config(t)
            result = rw.merge_into_context(ctx, cfg, auto_confirm=True)
        self.assertEqual(result["step"], "no_postgres_projects")
        self.assertEqual(result["unmapped"], 1)

    @patch("iterate_cross_railway_db._check_railway_auth", return_value=None)
    @patch("iterate_cross_railway_db.list_railway_projects")
    def test_only_targets_candidates_not_already_mapped(self, mock_list, _mock_auth):
        # MVP with db_signups already set (from Supabase pass) must NOT be touched.
        mock_list.return_value = [
            {"id": "rp1", "name": "alpha", "workspace": "w",
             "services": [{"id": "s", "name": "Postgres"}]},
        ]
        with tempfile.TemporaryDirectory() as t:
            ctx = self._write_context(t, [
                {"name": "alpha", "db_signups": 50, "db_signups_table": "auth.users.confirmed"},
                {"name": "beta",  "db_signups": None, "db_unmapped_reason": "no_match"},
            ])
            cfg = self._write_config(t)
            # auto-confirm so we get to query/persist phase
            with patch("iterate_cross_railway_db.get_database_url") as mock_url, \
                 patch("iterate_cross_railway_db.query_mvp_ground_truth_railway") as mock_q:
                mock_url.return_value = {"url": "postgresql://fake", "error": None}
                mock_q.return_value = {
                    "db_signups": 7, "db_signups_table": "railway:public.users",
                    "db_first_signup_at": None, "db_breakdown": {}, "errors": None,
                }
                _ = rw.merge_into_context(ctx, cfg, auto_confirm=True)
            # Re-read and verify: alpha untouched (50 + supabase), beta updated.
            updated = json.load(open(ctx))
            alpha = next(m for m in updated["mvps"] if m["name"] == "alpha")
            beta = next(m for m in updated["mvps"] if m["name"] == "beta")
            self.assertEqual(alpha["db_signups"], 50)
            self.assertEqual(alpha.get("db_signups_table"), "auth.users.confirmed")
            # beta got Railway data (only if it fuzzy-matched 'alpha'... it doesn't,
            # so it falls into no_match_neither branch). To test SUCCESS, rename:

    @patch("iterate_cross_railway_db._check_railway_auth", return_value=None)
    @patch("iterate_cross_railway_db.list_railway_projects")
    @patch("iterate_cross_railway_db.get_database_url")
    @patch("iterate_cross_railway_db.query_mvp_ground_truth_railway")
    def test_success_path_writes_railway_fields(self, mock_q, mock_url, mock_list, _mock_auth):
        # MVP name = Railway project name (exact match)
        mock_list.return_value = [
            {"id": "rp1", "name": "neuralpost", "workspace": "w",
             "services": [{"id": "s", "name": "Postgres"}]},
        ]
        mock_url.return_value = {"url": "postgresql://fake", "error": None}
        mock_q.return_value = {
            "db_signups": 23,
            "db_signups_table": "railway:public.users",
            "db_first_signup_at": "2026-04-01T00:00:00+00:00",
            "db_breakdown": {"public.users": 23},
            "errors": None,
        }
        with tempfile.TemporaryDirectory() as t:
            ctx = self._write_context(t, [
                {"name": "neuralpost", "db_signups": None, "db_unmapped_reason": "no_match"},
            ])
            cfg = self._write_config(t)
            result = rw.merge_into_context(ctx, cfg, auto_confirm=True)
            self.assertEqual(result["step"], "merged")
            self.assertEqual(result["queried"], 1)
            updated = json.load(open(ctx))
            m = updated["mvps"][0]
            self.assertEqual(m["db_signups"], 23)
            self.assertEqual(m["db_source"], "railway")
            self.assertEqual(m["railway_project_id"], "rp1")
            self.assertEqual(m["railway_service_name"], "Postgres")
            self.assertIsNone(m["db_unmapped_reason"])
            # Config got the mapping persisted (idempotency anchor for next run)
            import yaml as _yaml
            cfg_after = _yaml.safe_load(open(cfg))
            self.assertEqual(
                cfg_after["mvp_mappings"]["neuralpost"]["railway_project_id"], "rp1"
            )

    @patch("iterate_cross_railway_db._check_railway_auth", return_value=None)
    @patch("iterate_cross_railway_db._check_psql_available", return_value=None)
    @patch("iterate_cross_railway_db.list_railway_projects")
    @patch("iterate_cross_railway_db.get_database_url")
    @patch("iterate_cross_railway_db.query_mvp_ground_truth_railway")
    def test_dry_run_leaves_context_file_untouched(self, mock_q, mock_url, mock_list, *_):
        mock_list.return_value = [
            {"id": "rp1", "name": "neuralpost", "workspace": "w",
             "services": [{"id": "s", "name": "Postgres"}]},
        ]
        mock_url.return_value = {"url": "postgresql://fake", "error": None}
        mock_q.return_value = {
            "db_signups": 23,
            "db_signups_raw": 23,
            "db_signups_real": 23,
            "db_signups_team": 0,
            "db_signups_test": 0,
            "db_signups_filter_audit": [],
            "db_signups_real_windowed": True,
            "db_signups_table": "railway:public.users",
            "db_first_signup_at": "2026-04-01T00:00:00+00:00",
            "db_breakdown": {"public.users": 23},
            "errors": None,
        }
        original = {
            "window_days": 90,
            "mvps": [{"name": "neuralpost", "db_signups": None, "db_unmapped_reason": "no_match"}],
        }
        with tempfile.TemporaryDirectory() as t:
            ctx = self._write_context(t, original["mvps"])
            cfg = self._write_config(t, {
                "neuralpost": {
                    "railway_project_id": "rp1",
                    "railway_service_name": "Postgres",
                },
            })
            result = rw.merge_into_context(ctx, cfg, auto_confirm=True, dry_run=True)

            self.assertEqual(result["step"], "merged")
            self.assertEqual(json.load(open(ctx)), original)

    @patch("iterate_cross_railway_db._check_railway_auth", return_value=None)
    @patch("iterate_cross_railway_db._check_psql_available", return_value=None)
    @patch("iterate_cross_railway_db.list_railway_projects")
    @patch("iterate_cross_railway_db.get_database_url")
    @patch("iterate_cross_railway_db._psql_query")
    def test_product_domain_filter_threads_through_railway_merge(
        self, mock_psql, mock_url, mock_list, *_,
    ):
        mock_list.return_value = [
            {"id": "rp1", "name": "alpha", "workspace": "w",
             "services": [{"id": "s", "name": "Postgres"}]},
        ]
        mock_url.return_value = {"url": "postgresql://fake", "error": None}
        mock_psql.side_effect = [
            {"rows": [["waitlist", "id,email,created_at"]], "error": None},
            {"rows": [
                ["founder@alpha.dev", "2026-05-01T00:00:00+00:00"],
                ["buyer@customer.io", "2026-05-02T00:00:00+00:00"],
            ], "error": None},
        ]
        with tempfile.TemporaryDirectory() as t:
            ctx = self._write_context(t, [
                {"name": "alpha", "db_signups": None, "db_unmapped_reason": "no_match"},
            ])
            cfg = os.path.join(t, "cfg.yaml")
            import yaml as _yaml
            with open(cfg, "w") as f:
                _yaml.safe_dump({
                    "mvp_mappings": {
                        "alpha": {
                            "railway_project_id": "rp1",
                            "railway_service_name": "Postgres",
                            "deploy_domain": "alpha.dev",
                        },
                    },
                    "email_filter": {"rules": {}},
                }, f)

            result = rw.merge_into_context(ctx, cfg, auto_confirm=True)
            updated = json.load(open(ctx))["mvps"][0]

        self.assertEqual(result["queried"], 1)
        self.assertEqual(updated["db_signups_raw"], 2)
        self.assertEqual(updated["db_signups_real"], 1)
        self.assertEqual(updated["db_signups_test"], 1)
        self.assertTrue(any(
            row.get("reason") == "product-own-domain"
            for row in updated["db_signups_filter_audit"]
        ))

    @patch("iterate_cross_railway_db._check_railway_auth", return_value=None)
    @patch("iterate_cross_railway_db.list_railway_projects")
    def test_no_candidates_when_supabase_covered_everything(self, mock_list, _mock_auth):
        mock_list.return_value = [
            {"id": "rp1", "name": "neuralpost", "workspace": "w",
             "services": [{"id": "s", "name": "Postgres"}]},
        ]
        with tempfile.TemporaryDirectory() as t:
            # Every MVP has db_signups from Supabase already
            ctx = self._write_context(t, [
                {"name": "neuralpost", "db_signups": 19, "db_signups_table": "public.early_access"},
                {"name": "diarly",     "db_signups": 30, "db_signups_table": "public.profiles"},
            ])
            cfg = self._write_config(t)
            result = rw.merge_into_context(ctx, cfg, auto_confirm=True)
        self.assertEqual(result["step"], "no_candidates")

    @patch("iterate_cross_railway_db._check_railway_auth", return_value=None)
    @patch("iterate_cross_railway_db._check_psql_available", return_value=None)
    @patch("iterate_cross_railway_db.list_railway_projects")
    @patch("iterate_cross_railway_db.get_database_url")
    @patch("iterate_cross_railway_db.query_mvp_ground_truth_railway")
    def test_refreshes_services_and_retries_sole_canonical_postgres(
        self, mock_q, mock_url, mock_list, *_,
    ):
        initial = [
            {"id": "rp1", "name": "alpha", "workspace": "w",
             "services": [{"id": "old", "name": "Old Postgres"}]},
        ]
        refreshed = [
            {"id": "rp1", "name": "alpha", "workspace": "w",
             "services": [{"id": "pg", "name": "Postgres"}]},
        ]
        mock_list.side_effect = [initial, refreshed]
        mock_url.side_effect = [
            {"url": None, "error": "service not found"},
            {"url": "postgresql://fake", "error": None},
        ]
        mock_q.return_value = {
            "db_signups": 9, "db_signups_table": "railway:public.users",
            "db_first_signup_at": None, "db_breakdown": {"public.users": 9},
            "db_signups_raw": 9, "db_signups_real": 9, "db_signups_team": 0,
            "db_signups_test": 0, "db_signups_filter_audit": [],
            "db_signups_real_windowed": True, "errors": None,
        }
        with tempfile.TemporaryDirectory() as t:
            ctx = self._write_context(t, [
                {"name": "alpha", "db_signups": None, "db_unmapped_reason": "no_match"},
            ])
            cfg = self._write_config(t, {
                "alpha": {"railway_project_id": "rp1", "railway_service_name": "Old Postgres"},
            })
            result = rw.merge_into_context(ctx, cfg, auto_confirm=True)
            updated = json.load(open(ctx))["mvps"][0]
        self.assertEqual(result["queried"], 1)
        self.assertEqual(mock_url.call_args_list[0].args[:2], ("rp1", "Old Postgres"))
        self.assertEqual(mock_url.call_args_list[1].args[:2], ("rp1", "Postgres"))
        self.assertEqual(updated["railway_service_name"], "Postgres")
        self.assertEqual(updated["db_source"], "railway")

    @patch("iterate_cross_railway_db._check_railway_auth", return_value=None)
    @patch("iterate_cross_railway_db._check_psql_available", return_value=None)
    @patch("iterate_cross_railway_db.list_railway_projects")
    @patch("iterate_cross_railway_db.get_database_url")
    def test_multiple_services_without_match_marks_service_missing(self, mock_url, mock_list, *_):
        projects = [
            {"id": "rp1", "name": "alpha", "workspace": "w",
             "services": [{"id": "pg1", "name": "Postgres A"}, {"id": "pg2", "name": "Postgres B"}]},
        ]
        mock_list.side_effect = [projects, projects]
        mock_url.return_value = {"url": None, "error": "service not found"}
        with tempfile.TemporaryDirectory() as t:
            ctx = self._write_context(t, [
                {"name": "alpha", "db_signups": None, "db_unmapped_reason": "no_match"},
            ])
            cfg = self._write_config(t, {
                "alpha": {"railway_project_id": "rp1", "railway_service_name": "Deleted Postgres"},
            })
            result = rw.merge_into_context(ctx, cfg, auto_confirm=True)
            updated = json.load(open(ctx))["mvps"][0]
        self.assertEqual(result["errors"], 1)
        self.assertEqual(updated["db_unmapped_reason"], "railway_service_missing")
        self.assertEqual(mock_url.call_count, 1)

    @patch("iterate_cross_railway_db._check_railway_auth", return_value=None)
    @patch("iterate_cross_railway_db._check_psql_available", return_value=None)
    @patch("iterate_cross_railway_db.list_railway_projects")
    @patch("iterate_cross_railway_db.get_database_url")
    @patch("iterate_cross_railway_db.query_mvp_ground_truth_railway")
    def test_candidate_selection_respects_allow_railway_fallback(
        self, mock_q, mock_url, mock_list, *_,
    ):
        reasons = {
            "alpha": "no_match",
            "beta": "no_token",
            "gamma": "no_email_column",
            "delta": "project_deleted",
            "killed": "project_deleted",
            "epsilon": "query_error",
            "zeta": "forbidden",
        }
        mock_list.return_value = [
            {"id": name, "name": name, "workspace": "w",
             "services": [{"id": f"{name}-pg", "name": "Postgres"}]}
            for name in reasons
        ]
        mock_url.return_value = {"url": "postgresql://fake", "error": None}
        mock_q.return_value = {
            "db_signups": 1, "db_signups_table": "railway:public.users",
            "db_first_signup_at": None, "db_breakdown": {"public.users": 1},
            "db_signups_raw": 1, "db_signups_real": 1, "db_signups_team": 0,
            "db_signups_test": 0, "db_signups_filter_audit": [],
            "db_signups_real_windowed": True, "errors": None,
        }
        with tempfile.TemporaryDirectory() as t:
            ctx = self._write_context(t, [
                {
                    "name": name,
                    "db_signups": None,
                    "db_unmapped_reason": reason,
                    "lifecycle_status": "killed" if name == "killed" else "active",
                }
                for name, reason in reasons.items()
            ])
            cfg = self._write_config(t)
            rw.merge_into_context(ctx, cfg, auto_confirm=True)
            updated = {m["name"]: m for m in json.load(open(ctx))["mvps"]}
        self.assertEqual(mock_q.call_count, 4)
        for name in ["alpha", "beta", "gamma", "delta"]:
            self.assertEqual(updated[name]["db_source"], "railway")
        for name in ["killed", "epsilon", "zeta"]:
            self.assertIsNone(updated[name]["db_signups"])
            self.assertNotIn("db_source", updated[name])
        self.assertEqual(updated["killed"]["lifecycle_status"], "killed")

    @patch("iterate_cross_railway_db._check_railway_auth", return_value=None)
    @patch("iterate_cross_railway_db._check_psql_available", return_value=None)
    @patch("iterate_cross_railway_db.list_railway_projects")
    def test_project_deleted_preserved_when_railway_also_misses(
        self, mock_list, *_,
    ):
        # The workspace has a Postgres project, but its name matches neither MVP,
        # so both fall into the no-Railway-match branch. The definitive Supabase
        # "project_deleted" signal must survive (x4 money-leak / archived /
        # kill-proposal key on it); only the weaker "no_match" is downgraded to
        # "no_match_neither".
        mock_list.return_value = [
            {"id": "rp-unrelated", "name": "totally-different-xyz", "workspace": "w",
             "services": [{"id": "s", "name": "Postgres"}]},
        ]
        with tempfile.TemporaryDirectory() as t:
            ctx = self._write_context(t, [
                {"name": "leasebrief", "db_signups": None, "db_unmapped_reason": "project_deleted"},
                {"name": "ctrl-nomatch", "db_signups": None, "db_unmapped_reason": "no_match"},
            ])
            cfg = self._write_config(t)
            rw.merge_into_context(ctx, cfg, auto_confirm=True)
            updated = {m["name"]: m for m in json.load(open(ctx))["mvps"]}
        self.assertEqual(updated["leasebrief"]["db_unmapped_reason"], "project_deleted")
        self.assertEqual(updated["ctrl-nomatch"]["db_unmapped_reason"], "no_match_neither")


class GetDatabaseUrlTests(unittest.TestCase):
    """Tests the link + variables subprocess sequencing in a temp dir."""

    @patch("iterate_cross_railway_db.subprocess.run")
    def test_prefers_public_url_over_internal(self, mock_run):
        # Sequence: link (success), variables --json (returns both URLs)
        from unittest.mock import MagicMock
        link = MagicMock(returncode=0, stdout="Project linked successfully! 🎉", stderr="")
        vars_r = MagicMock(returncode=0, stdout=json.dumps({
            "DATABASE_URL": "postgresql://u:p@postgres.railway.internal:5432/db",
            "DATABASE_PUBLIC_URL": "postgresql://u:p@proxy.rlwy.net:50318/db",
        }), stderr="")
        mock_run.side_effect = [link, vars_r]
        r = rw.get_database_url("test-project-id", "Postgres")
        self.assertEqual(r["error"], None)
        self.assertIn("proxy.rlwy.net", r["url"])

    @patch("iterate_cross_railway_db.subprocess.run")
    def test_link_failure_returns_error(self, mock_run):
        from unittest.mock import MagicMock
        link = MagicMock(returncode=1, stdout="", stderr="project not found")
        mock_run.return_value = link
        r = rw.get_database_url("bad-id", "Postgres")
        self.assertIsNone(r["url"])
        self.assertIn("link failed", r["error"])

    @patch("iterate_cross_railway_db.subprocess.run")
    def test_missing_database_url_in_vars(self, mock_run):
        from unittest.mock import MagicMock
        link = MagicMock(returncode=0, stdout="Project linked successfully!", stderr="")
        vars_r = MagicMock(returncode=0, stdout=json.dumps({
            "REDIS_URL": "redis://x",  # wrong service shape
        }), stderr="")
        mock_run.side_effect = [link, vars_r]
        r = rw.get_database_url("test-id", "Redis")
        self.assertIsNone(r["url"])
        self.assertIn("no DATABASE_PUBLIC_URL", r["error"])


if __name__ == "__main__":
    unittest.main()
