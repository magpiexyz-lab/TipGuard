"""Stack dependency and configuration validation checks."""
import os
import re

from ._utils import (
    extract_code_blocks,
    extract_prose,
    parse_frontmatter,
    parse_frontmatter_from_content,
    OPTIONAL_CATEGORIES,
)

__all__ = [
    "check_9_env_loading_outside_nextjs",
    "check_11_hardcoded_provider_names",
    "check_14_stack_fallback_when_assumes_not_met",
    "check_23_testing_ci_payment_env_vars",
    "check_24_testing_noauth_fallback_ci",
    "check_27_auth_post_auth_redirects",
    "check_30_analytics_dashboard_navigation",
    "check_32_analytics_test_blocking",
    "check_34_conditional_files_frontmatter",
    "check_35_noauth_ci_database_env_vars",
    "check_51_track_server_event_signature",
    "check_52_track_server_event_awaited",
]

def check_9_env_loading_outside_nextjs(stack_contents: dict[str, str]) -> list[str]:
    """Check 9: Non-src templates that use process.env load env config."""
    errors: list[str] = []
    for sf, content in stack_contents.items():
        headers = [
            (m.start(), m.group(1))
            for m in re.finditer(r"###\s+`([^`]+)`", content)
        ]
        blocks = extract_code_blocks(content, {"ts", "tsx", "js"})

        file_has_env_loader = any(
            re.search(r"loadEnvConfig|dotenv|@next/env", b["code"])
            for b in blocks
        )

        for block in blocks:
            block_start = block["start_line"]
            closest_path = None
            for hdr_pos, path in headers:
                hdr_line = content[:hdr_pos].count("\n") + 1
                if hdr_line < block_start:
                    closest_path = path

            if not closest_path or closest_path.startswith("src/"):
                continue

            if "process.env." not in block["code"]:
                continue

            has_env_loading = bool(
                re.search(r"loadEnvConfig|dotenv|@next/env", block["code"])
            )
            if not has_env_loading and not file_has_env_loader:
                errors.append(
                    f"[9] {sf}: template for '{closest_path}' uses process.env "
                    f"but doesn't load env config (loadEnvConfig/dotenv/@next/env)"
                )
    return errors


def check_11_hardcoded_provider_names(stack_contents: dict[str, str]) -> list[str]:
    """Check 11: Code blocks using provider identifiers must have matching assumes."""
    errors: list[str] = []
    provider_identifiers: dict[str, str] = {
        "posthog": "analytics/posthog",
        "amplitude": "analytics/amplitude",
        "segment": "analytics/segment",
        "stripe": "payment/stripe",
        "@next/": "framework/nextjs",
    }
    for sf, content in stack_contents.items():
        fm = parse_frontmatter_from_content(content)
        if not fm:
            continue
        assumes = set(fm.get("assumes", []) or [])
        blocks = extract_code_blocks(content, {"ts", "tsx", "js", "jsx"})
        for block in blocks:
            code_lower = block["code"].lower()
            for identifier, category_value in provider_identifiers.items():
                if identifier in code_lower:
                    cat_val = sf.replace(".claude/stacks/", "").replace(".md", "")
                    if cat_val == category_value:
                        continue
                    if category_value not in assumes:
                        errors.append(
                            f"[11] {sf}:{block['start_line']}: code block uses "
                            f"'{identifier}' but '{category_value}' not in assumes frontmatter"
                        )
                        break
    return errors


def check_14_stack_fallback_when_assumes_not_met(stack_contents: dict[str, str]) -> list[str]:
    """Check 14: Stack files with optional assumes have fallback sections."""
    errors: list[str] = []
    FALLBACK_INDICATORS = re.compile(
        r"(?i)\b(?:fallback|no[- ]auth|without|not met|absent|simplified|"
        r"when.*(?:not|missing|absent)|anonymous)\b"
    )
    OPTIONAL_ASSUME_CATEGORIES = {"database", "auth", "payment", "testing"}
    # Shared stack categories (not per-service) that may assume a specific framework
    # but must work across different service runtimes
    SHARED_STACK_CATEGORIES = {"database", "auth", "analytics", "payment", "email", "ai", "telephony", "voice", "notifications", "project-management"}

    for sf, content in stack_contents.items():
        fm = parse_frontmatter(sf)
        if not fm:
            continue
        assumes = fm.get("assumes", []) or []
        if not assumes:
            continue

        # Determine the stack file's own category from its path
        # e.g., .claude/stacks/database/supabase.md -> "database"
        parts = sf.replace("\\", "/").split("/")
        file_category = ""
        if "stacks" in parts:
            idx = parts.index("stacks")
            if idx + 1 < len(parts):
                file_category = parts[idx + 1]

        # Framework assumes need fallbacks only for shared-category stack files
        # (per-service categories like ui are always paired with their framework)
        framework_assumes = [
            a for a in assumes if a.split("/")[0] == "framework"
        ]
        optional_assumes = [
            a for a in assumes
            if a.split("/")[0] in OPTIONAL_ASSUME_CATEGORIES
        ]
        if framework_assumes and file_category in SHARED_STACK_CATEGORIES:
            optional_assumes.extend(framework_assumes)

        if not optional_assumes:
            continue

        prose = extract_prose(content)
        if not FALLBACK_INDICATORS.search(prose):
            errors.append(
                f"[14] {sf}: has optional assumes {optional_assumes} but no "
                f"fallback section for when dependencies are absent"
            )
    return errors


def check_23_testing_ci_payment_env_vars(stack_contents: dict[str, str]) -> list[str]:
    """Check 23: Testing CI template includes payment env vars when ci.yml does."""
    errors: list[str] = []
    ci_yml_path = ".github/workflows/ci.yml"
    if not os.path.isfile(ci_yml_path):
        return errors

    with open(ci_yml_path) as f:
        ci_content = f.read()

    e2e_match = re.search(
        r"e2e:.*?(?=\n  \w+:|\Z)", ci_content, re.DOTALL
    )
    if not e2e_match:
        return errors

    e2e_section = e2e_match.group(0)
    stripe_vars_in_ci = re.findall(
        r"(STRIPE_\w+|NEXT_PUBLIC_STRIPE_\w+)", e2e_section
    )

    if not stripe_vars_in_ci:
        return errors

    for sf, content in stack_contents.items():
        if "/testing/" not in sf:
            continue
        ci_template_match = re.search(
            r"## CI Job Template\s*\n(.*?)(?=\n## |\Z)",
            content,
            re.DOTALL,
        )
        if ci_template_match:
            ci_template = ci_template_match.group(1)
            for var in stripe_vars_in_ci:
                if var not in ci_template:
                    errors.append(
                        f"[23] {sf}: CI Job Template missing '{var}' "
                        f"which is present in ci.yml e2e job"
                    )
    return errors


def check_24_testing_noauth_fallback_ci(stack_contents: dict[str, str]) -> list[str]:
    """Check 24: Testing stack no-auth fallback includes CI job template."""
    errors: list[str] = []
    for sf, content in stack_contents.items():
        if "/testing/" not in sf:
            continue
        fm = parse_frontmatter(sf)
        if not fm:
            continue

        fallback_match = re.search(
            r"## No-Auth Fallback\s*\n(.*?)(?=\n## [^#]|\Z)",
            content,
            re.DOTALL,
        )
        if fallback_match:
            fallback_section = fallback_match.group(1)
            yaml_blocks = re.findall(
                r"```yaml\s*\n(.*?)```", fallback_section, re.DOTALL
            )
            has_e2e_job = any("e2e:" in block for block in yaml_blocks)
            if not has_e2e_job:
                errors.append(
                    f"[24] {sf}: No-Auth Fallback section missing a CI job "
                    f"template (YAML code block with 'e2e:' job definition)"
                )
    return errors


def check_27_auth_post_auth_redirects(stack_contents: dict[str, str]) -> list[str]:
    """Check 27: Auth page templates contain router.push/redirect after auth success."""
    errors: list[str] = []
    for sf, content in stack_contents.items():
        if "/auth/" not in sf:
            continue

        blocks = extract_code_blocks(content, {"tsx", "jsx"})
        for block in blocks:
            code = block["code"]
            is_signup = "signUp" in code or "handleSignup" in code
            is_login = "signInWithPassword" in code or "handleLogin" in code
            if not is_signup and not is_login:
                continue

            page_type = "signup" if is_signup else "login"

            has_redirect = bool(
                re.search(r"router\.push\(|router\.replace\(|redirect\(", code)
            )
            has_only_todo = bool(
                re.search(r"//\s*TODO.*redirect", code, re.IGNORECASE)
            )

            if not has_redirect or has_only_todo:
                errors.append(
                    f"[27] {sf}:{block['start_line']}: {page_type} page template "
                    f"has no post-auth redirect (router.push/redirect) — only a "
                    f"TODO comment"
                    if has_only_todo
                    else f"[27] {sf}:{block['start_line']}: {page_type} page "
                    f"template missing post-auth redirect (router.push/redirect)"
                )
    return errors


def check_30_analytics_dashboard_navigation(
    stack_files: list[str],
    stack_contents: dict[str, str],
) -> list[str]:
    """Check 30: Analytics stack files include Dashboard Navigation section."""
    errors: list[str] = []
    analytics_stack_files = [sf for sf in stack_files if "/analytics/" in sf]

    for sf in analytics_stack_files:
        content = stack_contents[sf]
        has_dashboard_nav = bool(
            re.search(r"(?i)^## Dashboard Navigation", content, re.MULTILINE)
        )
        if not has_dashboard_nav:
            errors.append(
                f"[30] {sf}: analytics stack file missing required "
                f"'## Dashboard Navigation' section (needed by /iterate skill)"
            )
    return errors


def check_32_analytics_test_blocking(
    stack_files: list[str],
    stack_contents: dict[str, str],
) -> list[str]:
    """Check 32: Analytics stack files include Test Blocking section."""
    errors: list[str] = []
    analytics_stack_files = [sf for sf in stack_files if "/analytics/" in sf]

    for sf in analytics_stack_files:
        content = stack_contents[sf]
        has_test_blocking = bool(
            re.search(r"(?i)^## Test Blocking", content, re.MULTILINE)
        )
        if not has_test_blocking:
            errors.append(
                f"[32] {sf}: analytics stack file missing required "
                f"'## Test Blocking' section (needed by testing stack's "
                f"blockAnalytics helper)"
            )
    return errors


def check_34_conditional_files_frontmatter(stack_contents: dict[str, str]) -> list[str]:
    """Check 34: Fallback stacks annotate conditional files in frontmatter."""
    errors: list[str] = []
    for sf, content in stack_contents.items():
        fm = parse_frontmatter(sf)
        if not fm:
            continue

        has_fallback = bool(
            re.search(r"(?i)## No-Auth Fallback|## .*Fallback", content)
        )
        if not has_fallback:
            continue

        fm_files = fm.get("files", []) or []
        if not fm_files:
            continue

        fm_match = re.match(r"^---\n(.*?\n)---", content, re.DOTALL)
        if not fm_match:
            continue
        fm_text = fm_match.group(1)
        files_block_match = re.search(
            r"^files:.*(?:\n  - .*)*", fm_text, re.MULTILINE
        )
        if not files_block_match:
            continue
        files_block = files_block_match.group(0)

        fallback_start = re.search(r"(?i)## No-Auth Fallback|## .*Fallback", content)
        if not fallback_start:
            continue

        pre_fallback = content[:fallback_start.start()]
        post_fallback = content[fallback_start.start():]

        pre_headers = set(re.findall(r"###\s+`([^`]+)`", pre_fallback))
        post_headers = set(re.findall(r"###\s+`([^`]+)`", post_fallback))

        full_only_headers = pre_headers - post_headers

        assumes_dependent_files = [f for f in fm_files if f in full_only_headers]

        if assumes_dependent_files:
            unannotated = []
            for dep_file in assumes_dependent_files:
                entry_match = re.search(
                    rf"^\s*-\s+{re.escape(dep_file)}.*#\s*conditional",
                    files_block,
                    re.MULTILINE,
                )
                if not entry_match:
                    unannotated.append(dep_file)
            if unannotated and "# conditional" not in files_block.split("\n")[0]:
                errors.append(
                    f"[34] {sf}: files frontmatter lists assumes-dependent files "
                    f"{unannotated} but lacks '# conditional' annotation"
                )
    return errors


def check_35_noauth_ci_database_env_vars(stack_contents: dict[str, str]) -> list[str]:
    """Check 35: No-auth CI template includes database placeholder env vars."""
    errors: list[str] = []
    for sf, content in stack_contents.items():
        if "/testing/" not in sf:
            continue

        full_ci_match = re.search(
            r"## CI Job Template\s*\n(.*?)(?=\n## |\Z)",
            content,
            re.DOTALL,
        )
        if not full_ci_match:
            continue

        noauth_ci_match = re.search(
            r"### No-Auth CI Job Template\s*\n(.*?)(?=\n### |\n## |\Z)",
            content,
            re.DOTALL,
        )
        if not noauth_ci_match:
            continue

        full_ci_text = full_ci_match.group(1)
        noauth_ci_text = noauth_ci_match.group(1)

        db_env_vars = re.findall(
            r"(NEXT_PUBLIC_SUPABASE_URL|NEXT_PUBLIC_SUPABASE_ANON_KEY)",
            full_ci_text,
        )

        if db_env_vars:
            for var in set(db_env_vars):
                if var not in noauth_ci_text:
                    errors.append(
                        f"[35] {sf}: No-Auth CI Job Template missing database "
                        f"env var '{var}' which is present in full-auth CI "
                        f"Job Template (should be commented or uncommented)"
                    )
    return errors


def check_51_track_server_event_signature(stack_contents: dict[str, str]) -> list[str]:
    """Check 51: trackServerEvent calls pass string as distinctId, not object."""
    errors: list[str] = []
    analytics_server_sig = None
    for sf in sorted(f for f in stack_contents if "/analytics/" in f):
        content = stack_contents[sf]
        if re.search(r"trackServerEvent\s*\(\s*\n?\s*event:\s*string,\s*\n?\s*distinctId:\s*string", content):
            analytics_server_sig = sf
            break

    if not analytics_server_sig:
        return errors

    for sf, content in stack_contents.items():
        code_blocks = extract_code_blocks(content, {"ts", "tsx", "typescript"})
        for block in code_blocks:
            bad_calls = re.findall(
                r'trackServerEvent\s*\(\s*"[^"]+"\s*,\s*\{',
                block["code"],
            )
            for call in bad_calls:
                errors.append(
                    f"[51] {sf}: trackServerEvent call passes object as distinctId "
                    f"(expected string) near line {block['start_line']}: {call.strip()}"
                )
    return errors


def check_52_track_server_event_awaited(stack_contents: dict[str, str]) -> list[str]:
    """Check 52: trackServerEvent calls are awaited in stack file code blocks."""
    errors: list[str] = []
    analytics_server_sig = None
    for sf in sorted(f for f in stack_contents if "/analytics/" in f):
        content = stack_contents[sf]
        if re.search(r"trackServerEvent\s*\(\s*\n?\s*event:\s*string,\s*\n?\s*distinctId:\s*string", content):
            analytics_server_sig = sf
            break

    if not analytics_server_sig:
        return errors

    for sf, content in stack_contents.items():
        code_blocks = extract_code_blocks(content, {"ts", "tsx", "typescript"})
        for block in code_blocks:
            unwaited = re.findall(
                r"^(?!.*\bawait\b)(?!.*\bfunction\b).*\btrackServerEvent\s*\(",
                block["code"],
                re.MULTILINE,
            )
            for call in unwaited:
                errors.append(
                    f"[52] {sf}: trackServerEvent call without await "
                    f"near line {block['start_line']}: {call.strip()}"
                )
    return errors
