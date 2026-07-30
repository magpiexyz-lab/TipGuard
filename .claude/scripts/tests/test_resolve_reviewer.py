#!/usr/bin/env python3
"""test_resolve_reviewer.py — verify resolve-reviewer first-class agent (AOC v1.1 PR4).

Closes #1055 (alias drift). Static-only checks: confirms agent file exists with
required frontmatter, the resolve skill manifest declares it, and the
agent-registry.json entries are consistent.

Note: this test does NOT spawn the agent (that is exercised end-to-end by
running /resolve). It validates that the static contracts (manifest +
registry + agent definition) are aligned so skill-agent-gate.sh, the
write-guards, and the state-completion check all see a consistent identity.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]


class TestResolveReviewerFirstClass(unittest.TestCase):
    def test_agent_file_exists_with_frontmatter(self):
        path = ROOT / ".claude/agents/resolve-reviewer.md"
        self.assertTrue(path.is_file(), f"missing {path}")
        text = path.read_text()
        # YAML frontmatter starts with --- and contains name + tools
        self.assertTrue(text.startswith("---\n"), "missing frontmatter")
        end = text.find("\n---\n", 4)
        self.assertGreater(end, 0, "frontmatter not closed with ---")
        front = yaml.safe_load(text[4:end])
        self.assertEqual(front.get("name"), "resolve-reviewer")
        self.assertIn("Bash", front.get("tools", []))
        self.assertIn("Read", front.get("tools", []))
        # Read-only: must not allow Edit/Write
        self.assertIn("Edit", front.get("disallowedTools", []))
        self.assertIn("Write", front.get("disallowedTools", []))

    def test_skill_manifest_declares_agent(self):
        path = ROOT / ".claude/skills/resolve/skill.yaml"
        manifest = yaml.safe_load(path.read_text())
        agents = manifest.get("agents", {})
        self.assertIn(
            "resolve-reviewer", agents,
            "resolve-reviewer must be declared in resolve/skill.yaml agents:",
        )

    def test_registry_verdict_agents_includes(self):
        reg = json.load((ROOT / ".claude/patterns/agent-registry.json").open())
        self.assertIn("resolve-reviewer", reg["verdict_agents"])

    def test_registry_verdict_schema_consistent_with_resolve_challenger(self):
        reg = json.load((ROOT / ".claude/patterns/agent-registry.json").open())
        sib = reg["verdict_agents_schema"]["resolve-challenger"]
        rev = reg["verdict_agents_schema"]["resolve-reviewer"]
        # Reviewer mirrors challenger's count_summary shape (sibling agents).
        self.assertEqual(rev["allowed_verdicts"], sib["allowed_verdicts"])
        self.assertEqual(rev["allowed_results"], sib["allowed_results"])
        self.assertEqual(rev["required_structured_fields"], sib["required_structured_fields"])

    def test_registry_non_fixer_agents_includes(self):
        reg = json.load((ROOT / ".claude/patterns/agent-registry.json").open())
        self.assertIn(
            "resolve-reviewer", reg["non_fixer_agents"],
            "resolve-reviewer is read-only — must be in non_fixer_agents",
        )

    def test_registry_hard_gates_entry_correct(self):
        reg = json.load((ROOT / ".claude/patterns/agent-registry.json").open())
        gates = {g.get("agent"): g for g in reg["hard_gates"]}
        self.assertIn("resolve-reviewer", gates)
        gate = gates["resolve-reviewer"]
        # Read-only reviewer: should NOT include pass_after_fixes (no fixes applied)
        # or aggregate_ok (single trace, no per-issue siblings).
        self.assertNotIn("pass_after_fixes", gate["allow_predicates"])
        self.assertNotIn("aggregate_ok", gate["allow_predicates"])
        # Should include the standard read-mostly predicates.
        self.assertIn("pass_clean", gate["allow_predicates"])
        self.assertIn("pass_self_pass_or_fail", gate["allow_predicates"])
        self.assertIn("validated_fallback", gate["allow_predicates"])
        self.assertIn("legacy_pass_no_recovery", gate["allow_predicates"])

    def test_state_10_uses_subagent_type_resolve_reviewer(self):
        path = ROOT / ".claude/skills/resolve/state-10-post-fix-review.md"
        text = path.read_text()
        # First-class spawn: subagent_type matches the agent name (no alias).
        self.assertIn("subagent_type: resolve-reviewer", text,
                      "state-10 should spawn subagent_type:resolve-reviewer (first-class, not alias)")

    def test_state_10_no_alias_filename_override(self):
        path = ROOT / ".claude/skills/resolve/state-10-post-fix-review.md"
        text = path.read_text()
        # The pre-PR4 alias instruction was: "Use resolve-reviewer as the agent name
        # (not resolve-challenger)." which embedded a filename override. After PR4
        # promotion, that prose must be gone — the agent definition handles it.
        self.assertNotIn(
            "Use `resolve-reviewer` as the agent name (not `resolve-challenger`)",
            text,
            "state-10 still contains the pre-PR4 alias prose — first-class promotion incomplete",
        )

    def test_registry_schema_version_bumped_to_5(self):
        reg = json.load((ROOT / ".claude/patterns/agent-registry.json").open())
        self.assertGreaterEqual(
            reg["_schema_version"], 5,
            "_schema_version should be 5 after PR4 (resolve-reviewer first-class)",
        )

    def test_state_registry_verify_checks_trace_existence(self):
        sr = json.load((ROOT / ".claude/patterns/state-registry.json").open())
        entry = sr["resolve"]["10"]
        # Registry entries can be string (legacy) or dict (with `verify` key
        # plus optional artifact/lifecycle/calls metadata). The verify command
        # is the canonical content either way.
        verify = entry if isinstance(entry, str) else entry.get("verify", "")
        # The post-PR4 VERIFY must check that the resolve-reviewer trace
        # exists and has a verdict (not a stub) — defends against alias-drift
        # regression.
        self.assertIn(
            "resolve-reviewer.json", verify,
            "state-10 VERIFY must check resolve-reviewer trace existence",
        )
        self.assertIn(
            "stub", verify,
            "state-10 VERIFY must check the trace is not a started-only stub",
        )


def main():
    result = unittest.main(exit=False, verbosity=2).result
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
