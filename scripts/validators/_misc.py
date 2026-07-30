"""Miscellaneous validation checks (distribution docs, procedures, agents, settings, traces)."""
import glob
import json
import os
import re

from ._utils import (
    extract_code_blocks,
    parse_frontmatter_from_content,
    parse_frontmatter,
    BASE_REQUIRED_EXPERIMENT_FIELDS,
    OPTIONAL_CATEGORIES,
)

__all__ = [
    "check_41_distribution_docs_references",
    "check_53_supabase_delete_flag",
    "check_54_procedure_production_branch",
    "check_55_production_references_tdd",
    "check_56_production_references_implementer",
    "check_58_agent_tool_consistency",
    "check_60_settings_hook_paths",
    "check_61_footer_directive_sync",
    "check_62_trace_framework_completeness",
    "check_66_audit_review_scope_coverage",
]

def check_41_distribution_docs_references() -> list[str]:
    """Check 41: docs/*.md files referenced in distribute.md or distribution stack files exist."""
    errors: list[str] = []
    docs_ref_sources = [".claude/commands/distribute.md"] + glob.glob(
        ".claude/stacks/distribution/*.md"
    )
    for src_path in docs_ref_sources:
        if os.path.isfile(src_path):
            with open(src_path) as f:
                content = f.read()

            for ref_match in re.finditer(r"`(docs/[^`]+\.md)`", content):
                referenced_path = ref_match.group(1)
                if not os.path.isfile(referenced_path):
                    errors.append(
                        f"[41] {src_path}: references `{referenced_path}` "
                        f"but that file does not exist on disk"
                    )
    return errors


def check_53_supabase_delete_flag(file_contents: dict[str, str]) -> list[str]:
    """Check 53: supabase projects delete uses --project-ref flag."""
    errors: list[str] = []
    for sf, content in file_contents.items():
        code_blocks = extract_code_blocks(content, {"bash", "sh"})
        for block in code_blocks:
            if "supabase projects delete" in block["code"]:
                if "--project-ref" not in block["code"]:
                    errors.append(
                        f"[53] {sf}: `supabase projects delete` without --project-ref flag "
                        f"near line {block['start_line']}"
                    )
    return errors


def check_54_procedure_production_branch(procedure_files: dict[str, str]) -> list[str]:
    """Check 54: Procedure files for Feature/Upgrade/Fix have quality gate branches."""
    errors: list[str] = []
    target_procedures = {"change-feature.md", "change-upgrade.md", "change-fix.md"}
    for path, content in procedure_files.items():
        basename = os.path.basename(path)
        if basename not in target_procedures:
            continue
        # TDD/implementer references must be present unconditionally (no MVP mode)
        if not re.search(r"tdd\.md|patterns/tdd|ON-TOUCH", content):
            errors.append(
                f"[54] {path}: procedure file missing TDD or ON-TOUCH reference"
            )
    return errors


def check_55_production_references_tdd(procedure_files: dict[str, str]) -> list[str]:
    """Check 55: Procedure files reference TDD (unconditional — no MVP mode)."""
    errors: list[str] = []
    target_procedures = {"change-feature.md", "change-upgrade.md", "change-fix.md"}
    for path, content in procedure_files.items():
        basename = os.path.basename(path)
        if basename not in target_procedures:
            continue
        # TDD reference should exist somewhere in the file
        if not re.search(r"tdd\.md|patterns/tdd|TDD|regression test", content):
            errors.append(
                f"[55] {path}: procedure file does not reference tdd.md"
            )
    return errors


def check_56_production_references_implementer(procedure_files: dict[str, str]) -> list[str]:
    """Check 56: Feature and upgrade procedures reference implementer agent.

    Only checks feature and upgrade procedures — fix uses a simpler single-task
    TDD path (regression test + minimal fix) without implementer agents.
    """
    errors: list[str] = []
    target_procedures = {"change-feature.md", "change-upgrade.md"}
    for path, content in procedure_files.items():
        basename = os.path.basename(path)
        if basename not in target_procedures:
            continue
        # Implementer reference should exist somewhere in the file
        if not re.search(r"implementer\.md|agents/implementer|implementer agent", content):
            errors.append(
                f"[56] {path}: procedure file does not reference implementer agent"
            )
    return errors


def check_58_agent_tool_consistency(agent_files: dict[str, str]) -> list[str]:
    """Check 58: Agent tool declarations are consistent with their roles."""
    errors: list[str] = []
    for path, content in agent_files.items():
        basename = os.path.basename(path)
        fm = parse_frontmatter_from_content(content)
        if not fm:
            continue
        tools = fm.get("tools", []) or []
        disallowed = fm.get("disallowedTools", []) or []

        if basename == "implementer.md":
            for required in ["Edit", "Write", "Bash"]:
                if required not in tools:
                    errors.append(
                        f"[58] {path}: implementer agent missing required tool '{required}'"
                    )

        if basename == "spec-reviewer.md":
            for forbidden in ["Edit", "Write"]:
                if forbidden in tools:
                    errors.append(
                        f"[58] {path}: spec-reviewer agent has write tool '{forbidden}' "
                        f"but should be read-only"
                    )
                if forbidden not in disallowed:
                    errors.append(
                        f"[58] {path}: spec-reviewer agent should disallow '{forbidden}'"
                    )
    return errors


def check_60_settings_hook_paths() -> list[str]:
    """Check 60: Every hook command path in settings.json must resolve to an existing file."""
    errors: list[str] = []
    settings_path = ".claude/settings.json"
    if not os.path.isfile(settings_path):
        return errors
    try:
        with open(settings_path) as f:
            settings = json.loads(f.read())
    except (json.JSONDecodeError, OSError):
        return errors
    hooks = settings.get("hooks", {})
    for _matcher, hook_list in hooks.items():
        if not isinstance(hook_list, list):
            continue
        for entry in hook_list:
            if not isinstance(entry, dict):
                continue
            hook_entries = entry.get("hooks", [entry])
            if not isinstance(hook_entries, list):
                hook_entries = [hook_entries]
            for hook in hook_entries:
                if not isinstance(hook, dict):
                    continue
                cmd = hook.get("command", "")
                # Normalize: strip quotes and replace $CLAUDE_PROJECT_DIR with .
                normalized = cmd.replace('"', "").replace("'", "")
                normalized = normalized.replace("$CLAUDE_PROJECT_DIR/", "")
                # Extract just the script path (first token)
                script_path = normalized.split()[0] if normalized.split() else ""
                if script_path and script_path.endswith(".sh"):
                    if not os.path.isfile(script_path):
                        errors.append(
                            f"[60] {settings_path}: hook path '{script_path}' "
                            f"does not resolve to an existing file"
                        )
    return errors


def check_61_footer_directive_sync() -> list[str]:
    """Check 61: Directive marker in agent-prompt-footer.md must match skill-agent-gate.sh grep."""
    errors: list[str] = []
    footer_path = ".claude/agent-prompt-footer.md"
    hook_paths = [".claude/hooks/skill-agent-gate.sh", ".claude/hooks/lib.sh", ".claude/hooks/lib-artifacts.sh"]
    if not os.path.isfile(footer_path) or not any(os.path.isfile(p) for p in hook_paths):
        return errors
    with open(footer_path) as f:
        first_line = f.readline().strip()
    # Extract directive marker from HTML comment: <!-- DIRECTIVES:... -->
    marker = first_line
    if marker.startswith("<!--"):
        marker = marker[4:]
    if marker.endswith("-->"):
        marker = marker[:-3]
    marker = marker.strip()
    if not marker.startswith("DIRECTIVES:"):
        return errors
    found = False
    for hook_path in hook_paths:
        if os.path.isfile(hook_path):
            with open(hook_path) as f:
                if marker in f.read():
                    found = True
                    break
    if not found:
        errors.append(
            f"[61] hook files: directive grep pattern does not match "
            f"agent-prompt-footer.md marker '{marker}'"
        )
    return errors


def check_62_trace_framework_completeness() -> list[str]:
    """Check 62: Every stateful skill has Q-score and epilogue categorization."""
    errors: list[str] = []

    # Find all stateful skills (dirs with state-*.md files).
    # Per-skill state files live at .claude/skills/<skill>/state-*.md;
    # shared terminal states (e.g., state-99) live at .claude/patterns/state-*.md
    # and are tracked separately by verify-linter.sh.
    stateful_skills: list[str] = []
    skills_dir = ".claude/skills"
    if os.path.isdir(skills_dir):
        for d in sorted(os.listdir(skills_dir)):
            skill_dir = os.path.join(skills_dir, d)
            if os.path.isdir(skill_dir) and glob.glob(os.path.join(skill_dir, "state-*.md")):
                stateful_skills.append(d)

    # Skills excluded from Q-score check:
    # - verify: uses own STATE 7 --raw mechanism
    # - ads-ready: deterministic pre-flight verification gate (pass/fail) — no
    #   variable-quality deliverable to score; correctness is covered by the
    #   ads_ready_static / ads_ready_smoke test suites, not a self-assessed q-score
    excluded_qscore = {"verify", "ads-ready"}
    # Skills excluded from epilogue categorization:
    # - verify: own mechanism
    # - optimize-prompt: stateless (no state files, won't appear)
    excluded_epilogue = {"verify"}

    # Check 1: Q-score presence.
    # Q-score is centrally wired via lifecycle-finalize.sh (Step 3) which
    # invokes `.claude/scripts/write-q-score.py` whenever a skill leaves a
    # `.runs/q-dimensions.json` artifact. So per-skill coverage requires
    # that at least one of the skill's state files writes q-dimensions.json
    # (or, for legacy paths, calls write-q-score directly).
    qscore_pattern = re.compile(r"q-dimensions\.json|write-q-score|write_q_score")
    for skill in stateful_skills:
        if skill in excluded_qscore:
            continue
        skill_dir = os.path.join(skills_dir, skill)
        state_files = glob.glob(os.path.join(skill_dir, "state-*.md"))
        has_qscore = False
        for sf in state_files:
            with open(sf) as f:
                if qscore_pattern.search(f.read()):
                    has_qscore = True
                    break
        if not has_qscore:
            errors.append(
                f"[62] Skill '{skill}' has {len(state_files)} state files but "
                f"no q-dimensions.json write or write-q-score call in any state"
            )

    # Check 2: Epilogue categorization
    epilogue_path = ".claude/patterns/skill-epilogue.md"
    if os.path.isfile(epilogue_path):
        with open(epilogue_path) as f:
            epilogue_content = f.read()
        for skill in stateful_skills:
            if skill in excluded_epilogue:
                continue
            # Check if skill appears in epilogue (Strategy A, B, or verify-embedded)
            if f"/{skill}" not in epilogue_content and skill not in epilogue_content:
                errors.append(
                    f"[62] Skill '{skill}' not categorized in skill-epilogue.md"
                )

    return errors


def check_66_audit_review_scope_coverage() -> list[str]:
    """Check 66: audit + review skills jointly cover every template-source directory.

    Three assertions:
    1. Resolution — every Glob/Read pattern parsed from audit state-1 and
       review state-2a resolves to ≥1 file on disk (catches phantom paths
       added by accident).
    2. Directory coverage — each template-source directory is referenced
       by ≥1 Glob in BOTH skills (catches new template dirs added without
       expanding either skill's scope).
    3. File coverage — each template-source individual file is referenced
       by ≥1 Glob/Read in either skill.

    Adding a new template-source directory requires adding a Glob line to
    both audit/state-1 AND review/state-2a, then adding it to
    TEMPLATE_SCAN_DIRS below.
    """
    errors: list[str] = []

    AUDIT_FILE = ".claude/skills/audit/state-1-parallel-analysis.md"
    REVIEW_FILE = ".claude/skills/review/state-2a-review-scan.md"

    # Phantom paths intentionally referenced; their underlying directory
    # absence is tracked as a separate template observation. Skip resolution
    # check for these.
    PHANTOM_ALLOWLIST = {"tests/fixtures/*.yaml"}

    # Template-source directories that BOTH audit + review must scan.
    # Order does not matter. A directory listed here but absent on disk
    # (e.g., a retired location) is silently skipped.
    TEMPLATE_SCAN_DIRS = [
        ".claude/commands",
        ".claude/skills",
        ".claude/patterns",
        ".claude/procedures",
        ".claude/agents",
        ".claude/archetypes",
        ".claude/templates",
        ".claude/stacks",
        ".claude/hooks",
        ".claude/scripts",
        ".claude/agent-memory",
        "scripts",
    ]

    # Individual template-source files that must be referenced by Glob or
    # Read in at least one of the two skills.
    TEMPLATE_SCAN_FILES = [
        ".claude/agent-prompt-footer.md",
        ".claude/settings.json",
        "Makefile",
    ]

    def extract_patterns(path: str) -> list[tuple[str, int]]:
        if not os.path.isfile(path):
            return []
        with open(path) as f:
            lines = f.readlines()
        out: list[tuple[str, int]] = []
        for i, line in enumerate(lines, start=1):
            for m in re.finditer(r"\b(?:Glob|Read)\s+`([^`]+)`", line):
                out.append((m.group(1), i))
        return out

    audit_patterns = extract_patterns(AUDIT_FILE)
    review_patterns = extract_patterns(REVIEW_FILE)

    if not audit_patterns:
        errors.append(
            f"[66] {AUDIT_FILE}: no Glob/Read patterns extracted "
            f"(file structure may have changed)"
        )
    if not review_patterns:
        errors.append(
            f"[66] {REVIEW_FILE}: no Glob/Read patterns extracted "
            f"(file structure may have changed)"
        )

    # Sub-check 1: every pattern resolves to ≥1 file on disk.
    for label, path, patterns in (
        ("audit", AUDIT_FILE, audit_patterns),
        ("review", REVIEW_FILE, review_patterns),
    ):
        for pattern, lineno in patterns:
            if pattern in PHANTOM_ALLOWLIST:
                continue
            if any(c in pattern for c in "*?["):
                matches = glob.glob(pattern, recursive=True)
            else:
                matches = [pattern] if os.path.exists(pattern) else []
            if not matches:
                errors.append(
                    f"[66] {path}:{lineno}: {label} pattern `{pattern}` "
                    f"resolves to zero files on disk"
                )

    # Sub-check 2: each TEMPLATE_SCAN_DIR is covered by both skills.
    def covers_dir(patterns: list[tuple[str, int]], directory: str) -> bool:
        prefix = directory.rstrip("/") + "/"
        return any(p.startswith(prefix) or p == directory for p, _ in patterns)

    for directory in TEMPLATE_SCAN_DIRS:
        if not os.path.isdir(directory):
            continue
        if not covers_dir(audit_patterns, directory):
            errors.append(
                f"[66] {AUDIT_FILE}: missing Glob for template-source "
                f"directory '{directory}/' (every audit subagent needs "
                f"this in its shared-context-instruction box)"
            )
        if not covers_dir(review_patterns, directory):
            errors.append(
                f"[66] {REVIEW_FILE}: missing Glob for template-source "
                f"directory '{directory}/' (at least one Dimension's "
                f"Files-to-read list needs this)"
            )

    # Sub-check 3: each TEMPLATE_SCAN_FILE is referenced by either skill.
    union_patterns = {p for p, _ in audit_patterns} | {p for p, _ in review_patterns}
    for f in TEMPLATE_SCAN_FILES:
        if not os.path.exists(f):
            continue
        if f not in union_patterns:
            errors.append(
                f"[66] template-source file '{f}' is not referenced by "
                f"any Glob/Read in audit/state-1 or review/state-2a"
            )

    return errors


# ---------------------------------------------------------------------------
# Check registry and runner
# ---------------------------------------------------------------------------
