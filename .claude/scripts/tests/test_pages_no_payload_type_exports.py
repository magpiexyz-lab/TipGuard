#!/usr/bin/env python3
"""Behavioral tests for verify-linter.sh check_pages_no_payload_type_exports().

Validates that the #1161 (b) coherence rule catches payload-shape type
declarations in page files (both exported and local — round-2 Concern 3 fix)
and detects name collisions against src/lib/types.ts exports, while exempting
framework files (layout/loading/error) and API routes.

Run via: python3 .claude/scripts/tests/test_pages_no_payload_type_exports.py
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest


REAL_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
LINTER = os.path.join(REAL_REPO, ".claude", "scripts", "verify-linter.sh")
LIB_DIR = os.path.join(REAL_REPO, ".claude", "scripts", "lib")


def _setup_minimal_repo(tmpdir: str, rules: dict, files: dict[str, str]):
    os.makedirs(os.path.join(tmpdir, ".claude/scripts/lib"), exist_ok=True)
    os.makedirs(os.path.join(tmpdir, ".claude/patterns"), exist_ok=True)
    os.makedirs(os.path.join(tmpdir, ".claude/skills"), exist_ok=True)

    shutil.copy(LINTER, os.path.join(tmpdir, ".claude/scripts/verify-linter.sh"))
    if os.path.isdir(LIB_DIR):
        shutil.copytree(
            LIB_DIR,
            os.path.join(tmpdir, ".claude/scripts/lib"),
            dirs_exist_ok=True,
        )
    with open(os.path.join(tmpdir, ".claude/patterns/state-registry.json"), "w") as f:
        json.dump({}, f)
    with open(os.path.join(tmpdir, ".claude/patterns/template-coherence-rules.json"), "w") as f:
        json.dump(rules, f)
    for rel_path, content in files.items():
        full = os.path.join(tmpdir, rel_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(content)


def _run_linter(tmpdir: str) -> tuple[int, str]:
    result = subprocess.run(
        ["bash", os.path.join(tmpdir, ".claude/scripts/verify-linter.sh")],
        capture_output=True,
        text=True,
        cwd=tmpdir,
    )
    return result.returncode, result.stdout + result.stderr


def _rule(extras: dict | None = None) -> dict:
    base = {
        "id": "pages-no-payload-type-exports",
        "type": "pages_no_payload_type_exports",
        "severity": "block",
        "scope_glob": "src/app/**/*.tsx",
        "path_excludes": ["src/app/api/**", "**/__tests__/**"],
        "filename_excludes": [
            "layout.tsx", "loading.tsx", "error.tsx", "not-found.tsx",
            "default.tsx", "template.tsx", "*.test.tsx", "*.stories.tsx",
        ],
        "types_source_path": "src/lib/types.ts",
    }
    if extras:
        base.update(extras)
    return {"rules": [base]}


class TestPagesNoPayloadTypeExports(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_clean_page_passes(self):
        """A page with no payload-shape types and no name collisions has no findings."""
        _setup_minimal_repo(self.tmpdir, _rule(), {
            "src/app/dashboard/page.tsx":
                "export default function Page() { return <div>hi</div>; }\n",
            "src/lib/types.ts": "export type FooRow = { id: string };\n",
        })
        _, out = _run_linter(self.tmpdir)
        self.assertNotIn("pages-no-payload-type-exports", out)

    def test_exported_payload_blocks(self):
        _setup_minimal_repo(self.tmpdir, _rule(), {
            "src/app/dashboard/page.tsx":
                "export type DashboardPayload = { count: number };\n"
                "export default function Page() { return <div/>; }\n",
            "src/lib/types.ts": "",
        })
        _, out = _run_linter(self.tmpdir)
        self.assertIn("pages-no-payload-type-exports", out)
        self.assertIn("DashboardPayload", out)

    def test_local_payload_blocks(self):
        """Round-2 Concern 3: Pattern A must catch local declarations too."""
        _setup_minimal_repo(self.tmpdir, _rule(), {
            "src/app/dashboard/page.tsx":
                "type DashboardPayload = { count: number };\n"
                "export default function Page() { return <div/>; }\n",
            "src/lib/types.ts": "",
        })
        _, out = _run_linter(self.tmpdir)
        self.assertIn("pages-no-payload-type-exports", out)
        self.assertIn("DashboardPayload", out)

    def test_interface_response_blocks(self):
        _setup_minimal_repo(self.tmpdir, _rule(), {
            "src/app/dashboard/page.tsx":
                "export interface UserResponse { id: string }\n"
                "export default function Page() { return <div/>; }\n",
            "src/lib/types.ts": "",
        })
        _, out = _run_linter(self.tmpdir)
        self.assertIn("UserResponse", out)

    def test_request_schema_suffix_blocks(self):
        _setup_minimal_repo(self.tmpdir, _rule(), {
            "src/app/dashboard/page.tsx":
                "type CreateInvoiceRequest = { amount: number };\n"
                "type CreateInvoiceSchema = { foo: string };\n"
                "export default function Page() { return <div/>; }\n",
            "src/lib/types.ts": "",
        })
        _, out = _run_linter(self.tmpdir)
        self.assertIn("CreateInvoiceRequest", out)
        self.assertIn("CreateInvoiceSchema", out)

    def test_name_collision_blocks(self):
        """A page redefining a name exported from src/lib/types.ts is blocked."""
        _setup_minimal_repo(self.tmpdir, _rule(), {
            "src/app/dashboard/page.tsx":
                "export type DashboardData = { x: number };\n"
                "export default function Page() { return <div/>; }\n",
            "src/lib/types.ts":
                "export type DashboardData = { y: string };\n",
        })
        _, out = _run_linter(self.tmpdir)
        self.assertIn("DashboardData", out)
        self.assertIn("collides", out)

    def test_api_route_excluded(self):
        """API routes legitimately export Zod schemas — must NOT be flagged."""
        _setup_minimal_repo(self.tmpdir, _rule(), {
            "src/app/api/foo/route.ts":
                "export const fooSchema = z.object({});\n"
                "export type FooResponse = { id: string };\n",
            "src/lib/types.ts": "",
        })
        _, out = _run_linter(self.tmpdir)
        self.assertNotIn("pages-no-payload-type-exports", out)

    def test_layout_excluded(self):
        """Framework files (layout.tsx, loading.tsx, error.tsx) are exempt."""
        _setup_minimal_repo(self.tmpdir, _rule(), {
            "src/app/layout.tsx":
                "export type RootLayoutPayload = { x: 1 };\n"
                "export default function Layout({ children }) { return children; }\n",
            "src/app/loading.tsx":
                "export type LoadingResponse = {};\n"
                "export default function Loading() { return null; }\n",
            "src/lib/types.ts": "",
        })
        _, out = _run_linter(self.tmpdir)
        self.assertNotIn("RootLayoutPayload", out)
        self.assertNotIn("LoadingResponse", out)

    def test_test_files_excluded(self):
        _setup_minimal_repo(self.tmpdir, _rule(), {
            "src/app/dashboard/page.test.tsx":
                "type FixturePayload = { x: number };\n",
            "src/app/dashboard/__tests__/helper.tsx":
                "type HelperResponse = {};\n",
            "src/lib/types.ts": "",
        })
        _, out = _run_linter(self.tmpdir)
        self.assertNotIn("FixturePayload", out)
        self.assertNotIn("HelperResponse", out)

    def test_local_non_suffix_type_allowed(self):
        """Local types with non-suffix names are fine (e.g., props types)."""
        _setup_minimal_repo(self.tmpdir, _rule(), {
            "src/app/dashboard/page.tsx":
                "type Props = { className?: string };\n"
                "type RowData = { id: number };\n"
                "export default function Page({ className }: Props) { return <div/>; }\n",
            "src/lib/types.ts": "export type FooRow = { id: string };\n",
        })
        _, out = _run_linter(self.tmpdir)
        self.assertNotIn("pages-no-payload-type-exports", out)


if __name__ == "__main__":
    unittest.main()
