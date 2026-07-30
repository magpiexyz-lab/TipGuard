#!/usr/bin/env python3
"""Gate /distribute campaign creation on fresh passing /ads-ready artifacts."""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


DEFAULT_STATIC = ".runs/ads-ready-static-result.json"
DEFAULT_SMOKE = ".runs/ads-ready-smoke-result.json"
CONTEXT_PATH = ".runs/distribute-context.json"
VALID_PHASES = {"phase-1", "phase-2"}
IDENTITY_FIELDS = {"skill", "run_id", "written_at"}
REMEDIATION = (
    "Run `/ads-ready phase-1` after the latest deploy, then re-run `/distribute` "
    "— it resumes at the campaign step."
)


class GateResult:
    def __init__(
        self,
        ok: bool,
        message: str,
        *,
        phase: str | None = None,
        git_head: str | None = None,
    ) -> None:
        self.ok = ok
        self.message = message
        self.phase = phase
        self.git_head = git_head


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _parse_time(value: str) -> _dt.datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = _dt.datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.astimezone(_dt.timezone.utc)


def _current_head(injected: str | None = None) -> str | None:
    if injected:
        return injected
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            check=False,
            text=True,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _read_json_artifact(path: str, label: str) -> tuple[dict[str, Any] | None, str | None]:
    artifact = Path(path)
    if not artifact.exists():
        return None, f"missing {label} artifact: {path}"
    try:
        data = json.loads(artifact.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, f"could not parse {label} artifact {path}: {exc}"
    if not isinstance(data, dict):
        return None, f"{label} artifact {path} is not a JSON object"
    return data, None


def _artifact_phase(data: dict[str, Any], label: str) -> tuple[str | None, str | None]:
    phase = data.get("phase")
    if phase not in VALID_PHASES:
        return None, f"{label} artifact phase missing or invalid: {phase!r}"
    return str(phase), None


def check_gate(
    static_path: str,
    smoke_path: str,
    *,
    current_head: str | None,
    now: _dt.datetime,
    max_smoke_age_hours: float,
) -> GateResult:
    if not current_head:
        return GateResult(False, "current git HEAD could not be resolved")

    static, error = _read_json_artifact(static_path, "static")
    if error:
        return GateResult(False, error)
    smoke, error = _read_json_artifact(smoke_path, "smoke")
    if error:
        return GateResult(False, error)
    assert static is not None
    assert smoke is not None

    if static.get("overall_pass") is not True:
        return GateResult(False, "static ads-ready result failed")
    if smoke.get("skipped") is True:
        return GateResult(False, "smoke ads-ready result was skipped; static-only runs cannot launch ads")
    if smoke.get("overall_pass") is not True:
        return GateResult(False, "smoke ads-ready result failed")

    static_head = static.get("git_head")
    smoke_head = smoke.get("git_head")
    if not static_head:
        return GateResult(False, "git_head missing from static ads-ready artifact")
    if not smoke_head:
        return GateResult(False, "git_head missing from smoke ads-ready artifact")
    if static_head != current_head:
        return GateResult(
            False,
            f"static git_head mismatch: artifact {static_head}, current {current_head}",
        )
    if smoke_head != current_head:
        return GateResult(
            False,
            f"smoke git_head mismatch: artifact {smoke_head}, current {current_head}",
        )

    static_phase, error = _artifact_phase(static, "static")
    if error:
        return GateResult(False, error)
    smoke_phase, error = _artifact_phase(smoke, "smoke")
    if error:
        return GateResult(False, error)
    if static_phase != smoke_phase:
        return GateResult(
            False,
            f"phase mismatch between ads-ready artifacts: static {static_phase}, smoke {smoke_phase}",
        )

    timestamp = smoke.get("timestamp")
    if not isinstance(timestamp, str) or not timestamp:
        return GateResult(False, "smoke timestamp missing or invalid")
    try:
        smoke_time = _parse_time(timestamp)
    except Exception as exc:
        return GateResult(False, f"smoke timestamp missing or invalid: {exc}")
    max_age = _dt.timedelta(hours=max_smoke_age_hours)
    age = now.astimezone(_dt.timezone.utc) - smoke_time
    if age > max_age:
        return GateResult(
            False,
            f"smoke result is older than {max_smoke_age_hours:g} hours",
        )

    return GateResult(
        True,
        f"ads-ready gate passed: {static_phase} artifacts are fresh for {current_head}",
        phase=static_phase,
        git_head=current_head,
    )


def _read_context() -> dict[str, Any]:
    path = Path(CONTEXT_PATH)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _deep_merge(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _phase_from_context(ctx: dict[str, Any]) -> str:
    phase = ctx.get("phase")
    if phase in VALID_PHASES:
        return str(phase)
    if phase == 2 or phase == "2":
        return "phase-2"
    return "phase-1"


def emit_record(
    *,
    passed: bool = False,
    skipped: bool = False,
    phase: str,
    git_head: str | None,
    checked_at: str,
    reason: str | None = None,
) -> dict[str, Any]:
    context = {k: v for k, v in _read_context().items() if k not in IDENTITY_FIELDS}
    existing_gate = context.get("ads_ready_gate")
    if isinstance(existing_gate, dict):
        context["ads_ready_gate"] = {
            k: v for k, v in existing_gate.items() if k not in {"passed", "skipped", "reason"}
        }
    gate: dict[str, Any] = {
        "phase": phase,
        "git_head": git_head,
        "checked_at": checked_at,
    }
    if passed:
        gate["passed"] = True
    if skipped:
        gate["skipped"] = True
    if reason:
        gate["reason"] = reason
    return _deep_merge(context, {"ads_ready_gate": gate})


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--static", default=DEFAULT_STATIC)
    parser.add_argument("--smoke", default=DEFAULT_SMOKE)
    parser.add_argument("--max-smoke-age-hours", type=float, default=24.0)
    parser.add_argument("--emit-record", action="store_true")
    parser.add_argument("--skip")
    parser.add_argument("--head", default=os.environ.get("ADS_READY_GATE_HEAD"), help=argparse.SUPPRESS)
    parser.add_argument("--now", default=os.environ.get("ADS_READY_GATE_NOW"), help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        now = _parse_time(args.now) if args.now else _utc_now()
    except Exception as exc:
        print(f"ads-ready gate failed: invalid --now value: {exc}", file=sys.stderr)
        return 1
    checked_at = now.astimezone(_dt.timezone.utc).isoformat()
    head = _current_head(args.head)

    if args.skip:
        if not args.emit_record:
            print("ads-ready gate failed: --skip requires --emit-record", file=sys.stderr)
            return 1
        payload = emit_record(
            skipped=True,
            phase=_phase_from_context(_read_context()),
            git_head=head,
            checked_at=checked_at,
            reason=args.skip,
        )
        print(json.dumps(payload, indent=2))
        return 0

    result = check_gate(
        args.static,
        args.smoke,
        current_head=head,
        now=now,
        max_smoke_age_hours=args.max_smoke_age_hours,
    )
    if not result.ok:
        print(f"ads-ready gate failed: {result.message}", file=sys.stderr)
        print(REMEDIATION, file=sys.stderr)
        return 1

    if args.emit_record:
        payload = emit_record(
            passed=True,
            phase=result.phase or "phase-1",
            git_head=result.git_head,
            checked_at=checked_at,
        )
        print(json.dumps(payload, indent=2))
    else:
        print(result.message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
