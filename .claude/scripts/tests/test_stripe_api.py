#!/usr/bin/env python3
"""Tests for .claude/scripts/lib/stripe_api.py."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import stripe_api  # noqa: E402


def _completed(stdout: str, returncode: int = 0, stderr: str = ""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _write_config(path: Path, key: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'[default]\ntest_mode_api_key = "{key}"\n')


class StripeApiTests(unittest.TestCase):
    def test_read_stripe_key_env_wins_over_file(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            linux_path = home / ".config" / "stripe" / "config.toml"
            _write_config(linux_path, "sk_test_file")
            with patch.dict(os.environ, {"STRIPE_API_KEY": "sk_test_env"}, clear=True):
                with patch("stripe_api.Path.home", return_value=home):
                    self.assertEqual(
                        stripe_api.read_stripe_key_from_config(),
                        "sk_test_env",
                    )

    def test_read_stripe_key_macos_linux_and_none(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            mac_path = home / "Library" / "Application Support" / "Stripe" / "config.toml"
            _write_config(mac_path, "sk_test_mac")
            with patch.dict(os.environ, {}, clear=True):
                with patch("stripe_api.sys.platform", "darwin"):
                    with patch("stripe_api.Path.home", return_value=home):
                        self.assertEqual(
                            stripe_api.read_stripe_key_from_config(),
                            "sk_test_mac",
                        )

        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            linux_path = home / ".config" / "stripe" / "config.toml"
            _write_config(linux_path, "sk_test_linux")
            with patch.dict(os.environ, {}, clear=True):
                with patch("stripe_api.sys.platform", "linux"):
                    with patch("stripe_api.Path.home", return_value=home):
                        self.assertEqual(
                            stripe_api.read_stripe_key_from_config(),
                            "sk_test_linux",
                        )

        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            with patch.dict(os.environ, {}, clear=True):
                with patch("stripe_api.sys.platform", "linux"):
                    with patch("stripe_api.Path.home", return_value=home):
                        self.assertIsNone(stripe_api.read_stripe_key_from_config())

    def test_read_stripe_key_configparser_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            linux_path = home / ".config" / "stripe" / "config.toml"
            _write_config(linux_path, "sk_test_configparser")
            with patch.dict(os.environ, {}, clear=True):
                with patch("stripe_api.sys.platform", "linux"):
                    with patch("stripe_api.Path.home", return_value=home):
                        with patch("stripe_api._HAS_TOMLLIB", False):
                            self.assertEqual(
                                stripe_api.read_stripe_key_from_config(),
                                "sk_test_configparser",
                            )

    @patch("stripe_api.subprocess.run")
    def test_get_account_id_success_curl_failure_and_malformed_json(self, mock_run):
        mock_run.return_value = _completed('{"id":"acct_123"}')
        self.assertEqual(stripe_api.get_account_id("sk_test"), "acct_123")
        self.assertEqual(mock_run.call_args[0][0][-2], "sk_test:")

        mock_run.return_value = _completed("", returncode=7, stderr="offline")
        self.assertIsNone(stripe_api.get_account_id("sk_test"))

        mock_run.return_value = _completed("not-json")
        self.assertIsNone(stripe_api.get_account_id("sk_test"))


if __name__ == "__main__":
    unittest.main()
