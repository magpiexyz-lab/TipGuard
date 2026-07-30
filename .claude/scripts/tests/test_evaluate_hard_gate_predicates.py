#!/usr/bin/env python3
"""test_evaluate_hard_gate_predicates.py — direct unit tests for the
extracted predicate evaluator.

Companion to test_hard_gate_predicates.py, which exercises the same logic
through the bash subprocess path (lib.sh -> shim -> lib-hard-gate.sh ->
evaluate-hard-gate-predicates.py). That bash test stays as the regression
net for the bash-Python boundary. This file imports the Python module
directly to test predicate semantics without subprocess overhead.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / ".claude/scripts/evaluate-hard-gate-predicates.py"

# Direct module import (filename has hyphens so use importlib)
_spec = importlib.util.spec_from_file_location("ehgp", SCRIPT)
ehgp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ehgp)


@pytest.fixture
def workspace(tmp_path):
    """Provides (tmp_path, traces_dir, registry_path)."""
    traces = tmp_path / "agent-traces"
    traces.mkdir()
    reg = tmp_path / "agent-registry.json"
    return tmp_path, traces, reg


def _write_trace(traces_dir, name, data):
    (traces_dir / f"{name}.json").write_text(json.dumps(data))


def _write_registry(reg_path, gates):
    reg_path.write_text(json.dumps({"hard_gates": gates}))


def _run(workspace, agent, allow_predicates, trace, *,
         additional_block_conditions=None, sibling_traces=None):
    """One-shot helper: write registry, write trace, write any siblings, evaluate."""
    tmp_path, traces, reg = workspace
    gate = {"agent": agent, "allow_predicates": allow_predicates}
    if additional_block_conditions is not None:
        gate["additional_block_conditions"] = additional_block_conditions
    _write_registry(reg, [gate])
    _write_trace(traces, agent, trace)
    if sibling_traces:
        for sib_name, sib_data in sibling_traces.items():
            _write_trace(traces, sib_name, sib_data)
    trace_path = traces / f"{agent}.json"
    return ehgp.evaluate(agent, str(trace_path), str(traces), str(reg))


# ============================================================
# Predicate: pass_clean
# ============================================================

def test_pass_clean_allows(workspace):
    out = _run(workspace, "design-critic", ["pass_clean"], {
        "verdict": "pass", "result": "clean", "provenance": "self",
    })
    assert out == "OK"


def test_pass_clean_rejects_when_provenance_not_self(workspace):
    out = _run(workspace, "design-critic", ["pass_clean"], {
        "verdict": "pass", "result": "clean", "provenance": "lead-merge",
    })
    assert out.startswith("BLOCK:no allow_predicate satisfied")


# ============================================================
# Predicate: pass_after_fixes
# ============================================================

def test_pass_after_fixes_allows_with_zero_unresolved(workspace):
    out = _run(workspace, "design-critic", ["pass_after_fixes"], {
        "verdict": "pass", "result": "fixed", "provenance": "self",
        "unresolved_critical": 0,
    })
    assert out == "OK"


def test_pass_after_fixes_blocks_when_unresolved_critical(workspace):
    out = _run(workspace, "design-critic", ["pass_after_fixes"], {
        "verdict": "pass", "result": "fixed", "provenance": "self",
        "unresolved_critical": 1,
    })
    assert out.startswith("BLOCK:")


# ============================================================
# Predicate: pass_self_pass_or_fail
# ============================================================

def test_pass_self_pass_or_fail_allows_pass(workspace):
    out = _run(workspace, "design-critic", ["pass_self_pass_or_fail"], {
        "verdict": "pass", "provenance": "self",
    })
    assert out == "OK"


def test_pass_self_pass_or_fail_allows_fail(workspace):
    out = _run(workspace, "design-critic", ["pass_self_pass_or_fail"], {
        "verdict": "fail", "provenance": "self",
    })
    assert out == "OK"


def test_pass_self_pass_or_fail_blocks_unresolved(workspace):
    out = _run(workspace, "design-critic", ["pass_self_pass_or_fail"], {
        "verdict": "unresolved", "provenance": "self",
    })
    assert out.startswith("BLOCK:")


# ============================================================
# Predicate: pass_self_strict
# ============================================================

def test_pass_self_strict_blocks_fail(workspace):
    out = _run(workspace, "design-critic", ["pass_self_strict"], {
        "verdict": "fail", "provenance": "self",
    })
    assert out.startswith("BLOCK:")


def test_pass_self_strict_allows_pass(workspace):
    out = _run(workspace, "design-critic", ["pass_self_strict"], {
        "verdict": "pass", "provenance": "self",
    })
    assert out == "OK"


# ============================================================
# Predicate: validated_fallback
# ============================================================

def test_validated_fallback_recovery_validated_allows(workspace):
    out = _run(workspace, "design-critic", ["validated_fallback"], {
        "verdict": "recovery", "provenance": "recovery",
        "recovery": True, "recovery_validated": True,
    })
    assert out == "OK"


def test_validated_fallback_blocks_when_not_validated(workspace):
    out = _run(workspace, "design-critic", ["validated_fallback"], {
        "verdict": "recovery", "provenance": "recovery",
        "recovery": True, "recovery_validated": False,
    })
    assert out.startswith("BLOCK:")


def test_validated_fallback_accepts_self_degraded(workspace):
    out = _run(workspace, "design-critic", ["validated_fallback"], {
        "verdict": "degraded", "provenance": "self-degraded",
        "recovery_validated": True,
    })
    assert out == "OK"


def test_validated_fallback_accepts_lead_on_behalf(workspace):
    out = _run(workspace, "design-critic", ["validated_fallback"], {
        "verdict": "pass", "provenance": "lead-on-behalf",
        "recovery_validated": True,
    })
    assert out == "OK"


# ============================================================
# Predicate: legacy_pass_no_recovery
# ============================================================

def test_legacy_pass_no_recovery_only_pre_aoc(workspace):
    out = _run(workspace, "design-critic", ["legacy_pass_no_recovery"], {
        "verdict": "pass", "provenance": "self",
    })
    assert out.startswith("BLOCK:")


def test_legacy_pass_no_recovery_allows_pre_aoc_pass(workspace):
    out = _run(workspace, "design-critic", ["legacy_pass_no_recovery"], {
        "verdict": "pass",
    })
    assert out == "OK"


def test_legacy_pass_no_recovery_blocks_with_recovery_flag(workspace):
    out = _run(workspace, "design-critic", ["legacy_pass_no_recovery"], {
        "verdict": "pass", "recovery": True,
    })
    assert out.startswith("BLOCK:")


# ============================================================
# Predicate: pass_lead_on_behalf
# ============================================================

def test_pass_lead_on_behalf_requires_recovery_validated(workspace):
    out = _run(workspace, "design-critic", ["pass_lead_on_behalf"], {
        "verdict": "pass", "provenance": "lead-on-behalf",
        "recovery_validated": True,
    })
    assert out == "OK"


def test_pass_lead_on_behalf_blocks_without_validation(workspace):
    out = _run(workspace, "design-critic", ["pass_lead_on_behalf"], {
        "verdict": "pass", "provenance": "lead-on-behalf",
        "recovery_validated": False,
    })
    assert out.startswith("BLOCK:")


# ============================================================
# Predicate: pass_lead_fix
# ============================================================

def test_pass_lead_fix_requires_attestation(workspace):
    out = _run(workspace, "design-critic", ["pass_lead_fix"], {
        "verdict": "pass", "provenance": "lead-fix",
        "lead_attestation": True,
    })
    assert out == "OK"


def test_pass_lead_fix_blocks_without_attestation(workspace):
    out = _run(workspace, "design-critic", ["pass_lead_fix"], {
        "verdict": "pass", "provenance": "lead-fix",
    })
    assert out.startswith("BLOCK:")


# ============================================================
# Predicate: pass_lead_synthesized
# ============================================================

def test_pass_lead_synthesized_requires_coverage_provider(workspace):
    out = _run(workspace, "design-critic", ["pass_lead_synthesized"], {
        "verdict": "pass", "provenance": "lead-synthesized",
        "coverage_provider": "spec-reviewer",
    })
    assert out == "OK"


def test_pass_lead_synthesized_blocks_without_coverage(workspace):
    out = _run(workspace, "design-critic", ["pass_lead_synthesized"], {
        "verdict": "pass", "provenance": "lead-synthesized",
    })
    assert out.startswith("BLOCK:")


# ============================================================
# Predicate: aggregate_ok
# ============================================================

def test_aggregate_ok_passes_when_all_siblings_pass(workspace):
    out = _run(workspace, "design-critic", ["aggregate_ok"],
               trace={
                   "verdict": "pass", "provenance": "lead-merge",
                   "contributing_spawn_indexes": [1, 2],
               },
               sibling_traces={
                   "design-critic-landing": {
                       "verdict": "pass", "provenance": "self",
                   },
                   "design-critic-pricing": {
                       "verdict": "pass", "provenance": "self",
                   },
               })
    assert out == "OK"


def test_aggregate_ok_blocks_when_one_sibling_fails(workspace):
    out = _run(workspace, "design-critic", ["aggregate_ok"],
               trace={
                   "verdict": "pass", "provenance": "lead-merge",
                   "contributing_spawn_indexes": [1, 2],
               },
               sibling_traces={
                   "design-critic-landing": {
                       "verdict": "pass", "provenance": "self",
                   },
                   "design-critic-pricing": {
                       "verdict": "unresolved", "provenance": "self",
                   },
               })
    assert out.startswith("BLOCK:")


def test_aggregate_ok_blocks_when_no_siblings(workspace):
    out = _run(workspace, "design-critic", ["aggregate_ok"], trace={
        "verdict": "pass", "provenance": "lead-merge",
        "contributing_spawn_indexes": [1, 2],
    })
    assert out.startswith("BLOCK:")


def test_aggregate_ok_blocks_when_csi_empty(workspace):
    out = _run(workspace, "design-critic", ["aggregate_ok"], trace={
        "verdict": "pass", "provenance": "lead-merge",
        "contributing_spawn_indexes": [],
    })
    assert out.startswith("BLOCK:")


# ============================================================
# additional_block_conditions
# ============================================================

def test_additional_block_eq(workspace):
    out = _run(workspace, "design-critic", ["pass_self_pass_or_fail"],
               trace={
                   "verdict": "pass", "provenance": "self",
                   "partial": True,
               },
               additional_block_conditions=[
                   {"field": "partial", "eq": True},
               ])
    assert "additional block triggered" in out
    assert "partial=True" in out


def test_additional_block_eq_not_hit(workspace):
    out = _run(workspace, "design-critic", ["pass_self_pass_or_fail"],
               trace={
                   "verdict": "pass", "provenance": "self",
                   "partial": False,
               },
               additional_block_conditions=[
                   {"field": "partial", "eq": True},
               ])
    assert out == "OK"


def test_additional_block_gt(workspace):
    out = _run(workspace, "design-critic", ["pass_self_pass_or_fail"],
               trace={
                   "verdict": "pass", "provenance": "self",
                   "violations": 3,
               },
               additional_block_conditions=[
                   {"field": "violations", "gt": 2},
               ])
    assert "additional block triggered" in out
    assert "violations=3" in out


def test_additional_block_all_compound(workspace):
    out = _run(workspace, "design-critic", ["pass_self_pass_or_fail"],
               trace={
                   "verdict": "pass", "provenance": "self",
                   "partial": True, "violations": 5,
               },
               additional_block_conditions=[
                   {"all": [
                       {"field": "partial", "eq": True},
                       {"field": "violations", "gt": 2},
                   ]},
               ])
    assert "additional block triggered" in out
    assert "partial=True AND violations=5" in out


def test_additional_block_all_partial_match_does_not_fire(workspace):
    out = _run(workspace, "design-critic", ["pass_self_pass_or_fail"],
               trace={
                   "verdict": "pass", "provenance": "self",
                   "partial": True, "violations": 1,
               },
               additional_block_conditions=[
                   {"all": [
                       {"field": "partial", "eq": True},
                       {"field": "violations", "gt": 2},
                   ]},
               ])
    assert out == "OK"


# ============================================================
# Error paths
# ============================================================

def test_unknown_predicate_emits_error(workspace):
    out = _run(workspace, "design-critic", ["does_not_exist"], {
        "verdict": "pass", "provenance": "self",
    })
    assert out == "UNKNOWN_PREDICATE:does_not_exist"


def test_no_gate_registered_returns_empty(workspace):
    tmp_path, traces, reg = workspace
    _write_registry(reg, [])
    _write_trace(traces, "design-critic", {"verdict": "pass"})
    out = ehgp.evaluate(
        "design-critic",
        str(traces / "design-critic.json"),
        str(traces),
        str(reg),
    )
    assert out == ""


def test_malformed_trace_returns_read_error(workspace):
    tmp_path, traces, reg = workspace
    _write_registry(reg, [{"agent": "x", "allow_predicates": ["pass_clean"]}])
    (traces / "x.json").write_text("not json {")
    out = ehgp.evaluate(
        "x",
        str(traces / "x.json"),
        str(traces),
        str(reg),
    )
    assert out.startswith("READ_ERROR:")


def test_malformed_registry_returns_read_error(workspace):
    tmp_path, traces, reg = workspace
    reg.write_text("{ bad json")
    _write_trace(traces, "design-critic", {"verdict": "pass"})
    out = ehgp.evaluate(
        "design-critic",
        str(traces / "design-critic.json"),
        str(traces),
        str(reg),
    )
    assert out.startswith("READ_ERROR:registry:")


# ============================================================
# CLI entry point — verifies env-vars-primary + argparse-override
# ============================================================

def test_cli_env_vars_drive_evaluation(workspace):
    tmp_path_, traces, reg = workspace
    _write_registry(reg, [{
        "agent": "design-critic", "allow_predicates": ["pass_self_strict"],
    }])
    _write_trace(traces, "design-critic", {
        "verdict": "pass", "provenance": "self",
    })
    proc = subprocess.run(
        ["python3", str(SCRIPT)],
        env={
            **os.environ,
            "AGENT_ENV": "design-critic",
            "TRACE_ENV": str(traces / "design-critic.json"),
            "TRACES_DIR_ENV": str(traces),
            "REG_ENV": str(reg),
        },
        capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == "OK"


def test_cli_argparse_overrides_env(workspace):
    tmp_path_, traces, reg = workspace
    _write_registry(reg, [{
        "agent": "design-critic", "allow_predicates": ["pass_self_strict"],
    }])
    _write_trace(traces, "design-critic", {
        "verdict": "pass", "provenance": "self",
    })
    proc = subprocess.run(
        ["python3", str(SCRIPT),
         "--agent", "design-critic",
         "--trace", str(traces / "design-critic.json"),
         "--traces-dir", str(traces),
         "--registry", str(reg)],
        env={k: v for k, v in os.environ.items()
             if k not in ("AGENT_ENV", "TRACE_ENV", "TRACES_DIR_ENV", "REG_ENV")},
        capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == "OK"


def test_cli_missing_inputs_exits_2(workspace):
    proc = subprocess.run(
        ["python3", str(SCRIPT)],
        env={k: v for k, v in os.environ.items()
             if k not in ("AGENT_ENV", "TRACE_ENV", "TRACES_DIR_ENV", "REG_ENV")},
        capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 2
    assert "missing required input" in proc.stderr
