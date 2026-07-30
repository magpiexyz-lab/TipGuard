#!/usr/bin/env python3
"""Layer A entry point for /ads-ready static checks."""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ads_ready_static_helpers as H  # noqa: E402


CHECKS = [
    (1, "PROJECT_NAME consistency", H.check_project_name_drift, None),
    (2, "phc_TEAM_KEY placeholder absent", H.check_no_posthog_placeholder, None),
    (3, "analytics module reachable from landing page", H.check_analytics_module_wired, None),
    (
        4,
        "No raw posthog.{capture,identify,init,register,reset}() bypass",
        H.check_no_raw_capture,
        None,
    ),
    (
        5,
        "signup_events in mvp_mappings have track calls",
        H.check_signup_events_implemented,
        H.applies_if_iterate_cross_config_has_signup_events,
    ),
    (6, "PostHog key matches team's shared project", H.check_posthog_team_key, None),
    (
        7,
        "Supabase project in team org",
        H.check_supabase_team_org,
        H.applies_if_stack_database_supabase,
    ),
    (
        8,
        "Railway project in team workspace",
        H.check_railway_team_workspace,
        H.applies_if_stack_database_railway,
    ),
    (
        9,
        "Vercel deployment in team account",
        H.check_vercel_team_account,
        H.applies_if_stack_hosting_vercel,
    ),
    (
        10,
        "Stripe account is team's",
        H.check_stripe_team_account,
        H.applies_if_stack_payment_stripe,
    ),
    (
        11,
        "EVENTS.yaml events implemented in code",
        H.check_events_yaml_all_implemented,
        H.applies_if_events_yaml_exists,
    ),
    (
        12,
        "No track() calls outside EVENTS.yaml",
        H.check_no_unauthorized_track_calls,
        H.applies_if_events_yaml_exists,
    ),
    (13, "identify() reachable from signup handler", H.check_identify_in_signup, None),
    (
        "P2-a",
        "pay_intent event and callsite pass utm_campaign",
        H.check_phase2_pay_intent_event_and_callsite,
        H.applies_if_phase_2,
    ),
    (
        "P2-b",
        "POST /api/pay-intent inserts gclid and utm_campaign",
        H.check_phase2_pay_intent_route,
        H.applies_if_phase_2,
    ),
    (
        "P2-c",
        "pay_intent migration has attribution, auth FK, and RLS",
        H.check_phase2_pay_intent_migration,
        H.applies_if_phase_2,
    ),
    (
        "P2-d",
        "Upgrade CTA is auth and activation guarded",
        H.check_phase2_upgrade_cta_guard,
        H.applies_if_phase_2,
    ),
    (
        "P2-e",
        "No payment provider import reachable from fake-door path",
        H.check_phase2_no_payment_provider_on_fake_door_path,
        H.applies_if_phase_2,
    ),
]


PATH_RE = re.compile(
    r"(?P<path>[\w./-]+\.(?:ts|tsx|js|jsx|mjs|cjs|py|json|ya?ml|md|html))(?::(?P<line>\d+))?"
)


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _git_head() -> str | None:
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
    head = proc.stdout.strip()
    return head or None


def _phase(ctx: dict[str, Any] | None) -> str:
    data = ctx or {}
    return str(data.get("phase") or ("phase-2" if data.get("phase_2") else "phase-1"))


def _read_json(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data if isinstance(data, dict) else {}


def _check_result(
    check_id: int | str,
    name: str,
    applicable: bool,
    passed: bool | None,
    details: str,
    fix: str | None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "name": name,
        "applicable": applicable,
        "passed": passed,
        "details": details,
        "fix": fix,
    }


def _summarize(results: list[dict[str, Any]]) -> dict[str, int | bool]:
    applicable = [r for r in results if r.get("applicable") is True]
    passed = [r for r in applicable if r.get("passed") is True]
    failed = [r for r in applicable if r.get("passed") is not True]
    skipped = [r for r in results if r.get("applicable") is not True]
    return {
        "overall_pass": len(failed) == 0,
        "applicable_count": len(applicable),
        "passed_count": len(passed),
        "failed_count": len(failed),
        "skipped_count": len(skipped),
    }


def _build_output(results: list[dict[str, Any]], ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    output: dict[str, Any] = {
        "skill": "ads-ready",
        "layer": "A",
        "timestamp": _utc_now(),
        "phase": _phase(ctx),
        "git_head": _git_head(),
        "checks": results,
    }
    output.update(_summarize(results))
    return output


def _write_output(path: str, output: dict[str, Any]) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2)
        fh.write("\n")


def _extract_location(result: dict[str, Any]) -> str:
    text = f"{result.get('details') or ''}\n{result.get('fix') or ''}"
    match = PATH_RE.search(text)
    if not match:
        return "unknown:0"
    line = match.group("line") or "1"
    return f"{match.group('path')}:{line}"


def print_summary(output: dict[str, Any], stream=sys.stderr) -> None:
    status = "PASS" if output.get("overall_pass") is True else "FAIL"
    print(
        "ads-ready Layer A {status}: {passed}/{applicable} passed, "
        "{failed} failed, {skipped} skipped".format(
            status=status,
            passed=output.get("passed_count", 0),
            applicable=output.get("applicable_count", 0),
            failed=output.get("failed_count", 0),
            skipped=output.get("skipped_count", 0),
        ),
        file=stream,
    )
    for result in output.get("checks", []):
        if result.get("applicable") is True and result.get("passed") is not True:
            location = _extract_location(result)
            print(
                f"- Check {result.get('id')} {result.get('name')}: {location}",
                file=stream,
            )
            print(f"  details: {result.get('details')}", file=stream)
            print(f"  fix: {result.get('fix') or 'No fix provided.'}", file=stream)


def run_checks(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for check_id, name, helper_fn, applies_predicate in CHECKS:
        try:
            if applies_predicate is not None and not applies_predicate(ctx):
                results.append(
                    _check_result(
                        check_id,
                        name,
                        False,
                        None,
                        "N/A (not applicable to this MVP)",
                        None,
                    )
                )
                continue
            passed, details, fix = helper_fn(ctx)
            results.append(
                _check_result(
                    check_id,
                    name,
                    True,
                    bool(passed),
                    str(details),
                    None if fix is None else str(fix),
                )
            )
        except Exception as exc:
            results.append(
                _check_result(
                    check_id,
                    name,
                    True,
                    False,
                    f"INTERNAL ERROR: {exc}",
                    "Report to template maintainer.",
                )
            )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    try:
        ctx = _read_json(args.context)
        output = _build_output(run_checks(ctx), ctx)
    except Exception as exc:
        output = _build_output(
            [
                _check_result(
                    0,
                    "Layer A orchestration",
                    True,
                    False,
                    f"INTERNAL ERROR: {exc}",
                    "Report to template maintainer.",
                )
            ],
            None,
        )

    _write_output(args.output, output)
    print_summary(output, stream=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
