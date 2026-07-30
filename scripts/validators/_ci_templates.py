"""CI template and Makefile validation checks."""
import json
import re

from ._utils import (
    parse_makefile_targets,
)

__all__ = [
    "check_2_makefile_target_guards",
    "check_6_required_fields_consistency",
    "check_10_validate_warning_differentiation",
    "check_15_makefile_deploy_hosting_guard",
    "check_20_makefile_help_no_env_vars",
]

def check_2_makefile_target_guards(makefile_content: str) -> list[str]:
    """Check 2: Makefile npm/node targets guard on package.json."""
    errors: list[str] = []
    if not makefile_content:
        return errors

    EXEMPT_TARGETS = {
        "validate", "clean", "clean-all", "help",
        "test-e2e", "supabase-start", "supabase-stop",
    }

    targets = parse_makefile_targets(makefile_content)

    for target_name, recipe in targets.items():
        if target_name in EXEMPT_TARGETS:
            continue
        if target_name.startswith("."):
            continue

        uses_npm = bool(re.search(r"\bnpm\b|\bnpx\b|\bnode\b", recipe))
        if not uses_npm:
            continue

        has_guard = bool(
            re.search(r"if\s+\[.*package\.json", recipe)
            or re.search(r"test\s+-f\s+package\.json", recipe)
            or re.search(r"-f\s+package\.json", recipe)
            or re.search(r"-e\s+package\.json", recipe)
        )

        if not has_guard:
            line_num = makefile_content[
                : makefile_content.index(f"{target_name}:")
            ].count("\n") + 1
            errors.append(
                f"[2] Makefile:{line_num}: target '{target_name}' uses "
                f"npm/node but has no package.json guard"
            )
    return errors


def check_6_required_fields_consistency(
    makefile_content: str | None,
    required_experiment_fields: list[str],
) -> list[str]:
    """Check 6: Makefile and validator agree on required fields."""
    errors: list[str] = []
    if not makefile_content:
        return errors
    mk_required_match = re.search(
        r"required\s*=\s*\[([^\]]+)\]", makefile_content
    )
    if not mk_required_match:
        return errors
    mk_fields_raw = mk_required_match.group(1)
    mk_fields = [
        f.strip().strip("'\"")
        for f in mk_fields_raw.split(",")
        if f.strip()
    ]
    mk_fields_set = set(mk_fields)
    sem_fields_set = set(required_experiment_fields)

    for field in sorted(mk_fields_set - sem_fields_set):
        errors.append(
            f"[6] Makefile validate has required field '{field}' "
            f"missing from validate-semantics.py"
        )
    for field in sorted(sem_fields_set - mk_fields_set):
        errors.append(
            f"[6] validate-semantics.py has required field '{field}' "
            f"missing from Makefile validate"
        )
    return errors


def check_10_validate_warning_differentiation(
    makefile_content: str | None,
    targets: dict[str, str],
) -> list[str]:
    """Check 10: Makefile validate success message varies with warnings."""
    errors: list[str] = []
    if not makefile_content:
        return errors
    validate_recipe = targets.get("validate", "")

    has_conditional = bool(
        re.search(r"(?i)WARN|warning.*if|if.*warn", validate_recipe)
    )
    has_passed_message = bool(
        re.search(r"Validation passed", validate_recipe)
    )

    if has_passed_message and not has_conditional:
        errors.append(
            f"[10] Makefile validate: success message is unconditional — "
            f"should differentiate between clean pass and pass with warnings"
        )
    return errors


def check_15_makefile_deploy_hosting_guard(
    makefile_content: str | None,
    targets: dict[str, str],
) -> list[str]:
    """Check 15: Makefile deploy target checks hosting stack."""
    errors: list[str] = []
    if not makefile_content:
        return errors
    deploy_recipe = targets.get("deploy", "")

    provider_commands = {
        "vercel": r"\bvercel\b",
        "netlify": r"\bnetlify\b",
        "fly": r"\bfly\b|\bflyctl\b",
    }

    for provider, pattern in provider_commands.items():
        if re.search(pattern, deploy_recipe):
            has_hosting_guard = bool(
                re.search(
                    r"(?:HOSTING|hosting|stack.*hosting)",
                    deploy_recipe,
                )
            )
            if not has_hosting_guard:
                line_num = makefile_content[
                    : makefile_content.index("deploy:")
                ].count("\n") + 1
                errors.append(
                    f"[15] Makefile:{line_num}: deploy target uses "
                    f"'{provider}' command without hosting stack guard"
                )
    return errors


def check_20_makefile_help_no_env_vars(makefile_content: str | None) -> list[str]:
    """Check 20: Makefile help comments don't hardcode optional env vars."""
    errors: list[str] = []
    if not makefile_content:
        return errors

    for m in re.finditer(r"^([a-zA-Z0-9_-]+):\s*.*?##\s*(.+)$", makefile_content, re.MULTILINE):
        target_name_20 = m.group(1)
        help_text = m.group(2)

        env_vars_in_help = re.findall(
            r"\b(?:NEXT_PUBLIC_[A-Z_]+|[A-Z][A-Z_]{3,}(?:_KEY|_URL|_ID|_SECRET|_TOKEN|_ANON_KEY|_ROLE_KEY))\b",
            help_text,
        )
        if env_vars_in_help:
            line_num = makefile_content[: m.start()].count("\n") + 1
            errors.append(
                f"[20] Makefile:{line_num}: target '{target_name_20}' help "
                f"text contains environment variable name(s) "
                f"{env_vars_in_help} that are conditional on stack configuration"
            )
    return errors
