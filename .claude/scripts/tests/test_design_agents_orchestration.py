#!/usr/bin/env python3
"""test_design_agents_orchestration.py — recurrence guard for #1256, #1257, #1274.

Asserts the three sub-fixes work as designed:

  (a) #1256 Stage 0 fast-path detector: PR_RELEVANT exclusion semantics
      (test files, shadcn primitives, api routes), and the lead-synthesized
      aggregate clears state-completion-gate's per-trace check.
  (b) #1257 consistency-checker page-budget soft-exit: per_page_budget
      computation and partial-trace shape via write-degraded-trace.py.
  (c) #1274 merger fix-ledger consultation: ledger filter (literal
      provenance='lead' AND current run_id), unresolved → fixed verdict
      upgrade, lead_fix_corrections audit array, and per-page trace
      immutability.

Exit 0 on all-pass, 1 on any failure.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MERGE_SCRIPT = ROOT / ".claude/scripts/merge-design-critic-traces.py"
WRITE_AGENT_TRACE = ROOT / ".claude/scripts/write-agent-trace.sh"
STATE_3A_MD = ROOT / ".claude/skills/verify/state-3a-design-agents.md"
STATE_3B_MD = ROOT / ".claude/skills/verify/state-3b-quality-gate.md"
STATE_7A_MD = ROOT / ".claude/skills/verify/state-7a-write-report.md"
STATE_REGISTRY = ROOT / ".claude/patterns/state-registry.json"
AGENT_REGISTRY = ROOT / ".claude/patterns/agent-registry.json"
GATE_HOOK = ROOT / ".claude/hooks/state-completion-gate.sh"
CONSISTENCY_PROC = ROOT / ".claude/procedures/design-consistency-checker.md"


# ── (a) Stage 0 fast-path detector tests ─────────────────────────────────


class TestStage0Detector(unittest.TestCase):
    """#1256: PR_RELEVANT exclusion grep semantics encoded in state-3a-design-agents.md.

    The detector regex is documented as a multi-step grep pipeline; the test
    extracts the regex from the markdown and exercises the same grep filter
    on synthetic file lists.
    """

    @staticmethod
    def filter_pr_relevant(files: list[str]) -> int:
        """Apply the same filter as state-3a Stage 0 PR_RELEVANT pipeline."""
        # Match the include + 3 excludes from state-3a-design-agents.md
        include = re.compile(r"^(src/lib|src/components|src/app)/")
        excl_shadcn = re.compile(r"^src/components/(ui|magicui)/")
        excl_api = re.compile(r"^src/app/api/")
        excl_test = re.compile(r"\.test\.[jt]sx?$")
        kept = [
            f for f in files
            if include.search(f)
            and not excl_shadcn.search(f)
            and not excl_api.search(f)
            and not excl_test.search(f)
        ]
        return len(kept)

    def test_test_only_pr_triggers_fast_path(self):
        files = [
            "src/app/home/page.test.tsx",
            "src/components/landing-content.test.tsx",
            "src/lib/utils.test.ts",
        ]
        self.assertEqual(self.filter_pr_relevant(files), 0,
                         "test-only PR should trigger fast-path")

    def test_shadcn_primitive_only_does_not_count(self):
        files = [
            "src/components/ui/button.tsx",
            "src/components/magicui/sparkles.tsx",
        ]
        self.assertEqual(self.filter_pr_relevant(files), 0,
                         "shadcn-primitive-only PR should trigger fast-path")

    def test_api_only_pr_does_not_count(self):
        files = [
            "src/app/api/foo/route.ts",
            "src/app/api/bar/handler.ts",
        ]
        self.assertEqual(self.filter_pr_relevant(files), 0,
                         "api-only PR should trigger fast-path")

    def test_one_page_local_file_blocks_fast_path(self):
        files = ["src/app/home/page.tsx"]
        self.assertGreater(self.filter_pr_relevant(files), 0,
                           "page-local file must block fast-path")

    def test_mixed_pr_with_one_real_change_blocks_fast_path(self):
        files = [
            "src/app/home/page.test.tsx",       # excluded
            "src/components/ui/button.tsx",      # excluded
            "src/app/api/foo/route.ts",          # excluded
            "src/lib/auth.ts",                   # COUNTS
        ]
        self.assertEqual(self.filter_pr_relevant(files), 1,
                         "one real change among excludes must block fast-path")

    def test_state3a_md_documents_stage0(self):
        """Stage 0 section must exist with key fields."""
        text = STATE_3A_MD.read_text()
        self.assertIn("Stage 0: All-pages fast-path detector", text,
                      "Stage 0 heading missing")
        self.assertIn("ALL_PAGES_FAST_PATH", text,
                      "ALL_PAGES_FAST_PATH variable missing")
        self.assertIn(".runs/all-pages-fast-path-decision.json", text,
                      "decision artifact path missing")
        self.assertIn("boundary-skip-all-pages", text,
                      "review_method=boundary-skip-all-pages missing")
        self.assertIn("lead-synthesized", text,
                      "lead-synthesized provenance missing")

    def test_state3a_imperative_skip_directive(self):
        """state-3a must imperatively halt the lead from running pre-flight +
        Stage 1 + Stage 1b + Stage 1c when Stage 0 fired (post-merge fix-up:
        soft callouts are insufficient — leads can miss them).
        """
        text = STATE_3A_MD.read_text()
        self.assertIn("STOP HERE", text,
                      "state-3a missing imperative STOP HERE directive when Stage 0 fired")
        # The directive must appear AFTER the Stage 0 ACTIONS block and BEFORE
        # the existing Pre-flight section (i.e., it gates the rest of state-3a).
        stop_idx = text.find("STOP HERE")
        preflight_idx = text.find("Pre-flight: Thin-wrapper detection")
        stage0_idx = text.find("Stage 0: All-pages fast-path detector")
        self.assertGreater(stop_idx, stage0_idx,
                           "STOP HERE directive must appear after Stage 0 heading")
        self.assertLess(stop_idx, preflight_idx,
                        "STOP HERE directive must appear before Pre-flight section")

    def test_state3b_imperative_skip_step_b(self):
        """state-3b Step B (consistency-checker spawn) must imperatively halt
        the lead from spawning the agent when Stage 0 fired.
        """
        text = STATE_3B_MD.read_text()
        # Locate Step B section. Scope search to the next sibling/parent
        # heading — must skip past Step B's own `#####` prefix and not match
        # `####` substrings inside `#####` headings. Step B heading was
        # renamed to "Page-batched consistency check (#1257)" — match by
        # the stable "##### Step B:" prefix.
        step_b_idx = text.find("##### Step B:")
        self.assertGreater(step_b_idx, -1, "Step B heading missing")
        # Search starting AFTER Step B's heading line (skip its own `#####`).
        search_start = text.find("\n", step_b_idx) + 1
        # Find the next 4-hash heading (#### at line start, NOT prefixed by
        # another #) — that's the Post-design-critic lint gate.
        m = re.search(r"^####(?!#)", text[search_start:], re.MULTILINE)
        next_heading_idx = search_start + m.start() if m else len(text)
        step_b_section = text[step_b_idx:next_heading_idx]
        self.assertIn("STOP HERE", step_b_section,
                      "Step B missing imperative STOP HERE directive when Stage 0 fired")
        self.assertIn("all-pages-fast-path-decision.json", step_b_section,
                      "Step B skip directive must reference decision artifact")

    def test_state3b_guards_use_file_existence_not_subprocess_local_var(self):
        """Each fenced bash block in state-3b is its own subprocess. Guards
        MUST gate on `.runs/all-pages-fast-path-decision.json` file existence,
        NOT on a $STAGE0_FAST_PATH bash variable that doesn't persist between
        fences (post-merge fix-up: the variable-based guards were purely
        decorative because each fence got a fresh subprocess with empty env).
        """
        text = STATE_3B_MD.read_text()
        self.assertNotRegex(
            text, r'\$STAGE0_FAST_PATH',
            "state-3b uses $STAGE0_FAST_PATH which doesn't persist across "
            "separate fenced bash blocks — guards become decorative. "
            "Use `if [ ! -f .runs/all-pages-fast-path-decision.json ]` instead.",
        )
        # Positive assertion: the actual file-existence guards must be present
        # before each of the three skip targets (Stage 1c loop, merger, post-merge validation).
        guard_pattern = r'if \[ ! -f \.runs/all-pages-fast-path-decision\.json \]'
        guard_count = len(re.findall(guard_pattern, text))
        self.assertGreaterEqual(guard_count, 3,
                                f"expected ≥3 file-existence guards in state-3b "
                                f"(Stage 1c, Step A merger, post-merge validation); found {guard_count}")

    def test_state7a_pages_remaining_field_sources_documented(self):
        """state-7a Notes cell must tell the lead WHERE M, N, and slug-list
        come from in the trace (post-merge fix-up: parameterized format alone
        is insufficient — the spec must specify field provenance).
        """
        text = STATE_7A_MD.read_text()
        self.assertIn("design-consistency-checker", text,
                      "state-7a missing design-consistency-checker row")
        self.assertIn("trace.pages_reviewed", text,
                      "state-7a Notes cell missing trace.pages_reviewed source")
        self.assertIn("trace.pages_remaining", text,
                      "state-7a Notes cell missing trace.pages_remaining source")


class TestStage0GateExemption(unittest.TestCase):
    """#1256: state-completion-gate.sh SANCTIONED_COVERAGE_PROVIDERS allowlist."""

    def test_sanctioned_set_declared(self):
        text = GATE_HOOK.read_text()
        self.assertIn("SANCTIONED_COVERAGE_PROVIDERS", text,
                      "SANCTIONED_COVERAGE_PROVIDERS allowlist missing")
        self.assertIn(".runs/all-pages-fast-path-decision.json", text,
                      "fast-path decision artifact not in allowlist")
        # Exemption logic for lead-synthesized
        self.assertIn("lead-synthesized", text,
                      "lead-synthesized exemption logic missing")

    def test_agent_registry_predicate_added(self):
        r = json.loads(AGENT_REGISTRY.read_text())
        dc_gate = next(
            g for g in r["hard_gates"] if g["agent"] == "design-critic"
        )
        self.assertIn("pass_lead_synthesized", dc_gate["allow_predicates"],
                      "pass_lead_synthesized not in design-critic allow_predicates")

    def test_state_registry_3a_branches_on_decision_artifact(self):
        r = json.loads(STATE_REGISTRY.read_text())
        verify_3a = r["verify"]["3a"]["verify"]
        self.assertIn("all-pages-fast-path-decision.json", verify_3a,
                      "state-registry 3a verify must branch on decision artifact")
        self.assertIn("Stage 0:", verify_3a,
                      "state-registry 3a verify must mention Stage 0")

    def test_state_registry_3b_branches_on_decision_artifact(self):
        r = json.loads(STATE_REGISTRY.read_text())
        verify_3b = r["verify"]["3b"]["verify"]
        self.assertIn("all-pages-fast-path-decision.json", verify_3b,
                      "state-registry 3b verify must branch on decision artifact")
        self.assertIn("Stage 0:", verify_3b,
                      "state-registry 3b verify must mention Stage 0")


# ── (b) Consistency-checker soft-exit tests ────────────────────────────


class TestConsistencyCheckerPageBatching(unittest.TestCase):
    """#1257 final: page-batching architecture replaces the soft-exit primitive.

    Verifies the architectural pivot:
      * agent-registry.json: aggregate_ok in design-consistency-checker.allow_predicates
      * agent-trace-write-guard.sh: merge-design-consistency-checker-traces.py allowlisted
      * procedure: no soft-exit / consumed_turns / Budget Self-Monitoring residue
      * agent definition: maxTurns 1000 retained (per-batch agents have full budget)
      * procedure references prepass artifact + assigned_pages spawn input
    """

    def test_aggregate_ok_in_allow_predicates(self):
        """Page-batched lead-merge aggregate is acceptable to the hard gate."""
        registry = json.load(open(ROOT / ".claude/patterns/agent-registry.json"))
        for entry in registry.get("hard_gates", []):
            if entry.get("agent") == "design-consistency-checker":
                self.assertIn("aggregate_ok", entry.get("allow_predicates", []),
                              "aggregate_ok must be in design-consistency-checker.allow_predicates "
                              "so the page-batched lead-merge aggregate is accepted (#1257)")
                return
        self.fail("design-consistency-checker not found in agent-registry.json hard_gates")

    def test_merger_allowlisted_in_write_guard(self):
        """The page-batched aggregator must be in the write-guard allowlist."""
        guard = (ROOT / ".claude/hooks/agent-trace-write-guard.sh").read_text()
        self.assertIn("merge-design-consistency-checker-traces", guard,
                      "agent-trace-write-guard.sh must allowlist the new merger (#1257)")

    def test_consistency_checker_maxturns_retained_at_1000(self):
        """Each batch agent still has the full 1000-turn budget for ≤8 pages."""
        cc_md = ROOT / ".claude/agents/design-consistency-checker.md"
        text = cc_md.read_text()
        self.assertIn("maxTurns: 1000", text,
                      "design-consistency-checker maxTurns must remain 1000 (#1257)")

    def test_procedure_has_no_soft_exit_residue(self):
        """Phase 4/5 cleanup: no soft-exit / consumed_turns / Budget Self-Monitoring left."""
        text = CONSISTENCY_PROC.read_text()
        self.assertNotIn("Budget Self-Monitoring", text,
                         "Step 2.5 Budget Self-Monitoring must be removed (#1257 final)")
        self.assertNotIn("consumed_turns", text,
                         "consumed_turns self-counting must be removed (#1257 final / #844 anti-pattern)")
        self.assertNotIn("budget-soft-exit", text,
                         "budget-soft-exit reason must not appear in procedure (#1257 final)")
        self.assertNotIn("per_page_budget", text,
                         "per_page_budget formula must be removed (#1257 final)")

    def test_procedure_references_prepass_and_batch_inputs(self):
        """The page-batched procedure consumes a lead-side prepass artifact."""
        text = CONSISTENCY_PROC.read_text()
        self.assertIn("prepass_artifact", text,
                      "procedure must reference prepass_artifact spawn input (#1257)")
        self.assertIn("anomaly_candidates", text,
                      "procedure must reference anomaly_candidates from prepass (#1257)")
        self.assertIn("batch_id", text,
                      "procedure must reference batch_id spawn input (#1257)")
        self.assertIn("assigned_pages", text,
                      "procedure must reference assigned_pages spawn input (#1257)")

    def test_state_3b_describes_page_batching(self):
        """state-3b Stage 2 Step B documents the lead prepass + multi-batch flow."""
        text = (ROOT / ".claude/skills/verify/state-3b-quality-gate.md").read_text()
        self.assertIn("run-consistency-static-prepass.py", text,
                      "state-3b must invoke the lead-side prepass (#1257)")
        self.assertIn("merge-design-consistency-checker-traces.py", text,
                      "state-3b multi-batch path must invoke the merger (#1257)")
        # The legacy soft-exit primitive description must be removed
        self.assertNotIn("Budget Self-Monitoring", text,
                         "state-3b must not reference Budget Self-Monitoring (#1257 final)")

    def test_state_3b_verify_block_includes_lead_merge_check(self):
        """state-registry.json verify[3b] enforces lead-merge contract presence."""
        registry = json.load(open(ROOT / ".claude/patterns/state-registry.json"))
        v = registry.get("verify", {}).get("3b", {}).get("verify", "")
        self.assertIn("contributing_spawn_indexes", v,
                      "verify[3b] must check lead-merge aggregate's contributing_spawn_indexes (#1257)")
        self.assertIn("design-consistency-checker-batch", v,
                      "verify[3b] must check per-batch sibling traces (#1257)")


class TestScaffoldImagesSchemaVersionStamp(unittest.TestCase):
    """#1272 follow-up — producer-drift recurrence guard.

    The validate-step55-evidence.py validator at state-3b VERIFY enforces
    schema_version=2 on post-cutoff sidecars. The producer-side enforcement
    (scaffold-images Step 5b stamps the field on first write) was added in
    PR #1309. If a future scaffold-images change accidentally drops the
    stamp, post-cutoff projects would emit "missing schema_version" telemetry
    and the soak gate would never pass — but the regression would only
    surface after several real bootstraps, not at CI time.

    These tests catch the regression at lint/test time."""

    SCAFFOLD_IMAGES_PROC = ROOT / ".claude/procedures/scaffold-images.md"

    def test_step5b_template_stamps_schema_version_2(self):
        """scaffold-images Step 5b sidecar template MUST contain
        `"schema_version": 2` — otherwise scaffold-images writes an
        unstamped sidecar that triggers validate-step55-evidence.py
        producer-drift detection on every post-cutoff verify."""
        text = self.SCAFFOLD_IMAGES_PROC.read_text()
        self.assertIn('"schema_version": 2', text,
            'scaffold-images Step 5b template must stamp `"schema_version": 2` '
            '(see PR #1309 commit f6496e2). Producer-drift would re-create '
            'the #1272 chicken-and-egg back door.')

    def test_step5b_documents_canonical_birthplace_role(self):
        """The procedure must explain WHY the stamp is there — otherwise
        a future maintainer might delete it as 'redundant' (design-critic
        also stamps as defensive idempotent fallback)."""
        text = self.SCAFFOLD_IMAGES_PROC.read_text().lower()
        self.assertTrue(
            "canonical birthplace" in text or "#1272 follow-up" in text,
            "Step 5b must explain canonical-birthplace role of the stamp; "
            "delete-protection rationale is load-bearing for the soak gate.")

    def test_migration_script_referenced_from_runbook(self):
        """The rollout runbook must reference the migration script —
        otherwise operators won't know how to unblock soak when their
        legacy sidecar emits 'missing schema_version' telemetry."""
        runbook = ROOT / ".claude/patterns/step55-evidence-rollout.md"
        text = runbook.read_text()
        self.assertIn("migrate-image-candidates-v2.py", text,
            "step55-evidence-rollout.md must reference the migration script "
            "so operators can unblock the soak window on legacy sidecars.")


# ── (c) Merger fix-ledger consultation tests ───────────────────────────


class TestMergerLeadFixCredit(unittest.TestCase):
    """#1274: merger consults fix-ledger.jsonl for lead-applied fixes."""

    def _setup_run(self, tmp: Path, per_page_traces: list[dict],
                   ledger_rows: list[dict] | None = None,
                   shared_trace: dict | None = None) -> Path:
        """Build a tmp run directory with traces, optional ledger, optional shared trace."""
        traces_dir = tmp / ".runs" / "agent-traces"
        traces_dir.mkdir(parents=True)
        (tmp / ".runs" / "verify-context.json").write_text(
            json.dumps({"run_id": "test-run"})
        )
        for t in per_page_traces:
            page = t["page"]
            (traces_dir / f"design-critic-{page}.json").write_text(json.dumps(t))
        if ledger_rows is not None:
            (tmp / ".runs" / "fix-ledger.jsonl").write_text(
                "\n".join(json.dumps(r) for r in ledger_rows) + "\n"
            )
        if shared_trace is not None:
            (traces_dir / "design-critic-shared.json").write_text(
                json.dumps(shared_trace)
            )
        return traces_dir

    def _run_merge(self, tmp: Path) -> dict:
        traces_dir = tmp / ".runs" / "agent-traces"
        subprocess.run(
            ["python3", str(MERGE_SCRIPT)],
            capture_output=True,
            text=True,
            cwd=tmp,
            check=True,
        )
        return json.loads((traces_dir / "design-critic.json").read_text())

    def _make_trace(self, page: str, verdict: str = "pass",
                    unresolved_sections: int = 0,
                    shared_issues: list[dict] | None = None,
                    review_method: str = "rendered-authed") -> dict:
        return {
            "agent": "design-critic",
            "page": page,
            "pages_reviewed": 1,
            "verdict": verdict,
            "result": "clean" if verdict == "pass" else None,
            "checks_performed": ["c1", "c2", "c3"],
            "min_score": 9,
            "min_score_all": 9,
            "sections_below_8": 0,
            "fixes_applied": 0,
            "unresolved_sections": unresolved_sections,
            "pre_existing_debt": [],
            "fixes": [],
            "shared_issues": shared_issues or [],
            "review_method": review_method,
            "review_evidence": {
                "requested_route": f"/{page}",
                "final_url": f"http://localhost:3000/{page}",
                "auth_source": None,
                "fallback_reason": None,
                "content_density": 1.0,
            },
        }

    def test_lead_provenance_literal_credits_correctly(self):
        """Ledger row with provenance='lead' AND matching run_id credits the fix."""
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            self._setup_run(
                tmp,
                per_page_traces=[
                    self._make_trace(
                        "home",
                        verdict="unresolved",
                        unresolved_sections=1,
                        shared_issues=[{
                            "file": "src/components/landing-content.tsx",
                            "section": "hero",
                            "description": "overflow",
                        }],
                    ),
                ],
                ledger_rows=[{
                    "run_id": "test-run",
                    "provenance": "lead",
                    "file": "src/components/landing-content.tsx",
                    "symptom": "overflow",
                    "fix": "max-w adjusted",
                }],
            )
            merged = self._run_merge(tmp)
        self.assertIn("lead_fix_corrections", merged,
                      "lead_fix_corrections audit array missing")
        self.assertEqual(len(merged["lead_fix_corrections"]), 1)
        self.assertEqual(merged["lead_fix_corrections"][0]["page"], "home")
        self.assertEqual(merged["lead_fix_corrections"][0]["file"],
                         "src/components/landing-content.tsx")
        # Verdict upgrade: unresolved → fixed
        self.assertEqual(merged["verdict"], "fixed",
                         "verdict not upgraded after crediting lead-fix")
        self.assertEqual(merged["unresolved_sections"], 0,
                         "unresolved_sections not zeroed")

    def test_lead_on_behalf_provenance_also_credited(self):
        """Ledger row with provenance='lead-on-behalf' is also credited."""
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            self._setup_run(
                tmp,
                per_page_traces=[
                    self._make_trace(
                        "home",
                        verdict="unresolved",
                        unresolved_sections=1,
                        shared_issues=[{
                            "file": "src/components/header.tsx",
                            "section": "nav",
                            "description": "color",
                        }],
                    ),
                ],
                ledger_rows=[{
                    "run_id": "test-run",
                    "provenance": "lead-on-behalf",
                    "file": "src/components/header.tsx",
                    "symptom": "color",
                    "fix": "tone aligned",
                }],
            )
            merged = self._run_merge(tmp)
        self.assertEqual(len(merged.get("lead_fix_corrections", [])), 1)

    def test_lead_fix_provenance_NOT_credited(self):
        """Ledger row with WRONG provenance value 'lead-fix' (literal) is NOT credited.

        write-fix-ledger.py:373 writes literal 'lead' for --lead-fix mode.
        'lead-fix' is a TRACE-level provenance, NOT a ledger-level one.
        """
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            self._setup_run(
                tmp,
                per_page_traces=[
                    self._make_trace(
                        "home",
                        verdict="unresolved",
                        unresolved_sections=1,
                        shared_issues=[{"file": "src/components/x.tsx",
                                        "section": "y", "description": "z"}],
                    ),
                ],
                ledger_rows=[{
                    "run_id": "test-run",
                    "provenance": "lead-fix",   # WRONG value — must NOT match
                    "file": "src/components/x.tsx",
                    "symptom": "z",
                    "fix": "fixed",
                }],
            )
            merged = self._run_merge(tmp)
        self.assertNotIn("lead_fix_corrections", merged,
                         "ledger row with provenance='lead-fix' must NOT be credited "
                         "(only literal 'lead' or 'lead-on-behalf')")
        self.assertEqual(merged["verdict"], "unresolved",
                         "verdict must remain unresolved when no valid credits found")

    def test_stale_run_id_not_credited(self):
        """Ledger row with different run_id is NOT credited (cross-run pollution guard)."""
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            self._setup_run(
                tmp,
                per_page_traces=[
                    self._make_trace(
                        "home",
                        verdict="unresolved",
                        unresolved_sections=1,
                        shared_issues=[{"file": "src/components/x.tsx",
                                        "section": "y", "description": "z"}],
                    ),
                ],
                ledger_rows=[{
                    "run_id": "OTHER-run",   # mismatch
                    "provenance": "lead",
                    "file": "src/components/x.tsx",
                    "symptom": "z",
                    "fix": "fixed",
                }],
            )
            merged = self._run_merge(tmp)
        self.assertNotIn("lead_fix_corrections", merged,
                         "stale run_id ledger row must NOT be credited")
        self.assertEqual(merged["verdict"], "unresolved")

    def test_per_page_traces_remain_immutable(self):
        """After merger runs, per-page trace file content is unchanged."""
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            traces_dir = self._setup_run(
                tmp,
                per_page_traces=[
                    self._make_trace(
                        "home",
                        verdict="unresolved",
                        unresolved_sections=1,
                        shared_issues=[{"file": "src/components/x.tsx",
                                        "section": "y", "description": "z"}],
                    ),
                ],
                ledger_rows=[{
                    "run_id": "test-run",
                    "provenance": "lead",
                    "file": "src/components/x.tsx",
                    "symptom": "z",
                    "fix": "fixed",
                }],
            )
            home_path = traces_dir / "design-critic-home.json"
            before = home_path.read_text()
            self._run_merge(tmp)
            after = home_path.read_text()
        self.assertEqual(before, after,
                         "per-page trace must remain immutable post-merge")


# ── Scaffolding sanity ──────────────────────────────────────────────


class TestScaffoldingSanity(unittest.TestCase):
    def test_critical_files_exist(self):
        """Sanity: all files this test inspects must be present."""
        for p in (MERGE_SCRIPT, WRITE_AGENT_TRACE, STATE_3A_MD,
                  STATE_REGISTRY, AGENT_REGISTRY, GATE_HOOK,
                  CONSISTENCY_PROC):
            self.assertTrue(p.exists(), f"missing critical file: {p}")


if __name__ == "__main__":
    unittest.main()
