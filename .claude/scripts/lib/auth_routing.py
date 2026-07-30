"""Auth-routing population for scaffold-wire (Issue #1077, PR3 gap fix).

scaffold-wire at state-14 calls this to populate .runs/auth-routing.json
with real signals (demo_mode_role from auth stack frontmatter, gated_routes
from emitted code, unreachable_demo_routes from role/demo cross-check).

Replaces the PR2 placeholder None values that made the consistency check
vacuous. PR3's drift detector reads this artifact via state-2b.
"""
import os
import re
import subprocess
from typing import Any


def parse_frontmatter(text: str) -> dict | None:
    """Line-anchored YAML frontmatter parser. Bare split('---') breaks on
    '# --- foo ---' comments inside list items (same fix as scaffold-init Step 5)."""
    if not text.startswith("---\n"):
        return None
    rest = text[4:]
    end = rest.find("\n---\n")
    if end < 0 and rest.endswith("\n---"):
        end = len(rest) - 4
    if end < 0:
        return None
    try:
        import yaml
    except ImportError:
        return None
    try:
        return yaml.safe_load(rest[:end]) or {}
    except Exception:
        return None


def read_demo_mode(auth_stack_path: str) -> dict[str, Any]:
    """Return {demo_mode_role, demo_user_metadata} from a stack file's
    YAML frontmatter `demo_mode` block. Defensive: missing keys → defaults.
    """
    if not os.path.exists(auth_stack_path):
        return {"demo_mode_role": None, "demo_user_metadata": {}}
    with open(auth_stack_path) as f:
        text = f.read()
    fm = parse_frontmatter(text)
    if not fm:
        return {"demo_mode_role": None, "demo_user_metadata": {}}
    dm = fm.get("demo_mode") or {}
    return {
        "demo_mode_role": dm.get("demo_mode_role"),
        "demo_user_metadata": dm.get("demo_user_metadata") or {},
    }


def discover_role_checks(src_root: str) -> list[str]:
    """Grep src/ for `app_metadata?.role === '<role>'` patterns. Returns
    the sorted unique list of role literals checked."""
    if not os.path.isdir(src_root):
        return []
    try:
        r = subprocess.run(
            ["grep", "-rE", "--include=*.ts", "--include=*.tsx",
             r"app_metadata\??\.role\s*===?\s*['\"]([a-z_]+)['\"]", src_root],
            capture_output=True, text=True,
        )
    except FileNotFoundError:
        return []
    roles: set[str] = set()
    for line in r.stdout.splitlines():
        m = re.search(r"['\"]([a-z_]+)['\"]", line)
        if m:
            roles.add(m.group(1))
    return sorted(roles)


def discover_gated_routes(src_root: str) -> list[str]:
    """Find admin-style route directories that imply role gating.

    Convention: src/app/admin/, src/app/(admin)/. Returns route patterns
    like '/admin'. Best-effort; not exhaustive.
    """
    routes: list[str] = []
    if not os.path.isdir(src_root):
        return routes
    candidates = [
        ("src/app/admin", "/admin"),
        ("src/app/(admin)", "/(admin)"),
        ("src/app/dashboard", "/dashboard"),  # may or may not be gated
    ]
    for d, route in candidates:
        full = os.path.join(os.path.dirname(src_root), d) \
            if os.path.basename(src_root) == "src" else os.path.join(src_root, d.replace("src/", ""))
        # Simpler: check relative-to-cwd
        rel_path = os.path.join(src_root if not src_root.endswith("src") else src_root, d.replace("src/", "")) \
            if False else d
        if os.path.isdir(rel_path):
            routes.append(route)
    return routes


def build_auth_routing(
    auth_stack: str | None,
    src_root: str = "src",
    auth_stack_dir: str = ".claude/stacks/auth",
) -> dict[str, Any]:
    """Build the auth-routing.json document for scaffold-wire to write."""
    demo = {"demo_mode_role": None, "demo_user_metadata": {}}
    if auth_stack and auth_stack != "none":
        demo = read_demo_mode(os.path.join(auth_stack_dir, f"{auth_stack}.md"))

    role_checks = discover_role_checks(src_root)
    gated_routes = discover_gated_routes(src_root)

    unreachable = []
    for role in role_checks:
        if role != demo["demo_mode_role"]:
            unreachable.append({
                "role": role,
                "demo_mode_role": demo["demo_mode_role"],
            })

    return {
        "_schema_version": 1,
        "_kind": "auth-routing",
        "auth_stack": auth_stack,
        "demo_mode_role": demo["demo_mode_role"],
        "demo_user_metadata": demo["demo_user_metadata"],
        "role_checks_observed": role_checks,
        "gated_routes": gated_routes,
        "unreachable_demo_routes": unreachable,
    }


def consistency_warnings(
    auth_routing: dict[str, Any],
    slot_intent: dict[str, Any] | None,
) -> list[str]:
    """Return warnings when slot-intent runtime_gate roles don't match
    emitted auth code. Empty list = consistent."""
    warnings: list[str] = []
    if not slot_intent or not slot_intent.get("design_slots_enabled"):
        return warnings

    role_checks = set(auth_routing.get("role_checks_observed") or [])
    demo_role = auth_routing.get("demo_mode_role")

    for slot_name, entry in (slot_intent.get("slots") or {}).items():
        gate = (entry or {}).get("runtime_gate")
        if not gate or not gate.get("role"):
            continue
        role = gate["role"]
        if role == demo_role:
            warnings.append(
                f"slot-intent declares runtime_gate.role={role!r} for "
                f"{slot_name!r} but demo_mode_role is the SAME — slot is "
                "reachable in DEMO_MODE; consider removing the gate."
            )
        elif role not in role_checks:
            warnings.append(
                f"slot-intent declares runtime_gate.role={role!r} for "
                f"{slot_name!r} but no `app_metadata.role === {role!r}` "
                "check found in src/. Either add the check (in middleware "
                "or page guards) or remove the slot's runtime_gate."
            )
    return warnings
