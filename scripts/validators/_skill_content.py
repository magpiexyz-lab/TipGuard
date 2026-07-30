"""Skill file content validation checks."""
import os
import re

from ._utils import (
    extract_prose,
    extract_code_blocks,
    parse_frontmatter,
    parse_frontmatter_from_content,
)

__all__ = [
    "check_5_conditional_dependency_refs",
    "check_8_tool_prereq_validity",
    "check_12_prose_file_refs_in_reads",
    "check_16_change_payment_auth",
    "check_18_change_payment_database",
    "check_22_bootstrap_payment_database",
    "check_25_change_test_type_testing_stack",
    "check_28_change_assumes_validation",
    "check_29_change_payment_before_plan",
    "check_31_change_testing_assumes_revalidation",
    "check_37_change_classification_before_dependent",
    "check_40_distribute_feedback_event",
    "check_42_distribute_validates_analytics",
    "check_43_distribute_validates_events_structure",
    "check_44_bootstrap_validates_variants",
    "check_46_iterate_verdict",
    "check_47_deploy_dashboard_setup",
    "check_48_iterate_next_checkin",
    "check_49_bootstrap_email_auth_database",
    "check_50_change_email_auth_database",
    "check_57_change_production_precondition",
    "check_59_framework_archetype_compatibility",
    "check_63_canonical_dependency_ref",
    "check_65_playwright_archetype_compatibility",
]

def check_5_conditional_dependency_refs(skill_contents: dict[str, str]) -> list[str]:
    """Check 5: References to optional stack categories have conditional guards."""
    errors: list[str] = []
    optional_categories = {"database", "auth", "payment", "email"}
    for sf, content in skill_contents.items():
        prose = extract_prose(content)
        for m in re.finditer(r"from the (\w+) stack file", prose):
            category = m.group(1)
            if category not in optional_categories:
                continue
            start = max(0, m.start() - 150)
            context_before = prose[start : m.start()]
            has_guard = bool(
                re.search(
                    rf"(?i)(?:if\s+.*(?:stack\.{category}|`stack\.{category}`)|"
                    rf"if\b.*\b{category}\b.*\bpresent\b)",
                    context_before,
                    re.DOTALL,
                )
            )
            if not has_guard:
                match_text = m.group(0)
                pos = content.find(match_text)
                line_num = content[:pos].count("\n") + 1 if pos >= 0 else "?"
                errors.append(
                    f"[5] {sf}:{line_num}: reference to optional '{category}' "
                    f"stack file lacks conditional guard within 150 chars"
                )
    return errors


def check_8_tool_prereq_validity(skill_contents: dict[str, str]) -> list[str]:
    """Check 8: Referenced tools in skill prose exist."""
    errors: list[str] = []
    KNOWN_TOOLS = {
        "Read", "Write", "Edit", "Bash", "Glob", "Grep",
        "WebFetch", "WebSearch", "Task", "NotebookEdit",
        "AskUserQuestion", "EnterPlanMode", "ExitPlanMode",
        "Skill", "TaskCreate", "TaskUpdate", "TaskGet", "TaskList",
        "TaskOutput", "TaskStop",
    }
    for sf, content in skill_contents.items():
        prose = extract_prose(content)
        for m in re.finditer(r"using the (\w+) tool", prose):
            tool_name = m.group(1)
            if tool_name not in KNOWN_TOOLS:
                pos = content.find(m.group(0))
                line_num = content[:pos].count("\n") + 1 if pos >= 0 else "?"
                errors.append(
                    f"[8] {sf}:{line_num}: references unknown tool "
                    f"'{tool_name}'"
                )
    return errors


def check_12_prose_file_refs_in_reads(skill_contents: dict[str, str]) -> list[str]:
    """Check 12: Prose file references appear in reads frontmatter."""
    errors: list[str] = []
    SPEC_REFERENCE_FILES = {"CLAUDE.md", "experiment/EVENTS.yaml"}

    for sf, content in skill_contents.items():
        fm = parse_frontmatter(sf)
        if not fm:
            continue
        reads = set(fm.get("reads", []) or [])
        writes = set(fm.get("writes", []) or [])
        declared = reads | writes
        prose = extract_prose(content)

        for ref_file in SPEC_REFERENCE_FILES:
            for m_ref in re.finditer(
                rf"\b{re.escape(ref_file)}\b", prose
            ):
                start = max(0, m_ref.start() - 100)
                context_before = prose[start : m_ref.start()]
                if re.search(r"e\.g\.\s*,", context_before):
                    continue

                matched = any(ref_file in r or r in ref_file for r in declared)
                if not matched:
                    pos = content.find(ref_file)
                    line_num = content[:pos].count("\n") + 1 if pos >= 0 else "?"
                    errors.append(
                        f"[12] {sf}:{line_num}: prose references '{ref_file}' "
                        f"but it's not in 'reads' or 'writes' frontmatter"
                    )
                    break
    return errors


def check_16_change_payment_auth(change_content: str, change_path: str) -> list[str]:
    """Check 16: change.md validates payment requires auth."""
    errors: list[str] = []
    change_prose = extract_prose(change_content)
    has_payment_ref = bool(
        re.search(r"(?i)adding\s+.*payment|payment.*stack", change_prose)
    )
    if has_payment_ref:
        has_auth_check = bool(
            re.search(
                r"(?i)payment.*auth.*present|auth.*present.*payment|"
                r"payment\s+requires\s+auth",
                change_prose,
            )
        )
        if not has_auth_check:
            errors.append(
                f"[16] {change_path}: mentions adding payment stack "
                f"category without a preceding auth-presence validation"
            )
    return errors


def check_18_change_payment_database(change_content: str, change_path: str) -> list[str]:
    """Check 18: change.md Feature constraints validate payment requires database."""
    errors: list[str] = []
    # Search Feature constraints section
    feature_constraints_match = re.search(
        r"(?i)####?\s+Feature constraints\s*\n(.*?)(?=\n####?\s|\Z)",
        change_content,
        re.DOTALL,
    )
    # Also search preconditions section (payment validation may be there)
    preconditions_match = re.search(
        r"(?i)(?:## Step \d+:.*?preconditions|# STATE \d+:\s*CHECK_PRECONDITIONS)\s*\n(.*?)(?=\n## Step \d|\n## Phase|\n# STATE|\Z)",
        change_content,
        re.DOTALL,
    )
    search_text = ""
    if feature_constraints_match:
        search_text += feature_constraints_match.group(1)
    if preconditions_match:
        search_text += "\n" + preconditions_match.group(1)

    if search_text:
        has_db_check = bool(
            re.search(
                r"(?i)payment.*database.*present|database.*present.*payment|"
                r"payment\s+requires.*database|"
                r"stack\.database.*(?:missing|present|also)|"
                r"both.*stack\.auth.*stack\.database",
                search_text,
            )
        )
        if not has_db_check:
            errors.append(
                f"[18] {change_path}: Feature constraints section "
                f"doesn't validate that `payment` in the stack requires "
                f"`database` to also be present"
            )
    return errors


def check_22_bootstrap_payment_database(bootstrap_content: str | None) -> list[str]:
    """Check 22: Bootstrap validates payment requires database."""
    errors: list[str] = []
    bootstrap_path = ".claude/commands/bootstrap.md"
    if not bootstrap_content:
        return errors

    validate_section_match = re.search(
        r"(?i)(?:###?\s*|\d+\.\s*(?:\*\*)?)Validate (?:idea|experiment)\.yaml(?:\*\*)?\s*\n(.*?)(?=\n\d+\.\s*\*\*|\n###?\s|\n##\s|\Z)",
        bootstrap_content,
        re.DOTALL,
    )
    if not validate_section_match:
        validate_section_match = re.search(
            r"(?i)#{1,2}\s*STATE\s+\d+[a-z]*:\s*VALIDATE_EXPERIMENT\s*\n(.*?)(?=\n---\s*\n#{1,2}\s*STATE|\n#\s*STATE|\Z)",
            bootstrap_content,
            re.DOTALL,
        )
    if validate_section_match:
        validate_section = validate_section_match.group(1)
        has_db_check = bool(
            re.search(
                r"(?i)payment.*database.*present|database.*present.*payment|"
                r"payment\s+requires.*database|"
                r"stack\.database.*(?:missing|present|also)|"
                r"stack\.payment.*(?:verify|check).*stack\.database",
                validate_section,
            )
        )
        if not has_db_check:
            errors.append(
                f"[22] {bootstrap_path}: Validate experiment.yaml section "
                f"doesn't validate that `stack.payment` requires "
                f"`stack.database` to also be present"
            )
    else:
        errors.append(
            f"[22] {bootstrap_path}: could not find Validate experiment.yaml "
            f"section to check payment-database dependency"
        )
    return errors


def check_25_change_test_type_testing_stack(change_content: str | None) -> list[str]:
    """Check 25: Change skill Test type permits adding testing to experiment.yaml stack."""
    errors: list[str] = []
    change_path = ".claude/commands/change.md"
    if not change_content:
        return errors

    has_testing_addition = bool(
        re.search(
            r"(?i)(?:test.*(?:add|update).*(?:experiment\.yaml|idea\.yaml|stack).*testing|"
            r"testing.*(?:experiment\.yaml|idea\.yaml|stack)|"
            r"stack\.testing.*(?:experiment\.yaml|idea\.yaml))",
            change_content,
        )
    )
    if not has_testing_addition:
        errors.append(
            f"[25] {change_path}: Test type constraints do not address "
            f"adding `testing` to experiment.yaml stack section"
        )
    return errors


def check_28_change_assumes_validation(change_content: str | None) -> list[str]:
    """Check 28: Change skill value-matches assumes, not just category-exists."""
    errors: list[str] = []
    change_path = ".claude/commands/change.md"
    if not change_content:
        return errors

    assumes_refs = list(
        re.finditer(r"(?i)assumes.*list", change_content)
    )
    if not assumes_refs:
        return errors

    has_value_matching = bool(
        re.search(
            r"(?i)category[/:]value|value\s+(?:must\s+)?match|"
            r"matching\s+.*pair|category:\s*value.*pair|"
            r"not just.*(?:category|present)",
            change_content,
        )
    )
    has_category_only = bool(
        re.search(
            r"(?i)check if the corresponding stack category exists",
            change_content,
        )
    )
    if has_category_only and not has_value_matching:
        errors.append(
            f"[28] {change_path}: assumes validation uses "
            f"category-existence language instead of value-matching "
            f"language (should match bootstrap's approach)"
        )
    return errors


def check_29_change_payment_before_plan(change_content: str | None) -> list[str]:
    """Check 29: Payment dependency checks appear before plan phase."""
    errors: list[str] = []
    change_path = ".claude/commands/change.md"
    if not change_content:
        return errors

    payment_validation_pattern = re.compile(
        r"Payment requires (?:authentication|a database)",
        re.IGNORECASE,
    )
    payment_matches = list(payment_validation_pattern.finditer(change_content))

    if not payment_matches:
        return errors

    plan_phase_match = re.search(
        r"## Phase 1|### STOP",
        change_content,
    )
    if not plan_phase_match:
        return errors

    plan_phase_pos = plan_phase_match.start()
    has_pre_plan = any(
        m.start() < plan_phase_pos for m in payment_matches
    )
    if not has_pre_plan:
        errors.append(
            f"[29] {change_path}: all payment dependency "
            f"validation appears after the plan phase — at least "
            f"one check must be in preconditions (before Phase 1)"
        )
    return errors


def check_31_change_testing_assumes_revalidation(change_content: str | None) -> list[str]:
    """Check 31: Change skill revalidates testing assumes for all change types."""
    errors: list[str] = []
    change_path = ".claude/commands/change.md"
    if not change_content:
        return errors

    preconditions_match = re.search(
        r"(?:## Step \d+:.*?[Cc]heck.*?preconditions|# STATE \d+:\s*CHECK_PRECONDITIONS).*?\n(.*?)(?=\n## Step \d|\n## Phase|\n# STATE|\Z)",
        change_content,
        re.DOTALL,
    )
    if preconditions_match:
        preconditions_text = preconditions_match.group(1)

        has_non_test_assumes_check = bool(
            re.search(
                r"(?i)(?:NOT\s+Test|type\s+is\s+NOT\s+Test).*testing.*assumes|"
                r"testing.*assumes.*(?:NOT\s+Test|type\s+is\s+NOT\s+Test)",
                preconditions_text,
                re.DOTALL,
            )
        )
        if not has_non_test_assumes_check:
            errors.append(
                f"[31] {change_path}: preconditions step does not "
                f"revalidate testing assumes for non-Test change types"
            )
    else:
        errors.append(
            f"[31] {change_path}: could not find preconditions step "
            f"to check testing assumes revalidation"
        )
    return errors


def check_37_change_classification_before_dependent(change_content: str | None) -> list[str]:
    """Check 37: Classification step precedes classification-dependent checks."""
    errors: list[str] = []
    change_path = ".claude/commands/change.md"
    if not change_content:
        return errors

    classify_match = re.search(
        r"^## Step (\d+):.*(?:Classify|classify)",
        change_content,
        re.MULTILINE,
    )

    step_pattern = re.compile(
        r"^## Step (\d+):.*\n(.*?)(?=^## Step \d|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    classification_dependent_steps: list[tuple[int, str]] = []
    for m in step_pattern.finditer(change_content):
        step_num = int(m.group(1))
        body = m.group(2)
        if re.search(r"classified as|is classified as|is a Fix|is NOT Test", body):
            classification_dependent_steps.append((step_num, body[:50]))

    if classify_match and classification_dependent_steps:
        classify_step = int(classify_match.group(1))
        for dep_step, _ in classification_dependent_steps:
            if dep_step < classify_step:
                errors.append(
                    f"[37] {change_path}: Step {dep_step} uses "
                    f"classification-dependent language but appears before "
                    f"the classification step (Step {classify_step})"
                )
    return errors


def check_40_distribute_feedback_event(distribute_content: str | None) -> list[str]:
    """Check 40: distribute.md contains feedback_submitted event definition."""
    errors: list[str] = []
    distribute_path = ".claude/commands/distribute.md"
    if not distribute_content:
        return errors

    yaml_blocks = extract_code_blocks(distribute_content, {"yaml"})
    has_event_def = any(
        "feedback_submitted" in block["code"] and "funnel_stage:" in block["code"]
        for block in yaml_blocks
    )
    if not has_event_def:
        errors.append(
            f"[40] {distribute_path}: must contain a YAML code block "
            f"defining the 'feedback_submitted' event (added to "
            f"experiment/EVENTS.yaml events map during Step 7c)"
        )
    return errors


def _find_preconditions_text(content: str) -> str | None:
    """Extract combined preconditions text from a skill's content.

    Handles both formats:
    - Old: single "## Step 1:" section
    - JIT: multiple state files with VALIDATE_*, ANALYTICS_*, or PREREQUISITES names
    """
    # Old format: ## Step 1: ... ## Step 2: (anchored to reject ### or deeper)
    old_match = re.search(
        r"(?m)^## Step 1:.*?\n(.*?)(?=\n## Step 2:|\Z)",
        content,
        re.DOTALL,
    )
    if old_match:
        return old_match.group(1)

    # JIT format: gather all validation/analytics/prerequisite/init/config state sections
    sections = re.findall(
        r"# STATE \d+[a-z]?:\s*(?:VALIDATE_\w+|ANALYTICS_\w+|PREREQUISITES\w*|INIT|CONFIG_\w+).*?\n(.*?)(?=\n# STATE|\Z)",
        content,
        re.DOTALL,
    )
    if sections:
        return "\n".join(sections)

    return None


def check_42_distribute_validates_analytics(distribute_content: str | None) -> list[str]:
    """Check 42: distribute.md preconditions validate stack.analytics."""
    errors: list[str] = []
    distribute_path = ".claude/commands/distribute.md"
    if not distribute_content:
        return errors

    preconditions_text = _find_preconditions_text(distribute_content)
    if preconditions_text:
        has_analytics_validation = bool(
            re.search(
                r"(?i)analytics.*(?:required|not present|not configured).*stop|"
                r"stack\.analytics.*(?:present|not|missing)|"
                r"(?:verify|check).*stack\.analytics|"
                r"analytics.*verif",
                preconditions_text,
                re.IGNORECASE,
            )
        )
        if not has_analytics_validation:
            errors.append(
                f"[42] {distribute_path}: preconditions section does not "
                f"validate that `stack.analytics` is present in experiment.yaml "
                f"before proceeding"
            )
    else:
        errors.append(
            f"[42] {distribute_path}: could not find preconditions section "
            f"(Step 1) to check analytics validation"
        )
    return errors


def check_43_distribute_validates_events_structure(distribute_content: str | None) -> list[str]:
    """Check 43: distribute.md preconditions validate events is a dict."""
    errors: list[str] = []
    distribute_path = ".claude/commands/distribute.md"
    if not distribute_content:
        return errors

    preconditions_text = _find_preconditions_text(distribute_content)
    if preconditions_text:
        has_events_validation = bool(
            re.search(
                r"`events`.*(?:dict|map|stop|malformed|missing)",
                preconditions_text,
                re.DOTALL,
            )
        )
        if not has_events_validation:
            has_events_validation = bool(
                re.search(
                    r"events.*(?:dict|map)",
                    preconditions_text,
                )
            )
        if not has_events_validation:
            errors.append(
                f"[43] {distribute_path}: preconditions section does not "
                f"validate that experiment/EVENTS.yaml `events` is a well-formed "
                f"dict before proceeding"
            )
    else:
        errors.append(
            f"[43] {distribute_path}: could not find preconditions section "
            f"(Step 1) to check events validation"
        )
    return errors


def check_44_bootstrap_validates_variants(bootstrap_content: str | None) -> list[str]:
    """Check 44: bootstrap.md Step 3 contains variant validation logic."""
    errors: list[str] = []
    bootstrap_path = ".claude/commands/bootstrap.md"
    if not bootstrap_content:
        return errors

    validate_section_match = re.search(
        r"##.*(?:Step 3|Validate (?:idea|experiment)\.yaml).*?\n(.*?)(?=\n## |\Z)",
        bootstrap_content,
        re.DOTALL,
    )
    if not validate_section_match:
        validate_section_match = re.search(
            r"(?i)#{1,2}\s*STATE\s+\d+[a-z]*:\s*VALIDATE_EXPERIMENT\s*\n(.*?)(?=\n---\s*\n#{1,2}\s*STATE|\n#\s*STATE|\Z)",
            bootstrap_content,
            re.DOTALL,
        )
    if validate_section_match:
        validate_text = validate_section_match.group(1)
        has_variant_validation = bool(
            re.search(
                r"variants?.*(?:present|list|at least 2|slug|valid)",
                validate_text,
                re.IGNORECASE,
            )
        )
        if not has_variant_validation:
            errors.append(
                f"[44] {bootstrap_path}: Step 3 (Validate experiment.yaml) does not "
                f"contain variant validation logic (expected mention of variants "
                f"with present/list/slug/at least 2)"
            )
        has_archetype_guard = bool(
            re.search(
                r"variants?.*archetype.*(?:NOT|not|!=).*web-app|web-app.*only.*variants?",
                validate_text,
                re.IGNORECASE,
            )
        )
        if not has_archetype_guard:
            errors.append(
                f"[44] {bootstrap_path}: Step 3 (Validate experiment.yaml) does not "
                f"restrict variants to web-app archetype (expected archetype guard "
                f"near variants validation)"
            )
    else:
        errors.append(
            f"[44] {bootstrap_path}: could not find 'Validate experiment.yaml' "
            f"section (Step 3) to check variant validation"
        )
    return errors


def check_46_iterate_verdict(iterate_content: str) -> list[str]:
    """Check 46: iterate.md contains verdict/GO/NO-GO with pace logic."""
    errors: list[str] = []
    if not re.search(r"(?i)verdict", iterate_content):
        errors.append("[46] iterate.md: missing experiment verdict section")
    if not re.search(r"(?i)NO.GO", iterate_content):
        errors.append("[46] iterate.md: missing GO/NO-GO verdict terminology")
    if not re.search(r"(?i)pace", iterate_content):
        errors.append("[46] iterate.md: missing pace-based progress metric")
    return errors


def check_47_deploy_dashboard_setup(deploy_content: str | None) -> list[str]:
    """Check 47: deploy.md contains analytics dashboard and scheduled digest setup."""
    errors: list[str] = []
    if not deploy_content:
        return errors
    has_dashboard = bool(re.search(r"(?i)dashboard", deploy_content))
    has_digest = bool(re.search(r"(?i)digest|subscription|subscribe", deploy_content))
    if not has_dashboard:
        errors.append("[47] deploy.md: missing analytics dashboard setup section")
    if not has_digest:
        errors.append("[47] deploy.md: missing scheduled digest/subscription setup")
    return errors


def check_48_iterate_next_checkin(iterate_content: str | None) -> list[str]:
    """Check 48: iterate.md contains Next Check-in schedule section."""
    errors: list[str] = []
    if not iterate_content:
        return errors
    has_checkin = bool(re.search(r"(?i)next.check.in", iterate_content))
    if not has_checkin:
        errors.append("[48] iterate.md: missing Next Check-in schedule section")
    return errors


def check_49_bootstrap_email_auth_database(bootstrap_content: str | None) -> list[str]:
    """Check 49: bootstrap validates email requires auth and database."""
    errors: list[str] = []
    if not bootstrap_content:
        return errors
    bs_prose = extract_prose(bootstrap_content)
    has_email_auth = bool(re.search(
        r"(?i)email.*auth.*present|email\s+requires.*auth", bs_prose
    ))
    has_email_db = bool(re.search(
        r"(?i)email.*database.*present|email\s+requires.*database", bs_prose
    ))
    if not has_email_auth:
        errors.append("[49] bootstrap.md: missing email-requires-auth dependency check")
    if not has_email_db:
        errors.append("[49] bootstrap.md: missing email-requires-database dependency check")
    return errors


def check_50_change_email_auth_database(change_content: str | None) -> list[str]:
    """Check 50: change validates email requires auth and database."""
    errors: list[str] = []
    if not change_content:
        return errors
    change_prose = extract_prose(change_content)
    has_email_ref = bool(re.search(r"(?i)adding\s+.*email|email.*stack", change_prose))
    if not has_email_ref:
        return errors
    has_email_auth_chk = bool(re.search(
        r"(?i)email.*auth.*present|email\s+requires.*auth", change_prose
    ))
    has_email_db_chk = bool(re.search(
        r"(?i)email.*database.*present|email\s+requires.*database", change_prose
    ))
    if not has_email_auth_chk:
        errors.append("[50] change.md: mentions adding email stack without auth-presence validation")
    if not has_email_db_chk:
        errors.append("[50] change.md: mentions adding email stack without database-presence validation")
    return errors


def check_57_change_production_precondition(change_content: str) -> list[str]:
    """Check 57: change.md validates stack.testing is present."""
    errors: list[str] = []
    # stack.testing should be validated unconditionally
    if not re.search(r"stack\.testing", change_content):
        errors.append(
            "[57] change.md: does not validate stack.testing is present"
        )
    return errors


def check_59_framework_archetype_compatibility(
    bootstrap_content: str, change_content: str
) -> list[str]:
    """Check 59: bootstrap.md and change.md validate framework-archetype compatibility."""
    errors: list[str] = []
    for label, content, path in [
        ("bootstrap.md", bootstrap_content, ".claude/commands/bootstrap.md"),
        ("change.md", change_content, ".claude/commands/change.md"),
    ]:
        # Must mention web-app requiring nextjs
        if not re.search(r"web-app.*requires.*nextjs|web-app.*nextjs", content, re.IGNORECASE):
            errors.append(
                f"[59] {path}: missing framework-archetype validation "
                f"(web-app requires nextjs)"
            )
        # Must mention cli requiring commander
        if not re.search(r"cli.*requires.*commander|cli.*commander", content, re.IGNORECASE):
            errors.append(
                f"[59] {path}: missing framework-archetype validation "
                f"(cli requires commander)"
            )
    return errors


def check_63_canonical_dependency_ref(
    bootstrap_content: str,
    change_content: str,
    procedure_contents: dict[str, str],
    agent_contents: dict[str, str],
) -> list[str]:
    """Check 63: bootstrap, change, change-feature procedure, and gate-keeper reference canonical dependency file."""
    errors: list[str] = []
    marker = "stack-dependency-validation.md"

    if marker not in bootstrap_content:
        errors.append(
            "[63] bootstrap.md (+ state files): missing reference to "
            "stack-dependency-validation.md (canonical dependency source)"
        )
    if marker not in change_content:
        errors.append(
            "[63] change.md (+ state files): missing reference to "
            "stack-dependency-validation.md (canonical dependency source)"
        )

    # change-feature.md is a procedure, not part of change_content
    change_feature_found = False
    for path, content in procedure_contents.items():
        if os.path.basename(path) == "change-feature.md":
            change_feature_found = True
            if marker not in content:
                errors.append(
                    f"[63] {path}: missing reference to "
                    "stack-dependency-validation.md (canonical dependency source)"
                )
            break
    if not change_feature_found:
        errors.append(
            "[63] .claude/procedures/change-feature.md not found in procedure_contents"
        )

    # gate-keeper.md is an agent file that enforces dependency validation
    gate_keeper_found = False
    for path, content in agent_contents.items():
        if os.path.basename(path) == "gate-keeper.md":
            gate_keeper_found = True
            if marker not in content:
                errors.append(
                    f"[63] {path}: missing reference to "
                    "stack-dependency-validation.md (canonical dependency source)"
                )
            break
    if not gate_keeper_found:
        errors.append(
            "[63] .claude/agents/gate-keeper.md not found in agent_contents"
        )

    return errors


def check_65_playwright_archetype_compatibility(
    bootstrap_content: str, change_content: str
) -> list[str]:
    """Check 65: bootstrap.md and change.md validate playwright-archetype compatibility."""
    errors: list[str] = []
    for label, content, path in [
        ("bootstrap.md", bootstrap_content, ".claude/commands/bootstrap.md"),
        ("change.md", change_content, ".claude/commands/change.md"),
    ]:
        # Must mention playwright incompatible with service/cli
        if not re.search(
            r"playwright.*(?:incompatible|not compatible).*(?:service|cli)"
            r"|(?:service|cli).*playwright.*stop"
            r"|testing.*playwright.*archetype.*(?:service|cli)",
            content,
            re.IGNORECASE,
        ):
            errors.append(
                f"[65] {path}: missing playwright-archetype validation "
                f"(playwright incompatible with service/cli)"
            )
    return errors
