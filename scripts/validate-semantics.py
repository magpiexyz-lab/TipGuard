#!/usr/bin/env python3
"""Validate semantic correctness across stack files, skill files, and fixtures.

This is the facade entry point. Domain-specific check functions are organized
in the validators/ package. This file contains the CHECKS registry, context
building, and orchestration logic.

Invocation: python3 scripts/validate-semantics.py
Exit code: 0 = all checks pass, 1 = one or more checks failed.
"""
import glob
import json
import os
import re
import sys

import yaml

# Add script directory to path for validators package import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from validators import *  # noqa: E402, F403 — re-exports all check_* functions
from validators._utils import (  # noqa: E402
    ERRORS,
    BASE_REQUIRED_EXPERIMENT_FIELDS,
    OPTIONAL_CATEGORIES,
    error,
    read_skill_with_states,
    parse_frontmatter,
    extract_code_blocks,
    extract_prose,
    parse_frontmatter_from_content,
    get_required_experiment_fields,
    parse_makefile_targets,
)


# ---------------------------------------------------------------------------
# Check registry — maps check numbers to descriptions and wiring lambdas
# ---------------------------------------------------------------------------

CHECKS: list[tuple[int, str, object]] = [
    (1, "Import Completeness", lambda ctx: check_1_import_completeness(ctx["stack_contents"])),
    (2, "Makefile Target Guards", lambda ctx: check_2_makefile_target_guards(ctx["makefile_content"]) if ctx["makefile_content"] else []),
    (3, "Fixture Validation", lambda ctx: ctx["_check_3_result"][0]),
    (4, "Frontmatter Content Sync", lambda ctx: check_4_frontmatter_content_sync(ctx["stack_files"], ctx["stack_contents"], ctx["makefile_content"])),
    (5, "Conditional Dependency References", lambda ctx: check_5_conditional_dependency_refs(ctx["skill_contents"])),
    (6, "Required Fields Consistency", lambda ctx: check_6_required_fields_consistency(ctx["makefile_content"], ctx["REQUIRED_EXPERIMENT_FIELDS"])),
    (7, "Fixture Stack Coverage", lambda ctx: check_7_fixture_stack_coverage(ctx["fixture_dir"], ctx["stack_files"], ctx["fixture_type_map"], ctx["bootstrap_content"])),
    (8, "Tool Prereq Validity", lambda ctx: check_8_tool_prereq_validity(ctx["skill_contents"])),
    (9, "Env Loading Outside Next.js Runtime", lambda ctx: check_9_env_loading_outside_nextjs(ctx["stack_contents"])),
    (10, "Validate Warning Differentiation", lambda ctx: check_10_validate_warning_differentiation(ctx["makefile_content"], ctx["makefile_targets"])),
    (11, "Hardcoded Provider Names Match Assumes", lambda ctx: check_11_hardcoded_provider_names(ctx["stack_contents"])),
    (12, "Prose File References in Reads Frontmatter", lambda ctx: check_12_prose_file_refs_in_reads(ctx["skill_contents"])),
    (13, "Fixture Branching Coverage", lambda ctx: check_13_fixture_branching_coverage(ctx["fixture_dir"], ctx["stack_contents"])),
    (14, "Stack Fallback When Assumes Not Met", lambda ctx: check_14_stack_fallback_when_assumes_not_met(ctx["stack_contents"])),
    (15, "Makefile Deploy Hosting Guard", lambda ctx: check_15_makefile_deploy_hosting_guard(ctx["makefile_content"], ctx["makefile_targets"])),
    (16, "Change Payment-Auth Dependency", lambda ctx: check_16_change_payment_auth(ctx["change_content"], ".claude/commands/change.md") if ctx["change_content"] else []),
    (17, "Env Vars Prose-Frontmatter Sync", lambda ctx: check_17_env_vars_prose_frontmatter_sync(ctx["stack_contents"])),
    (18, "Change Payment-Database Dependency", lambda ctx: check_18_change_payment_database(ctx["change_content"], ".claude/commands/change.md") if ctx["change_content"] else []),
    (19, "Fixture Testing Partial Assumes", lambda ctx: check_19_fixture_testing_partial_assumes(ctx["fixture_dir"], ctx["stack_files"])),
    (20, "Makefile Help No Env Var Names", lambda ctx: check_20_makefile_help_no_env_vars(ctx["makefile_content"])),
    (21, "Packages Prose-Frontmatter Sync", lambda ctx: check_21_packages_prose_frontmatter_sync(ctx["stack_contents"])),
    (22, "Bootstrap Payment-Database Dependency", lambda ctx: check_22_bootstrap_payment_database(ctx["bootstrap_content"])),
    (23, "Testing CI Payment Env Vars", lambda ctx: check_23_testing_ci_payment_env_vars(ctx["stack_contents"])),
    (24, "Testing No-Auth Fallback CI Template", lambda ctx: check_24_testing_noauth_fallback_ci(ctx["stack_contents"])),
    (25, "Change Test Type Testing Stack", lambda ctx: check_25_change_test_type_testing_stack(ctx["change_content"])),
    (26, "Testing Env Frontmatter Assumes", lambda ctx: check_26_testing_env_frontmatter_assumes(ctx["stack_files"], ctx["stack_contents"])),
    (27, "Auth Post-Auth Redirects", lambda ctx: check_27_auth_post_auth_redirects(ctx["stack_contents"])),
    (28, "Change Assumes Validation", lambda ctx: check_28_change_assumes_validation(ctx["change_content"])),
    (29, "Change Payment Before Plan", lambda ctx: check_29_change_payment_before_plan(ctx["change_content"])),
    (30, "Analytics Dashboard Navigation", lambda ctx: check_30_analytics_dashboard_navigation(ctx["stack_files"], ctx["stack_contents"])),
    (31, "Change Testing Assumes Revalidation", lambda ctx: check_31_change_testing_assumes_revalidation(ctx["change_content"])),
    (32, "Analytics Test Blocking", lambda ctx: check_32_analytics_test_blocking(ctx["stack_files"], ctx["stack_contents"])),
    (33, "Phantom Event Names", lambda ctx: check_33_phantom_event_names(ctx["skill_contents"], ctx["defined_events"], ctx["global_props"], ctx["event_props"]) if ctx["events_data"] else []),
    (34, "Conditional Files Frontmatter", lambda ctx: check_34_conditional_files_frontmatter(ctx["stack_contents"])),
    (35, "No-Auth CI Database Env Vars", lambda ctx: check_35_noauth_ci_database_env_vars(ctx["stack_contents"])),
    # 36 removed
    (37, "Change Classification Before Dependent", lambda ctx: check_37_change_classification_before_dependent(ctx["change_content"])),
    (38, "Ads.yaml Schema", lambda ctx: check_38_ads_yaml_schema(ctx["ads_data"], "experiment/ads.yaml") if ctx["ads_data"] else []),
    (39, "Ads Campaign Name Match", lambda ctx: check_39_ads_campaign_name(ctx["ads_data"], ctx["idea_data"], "experiment/ads.yaml") if ctx["ads_data"] and ctx["idea_data"] else []),
    (40, "Distribute Feedback Event", lambda ctx: check_40_distribute_feedback_event(ctx["distribute_content"])),
    (41, "Distribution Docs References", lambda ctx: check_41_distribution_docs_references()),
    (42, "Distribute Validates Analytics", lambda ctx: check_42_distribute_validates_analytics(ctx["distribute_content"])),
    (43, "Distribute Validates Events Structure", lambda ctx: check_43_distribute_validates_events_structure(ctx["distribute_content"])),
    (44, "Bootstrap Validates Variants", lambda ctx: check_44_bootstrap_validates_variants(ctx["bootstrap_content"])),
    (45, "visit_landing Variant Property", lambda ctx: check_45_visit_landing_variant_property(ctx["events_data"])),
    (46, "Iterate Verdict", lambda ctx: check_46_iterate_verdict(ctx["iterate_content"]) if ctx["iterate_content"] else []),
    (47, "Deploy Dashboard Setup", lambda ctx: check_47_deploy_dashboard_setup(ctx["deploy_content"])),
    (48, "Iterate Next Check-in", lambda ctx: check_48_iterate_next_checkin(ctx["iterate_content"])),
    (49, "Bootstrap Email-Auth-Database", lambda ctx: check_49_bootstrap_email_auth_database(ctx["bootstrap_content"])),
    (50, "Change Email-Auth-Database", lambda ctx: check_50_change_email_auth_database(ctx["change_content"])),
    (51, "trackServerEvent Signature", lambda ctx: check_51_track_server_event_signature(ctx["stack_contents"])),
    (52, "trackServerEvent Awaited", lambda ctx: check_52_track_server_event_awaited(ctx["stack_contents"])),
    (53, "Supabase Delete Flag", lambda ctx: check_53_supabase_delete_flag({**ctx["skill_contents"], **ctx["stack_contents"]})),
    (54, "Procedure Production Branch", lambda ctx: check_54_procedure_production_branch(ctx["procedure_contents"]) if ctx["procedure_contents"] else []),
    (55, "Production References TDD", lambda ctx: check_55_production_references_tdd(ctx["procedure_contents"]) if ctx["procedure_contents"] else []),
    (56, "Production References Implementer", lambda ctx: check_56_production_references_implementer(ctx["procedure_contents"]) if ctx["procedure_contents"] else []),
    (57, "Change Production Precondition", lambda ctx: check_57_change_production_precondition(ctx["change_content"]) if ctx["change_content"] else []),
    (58, "Agent Tool Consistency", lambda ctx: check_58_agent_tool_consistency(ctx["agent_contents"]) if ctx["agent_contents"] else []),
    (59, "Framework-Archetype Compatibility", lambda ctx: check_59_framework_archetype_compatibility(ctx["bootstrap_content"], ctx["change_content"]) if ctx["bootstrap_content"] and ctx["change_content"] else []),
    (60, "Settings Hook Paths", lambda ctx: check_60_settings_hook_paths()),
    (61, "Footer Directive Sync", lambda ctx: check_61_footer_directive_sync()),
    (62, "Trace Framework Completeness", lambda ctx: check_62_trace_framework_completeness()),
    (63, "Canonical Dependency Reference", lambda ctx: check_63_canonical_dependency_ref(
        ctx["bootstrap_content"], ctx["change_content"], ctx["procedure_contents"], ctx["agent_contents"])
        if ctx["bootstrap_content"] and ctx["change_content"] else []),
    (64, "Conditional Packages Prose Sync", lambda ctx: check_64_conditional_packages_prose_sync(ctx["stack_contents"])),
    (65, "Playwright-Archetype Compatibility", lambda ctx: check_65_playwright_archetype_compatibility(ctx["bootstrap_content"], ctx["change_content"]) if ctx["bootstrap_content"] and ctx["change_content"] else []),
    (66, "Audit/Review Scope Coverage", lambda ctx: check_66_audit_review_scope_coverage()),
]



def run_checks(
    checks: list[tuple[int, str, object]],
    ctx: dict,
) -> list[str]:
    """Run a list of check entries and collect all errors.

    Each entry is (check_number, description, callable_that_takes_ctx).
    """
    all_errors: list[str] = []
    for _num, _desc, check_fn in checks:
        errs = check_fn(ctx)
        if errs:
            all_errors.extend(errs)
    return all_errors


def main() -> int:
    """Run all semantic checks. Returns exit code (0=pass, 1=fail)."""
    ERRORS.clear()

    # ---------------------------------------------------------------------------
    # Collect files and read contents
    # ---------------------------------------------------------------------------

    stack_files = sorted(
        f
        for f in glob.glob(".claude/stacks/**/*.md", recursive=True)
        if "TEMPLATE" not in f
    )
    skill_files = sorted(glob.glob(".claude/commands/*.md"))

    stack_contents: dict[str, str] = {}
    for sf in stack_files:
        with open(sf) as f:
            stack_contents[sf] = f.read()

    skill_contents: dict[str, str] = {}
    for sf in skill_files:
        with open(sf) as f:
            skill_contents[sf] = f.read()

    # Read Makefile
    makefile_path = "Makefile"
    makefile_content: str | None = None
    makefile_targets: dict[str, str] = {}
    if os.path.isfile(makefile_path):
        with open(makefile_path) as f:
            makefile_content = f.read()
        makefile_targets = parse_makefile_targets(makefile_content)

    # Pre-read commonly used skill files
    bootstrap_path = ".claude/commands/bootstrap.md"
    bootstrap_content = read_skill_with_states(bootstrap_path) if os.path.isfile(bootstrap_path) else None

    change_path = ".claude/commands/change.md"
    change_content = read_skill_with_states(change_path) if os.path.isfile(change_path) else None

    deploy_path = ".claude/commands/deploy.md"
    deploy_content = read_skill_with_states(deploy_path) if os.path.isfile(deploy_path) else None

    iterate_path = ".claude/commands/iterate.md"
    iterate_content = read_skill_with_states(iterate_path) if os.path.isfile(iterate_path) else None

    distribute_path = ".claude/commands/distribute.md"
    distribute_content = read_skill_with_states(distribute_path) if os.path.isfile(distribute_path) else None

    # Pre-read procedure files
    procedure_contents: dict[str, str] = {}
    for pf in glob.glob(".claude/procedures/*.md"):
        if os.path.isfile(pf):
            with open(pf) as f:
                procedure_contents[pf] = f.read()

    # Pre-read agent files
    agent_contents: dict[str, str] = {}
    for af in glob.glob(".claude/agents/*.md"):
        if os.path.isfile(af):
            with open(af) as f:
                agent_contents[af] = f.read()

    # Pre-parse events data
    events_data: dict | None = None
    defined_events: set[str] = set()
    global_props: set[str] = set()
    event_props: set[str] = set()
    events_yaml_path = "experiment/EVENTS.yaml"
    if os.path.isfile(events_yaml_path):
        with open(events_yaml_path) as f:
            events_data = yaml.safe_load(f) or {}
        flat_events = events_data.get("events", {})
        if isinstance(flat_events, dict):
            for ename in flat_events:
                defined_events.add(ename)
            for ename, edef in flat_events.items():
                if isinstance(edef, dict):
                    for prop_name in (edef.get("properties", {}) or {}).keys():
                        event_props.add(prop_name)
        global_props = set((events_data.get("global_properties", {}) or {}).keys())

    # Pre-parse ads data
    ads_data: dict | None = None
    ads_yaml_path = "experiment/ads.yaml"
    if os.path.isfile(ads_yaml_path):
        with open(ads_yaml_path) as f:
            try:
                ads_data = yaml.safe_load(f)
            except yaml.YAMLError as e:
                error(f"[38] {ads_yaml_path}: invalid YAML: {e}")
        if ads_data and not isinstance(ads_data, dict):
            ads_data = None

    # Pre-parse experiment.yaml for idea data
    idea_data: dict | None = None
    if os.path.isfile("experiment/experiment.yaml"):
        with open("experiment/experiment.yaml") as f:
            idea_data = yaml.safe_load(f)
        if idea_data and not isinstance(idea_data, dict):
            idea_data = None

    # Fixture dir and type map (computed by check 3, needed by check 7)
    fixture_dir = "tests/fixtures"
    REQUIRED_EXPERIMENT_FIELDS = get_required_experiment_fields("web-app")
    check_3_result = check_3_fixture_validation(fixture_dir, get_required_experiment_fields)
    fixture_type_map = check_3_result[1]

    # ---------------------------------------------------------------------------
    # Build context dict
    # ---------------------------------------------------------------------------

    ctx = {
        "stack_files": stack_files,
        "stack_contents": stack_contents,
        "skill_contents": skill_contents,
        "makefile_content": makefile_content,
        "makefile_targets": makefile_targets,
        "fixture_dir": fixture_dir,
        "fixture_type_map": fixture_type_map,
        "REQUIRED_EXPERIMENT_FIELDS": REQUIRED_EXPERIMENT_FIELDS,
        "get_required_experiment_fields": get_required_experiment_fields,
        "bootstrap_content": bootstrap_content,
        "change_content": change_content,
        "deploy_content": deploy_content,
        "iterate_content": iterate_content,
        "distribute_content": distribute_content,
        "procedure_contents": procedure_contents,
        "agent_contents": agent_contents,
        "events_data": events_data,
        "defined_events": defined_events,
        "global_props": global_props,
        "event_props": event_props,
        "ads_data": ads_data,
        "idea_data": idea_data,
        "_check_3_result": check_3_result,
    }

    # ---------------------------------------------------------------------------
    # Run all checks
    # ---------------------------------------------------------------------------

    all_errors = run_checks(CHECKS, ctx)
    for e in all_errors:
        error(e)

    # ---------------------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------------------

    print()
    if ERRORS:
        print(f"FAILED: {len(ERRORS)} error(s)")
        return 1
    else:
        print("PASSED: All semantic checks passed.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
