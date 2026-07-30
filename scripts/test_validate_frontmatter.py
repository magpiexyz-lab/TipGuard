"""Tests for validate-frontmatter.py check functions."""

import os
import sys
import pytest
import yaml

# Add scripts dir to path for imports
sys.path.insert(0, os.path.dirname(__file__))

from conftest import fake_stack_file, fake_skill_file

# Import check functions from the refactored validator
import importlib.util
spec = importlib.util.spec_from_file_location(
    "validate_frontmatter",
    os.path.join(os.path.dirname(__file__), "validate-frontmatter.py"),
)
vf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vf)


# ---------------------------------------------------------------------------
# Check 1: Stack files have all required frontmatter keys
# ---------------------------------------------------------------------------


class TestCheck1StackFrontmatterKeys:
    def test_passes_with_all_keys(self, tmp_path):
        sf = str(tmp_path / "test.md")
        fake_stack_file(sf)
        errors, data = vf.check_1_stack_frontmatter_keys([sf])
        assert errors == []
        assert sf in data

    def test_fails_missing_key(self, tmp_path):
        sf = str(tmp_path / "test.md")
        with open(sf, "w") as f:
            f.write("---\nassumes: []\npackages: {}\n---\n")
        errors, _ = vf.check_1_stack_frontmatter_keys([sf])
        assert len(errors) > 0
        assert any("missing required key" in e for e in errors)

    def test_fails_missing_frontmatter(self, tmp_path):
        sf = str(tmp_path / "test.md")
        with open(sf, "w") as f:
            f.write("# No frontmatter\n")
        errors, _ = vf.check_1_stack_frontmatter_keys([sf])
        assert any("missing frontmatter" in e for e in errors)


# ---------------------------------------------------------------------------
# Check 2: Assumes entries resolve
# ---------------------------------------------------------------------------


class TestCheck2AssumesResolve:
    def test_passes_when_assumes_exist(self, tmp_path):
        os.makedirs(tmp_path / ".claude" / "stacks" / "database", exist_ok=True)
        dep_path = str(tmp_path / ".claude" / "stacks" / "database" / "supabase.md")
        fake_stack_file(dep_path)
        stack_data = {"test.md": {"assumes": ["database/supabase"]}}
        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            errors = vf.check_2_assumes_resolve(stack_data)
        finally:
            os.chdir(old_cwd)
        assert errors == []

    def test_fails_when_assumes_missing(self):
        stack_data = {"test.md": {"assumes": ["nonexistent/provider"]}}
        errors = vf.check_2_assumes_resolve(stack_data)
        assert len(errors) == 1
        assert "does not exist" in errors[0]


# ---------------------------------------------------------------------------
# Check 2b: Archetype frontmatter keys
# ---------------------------------------------------------------------------


class TestCheck2bArchetypeFrontmatterKeys:
    def test_passes_with_all_keys(self, tmp_path):
        af = str(tmp_path / "web-app.md")
        fm = {
            "description": "Web application",
            "required_stacks": ["framework"],
            "optional_stacks": ["database"],
            "excluded_stacks": [],
            "required_experiment_fields": ["pages"],
            "build_command": "npm run build",
        }
        with open(af, "w") as f:
            f.write("---\n" + yaml.dump(fm) + "---\n")
        errors, _ = vf.check_2b_archetype_frontmatter_keys([af])
        assert errors == []

    def test_fails_missing_key(self, tmp_path):
        af = str(tmp_path / "web-app.md")
        with open(af, "w") as f:
            f.write("---\ndescription: test\n---\n")
        errors, _ = vf.check_2b_archetype_frontmatter_keys([af])
        assert len(errors) > 0


# ---------------------------------------------------------------------------
# Check 3: Skill frontmatter keys
# ---------------------------------------------------------------------------


class TestCheck3SkillFrontmatterKeys:
    def test_passes_with_all_keys(self, tmp_path):
        sf = str(tmp_path / "test.md")
        fake_skill_file(sf)
        errors, data = vf.check_3_skill_frontmatter_keys([sf])
        assert errors == []
        assert sf in data

    def test_fails_missing_key(self, tmp_path):
        sf = str(tmp_path / "test.md")
        with open(sf, "w") as f:
            f.write("---\ntype: code-writing\n---\n")
        errors, _ = vf.check_3_skill_frontmatter_keys([sf])
        assert len(errors) > 0


# ---------------------------------------------------------------------------
# Check 4: References exist
# ---------------------------------------------------------------------------


class TestCheck4ReferencesExist:
    def test_passes_when_references_exist(self, tmp_path):
        ref_file = str(tmp_path / "verify.md")
        with open(ref_file, "w") as f:
            f.write("# Verify\n")
        skill_data = {"skill.md": {"references": [ref_file]}}
        errors = vf.check_4_references_exist(skill_data)
        assert errors == []

    def test_fails_when_reference_missing(self):
        skill_data = {"skill.md": {"references": ["/nonexistent/file.md"]}}
        errors = vf.check_4_references_exist(skill_data)
        assert len(errors) == 1
        assert "does not exist" in errors[0]


# ---------------------------------------------------------------------------
# Check 5: verify.md in code-writing skills
# ---------------------------------------------------------------------------


class TestCheck5VerifyMd:
    def test_passes_when_verify_present(self):
        skill_data = {
            "change.md": {
                "type": "code-writing",
                "references": [".claude/patterns/verify.md"],
            }
        }
        errors = vf.check_5_verify_md_in_code_writing(skill_data)
        assert errors == []

    def test_fails_when_verify_missing(self):
        skill_data = {
            "change.md": {
                "type": "code-writing",
                "references": [".claude/patterns/branch.md"],
            }
        }
        errors = vf.check_5_verify_md_in_code_writing(skill_data)
        assert len(errors) == 1
        assert "verify.md" in errors[0]

    def test_skips_non_code_writing(self):
        skill_data = {
            "iterate.md": {
                "type": "analysis",
                "references": [],
            }
        }
        errors = vf.check_5_verify_md_in_code_writing(skill_data)
        assert errors == []


# ---------------------------------------------------------------------------
# Check 6: branch.md in code-writing skills
# ---------------------------------------------------------------------------


class TestCheck6BranchMd:
    def test_passes_when_branch_present(self):
        skill_data = {
            "change.md": {
                "type": "code-writing",
                "references": [".claude/patterns/branch.md"],
            }
        }
        errors = vf.check_6_branch_md_in_code_writing(skill_data)
        assert errors == []

    def test_fails_when_branch_missing(self):
        skill_data = {
            "change.md": {
                "type": "code-writing",
                "references": [".claude/patterns/verify.md"],
            }
        }
        errors = vf.check_6_branch_md_in_code_writing(skill_data)
        assert len(errors) == 1
        assert "branch.md" in errors[0]


# ---------------------------------------------------------------------------
# Check 7: CLAUDE.md skill list
# ---------------------------------------------------------------------------


class TestCheck7ClaudeMdSkillList:
    def test_passes_when_lists_match(self, tmp_path):
        skill_files = [
            str(tmp_path / "bootstrap.md"),
            str(tmp_path / "change.md"),
        ]
        for sf in skill_files:
            with open(sf, "w") as f:
                f.write("")
        claude_content = (
            "outside a defined skill (/bootstrap, /change)"
        )
        errors = vf.check_7_claude_md_skill_list(skill_files, claude_content)
        assert errors == []

    def test_fails_when_lists_mismatch(self, tmp_path):
        skill_files = [
            str(tmp_path / "bootstrap.md"),
            str(tmp_path / "change.md"),
            str(tmp_path / "deploy.md"),
        ]
        for sf in skill_files:
            with open(sf, "w") as f:
                f.write("")
        claude_content = "outside a defined skill (/bootstrap, /change)"
        errors = vf.check_7_claude_md_skill_list(skill_files, claude_content)
        assert len(errors) == 1
        assert "mismatch" in errors[0]


# ---------------------------------------------------------------------------
# Check 8: ci_placeholders in ci.yml
# ---------------------------------------------------------------------------


class TestCheck8CiPlaceholders:
    def test_passes_when_all_keys_present(self):
        stack_data = {
            "test.md": {"ci_placeholders": {"NEXT_PUBLIC_KEY": "value"}}
        }
        ci_content = "env:\n  NEXT_PUBLIC_KEY: placeholder\n"
        errors = vf.check_8_ci_placeholders_in_ci_yml(stack_data, ci_content)
        assert errors == []

    def test_fails_when_key_missing(self):
        stack_data = {
            "test.md": {"ci_placeholders": {"MISSING_KEY": "value"}}
        }
        ci_content = "env:\n  OTHER_KEY: placeholder\n"
        errors = vf.check_8_ci_placeholders_in_ci_yml(stack_data, ci_content)
        assert len(errors) == 1
        assert "MISSING_KEY" in errors[0]


# ---------------------------------------------------------------------------
# Check 9: ci_placeholders values in gitleaks
# ---------------------------------------------------------------------------


class TestCheck9CiPlaceholdersGitleaks:
    def test_passes_when_matched(self):
        stack_data = {
            "test.md": {"ci_placeholders": {"KEY": "phc_placeholder"}}
        }
        gitleaks_content = "[[rules]]\nallowlist = '''phc_.*'''"
        errors = vf.check_9_ci_placeholders_in_gitleaks(stack_data, gitleaks_content)
        assert errors == []

    def test_skips_urls(self):
        stack_data = {
            "test.md": {"ci_placeholders": {"URL": "https://example.com"}}
        }
        gitleaks_content = ""
        errors = vf.check_9_ci_placeholders_in_gitleaks(stack_data, gitleaks_content)
        assert errors == []

    def test_fails_when_not_matched(self):
        stack_data = {
            "test.md": {"ci_placeholders": {"KEY": "unmatched-value"}}
        }
        gitleaks_content = "[[rules]]\nallowlist = '''phc_.*'''"
        errors = vf.check_9_ci_placeholders_in_gitleaks(stack_data, gitleaks_content)
        assert len(errors) == 1


# ---------------------------------------------------------------------------
# Check 10: branch_prefix in CLAUDE.md Rule 1
# ---------------------------------------------------------------------------


class TestCheck10BranchPrefix:
    def test_passes_when_prefix_allowed(self):
        skill_data = {"change.md": {"branch_prefix": "feat"}}
        claude_content = "Branch naming: `feat/<topic>`, `fix/<topic>`, `chore/<topic>`"
        errors = vf.check_10_branch_prefix_in_claude_md(skill_data, claude_content)
        assert errors == []

    def test_fails_when_prefix_not_allowed(self):
        skill_data = {"change.md": {"branch_prefix": "wip"}}
        claude_content = "Branch naming: `feat/<topic>`, `fix/<topic>`"
        errors = vf.check_10_branch_prefix_in_claude_md(skill_data, claude_content)
        assert len(errors) == 1
        assert "wip" in errors[0]


# ---------------------------------------------------------------------------
# Check 11: observe.md in references
# ---------------------------------------------------------------------------


class TestCheck11ObserveMd:
    def test_passes_when_observe_present(self):
        skill_data = {
            "change.md": {
                "type": "code-writing",
                "references": [".claude/patterns/observe.md"],
            }
        }
        errors = vf.check_11_observe_md_in_references(skill_data)
        assert errors == []

    def test_fails_for_code_writing_without_observe(self):
        skill_data = {
            "change.md": {
                "type": "code-writing",
                "references": [".claude/patterns/verify.md"],
            }
        }
        errors = vf.check_11_observe_md_in_references(skill_data)
        assert len(errors) == 1
        assert "observe.md" in errors[0]

    def test_fails_for_deploy_without_observe(self):
        skill_data = {
            "deploy.md": {
                "type": "other",
                "references": [],
            }
        }
        errors = vf.check_11_observe_md_in_references(skill_data)
        assert len(errors) == 1
