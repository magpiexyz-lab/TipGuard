#!/usr/bin/env python3
"""Validate YAML frontmatter in stack and skill files.

Checks:
  Stack structural:
    1. Required frontmatter keys present in every stack file
    2. Every `assumes` entry resolves to an existing stack file
  Archetype structural:
    2b. Required frontmatter keys present in every archetype file
  Skill structural:
    3. Required frontmatter keys present in every skill file
    4. Every `references` file path exists on disk
    5. code-writing skills must reference verify.md
    6. code-writing skills must reference branch.md
  Cross-file:
    7. CLAUDE.md Rule 0 skill list matches actual skill filenames
    8. Union of ci_placeholders keys appears in ci.yml
    9. All ci_placeholders values are covered by .gitleaks.toml allowlist
    10. Skill branch_prefix values appear in CLAUDE.md Rule 1
    11. code-writing skills and deploy.md must reference observe.md
"""

import glob
import os
import re
import sys

import yaml

ERRORS: list[str] = []

STACK_REQUIRED_KEYS = [
    "assumes",
    "packages",
    "files",
    "env",
    "ci_placeholders",
    "clean",
    "gitignore",
]
SKILL_REQUIRED_KEYS = [
    "type",
    "reads",
    "stack_categories",
    "requires_approval",
    "references",
    "branch_prefix",
    "modifies_specs",
]
ARCHETYPE_REQUIRED_KEYS = [
    "description",
    "required_stacks",
    "optional_stacks",
    "excluded_stacks",
    "required_experiment_fields",
    "build_command",
]


def error(msg: str) -> None:
    ERRORS.append(msg)
    print(f"FAIL: {msg}", file=sys.stderr)


def parse_frontmatter(filepath: str) -> dict | None:
    """Extract YAML frontmatter from a markdown file."""
    with open(filepath) as f:
        content = f.read()
    m = re.match(r"^---\n(.*?\n)---", content, re.DOTALL)
    if not m:
        return None
    return yaml.safe_load(m.group(1))


# ---------------------------------------------------------------------------
# Check functions — each returns a list of error strings
# ---------------------------------------------------------------------------


def check_1_stack_frontmatter_keys(stack_files: list[str]) -> tuple[list[str], dict[str, dict]]:
    """Check 1: Stack files have all required frontmatter keys.

    Returns (errors, stack_data) where stack_data maps filepath to parsed frontmatter.
    """
    errors: list[str] = []
    stack_data: dict[str, dict] = {}
    for sf in stack_files:
        data = parse_frontmatter(sf)
        if data is None:
            errors.append(f"[1] {sf}: missing frontmatter")
            continue
        stack_data[sf] = data
        for key in STACK_REQUIRED_KEYS:
            if key not in data:
                errors.append(f"[1] {sf}: missing required key '{key}'")
    return errors, stack_data


def check_2_assumes_resolve(stack_data: dict[str, dict]) -> list[str]:
    """Check 2: Every assumes entry resolves to an existing stack file."""
    errors: list[str] = []
    for sf, data in stack_data.items():
        for dep in data.get("assumes", []):
            dep_path = f".claude/stacks/{dep}.md"
            if not os.path.isfile(dep_path):
                errors.append(f"[2] {sf}: assumes '{dep}' but {dep_path} does not exist")
    return errors


def check_2b_archetype_frontmatter_keys(archetype_files: list[str]) -> tuple[list[str], dict[str, dict]]:
    """Check 2b: Archetype files have all required frontmatter keys."""
    errors: list[str] = []
    archetype_data: dict[str, dict] = {}
    for af in archetype_files:
        data = parse_frontmatter(af)
        if data is None:
            errors.append(f"[2b] {af}: missing frontmatter")
            continue
        archetype_data[af] = data
        for key in ARCHETYPE_REQUIRED_KEYS:
            if key not in data:
                errors.append(f"[2b] {af}: missing required key '{key}'")
    return errors, archetype_data


def check_3_skill_frontmatter_keys(skill_files: list[str]) -> tuple[list[str], dict[str, dict]]:
    """Check 3: Skill files have all required frontmatter keys."""
    errors: list[str] = []
    skill_data: dict[str, dict] = {}
    for sf in skill_files:
        data = parse_frontmatter(sf)
        if data is None:
            errors.append(f"[3] {sf}: missing frontmatter")
            continue
        skill_data[sf] = data
        for key in SKILL_REQUIRED_KEYS:
            if key not in data:
                errors.append(f"[3] {sf}: missing required key '{key}'")
    return errors, skill_data


def check_4_references_exist(skill_data: dict[str, dict]) -> list[str]:
    """Check 4: Every references file path exists on disk."""
    errors: list[str] = []
    for sf, data in skill_data.items():
        for ref in data.get("references", []):
            if not os.path.exists(ref):
                errors.append(f"[4] {sf}: references '{ref}' but file does not exist")
    return errors


def check_5_verify_md_in_code_writing(skill_data: dict[str, dict]) -> list[str]:
    """Check 5: code-writing skills must reference verify.md."""
    errors: list[str] = []
    for sf, data in skill_data.items():
        if data.get("type") != "code-writing":
            continue
        refs = data.get("references", [])
        ref_basenames = [os.path.basename(r) for r in refs]
        if "verify.md" not in ref_basenames:
            errors.append(f"[5] {sf}: code-writing skill missing verify.md in references")
    return errors


def check_6_branch_md_in_code_writing(skill_data: dict[str, dict]) -> list[str]:
    """Check 6: code-writing skills must reference branch.md."""
    errors: list[str] = []
    for sf, data in skill_data.items():
        if data.get("type") != "code-writing":
            continue
        refs = data.get("references", [])
        ref_basenames = [os.path.basename(r) for r in refs]
        if "branch.md" not in ref_basenames:
            errors.append(f"[6] {sf}: code-writing skill missing branch.md in references")
    return errors


def check_7_claude_md_skill_list(skill_files: list[str], claude_content: str) -> list[str]:
    """Check 7: CLAUDE.md Rule 0 parenthetical skill list matches actual filenames."""
    errors: list[str] = []
    m = re.search(
        r"outside a defined skill \((/[a-z, /-]+)\)", claude_content
    )
    if m:
        claude_skills = sorted(
            s.strip().lstrip("/") for s in m.group(1).split(",")
        )
        actual_skills = sorted(
            os.path.basename(f).replace(".md", "") for f in skill_files
        )
        if claude_skills != actual_skills:
            errors.append(
                f"[7] CLAUDE.md Rule 0 skill list mismatch: "
                f"claude.md={claude_skills} vs actual={actual_skills}"
            )
    else:
        errors.append("[7] Could not find Rule 0 skill list pattern in CLAUDE.md")
    return errors


def check_8_ci_placeholders_in_ci_yml(stack_data: dict[str, dict], ci_content: str) -> list[str]:
    """Check 8: Union of ci_placeholders keys appears in ci.yml."""
    errors: list[str] = []
    all_placeholder_keys: set[str] = set()
    for _sf, data in stack_data.items():
        for key in data.get("ci_placeholders", {}):
            all_placeholder_keys.add(key)
    for key in sorted(all_placeholder_keys):
        if key not in ci_content:
            errors.append(f"[8] ci_placeholders key '{key}' not found in .github/workflows/ci.yml")
    return errors


def check_9_ci_placeholders_in_gitleaks(stack_data: dict[str, dict], gitleaks_content: str) -> list[str]:
    """Check 9: All ci_placeholders values covered by .gitleaks.toml allowlist."""
    errors: list[str] = []
    gitleaks_patterns = re.findall(r"'''(.+?)'''", gitleaks_content)

    all_placeholder_values: set[str] = set()
    for _sf, data in stack_data.items():
        for val in data.get("ci_placeholders", {}).values():
            str_val = str(val)
            if str_val.startswith("https://") or str_val.startswith("http://"):
                continue
            all_placeholder_values.add(str_val)

    for val in sorted(all_placeholder_values):
        matched = False
        for pattern in gitleaks_patterns:
            try:
                if re.search(pattern, val):
                    matched = True
                    break
            except re.error:
                pass
        if not matched:
            errors.append(
                f"[9] ci_placeholder value '{val}' not matched by any "
                f".gitleaks.toml allowlist pattern"
            )
    return errors


def check_10_branch_prefix_in_claude_md(skill_data: dict[str, dict], claude_content: str) -> list[str]:
    """Check 10: Skill branch_prefix values appear in CLAUDE.md Rule 1."""
    errors: list[str] = []
    r1_match = re.search(
        r"Branch naming:\s*(.+)", claude_content
    )
    if r1_match:
        allowed_prefixes = set(
            re.findall(r"`(\w+)/<", r1_match.group(1))
        )
        for sf, data in skill_data.items():
            prefix = data.get("branch_prefix", "")
            if prefix and prefix not in allowed_prefixes:
                errors.append(
                    f"[10] {sf}: branch_prefix '{prefix}' not in "
                    f"CLAUDE.md Rule 1 allowed prefixes {sorted(allowed_prefixes)}"
                )
    else:
        errors.append("[10] Could not find Rule 1 branch naming pattern in CLAUDE.md")
    return errors


def check_11_observe_md_in_references(skill_data: dict[str, dict]) -> list[str]:
    """Check 11: code-writing skills and deploy.md must reference observe.md."""
    errors: list[str] = []
    for sf, data in skill_data.items():
        is_code_writing = data.get("type") == "code-writing"
        is_deploy = os.path.basename(sf) == "deploy.md"
        if not is_code_writing and not is_deploy:
            continue
        refs = data.get("references", [])
        ref_basenames = [os.path.basename(r) for r in refs]
        if "observe.md" not in ref_basenames:
            errors.append(f"[11] {sf}: missing observe.md in references")
    return errors


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> int:
    """Run all frontmatter checks. Returns exit code (0=pass, 1=fail)."""
    global ERRORS
    ERRORS = []

    # Collect files
    stack_files = sorted(
        f
        for f in glob.glob(".claude/stacks/**/*.md", recursive=True)
        if "TEMPLATE" not in f
    )
    skill_files = sorted(glob.glob(".claude/commands/*.md"))
    archetype_files = sorted(glob.glob(".claude/archetypes/*.md"))

    # Check 1: Stack frontmatter
    errs, stack_data = check_1_stack_frontmatter_keys(stack_files)
    for e in errs:
        error(e)

    # Check 2: Assumes resolve
    for e in check_2_assumes_resolve(stack_data):
        error(e)

    # Check 2b: Archetype frontmatter
    errs, _archetype_data = check_2b_archetype_frontmatter_keys(archetype_files)
    for e in errs:
        error(e)

    # Check 3: Skill frontmatter
    errs, skill_data = check_3_skill_frontmatter_keys(skill_files)
    for e in errs:
        error(e)

    # Check 4: References exist
    for e in check_4_references_exist(skill_data):
        error(e)

    # Check 5: verify.md in code-writing
    for e in check_5_verify_md_in_code_writing(skill_data):
        error(e)

    # Check 6: branch.md in code-writing
    for e in check_6_branch_md_in_code_writing(skill_data):
        error(e)

    # Check 7: CLAUDE.md skill list
    if os.path.isfile("CLAUDE.md"):
        with open("CLAUDE.md") as f:
            claude_content = f.read()
        for e in check_7_claude_md_skill_list(skill_files, claude_content):
            error(e)

    # Check 10: branch_prefix in CLAUDE.md Rule 1
    if os.path.isfile("CLAUDE.md"):
        with open("CLAUDE.md") as f:
            claude_content = f.read()
        for e in check_10_branch_prefix_in_claude_md(skill_data, claude_content):
            error(e)

    # Check 8: ci_placeholders in ci.yml
    ci_yml_path = ".github/workflows/ci.yml"
    if os.path.isfile(ci_yml_path):
        with open(ci_yml_path) as f:
            ci_content = f.read()
        for e in check_8_ci_placeholders_in_ci_yml(stack_data, ci_content):
            error(e)

    # Check 9: ci_placeholders in gitleaks
    gitleaks_path = ".gitleaks.toml"
    if os.path.isfile(gitleaks_path):
        with open(gitleaks_path) as f:
            gitleaks_content = f.read()
        for e in check_9_ci_placeholders_in_gitleaks(stack_data, gitleaks_content):
            error(e)

    # Check 11: observe.md in references
    for e in check_11_observe_md_in_references(skill_data):
        error(e)

    # Summary
    print()
    if ERRORS:
        print(f"FAILED: {len(ERRORS)} error(s)")
        return 1
    else:
        print("PASSED: All frontmatter checks passed.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
