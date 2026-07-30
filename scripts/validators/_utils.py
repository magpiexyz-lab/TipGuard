"""Shared utilities for semantic validation checks."""
import glob
import os
import re
import sys

import yaml

ERRORS: list[str] = []

BASE_REQUIRED_EXPERIMENT_FIELDS = [
    "name",
    "owner",
    "type",
    "description",
    "thesis",
    "target_user",
    "distribution",
    "behaviors",
    "stack",
]

OPTIONAL_CATEGORIES = {"database", "auth", "payment", "email", "ai", "telephony", "voice", "notifications", "project-management"}



def read_skill_with_states(skill_path: str) -> str:
    """Read a skill file and append content from its state files if they exist.

    When skills are decomposed into state files (e.g., .claude/skills/bootstrap/state-*.md),
    the semantic checks need to search both the orchestrator and the state files.
    """
    content = ""
    if os.path.isfile(skill_path):
        with open(skill_path) as f:
            content = f.read()
    # Derive skill name from path: .claude/commands/<skill>.md -> <skill>
    skill_name = os.path.splitext(os.path.basename(skill_path))[0]
    state_dir = f".claude/skills/{skill_name}"
    if os.path.isdir(state_dir):
        # Sort numerically by state number (state-0, state-1, ..., state-10, state-11)
        # not alphabetically (which would put state-10 before state-2)
        state_files = glob.glob(f"{state_dir}/state-*.md")
        def state_sort_key(path: str) -> tuple:
            name = os.path.basename(path)
            # Extract the state ID between "state-" and the next "-"
            parts = name.replace("state-", "", 1).split("-", 1)
            state_id = parts[0]
            try:
                return (0, int(state_id), name)
            except ValueError:
                return (1, 0, name)  # Non-numeric (3a, 3b) sort after numeric
        for state_file in sorted(state_files, key=state_sort_key):
            with open(state_file) as f:
                content += "\n" + f.read()
    return content


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


def extract_code_blocks(content: str, lang_filter: set[str] | None = None) -> list[dict]:
    """Extract fenced code blocks from markdown content.

    Returns list of dicts with keys: lang, code, start_line.
    If lang_filter is provided, only blocks with matching language tags are returned.
    """
    blocks = []
    pattern = re.compile(r"^```(\w+)?\s*\n(.*?)^```", re.MULTILINE | re.DOTALL)
    for m in pattern.finditer(content):
        lang = m.group(1) or ""
        if lang_filter and lang not in lang_filter:
            continue
        start_line = content[: m.start()].count("\n") + 1
        blocks.append({"lang": lang, "code": m.group(2), "start_line": start_line})
    return blocks


def extract_prose(content: str) -> str:
    """Extract text outside of fenced code blocks."""
    return re.sub(r"```\w*\s*\n.*?```", "", content, flags=re.MULTILINE | re.DOTALL)


def parse_frontmatter_from_content(content: str) -> dict | None:
    """Extract YAML frontmatter from markdown content string."""
    m = re.match(r"^---\n(.*?\n)---", content, re.DOTALL)
    if not m:
        return None
    return yaml.safe_load(m.group(1))


def get_required_experiment_fields(experiment_type: str | None = None) -> list[str]:
    """Return required experiment.yaml fields based on archetype type."""
    effective = experiment_type if experiment_type else "web-app"
    archetype_path = f".claude/archetypes/{effective}.md"
    extra = ["pages"]  # fallback if archetype file missing
    if os.path.isfile(archetype_path):
        fm = parse_frontmatter(archetype_path)
        if fm and "required_experiment_fields" in fm:
            extra = fm["required_experiment_fields"]
    return BASE_REQUIRED_EXPERIMENT_FIELDS + extra


def parse_makefile_targets(makefile_content: str) -> dict[str, str]:
    """Parse Makefile targets and their recipe text."""
    target_pattern = re.compile(r"^([a-zA-Z0-9_-]+)\s*:(?!=)", re.MULTILINE)
    targets: dict[str, str] = {}
    matches = list(target_pattern.finditer(makefile_content))
    for i, m in enumerate(matches):
        name = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(makefile_content)
        recipe = makefile_content[start:end]
        targets[name] = recipe
    return targets

