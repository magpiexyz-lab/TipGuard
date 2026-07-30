"""Fixture validation checks."""
import glob
import os
import re
import yaml

from ._utils import (
    extract_code_blocks,
    extract_prose,
    parse_frontmatter,
    get_required_experiment_fields,
    OPTIONAL_CATEGORIES,
)

__all__ = [
    "check_1_import_completeness",
    "check_3_fixture_validation",
    "check_7_fixture_stack_coverage",
    "check_13_fixture_branching_coverage",
    "check_19_fixture_testing_partial_assumes",
]

BUILTIN_COMPONENTS = {"Fragment", "Suspense", "StrictMode"}


def check_1_import_completeness(stack_contents: dict[str, str]) -> list[str]:
    """Check 1: JSX components used in code blocks have matching imports."""
    errors: list[str] = []
    for sf, content in stack_contents.items():
        blocks = extract_code_blocks(content, {"tsx", "jsx"})
        for block in blocks:
            code = block["code"]
            # Match JSX component tags only — not TypeScript generics.
            # JSX `<X>` is preceded by `(`, whitespace, `>`, `=`, `{`, `,`, or
            # line start. TS generics `Type<X>` are preceded by a word char
            # (the identifier immediately before `<`). Negative lookbehind on
            # `[a-zA-Z0-9_]` excludes generics like `SyntheticEvent<HTMLFormElement>`.
            used_components = set(re.findall(r"(?<![a-zA-Z0-9_])<([A-Z][a-zA-Z]+)", code))
            used_components -= BUILTIN_COMPONENTS

            imported: set[str] = set()
            for m in re.finditer(
                r"import\s+(?:type\s+)?(?:\{([^}]+)\}|(\w+))\s+from", code
            ):
                if m.group(1):
                    for name in m.group(1).split(","):
                        name = name.strip()
                        if " as " in name:
                            name = name.split(" as ")[1].strip()
                        if name:
                            imported.add(name)
                if m.group(2):
                    imported.add(m.group(2))

            locally_defined: set[str] = set()
            for m in re.finditer(r"\bfunction\s+([A-Z][a-zA-Z]+)\s*\(", code):
                locally_defined.add(m.group(1))
            for m in re.finditer(r"\b(?:const|let)\s+([A-Z][a-zA-Z]+)\s*=", code):
                locally_defined.add(m.group(1))

            missing = used_components - imported - locally_defined
            for comp in sorted(missing):
                errors.append(
                    f"[1] {sf}:{block['start_line']}: JSX component <{comp}> used but "
                    f"not imported in code block"
                )
    return errors


def check_3_fixture_validation(
    fixture_dir: str,
    get_required_fields_fn,
) -> tuple[list[str], dict[str, str]]:
    """Check 3: Fixture files are structurally correct (inline version with file I/O).

    Returns (errors, fixture_type_map).
    """
    errors: list[str] = []
    fixture_type_map: dict[str, str] = {}

    if not os.path.isdir(fixture_dir):
        return errors, fixture_type_map

    fixture_files = sorted(glob.glob(os.path.join(fixture_dir, "*.yaml")))

    if not fixture_files:
        errors.append(f"[3] {fixture_dir}: no fixture files found")
        return errors, fixture_type_map

    for ff in fixture_files:
        with open(ff) as f:
            try:
                fixture = yaml.safe_load(f)
            except yaml.YAMLError as e:
                errors.append(f"[3] {ff}: invalid YAML: {e}")
                continue

        if not isinstance(fixture, dict):
            errors.append(f"[3] {ff}: fixture must be a YAML mapping")
            continue

        for key in ["experiment", "events", "assertions"]:
            if key not in fixture:
                errors.append(f"[3] {ff}: missing required key '{key}'")

        experiment = fixture.get("experiment", {})
        if not isinstance(experiment, dict):
            errors.append(f"[3] {ff}: 'experiment' must be a mapping")
            continue

        name = experiment.get("name", "")
        if not re.match(r"^[a-z][a-z0-9-]*$", str(name)):
            errors.append(
                f"[3] {ff}: experiment.name '{name}' must be lowercase, start with "
                f"a letter, and use only a-z, 0-9, hyphens"
            )

        fixture_type = experiment.get("type", "web-app")
        fixture_type_map[ff] = fixture_type
        fixture_required = get_required_fields_fn(fixture_type)

        for field in fixture_required:
            if not experiment.get(field):
                errors.append(f"[3] {ff}: experiment.{field} is missing or empty")

        if "golden_path" in fixture_required:
            golden_path = experiment.get("golden_path", [])
            if isinstance(golden_path, list):
                has_landing = any(
                    isinstance(entry, dict) and entry.get("page") == "landing"
                    for entry in golden_path
                )
                if not has_landing:
                    errors.append(f"[3] {ff}: experiment.golden_path must include a 'landing' entry")
                pages = [
                    {"name": entry.get("page")}
                    for entry in golden_path
                    if isinstance(entry, dict) and entry.get("page")
                ]
                seen_pages: set[str] = set()
                unique_pages: list[dict] = []
                for p in pages:
                    if p["name"] not in seen_pages:
                        seen_pages.add(p["name"])
                        unique_pages.append(p)
                pages = unique_pages
            else:
                pages = []
        elif "pages" in fixture_required:
            pages = experiment.get("pages", [])
            if isinstance(pages, list):
                has_landing = any(
                    isinstance(p, dict) and p.get("name") == "landing" for p in pages
                )
                if not has_landing:
                    errors.append(f"[3] {ff}: experiment.pages must include a 'landing' entry")
        else:
            pages = []

        assertions = fixture.get("assertions", {})
        if isinstance(assertions, dict):
            stack = experiment.get("stack", {})
            has_payment = "payment" in stack if isinstance(stack, dict) else False
            payment_required = assertions.get("payment_events_required", False)
            if payment_required and not has_payment:
                errors.append(
                    f"[3] {ff}: assertions.payment_events_required is true but "
                    f"experiment.stack has no payment entry"
                )

            skippable = assertions.get("skippable_events", [])
            if "golden_path" in fixture_required or "pages" in fixture_required:
                has_signup = False
                if isinstance(pages, list):
                    has_signup = any(
                        isinstance(p, dict) and p.get("name") == "signup"
                        for p in pages
                    )
                if not has_signup:
                    for ev in ["signup_start", "signup_complete"]:
                        if ev not in skippable:
                            errors.append(
                                f"[3] {ff}: no signup page but '{ev}' not in "
                                f"assertions.skippable_events"
                            )
            else:
                fixture_stack = experiment.get("stack", {})
                effective_surface = fixture_stack.get("surface")
                if effective_surface is None:
                    effective_surface = "co-located" if "hosting" in fixture_stack else "detached"
                non_webapp_skippable = ["signup_start", "signup_complete"]
                if effective_surface == "none":
                    non_webapp_skippable.append("visit_landing")
                for ev in non_webapp_skippable:
                    if ev not in skippable:
                        errors.append(
                            f"[3] {ff}: {fixture_type} type but '{ev}' not in "
                            f"assertions.skippable_events"
                        )

            min_pages = assertions.get("min_pages")
            if min_pages is not None and isinstance(pages, list):
                if len(pages) < min_pages:
                    errors.append(
                        f"[3] {ff}: experiment has {len(pages)} page(s) but "
                        f"assertions.min_pages is {min_pages}"
                    )

            endpoints = experiment.get("endpoints", [])
            min_endpoints = assertions.get("min_endpoints")
            if min_endpoints is not None and isinstance(endpoints, list):
                if len(endpoints) < min_endpoints:
                    errors.append(
                        f"[3] {ff}: experiment has {len(endpoints)} endpoint(s) but "
                        f"assertions.min_endpoints is {min_endpoints}"
                    )

            commands = experiment.get("commands", [])
            min_commands = assertions.get("min_commands")
            if min_commands is not None and isinstance(commands, list):
                if len(commands) < min_commands:
                    errors.append(
                        f"[3] {ff}: experiment has {len(commands)} command(s) but "
                        f"assertions.min_commands is {min_commands}"
                    )

            experiment_variants = experiment.get("variants")
            has_variants_assertion = assertions.get("has_variants")
            variant_count_assertion = assertions.get("variant_count")

            if experiment_variants is not None:
                if not isinstance(experiment_variants, list):
                    errors.append(f"[3] {ff}: experiment.variants must be a list")
                elif len(experiment_variants) < 2:
                    errors.append(
                        f"[3] {ff}: experiment.variants must have at least 2 entries"
                    )
                else:
                    variant_slugs_seen: set[str] = set()
                    for vi, vv in enumerate(experiment_variants):
                        if not isinstance(vv, dict):
                            errors.append(
                                f"[3] {ff}: experiment.variants[{vi}] must be a mapping"
                            )
                            continue
                        for vfield in [
                            "slug", "headline", "subheadline", "cta", "pain_points"
                        ]:
                            if not vv.get(vfield):
                                errors.append(
                                    f"[3] {ff}: experiment.variants[{vi}].{vfield} "
                                    f"is missing or empty"
                                )
                        vslug = vv.get("slug", "")
                        if vslug in variant_slugs_seen:
                            errors.append(
                                f"[3] {ff}: duplicate variant slug: {vslug}"
                            )
                        variant_slugs_seen.add(vslug)
                        vpp = vv.get("pain_points", [])
                        if isinstance(vpp, list) and len(vpp) != 3:
                            errors.append(
                                f"[3] {ff}: experiment.variants[{vi}].pain_points "
                                f"must have exactly 3 items"
                            )

                if has_variants_assertion is not None and not has_variants_assertion:
                    errors.append(
                        f"[3] {ff}: experiment has variants but "
                        f"assertions.has_variants is false"
                    )

                if (
                    variant_count_assertion is not None
                    and isinstance(experiment_variants, list)
                    and len(experiment_variants) != variant_count_assertion
                ):
                    errors.append(
                        f"[3] {ff}: experiment has {len(experiment_variants)} variant(s) "
                        f"but assertions.variant_count is "
                        f"{variant_count_assertion}"
                    )
            else:
                if has_variants_assertion:
                    errors.append(
                        f"[3] {ff}: assertions.has_variants is true but "
                        f"experiment has no variants field"
                    )

        events = fixture.get("events", {})
        if isinstance(events, dict):
            if not has_payment:
                for ename, edef in events.items():
                    if isinstance(edef, dict) and "payment" in (edef.get("requires") or []):
                        errors.append(
                            f"[3] {ff}: events.{ename} has requires: [payment] but "
                            f"experiment.stack has no payment entry"
                        )

    return errors, fixture_type_map


def check_7_fixture_stack_coverage(
    fixture_dir: str,
    stack_files: list[str],
    fixture_type_map: dict[str, str],
    bootstrap_content: str | None,
) -> list[str]:
    """Check 7: Every stack file is covered by at least one fixture (inline version with file I/O)."""
    errors: list[str] = []
    if not os.path.isdir(fixture_dir):
        return errors

    fixture_files_cov = sorted(glob.glob(os.path.join(fixture_dir, "*.yaml")))

    stack_pairs = set()
    for sf in stack_files:
        pair = sf.replace(".claude/stacks/", "").replace(".md", "")
        if pair.startswith("distribution/") or pair.startswith("ai/"):
            continue
        stack_pairs.add(pair)

    fixture_stack_coverage: dict[str, set[str]] = {}
    all_fixture_stacks: set[str] = set()

    SERVICE_KEY_TO_DIR = {
        "runtime": "framework",
        "hosting": "hosting",
        "ui": "ui",
        "testing": "testing",
    }

    for ff in fixture_files_cov:
        with open(ff) as f:
            try:
                fixture = yaml.safe_load(f)
            except yaml.YAMLError:
                continue
        if not isinstance(fixture, dict):
            continue
        experiment = fixture.get("experiment", {})
        stack = experiment.get("stack", {})
        if isinstance(stack, dict):
            pairs: set[str] = set()
            for k, v in stack.items():
                if k == "services":
                    continue
                pairs.add(f"{k}/{v}")
            services = stack.get("services", [])
            if isinstance(services, list):
                for svc in services:
                    if isinstance(svc, dict):
                        for svc_key, stack_dir in SERVICE_KEY_TO_DIR.items():
                            if svc_key in svc:
                                pairs.add(f"{stack_dir}/{svc[svc_key]}")
            fixture_stack_coverage[ff] = pairs
            all_fixture_stacks |= pairs

    for pair in sorted(stack_pairs):
        if pair not in all_fixture_stacks:
            errors.append(
                f"[7] Stack file .claude/stacks/{pair}.md has no "
                f"fixture coverage in {fixture_dir}/"
            )

    if bootstrap_content:
        always_match = re.search(
            r"always:\s*([^;)]+?)(?:\)|;|$)", bootstrap_content
        )
        if always_match:
            mandatory_cats = [
                c.strip().rstrip(",")
                for c in always_match.group(1).split(",")
                if c.strip()
            ]
            for ff, pairs in fixture_stack_coverage.items():
                fixture_cats = {p.split("/")[0] for p in pairs}
                ft = fixture_type_map.get(ff, "web-app")
                excluded: set[str] = set()
                arch_path = f".claude/archetypes/{ft}.md"
                if os.path.isfile(arch_path):
                    afm = parse_frontmatter(arch_path)
                    if afm:
                        excluded = set(afm.get("excluded_stacks", []))
                for cat in mandatory_cats:
                    if cat in excluded:
                        continue
                    if cat not in fixture_cats:
                        errors.append(
                            f"[7] {ff}: missing mandatory stack category "
                            f"'{cat}' (must be in all fixtures)"
                        )
    return errors


def check_13_fixture_branching_coverage(
    fixture_dir: str,
    stack_contents: dict[str, str],
) -> list[str]:
    """Check 13: Conditional stack paths have fixture coverage."""
    errors: list[str] = []
    if not os.path.isdir(fixture_dir):
        return errors

    fixture_files_branch = sorted(glob.glob(os.path.join(fixture_dir, "*.yaml")))

    fixture_stacks_13: list[dict[str, str]] = []
    for ff in fixture_files_branch:
        with open(ff) as f:
            try:
                fixture = yaml.safe_load(f)
            except yaml.YAMLError:
                continue
        if not isinstance(fixture, dict):
            continue
        experiment = fixture.get("experiment", {})
        stack = experiment.get("stack", {})
        if isinstance(stack, dict):
            fixture_stacks_13.append(stack)

    for sf, content in stack_contents.items():
        prose = extract_prose(content)
        cat_val = sf.replace(".claude/stacks/", "").replace(".md", "")
        category = cat_val.split("/")[0]

        for m in re.finditer(
            r"(?i)when\s+`?stack\.(\w+)`?\s+is\s+NOT\s+(\w+)",
            prose,
        ):
            dep_category = m.group(1)
            dep_value = m.group(2)

            has_not_branch = any(
                dep_category not in fs or fs.get(dep_category) != dep_value
                for fs in fixture_stacks_13
                if category in fs
            )

            if not has_not_branch:
                errors.append(
                    f"[13] {sf}: has conditional for 'stack.{dep_category} "
                    f"is NOT {dep_value}' but no fixture exercises this branch"
                )
    return errors


def check_19_fixture_testing_partial_assumes(
    fixture_dir: str,
    stack_files: list[str],
) -> list[str]:
    """Check 19: Testing fixtures cover partial-met assumes scenario."""
    errors: list[str] = []
    if not os.path.isdir(fixture_dir):
        return errors

    fixture_files_testing = sorted(glob.glob(os.path.join(fixture_dir, "*.yaml")))

    testing_assumes_categories: set[str] = set()
    for sf in stack_files:
        if "/testing/" in sf:
            fm_t = parse_frontmatter(sf)
            if fm_t:
                for a in fm_t.get("assumes", []) or []:
                    testing_assumes_categories.add(a.split("/")[0])

    if not testing_assumes_categories:
        return errors

    optional_testing_assumes = testing_assumes_categories & OPTIONAL_CATEGORIES

    testing_fixtures_all_met: list[str] = []
    testing_fixtures_none_met: list[str] = []
    testing_fixtures_partial_met: list[str] = []

    for ff in fixture_files_testing:
        with open(ff) as f:
            try:
                fixture = yaml.safe_load(f)
            except yaml.YAMLError:
                continue
        if not isinstance(fixture, dict):
            continue
        experiment = fixture.get("experiment", {})
        stack = experiment.get("stack", {})
        if not isinstance(stack, dict):
            continue

        if "testing" not in stack:
            continue

        met = {
            cat for cat in optional_testing_assumes
            if cat in stack
        }

        if met == optional_testing_assumes:
            testing_fixtures_all_met.append(ff)
        elif not met:
            testing_fixtures_none_met.append(ff)
        else:
            testing_fixtures_partial_met.append(ff)

    if testing_fixtures_all_met and testing_fixtures_none_met and not testing_fixtures_partial_met:
        errors.append(
            f"[19] tests/fixtures/: testing fixtures only cover "
            f"all-met and none-met assumes scenarios without at least "
            f"one partial-met fixture (e.g., auth present, database absent)"
        )
    return errors
