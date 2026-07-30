#!/usr/bin/env python3
"""Validate experiment.yaml structure: name format, archetype structure, required fields,
stack file existence, testing warning, and stack assumes consistency.

Exit codes:
  0 — all checks passed
  1 — hard error (validation failed)
  2 — passed with warnings (missing stack files, testing in stack, etc.)
"""

import os
import re
import sys

import yaml


data = yaml.safe_load(open("experiment/experiment.yaml"))
warnings = False

# --- Name format ---
name = data.get("name", "")
if not re.fullmatch(r"[a-z][a-z0-9-]*", name):
    print(
        f'Error: name "{name}" must be lowercase, start with a letter, '
        "and use only a-z, 0-9, hyphens."
    )
    print("Example: my-experiment-1")
    sys.exit(1)

# --- Product type (optional) ---
experiment_type = data.get("type")
if experiment_type is not None:
    if not re.fullmatch(r"[a-z][a-z0-9-]*", str(experiment_type)):
        print(
            f'Error: type "{experiment_type}" must be lowercase, start with a letter, '
            "and use only a-z, 0-9, hyphens."
        )
        print("Example: web-app")
        sys.exit(1)
    archetype_path = f".claude/archetypes/{experiment_type}.md"
    if not os.path.isfile(archetype_path):
        print(f"  Warning: type '{experiment_type}' — no file at {archetype_path}")
        print(
            "  Claude will use general knowledge for this archetype. "
            "To fix: create the archetype file or change the type value."
        )
        warnings = True

# --- Resolve archetype metadata ---
effective_type = experiment_type if experiment_type is not None else "web-app"

# --- Required fields ---
base_required = [
    "name", "owner", "description", "thesis", "target_user",
    "distribution", "behaviors", "stack",
]

# Add archetype-specific required fields
archetype_path = f".claude/archetypes/{effective_type}.md"
if os.path.isfile(archetype_path):
    with open(archetype_path) as af:
        arch_content = af.read()
    arch_fm_match = re.match(r"^---\n(.*?\n)---", arch_content, re.DOTALL)
    if arch_fm_match:
        arch_fm = yaml.safe_load(arch_fm_match.group(1)) or {}
        for field in arch_fm.get("required_experiment_fields", []):
            if field not in base_required:
                base_required.append(field)
else:
    # Fallback: web-app default requires golden_path
    if "golden_path" not in base_required:
        base_required.append("golden_path")

missing = [f for f in base_required if not data.get(f)]
if missing:
    print("Error: these required fields are missing or empty: " + ", ".join(missing))
    sys.exit(1)

# --- Variants validation (optional field) ---
variants = data.get("variants")
if variants is not None:
    if not isinstance(variants, list):
        print("Error: variants must be a list")
        sys.exit(1)
    if len(variants) < 2:
        print(
            "Error: variants must have at least 2 entries "
            "(testing 1 variant = no variants — remove the variants field)"
        )
        sys.exit(1)

    slugs_seen = set()

    for i, v in enumerate(variants):
        if not isinstance(v, dict):
            print(f"Error: variants[{i}] must be a mapping")
            sys.exit(1)

        for field in ["slug", "headline", "subheadline", "cta", "pain_points"]:
            val = v.get(field)
            if not val:
                print(f"Error: variants[{i}].{field} is missing or empty")
                sys.exit(1)

        slug = v.get("slug", "")
        if not re.fullmatch(r"[a-z][a-z0-9-]*", slug):
            print(
                f'Error: variants[{i}].slug "{slug}" must be lowercase, '
                "start with a letter, and use only a-z, 0-9, hyphens."
            )
            sys.exit(1)

        if slug in slugs_seen:
            print(f"Error: duplicate variant slug: {slug}")
            sys.exit(1)
        slugs_seen.add(slug)

        pp = v.get("pain_points", [])
        if not isinstance(pp, list) or len(pp) != 3:
            print(f"Error: variants[{i}].pain_points must have exactly 3 items")
            sys.exit(1)

        # Optional enrichment fields (promise, proof, urgency)
        for enrich_field in ["promise", "proof", "urgency"]:
            enrich_val = v.get(enrich_field)
            if enrich_val is not None:
                if not isinstance(enrich_val, str) or not enrich_val.strip():
                    print(f"Error: variants[{i}].{enrich_field} must be a non-empty string (or remove it)")
                    sys.exit(1)

    # Issue #1117: pricing_amount/pricing_model are required when level==3 AND
    # a monetize hypothesis exists. Otherwise optional. Documented in
    # .claude/templates/experiment-yaml.md `variants` section.
    level_value = data.get("level")
    has_monetize_hypothesis = False
    if isinstance(data.get("hypotheses"), list):
        has_monetize_hypothesis = any(
            isinstance(h, dict) and h.get("category") == "monetize"
            for h in data["hypotheses"]
        )
    pricing_required = level_value == 3 and has_monetize_hypothesis
    VALID_PRICING_MODELS = {"subscription", "one-time", "usage-based", "freemium"}
    for i, v in enumerate(variants):
        if not isinstance(v, dict):
            continue
        amt = v.get("pricing_amount")
        mdl = v.get("pricing_model")
        if pricing_required:
            if amt is None or mdl is None:
                print(
                    f"Error: variants[{i}] must have pricing_amount and pricing_model "
                    f"when level==3 AND a monetize hypothesis exists (#1117)."
                )
                sys.exit(1)
        if amt is not None:
            if not isinstance(amt, (int, float)) or isinstance(amt, bool) or amt < 0:
                print(f"Error: variants[{i}].pricing_amount must be a non-negative number")
                sys.exit(1)
        if mdl is not None:
            if mdl not in VALID_PRICING_MODELS:
                print(
                    f'Error: variants[{i}].pricing_model "{mdl}" must be one of: '
                    f'{", ".join(sorted(VALID_PRICING_MODELS))}'
                )
                sys.exit(1)

# --- Golden path validation (required field) ---
golden_path = data.get("golden_path")
if golden_path is not None:
    if not isinstance(golden_path, list):
        print("Error: golden_path must be a list")
        sys.exit(1)
    if len(golden_path) < 2:
        print("Error: golden_path must have at least 2 entries")
        sys.exit(1)

    for i, gp_step in enumerate(golden_path):
        if not isinstance(gp_step, dict):
            print(f"Error: golden_path[{i}] must be a mapping")
            sys.exit(1)

        step_val = gp_step.get("step")
        if not step_val or not isinstance(step_val, str):
            print(f"Error: golden_path[{i}].step is missing or empty")
            sys.exit(1)

# --- Target clicks validation (optional field) ---
target_clicks = data.get("target_clicks")
if target_clicks is not None:
    if not isinstance(target_clicks, int) or target_clicks < 1:
        print("Error: target_clicks must be a positive integer")
        sys.exit(1)

# --- Level validation (optional, /spec field) ---
level = data.get("level")
if level is not None:
    if not isinstance(level, int) or isinstance(level, bool) or level not in (1, 2, 3):
        print("Error: level must be 1, 2, or 3")
        sys.exit(1)

# --- Thesis validation (required field) ---
thesis = data.get("thesis")
if thesis is not None:
    if not isinstance(thesis, str) or not thesis.strip():
        print("Error: thesis must be a non-empty string")
        sys.exit(1)

# --- Hypotheses validation (optional, /spec field) ---
hypotheses = data.get("hypotheses")
hypothesis_ids = set()
if hypotheses is not None:
    if not isinstance(hypotheses, list):
        print("Error: hypotheses must be a list"); sys.exit(1)

    VALID_CATEGORIES = {"demand", "reach", "activate", "monetize", "retain"}
    VALID_STATUSES = {"pending", "resolved"}
    depends_to_check = []  # (index, list_of_dep_ids)

    for i, h in enumerate(hypotheses):
        if not isinstance(h, dict):
            print(f"Error: hypotheses[{i}] must be a mapping"); sys.exit(1)

        # Required string fields
        for field in ["id", "category", "statement"]:
            if not h.get(field) or not isinstance(h.get(field), str):
                print(f"Error: hypotheses[{i}].{field} is missing or empty"); sys.exit(1)

        # Issue #1117: hypotheses validated by desk research carry
        # status: resolved and use `evidence:{source,verdict,citation}` instead
        # of `metric:{formula,threshold,operator}`. Either shape is acceptable;
        # at least one must be present. Forcing metric on resolved hypotheses
        # produces invented placeholder formulas that never fire.
        h_status = h.get("status")
        metric = h.get("metric")
        evidence = h.get("evidence")
        if h_status == "resolved":
            # Resolved: prefer evidence; allow metric only if evidence absent (legacy).
            if evidence is None and metric is None:
                print(f"Error: hypotheses[{i}] (status=resolved) must have either evidence:{{source,verdict,citation}} or legacy metric:{{...}}"); sys.exit(1)
            if evidence is not None:
                if not isinstance(evidence, dict):
                    print(f"Error: hypotheses[{i}].evidence must be a mapping with source, verdict, citation"); sys.exit(1)
                for k in ("source", "verdict", "citation"):
                    if not evidence.get(k) or not isinstance(evidence.get(k), str):
                        print(f"Error: hypotheses[{i}].evidence.{k} must be a non-empty string"); sys.exit(1)
            # If only metric is present (legacy resolved entry), validate it below.
        if h_status != "resolved" or (metric is not None and evidence is None):
            # Required metric object for non-resolved hypotheses, or a
            # resolved-legacy entry that only has metric.
            if not isinstance(metric, dict):
                print(f"Error: hypotheses[{i}].metric must be a mapping with formula, threshold, operator"); sys.exit(1)
            metric_formula = metric.get("formula")
            if not metric_formula or not isinstance(metric_formula, str):
                print(f"Error: hypotheses[{i}].metric.formula must be a non-empty string"); sys.exit(1)
            metric_threshold = metric.get("threshold")
            if not isinstance(metric_threshold, (int, float)) or isinstance(metric_threshold, bool):
                print(f"Error: hypotheses[{i}].metric.threshold must be a number"); sys.exit(1)
            metric_operator = metric.get("operator")
            VALID_OPERATORS = {"gt", "gte", "lt", "lte"}
            if metric_operator not in VALID_OPERATORS:
                print(f'Error: hypotheses[{i}].metric.operator must be one of: {", ".join(sorted(VALID_OPERATORS))}'); sys.exit(1)

        h_id = h["id"]
        if not re.fullmatch(r"h-\d{2,}", h_id):
            print(f'Error: hypotheses[{i}].id "{h_id}" must match h-NN (e.g., h-01, h-02)'); sys.exit(1)

        if h["category"] not in VALID_CATEGORIES:
            print(f'Error: hypotheses[{i}].category "{h["category"]}" must be: {", ".join(sorted(VALID_CATEGORIES))}'); sys.exit(1)

        # Required int fields
        ps = h.get("priority_score")
        if not isinstance(ps, int) or isinstance(ps, bool) or not (0 <= ps <= 100):
            print(f"Error: hypotheses[{i}].priority_score must be integer 0-100"); sys.exit(1)

        el = h.get("experiment_level")
        if not isinstance(el, int) or isinstance(el, bool) or el not in (1, 2, 3):
            print(f"Error: hypotheses[{i}].experiment_level must be 1, 2, or 3"); sys.exit(1)

        status = h.get("status")
        if not isinstance(status, str) or status not in VALID_STATUSES:
            print(f'Error: hypotheses[{i}].status must be: {", ".join(sorted(VALID_STATUSES))}'); sys.exit(1)

        # Unique ID
        if h_id in hypothesis_ids:
            print(f"Error: duplicate hypothesis id: {h_id}"); sys.exit(1)
        hypothesis_ids.add(h_id)

        # depends_on (optional)
        deps = h.get("depends_on")
        if deps is not None:
            if not isinstance(deps, list):
                print(f"Error: hypotheses[{i}].depends_on must be a list"); sys.exit(1)
            depends_to_check.append((i, deps))

    # Second pass: depends_on references exist
    for i, deps in depends_to_check:
        for dep_id in deps:
            if dep_id not in hypothesis_ids:
                print(f'Error: hypotheses[{i}].depends_on references unknown id "{dep_id}"'); sys.exit(1)

    # Cross-field: experiment_level <= top-level level
    if level is not None:
        for i, h in enumerate(hypotheses):
            if h.get("experiment_level", 0) > level:
                print(f"Error: hypotheses[{i}].experiment_level ({h['experiment_level']}) exceeds top-level level ({level})"); sys.exit(1)

# --- Behaviors validation (optional, /spec field) ---
behaviors = data.get("behaviors")
if behaviors is not None:
    if not isinstance(behaviors, list):
        print("Error: behaviors must be a list"); sys.exit(1)

    behavior_ids = set()
    valid_behavior_actors = {"system", "cron"}
    for i, b in enumerate(behaviors):
        if not isinstance(b, dict):
            print(f"Error: behaviors[{i}] must be a mapping"); sys.exit(1)

        for field in ["id", "hypothesis_id", "given", "when", "then"]:
            if not b.get(field) or not isinstance(b.get(field), str):
                print(f"Error: behaviors[{i}].{field} is missing or empty"); sys.exit(1)

        b_id = b["id"]
        if not re.fullmatch(r"b-\d{2,}", b_id):
            print(f'Error: behaviors[{i}].id "{b_id}" must match b-NN (e.g., b-01, b-02)'); sys.exit(1)

        if b_id in behavior_ids:
            print(f"Error: duplicate behavior id: {b_id}"); sys.exit(1)
        behavior_ids.add(b_id)

        b_level = b.get("level")
        if not isinstance(b_level, int) or isinstance(b_level, bool) or b_level not in (1, 2, 3):
            print(f"Error: behaviors[{i}].level must be 1, 2, or 3"); sys.exit(1)

        # Optional actor field
        b_actor = b.get("actor")
        if b_actor is not None:
            if b_actor not in valid_behavior_actors:
                print(
                    f'Error: behaviors[{i}].actor "{b_actor}" '
                    f"must be one of: {', '.join(sorted(valid_behavior_actors))}"
                ); sys.exit(1)

        # Optional trigger field (just validate it's a non-empty string if present)
        b_trigger = b.get("trigger")
        if b_trigger is not None:
            if not isinstance(b_trigger, str) or not b_trigger.strip():
                print(f"Error: behaviors[{i}].trigger must be a non-empty string (or remove it)"); sys.exit(1)

        # Optional tests field: must be list of 1-5 strings
        b_tests = b.get("tests")
        if b_tests is not None:
            if not isinstance(b_tests, list) or not (1 <= len(b_tests) <= 5):
                print(f"Error: behaviors[{i}].tests must be a list of 1-5 strings"); sys.exit(1)
            for j, t in enumerate(b_tests):
                if not isinstance(t, str) or not t.strip():
                    print(f"Error: behaviors[{i}].tests[{j}] must be a non-empty string"); sys.exit(1)

        # Issue #1126: anonymous_allowed and requires_role are mutually exclusive.
        # A behavior cannot be both anonymous (no auth required) and role-gated
        # (auth required + specific role). Default-deny: anonymous_allowed defaults
        # to false. When true, derive_public_paths() adds the behavior's pages
        # to the auth proxy's publicPaths array.
        b_anon = b.get("anonymous_allowed")
        b_role = b.get("requires_role")
        if b_anon is not None and not isinstance(b_anon, bool):
            print(f"Error: behaviors[{i}].anonymous_allowed must be a boolean"); sys.exit(1)
        if b_anon is True and b_role:
            print(
                f"Error: behaviors[{i}] sets both anonymous_allowed=true and requires_role={b_role!r} -- "
                f"these are mutually exclusive (a behavior is either anonymous or role-gated, not both). See #1126."
            ); sys.exit(1)

        # Cross-ref: hypothesis_id must exist if hypotheses section present
        h_id_ref = b["hypothesis_id"]
        if hypotheses is not None:
            if h_id_ref not in hypothesis_ids:
                print(f'Error: behaviors[{i}].hypothesis_id "{h_id_ref}" not found in hypotheses'); sys.exit(1)
        elif hypothesis_ids is not None:
            # hypotheses absent but behaviors reference them — soft warning
            print(f'  Warning: behaviors[{i}].hypothesis_id "{h_id_ref}" — hypotheses section is absent')
            warnings = True

# --- Funnel validation (optional, /spec field) ---
funnel = data.get("funnel")
if funnel is not None:
    if not isinstance(funnel, dict):
        print("Error: funnel must be a mapping"); sys.exit(1)

    VALID_FUNNEL_KEYS = {"available_from", "decision_framework"}
    for fk in funnel:
        if fk not in VALID_FUNNEL_KEYS:
            print(f'Error: funnel.{fk} is not a valid funnel key (expected: {", ".join(sorted(VALID_FUNNEL_KEYS))})'); sys.exit(1)

    # available_from: map of dimension → level string
    VALID_FUNNEL_STAGES = {"reach", "demand", "activate", "monetize", "retain"}
    af = funnel.get("available_from")
    if af is not None:
        if not isinstance(af, dict):
            print("Error: funnel.available_from must be a mapping"); sys.exit(1)
        for stage_key, level_val in af.items():
            if stage_key not in VALID_FUNNEL_STAGES:
                print(f'Error: funnel.available_from.{stage_key} is not a valid stage (expected: {", ".join(sorted(VALID_FUNNEL_STAGES))})'); sys.exit(1)
            if not isinstance(level_val, str) or not level_val.strip():
                print(f"Error: funnel.available_from.{stage_key} must be a non-empty string (e.g., L1)"); sys.exit(1)

    df = funnel.get("decision_framework")
    if df is not None:
        if not isinstance(df, dict):
            print("Error: funnel.decision_framework must be a mapping"); sys.exit(1)
        VALID_DF_KEYS = {"scale", "refine", "pivot", "kill"}
        for dk in VALID_DF_KEYS:
            dv = df.get(dk)
            if not dv or not isinstance(dv, str):
                print(f"Error: funnel.decision_framework.{dk} is missing or empty"); sys.exit(1)
        for dk in df:
            if dk not in VALID_DF_KEYS:
                print(f'Error: funnel.decision_framework.{dk} is not valid (expected: {", ".join(sorted(VALID_DF_KEYS))})'); sys.exit(1)

# --- Stack validation ---
stack = data.get("stack", {})

# --- Level ↔ Stack consistency ---
if level is not None:
    stack_db = stack.get("database")
    stack_auth = stack.get("auth")
    stack_payment = stack.get("payment")

    if level == 1:
        if stack_db:
            print(f"Error: level 1 cannot have stack.database (got: {stack_db}). "
                  "Database requires level 2+.")
            sys.exit(1)
        if stack_auth:
            print(f"Error: level 1 cannot have stack.auth (got: {stack_auth}). "
                  "Auth requires level 3.")
            sys.exit(1)
        if stack_payment:
            print(f"Error: level 1 cannot have stack.payment (got: {stack_payment}). "
                  "Payment requires level 3 with monetize hypotheses.")
            sys.exit(1)

    if level == 2:
        if stack_auth:
            print(f"Error: level 2 cannot have stack.auth (got: {stack_auth}). "
                  "Auth requires level 3.")
            sys.exit(1)
        if stack_payment:
            print(f"Error: level 2 cannot have stack.payment (got: {stack_payment}). "
                  "Payment requires level 3 with monetize hypotheses.")
            sys.exit(1)

    if level == 3 and stack_payment:
        if hypotheses is not None:
            has_monetize = any(
                h.get("category") == "monetize"
                for h in hypotheses if isinstance(h, dict)
            )
            if not has_monetize:
                print("Error: level 3 with stack.payment requires at least one "
                      "hypothesis with category 'monetize'.")
                sys.exit(1)

# Per-service values via services[] array
services = stack.get("services", [])
if services:
    if not isinstance(services, list):
        print("Error: stack.services must be a list"); sys.exit(1)

    service_names_seen = set()
    for i, svc in enumerate(services):
        if not isinstance(svc, dict):
            print(f"Error: stack.services[{i}] must be a mapping"); sys.exit(1)

        svc_name = svc.get("name")
        if not svc_name or not isinstance(svc_name, str):
            print(f"Error: stack.services[{i}].name is missing or empty"); sys.exit(1)

        if svc_name in service_names_seen:
            print(f"Error: duplicate service name: {svc_name}"); sys.exit(1)
        service_names_seen.add(svc_name)

        svc_runtime = svc.get("runtime")
        if not svc_runtime or not isinstance(svc_runtime, str):
            print(f"Error: stack.services[{i}].runtime is missing or empty"); sys.exit(1)

        svc_hosting = svc.get("hosting")
        if not svc_hosting or not isinstance(svc_hosting, str):
            print(f"Error: stack.services[{i}].hosting is missing or empty"); sys.exit(1)

        # Optional per-service fields
        for opt_field in ["ui", "testing"]:
            opt_val = svc.get(opt_field)
            if opt_val is not None and not isinstance(opt_val, str):
                print(f"Error: stack.services[{i}].{opt_field} must be a string"); sys.exit(1)

# Stack file existence checks — per-service values
CATEGORY_DIR_MAP = {
    "runtime": "framework",
    "hosting": "hosting",
    "ui": "ui",
    "testing": "testing",
}
stack_file_warnings = []

# Reverse map: directory name → service key (e.g., "framework" → "runtime")
DIR_TO_SVC_KEY = {v: k for k, v in CATEGORY_DIR_MAP.items()}

for i, svc in enumerate(services):
    for svc_key, dir_name in CATEGORY_DIR_MAP.items():
        val = svc.get(svc_key)
        if val:
            sf_path = f".claude/stacks/{dir_name}/{val}.md"
            if not os.path.isfile(sf_path):
                stack_file_warnings.append(
                    f"stack.services[{i}].{svc_key}: {val} — no file at {sf_path}"
                )

# Stack file existence checks — shared values
SHARED_STACK_KEYS = {"database", "auth", "analytics", "payment", "email", "ai", "telephony", "voice", "notifications", "project-management"}
for k, v in stack.items():
    if k in SHARED_STACK_KEYS and isinstance(v, str):
        sf_path = f".claude/stacks/{k}/{v}.md"
        if not os.path.isfile(sf_path):
            stack_file_warnings.append(f"stack.{k}: {v} — no file at {sf_path}")

if stack_file_warnings:
    for w in stack_file_warnings:
        print(f"  Warning: {w}")
    print(
        "  Claude will use general knowledge for these. "
        "To fix: create the stack file or change the value."
    )
    warnings = True

# --- Surface validation ---
effective_surface = stack.get("surface")
if effective_surface is None:
    # Infer from hosting presence (check services for hosting)
    has_hosting = any(svc.get("hosting") for svc in services)
    effective_surface = "co-located" if has_hosting else "detached"

# Validate surface value format
if effective_surface not in ("co-located", "detached", "none"):
    print(f'Error: stack.surface "{effective_surface}" must be one of: co-located, detached, none')
    sys.exit(1)

# Validate surface + archetype combination
invalid_combos = {
    ("service", "detached"): "Services have a server — use co-located (surface at root URL) or none.",
    ("cli", "co-located"): "CLIs have no server — use detached (Vercel static site) or none.",
}
combo = (effective_type, effective_surface)
if combo in invalid_combos:
    print(f"Error: type '{effective_type}' + surface '{effective_surface}' is invalid. {invalid_combos[combo]}")
    sys.exit(1)

# Check surface stack file existence
if effective_surface != "none":
    sf_path = f".claude/stacks/surface/{effective_surface}.md"
    if not os.path.isfile(sf_path):
        print(f"  Warning: surface '{effective_surface}' — no file at {sf_path}")
        warnings = True

# --- Stack assumes consistency ---
assumes_warnings = []

# Check shared stack values
for cat in SHARED_STACK_KEYS:
    val = stack.get(cat)
    if not val or not isinstance(val, str):
        continue
    sf = f".claude/stacks/{cat}/{val}.md"
    if not os.path.isfile(sf):
        continue
    with open(sf) as f:
        content = f.read()
    m = re.match(r"^---\n(.*?\n)---", content, re.DOTALL)
    if not m:
        continue
    fm = yaml.safe_load(m.group(1)) or {}
    for assume in fm.get("assumes") or []:
        parts = assume.split("/")
        if len(parts) != 2:
            continue
        a_cat, a_val = parts
        # Check if assumption is satisfied by any service or shared stack
        # a_cat may be a dir name (framework) or a service key (runtime) — normalize
        resolved_svc_key = DIR_TO_SVC_KEY.get(a_cat) or (a_cat if a_cat in CATEGORY_DIR_MAP else None)
        if resolved_svc_key is not None:
            # Per-service value — check if any service has this
            svc_key = resolved_svc_key
            satisfied = any(svc.get(svc_key) == a_val for svc in services)
            if not satisfied:
                assumes_warnings.append(
                    f"stack.{cat}/{val} assumes {assume}, but no service has {svc_key}: {a_val}"
                )
        else:
            actual = stack.get(a_cat)
            if actual is None:
                assumes_warnings.append(
                    f"stack.{cat}/{val} assumes {assume}, but stack.{a_cat} is not set"
                )
            elif actual != a_val:
                assumes_warnings.append(
                    f"stack.{cat}/{val} assumes {assume}, but stack.{a_cat} is {actual}"
                )

# Check per-service stack values
for i, svc in enumerate(services):
    for svc_key, dir_name in CATEGORY_DIR_MAP.items():
        val = svc.get(svc_key)
        if not val or not isinstance(val, str):
            continue
        sf = f".claude/stacks/{dir_name}/{val}.md"
        if not os.path.isfile(sf):
            continue
        with open(sf) as f:
            content = f.read()
        m_match = re.match(r"^---\n(.*?\n)---", content, re.DOTALL)
        if not m_match:
            continue
        fm = yaml.safe_load(m_match.group(1)) or {}
        for assume in fm.get("assumes") or []:
            parts = assume.split("/")
            if len(parts) != 2:
                continue
            a_cat, a_val = parts
            resolved_a_svc_key = DIR_TO_SVC_KEY.get(a_cat) or (a_cat if a_cat in CATEGORY_DIR_MAP else None)
            if resolved_a_svc_key is not None:
                # Check within the same service first
                a_svc_key = resolved_a_svc_key
                actual = svc.get(a_svc_key)
                if actual is None:
                    assumes_warnings.append(
                        f"stack.services[{i}].{svc_key}/{val} assumes {assume}, but services[{i}].{a_svc_key} is not set"
                    )
                elif actual != a_val:
                    assumes_warnings.append(
                        f"stack.services[{i}].{svc_key}/{val} assumes {assume}, but services[{i}].{a_svc_key} is {actual}"
                    )
            else:
                actual = stack.get(a_cat)
                if actual is None:
                    assumes_warnings.append(
                        f"stack.services[{i}].{svc_key}/{val} assumes {assume}, but stack.{a_cat} is not set"
                    )
                elif actual != a_val:
                    assumes_warnings.append(
                        f"stack.services[{i}].{svc_key}/{val} assumes {assume}, but stack.{a_cat} is {actual}"
                    )

if assumes_warnings:
    print("  Warning: stack assumes mismatches:")
    for w in assumes_warnings:
        print(f"    - {w}")
    print(
        "  /bootstrap will reject these. "
        "Fix experiment.yaml stack values or create compatible stack files."
    )
    warnings = True

# --- Stack dependency matrix (canonical: patterns/stack-dependency-validation.md) ---
if stack.get("payment"):
    if not stack.get("auth"):
        print("Error: payment requires auth — add `auth: <provider>` to experiment.yaml stack")
        sys.exit(1)
    if not stack.get("database"):
        print("Error: payment requires database — add `database: <provider>` to experiment.yaml stack")
        sys.exit(1)

if stack.get("email"):
    if not stack.get("auth"):
        print("Error: email requires auth — add `auth: <provider>` to experiment.yaml stack")
        sys.exit(1)
    if not stack.get("database"):
        print("Error: email requires database — add `database: <provider>` to experiment.yaml stack")
        sys.exit(1)

if stack.get("auth_providers"):
    if not stack.get("auth"):
        print("Error: auth_providers requires auth — add `auth: <provider>` to experiment.yaml stack")
        sys.exit(1)

# --- Compatibility constraints (canonical: patterns/stack-dependency-validation.md) ---
for i, svc in enumerate(services):
    svc_testing = svc.get("testing")
    if svc_testing == "playwright" and effective_type in ("service", "cli"):
        print(
            f"Error: stack.services[{i}].testing: playwright is incompatible with "
            f"archetype '{effective_type}' — use vitest instead"
        )
        sys.exit(1)
    svc_runtime = svc.get("runtime")
    if effective_type == "web-app" and svc_runtime and svc_runtime != "nextjs":
        print(
            f"Error: stack.services[{i}].runtime: '{svc_runtime}' — "
            f"web-app archetype requires nextjs"
        )
        sys.exit(1)
    if effective_type == "cli" and svc_runtime and svc_runtime != "commander":
        print(
            f"Error: stack.services[{i}].runtime: '{svc_runtime}' — "
            f"cli archetype requires commander"
        )
        sys.exit(1)

sys.exit(2 if warnings else 0)
