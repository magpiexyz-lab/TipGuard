"""Tests for iterate_cross_auth.py — the /iterate --cross auth preflight.

All service probes are patched via the _CHECK_FNS registry so no test touches
the network, the Keychain, or any CLI on the machine running the suite.
"""

import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import iterate_cross_auth as A  # noqa: E402


def _ok(name):
    return lambda: {"name": name, "ok": True, "detail": "ok", "fix": A._FIXES[name]}


def _fail(name):
    return lambda: {"name": name, "ok": False, "detail": "missing", "fix": A._FIXES[name]}


ALL_OK = {n: _ok(n) for n in ("posthog", "supabase", "railway", "vercel")}


# ---------- run_preflight ----------

def test_all_ok_passes_and_payload_schema():
    with patch.dict(A._CHECK_FNS, ALL_OK):
        payload = A.run_preflight("cross", {})
    assert payload["all_required_ok"] is True
    assert payload["missing"] == []
    assert payload["mode"] == "cross"
    assert payload["require_db_ground_truth"] is True
    assert set(payload["checks"]) == {"posthog", "supabase", "railway", "vercel"}
    for c in payload["checks"].values():
        assert {"name", "ok", "detail", "fix", "required"} <= set(c)
    assert payload["timestamp"]


def test_multiple_missing_all_listed():
    fns = dict(ALL_OK)
    fns["supabase"] = _fail("supabase")
    fns["vercel"] = _fail("vercel")
    with patch.dict(A._CHECK_FNS, fns):
        payload = A.run_preflight("cross", {})
    assert payload["all_required_ok"] is False
    assert payload["missing"] == ["supabase", "vercel"]
    checklist = A.render_checklist(payload)
    # Every missing service appears with its fix command — one-shot listing.
    assert "supabase login" in checklist
    assert "vercel login" in checklist
    assert "STOP" in checklist


def test_require_db_false_softens_supabase_and_railway_only():
    fns = dict(ALL_OK)
    fns["supabase"] = _fail("supabase")
    fns["railway"] = _fail("railway")
    with patch.dict(A._CHECK_FNS, fns):
        payload = A.run_preflight("cross", {"require_db_ground_truth": False})
    assert payload["all_required_ok"] is True
    assert payload["checks"]["supabase"]["required"] is False
    assert payload["checks"]["railway"]["required"] is False
    # Vercel/PostHog stay hard even under the DB opt-out.
    fns["vercel"] = _fail("vercel")
    with patch.dict(A._CHECK_FNS, fns):
        payload = A.run_preflight("cross", {"require_db_ground_truth": False})
    assert payload["all_required_ok"] is False
    assert payload["missing"] == ["vercel"]


def test_phase2_mode_never_checks_vercel():
    calls = []
    fns = dict(ALL_OK)

    def _vercel_spy():
        calls.append(1)
        return {"name": "vercel", "ok": True, "detail": "ok", "fix": A._FIXES["vercel"]}

    fns["vercel"] = _vercel_spy
    with patch.dict(A._CHECK_FNS, fns):
        payload = A.run_preflight("cross-phase2", {})
    assert calls == []
    assert "vercel" not in payload["checks"]
    assert payload["mode"] == "cross-phase2"


# ---------- CLI ----------

def test_main_emit_payload_streams_and_exit_codes():
    with patch.dict(A._CHECK_FNS, ALL_OK):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = A.main(["--mode", "cross", "--config", "/nonexistent.yaml", "--emit-payload"])
    assert rc == 0
    # stdout is pure JSON; checklist goes to stderr.
    payload = json.loads(out.getvalue())
    assert payload["all_required_ok"] is True
    assert "Auth preflight" in err.getvalue()

    fns = dict(ALL_OK)
    fns["railway"] = _fail("railway")
    with patch.dict(A._CHECK_FNS, fns):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = A.main(["--mode", "cross", "--config", "/nonexistent.yaml", "--emit-payload"])
    assert rc == 1
    payload = json.loads(out.getvalue())
    assert payload["missing"] == ["railway"]
    assert "railway login" in err.getvalue()
