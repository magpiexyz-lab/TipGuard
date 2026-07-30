#!/usr/bin/env python3
"""#1335 follow-up — structural validation for sanctioned-respawn-flows.json.

The manifest declares which state files / lead orchestration paths are
sanctioned to spawn each agent. If a sanctioned_callers entry points at a
file that doesn't exist OR doesn't mention the agent name, the manifest is
itself an instance of the cluster antipattern this PR fixed: "declarative
guarantees without enforcement".

This test validates that every sanctioned_callers entry either:
  (a) is the special string "lead-orchestrator" (lead invokes directly,
      not via a state-file directive), OR
  (b) points at a real file that mentions the agent name in its content.

If this test fails, fix the manifest — don't relax the test.

Run via:
  python3 -m pytest .claude/scripts/tests/test_sanctioned_respawn_flows.py -v
"""
import json
import os
import unittest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
MANIFEST_PATH = os.path.join(
    REPO_ROOT, ".claude", "patterns", "sanctioned-respawn-flows.json"
)


class TestSanctionedRespawnFlows(unittest.TestCase):
    def setUp(self):
        with open(MANIFEST_PATH) as f:
            self.data = json.load(f)

    def test_manifest_is_valid_json(self):
        self.assertIn("flows", self.data)
        self.assertIsInstance(self.data["flows"], list)
        self.assertGreater(len(self.data["flows"]), 0)

    def test_every_entry_has_required_fields(self):
        required = {"agent", "sanctioned_callers", "rationale"}
        for entry in self.data["flows"]:
            missing = required - set(entry.keys())
            self.assertFalse(
                missing,
                f"entry for agent={entry.get('agent')!r} missing fields: {missing}",
            )
            self.assertIsInstance(entry["sanctioned_callers"], list)
            self.assertGreater(len(entry["sanctioned_callers"]), 0)

    def test_every_caller_path_exists_or_is_lead_orchestrator(self):
        """Each non-lead-orchestrator caller MUST point at an existing file."""
        for entry in self.data["flows"]:
            agent = entry["agent"]
            for caller in entry["sanctioned_callers"]:
                if caller == "lead-orchestrator":
                    continue
                full = os.path.join(REPO_ROOT, caller)
                self.assertTrue(
                    os.path.exists(full),
                    f"agent={agent!r} sanctioned_caller {caller!r} does not exist; "
                    "either the path is wrong or the file was renamed/deleted",
                )

    def test_every_caller_file_mentions_agent_name(self):
        """Each caller file MUST mention the agent name (substring match)."""
        for entry in self.data["flows"]:
            agent = entry["agent"]
            for caller in entry["sanctioned_callers"]:
                if caller == "lead-orchestrator":
                    continue
                full = os.path.join(REPO_ROOT, caller)
                if not os.path.exists(full):
                    continue  # caught by previous test
                with open(full) as f:
                    content = f.read()
                self.assertIn(
                    agent,
                    content,
                    f"agent={agent!r} sanctioned_caller {caller!r} does not "
                    "mention the agent name; the manifest entry is wrong or "
                    "the caller's content drifted (refactored to invoke a "
                    "different agent)",
                )

    def test_precondition_artifact_path_format(self):
        """When precondition_artifact is set, it must be a .runs/ path."""
        for entry in self.data["flows"]:
            pre = entry.get("precondition_artifact")
            if pre is None:
                continue
            self.assertTrue(
                pre.startswith(".runs/"),
                f"agent={entry['agent']!r} precondition_artifact must be a "
                f".runs/ path, got {pre!r}",
            )

    def test_precondition_field_value_pair_consistency(self):
        """precondition_field and precondition_value must come together."""
        for entry in self.data["flows"]:
            has_field = "precondition_field" in entry
            has_value = "precondition_value" in entry
            self.assertEqual(
                has_field,
                has_value,
                f"agent={entry['agent']!r} has precondition_field={has_field} "
                f"but precondition_value={has_value}; both must be present or "
                "both absent",
            )


if __name__ == "__main__":
    unittest.main()
