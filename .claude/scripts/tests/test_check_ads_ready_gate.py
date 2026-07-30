#!/usr/bin/env python3
"""Tests for .claude/scripts/lib/check_ads_ready_gate.py."""

from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import check_ads_ready_gate as G  # noqa: E402


NOW = "2026-06-10T12:00:00+00:00"
OLD = "2026-06-08T12:00:00+00:00"
HEAD = "abc123"


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def artifact(
    *,
    overall_pass: bool | None = True,
    phase: str = "phase-1",
    git_head: str | None = HEAD,
    timestamp: str = NOW,
    skipped: bool = False,
    omit_git_head: bool = False,
) -> dict:
    data = {
        "skill": "ads-ready",
        "layer": "A",
        "timestamp": timestamp,
        "phase": phase,
        "checks": [],
        "overall_pass": overall_pass,
    }
    if not omit_git_head:
        data["git_head"] = git_head
    if skipped:
        data["skipped"] = True
    return data


def setup_artifacts(tmp_path: Path, static: dict | None = None, smoke: dict | None = None) -> tuple[Path, Path]:
    static_path = tmp_path / "static.json"
    smoke_path = tmp_path / "smoke.json"
    write_json(static_path, static or artifact())
    write_json(smoke_path, smoke or artifact())
    return static_path, smoke_path


def run_gate(args: list[str]) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = G.main(args)
    return rc, out.getvalue(), err.getvalue()


def base_args(static_path: Path, smoke_path: Path) -> list[str]:
    return [
        "--static",
        str(static_path),
        "--smoke",
        str(smoke_path),
        "--head",
        HEAD,
        "--now",
        NOW,
    ]


def test_missing_file_fails_with_remediation(tmp_path: Path) -> None:
    smoke_path = tmp_path / "smoke.json"
    write_json(smoke_path, artifact())

    rc, _out, err = run_gate(base_args(tmp_path / "missing.json", smoke_path))

    assert rc == 1
    assert "missing static artifact" in err
    assert "Run `/ads-ready phase-1`" in err


def test_static_fail_blocks(tmp_path: Path) -> None:
    static_path, smoke_path = setup_artifacts(tmp_path, static=artifact(overall_pass=False))

    rc, _out, err = run_gate(base_args(static_path, smoke_path))

    assert rc == 1
    assert "static ads-ready result failed" in err


def test_smoke_skipped_blocks(tmp_path: Path) -> None:
    static_path, smoke_path = setup_artifacts(
        tmp_path,
        smoke=artifact(overall_pass=None, skipped=True),
    )

    rc, _out, err = run_gate(base_args(static_path, smoke_path))

    assert rc == 1
    assert "smoke ads-ready result was skipped" in err


def test_smoke_fail_blocks(tmp_path: Path) -> None:
    static_path, smoke_path = setup_artifacts(tmp_path, smoke=artifact(overall_pass=False))

    rc, _out, err = run_gate(base_args(static_path, smoke_path))

    assert rc == 1
    assert "smoke ads-ready result failed" in err


def test_git_head_mismatch_blocks(tmp_path: Path) -> None:
    static_path, smoke_path = setup_artifacts(tmp_path, static=artifact(git_head="old"))

    rc, _out, err = run_gate(base_args(static_path, smoke_path))

    assert rc == 1
    assert "static git_head mismatch" in err


def test_git_head_absent_blocks(tmp_path: Path) -> None:
    static_path, smoke_path = setup_artifacts(tmp_path, static=artifact(omit_git_head=True))

    rc, _out, err = run_gate(base_args(static_path, smoke_path))

    assert rc == 1
    assert "git_head missing from static" in err


def test_old_smoke_blocks(tmp_path: Path) -> None:
    static_path, smoke_path = setup_artifacts(tmp_path, smoke=artifact(timestamp=OLD))

    rc, _out, err = run_gate(base_args(static_path, smoke_path) + ["--max-smoke-age-hours", "24"])

    assert rc == 1
    assert "smoke result is older than 24 hours" in err


@pytest.mark.parametrize("phase", ["phase-1", "phase-2"])
def test_fresh_pass_accepts_phase_artifacts(tmp_path: Path, phase: str) -> None:
    static_path, smoke_path = setup_artifacts(
        tmp_path,
        static=artifact(phase=phase),
        smoke=artifact(phase=phase),
    )

    rc, out, err = run_gate(base_args(static_path, smoke_path))

    assert rc == 0
    assert err == ""
    assert f"ads-ready gate passed: {phase}" in out


def test_emit_record_preserves_context_and_strips_identity(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    static_path, smoke_path = setup_artifacts(tmp_path)
    write_json(
        tmp_path / ".runs" / "distribute-context.json",
        {
            "skill": "distribute",
            "run_id": "old-run",
            "written_at": "old-time",
            "approved": True,
            "nested": {"keep": "yes"},
            "ads_ready_gate": {"old": "keep", "skipped": True, "reason": "old"},
        },
    )

    rc, out, err = run_gate(base_args(static_path, smoke_path) + ["--emit-record"])
    payload = json.loads(out)

    assert rc == 0
    assert err == ""
    assert payload["approved"] is True
    assert payload["nested"] == {"keep": "yes"}
    assert "skill" not in payload
    assert "run_id" not in payload
    assert "written_at" not in payload
    assert payload["ads_ready_gate"]["old"] == "keep"
    assert payload["ads_ready_gate"]["passed"] is True
    assert "skipped" not in payload["ads_ready_gate"]
    assert "reason" not in payload["ads_ready_gate"]
    assert payload["ads_ready_gate"]["phase"] == "phase-1"
    assert payload["ads_ready_gate"]["git_head"] == HEAD
    assert payload["ads_ready_gate"]["checked_at"] == NOW


def test_emit_record_skip_preserves_context_and_marks_reason(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_json(
        tmp_path / ".runs" / "distribute-context.json",
        {
            "phase": 1,
            "approved": True,
            "ads_ready_gate": {"old": "keep", "passed": True},
        },
    )

    rc, out, err = run_gate(
        ["--emit-record", "--skip", "existing_campaign", "--head", HEAD, "--now", NOW]
    )
    payload = json.loads(out)

    assert rc == 0
    assert err == ""
    assert payload["approved"] is True
    assert payload["ads_ready_gate"]["old"] == "keep"
    assert payload["ads_ready_gate"]["skipped"] is True
    assert "passed" not in payload["ads_ready_gate"]
    assert payload["ads_ready_gate"]["reason"] == "existing_campaign"
    assert payload["ads_ready_gate"]["phase"] == "phase-1"
    assert payload["ads_ready_gate"]["git_head"] == HEAD
