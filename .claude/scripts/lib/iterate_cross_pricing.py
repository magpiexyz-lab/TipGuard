#!/usr/bin/env python3
"""Discover each MVP's monthly price from its GitHub repo (state x0c).

Feeds the CPC unit-economics gate (iterate_cross_verdicts.compute_cpc_flags): the
gate forces NO_GO when an over-cap MVP's implied CAC (cpc_usd * cpc_payback_multiple)
exceeds monthly_price_usd. This module fuzzy-matches each over-cap MVP to its
magpiexyz-lab repo, fetches price-candidate snippets from the spec + pricing files,
and (after the lead LLM extracts the price in state-x0c Step 2) persists
monthly_price_usd to the operator config with provenance.

Best-effort: missing gh / repo / price → the MVP stays unpriced and the gate stays
dormant for it (the existing cpc_price_unmapped advisory covers it). Pricing
discovery never blocks the skill.

Mirrors iterate_cross_db.py (fuzzy-match + config-write convention) and the x2
classify flow (prepare → lead extracts → persist).

Subcommands:
  prepare  --context --config --hosts --output
           select over-cap unpriced MVPs, resolve repos, fetch price snippets,
           write the extraction bundle the lead reads in state-x0c Step 2.
  persist  --context --config --proposals [--now]
           write lead-proposed prices + provenance to config; stamp every context
           record with monthly_price_usd / price_source / price_unmapped_reason.
"""
from __future__ import annotations

import argparse
import base64
import datetime
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from iterate_cross_classify import dump_yaml, load_yaml, match_key  # noqa: E402

GH_ORG = "magpiexyz-lab"

# Files scanned for a monthly price, priority order. experiment.yaml is the
# dominant source (recon: ~74% of hits); the pricing component is the structured
# fallback for products with checkout infra.
PRICE_FILES = (
    "experiment/experiment.yaml",
    "src/lib/plan.ts",
    "src/lib/pricing.ts",
    "src/app/pricing/page.tsx",
    "src/config/pricing.ts",
)

# Candidate price lines. Deliberately precise on dollar-amounts + code constants +
# waitlist/free markers; the lead LLM does the real disambiguation (own price vs
# competitor vs target-user income vs annual vs tiers), so we only surface
# candidate lines + context to keep the lead's input small (like x2's catalog).
_PRICE_LINE = re.compile(
    r"\$\s?\d|\bUSD\s?\d|\d+\s?(?:/mo\b|/month\b|per month|a month|monthly)"
    r"|amount_cents|price_?(?:usd|cents)|\bwaitlist\b|free (?:tier|plan|forever|trial)",
    re.I,
)

DEFAULT_MAX_CPC = 2.5
DEFAULT_FX = {"USD": 1.0, "SGD": 0.74}

PRICING_FIELDS = ("monthly_price_usd", "price_source", "price_unmapped_reason")


# ---------- pure helpers (unit-testable, no I/O) ----------

def _thresholds(config: dict) -> dict:
    return config.get("thresholds") or {}


def cpc_usd(mvp: dict, fx: dict | None, basis: str = "usd") -> float | None:
    """Native ga_cpc → USD (mirrors compute_cpc_flags). None when no CPC data."""
    ga_cpc = mvp.get("ga_cpc")
    if ga_cpc is None:
        return None
    if basis != "usd":
        return round(float(ga_cpc), 4)
    currency = mvp.get("ga_currency") or "USD"
    rate = (fx or {}).get(currency)
    if rate is None:
        rate = 1.0
    return round(float(ga_cpc) * rate, 4)


def is_over_cap(mvp: dict, config: dict) -> bool:
    th = _thresholds(config)
    max_cpc = th.get("max_cpc", DEFAULT_MAX_CPC)
    if max_cpc is None:
        return False
    c = cpc_usd(mvp, config.get("fx_to_usd", DEFAULT_FX), config.get("max_cpc_basis", "usd"))
    return c is not None and c > float(max_cpc)


def select_over_cap_targets(mvps: list[dict], config: dict) -> list[str]:
    """MVP names needing a price: over cap, no cached monthly_price_usd, not
    operator-locked, no active cpc_exception (gate bypassed), not orphan."""
    mappings = config.get("mvp_mappings") or {}
    targets = []
    for m in mvps:
        if m.get("orphan"):
            continue
        name = m.get("name")
        mp = mappings.get(name) or {}
        if mp.get("monthly_price_usd") is not None:
            continue  # cache hit
        if mp.get("price_classified_by") == "operator":
            continue  # operator-locked
        if mp.get("cpc_exception"):
            continue  # gate bypassed → no price needed
        if is_over_cap(m, config):
            targets.append(name)
    return targets


def resolve_repo(name: str, repo_names: list[str], mappings: dict, repo_aliases: dict) -> str | None:
    """github_repo override > repo_aliases > match_key fuzzy match. None if unmatched.

    Legacy exact-name layer, kept for back-compat. Production call sites use
    resolve_repo_layered (adds name-index / description / homepage layers that
    resolve repos named differently from their product — SEO-optimiser for
    lumen, freelancer-income-hub for income-flow)."""
    mp = mappings.get(name) or {}
    if mp.get("github_repo"):
        return mp["github_repo"]
    if repo_aliases.get(name):
        return repo_aliases[name]
    key = match_key(name)
    for r in repo_names:
        if match_key(r) == key:
            return r
    return None


def _experiment_name(text: str | None) -> str | None:
    """Top-level `name:` value from an experiment.yaml body (no YAML parse needed)."""
    if not text:
        return None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("name:"):
            v = s.split(":", 1)[1].strip().strip("\"'")
            return v or None
    return None


def resolve_repo_layered(
    name: str,
    records: list[dict],
    mappings: dict,
    repo_aliases: dict,
    name_index: dict | None = None,
    deploy_host: str | None = None,
) -> tuple[str | None, str | None]:
    """(repo, method) via layered high-precision signals; (None, None) if unmatched.

    Layers, most authoritative first:
      override    — mvp_mappings.<name>.github_repo (operator pin)
      alias       — config repo_aliases
      exact-name  — match_key(repo name) == match_key(mvp name) (the legacy layer)
      name-index  — org-wide experiment.yaml `name:` scan (bootstrap writes the
                    canonical project_name verbatim, so this is THE join key;
                    see load_or_refresh_name_index)
      desc-prefix — repo description starts with "<name>:" (org convention:
                    'lumen: AI search visibility tracker' on SEO-optimiser)
      homepage    — MVP name key (or deploy host key) inside the repo homepage
                    URL (freelancer-income-hub → income-flow-three.vercel.app);
                    keys shorter than 5 chars are skipped (false-positive guard)

    `records` rows are {name, description, homepage, pushed_at} from
    list_org_repo_records(). A plain repo-name list also works (dict-less rows
    are coerced), degrading gracefully to the exact-name layer.
    """
    mp = mappings.get(name) or {}
    if mp.get("github_repo"):
        return mp["github_repo"], "override"
    if repo_aliases.get(name):
        return repo_aliases[name], "alias"

    recs = [r if isinstance(r, dict) else {"name": r} for r in records]
    key = match_key(name)
    for r in recs:
        if match_key(r.get("name") or "") == key:
            return r["name"], "exact-name"

    if name_index and name_index.get(name):
        return name_index[name], "name-index"

    lowname = name.lower()
    for r in recs:
        desc = (r.get("description") or "").strip().lower()
        if desc.startswith(lowname + ":"):
            return r["name"], "desc-prefix"

    host_key = match_key((deploy_host or "").split(".")[0]) if deploy_host else ""
    for r in recs:
        home = match_key(r.get("homepage") or "")
        if not home:
            continue
        if key and len(key) >= 5 and key in home:
            return r["name"], "homepage"
        if host_key and len(host_key) >= 5 and host_key in home:
            return r["name"], "homepage"
    return None, None


def extract_price_snippets(text: str | None, path: str, ctx: int = 1, max_lines: int = 30) -> list[dict]:
    """Candidate price lines (matching _PRICE_LINE) with ±ctx context, capped."""
    if not text:
        return []
    lines = text.splitlines()
    keep: set[int] = set()
    for i, ln in enumerate(lines):
        if _PRICE_LINE.search(ln):
            for j in range(max(0, i - ctx), min(len(lines), i + ctx + 1)):
                keep.add(j)
    out = [{"file": path, "line": j + 1, "text": lines[j].strip()[:300]} for j in sorted(keep)]
    return out[:max_lines]


def _empty_pricing(reason: str) -> dict:
    return {"monthly_price_usd": None, "price_source": None, "price_unmapped_reason": reason}


def _live_url(mvp: dict, hosts: dict) -> str | None:
    host = (mvp.get("deploy_domain") or hosts.get(mvp.get("name"), "") or "").strip()
    host = host.replace("https://", "").replace("http://", "").rstrip("/")
    return f"https://{host}/pricing" if host else None


# ---------- gh transport (mockable via monkeypatching _gh) ----------

def _gh(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    try:
        r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        return 1, "", str(e)


def gh_available() -> bool:
    rc, _, _ = _gh(["auth", "status"], timeout=15)
    return rc == 0


def list_org_repos(org: str = GH_ORG) -> list[str]:
    rc, out, _ = _gh(["repo", "list", org, "--limit", "500", "--json", "name"], timeout=60)
    if rc != 0:
        return []
    try:
        return [r["name"] for r in json.loads(out or "[]")]
    except (ValueError, TypeError, KeyError):
        return []


def list_org_repo_records(org: str = GH_ORG) -> list[dict]:
    """Org repos with the metadata the layered resolver matches on."""
    rc, out, _ = _gh(
        ["repo", "list", org, "--limit", "500", "--json", "name,description,homepageUrl,pushedAt"],
        timeout=60,
    )
    if rc != 0:
        return []
    try:
        rows = json.loads(out or "[]")
    except (ValueError, TypeError):
        return []
    return [
        {
            "name": r.get("name") or "",
            "description": r.get("description") or "",
            "homepage": r.get("homepageUrl") or "",
            "pushed_at": r.get("pushedAt") or "",
        }
        for r in rows
        if isinstance(r, dict) and r.get("name")
    ]


NAME_INDEX_CACHE = ".runs/gh-name-index.json"
NAME_INDEX_CACHE_ENV = "ITERATE_CROSS_NAME_INDEX_CACHE"  # test isolation override


def load_or_refresh_name_index(
    records: list[dict],
    cache_path: str | None = None,
    max_fetches: int = 250,
) -> dict:
    """Authoritative project_name → repo map from each org repo's experiment.yaml.

    /bootstrap state-3 writes experiment.yaml `name:` verbatim from the canonical
    project_name, so this index joins MVPs to repos regardless of how the repo
    itself is named. Incremental: a repo whose pushed_at matches the cache entry
    is not re-fetched (cold build ≈ one contents call per repo; warm runs fetch
    only repos pushed since). Repos without experiment.yaml cache project_name
    null and are likewise skipped until pushed again. `max_fetches` bounds a
    single run's API spend; the remainder refreshes on subsequent runs.
    """
    cache_path = cache_path or os.environ.get(NAME_INDEX_CACHE_ENV) or NAME_INDEX_CACHE
    try:
        cache = json.load(open(cache_path))
    except (OSError, ValueError):
        cache = {}
    repos_cache = dict(cache.get("repos") or {})
    fetched = 0
    for rec in records:
        rname = rec.get("name")
        if not rname:
            continue
        cached = repos_cache.get(rname)
        if cached and cached.get("pushed_at") == rec.get("pushed_at"):
            continue
        if fetched >= max_fetches:
            continue
        text = fetch_file(rname, "experiment/experiment.yaml")
        fetched += 1
        repos_cache[rname] = {
            "pushed_at": rec.get("pushed_at") or "",
            "project_name": _experiment_name(text),
        }
    payload = {
        "repos": repos_cache,
        "refreshed_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fetched_last_run": fetched,
    }
    try:
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(payload, f, indent=1)
    except OSError:
        pass  # cache is an accelerator; resolution still works this run
    index: dict = {}
    for repo_name, meta in repos_cache.items():
        pn = (meta or {}).get("project_name")
        if pn and pn not in index:
            index[pn] = repo_name
    return index


def fetch_file(repo: str, path: str, org: str = GH_ORG) -> str | None:
    """File contents from `<org>/<repo>` — or any `<owner>/<repo>` slug (repos
    outside the org, e.g. resolved via the Vercel link channel)."""
    slug = repo if "/" in repo else f"{org}/{repo}"
    rc, out, _ = _gh(["api", f"repos/{slug}/contents/{path}", "--jq", ".content"], timeout=30)
    if rc != 0 or not out.strip():
        return None
    try:
        return base64.b64decode(out).decode("utf-8", "replace")
    except (ValueError, TypeError):
        return None


# ---------- subcommands ----------

def cmd_prepare(context_path: str, config_path: str, hosts_path: str | None, output_path: str) -> int:
    ctx = json.load(open(context_path))
    config = load_yaml(config_path)
    mvps = ctx.get("mvps", [])
    mappings = config.get("mvp_mappings") or {}
    repo_aliases = config.get("repo_aliases") or {}

    hosts = {}
    if hosts_path and os.path.exists(hosts_path):
        try:
            hosts = json.load(open(hosts_path)) or {}
        except (ValueError, OSError):
            hosts = {}

    targets = select_over_cap_targets(mvps, config)
    records = list_org_repo_records() if targets else []
    name_index = load_or_refresh_name_index(records) if records else {}
    by_name = {m.get("name"): m for m in mvps}

    to_extract, repo_empty_try_live, no_source = [], [], []
    for name in targets:
        m = by_name.get(name, {})
        repo, _method = resolve_repo_layered(
            name, records, mappings, repo_aliases, name_index,
            deploy_host=hosts.get(name),
        )
        live_url = _live_url(m, hosts)
        snippets, files_found = [], []
        if repo:
            for path in PRICE_FILES:
                text = fetch_file(repo, path)
                if text is None:
                    continue
                files_found.append(path)
                snippets.extend(extract_price_snippets(text, path))
        entry = {
            "name": name,
            "repo": repo,
            "live_pricing_url": live_url,
            "files_found": files_found,
            "snippets": snippets,
        }
        if snippets:
            to_extract.append(entry)
        elif live_url:
            repo_empty_try_live.append(entry)
        else:
            no_source.append(entry)

    out = {
        "to_extract": to_extract,
        "repo_empty_try_live": repo_empty_try_live,
        "no_source": no_source,
        "target_count": len(targets),
    }
    with open(output_path, "w") as f:
        json.dump(out, f, indent=2)
    print(
        f"pricing-prepare: {len(targets)} over-cap targets → "
        f"{len(to_extract)} with repo snippets, {len(repo_empty_try_live)} live-only, "
        f"{len(no_source)} no source → {output_path}"
    )
    return 0


def cmd_persist(context_path: str, config_path: str, proposals_path: str, now_iso: str | None = None) -> int:
    now_iso = now_iso or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ctx = json.load(open(context_path))
    config = load_yaml(config_path)
    config.setdefault("mvp_mappings", {})
    mappings = config["mvp_mappings"]

    proposals = []
    if os.path.exists(proposals_path):
        proposals = json.load(open(proposals_path)) or []
    prop_by_name = {p["name"]: p for p in proposals if p.get("name")}

    written = 0
    for p in proposals:
        name = p.get("name")
        if not name:
            continue
        entry = mappings.get(name) or {}
        if entry.get("price_classified_by") == "operator":
            continue  # never overwrite an operator lock
        price = p.get("monthly_price_usd")
        entry["price_source"] = p.get("source")
        entry["price_classified_by"] = f"x0c-{p.get('confidence', 'unknown')}"
        entry["price_classified_at"] = now_iso
        if p.get("rationale"):
            entry["price_rationale"] = p["rationale"]
        if price is not None:
            entry["monthly_price_usd"] = float(price)
            written += 1
        mappings[name] = entry

    config["mvp_mappings"] = mappings
    dump_yaml(config, config_path)

    # Stamp every context record with a uniform pricing schema (for VERIFY).
    fx = config.get("fx_to_usd", DEFAULT_FX)
    basis = config.get("max_cpc_basis", "usd")
    for m in ctx.get("mvps", []):
        name = m.get("name")
        mp = mappings.get(name) or {}
        price = mp.get("monthly_price_usd")
        if price is not None:
            m["monthly_price_usd"] = float(price)
            m["price_source"] = mp.get("price_source")
            m["price_unmapped_reason"] = None
            continue
        if m.get("orphan"):
            m.update(_empty_pricing("orphan"))
            continue
        if not is_over_cap(m, config):
            m.update(_empty_pricing("not_over_cap"))
            continue
        prop = prop_by_name.get(name)
        if prop is not None:
            m.update(_empty_pricing(prop.get("price_unmapped_reason") or "free_or_waitlist"))
        else:
            m.update(_empty_pricing("not_found"))

    json.dump(ctx, open(context_path, "w"), indent=2)
    print(
        f"pricing-persist: wrote {written} prices to config; "
        f"stamped {len(ctx.get('mvps', []))} context records"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="x0c: discover MVP monthly prices from GitHub repos")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("prepare")
    pp.add_argument("--context", required=True)
    pp.add_argument("--config", required=True)
    pp.add_argument("--hosts", default=None)
    pp.add_argument("--output", required=True)

    ps = sub.add_parser("persist")
    ps.add_argument("--context", required=True)
    ps.add_argument("--config", required=True)
    ps.add_argument("--proposals", required=True)
    ps.add_argument("--now", default=None)

    args = ap.parse_args(argv)
    if args.cmd == "prepare":
        return cmd_prepare(args.context, args.config, args.hosts, args.output)
    if args.cmd == "persist":
        return cmd_persist(args.context, args.config, args.proposals, args.now)
    return 2


if __name__ == "__main__":
    sys.exit(main())
