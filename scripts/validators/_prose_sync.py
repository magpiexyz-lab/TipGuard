"""Prose-frontmatter synchronization validation checks."""
import re

from ._utils import (
    parse_frontmatter,
    parse_frontmatter_from_content,
    extract_code_blocks,
    extract_prose,
    OPTIONAL_CATEGORIES,
    parse_makefile_targets,
)

__all__ = [
    "check_4_frontmatter_content_sync",
    "check_17_env_vars_prose_frontmatter_sync",
    "check_21_packages_prose_frontmatter_sync",
    "check_26_testing_env_frontmatter_assumes",
    "check_64_conditional_packages_prose_sync",
]

def check_4_frontmatter_content_sync(
    stack_files: list[str],
    stack_contents: dict[str, str],
    makefile_content: str | None,
) -> list[str]:
    """Check 4: Code block headers match frontmatter files; Makefile clean matches clean frontmatter."""
    errors: list[str] = []

    # 4a: Code block section headers
    for sf in stack_files:
        content = stack_contents.get(sf, "")
        fm = parse_frontmatter_from_content(content)
        if not fm:
            continue
        fm_files = set(fm.get("files", []) or [])
        header_paths = set(re.findall(r"###\s+`([^`]+)`", content))
        for path in sorted(header_paths):
            if path not in fm_files:
                errors.append(
                    f"[4] {sf}: code block header path '{path}' not listed in frontmatter 'files'"
                )

    # 4b: Makefile clean lines
    if makefile_content:
        clean_match = re.search(
            r"^clean:.*?\n((?:\t.*\n)*)", makefile_content, re.MULTILINE
        )
        if clean_match:
            clean_recipe = clean_match.group(1)
            makefile_clean_items: dict[str, set[str]] = {}
            for line in clean_recipe.splitlines():
                line_s = line.strip()
                if not line_s:
                    continue
                tag_match = re.search(r"#\s+(\w+/\w+)\s*$", line_s)
                if not tag_match:
                    continue
                tag = tag_match.group(1)
                line_body = line_s[: tag_match.start()].strip()
                rm_match = re.match(r"rm\s+(?:-rf|-f)\s+(.*)", line_body)
                if rm_match:
                    items = rm_match.group(1).split()
                    makefile_clean_items.setdefault(tag, set()).update(items)

            for sf in stack_files:
                content = stack_contents.get(sf, "")
                fm = parse_frontmatter_from_content(content)
                if not fm or "clean" not in fm:
                    continue
                cat_val = sf.replace(".claude/stacks/", "").replace(".md", "")
                clean_fm = fm.get("clean", {}) or {}
                fm_clean_files = set(clean_fm.get("files", []) or [])
                fm_clean_dirs = set(clean_fm.get("dirs", []) or [])
                fm_all = fm_clean_files | fm_clean_dirs
                if not fm_all:
                    continue
                if cat_val not in makefile_clean_items:
                    errors.append(
                        f"[4] {sf}: clean frontmatter has entries but no "
                        f"Makefile clean line tagged '# {cat_val}'"
                    )
                    continue
                mk_items = makefile_clean_items[cat_val]
                for item in sorted(fm_all - mk_items):
                    errors.append(
                        f"[4] {sf}: clean item '{item}' not in Makefile clean target (# {cat_val})"
                    )
                for item in sorted(mk_items - fm_all):
                    errors.append(
                        f"[4] Makefile clean (# {cat_val}): item '{item}' not in "
                        f"{sf} clean frontmatter"
                    )
    return errors


def check_17_env_vars_prose_frontmatter_sync(stack_contents: dict[str, str]) -> list[str]:
    """Check 17: Env vars in prose match frontmatter declarations."""
    errors: list[str] = []
    env_var_pattern = re.compile(
        r"`?(NEXT_PUBLIC_[A-Z0-9_]+|[A-Z][A-Z0-9_]{3,}(?:_KEY|_URL|_ID|_SECRET|_TOKEN|_ANON_KEY|_ROLE_KEY))`?"
    )
    for sf, content in stack_contents.items():
        fm = parse_frontmatter_from_content(content)
        if not fm:
            continue
        env_section = fm.get("env", {}) or {}
        fm_server = set(env_section.get("server", []) or [])
        fm_client = set(env_section.get("client", []) or [])
        fm_all_env = fm_server | fm_client

        env_section_match = re.search(
            r"##\s+Environment Variables\s*\n(.*?)(?=\n##\s|\Z)",
            content,
            re.DOTALL,
        )
        if not env_section_match:
            continue

        env_prose = env_section_match.group(1)
        env_prose_no_code = re.sub(r"```.*?```", "", env_prose, flags=re.DOTALL)
        prose_env_vars: set[str] = set()
        for m in env_var_pattern.finditer(env_prose_no_code):
            var_name = m.group(1) or m.group(0).strip("`")
            prose_env_vars.add(var_name)

        for var in sorted(prose_env_vars - fm_all_env):
            line_num = content[: env_section_match.start()].count("\n") + 1
            errors.append(
                f"[17] {sf}:{line_num}: Environment Variables prose mentions "
                f"'{var}' but it's not in frontmatter env.server or env.client"
            )
    return errors


def check_21_packages_prose_frontmatter_sync(stack_contents: dict[str, str]) -> list[str]:
    """Check 21: Packages in prose match frontmatter declarations."""
    errors: list[str] = []
    package_install_pattern = re.compile(r"^npm install\s+(.+)$", re.MULTILINE)

    for sf, content in stack_contents.items():
        fm = parse_frontmatter_from_content(content)
        if not fm:
            continue
        pkg_section = fm.get("packages", {}) or {}
        fm_runtime = set(pkg_section.get("runtime", []) or [])
        fm_dev = set(pkg_section.get("dev", []) or [])
        fm_all_packages = fm_runtime | fm_dev

        pkg_section_match = re.search(
            r"##\s+Packages\s*\n(.*?)(?=\n##\s|\Z)",
            content,
            re.DOTALL,
        )
        if not pkg_section_match:
            continue

        pkg_prose = pkg_section_match.group(1)
        code_blocks_in_section = re.findall(
            r"```(?:bash|sh)\s*\n(.*?)```", pkg_prose, re.DOTALL
        )
        prose_packages: set[str] = set()
        for code_block in code_blocks_in_section:
            for m in package_install_pattern.finditer(code_block):
                tokens = m.group(1).strip().split()
                pkgs = [t for t in tokens if not t.startswith("-")]
                prose_packages.update(pkgs)

        for pkg in sorted(prose_packages - fm_all_packages):
            line_num = content[: pkg_section_match.start()].count("\n") + 1
            errors.append(
                f"[21] {sf}:{line_num}: Packages prose contains 'npm install {pkg}' "
                f"but '{pkg}' is not in frontmatter packages.runtime or packages.dev"
            )
    return errors


def check_64_conditional_packages_prose_sync(stack_contents: dict[str, str]) -> list[str]:
    """Check 64: Packages skipped in fallback sections must not appear unconditionally in ## Packages."""
    errors: list[str] = []
    skip_pattern = re.compile(r"skip\s+`([^`]+)`")

    for sf, content in stack_contents.items():
        # Find packages explicitly skipped in framework-fallback sections
        skipped_pkgs: set[str] = set()
        for m in skip_pattern.finditer(content):
            skipped_pkgs.add(m.group(1))
        if not skipped_pkgs:
            continue

        # Find the main ## Packages section
        pkg_section_match = re.search(
            r"##\s+Packages\s*\n(.*?)(?=\n##\s|\Z)", content, re.DOTALL
        )
        if not pkg_section_match:
            continue

        # Extract unconditional npm install commands (not preceded by "> When")
        pkg_prose = pkg_section_match.group(1)
        # Split into lines and find npm install commands that are inside code blocks
        # but NOT after a conditional note ("> When...")
        in_conditional = False
        for line in pkg_prose.splitlines():
            if line.strip().startswith("> When") or line.strip().startswith("> when"):
                in_conditional = True
            elif line.startswith("```") and in_conditional:
                # Code block following a conditional note — skip until closing ```
                continue
            elif line.startswith("```"):
                in_conditional = False

            if not in_conditional and line.strip().startswith("npm install"):
                tokens = line.strip().split()[2:]  # skip "npm" and "install"
                pkgs = [t for t in tokens if not t.startswith("-")]
                for pkg in pkgs:
                    if pkg in skipped_pkgs:
                        errors.append(
                            f"[64] {sf}: ## Packages has unconditional 'npm install {pkg}' "
                            f"but a fallback section says to skip it"
                        )
    return errors


def check_26_testing_env_frontmatter_assumes(
    stack_files: list[str],
    stack_contents: dict[str, str],
) -> list[str]:
    """Check 26: Testing stack env frontmatter excludes assumes-dependent vars."""
    errors: list[str] = []
    for sf in stack_files:
        if "/testing/" not in sf:
            continue
        fm = parse_frontmatter(sf)
        if not fm:
            continue

        assumes = fm.get("assumes", []) or []
        optional_assumes = [
            a for a in assumes
            if a.split("/")[0] in OPTIONAL_CATEGORIES
        ]
        if not optional_assumes:
            continue

        content = stack_contents.get(sf, "")
        has_fallback = bool(
            re.search(r"(?i)fallback|no[- ]auth", content)
        )
        if not has_fallback:
            continue

        provider_names = set()
        for a in optional_assumes:
            provider_names.add(a.split("/")[1].upper())

        env_section = fm.get("env", {}) or {}
        server_vars = env_section.get("server", []) or []
        client_vars = env_section.get("client", []) or []
        all_env = server_vars + client_vars

        for var in all_env:
            for provider in provider_names:
                if provider in var:
                    errors.append(
                        f"[26] {sf}: env frontmatter var '{var}' contains "
                        f"provider name '{provider}' from optional assumes — "
                        f"should not be unconditional when a fallback exists"
                    )
    return errors
