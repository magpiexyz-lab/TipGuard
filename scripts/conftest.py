"""Shared pytest fixtures for validator tests."""

import os
import textwrap

import pytest
import yaml


@pytest.fixture
def tmp_template_dir(tmp_path):
    """Create a minimal .claude/ template structure for validator testing."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "stacks").mkdir()
    (claude_dir / "stacks" / "framework").mkdir()
    (claude_dir / "stacks" / "analytics").mkdir()
    (claude_dir / "stacks" / "ui").mkdir()
    (claude_dir / "stacks" / "hosting").mkdir()
    (claude_dir / "commands").mkdir()
    (claude_dir / "archetypes").mkdir()
    (claude_dir / "patterns").mkdir()

    (tmp_path / "tests" / "fixtures").mkdir(parents=True)
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / "experiment").mkdir()
    (tmp_path / "scripts").mkdir()

    return tmp_path


def fake_stack_file(
    path,
    *,
    assumes=None,
    packages=None,
    files=None,
    env=None,
    ci_placeholders=None,
    clean=None,
    gitignore=None,
    extra_content="",
):
    """Generate a stack .md file with valid frontmatter."""
    fm = {
        "assumes": assumes or [],
        "packages": packages or {"runtime": [], "dev": []},
        "files": files or [],
        "env": env or {"server": [], "client": []},
        "ci_placeholders": ci_placeholders or {},
        "clean": clean or {"files": [], "dirs": []},
        "gitignore": gitignore or [],
    }
    content = "---\n" + yaml.dump(fm, default_flow_style=False) + "---\n\n"
    content += extra_content
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    return path


def fake_skill_file(
    path,
    *,
    skill_type="code-writing",
    reads=None,
    stack_categories=None,
    requires_approval=False,
    references=None,
    branch_prefix="feat",
    modifies_specs=False,
    extra_content="",
):
    """Generate a skill .md file with valid frontmatter."""
    fm = {
        "type": skill_type,
        "reads": reads or [],
        "stack_categories": stack_categories or [],
        "requires_approval": requires_approval,
        "references": references or [],
        "branch_prefix": branch_prefix,
        "modifies_specs": modifies_specs,
    }
    content = "---\n" + yaml.dump(fm, default_flow_style=False) + "---\n\n"
    content += extra_content
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    return path


def fake_fixture(
    path,
    *,
    name="test-app",
    fixture_type="web-app",
    pages=None,
    stack=None,
    events=None,
    assertions=None,
    extra_experiment=None,
):
    """Generate a test fixture .yaml file."""
    experiment = {
        "name": name,
        "type": fixture_type,
        "title": "Test App",
        "owner": "test@example.com",
        "problem": "Test problem",
        "solution": "Test solution",
        "target_user": "Developers",
        "distribution": "organic",
        "description": "Test experiment description",
        "thesis": "If we build X, then Y will happen, measured by signups reaching 100",
        "behaviors": [{"id": "core", "description": "Core behavior"}],
        "stack": stack or {"services": [{"name": "web", "runtime": "nextjs", "hosting": "vercel", "ui": "shadcn"}], "analytics": "posthog"},
    }
    if pages is not None:
        experiment["pages"] = pages
    elif fixture_type == "web-app":
        experiment["pages"] = [{"name": "landing", "description": "Landing page"}]

    if extra_experiment:
        experiment.update(extra_experiment)

    fixture = {
        "experiment": experiment,
        "events": events or {},
        "assertions": assertions or {
            "min_pages": 1,
            "payment_events_required": False,
            "skippable_events": ["signup_start", "signup_complete"],
        },
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(fixture, f, default_flow_style=False)
    return path
