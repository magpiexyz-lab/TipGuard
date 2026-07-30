#!/usr/bin/env python3
"""iterate_cross_auth.py — one-shot auth preflight for /iterate --cross.

Why this exists: credential gaps used to surface mid-run (Supabase/Railway at
state-x0b, after the PostHog discovery + operator confirm already ran) or not
at all (a missing Vercel token silently disabled the owner-resolution channel,
mis-attributing MVPs to the operator for days). This preflight runs as the
FIRST step of a cross run, checks every required service, lists ALL missing
ones at once with exact login instructions, and exits non-zero so the operator
logs in before any data work starts.

Required set by mode:
  cross         → posthog + supabase + railway + vercel
  cross-phase2  → posthog + supabase + railway   (x5 never uses the Vercel channel)

`require_db_ground_truth: false` in experiment/iterate-cross-config.yaml
downgrades supabase + railway to non-gating warnings (same semantics as the
state-x0b defense-in-depth gate, which stays in place). PostHog and Vercel are
always hard requirements — operator decision 2026-07-27; there is no bypass.

Checks are presence/probe only (~2s total): Supabase gets a live
GET /v1/projects probe (catches revoked tokens), the others are local presence
checks. A revoked Railway/Vercel token still passes and degrades mid-run
exactly as before.

Output contract (--emit-payload): the JSON payload goes to stdout so the
caller can persist it via write-gate-artifact.sh; the human checklist goes to
stderr. Exit 0 iff all required checks pass.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

POSTHOG_KEY_PATH = "~/.posthog/personal-api-key"

_FIXES = {
    "posthog": (
        "Create a personal API key at https://us.posthog.com/settings/user-api-keys "
        "(scope: Query Read, Project Read), then: "
        "mkdir -p ~/.posthog && echo 'phx_YOUR_KEY' > ~/.posthog/personal-api-key"
    ),
    "supabase": (
        "Run `supabase login` once (token lands in the macOS Keychain, which this "
        "check reads) or export SUPABASE_ACCESS_TOKEN / write ~/.supabase/access-token."
    ),
    "railway": (
        "Run `! railway login` in the prompt box (the `!` prefix lets the browser "
        "flow run in your session)."
    ),
    "vercel": (
        "Run `vercel login` (the CLI auth.json is read directly), or export "
        "VERCEL_TOKEN, or write a scoped token to ~/.vercel/api-token."
    ),
}


def _check(name: str, ok: bool, detail: str) -> dict:
    return {"name": name, "ok": bool(ok), "detail": detail, "fix": _FIXES[name]}


def check_posthog() -> dict:
    path = os.path.expanduser(POSTHOG_KEY_PATH)
    try:
        content = open(path).read().strip()
    except OSError:
        content = ""
    if content:
        return _check("posthog", True, f"personal API key present at {POSTHOG_KEY_PATH}")
    return _check("posthog", False, f"no personal API key at {POSTHOG_KEY_PATH}")


def check_supabase() -> dict:
    from iterate_cross_db import _read_token, probe_supabase_projects

    try:
        token = _read_token()
    except SystemExit as exc:
        return _check("supabase", False, str(exc).splitlines()[0])
    probe = probe_supabase_projects(token)
    if probe.get("ok"):
        n = len(probe.get("projects") or [])
        return _check("supabase", True, f"Management API probe ok ({n} projects visible)")
    return _check(
        "supabase", False,
        f"token resolved but GET /v1/projects failed: {probe.get('reason')}",
    )


def check_railway() -> dict:
    from iterate_cross_railway_db import _check_railway_auth

    err = _check_railway_auth()
    if err is None:
        return _check("railway", True, "railway whoami reports a logged-in account")
    return _check("railway", False, err)


def check_vercel() -> dict:
    from iterate_cross_vercel import vercel_token

    if vercel_token():
        return _check(
            "vercel", True,
            "token resolved ($VERCEL_TOKEN / ~/.vercel/api-token / CLI auth.json)",
        )
    return _check("vercel", False, "no token in env, ~/.vercel/api-token, or CLI auth.json")


_CHECKS_BY_MODE = {
    "cross": ("posthog", "supabase", "railway", "vercel"),
    "cross-phase2": ("posthog", "supabase", "railway"),
}

# supabase/railway soften to warnings under require_db_ground_truth: false;
# posthog/vercel never do.
_DB_CHECKS = frozenset({"supabase", "railway"})

_CHECK_FNS = {
    "posthog": check_posthog,
    "supabase": check_supabase,
    "railway": check_railway,
    "vercel": check_vercel,
}


def load_config(path: str) -> dict:
    try:
        import yaml
    except ImportError:
        return {}
    if not os.path.exists(path):
        return {}
    try:
        return yaml.safe_load(open(path)) or {}
    except Exception:
        return {}


def run_preflight(mode: str, config: dict) -> dict:
    require_db = bool(config.get("require_db_ground_truth", True))
    checks = {}
    missing = []
    for name in _CHECKS_BY_MODE[mode]:
        result = _CHECK_FNS[name]()
        required = require_db or name not in _DB_CHECKS
        result["required"] = required
        checks[name] = result
        if required and not result["ok"]:
            missing.append(name)
    return {
        "mode": mode,
        "require_db_ground_truth": require_db,
        "checks": checks,
        "missing": missing,
        "all_required_ok": not missing,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def render_checklist(payload: dict) -> str:
    lines = [f"Auth preflight ({payload['mode']}):"]
    for name, c in payload["checks"].items():
        mark = "✅" if c["ok"] else ("⚠️ " if not c["required"] else "❌")
        lines.append(f"  {mark} {name}: {c['detail']}")
    missing = payload["missing"]
    if missing:
        lines.append("")
        lines.append(
            "STOP: /iterate --cross requires the services above before any data work."
        )
        lines.append("Fix ALL of the following, then re-run:")
        for name in missing:
            lines.append(f"  • {name}: {payload['checks'][name]['fix']}")
    else:
        soft_fails = [n for n, c in payload["checks"].items() if not c["ok"]]
        if soft_fails:
            lines.append(
                "  (warnings above are non-gating: require_db_ground_truth is false)"
            )
        lines.append("Auth preflight passed.")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="One-shot auth preflight for /iterate --cross (fail fast on missing logins)."
    )
    parser.add_argument("--mode", required=True, choices=sorted(_CHECKS_BY_MODE))
    parser.add_argument("--config", default="experiment/iterate-cross-config.yaml")
    parser.add_argument(
        "--emit-payload", action="store_true",
        help="Print the JSON payload to stdout (checklist goes to stderr).",
    )
    args = parser.parse_args(argv)

    payload = run_preflight(args.mode, load_config(args.config))
    checklist = render_checklist(payload)
    if args.emit_payload:
        print(checklist, file=sys.stderr)
        print(json.dumps(payload))
    else:
        print(checklist)
    return 0 if payload["all_required_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
