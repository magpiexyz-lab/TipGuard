#!/usr/bin/env python3
"""VERIFY script for review state 2c: validate review-adversarial.json schema.

Checks:
- confirmed, disputed, needs_evidence are lists of objects
- Each item has agent_classification and final_classification
- review-challenger trace exists
"""
import json
import os

d = json.load(open(".runs/review-adversarial.json"))

for lst_name in ("confirmed", "disputed", "needs_evidence"):
    lst = d.get(lst_name, [])
    assert isinstance(lst, list), f"{lst_name} missing or not list"
    for i, item in enumerate(lst):
        assert isinstance(item, dict), f"{lst_name}[{i}] must be an object, got {type(item).__name__}"
        assert "agent_classification" in item, f"{lst_name}[{i}] missing agent_classification"
        assert "final_classification" in item, f"{lst_name}[{i}] missing final_classification"

assert os.path.exists(
    ".runs/agent-traces/review-challenger.json"
), "review-challenger.json trace missing"
