"""Tests for consistency-check.sh via subprocess."""

import os
import subprocess
import textwrap

import pytest
import yaml


def run_consistency_check(cwd):
    """Run consistency-check.sh in the given directory."""
    script_path = os.path.join(
        os.path.dirname(__file__), "consistency-check.sh"
    )
    result = subprocess.run(
        ["bash", script_path],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    return result


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(textwrap.dedent(content))


class TestConsistencyCheckCleanTemplate:
    """Test that the real template passes consistency checks."""

    def test_passes_on_real_template(self):
        result = subprocess.run(
            ["bash", "scripts/consistency-check.sh"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "PASSED" in result.stdout


class TestCheck1EventEnumerationsInClaudeMd:
    """CLAUDE.md must not enumerate event definitions inline."""

    def test_passes_when_clean(self, tmp_path):
        write_file(
            str(tmp_path / "CLAUDE.md"),
            "# Rules\nSee experiment/EVENTS.yaml for event definitions.\n",
        )
        # Need a code-writing skill to populate CODE_WRITING_SKILLS array (bash set -u)
        (tmp_path / ".claude" / "commands").mkdir(parents=True)
        write_file(
            str(tmp_path / ".claude" / "commands" / "test.md"),
            "---\ntype: code-writing\n---\nFollow patterns/verify.md.\n",
        )
        result = run_consistency_check(tmp_path)
        assert result.returncode == 0

    def test_fails_with_event_enumeration(self, tmp_path):
        write_file(
            str(tmp_path / "CLAUDE.md"),
            "# Rules\n- `visit_landing` — fires on page load\n",
        )
        (tmp_path / ".claude" / "commands").mkdir(parents=True)
        result = run_consistency_check(tmp_path)
        assert result.returncode == 1
        assert "enumerated event definitions" in result.stdout


class TestCheck3HardcodedAnalyticsPaths:
    """Skill files must not hardcode analytics import paths."""

    def test_passes_when_clean(self, tmp_path):
        (tmp_path / ".claude" / "commands").mkdir(parents=True)
        write_file(
            str(tmp_path / ".claude" / "commands" / "test.md"),
            "---\ntype: code-writing\n---\nUse the analytics library.\nFollow patterns/verify.md.\n",
        )
        write_file(str(tmp_path / "CLAUDE.md"), "# Rules\n")
        result = run_consistency_check(tmp_path)
        assert result.returncode == 0

    def test_fails_with_hardcoded_path(self, tmp_path):
        (tmp_path / ".claude" / "commands").mkdir(parents=True)
        write_file(
            str(tmp_path / ".claude" / "commands" / "test.md"),
            '---\ntype: code-writing\n---\nimport from @/lib/analytics\n',
        )
        write_file(str(tmp_path / "CLAUDE.md"), "# Rules\n")
        result = run_consistency_check(tmp_path)
        assert result.returncode == 1
        assert "hardcoded import path" in result.stdout


class TestCheck4FrameworkTermsInClaudeMd:
    """CLAUDE.md must not use framework-specific terms."""

    def test_fails_with_server_actions(self, tmp_path):
        write_file(
            str(tmp_path / "CLAUDE.md"),
            "# Rules\nUse Server Actions for mutations.\n",
        )
        (tmp_path / ".claude" / "commands").mkdir(parents=True)
        result = run_consistency_check(tmp_path)
        assert result.returncode == 1
        assert "framework-specific" in result.stdout


class TestCheck10VerifyMdInContent:
    """Code-writing skill content must reference verify.md."""

    def test_passes_when_verify_referenced(self, tmp_path):
        (tmp_path / ".claude" / "commands").mkdir(parents=True)
        write_file(
            str(tmp_path / ".claude" / "commands" / "change.md"),
            "---\ntype: code-writing\n---\nFollow patterns/verify.md for validation.\n",
        )
        write_file(str(tmp_path / "CLAUDE.md"), "# Rules\n")
        result = run_consistency_check(tmp_path)
        assert result.returncode == 0

    def test_fails_when_verify_not_referenced(self, tmp_path):
        (tmp_path / ".claude" / "commands").mkdir(parents=True)
        write_file(
            str(tmp_path / ".claude" / "commands" / "change.md"),
            "---\ntype: code-writing\n---\nBuild stuff.\n",
        )
        write_file(str(tmp_path / "CLAUDE.md"), "# Rules\n")
        result = run_consistency_check(tmp_path)
        assert result.returncode == 1
        assert "verify.md" in result.stdout


class TestCheck13ProviderNamesInHeadings:
    """Skill section headings must not hardcode analytics provider names."""

    def test_passes_when_clean(self, tmp_path):
        (tmp_path / ".claude" / "commands").mkdir(parents=True)
        write_file(
            str(tmp_path / ".claude" / "commands" / "test.md"),
            "---\ntype: code-writing\n---\n### Analytics Setup\nContent.\nFollow patterns/verify.md.\n",
        )
        write_file(str(tmp_path / "CLAUDE.md"), "# Rules\n")
        result = run_consistency_check(tmp_path)
        assert result.returncode == 0

    def test_fails_with_posthog_heading(self, tmp_path):
        (tmp_path / ".claude" / "commands").mkdir(parents=True)
        write_file(
            str(tmp_path / ".claude" / "commands" / "test.md"),
            "---\ntype: code-writing\n---\n### PostHog Setup\nContent.\n",
        )
        write_file(str(tmp_path / "CLAUDE.md"), "# Rules\n")
        result = run_consistency_check(tmp_path)
        assert result.returncode == 1
        assert "provider name" in result.stdout


def _minimal_clean_layout(tmp_path):
    """Create just enough for the other checks to pass so we can isolate 20/21/22."""
    (tmp_path / ".claude" / "commands").mkdir(parents=True)
    write_file(
        str(tmp_path / ".claude" / "commands" / "test.md"),
        "---\ntype: code-writing\n---\nFollow patterns/verify.md.\n",
    )
    write_file(str(tmp_path / "CLAUDE.md"), "# Rules\n")


class TestCheck20MakefileCiParity:
    """Makefile lint-template must cover every template validator CI runs."""

    def test_passes_when_no_ci_workflows(self, tmp_path):
        # No .github/workflows → nothing to mirror, Check 20 is vacuously ok.
        _minimal_clean_layout(tmp_path)
        result = run_consistency_check(tmp_path)
        assert "Check 20: Makefile lint-template ↔ CI validators parity... ok" in result.stdout

    def test_passes_when_makefile_mirrors_ci(self, tmp_path):
        _minimal_clean_layout(tmp_path)
        (tmp_path / ".github" / "workflows").mkdir(parents=True)
        write_file(
            str(tmp_path / ".github" / "workflows" / "ci.yml"),
            "name: CI\nsteps:\n  - run: python3 scripts/validate-foo.py\n",
        )
        write_file(
            str(tmp_path / "Makefile"),
            "lint-template:\n\t@python3 scripts/validate-foo.py\n",
        )
        result = run_consistency_check(tmp_path)
        assert "Check 20: Makefile lint-template ↔ CI validators parity... ok" in result.stdout

    def test_fails_when_makefile_missing_validator(self, tmp_path):
        _minimal_clean_layout(tmp_path)
        (tmp_path / ".github" / "workflows").mkdir(parents=True)
        write_file(
            str(tmp_path / ".github" / "workflows" / "ci.yml"),
            "name: CI\nsteps:\n  - run: python3 scripts/validate-foo.py\n  - run: python3 scripts/validate-bar.py\n",
        )
        write_file(
            str(tmp_path / "Makefile"),
            "lint-template:\n\t@python3 scripts/validate-foo.py\n",
        )
        result = run_consistency_check(tmp_path)
        assert result.returncode == 1
        assert "Makefile lint-template drifted from CI validators" in result.stdout
        assert "validate-bar.py" in result.stdout

    def test_passes_when_ci_only_comment_covers_gap(self, tmp_path):
        _minimal_clean_layout(tmp_path)
        (tmp_path / ".github" / "workflows").mkdir(parents=True)
        write_file(
            str(tmp_path / ".github" / "workflows" / "ci.yml"),
            "name: CI\nsteps:\n  - run: python3 scripts/validate-foo.py\n  - run: python3 scripts/validate-bar.py\n",
        )
        write_file(
            str(tmp_path / "Makefile"),
            "# CI-ONLY: python3 scripts/validate-bar.py\n"
            "lint-template:\n\t@python3 scripts/validate-foo.py\n",
        )
        result = run_consistency_check(tmp_path)
        assert "Check 20: Makefile lint-template ↔ CI validators parity... ok" in result.stdout

    def test_passes_when_validator_split_across_lint_template_targets(self, tmp_path):
        # Multi-target case: lint-template has one validator, lint-template-tests has another.
        # Check 20 should union both under the lint-template* family.
        _minimal_clean_layout(tmp_path)
        (tmp_path / ".github" / "workflows").mkdir(parents=True)
        write_file(
            str(tmp_path / ".github" / "workflows" / "ci.yml"),
            "name: CI\nsteps:\n  - run: python3 scripts/validate-foo.py\n  - run: python3 -m pytest scripts/\n",
        )
        write_file(
            str(tmp_path / "Makefile"),
            "lint-template:\n\t@python3 scripts/validate-foo.py\n\n"
            "lint-template-tests:\n\t@python3 -m pytest scripts/\n",
        )
        result = run_consistency_check(tmp_path)
        assert "Check 20: Makefile lint-template ↔ CI validators parity... ok" in result.stdout

    def test_fails_when_ci_only_lists_stale_entry(self, tmp_path):
        _minimal_clean_layout(tmp_path)
        (tmp_path / ".github" / "workflows").mkdir(parents=True)
        write_file(
            str(tmp_path / ".github" / "workflows" / "ci.yml"),
            "name: CI\nsteps:\n  - run: python3 scripts/validate-foo.py\n",
        )
        write_file(
            str(tmp_path / "Makefile"),
            "# CI-ONLY: python3 scripts/validate-gone.py\n"
            "lint-template:\n\t@python3 scripts/validate-foo.py\n",
        )
        result = run_consistency_check(tmp_path)
        assert result.returncode == 1
        assert "STALE-CI-ONLY" in result.stdout
        assert "validate-gone.py" in result.stdout


class TestCheck21NoAutoFlag:
    """No gh pr merge --auto anywhere under .claude/ (allow_auto_merge=false footgun)."""

    def test_passes_when_clean(self, tmp_path):
        _minimal_clean_layout(tmp_path)
        (tmp_path / ".claude" / "scripts").mkdir(parents=True)
        write_file(
            str(tmp_path / ".claude" / "scripts" / "finalize.sh"),
            "#!/bin/bash\ngh pr merge --squash\n",
        )
        result = run_consistency_check(tmp_path)
        assert "Check 21: No gh pr merge --auto under .claude/... ok" in result.stdout

    def test_fails_when_auto_flag_present(self, tmp_path):
        _minimal_clean_layout(tmp_path)
        (tmp_path / ".claude" / "scripts").mkdir(parents=True)
        write_file(
            str(tmp_path / ".claude" / "scripts" / "bad.sh"),
            "#!/bin/bash\ngh pr merge --auto --squash\n",
        )
        result = run_consistency_check(tmp_path)
        assert result.returncode == 1
        assert "forbidden --auto flag" in result.stdout

    def test_passes_when_auto_is_behind_do_not_marker(self, tmp_path):
        # DO_NOT marker in doc prose should be skipped (this is how auto-merge.md
        # discusses the forbidden pattern without tripping the check).
        _minimal_clean_layout(tmp_path)
        (tmp_path / ".claude" / "patterns").mkdir(parents=True)
        write_file(
            str(tmp_path / ".claude" / "patterns" / "auto-merge.md"),
            "# Auto-Merge\n\n# DO_NOT: gh pr merge --auto  # silently immediate-merges\n",
        )
        result = run_consistency_check(tmp_path)
        assert "Check 21: No gh pr merge --auto under .claude/... ok" in result.stdout


class TestCheck22MergeCallerAllowlist:
    """gh pr merge must only be called from lifecycle-finalize.sh or auto-merge.md."""

    def test_passes_when_only_allowlisted_callers(self, tmp_path):
        _minimal_clean_layout(tmp_path)
        (tmp_path / ".claude" / "scripts").mkdir(parents=True)
        (tmp_path / ".claude" / "patterns").mkdir(parents=True)
        write_file(
            str(tmp_path / ".claude" / "scripts" / "lifecycle-finalize.sh"),
            "#!/bin/bash\ngh pr merge --squash\n",
        )
        write_file(
            str(tmp_path / ".claude" / "patterns" / "auto-merge.md"),
            "# Auto-Merge\n```bash\ngh pr merge --squash\n```\n",
        )
        result = run_consistency_check(tmp_path)
        assert "Check 22: gh pr merge callers restricted to allowlist... ok" in result.stdout

    def test_fails_when_rogue_caller_added(self, tmp_path):
        _minimal_clean_layout(tmp_path)
        (tmp_path / ".claude" / "scripts").mkdir(parents=True)
        write_file(
            str(tmp_path / ".claude" / "scripts" / "rogue.sh"),
            "#!/bin/bash\ngh pr merge --squash\n",
        )
        result = run_consistency_check(tmp_path)
        assert result.returncode == 1
        assert "gh pr merge called outside allowlist" in result.stdout
        assert "rogue.sh" in result.stdout

    def test_passes_when_rogue_mention_is_behind_do_not_marker(self, tmp_path):
        _minimal_clean_layout(tmp_path)
        (tmp_path / ".claude" / "hooks").mkdir(parents=True)
        write_file(
            str(tmp_path / ".claude" / "hooks" / "some-hook.sh"),
            "#!/bin/bash\n# DO_NOT: do not call 'gh pr merge' here — use lifecycle-finalize.sh\n",
        )
        result = run_consistency_check(tmp_path)
        assert "Check 22: gh pr merge callers restricted to allowlist... ok" in result.stdout


_DEMO_REGISTRY = [
    ("accessibility-scanner", 3096),
    ("behavior-verifier", 3097),
    ("ux-journeyer", 3098),
    ("design-critic", 3099),
]


def _demo_procedure_body(port):
    """Minimal valid procedure body containing the canonical command + REF."""
    return (
        "# Procedure\n\n"
        "### Start Server\n\n"
        "```bash\n"
        f"DEMO_MODE=true NEXT_PUBLIC_DEMO_MODE=true npm run start -- -p {port} &\n"
        "```\n\n"
        f"Poll `http://localhost:{port}` until it responds (max 15 seconds, then abort).\n\n"
        "> REF: see `.claude/patterns/demo-server-startup.md`.\n"
    )


def _demo_clean_layout(tmp_path):
    """Set up pattern file + all 4 procedures with correct snippets and REFs."""
    _minimal_clean_layout(tmp_path)
    (tmp_path / ".claude" / "patterns").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".claude" / "procedures").mkdir(parents=True, exist_ok=True)
    write_file(
        str(tmp_path / ".claude" / "patterns" / "demo-server-startup.md"),
        "# Demo-Mode Dev-Server Startup\nCanonical reference.\n",
    )
    for proc, port in _DEMO_REGISTRY:
        write_file(
            str(tmp_path / ".claude" / "procedures" / f"{proc}.md"),
            _demo_procedure_body(port),
        )


class TestCheck24DemoServerStartupDrift:
    """The 4 registered procedures must inline the canonical snippet with the
    registered port AND carry a REF line. No unregistered procedure may inline
    the snippet. Skip cleanly when the canonical pattern file is absent."""

    def test_skips_when_no_pattern_file(self, tmp_path):
        _minimal_clean_layout(tmp_path)
        result = run_consistency_check(tmp_path)
        assert (
            "Check 24: demo-server-startup canonical snippet drift... skip (no canonical)"
            in result.stdout
        )

    def test_passes_when_clean(self, tmp_path):
        _demo_clean_layout(tmp_path)
        result = run_consistency_check(tmp_path)
        assert (
            "Check 24: demo-server-startup canonical snippet drift... ok"
            in result.stdout
        ), result.stdout

    def test_fails_when_port_drifts(self, tmp_path):
        _demo_clean_layout(tmp_path)
        # design-critic is registered at 3099; rewrite it to 4099.
        write_file(
            str(tmp_path / ".claude" / "procedures" / "design-critic.md"),
            _demo_procedure_body(4099)
            .replace("localhost:4099", "localhost:3099"),  # leave poll line alone — only the command port drifts
        )
        result = run_consistency_check(tmp_path)
        assert result.returncode == 1
        assert "demo-server-startup drift detected" in result.stdout
        assert "design-critic.md" in result.stdout
        assert "port drifted" in result.stdout

    def test_fails_when_ref_line_missing(self, tmp_path):
        _demo_clean_layout(tmp_path)
        body_no_ref = _demo_procedure_body(3098).replace(
            "> REF: see `.claude/patterns/demo-server-startup.md`.\n", ""
        )
        write_file(
            str(tmp_path / ".claude" / "procedures" / "ux-journeyer.md"),
            body_no_ref,
        )
        result = run_consistency_check(tmp_path)
        assert result.returncode == 1
        assert "missing REF line" in result.stdout
        assert "ux-journeyer.md" in result.stdout

    def test_fails_when_unregistered_procedure_inlines_snippet(self, tmp_path):
        _demo_clean_layout(tmp_path)
        write_file(
            str(tmp_path / ".claude" / "procedures" / "rogue-procedure.md"),
            _demo_procedure_body(3100),
        )
        result = run_consistency_check(tmp_path)
        assert result.returncode == 1
        assert "rogue-procedure.md" in result.stdout
        assert "not in Check 24 registry" in result.stdout


class TestCheck27ClientIpHelper:
    """Stack-file rate-limit examples must use clientIpFromHeaders helper.

    Recurrence guard for #1361: Vercel proxy appends the verified client IP as
    the LAST X-Forwarded-For entry. A raw `headers.get("x-forwarded-for")`
    read used as a rate-limit key lets attackers rotate the header prefix to
    bypass the per-IP cap. The canonical fix is the `clientIpFromHeaders`
    helper exported from `src/lib/rate-limit`.

    These tests are also the fail-closed guard against deletion of Check 27
    itself: if a future maintainer removes the check from
    consistency-check.sh, both tests fail in CI (`pytest scripts/`).
    """

    def test_blocks_raw_xff_in_stack_file(self, tmp_path):
        # Minimum scaffold so consistency-check.sh's earlier checks pass and
        # we exercise Check 27 specifically. Need a code-writing skill so the
        # CODE_WRITING_SKILLS array is non-empty (bash set -u).
        (tmp_path / ".claude" / "commands").mkdir(parents=True)
        write_file(
            str(tmp_path / ".claude" / "commands" / "test.md"),
            "---\ntype: code-writing\n---\nFollow patterns/verify.md.\n",
        )
        # Stack file with raw XFF read in a code block, no helper definition.
        write_file(
            str(tmp_path / ".claude" / "stacks" / "hosting" / "test-host.md"),
            (
                "# Test host\n\n"
                "```ts\n"
                'import { rateLimit } from "@/lib/rate-limit";\n'
                'const ip = request.headers.get("x-forwarded-for") ?? "unknown";\n'
                "const { success } = rateLimit(ip);\n"
                "```\n"
            ),
        )
        result = run_consistency_check(tmp_path)
        assert result.returncode == 1
        assert "Check 27" in result.stdout
        assert "clientIpFromHeaders" in result.stdout

    def test_passes_when_helper_defined_in_same_block(self, tmp_path):
        (tmp_path / ".claude" / "commands").mkdir(parents=True)
        write_file(
            str(tmp_path / ".claude" / "commands" / "test.md"),
            "---\ntype: code-writing\n---\nFollow patterns/verify.md.\n",
        )
        # Stack file where the SAME code block contains both the helper
        # definition (function clientIpFromHeaders) and the literal XFF read.
        # This is the canonical helper-definition pattern shipped by
        # vercel.md and is allowed.
        write_file(
            str(tmp_path / ".claude" / "stacks" / "hosting" / "test-host.md"),
            (
                "# Test host\n\n"
                "```ts\n"
                "export function clientIpFromHeaders(headers: Headers): string {\n"
                '  const xff = headers.get("x-forwarded-for");\n'
                '  return xff?.split(",").at(-1)?.trim() ?? "unknown";\n'
                "}\n"
                "```\n"
            ),
        )
        result = run_consistency_check(tmp_path)
        assert result.returncode == 0
        assert "Check 27" in result.stdout
        assert "PASSED" in result.stdout
