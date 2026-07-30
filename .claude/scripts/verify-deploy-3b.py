#!/usr/bin/env python3
"""VERIFY script for deploy state 3b.

Asserts:
- hosting_created is True
- env_vars_set is True
- domain_added is populated
- domain_added / canonical_url are consistent
- collected_secrets is a dict (producer contract — see observation #988)
- When stack.email == 'resend': collected_secrets contains RESEND_API_KEY + CRON_SECRET
- When stack.email is present (any value): collected_secrets contains RESEND_FROM
"""
import json
import os
import sys

d = json.load(open(".runs/deploy-provision-3b.json"))

assert d.get("hosting_created") is True, "hosting_created not True"
assert d.get("env_vars_set") is True, "env_vars_set not True"
assert d.get("domain_added") is not None, "domain_added missing"
if d.get("domain_added") is not True:
    assert d.get("canonical_url") in (None, ""), "domain_added False but canonical_url set unexpectedly"
else:
    assert d.get("canonical_url") not in (None, ""), "domain_added True but canonical_url empty"

cs = d.get("collected_secrets")
assert isinstance(cs, dict), "collected_secrets missing or not a dict"

email = None
if os.path.exists("experiment/experiment.yaml"):
    try:
        import yaml

        ey = yaml.safe_load(open("experiment/experiment.yaml"))
        if isinstance(ey, dict):
            stack = ey.get("stack", {}) or {}
            email = stack.get("email")
    except Exception:
        pass

if email == "resend":
    for key in ("RESEND_API_KEY", "CRON_SECRET"):
        assert key in cs, f"collected_secrets missing {key} (stack.email=resend)"
if email:
    assert "RESEND_FROM" in cs, "collected_secrets missing RESEND_FROM (stack.email present)"

sys.exit(0)
