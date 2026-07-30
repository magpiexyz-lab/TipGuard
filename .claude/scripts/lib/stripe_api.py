"""Stripe API helper using the operator's CLI auth."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

try:
    import tomllib

    _HAS_TOMLLIB = True
except ImportError:  # pragma: no cover - exercised by direct module patching
    import configparser

    _HAS_TOMLLIB = False


def _candidate_config_paths() -> list[Path]:
    paths: list[Path] = []
    if sys.platform == "darwin":
        paths.append(
            Path.home() / "Library" / "Application Support" / "Stripe" / "config.toml"
        )
    paths.append(Path.home() / ".config" / "stripe" / "config.toml")
    return paths


def _read_key_with_tomllib(path: Path) -> str | None:
    with path.open("rb") as fh:
        cfg = tomllib.load(fh)  # type: ignore[name-defined]
    for profile in cfg.values():
        if not isinstance(profile, dict):
            continue
        key = profile.get("test_mode_api_key") or profile.get("live_mode_api_key")
        if key:
            return str(key).strip('"')
    return None


def _read_key_with_configparser(path: Path) -> str | None:
    import configparser

    cfg = configparser.ConfigParser()  # type: ignore[name-defined]
    cfg.read(path)
    for section in cfg.sections():
        key = cfg[section].get("test_mode_api_key") or cfg[section].get(
            "live_mode_api_key"
        )
        if key:
            return key.strip('"')
    return None


def read_stripe_key_from_config() -> str | None:
    """Read the operator's Stripe key, preferring STRIPE_API_KEY."""
    env_key = os.environ.get("STRIPE_API_KEY")
    if env_key:
        return env_key

    for path in _candidate_config_paths():
        if not path.exists():
            continue
        try:
            if _HAS_TOMLLIB:
                key = _read_key_with_tomllib(path)
            else:
                key = _read_key_with_configparser(path)
            if key:
                return key
        except Exception:
            continue
    return None


def get_account_id(stripe_key: str) -> str | None:
    """Call GET /v1/account and return account.id, or None on failure."""
    r = subprocess.run(
        ["curl", "-s", "-u", f"{stripe_key}:", "https://api.stripe.com/v1/account"],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout).get("id")
    except Exception:
        return None
