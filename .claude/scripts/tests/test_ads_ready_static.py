#!/usr/bin/env python3
"""Tests for .claude/scripts/lib/ads_ready_static.py."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import ads_ready_static as S  # noqa: E402


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def write_file(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_phase2_fixture(root: Path) -> None:
    files = {
        "experiment/experiment.yaml": "name: alpha\ntype: web-app\nstack:\n  analytics: posthog\n",
        "experiment/EVENTS.yaml": (
            "events:\n"
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
    for rel, content in files.items():
        write_file(root, rel, content)


class AdsReadyStaticOrchestratorTests(unittest.TestCase):
    def run_static(self, checks, context_extra: dict | None = None):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            context = root / "context.json"
            output = root / "result.json"
            ctx = {"mvp_root": str(root), "marker": "ctx"}
            if context_extra:
                ctx.update(context_extra)
            write_json(context, ctx)
            with (
                patch.object(S, "CHECKS", checks),
                patch.object(S, "_git_head", return_value="test-head"),
                patch("sys.stderr", new=io.StringIO()),
            ):
                rc = S.main(["--context", str(context), "--output", str(output)])
            return rc, json.loads(output.read_text(encoding="utf-8"))

    def test_all_checks_pass(self):
        calls = []

        def helper(ctx):
            calls.append(ctx["marker"])
            return True, "ok", None

        rc, result = self.run_static([(1, "one", helper, None), (2, "two", helper, None)])

        self.assertEqual(rc, 0)
        self.assertTrue(result["overall_pass"])
        self.assertEqual(result["passed_count"], 2)
        self.assertEqual(result["failed_count"], 0)
        self.assertEqual(calls, ["ctx", "ctx"])

    def test_some_checks_fail_and_results_accumulate(self):
        ran = []

        def passes(_ctx):
            ran.append("pass")
            return True, "ok", None

        def fails(_ctx):
            ran.append("fail")
            return False, "src/app/page.tsx:12 missing event", "Fix src/app/page.tsx:12"

        def applies_false(_ctx):
            ran.append("predicate")
            return False

        checks = [
            (1, "pass", passes, None),
            (2, "fail", fails, None),
            (3, "skip", passes, applies_false),
            (4, "pass again", passes, None),
        ]
        _rc, result = self.run_static(checks)

        self.assertFalse(result["overall_pass"])
        self.assertEqual(result["passed_count"], 2)
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(result["skipped_count"], 1)
        self.assertEqual(ran, ["pass", "fail", "predicate", "pass"])

    def test_internal_error_does_not_crash(self):
        def raises(_ctx):
            raise RuntimeError("boom")

        def passes(_ctx):
            return True, "still ran", None

        rc, result = self.run_static([(1, "raises", raises, None), (2, "passes", passes, None)])

        self.assertEqual(rc, 0)
        self.assertFalse(result["overall_pass"])
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(result["passed_count"], 1)
        self.assertIn("INTERNAL ERROR: boom", result["checks"][0]["details"])

    def test_schema_conformance(self):
        def helper(_ctx):
            return True, "ok", None

        _rc, result = self.run_static([(1, "one", helper, None)])

        self.assertEqual(result["skill"], "ads-ready")
        self.assertEqual(result["layer"], "A")
        for key in (
            "timestamp",
            "checks",
            "overall_pass",
            "applicable_count",
            "passed_count",
            "failed_count",
            "skipped_count",
        ):
            self.assertIn(key, result)
        self.assertEqual(
            set(result["checks"][0]),
            {"id", "name", "applicable", "passed", "details", "fix"},
        )

    def test_output_includes_phase_and_git_head(self):
        def helper(_ctx):
            return True, "ok", None

        _rc, result = self.run_static(
            [(1, "one", helper, None)],
            context_extra={"phase": "phase-2", "phase_2": True},
        )

        self.assertEqual(result["phase"], "phase-2")
        self.assertEqual(result["git_head"], "test-head")

    def test_orchestration_error_output_uses_safe_phase_and_git_head(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output = root / "result.json"
            with patch.object(S, "_git_head", return_value="test-head"), patch(
                "sys.stderr", new=io.StringIO()
            ):
                rc = S.main(["--context", str(root / "missing.json"), "--output", str(output)])
            result = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(rc, 0)
        self.assertFalse(result["overall_pass"])
        self.assertEqual(result["phase"], "phase-1")
        self.assertEqual(result["git_head"], "test-head")
        self.assertIn("Layer A orchestration", result["checks"][0]["name"])

    def test_phase2_checks_skip_without_phase2_and_run_with_phase2(self):
        p2_checks = [check for check in S.CHECKS if str(check[0]).startswith("P2-")]
        self.assertEqual([check[0] for check in p2_checks], ["P2-a", "P2-b", "P2-c", "P2-d", "P2-e"])

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_phase2_fixture(root)
            with patch.object(S, "CHECKS", p2_checks):
                normal = S.run_checks({"mvp_root": str(root), "phase_2": False})
                phase2 = S.run_checks({"mvp_root": str(root), "phase_2": True})

        self.assertTrue(all(result["applicable"] is False for result in normal))
        self.assertTrue(all(result["passed"] is None for result in normal))
        self.assertTrue(all(result["applicable"] is True for result in phase2))
        self.assertTrue(all(result["passed"] is True for result in phase2))


if __name__ == "__main__":
    unittest.main()
