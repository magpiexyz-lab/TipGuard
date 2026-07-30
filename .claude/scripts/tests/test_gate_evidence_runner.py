#!/usr/bin/env python3
"""test_gate_evidence_runner.py — GECR runner tests.

Covers:
  1. Schema validation: malformed rules → SystemExit(2)
  2. Empty rules.json → no failures
  3. #1473 positive-block fixture: synthetic-href with dynamic-only page
  4. #1473 negative-control: template-literal nav passes
  5. #1473 static-page-control: bare-slug preserved for static pages
  6. #1473 mixed-page-control: both forms required
  7. #1470 positive-block fixture: empty-stub observation + non-empty friction
  8. #1470 negative-control: filed candidates pass
  9. #1470 suppression-control: suppressed candidates pass
 10. MODE=warn returns 0 even with failures
 11. derive_dynamic_only_pages classification correctness
 12. Slug-suffix handling (portfolio-detail → portfolio/[slug])

Run: python3 .claude/scripts/tests/test_gate_evidence_runner.py
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile

# Make .claude/scripts/lib importable
_HERE = os.path.dirname(os.path.abspath(__file__))
_LIB = os.path.normpath(os.path.join(_HERE, "..", "lib"))
sys.path.insert(0, _LIB)

from derive_pages import derive_dynamic_only_pages  # type: ignore
from gate_evidence_runner import (  # type: ignore
    load_rules,
    run_rule,
    apply_matcher,
    check_expected_observation,
    resolve_evidence,
)


_PASS = 0
_FAIL = 0
_NAMES: list[tuple[str, bool]] = []


def _t(name: str, cond: bool, hint: str = "") -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        _NAMES.append((name, True))
        print(f"  PASS  {name}")
    else:
        _FAIL += 1
        _NAMES.append((name, False))
        print(f"  FAIL  {name}")
        if hint:
            print(f"        {hint}")


def _mktree(root: str, layout: dict) -> None:
    """Build a fixture directory tree from a {path: content_or_None} mapping."""
    for rel, content in layout.items():
        full = os.path.join(root, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as fh:
            fh.write(content if content is not None else "")


# ----------------------------------------------------------------------------
# 1. derive_dynamic_only_pages classification
# ----------------------------------------------------------------------------

def test_classification() -> None:
    print("\n[test_classification]")
    with tempfile.TemporaryDirectory() as root:
        _mktree(root, {
            "src/app/dashboard/page.tsx": "// static",
            "src/app/project/[id]/page.tsx": "// dynamic only",
            "src/app/quote/[token]/page.tsx": "// dynamic only with hyphenated slug",
            "src/app/portfolio/page.tsx": "// static",
            "src/app/portfolio/[slug]/page.tsx": "// dynamic child of mixed",
            "src/app/admin/[[...slug]]/page.tsx": "// optional catch-all",
        })
        result = derive_dynamic_only_pages({
            "golden_path": [{"page": "dashboard"}],
            "behaviors": [{"pages": ["project", "quote-token", "portfolio-detail", "admin"]}],
        }, repo_root=root)

        _t("dashboard → static", result.get("dashboard") == "static",
           f"got {result.get('dashboard')!r}")
        _t("project → dynamic-only", result.get("project") == "dynamic-only",
           f"got {result.get('project')!r}")
        _t("quote-token (hyphenated) → dynamic-only via prefix fallback",
           result.get("quote-token") == "dynamic-only",
           f"got {result.get('quote-token')!r}")
        _t("portfolio-detail (hyphenated) → mixed",
           result.get("portfolio-detail") == "mixed",
           f"got {result.get('portfolio-detail')!r}")
        _t("admin (only optional catch-all) → static",
           result.get("admin") == "static",
           f"got {result.get('admin')!r}")


def test_classification_absent() -> None:
    print("\n[test_classification_absent]")
    with tempfile.TemporaryDirectory() as root:
        os.makedirs(os.path.join(root, "src", "app"))
        result = derive_dynamic_only_pages({
            "behaviors": [{"pages": ["nonexistent"]}],
        }, repo_root=root)
        _t("page declared but no folder → absent",
           result.get("nonexistent") == "absent",
           f"got {result!r}")


def test_classification_no_src_app() -> None:
    print("\n[test_classification_no_src_app]")
    with tempfile.TemporaryDirectory() as root:
        # No src/app at all — service/cli archetype
        result = derive_dynamic_only_pages({
            "behaviors": [{"pages": ["anything"]}],
        }, repo_root=root)
        _t("no src/app → empty dict", result == {},
           f"got {result!r}")


# ----------------------------------------------------------------------------
# 2. Schema validation
# ----------------------------------------------------------------------------

def test_load_rules_empty() -> None:
    """Test that an explicitly-empty rules JSON loads to []. The project's
    actual rules.json may have seed rules; this test isolates the contract
    by writing a synthetic empty rules file to a tempdir."""
    print("\n[test_load_rules_empty]")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        fh.write('{"rules": []}')
        empty_path = fh.name
    try:
        rules = load_rules(empty_path)
        _t("empty rules.json loads to []", rules == [],
           f"got {rules!r}")
    finally:
        os.unlink(empty_path)


def test_load_rules_project_seed() -> None:
    """The project's actual rules.json should load with the 2 seed rules
    (bg2-wire-nav-reachability + agent-workaround-pairing)."""
    print("\n[test_load_rules_project_seed]")
    rules = load_rules()
    rule_ids = {r.get("id") for r in rules}
    _t("seed rule bg2-wire-nav-reachability present",
       "bg2-wire-nav-reachability" in rule_ids,
       f"got rule_ids={rule_ids}")
    _t("seed rule agent-workaround-pairing present",
       "agent-workaround-pairing" in rule_ids,
       f"got rule_ids={rule_ids}")


def test_load_rules_malformed() -> None:
    print("\n[test_load_rules_malformed]")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        fh.write('{"rules": [{"id": "x"}]}')  # missing many required keys
        bad_path = fh.name
    try:
        try:
            load_rules(bad_path)
            _t("malformed rule raises SystemExit", False, "did not raise")
        except SystemExit as exc:
            _t("malformed rule → SystemExit(2)", exc.code == 2,
               f"got code={exc.code}")
    finally:
        os.unlink(bad_path)


# ----------------------------------------------------------------------------
# 3. #1473 fixtures — synthetic-href detection
# ----------------------------------------------------------------------------

def _bg2_wire_rule() -> dict:
    """The seed rule for #1473 (matches Step 6 PR-C seed definition)."""
    return {
        "id": "bg2-wire-nav-reachability",
        "type": "navigation_reachability",
        "gate_id": "bg2-wire-check-1",
        "severity": "block",
        "evidence_sources": [
            {
                "path_glob": "src/app/**/*.tsx",
                "reader": "grep_tsx",
                "always_included_paths": ["src/components/nav-bar.tsx"],
            },
        ],
        "matcher": {
            "kind": "template_literal_navigation",
            "params": {"page_classification_via": "derive_dynamic_only_pages"},
        },
        "expected_observation": {
            "artifact_path": "src/components/nav-bar.tsx",
            "predicate": "exists_with_citation",
        },
        "failure_citation_format": "page '{page}' is {classification} — {requirement}.",
        "mode_env": "GATE_EVIDENCE_NAV_REACHABILITY_MODE",
        "schema_cutoff": False,
    }


def _bg2_wire_fixture(root: str, nav_content: str) -> None:
    """Build a project tree with project/[id]/page.tsx and a nav-bar."""
    _mktree(root, {
        "src/app/project/[id]/page.tsx": "// dynamic only",
        "src/components/nav-bar.tsx": nav_content,
        "experiment/experiment.yaml": (
            "name: test\n"
            "type: web-app\n"
            "stack:\n  auth: supabase\n"
            "behaviors:\n  - pages: [project]\n"
            "golden_path:\n  - page: landing\n"
        ),
    })


def test_bg2_wire_synthetic_href_blocks() -> None:
    print("\n[test_bg2_wire_synthetic_href_blocks]")
    with tempfile.TemporaryDirectory() as root:
        # Synthetic href: bare slug `/project` with onClick redirect.
        # Bare-slug grep MATCHES, but page is dynamic-only → must FAIL.
        nav = (
            '<Link href="/project" onClick={(e) => { '
            'e.preventDefault(); router.push("/dashboard"); }}>\n'
            '  Project\n'
            '</Link>\n'
        )
        _bg2_wire_fixture(root, nav)
        cwd = os.getcwd()
        os.chdir(root)
        try:
            rule = _bg2_wire_rule()
            mode, failures = run_rule(rule)
            project_failure = next(
                (f for f in failures if f.get("page") == "project"), None
            )
            _t("synthetic href produces a failure for 'project'",
               project_failure is not None,
               f"failures={failures}")
            _t("failure classification is 'dynamic-only'",
               project_failure and project_failure.get("classification") == "dynamic-only",
               f"got {project_failure!r}")
            _t("mode is 'deny' (default for severity=block)", mode == "deny",
               f"got {mode!r}")
        finally:
            os.chdir(cwd)


def test_bg2_wire_template_literal_passes() -> None:
    print("\n[test_bg2_wire_template_literal_passes]")
    with tempfile.TemporaryDirectory() as root:
        nav = '<Link href={`/project/${id}`}>Project</Link>\n'
        _bg2_wire_fixture(root, nav)
        cwd = os.getcwd()
        os.chdir(root)
        try:
            rule = _bg2_wire_rule()
            mode, failures = run_rule(rule)
            project_failure = next(
                (f for f in failures if f.get("page") == "project"), None
            )
            _t("template-literal nav PASSES (no failure for project)",
               project_failure is None,
               f"got failures={failures}")
        finally:
            os.chdir(cwd)


def test_bg2_wire_static_page_bare_slug_passes() -> None:
    print("\n[test_bg2_wire_static_page_bare_slug_passes]")
    with tempfile.TemporaryDirectory() as root:
        _mktree(root, {
            "src/app/dashboard/page.tsx": "// static",
            "src/components/nav-bar.tsx": '<Link href="/dashboard">Dashboard</Link>\n',
            "experiment/experiment.yaml": (
                "name: test\n"
                "type: web-app\n"
                "stack:\n  auth: supabase\n"
                "behaviors:\n  - pages: [dashboard]\n"
                "golden_path:\n  - page: landing\n  - page: dashboard\n"
            ),
        })
        cwd = os.getcwd()
        os.chdir(root)
        try:
            rule = _bg2_wire_rule()
            mode, failures = run_rule(rule)
            dashboard_failure = next(
                (f for f in failures if f.get("page") == "dashboard"), None
            )
            _t("static page with bare slug PASSES",
               dashboard_failure is None,
               f"failures={failures}")
        finally:
            os.chdir(cwd)


def test_bg2_wire_static_page_template_literal_only_fails() -> None:
    """Static page should keep bare-slug requirement; template literal alone
    does NOT suffice (the user can't reach the static page via parameterized URL)."""
    print("\n[test_bg2_wire_static_page_template_literal_only_fails]")
    with tempfile.TemporaryDirectory() as root:
        _mktree(root, {
            "src/app/dashboard/page.tsx": "// static",
            "src/components/nav-bar.tsx": '<Link href={`/dashboard/${id}`}>Dashboard</Link>\n',
            "experiment/experiment.yaml": (
                "name: test\n"
                "type: web-app\n"
                "stack:\n  auth: supabase\n"
                "behaviors:\n  - pages: [dashboard]\n"
                "golden_path:\n  - page: landing\n  - page: dashboard\n"
            ),
        })
        cwd = os.getcwd()
        os.chdir(root)
        try:
            rule = _bg2_wire_rule()
            mode, failures = run_rule(rule)
            dashboard_failure = next(
                (f for f in failures if f.get("page") == "dashboard"), None
            )
            _t("static page WITHOUT bare slug FAILS",
               dashboard_failure is not None,
               f"got failures={failures}")
        finally:
            os.chdir(cwd)


def test_bg2_wire_mixed_requires_both() -> None:
    print("\n[test_bg2_wire_mixed_requires_both]")
    with tempfile.TemporaryDirectory() as root:
        # portfolio is mixed (static index + dynamic child)
        _mktree(root, {
            "src/app/portfolio/page.tsx": "// static list",
            "src/app/portfolio/[slug]/page.tsx": "// detail",
            "src/components/nav-bar.tsx": (
                '<Link href="/portfolio">List</Link>\n'
                '<Link href={`/portfolio/${slug}`}>Detail</Link>\n'
            ),
            "experiment/experiment.yaml": (
                "name: test\n"
                "type: web-app\n"
                "stack:\n  auth: supabase\n"
                "behaviors:\n  - pages: [portfolio-detail]\n"
                "golden_path:\n  - page: landing\n"
            ),
        })
        cwd = os.getcwd()
        os.chdir(root)
        try:
            rule = _bg2_wire_rule()
            mode, failures = run_rule(rule)
            portfolio_failure = next(
                (f for f in failures if f.get("page") == "portfolio-detail"), None
            )
            _t("mixed page with both forms PASSES",
               portfolio_failure is None,
               f"failures={failures}")
        finally:
            os.chdir(cwd)

        # Now drop the template literal — should FAIL
        _mktree(root, {
            "src/components/nav-bar.tsx": '<Link href="/portfolio">List</Link>\n',
        })
        os.chdir(root)
        try:
            rule = _bg2_wire_rule()
            mode, failures = run_rule(rule)
            portfolio_failure = next(
                (f for f in failures if f.get("page") == "portfolio-detail"), None
            )
            _t("mixed page missing template literal FAILS",
               portfolio_failure is not None,
               f"failures={failures}")
        finally:
            os.chdir(cwd)


def test_bg2_wire_warn_mode_returns_no_block() -> None:
    print("\n[test_bg2_wire_warn_mode_returns_no_block]")
    with tempfile.TemporaryDirectory() as root:
        nav = '<Link href="/project">Project</Link>\n'  # bare slug for dynamic-only
        _bg2_wire_fixture(root, nav)
        cwd = os.getcwd()
        os.chdir(root)
        try:
            rule = _bg2_wire_rule()
            os.environ["GATE_EVIDENCE_NAV_REACHABILITY_MODE"] = "warn"
            mode, failures = run_rule(rule)
            _t("MODE=warn returns mode='warn' even with failures",
               mode == "warn" and len(failures) > 0,
               f"mode={mode}, failures={failures}")
            os.environ.pop("GATE_EVIDENCE_NAV_REACHABILITY_MODE", None)
        finally:
            os.chdir(cwd)


def test_bg2_wire_multiline_template_literal() -> None:
    """Prettier-formatted multi-line template literal should be detected."""
    print("\n[test_bg2_wire_multiline_template_literal]")
    with tempfile.TemporaryDirectory() as root:
        nav = (
            "<Link\n"
            "  href={`/project/${id}`}\n"
            ">\n"
            "  Project\n"
            "</Link>\n"
        )
        _bg2_wire_fixture(root, nav)
        cwd = os.getcwd()
        os.chdir(root)
        try:
            rule = _bg2_wire_rule()
            mode, failures = run_rule(rule)
            project_failure = next(
                (f for f in failures if f.get("page") == "project"), None
            )
            _t("multi-line template literal PASSES",
               project_failure is None,
               f"failures={failures}")
        finally:
            os.chdir(cwd)


# ----------------------------------------------------------------------------
# 4. #1470 fixtures — observation evidence pairing
# ----------------------------------------------------------------------------

def _observation_pairing_rule() -> dict:
    return {
        "id": "agent-workaround-pairing",
        "type": "friction_event_extraction",
        "gate_id": "check-observation-artifacts",
        "severity": "warn",
        "evidence_sources": [
            {"path_glob": ".runs/agent-traces/*.json", "reader": "json"},
            {"path_glob": ".runs/verify-recheck.json", "reader": "json"},
        ],
        "matcher": {
            "kind": "friction_event_extraction",
            "params": {"fields": ["workarounds", "template_gap_observed", "verify_results"]},
        },
        "expected_observation": {
            "artifact_path": ".runs/retrospective-filed-findings.json",
            "predicate": "matches_friction_count",
            "params": {"or_suppressed_in": ".runs/retrospective-result.json"},
        },
        "failure_citation_format": (
            "friction event '{description}' from {source_path} has no paired observation."
        ),
        "mode_env": "GATE_EVIDENCE_OBSERVATION_PAIRING_MODE",
        "schema_cutoff": False,
    }


def _run_enumerator(root: str) -> str:
    """Invoke the canonical enumerator and return path to written pending file.

    The enumerator is the single source of truth for candidate_ids; tests
    cross-reference its output rather than re-deriving cids locally
    (which used to silently diverge — see this PR's first-principles audit).
    """
    import subprocess
    enum_path = os.path.normpath(
        os.path.join(_LIB, "..", "enumerate-pending-retrospective-findings.py")
    )
    subprocess.check_call(
        ["python3", enum_path],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return os.path.join(root, ".runs", "retrospective-pending-findings.json")


def _read_first_cid(pending_path: str, kind: str) -> str:
    with open(pending_path) as fh:
        doc = json.load(fh)
    for c in doc.get("candidates") or []:
        if c.get("kind") == kind:
            return c.get("candidate_id") or ""
    return ""


def test_observation_pairing_unfiled_blocks() -> None:
    print("\n[test_observation_pairing_unfiled_blocks]")
    with tempfile.TemporaryDirectory() as root:
        # Agent trace with a workaround that has NO paired filing/suppression
        trace_path = os.path.join(root, ".runs", "agent-traces", "test.json")
        os.makedirs(os.path.dirname(trace_path))
        with open(trace_path, "w") as fh:
            json.dump({
                "agent": "implementer",
                "workarounds": [{
                    "file": "src/foo.ts",
                    "line": 42,
                    "type": "fallback",
                    "description": "stubbed because template missing",
                    "root_cause_unresolved": True,
                }],
                "template_gap_observed": [],
            }, fh)

        # Empty filed + empty suppressions
        filed_path = os.path.join(root, ".runs", "retrospective-filed-findings.json")
        with open(filed_path, "w") as fh:
            json.dump({"schema_version": 2, "filed": []}, fh)
        result_path = os.path.join(root, ".runs", "retrospective-result.json")
        with open(result_path, "w") as fh:
            json.dump({"suppressions": []}, fh)

        cwd = os.getcwd()
        os.chdir(root)
        try:
            _run_enumerator(root)
            rule = _observation_pairing_rule()
            mode, failures = run_rule(rule)
            _t("unfiled friction → failures non-empty",
               len(failures) > 0,
               f"failures={failures}")
            _t("failure cites the workaround description",
               any("stubbed because template missing" in f.get("description", "") for f in failures),
               f"failures={failures}")
        finally:
            os.chdir(cwd)


def test_observation_pairing_filed_passes() -> None:
    print("\n[test_observation_pairing_filed_passes]")
    with tempfile.TemporaryDirectory() as root:
        trace_path = os.path.join(root, ".runs", "agent-traces", "test.json")
        os.makedirs(os.path.dirname(trace_path))
        with open(trace_path, "w") as fh:
            json.dump({
                "agent": "implementer",
                "workarounds": [{
                    "file": "src/foo.ts",
                    "line": 42,
                    "type": "fallback",
                    "description": "stubbed because template missing",
                    "root_cause_unresolved": True,
                }],
                "template_gap_observed": [],
            }, fh)
        cwd = os.getcwd()
        os.chdir(root)
        try:
            pending = _run_enumerator(root)
            cid = _read_first_cid(pending, "agent-workaround")
            _t("enumerator emitted canonical cid",
               bool(cid),
               f"pending file: {pending}")
            # FILED with the canonical cid (from the enumerator)
            filed_path = os.path.join(root, ".runs", "retrospective-filed-findings.json")
            with open(filed_path, "w") as fh:
                json.dump({"schema_version": 2, "filed": [{"candidate_id": cid}]}, fh)
            result_path = os.path.join(root, ".runs", "retrospective-result.json")
            with open(result_path, "w") as fh:
                json.dump({"suppressions": []}, fh)
            rule = _observation_pairing_rule()
            mode, failures = run_rule(rule)
            _t("FILED candidate (canonical cid) → no failure",
               len(failures) == 0,
               f"failures={failures}")
        finally:
            os.chdir(cwd)


def test_observation_pairing_suppressed_passes() -> None:
    print("\n[test_observation_pairing_suppressed_passes]")
    with tempfile.TemporaryDirectory() as root:
        trace_path = os.path.join(root, ".runs", "agent-traces", "test.json")
        os.makedirs(os.path.dirname(trace_path))
        with open(trace_path, "w") as fh:
            json.dump({
                "agent": "implementer",
                "workarounds": [{
                    "file": "src/foo.ts",
                    "line": 42,
                    "type": "fallback",
                    "description": "stubbed because template missing",
                    "root_cause_unresolved": True,
                }],
                "template_gap_observed": [],
            }, fh)
        cwd = os.getcwd()
        os.chdir(root)
        try:
            pending = _run_enumerator(root)
            cid = _read_first_cid(pending, "agent-workaround")
            filed_path = os.path.join(root, ".runs", "retrospective-filed-findings.json")
            with open(filed_path, "w") as fh:
                json.dump({"schema_version": 2, "filed": []}, fh)
            # SUPPRESSED with the canonical cid
            result_path = os.path.join(root, ".runs", "retrospective-result.json")
            with open(result_path, "w") as fh:
                json.dump({
                    "suppressions": [{
                        "candidate_id": cid,
                        "reason": "addressed_inline",
                        "rationale": "fixed in same PR via separate commit",
                    }]
                }, fh)
            rule = _observation_pairing_rule()
            mode, failures = run_rule(rule)
            _t("SUPPRESSED candidate (canonical cid) → no failure",
               len(failures) == 0,
               f"failures={failures}")
        finally:
            os.chdir(cwd)


def test_observation_pairing_self_resolved_workaround_skipped() -> None:
    print("\n[test_observation_pairing_self_resolved_workaround_skipped]")
    with tempfile.TemporaryDirectory() as root:
        trace_path = os.path.join(root, ".runs", "agent-traces", "test.json")
        os.makedirs(os.path.dirname(trace_path))
        with open(trace_path, "w") as fh:
            json.dump({
                "agent": "implementer",
                "workarounds": [{
                    "file": "src/foo.ts",
                    "line": 42,
                    "type": "fallback",
                    "description": "self-resolved within run",
                    "root_cause_unresolved": False,  # explicit
                }],
                "template_gap_observed": [],
            }, fh)
        cwd = os.getcwd()
        os.chdir(root)
        try:
            _run_enumerator(root)
            rule = _observation_pairing_rule()
            mode, failures = run_rule(rule)
            _t("root_cause_unresolved=False workaround → no friction event",
               len(failures) == 0,
               f"failures={failures}")
        finally:
            os.chdir(cwd)


def test_observation_pairing_verify_failure() -> None:
    print("\n[test_observation_pairing_verify_failure]")
    with tempfile.TemporaryDirectory() as root:
        os.makedirs(os.path.join(root, ".runs"))
        with open(os.path.join(root, ".runs", "verify-recheck.json"), "w") as fh:
            json.dump({
                "verify_results": [
                    {"state": "3b", "passed": False, "error": "build failed"},
                    {"state": "4", "passed": True, "error": None},
                ],
            }, fh)
        cwd = os.getcwd()
        os.chdir(root)
        try:
            _run_enumerator(root)
            rule = _observation_pairing_rule()
            mode, failures = run_rule(rule)
            _t("verify-recheck failed state → failure cited",
               any(f.get("kind") == "verify-failure" for f in failures),
               f"failures={failures}")
            _t("passed states do NOT emit failure",
               not any(f.get("state") == "4" for f in failures),
               f"failures={failures}")
        finally:
            os.chdir(cwd)


def test_observation_pairing_pending_canonical_cid_match() -> None:
    """Regression: the GECR rule's cid lookup MUST match the cid the
    enumerator writes. The original implementation re-derived cids locally
    with a different prefix convention than `_hash_key(prefix, key)`, so
    real filed cids never matched. This test would have caught that bug.
    """
    print("\n[test_observation_pairing_pending_canonical_cid_match]")
    with tempfile.TemporaryDirectory() as root:
        trace_path = os.path.join(root, ".runs", "agent-traces", "test.json")
        os.makedirs(os.path.dirname(trace_path))
        with open(trace_path, "w") as fh:
            json.dump({
                "agent": "implementer",
                "workarounds": [{
                    "file": "src/foo.ts",
                    "line": 42,
                    "type": "fallback",
                    "description": "stubbed because template missing",
                    "root_cause_unresolved": True,
                }],
                "template_gap_observed": [],
            }, fh)
        cwd = os.getcwd()
        os.chdir(root)
        try:
            pending = _run_enumerator(root)
            with open(pending) as fh:
                doc = json.load(fh)
            cid_from_enum = ""
            for c in doc.get("candidates") or []:
                if c.get("kind") == "agent-workaround":
                    cid_from_enum = c.get("candidate_id") or ""
                    break
            _t("enumerator wrote a candidate_id",
               bool(cid_from_enum),
               f"pending: {doc}")
            # The cid the rule reports as missing must equal what enumerator wrote
            filed_path = os.path.join(root, ".runs", "retrospective-filed-findings.json")
            with open(filed_path, "w") as fh:
                json.dump({"schema_version": 2, "filed": []}, fh)
            rule = _observation_pairing_rule()
            mode, failures = run_rule(rule)
            cids_from_rule = {f.get("candidate_id") for f in failures}
            _t("rule's cid matches enumerator's cid (no re-derive divergence)",
               cid_from_enum in cids_from_rule,
               f"enum={cid_from_enum!r} rule={cids_from_rule!r}")
        finally:
            os.chdir(cwd)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main() -> int:
    test_classification()
    test_classification_absent()
    test_classification_no_src_app()
    test_load_rules_empty()
    test_load_rules_project_seed()
    test_load_rules_malformed()
    test_bg2_wire_synthetic_href_blocks()
    test_bg2_wire_template_literal_passes()
    test_bg2_wire_static_page_bare_slug_passes()
    test_bg2_wire_static_page_template_literal_only_fails()
    test_bg2_wire_mixed_requires_both()
    test_bg2_wire_warn_mode_returns_no_block()
    test_bg2_wire_multiline_template_literal()
    test_observation_pairing_unfiled_blocks()
    test_observation_pairing_filed_passes()
    test_observation_pairing_suppressed_passes()
    test_observation_pairing_self_resolved_workaround_skipped()
    test_observation_pairing_verify_failure()
    test_observation_pairing_pending_canonical_cid_match()

    print()
    print(f"=== {_PASS} passed, {_FAIL} failed ===")
    if _FAIL:
        for name, ok in _NAMES:
            if not ok:
                print(f"  FAIL: {name}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
