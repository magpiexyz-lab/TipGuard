#!/usr/bin/env python3
"""Behavioral tests for merge_mvp_aliases() and the merge-aliases CLI subcommand.

Validates:
- Empty aliases → passthrough (idempotent)
- Single alias merge: visitor sum, first/last_seen min/max,
  sample_utm_campaign from highest-visitor source
- Multiple aliases under one canonical
- Stale alias (config refers to MVP not in discovery): silently ignored
- Synthesized canonical (canonical absent from discovery but aliases present):
  alias data attributed to canonical name
- Conflicting alias (same alias under two canonicals): ValueError
- Idempotence: re-applying the merge is a no-op

Run via: python3 .claude/scripts/tests/test_merge_mvp_aliases.py
Or via:  bash .claude/scripts/tests/run-all.sh
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

REAL_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
LIB_DIR = os.path.join(REAL_REPO, ".claude", "scripts", "lib")
sys.path.insert(0, LIB_DIR)

from iterate_cross_classify import merge_mvp_aliases  # noqa: E402

SCRIPT = os.path.join(LIB_DIR, "iterate_cross_classify.py")


def _row(name, utm, visitors, first, last):
    """Helper to construct a discovery row in the canonical shape."""
    return [name, utm, visitors, first, last]


class TestMergeMvpAliases(unittest.TestCase):
    def test_empty_aliases_passthrough(self):
        rows = [
            _row("a", "u1", 10, "2026-01-01", "2026-02-01"),
            _row("b", "u2", 20, "2026-01-15", "2026-03-01"),
        ]
        merged, audit = merge_mvp_aliases(rows, {})
        self.assertEqual(merged, rows)
        self.assertEqual(audit, [])

    def test_no_aliases_field_passthrough(self):
        rows = [_row("a", "u1", 10, "2026-01-01", "2026-02-01")]
        merged, audit = merge_mvp_aliases(rows, None or {})
        self.assertEqual(merged, rows)
        self.assertEqual(audit, [])

    def test_single_alias_merged(self):
        rows = [
            _row("splitshare", "u-canonical", 77, "2026-04-08", "2026-05-12"),
            _row("split-share-neon", "u-alias", 42, "2026-04-10", "2026-05-11"),
            _row("other", "u-other", 5, "2026-05-01", "2026-05-02"),
        ]
        aliases = {"splitshare": ["split-share-neon"]}
        merged, audit = merge_mvp_aliases(rows, aliases)
        self.assertEqual(len(merged), 2)
        # Canonical's row
        canonical = [r for r in merged if r[0] == "splitshare"][0]
        self.assertEqual(canonical[2], 77 + 42)  # visitor sum
        # sample_utm = picked from highest-visitor source (canonical itself, 77 > 42)
        self.assertEqual(canonical[1], "u-canonical")
        self.assertEqual(canonical[3], "2026-04-08")  # min first_seen
        self.assertEqual(canonical[4], "2026-05-12")  # max last_seen
        # Audit
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["canonical"], "splitshare")
        self.assertEqual(audit[0]["absorbed_aliases"], ["split-share-neon"])
        self.assertEqual(audit[0]["absorbed_visitors"], 42)
        self.assertEqual(audit[0]["total_visitors"], 119)
        # Other MVP untouched
        other = [r for r in merged if r[0] == "other"][0]
        self.assertEqual(other[2], 5)

    def test_sample_utm_from_strongest_alias(self):
        # Alias has MORE traffic than canonical — sample_utm should follow.
        rows = [
            _row("canon", "u-canonical", 10, "2026-01-01", "2026-02-01"),
            _row("alias", "u-strong-alias", 100, "2026-01-15", "2026-03-01"),
        ]
        merged, _ = merge_mvp_aliases(rows, {"canon": ["alias"]})
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0][1], "u-strong-alias")
        self.assertEqual(merged[0][2], 110)

    def test_multiple_aliases_under_one_canonical(self):
        rows = [
            _row("c", "uc", 10, "2026-01-01", "2026-02-01"),
            _row("a1", "u1", 20, "2026-01-15", "2026-02-15"),
            _row("a2", "u2", 30, "2026-02-01", "2026-03-01"),
        ]
        merged, audit = merge_mvp_aliases(rows, {"c": ["a1", "a2"]})
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0][0], "c")
        self.assertEqual(merged[0][2], 60)
        # Highest-visitor utm = a2 (30 visitors)
        self.assertEqual(merged[0][1], "u2")
        self.assertEqual(merged[0][3], "2026-01-01")
        self.assertEqual(merged[0][4], "2026-03-01")
        self.assertEqual(audit[0]["absorbed_aliases"], ["a1", "a2"])

    def test_stale_alias_silently_ignored(self):
        # Alias referenced in config but absent from discovery: noop.
        rows = [_row("canon", "uc", 10, "2026-01-01", "2026-02-01")]
        aliases = {"canon": ["never-existed"]}
        merged, audit = merge_mvp_aliases(rows, aliases)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0][0], "canon")
        self.assertEqual(merged[0][2], 10)
        # Audit still records the canonical (it was present in discovery)
        self.assertEqual(audit[0]["absorbed_aliases"], [])

    def test_synthesized_canonical(self):
        # Canonical absent from discovery; one alias present.
        # Result: canonical record synthesized using alias data, but named canonical.
        rows = [_row("alias", "u-alias", 25, "2026-02-01", "2026-03-01")]
        aliases = {"canon": ["alias"]}
        merged, audit = merge_mvp_aliases(rows, aliases)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0][0], "canon")  # name remapped
        self.assertEqual(merged[0][2], 25)
        self.assertEqual(merged[0][1], "u-alias")

    def test_conflicting_alias_raises(self):
        rows = [
            _row("canon1", "u1", 10, "2026-01-01", "2026-02-01"),
            _row("canon2", "u2", 20, "2026-01-01", "2026-02-01"),
            _row("dup", "u-dup", 5, "2026-01-15", "2026-02-15"),
        ]
        aliases = {
            "canon1": ["dup"],
            "canon2": ["dup"],
        }
        with self.assertRaises(ValueError):
            merge_mvp_aliases(rows, aliases)

    def test_idempotent(self):
        # Re-applying the merge to already-merged input must be a no-op.
        rows = [
            _row("canon", "uc", 10, "2026-01-01", "2026-02-01"),
            _row("alias", "ua", 20, "2026-01-15", "2026-02-15"),
        ]
        aliases = {"canon": ["alias"]}
        merged1, _ = merge_mvp_aliases(rows, aliases)
        merged2, _ = merge_mvp_aliases(merged1, aliases)
        self.assertEqual(merged1, merged2)

    def test_order_preserved(self):
        # Discovery rows are sorted by visitors DESC at PostHog; the merge
        # output should keep that order (canonical at canonical's original
        # position, aliases stripped from where they were).
        rows = [
            _row("alpha", "u-a", 100, "2026-01-01", "2026-02-01"),
            _row("beta", "u-b", 50, "2026-01-01", "2026-02-01"),
            _row("beta-alias", "u-ba", 30, "2026-01-15", "2026-02-15"),
            _row("gamma", "u-g", 10, "2026-01-01", "2026-02-01"),
        ]
        merged, _ = merge_mvp_aliases(rows, {"beta": ["beta-alias"]})
        names = [r[0] for r in merged]
        self.assertEqual(names, ["alpha", "beta", "gamma"])


class TestMergeAliasesCLI(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _write(self, path, content):
        with open(path, "w") as fh:
            fh.write(content)

    def test_cli_passthrough_no_config(self):
        discovery_path = os.path.join(self.tmpdir, "discovery.json")
        config_path = os.path.join(self.tmpdir, "config.yaml")
        output_path = os.path.join(self.tmpdir, "out.json")
        self._write(
            discovery_path,
            json.dumps({"results": [_row("a", "u", 10, "2026-01-01", "2026-02-01")]}),
        )
        self._write(config_path, "")  # empty config

        result = subprocess.run(
            ["python3", SCRIPT, "merge-aliases",
             "--discovery", discovery_path,
             "--config", config_path,
             "--output", output_path],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(output_path) as fh:
            out = json.load(fh)
        self.assertEqual(len(out["results"]), 1)
        self.assertEqual(out["alias_merge_audit"], [])

    def test_cli_overwrites_in_place(self):
        # --discovery and --output may be the same path (in-place merge).
        path = os.path.join(self.tmpdir, "shared.json")
        config_path = os.path.join(self.tmpdir, "config.yaml")
        self._write(
            path,
            json.dumps({"results": [
                _row("canon", "uc", 10, "2026-01-01", "2026-02-01"),
                _row("alias", "ua", 20, "2026-01-15", "2026-02-15"),
            ]}),
        )
        self._write(config_path, "mvp_aliases:\n  canon: [alias]\n")

        result = subprocess.run(
            ["python3", SCRIPT, "merge-aliases",
             "--discovery", path,
             "--config", config_path,
             "--output", path],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(path) as fh:
            out = json.load(fh)
        self.assertEqual(len(out["results"]), 1)
        self.assertEqual(out["results"][0][0], "canon")
        self.assertEqual(out["results"][0][2], 30)
        self.assertEqual(len(out["alias_merge_audit"]), 1)

    def test_cli_conflict_exits_nonzero(self):
        discovery_path = os.path.join(self.tmpdir, "discovery.json")
        config_path = os.path.join(self.tmpdir, "config.yaml")
        output_path = os.path.join(self.tmpdir, "out.json")
        self._write(
            discovery_path,
            json.dumps({"results": [
                _row("c1", "u1", 10, "2026-01-01", "2026-02-01"),
                _row("c2", "u2", 20, "2026-01-01", "2026-02-01"),
                _row("dup", "ud", 5, "2026-01-15", "2026-02-15"),
            ]}),
        )
        self._write(
            config_path,
            "mvp_aliases:\n  c1: [dup]\n  c2: [dup]\n",
        )

        result = subprocess.run(
            ["python3", SCRIPT, "merge-aliases",
             "--discovery", discovery_path,
             "--config", config_path,
             "--output", output_path],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("dup", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
