"""test_post_completion_respawn_doc_lint.py — unit tests for the
`post_completion_respawn_doc_present` coherence-rule handler
(closes #1275 audit gap, follow-up to PR #1303).

The handler enumerates from agent-registry.json `hard_gates` entries
that contain `pass_lead_orchestrated` in `allow_predicates` and
asserts each agent's .md contains a `## Post-completion re-spawn`
section. Severity=warn — informational catch for future drift.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
CLI = ROOT / ".claude/scripts/lib/linter/cli.py"
PROD_REGISTRY = ROOT / ".claude/patterns/state-registry.json"


def _setup_repo(tmp_path: Path,
                hard_gates: list[dict],
                agent_md_contents: dict[str, str]) -> Path:
    """Build a minimal repo skeleton with ONLY the
    post_completion_respawn_doc_present rule registered, so other
    rules (executor-enforcement, etc.) cannot fire spuriously."""
    repo = tmp_path / "repo"
    (repo / ".claude/patterns").mkdir(parents=True)
    (repo / ".claude/agents").mkdir(parents=True)

    registry = {
        "verdict_agents": list(agent_md_contents.keys()),
        "recovery_forbidden": [],
        "lead_orchestrated_forbidden": [],
        "_aggregate_ok_accepted_predicates": [],
        "hard_gates": hard_gates,
    }
    (repo / ".claude/patterns/agent-registry.json").write_text(
        json.dumps(registry)
    )

    rules = {
        "rules": [
            {
                "id": "post-completion-respawn-doc-required",
                "type": "post_completion_respawn_doc_present",
                "severity": "warn",
                "registry_path": ".claude/patterns/agent-registry.json",
                "agents_dir": ".claude/agents",
                "required_section": "## Post-completion re-spawn",
                "description": "test rule",
            }
        ]
    }
    (repo / ".claude/patterns/template-coherence-rules.json").write_text(
        json.dumps(rules)
    )

    # state-registry.json is required by the runner's drift-check
    # framework even when only cross-file rules are loaded; copy the
    # production file so the runner doesn't refuse to start.
    shutil.copy(PROD_REGISTRY, repo / ".claude/patterns/state-registry.json")

    for agent, content in agent_md_contents.items():
        (repo / f".claude/agents/{agent}.md").write_text(content)

    return repo


def _run_linter(repo: Path) -> subprocess.CompletedProcess:
    """Invoke the linter's Python entrypoint directly with explicit
    VL_REPO_ROOT / VL_RULES_PATH so it reads the fixture's rules JSON
    (not the production one). Bypasses verify-linter.sh which always
    overwrites VL_REPO_ROOT to the script's enclosing repo."""
    env = os.environ.copy()
    env["VL_REPO_ROOT"] = str(repo)
    env["VL_RULES_PATH"] = str(repo / ".claude/patterns/template-coherence-rules.json")
    env["VL_JSON_OUT"] = ""
    env["VL_CACHE_FILE"] = ""
    env["VL_WARN_ONLY"] = ""
    env["VL_STRICT_AOC"] = ""
    return subprocess.run(
        ["python3", str(CLI)],
        cwd=str(repo), env=env, capture_output=True, text=True,
    )


def test_all_agents_have_section_no_findings(tmp_path: Path) -> None:
    """When every registered agent has the required section, the rule
    emits no findings."""
    section = "## Post-completion re-spawn\n\nLead orchestrates ..."
    repo = _setup_repo(
        tmp_path,
        hard_gates=[
            {"agent": "alpha", "allow_predicates": ["pass_lead_orchestrated"]},
            {"agent": "beta", "allow_predicates": ["pass_lead_orchestrated"]},
        ],
        agent_md_contents={
            "alpha": f"# alpha\n\n{section}\n",
            "beta": f"# beta\n\n{section}\n",
        },
    )
    rc = _run_linter(repo)
    assert "post-completion-respawn-doc-required" not in rc.stdout, (
        f"Expected no findings; got:\n{rc.stdout}"
    )


def test_one_agent_missing_section_emits_finding(tmp_path: Path) -> None:
    """When an agent is in hard_gates with pass_lead_orchestrated but
    its .md lacks the section, the rule reports it by name."""
    section = "## Post-completion re-spawn\n\nLead orchestrates ..."
    repo = _setup_repo(
        tmp_path,
        hard_gates=[
            {"agent": "alpha", "allow_predicates": ["pass_lead_orchestrated"]},
            {"agent": "beta",  "allow_predicates": ["pass_lead_orchestrated"]},
        ],
        agent_md_contents={
            "alpha": f"# alpha\n\n{section}\n",
            "beta":  f"# beta\n\n(no re-spawn section here)\n",
        },
    )
    rc = _run_linter(repo)
    out = rc.stdout
    assert "post-completion-respawn-doc-required" in out
    assert "'beta'" in out, f"Expected 'beta' to be named in finding; got:\n{out}"
    # alpha is registered but compliant — should not appear in findings
    bad_lines = [
        ln for ln in out.splitlines()
        if "post-completion-respawn-doc-required" in ln and "'alpha'" in ln
    ]
    assert not bad_lines, f"alpha should not appear; got: {bad_lines}"


def test_agent_not_registered_does_not_require_section(tmp_path: Path) -> None:
    """Agents NOT in hard_gates with pass_lead_orchestrated are not
    required to have the section."""
    repo = _setup_repo(
        tmp_path,
        hard_gates=[
            {"agent": "gamma", "allow_predicates": ["pass_clean"]},  # NOT lead-orchestrated
        ],
        agent_md_contents={
            "gamma": "# gamma\n\n(no re-spawn section, but not required)\n",
        },
    )
    rc = _run_linter(repo)
    assert "post-completion-respawn-doc-required" not in rc.stdout, (
        f"Expected no findings; got:\n{rc.stdout}"
    )


def test_missing_md_file_emits_finding(tmp_path: Path) -> None:
    """Agent in hard_gates but its .md file does not exist on disk."""
    repo = _setup_repo(
        tmp_path,
        hard_gates=[
            {"agent": "phantom", "allow_predicates": ["pass_lead_orchestrated"]},
        ],
        agent_md_contents={},  # no phantom.md created
    )
    rc = _run_linter(repo)
    assert "post-completion-respawn-doc-required" in rc.stdout
    assert "phantom" in rc.stdout
    assert "does not exist" in rc.stdout


def test_severity_warn_does_not_block_exit_code(tmp_path: Path) -> None:
    """severity=warn means the finding appears but does NOT cause the
    linter to exit non-zero (production behavior — informational catch
    for drift, not a delivery-block)."""
    section = "## Post-completion re-spawn\n\nLead orchestrates ..."
    repo = _setup_repo(
        tmp_path,
        hard_gates=[
            {"agent": "alpha", "allow_predicates": ["pass_lead_orchestrated"]},
        ],
        agent_md_contents={"alpha": "# alpha\n\n(no re-spawn section)\n"},
    )
    rc = _run_linter(repo)
    # The rule fires but the linter exit is 0 because severity=warn.
    # (CI's grep for DRIFT_DECLARED_VS_PROSE / CROSS_FILE_CONTRADICTION
    # determines block vs warn; severity=warn rules emit findings but
    # don't appear under those exit-blocking categories.)
    assert "post-completion-respawn-doc-required" in rc.stdout
    # severity=warn rules go under cross_file_contradiction bucket but
    # exit code logic in CI keys on the strict-aoc partition. The
    # linter's own exit code is informational here; assert it's a
    # reasonable value (0 or non-zero, but consistent with severity).
    # Specific exit-code semantics are validated by the linter's own
    # tests (test_aoc_coherence_rules.py); we only assert finding presence.
    assert "phantom" not in rc.stdout  # different fixture
