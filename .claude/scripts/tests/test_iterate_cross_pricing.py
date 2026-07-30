#!/usr/bin/env python3
"""Tests for .claude/scripts/lib/iterate_cross_pricing.py (state x0c).

Run:
  python3 -m pytest .claude/scripts/tests/test_iterate_cross_pricing.py -v
  # OR (no pytest dependency):
  python3 .claude/scripts/tests/test_iterate_cross_pricing.py
"""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

# Direct-run isolation (pytest gets the same via conftest.py): keep the gh
# name-index cache out of the production .runs/ artifact.
os.environ.setdefault(
    "ITERATE_CROSS_NAME_INDEX_CACHE",
    os.path.join(tempfile.gettempdir(), "gh-name-index-test.json"),
)

import iterate_cross_pricing as P  # noqa: E402

FX = {"USD": 1.0, "SGD": 0.74}
CFG = {"thresholds": {"max_cpc": 2.5}, "fx_to_usd": FX, "max_cpc_basis": "usd", "mvp_mappings": {}}


# ---------- pure helpers ----------

def test_cpc_usd_sgd_conversion():
    assert P.cpc_usd({"ga_cpc": 4.2694, "ga_currency": "SGD"}, FX) == 3.1594


def test_cpc_usd_none_without_cpc():
    assert P.cpc_usd({"ga_cpc": None}, FX) is None
    assert P.cpc_usd({}, FX) is None


def test_cpc_usd_native_basis():
    assert P.cpc_usd({"ga_cpc": 3.0, "ga_currency": "SGD"}, FX, basis="native") == 3.0


def test_is_over_cap():
    assert P.is_over_cap({"ga_cpc": 4.0, "ga_currency": "USD"}, CFG) is True
    assert P.is_over_cap({"ga_cpc": 2.0, "ga_currency": "USD"}, CFG) is False
    assert P.is_over_cap({"ga_cpc": None}, CFG) is False


def test_select_over_cap_targets_filters():
    mvps = [
        {"name": "over", "ga_cpc": 4.0, "ga_currency": "USD"},        # → target
        {"name": "cheap", "ga_cpc": 1.0, "ga_currency": "USD"},       # under cap
        {"name": "locked", "ga_cpc": 9.0, "ga_currency": "USD"},      # operator-locked
        {"name": "priced", "ga_cpc": 9.0, "ga_currency": "USD"},      # already priced
        {"name": "exc", "ga_cpc": 9.0, "ga_currency": "USD"},         # cpc_exception
        {"name": "orph", "ga_cpc": 9.0, "ga_currency": "USD", "orphan": True},
    ]
    cfg = dict(CFG, mvp_mappings={
        "locked": {"price_classified_by": "operator"},
        "priced": {"monthly_price_usd": 29},
        "exc": {"cpc_exception": {"reason": "x"}},
    })
    assert P.select_over_cap_targets(mvps, cfg) == ["over"]


def test_resolve_repo_exact_case_alias_override():
    repos = ["pmax-sentinel", "Bayt-Labs", "freelancer-income-hub"]
    assert P.resolve_repo("pmax-sentinel", repos, {}, {}) == "pmax-sentinel"
    assert P.resolve_repo("bayt-labs", repos, {}, {}) == "Bayt-Labs"  # case-only
    assert P.resolve_repo("income-flow", repos, {}, {"income-flow": "freelancer-income-hub"}) == "freelancer-income-hub"
    assert P.resolve_repo("x", repos, {"x": {"github_repo": "Custom"}}, {}) == "Custom"
    assert P.resolve_repo("nomatch", repos, {}, {}) is None


def test_resolve_repo_override_beats_fuzzy():
    repos = ["pmax-sentinel"]
    assert P.resolve_repo("pmax-sentinel", repos, {"pmax-sentinel": {"github_repo": "Other"}}, {}) == "Other"


# ---------- layered resolver (name-index / description / homepage) ----------

_RECORDS = [
    {"name": "Pmax-Sentinel", "description": "", "homepage": "", "pushed_at": "t1"},
    {"name": "SEO-optimiser", "description": "lumen: AI search visibility tracker", "homepage": "", "pushed_at": "t2"},
    {"name": "freelancer-income-hub", "description": "tracks payouts",
     "homepage": "https://income-flow-three.vercel.app", "pushed_at": "t3"},
    {"name": "DeadLink-Broken-Link-Uptime-Monitor-for-Solopreneurs", "description": "", "homepage": "", "pushed_at": "t4"},
]


def test_resolve_repo_layered_precedence_and_layers():
    # override beats everything
    assert P.resolve_repo_layered(
        "lumen", _RECORDS, {"lumen": {"github_repo": "Pinned"}}, {}
    ) == ("Pinned", "override")
    # alias beats matching layers
    assert P.resolve_repo_layered("lumen", _RECORDS, {}, {"lumen": "Aliased"}) == ("Aliased", "alias")
    # exact repo-name key match (case/hyphen-insensitive)
    assert P.resolve_repo_layered("pmax-sentinel", _RECORDS, {}, {}) == ("Pmax-Sentinel", "exact-name")
    # authoritative name-index (experiment.yaml `name:` scan)
    idx = {"dead-link": "DeadLink-Broken-Link-Uptime-Monitor-for-Solopreneurs"}
    assert P.resolve_repo_layered("dead-link", _RECORDS, {}, {}, name_index=idx) == (
        "DeadLink-Broken-Link-Uptime-Monitor-for-Solopreneurs", "name-index")
    # description prefix "<name>:"
    assert P.resolve_repo_layered("lumen", _RECORDS, {}, {}) == ("SEO-optimiser", "desc-prefix")
    # homepage host containment
    assert P.resolve_repo_layered("income-flow", _RECORDS, {}, {}) == (
        "freelancer-income-hub", "homepage")
    # deploy-host key also matches homepage
    assert P.resolve_repo_layered(
        "totally-different", _RECORDS, {}, {}, deploy_host="income-flow-three.vercel.app"
    ) == ("freelancer-income-hub", "homepage")
    # short keys never homepage-match (false-positive guard)
    assert P.resolve_repo_layered("app", _RECORDS, {}, {}) == (None, None)
    # nothing matches
    assert P.resolve_repo_layered("nomatch", _RECORDS, {}, {}) == (None, None)
    # plain repo-name list degrades to the exact layer
    assert P.resolve_repo_layered("pmax-sentinel", ["Pmax-Sentinel"], {}, {}) == (
        "Pmax-Sentinel", "exact-name")


def test_experiment_name_parse():
    assert P._experiment_name("kind: x\nname: tifa\nfoo: 1") == "tifa"
    assert P._experiment_name('name: "quoted-app"') == "quoted-app"
    assert P._experiment_name("nothing: here") is None
    assert P._experiment_name(None) is None


def test_name_index_incremental_refresh():
    yaml_a = "name: alpha-product\nthesis: t"
    calls = {"contents": 0}

    def gh(args, timeout=30):
        if args and args[0] == "api" and "/contents/" in args[1]:
            calls["contents"] += 1
            repo = args[1].split("/")[2]
            if repo == "A-Repo":
                return 0, base64.b64encode(yaml_a.encode()).decode(), ""
            return 1, "", "gh: Not Found (HTTP 404)"
        return 1, "", "unknown"

    records = [
        {"name": "A-Repo", "description": "", "homepage": "", "pushed_at": "p1"},
        {"name": "B-NoYaml", "description": "", "homepage": "", "pushed_at": "p1"},
    ]
    with tempfile.TemporaryDirectory() as td:
        cache = os.path.join(td, "idx.json")
        with patch.object(P, "_gh", gh):
            idx = P.load_or_refresh_name_index(records, cache_path=cache)
            assert idx == {"alpha-product": "A-Repo"}
            assert calls["contents"] == 2  # cold build fetches both
            # warm: same pushed_at → zero fetches
            idx = P.load_or_refresh_name_index(records, cache_path=cache)
            assert idx == {"alpha-product": "A-Repo"}
            assert calls["contents"] == 2
            # push moves → only the changed repo re-fetches
            records[0]["pushed_at"] = "p2"
            idx = P.load_or_refresh_name_index(records, cache_path=cache)
            assert calls["contents"] == 3
            assert idx == {"alpha-product": "A-Repo"}


def test_fetch_file_accepts_cross_org_slug():
    seen = {}

    def gh(args, timeout=30):
        seen["endpoint"] = args[1]
        return 0, base64.b64encode(b"body").decode(), ""

    with patch.object(P, "_gh", gh):
        assert P.fetch_file("someone/their-repo", "experiment/experiment.yaml") == "body"
        assert seen["endpoint"].startswith("repos/someone/their-repo/contents/")
        assert P.fetch_file("org-repo", "experiment/experiment.yaml") == "body"
        assert seen["endpoint"].startswith(f"repos/{P.GH_ORG}/org-repo/contents/")


def test_extract_price_snippets_matches_dollars():
    txt = ("intro\nthesis: subscribe at $19/mo to catch waste\n"
           "Optmyzr is $249+/mo\nconst amount_cents = 4900\nnothing here\nwaitlist only")
    sn = P.extract_price_snippets(txt, "experiment/experiment.yaml")
    joined = " | ".join(s["text"] for s in sn)
    assert "$19/mo" in joined and "amount_cents" in joined and "waitlist" in joined
    assert all(s["file"] == "experiment/experiment.yaml" for s in sn)


def test_extract_price_snippets_empty():
    assert P.extract_price_snippets("", "x") == []
    assert P.extract_price_snippets(None, "x") == []
    assert P.extract_price_snippets("no money words here\njust text", "x") == []


def test_extract_price_snippets_caps():
    txt = "\n".join(f"$however {i}/mo" for i in range(200))
    assert len(P.extract_price_snippets(txt, "x", max_lines=30)) == 30


def test_live_url():
    assert P._live_url({"name": "a", "deploy_domain": "a.com"}, {}) == "https://a.com/pricing"
    assert P._live_url({"name": "a"}, {"a": "b.draftlabs.org"}) == "https://b.draftlabs.org/pricing"
    assert P._live_url({"name": "a", "deploy_domain": "https://c.com/"}, {}) == "https://c.com/pricing"
    assert P._live_url({"name": "a"}, {}) is None


# ---------- prepare / persist (I/O, mock gh) ----------

def _fake_gh(repos=("Pmax-Sentinel",), files=None):
    """files: {(repo, path): text}. Missing file/path → rc 1 (404)."""
    files = files or {}

    def gh(args, timeout=30):
        if args[:2] == ["auth", "status"]:
            return 0, "", ""
        if args[:2] == ["repo", "list"]:
            return 0, json.dumps([{"name": r} for r in repos]), ""
        if args and args[0] == "api":
            endpoint = args[1]  # repos/ORG/REPO/contents/PATH
            parts = endpoint.split("/")
            repo = parts[2]
            path = "/".join(parts[4:])
            text = files.get((repo, path))
            if text is None:
                return 1, "", "gh: Not Found (HTTP 404)"
            return 0, base64.b64encode(text.encode()).decode(), ""
        return 1, "", "unknown"
    return gh


def _write(td, ctx, cfg):
    cp = os.path.join(td, "ctx.json")
    yp = os.path.join(td, "cfg.yaml")
    json.dump(ctx, open(cp, "w"))
    P.dump_yaml(cfg, yp)
    return cp, yp


def test_prepare_buckets_repo_live_and_none():
    ctx = {"mvps": [
        {"name": "pmax-sentinel", "ga_cpc": 4.0, "ga_currency": "USD", "deploy_domain": "pmax.com"},
        {"name": "nolive", "ga_cpc": 4.0, "ga_currency": "USD"},  # repo has no price file, no host
    ]}
    cfg = dict(CFG, mvp_mappings={})
    files = {("Pmax-Sentinel", "experiment/experiment.yaml"): "thesis: $19/mo\n"}
    with tempfile.TemporaryDirectory() as td:
        cp, yp = _write(td, ctx, cfg)
        outp = os.path.join(td, "out.json")
        with patch.object(P, "_gh", _fake_gh(repos=("Pmax-Sentinel",), files=files)):
            P.cmd_prepare(cp, yp, None, outp)
        out = json.load(open(outp))
    assert out["target_count"] == 2
    names_extract = [e["name"] for e in out["to_extract"]]
    assert "pmax-sentinel" in names_extract
    # nolive: no repo match (not in repo list), no host → no_source
    assert any(e["name"] == "nolive" for e in out["no_source"])
    pmax = next(e for e in out["to_extract"] if e["name"] == "pmax-sentinel")
    assert pmax["repo"] == "Pmax-Sentinel"
    assert any("$19/mo" in s["text"] for s in pmax["snippets"])


def test_prepare_repo_empty_falls_to_live():
    ctx = {"mvps": [{"name": "pmax-sentinel", "ga_cpc": 4.0, "ga_currency": "USD"}]}
    cfg = dict(CFG, mvp_mappings={})
    with tempfile.TemporaryDirectory() as td:
        cp, yp = _write(td, ctx, cfg)
        hp = os.path.join(td, "hosts.json")
        json.dump({"pmax-sentinel": "pmax.draftlabs.org"}, open(hp, "w"))
        outp = os.path.join(td, "out.json")
        # repo exists but has NO price files → empty snippets → live fallback bucket
        with patch.object(P, "_gh", _fake_gh(repos=("Pmax-Sentinel",), files={})):
            P.cmd_prepare(cp, yp, hp, outp)
        out = json.load(open(outp))
    assert [e["name"] for e in out["repo_empty_try_live"]] == ["pmax-sentinel"]
    assert out["repo_empty_try_live"][0]["live_pricing_url"] == "https://pmax.draftlabs.org/pricing"


def test_persist_writes_price_provenance_and_stamps_context():
    ctx = {"mvps": [
        {"name": "pmax-sentinel", "ga_cpc": 4.0, "ga_currency": "USD"},
        {"name": "cheap", "ga_cpc": 1.0, "ga_currency": "USD"},
    ]}
    cfg = dict(CFG, mvp_mappings={})
    proposals = [{"name": "pmax-sentinel", "monthly_price_usd": 19,
                  "source": "repo:experiment.yaml", "confidence": "high", "rationale": "thesis $19/mo"}]
    with tempfile.TemporaryDirectory() as td:
        cp, yp = _write(td, ctx, cfg)
        pp = os.path.join(td, "prop.json")
        json.dump(proposals, open(pp, "w"))
        P.cmd_persist(cp, yp, pp, now_iso="2026-06-27T00:00:00Z")
        out_cfg = P.load_yaml(yp)
        out_ctx = json.load(open(cp))
    e = out_cfg["mvp_mappings"]["pmax-sentinel"]
    assert e["monthly_price_usd"] == 19.0
    assert e["price_classified_by"] == "x0c-high"
    assert e["price_classified_at"] == "2026-06-27T00:00:00Z"
    assert e["price_source"] == "repo:experiment.yaml"
    by = {m["name"]: m for m in out_ctx["mvps"]}
    assert by["pmax-sentinel"]["monthly_price_usd"] == 19.0
    assert by["pmax-sentinel"]["price_unmapped_reason"] is None
    # under-cap MVP gets stamped not_over_cap
    assert by["cheap"]["price_unmapped_reason"] == "not_over_cap"
    assert by["cheap"]["monthly_price_usd"] is None


def test_persist_preserves_operator_lock():
    ctx = {"mvps": [{"name": "x", "ga_cpc": 9.0, "ga_currency": "USD"}]}
    cfg = dict(CFG, mvp_mappings={"x": {"price_classified_by": "operator", "monthly_price_usd": 99}})
    proposals = [{"name": "x", "monthly_price_usd": 5, "source": "repo", "confidence": "high"}]
    with tempfile.TemporaryDirectory() as td:
        cp, yp = _write(td, ctx, cfg)
        pp = os.path.join(td, "prop.json")
        json.dump(proposals, open(pp, "w"))
        P.cmd_persist(cp, yp, pp, now_iso="2026-06-27T00:00:00Z")
        out_cfg = P.load_yaml(yp)
    # operator lock untouched (still 99, still operator)
    assert out_cfg["mvp_mappings"]["x"]["monthly_price_usd"] == 99
    assert out_cfg["mvp_mappings"]["x"]["price_classified_by"] == "operator"


def test_persist_null_price_uses_proposal_reason():
    ctx = {"mvps": [{"name": "wl", "ga_cpc": 9.0, "ga_currency": "USD"}]}
    cfg = dict(CFG, mvp_mappings={})
    proposals = [{"name": "wl", "monthly_price_usd": None, "source": "repo:experiment.yaml",
                  "confidence": "high", "price_unmapped_reason": "free_or_waitlist"}]
    with tempfile.TemporaryDirectory() as td:
        cp, yp = _write(td, ctx, cfg)
        pp = os.path.join(td, "prop.json")
        json.dump(proposals, open(pp, "w"))
        P.cmd_persist(cp, yp, pp, now_iso="2026-06-27T00:00:00Z")
        out_ctx = json.load(open(cp))
    m = out_ctx["mvps"][0]
    assert m["monthly_price_usd"] is None
    assert m["price_unmapped_reason"] == "free_or_waitlist"


def test_persist_over_cap_no_proposal_is_not_found():
    ctx = {"mvps": [{"name": "missing", "ga_cpc": 9.0, "ga_currency": "USD"}]}
    cfg = dict(CFG, mvp_mappings={})
    with tempfile.TemporaryDirectory() as td:
        cp, yp = _write(td, ctx, cfg)
        pp = os.path.join(td, "prop.json")
        json.dump([], open(pp, "w"))
        P.cmd_persist(cp, yp, pp, now_iso="2026-06-27T00:00:00Z")
        out_ctx = json.load(open(cp))
    assert out_ctx["mvps"][0]["price_unmapped_reason"] == "not_found"


# Self-runner so this file works without pytest installed.
if __name__ == "__main__":
    import inspect

    failed = passed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn) and not inspect.signature(fn).parameters:
            try:
                fn()
                print(f"PASS  {name}")
                passed += 1
            except Exception as e:  # noqa: BLE001
                print(f"FAIL  {name}: {e!r}")
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
