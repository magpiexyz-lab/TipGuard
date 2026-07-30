"""Pure helper functions for /ads-ready Layer A static checks."""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from check_project_name import main as cpn_main  # noqa: E402
from derive_pages import derive_scope_pages  # noqa: E402
from iterate_cross_db import _read_token  # noqa: E402
from iterate_cross_railway_db import (  # noqa: E402
    _check_railway_auth,
    list_railway_projects,
)
import stripe_api  # noqa: E402
import vercel_api  # noqa: E402

try:
    import yaml
except ImportError:  # pragma: no cover - tests run with PyYAML installed
    yaml = None


POSTHOG_PLACEHOLDER = "phc_TEAM_KEY"
POSTHOG_PRIVATE_API_HOST = "https://us.posthog.com"
SOURCE_FALLBACK_FILES = [
    "src/lib/analytics.ts",
    "src/lib/analytics-server.ts",
    "src/app/route.ts",
    "site/index.html",
]

SOURCE_EXTENSIONS = [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"]
ROUTE_EXTENSIONS = SOURCE_EXTENSIONS
ANALYTICS_TARGETS = {
    "src/lib/analytics.ts",
    "src/lib/analytics.tsx",
    "src/lib/events.ts",
    "src/lib/events.tsx",
}

RAW_POSTHOG_RE = re.compile(r"\bposthog\.(capture|identify|init|register|reset)\s*\(")
IMPORT_FROM_RE = re.compile(r"\bfrom\s+['\"]([^'\"]+)['\"]")
IMPORT_SIDE_EFFECT_RE = re.compile(r"\bimport\s+['\"]([^'\"]+)['\"]")
REQUIRE_RE = re.compile(r"\brequire\s*\(\s*['\"]([^'\"]+)['\"]\s*\)")
TRACK_RAW_RE = re.compile(r"\btrack\(\s*['\"]([^'\"]+)['\"]")
TRACK_WRAPPER_RE = re.compile(r"\btrack([A-Z][A-Za-z0-9_]*)\s*\(")
TRACKING_CALL_RE = re.compile(r"\b(?:track|identify|reset)\s*\(|\btrack[A-Z]\w+\s*\(")
PAYMENT_PROVIDER_IMPORT_RE = re.compile(
    r"(^stripe$|^@stripe/|stripe-js|checkout|paypal|braintree|paddle|lemonsqueezy)",
    re.IGNORECASE,
)

POSTHOG_ENV_FALLBACK_RE = re.compile(
    r"process\.env\.NEXT_PUBLIC_POSTHOG_KEY\s*\?\?\s*['\"]([^'\"]+)['\"]"
)
SURFACE_ASSIGNMENT_RE = re.compile(
    r"(?:const|var|let)\s+(?:POSTHOG_KEY|key)\s*=\s*['\"]([^'\"]+)['\"]"
)
POSTHOG_INIT_RE = re.compile(r"posthog\.init\s*\(\s*['\"]([^'\"]+)['\"]")

SIGNUP_EVENT_NAMES = {
    "signup_complete",
    "signup_completed",
    "signup_started",
    "signup_start",
    "waitlist_signup",
    "waitlist_submit",
    "waitlist_submitted",
    "register_complete",
    "account_created",
}
SIGNUP_EVENT_RE = re.compile(r".*_signup_(complete|completed|started)$")


def _root(ctx: dict) -> Path:
    return Path(ctx.get("mvp_root", ".")).expanduser()


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _path(ctx: dict, rel: str) -> Path:
    return _root(ctx) / rel


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_yaml_file(path: Path) -> dict:
    if yaml is None:
        return {}
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(_read_text(path)) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


class TeamConfigLoadError(RuntimeError):
    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"{path}: {reason}")


def load_team_config(skill_root: Path | None = None) -> dict:
    """Load .claude/team-config.yaml from the explicit MVP root or cwd."""
    explicit_root = skill_root is not None
    root = Path(skill_root).expanduser() if explicit_root else Path.cwd()
    path = root / ".claude" / "team-config.yaml"
    if not path.exists():
        if explicit_root:
            raise TeamConfigLoadError(path, "missing")
        return {}
    if yaml is None:
        return {}
    try:
        data = yaml.safe_load(_read_text(path)) or {}
    except Exception as exc:
        if explicit_root:
            raise TeamConfigLoadError(path, f"YAML parse error: {exc}")
        return {}
    return data if isinstance(data, dict) else {}


def _experiment(ctx: dict) -> dict:
    return _load_yaml_file(_path(ctx, "experiment/experiment.yaml"))


def _events_yaml(ctx: dict) -> dict:
    return _load_yaml_file(_path(ctx, "experiment/EVENTS.yaml"))


def _iterate_cross_config(ctx: dict) -> dict:
    return _load_yaml_file(_path(ctx, "experiment/iterate-cross-config.yaml"))


def _mvp_name(ctx: dict) -> str:
    return str(_experiment(ctx).get("name") or "").strip()


def _archetype(ctx: dict) -> str:
    return str(_experiment(ctx).get("type") or "web-app").strip() or "web-app"


def _stack(ctx: dict) -> dict:
    stack = _experiment(ctx).get("stack") or {}
    return stack if isinstance(stack, dict) else {}


def _service_values(ctx: dict, key: str) -> list[str]:
    services = _stack(ctx).get("services") or []
    if not isinstance(services, list):
        return []
    values = []
    for service in services:
        if isinstance(service, dict) and service.get(key):
            values.append(str(service[key]))
    return values


def _stack_has_requirement(ctx: dict, requirement: str) -> bool:
    stack = _stack(ctx)
    if requirement in stack and stack.get(requirement):
        return True
    if str(stack.get(requirement) or ""):
        return True
    for value in stack.values():
        if isinstance(value, str) and value == requirement:
            return True
    for service_key in ("runtime", "hosting", "ui", "testing"):
        if requirement in _service_values(ctx, service_key):
            return True
    return False


def _read_env_file(root: Path, rel: str = ".env.local") -> dict[str, str]:
    path = root / rel
    if not path.exists():
        return {}
    env: dict[str, str] = {}
    for raw_line in _read_text(path).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def _is_excluded_source(root: Path, path: Path, include_events: bool = True) -> bool:
    rel = _rel(root, path)
    name = path.name
    parts = set(path.parts)
    if rel in {"src/lib/analytics.ts", "src/lib/analytics-server.ts"}:
        return True
    if include_events and rel == "src/lib/events.ts":
        return True
    if re.search(r"\.(?:test|spec)\.(?:ts|tsx|js|jsx|mjs|cjs)$", name):
        return True
    if re.search(r"\.stories\.(?:ts|tsx|js|jsx|mjs|cjs)$", name):
        return True
    if ".storybook" in parts or "__tests__" in parts or "__mocks__" in parts:
        return True
    return False


def _is_excluded_traversal_path(path: Path) -> bool:
    name = path.name
    parts = set(path.parts)
    if re.search(r"\.(?:test|spec)\.(?:ts|tsx|js|jsx|mjs|cjs)$", name):
        return True
    if re.search(r"\.stories\.(?:ts|tsx|js|jsx|mjs|cjs)$", name):
        return True
    if ".storybook" in parts or "__tests__" in parts or "__mocks__" in parts:
        return True
    return False


def _source_files(root: Path, include_events: bool = True) -> list[Path]:
    src = root / "src"
    if not src.exists():
        return []
    files: list[Path] = []
    for ext in SOURCE_EXTENSIONS:
        files.extend(src.rglob(f"*{ext}"))
    return [
        path
        for path in sorted(files)
        if path.is_file() and not _is_excluded_source(root, path, include_events)
    ]


def _pascal_case(event: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[_\-\s]+", event) if part)


def _snake_case(name: str) -> str:
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _event_call_patterns(event: str) -> tuple[re.Pattern[str], re.Pattern[str]]:
    return (
        re.compile(rf"\btrack\(\s*['\"]{re.escape(event)}['\"]"),
        re.compile(rf"\btrack{re.escape(_pascal_case(event))}\s*\("),
    )


def _file_has_event_call(text: str, event: str) -> bool:
    raw, wrapper = _event_call_patterns(event)
    return bool(raw.search(text) or wrapper.search(text))


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _extract_call_args(text: str, callee: str) -> list[str]:
    args: list[str] = []
    pattern = re.compile(rf"\b{re.escape(callee)}\s*\(")
    for match in pattern.finditer(text):
        start = match.end()
        depth = 1
        i = start
        quote: str | None = None
        escape = False
        while i < len(text):
            ch = text[i]
            if quote:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == quote:
                    quote = None
                i += 1
                continue
            if ch in {"'", '"', "`"}:
                quote = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    args.append(text[start:i])
                    break
            i += 1
    return args


def _track_event_call_args(text: str, event: str) -> list[str]:
    args: list[str] = []
    for call_args in _extract_call_args(text, "track"):
        if re.match(rf"\s*['\"]{re.escape(event)}['\"]\s*,", call_args):
            args.append(call_args)
    args.extend(_extract_call_args(text, f"track{_pascal_case(event)}"))
    return args


def _source_files_matching(root: Path, predicate) -> list[Path]:
    return [path for path in _source_files(root) if predicate(_read_text(path))]


def _read_posthog_api_key() -> str:
    return open(os.path.expanduser("~/.posthog/personal-api-key")).read().strip()


def _read_vercel_project_link(root: Path) -> dict[str, str | None] | None:
    path = root / ".vercel" / "project.json"
    if not path.exists():
        return None
    try:
        data = json.loads(_read_text(path))
    except Exception:
        return None
    return {"projectId": data.get("projectId"), "orgId": data.get("orgId")}


TEAM_CONFIG_MISSING_DETAILS = "Team config not found at .claude/team-config.yaml — cannot validate."


def _team_config(ctx: dict) -> dict:
    return load_team_config(_root(ctx))


def _team_root(config: dict) -> dict:
    team = config.get("team") if isinstance(config, dict) else {}
    return team if isinstance(team, dict) else {}


def _team_provider(config: dict, provider: str) -> dict:
    team = _team_root(config)
    if not isinstance(team, dict):
        return {}
    section = team.get(provider)
    return section if isinstance(section, dict) else {}


def _team_list(config: dict, provider: str, field: str) -> list[str]:
    values = _team_provider(config, provider).get(field)
    if not isinstance(values, list):
        return []
    normalized = [str(value).strip() for value in values if value is not None]
    return [value for value in normalized if value]


def _team_config_load_error_result(exc: TeamConfigLoadError) -> tuple[bool, str, str | None]:
    if exc.reason == "missing":
        return (
            False,
            f"Team config not found at {exc.path}.",
            f"Add {exc.path} with the team's provider identity allowlists, then re-run /ads-ready.",
        )
    return (
        False,
        f"Team config parse error at {exc.path}: {exc.reason}",
        f"Fix YAML syntax in {exc.path}, then re-run /ads-ready.",
    )


def _missing_team_config_result() -> tuple[bool, str, str | None]:
    return (
        False,
        TEAM_CONFIG_MISSING_DETAILS,
        "Add .claude/team-config.yaml with the team's provider identity allowlists, then re-run /ads-ready.",
    )


def _missing_team_root_result() -> tuple[bool, str, str | None]:
    return (
        False,
        "Team config missing team section.",
        "Add a top-level team: section to .claude/team-config.yaml, then re-run /ads-ready.",
    )


def _missing_team_provider_result(provider: str) -> tuple[bool, str, str | None]:
    return (
        False,
        f"Team config missing team.{provider} section.",
        f"Add team.{provider} to .claude/team-config.yaml, then re-run /ads-ready.",
    )


def _missing_team_section_result(provider: str, field: str) -> tuple[bool, str, str | None]:
    return (
        False,
        f"Team config missing team.{provider}.{field}.",
        f"Add team.{provider}.{field} to .claude/team-config.yaml, then re-run /ads-ready.",
    )


def _team_values_or_failure(
    ctx: dict,
    provider: str,
    field: str,
    config: dict | None = None,
) -> tuple[list[str], tuple[bool, str, str | None] | None]:
    if config is None:
        try:
            config = _team_config(ctx)
        except TeamConfigLoadError as exc:
            return [], _team_config_load_error_result(exc)
    if not config:
        return [], _missing_team_config_result()
    team = config.get("team")
    if not isinstance(team, dict):
        return [], _missing_team_root_result()
    if not isinstance(team.get(provider), dict):
        return [], _missing_team_provider_result(provider)
    values = _team_list(config, provider, field)
    if not values:
        return [], _missing_team_section_result(provider, field)
    return values, None


def _vercel_identity(ctx: dict) -> tuple[str | None, str | None, str | None]:
    root = _root(ctx)
    link = _read_vercel_project_link(root)
    project_id = ctx.get("vercel_project_id")
    team_id = ctx.get("vercel_team_id")
    if link:
        project_id = project_id or link.get("projectId")
        team_id = team_id or link.get("orgId")
    token = ctx.get("vercel_token") or vercel_api.read_vercel_token()
    return token, project_id, team_id


def _extract_source_fallbacks(root: Path) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for rel in SOURCE_FALLBACK_FILES:
        path = root / rel
        if not path.exists():
            continue
        text = _read_text(path)
        if rel in {"src/lib/analytics.ts", "src/lib/analytics-server.ts"}:
            matches = POSTHOG_ENV_FALLBACK_RE.findall(text)
        else:
            matches = SURFACE_ASSIGNMENT_RE.findall(text)
            if not matches:
                matches = POSTHOG_INIT_RE.findall(text)
        for value in matches:
            found.append((rel, value))
    return found


def _format_source_drift(root: Path) -> str:
    pairs = _extract_source_fallbacks(root)
    return ", ".join(f"{file}={_mask_secret(value)}" for file, value in pairs)


def resolve_production_posthog_key(ctx: dict) -> tuple[str | None, str, str | None]:
    """Resolve the production NEXT_PUBLIC_POSTHOG_KEY for an MVP.

    Returns (key, source_tag, resolved_file). See the /ads-ready plan for the
    six source tags and branch semantics.
    """
    root = _root(ctx)
    token, project_id, team_id = _vercel_identity(ctx)
    if token and project_id:
        result = vercel_api.get_vercel_env_var(
            token,
            project_id,
            team_id,
            "NEXT_PUBLIC_POSTHOG_KEY",
            target="production",
        )
        if isinstance(result, vercel_api.EnvResultError):
            return None, "vercel_env_error", None
        if isinstance(result, vercel_api.EnvResultFound):
            if result.value and result.value != POSTHOG_PLACEHOLDER:
                return result.value, "vercel_env_set", None
            return result.value, "vercel_env_empty_or_placeholder", None

    fallbacks = _extract_source_fallbacks(root)
    if not fallbacks:
        return None, "missing", None

    for file, value in fallbacks:
        if value == POSTHOG_PLACEHOLDER:
            return value, "source_fallback", file

    values = {value for _, value in fallbacks}
    if len(values) > 1:
        return None, "source_fallback_inconsistent", None

    file, value = fallbacks[0]
    return value, "source_fallback", file


def applies_if_iterate_cross_config_has_signup_events(ctx: dict) -> bool:
    mapping = (_iterate_cross_config(ctx).get("mvp_mappings") or {}).get(_mvp_name(ctx))
    if not isinstance(mapping, dict):
        return False
    events = mapping.get("signup_events") or []
    return isinstance(events, list) and bool(events)


def _vercel_env_value_matches(ctx: dict, key: str, predicate) -> bool:
    root = _root(ctx)
    if not ctx.get("vercel_project_id") and not _read_vercel_project_link(root):
        return False
    token, project_id, team_id = _vercel_identity(ctx)
    if not token or not project_id:
        return False
    try:
        result = vercel_api.get_vercel_env_var(token, project_id, team_id, key, target="production")
    except Exception:
        return False
    return isinstance(result, vercel_api.EnvResultFound) and predicate(result.value)


def _env_value_matches(ctx: dict, key: str, predicate) -> bool:
    local_value = _read_env_file(_root(ctx)).get(key, "")
    if local_value and predicate(local_value):
        return True
    return _vercel_env_value_matches(ctx, key, predicate)


def _is_supabase_url(value: str | None) -> bool:
    return bool(_supabase_project_ref_from_url(value))


def _is_railway_database_url(value: str | None) -> bool:
    return "railway.app" in str(value or "")


def _is_stripe_secret_key(value: str | None) -> bool:
    return str(value or "").startswith(("sk_", "rk_"))


def applies_if_stack_database_supabase(ctx: dict) -> bool:
    if _stack(ctx).get("database") == "supabase":
        return True
    return _env_value_matches(ctx, "NEXT_PUBLIC_SUPABASE_URL", _is_supabase_url)


def applies_if_stack_database_railway(ctx: dict) -> bool:
    root = _root(ctx)
    if _stack(ctx).get("database") == "railway":
        return True
    if (root / "railway.json").exists():
        return True
    return _env_value_matches(ctx, "DATABASE_URL", _is_railway_database_url)


def applies_if_stack_hosting_vercel(ctx: dict) -> bool:
    if "vercel" in _service_values(ctx, "hosting"):
        return True
    return (_root(ctx) / ".vercel" / "project.json").exists()


def applies_if_stack_payment_stripe(ctx: dict) -> bool:
    if _stack(ctx).get("payment") == "stripe":
        return True
    return _env_value_matches(ctx, "STRIPE_SECRET_KEY", _is_stripe_secret_key)


def applies_if_events_yaml_exists(ctx: dict) -> bool:
    return _path(ctx, "experiment/EVENTS.yaml").exists()


def applies_if_phase_2(ctx: dict) -> bool:
    return _truthy(ctx.get("phase_2"))


def check_project_name_drift(ctx: dict) -> tuple[bool, str, str | None]:
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        rc = cpn_main(["--root", str(_root(ctx))])
    err = stderr.getvalue().strip()
    if rc == 0:
        return True, "PROJECT_NAME constants match experiment.yaml.name.", None
    if rc == 1:
        return (
            False,
            err or "PROJECT_NAME drift detected.",
            "PROJECT_NAME drift. Update the constant in the file(s) listed in stderr to match experiment.yaml.name.",
        )
    if rc == 2:
        return (
            False,
            "check_project_name returned environmental error (exit 2); see stderr"
            + (f": {err}" if err else ""),
            "Resolve the environmental issue (missing yaml, missing PyYAML) and re-run /ads-ready",
        )
    return False, f"check_project_name returned unexpected exit {rc}: {err}", "Report to template maintainer."


def check_no_posthog_placeholder(ctx: dict) -> tuple[bool, str, str | None]:
    key, source, resolved_file = resolve_production_posthog_key(ctx)
    if source in {"vercel_env_set", "source_fallback"} and key and key != POSTHOG_PLACEHOLDER:
        return True, f"PostHog key resolved from {source}.", None
    if source == "source_fallback_inconsistent":
        drift = _format_source_drift(_root(ctx))
        return (
            False,
            f"Active PostHog fallback values disagree across source files: {drift}.",
            f"Active PostHog fallback values disagree across source files: {drift}. All client+server analytics files must use the SAME team `phc_*` key (or all defer to Vercel production env). Sync them.",
        )
    if source == "vercel_env_empty_or_placeholder":
        return (
            False,
            "NEXT_PUBLIC_POSTHOG_KEY in Vercel production env is empty or placeholder.",
            "NEXT_PUBLIC_POSTHOG_KEY in Vercel production env is empty or placeholder. Set it to your team's real `phc_*` key in Vercel project settings (Production target).",
        )
    if source == "vercel_env_error":
        return (
            False,
            "Could not verify Vercel production env.",
            "Could not verify Vercel production env. Confirm `vercel login` and retry. Local .env.local does NOT count - production env is authoritative.",
        )
    if source == "source_fallback" and key == POSTHOG_PLACEHOLDER:
        return (
            False,
            f"Source file `{resolved_file}` still has the placeholder as its active PostHog fallback.",
            f"Source file `{resolved_file}` still has the `phc_TEAM_KEY` placeholder as its active PostHog fallback value. Replace the active fallback literal with the team's real `phc_*` key, OR set NEXT_PUBLIC_POSTHOG_KEY in Vercel production env. (Do NOT change any `POSTHOG_PLACEHOLDER` comparison constants - those exist intentionally for runtime misconfig detection.)",
        )
    return (
        False,
        "NEXT_PUBLIC_POSTHOG_KEY is not configured anywhere.",
        "NEXT_PUBLIC_POSTHOG_KEY is not configured in Vercel production env, nor as a source-level fallback in any of: src/lib/analytics.ts, src/lib/analytics-server.ts, src/app/route.ts, site/index.html. Set it in Vercel production env.",
    )


def _load_tsconfig_paths(root: Path) -> list[tuple[str, str]]:
    path = root / "tsconfig.json"
    if not path.exists():
        return [("@/*", "src/*")]
    try:
        data = json.loads(_read_text(path))
    except Exception:
        return [("@/*", "src/*")]
    raw_paths = ((data.get("compilerOptions") or {}).get("paths") or {})
    paths: list[tuple[str, str]] = [("@/*", "src/*")]
    if isinstance(raw_paths, dict):
        for alias, targets in raw_paths.items():
            if not isinstance(targets, list):
                continue
            for target in targets:
                if isinstance(target, str):
                    paths.append((alias, target))
    return paths


def _apply_alias(spec: str, aliases: list[tuple[str, str]]) -> str | None:
    for alias, target in aliases:
        if "*" in alias:
            prefix, suffix = alias.split("*", 1)
            if spec.startswith(prefix) and spec.endswith(suffix):
                middle = spec[len(prefix) : len(spec) - len(suffix) if suffix else len(spec)]
                return target.replace("*", middle)
        elif spec == alias or spec.startswith(alias.rstrip("/") + "/"):
            rest = spec[len(alias) :].lstrip("/")
            return str(Path(target) / rest)
    if spec.startswith("@/"):
        return "src/" + spec[2:]
    return None


def _probe_module(base: Path) -> Path | None:
    candidates: list[Path] = []
    if base.suffix in SOURCE_EXTENSIONS and base.exists():
        candidates.append(base)
    for ext in SOURCE_EXTENSIONS:
        candidates.append(base.with_suffix(ext))
    for ext in SOURCE_EXTENSIONS:
        candidates.append(base / f"index{ext}")
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _resolve_import(root: Path, importer: Path, spec: str, aliases: list[tuple[str, str]] | None = None) -> Path | None:
    aliases = aliases or _load_tsconfig_paths(root)
    base: Path | None = None
    if spec.startswith("."):
        base = (importer.parent / spec).resolve()
    else:
        alias_target = _apply_alias(spec, aliases)
        if alias_target:
            base = (root / alias_target).resolve()
    if base is None:
        return None
    resolved = _probe_module(base)
    if not resolved:
        return None
    try:
        resolved.resolve().relative_to((root / "src").resolve())
    except ValueError:
        return None
    if _is_excluded_traversal_path(resolved):
        return None
    return resolved


def _import_specs(text: str) -> list[str]:
    return IMPORT_FROM_RE.findall(text) + IMPORT_SIDE_EFFECT_RE.findall(text) + REQUIRE_RE.findall(text)


def _landing_roots(ctx: dict) -> list[Path]:
    root = _root(ctx)
    roots: list[Path] = []
    default_page = root / "src/app/page.tsx"
    if default_page.exists():
        roots.append(default_page)
    elif (root / "src/app/layout.tsx").exists():
        roots.append(root / "src/app/layout.tsx")

    for page in derive_scope_pages(_experiment(ctx)):
        page = str(page).strip("/")
        if not page or page in {"landing", "home"}:
            candidate = root / "src/app/page.tsx"
        else:
            candidate = root / "src/app" / page / "page.tsx"
        if candidate.exists() and candidate not in roots:
            roots.append(candidate)

    if not roots:
        roots.extend(sorted((root / "src/app").rglob("page.tsx")) if (root / "src/app").exists() else [])
    return roots


def check_analytics_module_wired(ctx: dict) -> tuple[bool, str, str | None]:
    root = _root(ctx)
    aliases = _load_tsconfig_paths(root)
    queue = list(_landing_roots(ctx))
    visited: set[Path] = set()
    cap = 200

    while queue and len(visited) < cap:
        current = queue.pop(0).resolve()
        if current in visited or not current.exists():
            continue
        visited.add(current)
        text = _read_text(current)
        imported_targets: list[Path] = []
        for spec in _import_specs(text):
            resolved = _resolve_import(root, current, spec, aliases)
            if not resolved:
                continue
            imported_targets.append(resolved)
            if resolved.resolve() not in visited and len(visited) + len(queue) < cap:
                queue.append(resolved)
        for target in imported_targets:
            if _rel(root, target) in ANALYTICS_TARGETS and TRACKING_CALL_RE.search(text):
                return (
                    True,
                    f"{_rel(root, current)} imports {_rel(root, target)} and calls a tracking function.",
                    None,
                )

    return (
        False,
        f"No reachable landing component imports analytics/events and calls a tracking function (visited {len(visited)} files).",
        "No file reachable from the landing page's component tree (BFS visited-set, up to 200 files) imports an analytics module AND calls a tracking function. Add `import { trackLandingViewed } from '@/lib/events'` to src/app/page.tsx (or to a colocated landing component) and call it on mount.",
    )


def check_no_raw_capture(ctx: dict) -> tuple[bool, str, str | None]:
    root = _root(ctx)
    offenders = []
    for path in _source_files(root):
        text = _read_text(path)
        if RAW_POSTHOG_RE.search(text):
            offenders.append(_rel(root, path))
    if not offenders:
        return True, "No raw posthog.* bypass calls found outside analytics wrappers.", None
    listed = ", ".join(offenders)
    return (
        False,
        f"Raw posthog.* calls found in: {listed}.",
        f"Replace raw posthog.<method>() calls with the corresponding wrapper from @/lib/analytics (track/identify/reset). Direct posthog.* is only allowed inside src/lib/analytics{{,-server}}.ts. File(s): {listed}.",
    )


def _signup_events_from_config(ctx: dict) -> list[str]:
    mappings = _iterate_cross_config(ctx).get("mvp_mappings") or {}
    mapping = mappings.get(_mvp_name(ctx)) if isinstance(mappings, dict) else None
    if not isinstance(mapping, dict):
        return []
    events = mapping.get("signup_events") or []
    return [str(event) for event in events] if isinstance(events, list) else []


def check_signup_events_implemented(ctx: dict) -> tuple[bool, str, str | None]:
    events = _signup_events_from_config(ctx)
    if not events:
        return True, "No iterate-cross signup_events configured for this MVP.", None
    root = _root(ctx)
    files = _source_files(root)
    missing = []
    for event in events:
        if not any(_file_has_event_call(_read_text(path), event) for path in files):
            missing.append(event)
    if not missing:
        return True, "All iterate-cross signup_events have call sites.", None
    event = missing[0]
    return (
        False,
        f"Missing call site for signup event `{event}`.",
        f"Event '{event}' is in mvp_mappings.{_mvp_name(ctx)}.signup_events but no call site invokes track('{event}') or track{_pascal_case(event)}(...) outside src/lib/events.ts. Add the call to the signup handler.",
    )


def _mask_secret(value: str | None) -> str:
    if not value:
        return "<empty>"
    if len(value) <= 10:
        return value
    return value[:6] + "..." + value[-4:]


def _posthog_get(url: str, api_key: str) -> dict:
    r = subprocess.run(
        ["curl", "-s", "-H", f"Authorization: Bearer {api_key}", url],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        raise RuntimeError(f"PostHog API failed: {r.stderr[:200]}")
    try:
        data = json.loads(r.stdout)
    except Exception as exc:
        raise RuntimeError(f"malformed PostHog response: {exc}") from exc
    if isinstance(data, dict) and str(data.get("detail", "")).lower().startswith("authentication"):
        raise PermissionError("PostHog token lacks Project Read scope.")
    return data if isinstance(data, dict) else {}


def _next_url(host: str, url: str | None) -> str | None:
    if not url:
        return None
    if url.startswith("http"):
        return url
    return host.rstrip("/") + "/" + url.lstrip("/")


def _list_posthog_projects(api_key: str, host: str = POSTHOG_PRIVATE_API_HOST) -> list[dict]:
    projects: list[dict] = []
    project_url: str | None = f"{host.rstrip('/')}/api/projects/"
    while project_url:
        project_page = _posthog_get(project_url, api_key)
        for project in project_page.get("results") or []:
            if isinstance(project, dict):
                projects.append(project)
        project_url = _next_url(host, project_page.get("next"))
    return projects


def _posthog_source_failure(source: str, resolved_file: str | None) -> tuple[bool, str, str | None]:
    if source == "source_fallback_inconsistent":
        return (
            False,
            "PostHog source fallback values are inconsistent.",
            "Sync active PostHog fallback literals across client and server source files before validating team ownership.",
        )
    if source == "vercel_env_empty_or_placeholder":
        return (
            False,
            "NEXT_PUBLIC_POSTHOG_KEY in Vercel production env is empty or placeholder.",
            "Set NEXT_PUBLIC_POSTHOG_KEY in Vercel production env to the team's real PostHog key.",
        )
    if source == "vercel_env_error":
        return (
            False,
            "Could not verify Vercel production env for NEXT_PUBLIC_POSTHOG_KEY.",
            "Confirm `vercel login` and retry. Do not rely on local .env.local for ads readiness.",
        )
    if source == "missing":
        return (
            False,
            "NEXT_PUBLIC_POSTHOG_KEY is not configured.",
            "Set NEXT_PUBLIC_POSTHOG_KEY in Vercel production env, or add a source fallback in the analytics file.",
        )
    if resolved_file:
        return (
            False,
            f"`{resolved_file}` still uses the phc_TEAM_KEY placeholder.",
            f"Replace the active fallback literal in `{resolved_file}` with the team's real `phc_*` key.",
        )
    return False, "PostHog key could not be resolved.", "Configure NEXT_PUBLIC_POSTHOG_KEY."


def _server_key_result(ctx: dict) -> Any:
    token, project_id, team_id = _vercel_identity(ctx)
    if not token or not project_id:
        return vercel_api.EnvResultAbsent()
    return vercel_api.get_vercel_env_var(
        token,
        project_id,
        team_id,
        "POSTHOG_SERVER_KEY",
        target="production",
    )


def _format_posthog_team_expectation(team_posthog: dict) -> str:
    project_ids = team_posthog.get("project_ids") if isinstance(team_posthog, dict) else []
    api_tokens = team_posthog.get("project_api_tokens") if isinstance(team_posthog, dict) else []
    if not isinstance(project_ids, list):
        project_ids = []
    if not isinstance(api_tokens, list):
        api_tokens = []
    return (
        f"team.posthog.project_ids={project_ids}; "
        f"team.posthog.project_api_tokens count={len(api_tokens)}"
    )


def _posthog_server_key_failure(
    ctx: dict,
    client_key: str,
) -> tuple[bool, str, str | None] | None:
    result = _server_key_result(ctx)
    if isinstance(result, vercel_api.EnvResultAbsent):
        return None
    if isinstance(result, vercel_api.EnvResultError):
        return (
            False,
            f"Could not verify Vercel POSTHOG_SERVER_KEY: {result.reason}. Fix Vercel auth and retry.",
            "Fix Vercel auth and retry.",
        )
    if isinstance(result, vercel_api.EnvResultFound):
        if result.value == "":
            message = (
                "POSTHOG_SERVER_KEY is set to empty string in Vercel prod env. "
                "JS ?? does NOT fall through on empty string, so server-side events will fail. "
                "Either unset POSTHOG_SERVER_KEY or set to a real team key."
            )
            return False, message, "Unset POSTHOG_SERVER_KEY or set it to a real team key."
        if result.value == POSTHOG_PLACEHOLDER:
            message = (
                "POSTHOG_SERVER_KEY is set to the placeholder phc_TEAM_KEY. "
                "Server events go to a no-op project. Unset or set to a real team key."
            )
            return False, message, "Unset POSTHOG_SERVER_KEY or set it to a real team key."
        if result.value != client_key:
            message = (
                "POSTHOG_SERVER_KEY targets a different PostHog project than "
                "NEXT_PUBLIC_POSTHOG_KEY. Per stack contract, all events must go to the same "
                "project. Set POSTHOG_SERVER_KEY to the same value as NEXT_PUBLIC_POSTHOG_KEY, "
                "or unset it."
            )
            return (
                False,
                message,
                "Set POSTHOG_SERVER_KEY to the same value as NEXT_PUBLIC_POSTHOG_KEY, or unset it.",
            )
    return None


def _resolve_mvp_env_value(ctx: dict, keys: list[str]) -> tuple[str | None, str | None, str | None]:
    root = _root(ctx)
    link = _read_vercel_project_link(root)
    env = _read_env_file(root)
    token, project_id, team_id = _vercel_identity(ctx)
    display_keys = "/".join(keys)

    if not token:
        return (
            None,
            "vercel_env_error",
            f"Could not verify Vercel production env for {display_keys}: Vercel token is missing.",
        )
    if not project_id:
        return (
            None,
            "vercel_env_error",
            f"Could not verify Vercel production env for {display_keys}: Vercel project ID is missing.",
        )

    for key in keys:
        result = vercel_api.get_vercel_env_var(token, project_id, team_id, key, target="production")
        if isinstance(result, vercel_api.EnvResultError):
            return (
                None,
                "vercel_env_error",
                f"Could not verify Vercel production env for {key}: {result.reason}",
            )
        if isinstance(result, vercel_api.EnvResultFound):
            if result.value:
                return result.value, "vercel_env_set", None
            return (
                None,
                "vercel_env_empty",
                f"{key} is set to empty string in Vercel production env; empty strings mask .env.local.",
            )

    local_keys = [key for key in keys if env.get(key)]
    local_note = ""
    if local_keys:
        local_note = (
            f" .env.local contains {', '.join(local_keys)}, but local env is diagnostic only "
            "and cannot satisfy /ads-ready."
        )
    if not link:
        return (
            None,
            "vercel_project_link_missing",
            f"{display_keys} is absent from Vercel production env and .vercel/project.json is missing.{local_note}",
        )
    return (
        None,
        "vercel_env_absent",
        f"{display_keys} is absent from Vercel production env.{local_note}",
    )


def _supabase_project_ref_from_url(supabase_url: str | None) -> str | None:
    match = re.search(r"https://([a-zA-Z0-9-]+)\.supabase\.co", supabase_url or "")
    return match.group(1) if match else None


def _get_supabase_project(project_ref: str, token: str) -> dict:
    r = subprocess.run(
        [
            "curl",
            "-s",
            "-w",
            "\nHTTP_STATUS:%{http_code}",
            "-H",
            f"Authorization: Bearer {token}",
            f"https://api.supabase.com/v1/projects/{project_ref}",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    if r.returncode != 0:
        raise RuntimeError(f"curl exit {r.returncode}: {r.stderr[:200]}")
    body_text, _, status_text = (r.stdout or "").rpartition("\nHTTP_STATUS:")
    if not status_text:
        body_text = r.stdout or ""
        status = None
    else:
        try:
            status = int(status_text.strip() or 0)
        except ValueError:
            status = None
    try:
        data = json.loads(body_text) if body_text.strip() else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"non-json response: {body_text[:200]}") from exc
    if status and status >= 400:
        raise RuntimeError(f"HTTP {status}: {json.dumps(data)[:200]}")
    return data if isinstance(data, dict) else {}


def check_posthog_team_key(ctx: dict) -> tuple[bool, str, str | None]:
    key, source, resolved_file = resolve_production_posthog_key(ctx)
    if source not in {"vercel_env_set", "source_fallback"} or not key or key == POSTHOG_PLACEHOLDER:
        return _posthog_source_failure(source, resolved_file)

    try:
        config = _team_config(ctx)
    except TeamConfigLoadError as exc:
        return _team_config_load_error_result(exc)
    team_tokens, failure = _team_values_or_failure(
        ctx,
        "posthog",
        "project_api_tokens",
        config,
    )
    if failure:
        return failure
    posthog_config = _team_provider(config, "posthog")
    expected = _format_posthog_team_expectation(posthog_config)
    source_label = (
        f"`{resolved_file}` source fallback"
        if source == "source_fallback"
        else "Vercel production env"
    )
    if key not in team_tokens:
        return (
            False,
            (
                "Resolved PostHog key is not in team-config. "
                f"Expected {expected}; actual={_mask_secret(key)} from {source_label}."
            ),
            (
                f"Set NEXT_PUBLIC_POSTHOG_KEY in {source_label} to one of "
                "team.posthog.project_api_tokens. "
                f"Expected {expected}; actual={_mask_secret(key)}."
            ),
        )
    server_key_failure = _posthog_server_key_failure(ctx, key)
    if server_key_failure:
        return server_key_failure
    return (
        True,
        "MVP NEXT_PUBLIC_POSTHOG_KEY matches team-config.yaml.team.posthog.project_api_tokens",
        None,
    )


def check_supabase_team_org(ctx: dict) -> tuple[bool, str, str | None]:
    expected_orgs, failure = _team_values_or_failure(ctx, "supabase", "organization_ids")
    if failure:
        return failure

    supabase_url, source, env_error = _resolve_mvp_env_value(ctx, ["NEXT_PUBLIC_SUPABASE_URL"])
    if env_error:
        return (
            False,
            env_error,
            "Set NEXT_PUBLIC_SUPABASE_URL in Vercel production env; .env.local is diagnostic only for /ads-ready.",
        )
    project_ref = _supabase_project_ref_from_url(supabase_url)
    if not project_ref:
        return (
            False,
            "NEXT_PUBLIC_SUPABASE_URL is missing or invalid in Vercel production env.",
            "Set NEXT_PUBLIC_SUPABASE_URL in Vercel production env to the team Supabase project URL.",
        )
    try:
        token = _read_token()
    except SystemExit as exc:
        return False, str(exc), "Run `supabase login`."
    except Exception as exc:
        return False, f"Supabase token read failed: {exc}", "Run `supabase login` and retry."
    try:
        project = _get_supabase_project(project_ref, token)
    except Exception as exc:
        return (
            False,
            f"Supabase project `{project_ref}` lookup failed: {exc}",
            "Confirm the Supabase token can read this project and retry.",
        )

    organization_id = str(project.get("organization_id") or "")
    if organization_id and organization_id in expected_orgs:
        return (
            True,
            f"Supabase project `{project_ref}` from {source} belongs to configured team org `{organization_id}`.",
            None,
        )
    return (
        False,
        f"Supabase project `{project_ref}` belongs to org `{organization_id or '<missing>'}`, not team.supabase.organization_ids={expected_orgs}.",
        f"Move Supabase project {project_ref} to one of team.supabase.organization_ids={expected_orgs}, or update the MVP Supabase URL.",
    )


def _railway_project_id(root: Path) -> str | None:
    path = root / "railway.json"
    if not path.exists():
        return None
    try:
        data = json.loads(_read_text(path))
    except Exception:
        return None
    return data.get("projectId") or data.get("project")


def check_railway_team_workspace(ctx: dict) -> tuple[bool, str, str | None]:
    expected_workspaces, failure = _team_values_or_failure(ctx, "railway", "workspace_ids")
    if failure:
        return failure

    auth_error = _check_railway_auth()
    if auth_error:
        return False, auth_error, "Run `! railway login`."
    root = _root(ctx)
    project_id = _railway_project_id(root)
    if not project_id:
        return (
            False,
            "Railway project ID is missing from railway.json.",
            "Run `railway link` for the team Railway project so railway.json contains projectId.",
        )
    projects = list_railway_projects()
    project = next((p for p in projects if p.get("id") == project_id), None)
    if not project:
        return (
            False,
            f"Railway project `{project_id}` is not accessible via `railway list --json`.",
            "Log in to Railway with an account that can access the configured team project, or re-link the MVP to the team Railway project.",
        )
    workspace = project.get("workspace")
    workspace_id = (
        workspace.get("id")
        if isinstance(workspace, dict)
        else project.get("workspace_id") or project.get("workspaceId")
    )
    workspace_id = str(workspace_id or "")
    if workspace_id in expected_workspaces:
        return True, f"Railway project `{project_id}` belongs to team workspace `{workspace_id}`.", None
    return (
        False,
        f"Railway project `{project_id}` belongs to workspace `{workspace_id or '<missing>'}`, not team.railway.workspace_ids={expected_workspaces}.",
        f"Transfer Railway project {project_id} to one of team.railway.workspace_ids={expected_workspaces}, or update railway.json to the team project.",
    )


def check_vercel_team_account(ctx: dict) -> tuple[bool, str, str | None]:
    expected_team_ids, failure = _team_values_or_failure(ctx, "vercel", "team_ids")
    if failure:
        return failure

    link = _read_vercel_project_link(_root(ctx))
    if not link or not link.get("orgId"):
        return (
            False,
            "Vercel project link is missing orgId in .vercel/project.json.",
            "Run `vercel link` against the team Vercel project so .vercel/project.json contains orgId.",
        )
    if not link.get("projectId"):
        return (
            False,
            "Vercel project link is missing projectId in .vercel/project.json.",
            "Run `vercel link` against the team Vercel project so .vercel/project.json contains projectId.",
        )
    team_id = str(link["orgId"])
    project_id = str(link["projectId"])
    if team_id not in expected_team_ids:
        return (
            False,
            f"Vercel project `{project_id}` is linked to orgId `{team_id}`, not team.vercel.team_ids={expected_team_ids}.",
            f"Transfer Vercel project {project_id} to one of team.vercel.team_ids={expected_team_ids}, or re-run `vercel link` against the team's project.",
        )

    token = ctx.get("vercel_token") or vercel_api.read_vercel_token()
    if not token:
        return (
            False,
            "Vercel token is missing; cannot validate .vercel/project.json against the Vercel API.",
            "Run `vercel login` with an account that can access the team project, then re-run /ads-ready.",
        )
    try:
        project = vercel_api.find_project(token, team_id=team_id, project_id_or_name=project_id)
    except Exception as exc:
        return (
            False,
            f"Could not verify Vercel project `{project_id}` via API: {exc}",
            "Fix Vercel auth/API access, then re-run /ads-ready.",
        )
    if project is None:
        return (
            False,
            f"Vercel project `{project_id}` was not accessible via API under team `{team_id}`.",
            "Re-link to an existing team Vercel project, or log in with a Vercel account that can access it.",
        )
    if str(project.get("id") or "") != project_id:
        return (
            False,
            f"Vercel projectId {project_id} in .vercel/project.json does not match any team project by ID. (A team project named {project_id} exists, but matching by name is not strict-safe — fix .vercel/project.json to the correct projectId via vercel link.)",
            "Run `vercel link` against the team Vercel project so .vercel/project.json contains the correct projectId.",
        )
    return True, f"Vercel project `{project_id}` is linked to team `{team_id}` and API-accessible.", None


def check_stripe_team_account(ctx: dict) -> tuple[bool, str, str | None]:
    expected_accounts, failure = _team_values_or_failure(ctx, "stripe", "account_ids")
    if failure:
        return failure

    mvp_key, _source, env_error = _resolve_mvp_env_value(ctx, ["STRIPE_SECRET_KEY"])
    if env_error:
        return (
            False,
            env_error,
            "Set STRIPE_SECRET_KEY in Vercel production env; .env.local is diagnostic only for /ads-ready.",
        )
    if not mvp_key:
        return (
            False,
            "STRIPE_SECRET_KEY is missing for a Stripe MVP.",
            "Set STRIPE_SECRET_KEY in Vercel production env.",
        )
    mvp_account = stripe_api.get_account_id(mvp_key)
    if not mvp_account:
        return False, "Could not resolve Stripe account ID from STRIPE_SECRET_KEY.", "Confirm STRIPE_SECRET_KEY and retry."
    if mvp_account in expected_accounts:
        return True, f"Stripe account `{mvp_account}` is in team.stripe.account_ids.", None
    return (
        False,
        f"MVP STRIPE_SECRET_KEY resolves to account `{mvp_account}`, not team.stripe.account_ids={expected_accounts}.",
        f"Set STRIPE_SECRET_KEY to a key for one of team.stripe.account_ids={expected_accounts}.",
    )


def _events_map(ctx: dict) -> dict[str, dict]:
    events = _events_yaml(ctx).get("events") or {}
    if isinstance(events, dict):
        return {str(k): (v if isinstance(v, dict) else {}) for k, v in events.items()}
    if isinstance(events, list):
        out = {}
        for item in events:
            if isinstance(item, dict) and item.get("name"):
                out[str(item["name"])] = item
        return out
    return {}


def _event_requires(event_config: dict) -> list[str]:
    requires = event_config.get("requires") or []
    if isinstance(requires, str):
        requires = [requires]
    if not isinstance(requires, list):
        return []
    return [str(req) for req in requires if str(req)]


def _event_archetypes(event_config: dict) -> list[str]:
    archetypes = event_config.get("archetypes") or []
    if isinstance(archetypes, str):
        archetypes = [archetypes]
    if not isinstance(archetypes, list):
        return []
    return [str(archetype) for archetype in archetypes if str(archetype)]


def _known_stack_requirement_keys(ctx: dict) -> set[str]:
    stack = _stack(ctx)
    known = {
        "database",
        "auth",
        "auth_providers",
        "analytics",
        "payment",
        "email",
        "runtime",
        "hosting",
        "ui",
        "testing",
    }
    known.update(str(key) for key in stack.keys() if key != "services")
    services = stack.get("services") or []
    if isinstance(services, list):
        for service in services:
            if isinstance(service, dict):
                known.update(str(key) for key in service.keys() if key != "name")
    return known


def _unknown_event_requires(ctx: dict) -> list[tuple[str, str]]:
    known = _known_stack_requirement_keys(ctx)
    unknown: list[tuple[str, str]] = []
    for event_name, event_config in _events_map(ctx).items():
        for requirement in _event_requires(event_config):
            if requirement not in known:
                unknown.append((event_name, requirement))
    return unknown


def _known_archetypes() -> set[str]:
    archetypes_dir = Path(__file__).resolve().parents[2] / "archetypes"
    return {
        path.stem
        for path in archetypes_dir.glob("*.md")
        if path.is_file()
    }


def _unknown_event_archetypes(ctx: dict) -> list[tuple[str, str]]:
    known = _known_archetypes()
    unknown: list[tuple[str, str]] = []
    for event_name, event_config in _events_map(ctx).items():
        for archetype in _event_archetypes(event_config):
            if archetype not in known:
                unknown.append((event_name, archetype))
    return unknown


def _event_applies(ctx: dict, event_config: dict) -> bool:
    requires = _event_requires(event_config)
    if any(not _stack_has_requirement(ctx, str(req)) for req in requires):
        return False
    archetypes = _event_archetypes(event_config)
    if archetypes and _archetype(ctx) not in archetypes:
        return False
    return True


def _filtered_events(ctx: dict) -> set[str]:
    return {
        name
        for name, config in _events_map(ctx).items()
        if _event_applies(ctx, config)
    }


def _event_property_required(event_config: dict, prop_name: str) -> bool:
    properties = event_config.get("properties") or {}
    if not isinstance(properties, dict):
        return False
    prop = properties.get(prop_name)
    if not isinstance(prop, dict):
        return False
    return _truthy(prop.get("required"))


def _event_property_type(event_config: dict, prop_name: str) -> str | None:
    properties = event_config.get("properties") or {}
    if not isinstance(properties, dict):
        return None
    prop = properties.get(prop_name)
    if not isinstance(prop, dict):
        return None
    prop_type = prop.get("type")
    return str(prop_type) if prop_type is not None else None


def check_phase2_pay_intent_event_and_callsite(ctx: dict) -> tuple[bool, str, str | None]:
    event_config = _events_map(ctx).get("pay_intent")
    if not isinstance(event_config, dict):
        return (
            False,
            "experiment/EVENTS.yaml does not define `pay_intent`.",
            "Add `pay_intent` to experiment/EVENTS.yaml with funnel_stage: monetize and required properties `price_cents` and `utm_campaign`.",
        )
    if str(event_config.get("funnel_stage") or "") != "monetize":
        return (
            False,
            "`pay_intent` must use funnel_stage: monetize.",
            "Set experiment/EVENTS.yaml events.pay_intent.funnel_stage to `monetize`.",
        )
    if "payment" in _event_requires(event_config):
        return (
            False,
            "`pay_intent` must not have requires: [payment]; it is a fake-door monetize event.",
            "Remove `payment` from experiment/EVENTS.yaml events.pay_intent.requires.",
        )
    if not _event_property_required(event_config, "utm_campaign"):
        return (
            False,
            "`pay_intent` must define properties.utm_campaign.required: true.",
            "Add `utm_campaign: { type: string, required: true }` under experiment/EVENTS.yaml events.pay_intent.properties.",
        )
    if not _event_property_required(event_config, "price_cents"):
        return (
            False,
            "`pay_intent` must define properties.price_cents.required: true.",
            "Add `price_cents: { type: number, required: true }` under experiment/EVENTS.yaml events.pay_intent.properties.",
        )
    if _event_property_type(event_config, "price_cents") != "number":
        return (
            False,
            "`pay_intent` must define properties.price_cents.type: number.",
            "Set experiment/EVENTS.yaml events.pay_intent.properties.price_cents to `{ type: number, required: true }`.",
        )

    root = _root(ctx)
    callsites: list[str] = []
    missing_args: list[str] = []
    for path in _source_files(root):
        text = _read_text(path)
        for args in _track_event_call_args(text, "pay_intent"):
            rel = _rel(root, path)
            callsites.append(rel)
            missing = []
            if not re.search(r"\butm_campaign\b", args):
                missing.append("utm_campaign")
            if not re.search(r"\bprice_cents\b", args):
                missing.append("price_cents")
            if not missing:
                return True, f"{rel} tracks pay_intent and passes utm_campaign + price_cents.", None
            missing_args.append(f"{rel} (missing: {', '.join(missing)})")

    if callsites:
        listed = ", ".join(sorted(set(missing_args or callsites)))
        return (
            False,
            f"`pay_intent` callsite(s) omit required attribution/price arguments: {listed}.",
            "Pass both `utm_campaign` and `price_cents` at the fake-door callsite, e.g. `trackPayIntent({ plan, price_cents, gclid, utm_campaign })`.",
        )
    return (
        False,
        "No `trackPayIntent(...)` or `track('pay_intent', ...)` callsite found outside analytics wrappers.",
        "Call `trackPayIntent({ plan, price_cents, gclid, utm_campaign })` when the fake-door Upgrade CTA is clicked.",
    )


def _pay_intent_route_files(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for ext in ROUTE_EXTENSIONS:
        candidates.append(root / "src" / "app" / "api" / "pay-intent" / f"route{ext}")
        candidates.append(root / "src" / "pages" / "api" / f"pay-intent{ext}")
    return [path for path in candidates if path.exists() and path.is_file()]


def _has_post_handler(text: str) -> bool:
    return bool(
        re.search(r"\bexport\s+(?:async\s+)?function\s+POST\s*\(", text)
        or re.search(r"\bPOST\s*[:=]\s*(?:async\s*)?(?:function\s*)?\(", text)
        or re.search(r"\breq\.method\s*={2,3}\s*['\"]POST['\"]", text)
        or re.search(r"\brequest\.method\s*={2,3}\s*['\"]POST['\"]", text)
    )


def _route_inserts_pay_intent_with_attribution(text: str) -> bool:
    return bool(
        re.search(r"\bpay_intent\b", text)
        and re.search(r"(?:\.insert\s*\(|\binsert\b)", text, re.IGNORECASE)
        and re.search(r"\bgclid\b", text)
        and re.search(r"\butm_campaign\b", text)
    )


def check_phase2_pay_intent_route(ctx: dict) -> tuple[bool, str, str | None]:
    root = _root(ctx)
    route_files = _pay_intent_route_files(root)
    if not route_files:
        return (
            False,
            "No POST /api/pay-intent route file found.",
            "Add src/app/api/pay-intent/route.ts with an exported POST handler that inserts a pay_intent row including gclid and utm_campaign.",
        )
    for path in route_files:
        text = _read_text(path)
        rel = _rel(root, path)
        if _has_post_handler(text) and _route_inserts_pay_intent_with_attribution(text):
            return True, f"{rel} exports POST and inserts pay_intent with gclid + utm_campaign.", None
    listed = ", ".join(_rel(root, path) for path in route_files)
    return (
        False,
        f"pay-intent route exists but does not prove POST insertion with both gclid and utm_campaign: {listed}.",
        "Ensure the POST /api/pay-intent handler inserts into `pay_intent` and includes both `gclid` and `utm_campaign` in the inserted row.",
    )


def _sql_files(root: Path) -> list[Path]:
    excluded = {".git", "node_modules", ".next", "dist", "build"}
    return [
        path
        for path in sorted(root.rglob("*.sql"))
        if path.is_file() and not (excluded & set(path.parts))
    ]


def _migration_defines_pay_intent_table(text: str) -> bool:
    return bool(
        re.search(
            r"\bcreate\s+table(?:\s+if\s+not\s+exists)?\s+(?:public\.)?pay_intent\b",
            text,
            re.IGNORECASE,
        )
    )


def _migration_has_pay_intent_rls(text: str) -> bool:
    return bool(
        re.search(
            r"\balter\s+table\s+(?:public\.)?pay_intent\s+enable\s+row\s+level\s+security\b",
            text,
            re.IGNORECASE,
        )
    )


def check_phase2_pay_intent_migration(ctx: dict) -> tuple[bool, str, str | None]:
    root = _root(ctx)
    candidates: list[str] = []
    for path in _sql_files(root):
        text = _read_text(path)
        if "pay_intent" not in text:
            continue
        candidates.append(_rel(root, path))
        has_table = _migration_defines_pay_intent_table(text)
        has_columns = bool(re.search(r"\bgclid\b", text) and re.search(r"\butm_campaign\b", text))
        has_fk = bool(
            re.search(r"\breferences\s+auth\.users\s*\(\s*id\s*\)", text, re.IGNORECASE)
        )
        has_rls = _migration_has_pay_intent_rls(text)
        if has_table and has_columns and has_fk and has_rls:
            return True, f"{_rel(root, path)} defines pay_intent attribution columns, auth.users FK, and RLS.", None
    if candidates:
        listed = ", ".join(candidates)
        return (
            False,
            f"pay_intent migration found but missing gclid, utm_campaign, auth.users(id) FK, or RLS: {listed}.",
            "Update the pay_intent migration to include gclid and utm_campaign columns, `user_id uuid references auth.users(id)`, and `alter table pay_intent enable row level security`.",
        )
    return (
        False,
        "No SQL migration defining `pay_intent` was found.",
        "Add a Supabase migration for `pay_intent` with gclid, utm_campaign, `user_id` FK to auth.users(id), and RLS enabled.",
    )


def _fake_door_cta_candidates(root: Path) -> list[Path]:
    return _source_files_matching(
        root,
        lambda text: bool(
            re.search(r"\bupgrade\b", text, re.IGNORECASE)
            and re.search(r"(trackPayIntent|pay[-_]intent|/api/pay-intent)", text)
        ),
    )


def _fake_door_entry_files(root: Path) -> list[Path]:
    entries = set(_pay_intent_route_files(root))
    entries.update(_fake_door_cta_candidates(root))
    entries.update(
        _source_files_matching(
            root,
            lambda text: bool(re.search(r"(trackPayIntent|/api/pay-intent)", text)),
        )
    )
    return sorted(entries)


def _has_auth_activation_render_guard(text: str) -> bool:
    auth = re.search(
        r"\b(user|currentUser|authUser|session|isAuthenticated|authenticated|auth)\b",
        text,
        re.IGNORECASE,
    )
    activation = re.search(
        r"\b(hasActivated|isActivated|activated|activation|activatedAt|valueDelivered|completedActivation|hasCompleted(?:Onboarding|Setup))\b",
        text,
    )
    render_guard = re.search(r"\breturn\s+(?:null|false)\b", text) or re.search(
        r"\b(canUpgrade|canShowUpgrade|showUpgrade|eligibleForUpgrade)\b\s*&&",
        text,
    )
    combined_guard = re.search(
        r"\b(user|currentUser|authUser|session|isAuthenticated|authenticated)\b[\s\S]{0,240}&&[\s\S]{0,240}\b(hasActivated|isActivated|activated|activation|valueDelivered|completedActivation)\b",
        text,
    ) or re.search(
        r"\b(hasActivated|isActivated|activated|activation|valueDelivered|completedActivation)\b[\s\S]{0,240}&&[\s\S]{0,240}\b(user|currentUser|authUser|session|isAuthenticated|authenticated)\b",
        text,
    )
    return bool(auth and activation and (render_guard or combined_guard))


def check_phase2_upgrade_cta_guard(ctx: dict) -> tuple[bool, str, str | None]:
    root = _root(ctx)
    candidates = _fake_door_cta_candidates(root)
    if not candidates:
        return (
            False,
            "No fake-door Upgrade CTA source file was found.",
            "Add an Upgrade CTA that calls `trackPayIntent` and POSTs to `/api/pay-intent`, visible only after auth and activation.",
        )
    for path in candidates:
        text = _read_text(path)
        if _has_auth_activation_render_guard(text):
            return True, f"{_rel(root, path)} guards the Upgrade CTA with auth and activation signals.", None
    listed = ", ".join(_rel(root, path) for path in candidates)
    return (
        False,
        f"Upgrade CTA found without an auth + activation render guard: {listed}.",
        "Render the fake-door Upgrade CTA only after the user is authenticated and has reached activation; do not mount it unconditionally.",
    )


def _is_payment_provider_import(spec: str) -> bool:
    if spec.startswith(".") or spec.startswith("@/"):
        return False
    return bool(PAYMENT_PROVIDER_IMPORT_RE.search(spec))


def check_phase2_no_payment_provider_on_fake_door_path(ctx: dict) -> tuple[bool, str, str | None]:
    root = _root(ctx)
    entries = _fake_door_entry_files(root)
    if not entries:
        return (
            False,
            "No fake-door CTA or /api/pay-intent route path was found.",
            "Add the fake-door CTA and POST /api/pay-intent route before running `/ads-ready phase-2`.",
        )

    aliases = _load_tsconfig_paths(root)
    queue = [path.resolve() for path in entries]
    visited: set[Path] = set()
    cap = 200
    while queue and len(visited) < cap:
        current = queue.pop(0)
        if current in visited or not current.exists():
            continue
        visited.add(current)
        text = _read_text(current)
        for spec in _import_specs(text):
            if _is_payment_provider_import(spec):
                return (
                    False,
                    f"{_rel(root, current)} imports payment provider SDK `{spec}` from the fake-door path.",
                    "Remove Stripe/checkout/payment SDK imports from the fake-door CTA and /api/pay-intent route path; Phase 2 records intent only and must not open checkout or charge.",
                )
            resolved = _resolve_import(root, current, spec, aliases)
            if resolved and resolved.resolve() not in visited and len(visited) + len(queue) < cap:
                queue.append(resolved.resolve())

    listed = ", ".join(sorted(_rel(root, path) for path in entries))
    return True, f"No payment provider import reachable from fake-door entry path(s): {listed}.", None


def check_events_yaml_all_implemented(ctx: dict) -> tuple[bool, str, str | None]:
    unknown_requires = _unknown_event_requires(ctx)
    if unknown_requires:
        event, requirement = unknown_requires[0]
        return (
            False,
            f"EVENTS.yaml event `{event}` has requires: `{requirement}` which is not a known stack key.",
            f"EVENTS.yaml event {event} has requires: {requirement} which is not a known stack key (typo? add to experiment.yaml stack first).",
        )
    unknown_archetypes = _unknown_event_archetypes(ctx)
    if unknown_archetypes:
        event, archetype = unknown_archetypes[0]
        known = ", ".join(sorted(_known_archetypes()))
        message = f"EVENTS.yaml event {event} has archetypes: {archetype} which is not a known archetype (typo? known archetypes: {known})."
        return False, message, message
    events = sorted(_filtered_events(ctx))
    if not events:
        return True, "EVENTS.yaml has no applicable events.", None
    root = _root(ctx)
    files = _source_files(root)
    missing = []
    for event in events:
        if not any(_file_has_event_call(_read_text(path), event) for path in files):
            missing.append(event)
    if not missing:
        return True, "All applicable EVENTS.yaml events have implementation call sites.", None
    event = missing[0]
    return (
        False,
        f"Event `{event}` is declared in EVENTS.yaml but has no call site.",
        f"Event '{event}' declared in EVENTS.yaml but no call site invokes track('{event}') or track{_pascal_case(event)}(...) outside src/lib/events.ts. Add the call to the page/component that triggers this event, or remove the event from EVENTS.yaml.",
    )


def _tracked_events_in_code(root: Path) -> list[tuple[str, str]]:
    tracked: list[tuple[str, str]] = []
    for path in _source_files(root):
        text = _read_text(path)
        rel = _rel(root, path)
        for match in TRACK_RAW_RE.finditer(text):
            tracked.append((match.group(1), rel))
        for match in TRACK_WRAPPER_RE.finditer(text):
            wrapper = match.group(1)
            if wrapper == "ServerEvent":
                continue
            tracked.append((_snake_case(wrapper), rel))
    return tracked


def check_no_unauthorized_track_calls(ctx: dict) -> tuple[bool, str, str | None]:
    allowed = _filtered_events(ctx)
    for event, rel in _tracked_events_in_code(_root(ctx)):
        if event not in allowed:
            return (
                False,
                f"Event `{event}` is tracked in code but not declared in EVENTS.yaml ({rel}).",
                f"Event '{event}' tracked in code (file {rel}) but not declared in EVENTS.yaml. Add it to EVENTS.yaml `events:` map (with proper funnel_stage + requires/archetypes), or remove the track() call.",
            )
    return True, "No track() calls outside EVENTS.yaml.", None


def _is_signup_event(event: str) -> bool:
    if event in SIGNUP_EVENT_NAMES:
        return True
    if event.startswith("early_access_"):
        return True
    return bool(SIGNUP_EVENT_RE.match(event))


def _signup_tracks(text: str) -> list[str]:
    events = []
    for match in TRACK_RAW_RE.finditer(text):
        event = match.group(1)
        if _is_signup_event(event):
            events.append(event)
    for match in TRACK_WRAPPER_RE.finditer(text):
        event = _snake_case(match.group(1))
        if _is_signup_event(event):
            events.append(event)
    return events


def _signup_search_roots(root: Path) -> list[Path]:
    paths: list[Path] = []
    for rel in ("src/app", "src/components", "src/hooks"):
        base = root / rel
        if base.exists():
            paths.extend(list(base.rglob("*.ts")) + list(base.rglob("*.tsx")))
    lib = root / "src/lib"
    if lib.exists():
        paths.extend(list(lib.glob("auth*.ts")) + list(lib.glob("auth*.tsx")))
    return [p for p in sorted(set(paths)) if p.is_file() and not _is_excluded_source(root, p)]


def _imports_auth_utility(spec: str) -> bool:
    return bool(
        re.match(r"@/(lib/auth|hooks/use-auth|hooks/use-supabase|lib/supabase)", spec)
        or re.match(r"\.{1,2}/.*(auth|use-auth|use-supabase|supabase)", spec)
    )


def check_identify_in_signup(ctx: dict) -> tuple[bool, str, str | None]:
    root = _root(ctx)
    aliases = _load_tsconfig_paths(root)
    files = _signup_search_roots(root)
    signup_files: list[tuple[Path, str]] = []
    for path in files:
        text = _read_text(path)
        events = _signup_tracks(text)
        if not events:
            continue
        event = events[0]
        signup_files.append((path, event))
        if re.search(r"\bidentify\s*\(", text):
            return True, f"{_rel(root, path)} tracks `{event}` and calls identify().", None
        for spec in _import_specs(text):
            if not _imports_auth_utility(spec):
                continue
            resolved = _resolve_import(root, path, spec, aliases)
            if resolved and re.search(r"\bidentify\s*\(", _read_text(resolved)):
                return (
                    True,
                    f"{_rel(root, path)} tracks `{event}` and imports identify-capable auth utility {_rel(root, resolved)}.",
                    None,
                )
    if signup_files:
        path, event = signup_files[0]
        return (
            False,
            f"{_rel(root, path)} tracks signup event `{event}` but no identify() call is reachable.",
            f"File {_rel(root, path)} tracks signup event '{event}' but no identify() call is reachable from this file (neither in-file nor via imported auth utility). Without identify(), the anon->signed-in distinct_id link breaks. Add `identify(user.id)` to the signup handler OR ensure the imported auth utility calls it on session creation.",
        )
    return (
        False,
        "No signup-shaped tracking event was found.",
        "Add a signup completion tracking event and call `identify(user.id)` when the user signs up.",
    )


def check_1(ctx: dict) -> tuple[bool, str, str | None]:
    return check_project_name_drift(ctx)


def check_2(ctx: dict) -> tuple[bool, str, str | None]:
    return check_no_posthog_placeholder(ctx)


def check_3(ctx: dict) -> tuple[bool, str, str | None]:
    return check_analytics_module_wired(ctx)


def check_4(ctx: dict) -> tuple[bool, str, str | None]:
    return check_no_raw_capture(ctx)


def check_5(ctx: dict) -> tuple[bool, str, str | None]:
    return check_signup_events_implemented(ctx)


def check_6(ctx: dict) -> tuple[bool, str, str | None]:
    return check_posthog_team_key(ctx)


def check_7(ctx: dict) -> tuple[bool, str, str | None]:
    return check_supabase_team_org(ctx)


def check_8(ctx: dict) -> tuple[bool, str, str | None]:
    return check_railway_team_workspace(ctx)


def check_9(ctx: dict) -> tuple[bool, str, str | None]:
    return check_vercel_team_account(ctx)


def check_10(ctx: dict) -> tuple[bool, str, str | None]:
    return check_stripe_team_account(ctx)


def check_11(ctx: dict) -> tuple[bool, str, str | None]:
    return check_events_yaml_all_implemented(ctx)


def check_12(ctx: dict) -> tuple[bool, str, str | None]:
    return check_no_unauthorized_track_calls(ctx)


def check_13(ctx: dict) -> tuple[bool, str, str | None]:
    return check_identify_in_signup(ctx)
