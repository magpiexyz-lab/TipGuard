"""Analytics and ads schema validation checks."""
import datetime
import re
import yaml

from ._utils import (
    extract_code_blocks,
    extract_prose,
)

__all__ = [
    "check_33_phantom_event_names",
    "check_38_ads_yaml_schema",
    "check_39_ads_campaign_name",
    "check_45_visit_landing_variant_property",
    "check_ads_for_distribute",
]

def check_33_phantom_event_names(
    skill_contents: dict[str, str],
    defined_events: set[str],
    global_props: set[str],
    event_props: set[str],
) -> list[str]:
    """Check 33: Backtick-wrapped event names in skill prose exist in experiment/EVENTS.yaml."""
    errors: list[str] = []
    skip_tokens = {
        "stack", "testing", "payment", "analytics", "database",
        "auth", "posthog", "supabase", "stripe", "nextjs",
        "funnel_stage", "events",
        "object_action", "track", "event_name",
        "name", "title", "owner", "problem", "solution",
        "target_user", "distribution", "thesis",
        "description", "behaviors",
        "page_name", "feature", "features", "pages", "variants",
    }

    for sf, content in skill_contents.items():
        prose = extract_prose(content)

        skill_defined_events: set[str] = set()
        skill_defined_props: set[str] = set()
        for yblock in extract_code_blocks(content, {"yaml"}):
            try:
                ydata = yaml.safe_load(yblock["code"])
            except yaml.YAMLError:
                continue
            event_items: list[dict] = []
            if isinstance(ydata, list):
                event_items = [item for item in ydata if isinstance(item, dict)]
            elif isinstance(ydata, dict):
                if "event" in ydata:
                    event_items = [ydata]
                elif "funnel_stage" in ydata:
                    # Single event definition in new flat format
                    event_items = [ydata]
                else:
                    # Flat events map: each value is an event definition
                    for key, val in ydata.items():
                        if isinstance(val, dict) and ("trigger" in val or "funnel_stage" in val):
                            edef = dict(val)
                            edef["event"] = key
                            event_items.append(edef)
            for item in event_items:
                if "event" in item:
                    skill_defined_events.add(item["event"])
                    for prop_name in (item.get("properties", {}) or {}).keys():
                        skill_defined_props.add(prop_name)

        for m in re.finditer(r"`([a-z][a-z0-9_]+)`", prose):
            token = m.group(1)
            if "/" in token or "." in token:
                continue
            start = max(0, m.start() - 100)
            end = min(len(prose), m.end() + 100)
            context = prose[start:end].lower()
            if not re.search(r"\bevent\b|\bfire\b", context):
                continue
            if token in defined_events:
                continue
            if token in global_props:
                continue
            if token in event_props:
                continue
            if token in skill_defined_events or token in skill_defined_props:
                continue
            context_before = prose[start:m.start()].lower()
            if re.search(r"(?:from|in)\s+events\.yaml", context_before):
                continue
            if re.search(r"events\.yaml", context.lower()):
                continue
            if token in skip_tokens:
                continue
            pos = content.find(f"`{token}`")
            line_num = content[:pos].count("\n") + 1 if pos >= 0 else "?"
            errors.append(
                f"[33] {sf}:{line_num}: prose references event name "
                f"'{token}' near event/fire context, but it is not "
                f"defined in experiment/EVENTS.yaml"
            )
    return errors


def check_38_ads_yaml_schema(ads_data: dict, ads_path: str) -> list[str]:
    """Check 38: Ads.yaml has valid schema."""
    errors: list[str] = []
    ads_channel = ads_data.get("channel", "google-ads")

    ads_universal_keys = [
        "campaign_name", "project_name", "landing_url",
        "budget", "targeting", "conversions", "guardrails", "thresholds",
    ]
    for key in ads_universal_keys:
        if key not in ads_data:
            errors.append(f"[38] {ads_path}: missing required key '{key}'")

    if ads_channel == "google-ads":
        for key in ("keywords", "ads"):
            if key not in ads_data:
                errors.append(f"[38] {ads_path}: missing required key '{key}' (channel: google-ads)")

        kw = ads_data.get("keywords", {})
        if isinstance(kw, dict):
            if len(kw.get("exact", []) or []) < 3:
                errors.append(f"[38] {ads_path}: keywords.exact needs at least 3 entries")
            if len(kw.get("phrase", []) or []) < 2:
                errors.append(f"[38] {ads_path}: keywords.phrase needs at least 2 entries")
            if len(kw.get("broad", []) or []) < 1:
                errors.append(f"[38] {ads_path}: keywords.broad needs at least 1 entry")
            if len(kw.get("negative", []) or []) < 2:
                errors.append(f"[38] {ads_path}: keywords.negative needs at least 2 entries")

        ads_list = ads_data.get("ads", [])
        if isinstance(ads_list, list):
            if len(ads_list) < 2:
                errors.append(f"[38] {ads_path}: ads needs at least 2 variations")
            for i, ad in enumerate(ads_list):
                if isinstance(ad, dict):
                    headlines = ad.get("headlines", []) or []
                    descriptions = ad.get("descriptions", []) or []
                    if len(headlines) < 5:
                        errors.append(f"[38] {ads_path}: ads[{i}] needs at least 5 headlines")
                    if len(descriptions) < 2:
                        errors.append(f"[38] {ads_path}: ads[{i}] needs at least 2 descriptions")

    elif ads_channel == "twitter":
        if "tweets" not in ads_data:
            errors.append(f"[38] {ads_path}: missing required key 'tweets' (channel: twitter)")
        tweets = ads_data.get("tweets", [])
        if isinstance(tweets, list):
            if len(tweets) < 2:
                errors.append(f"[38] {ads_path}: tweets needs at least 2 variations")
            for i, tw in enumerate(tweets):
                if isinstance(tw, dict):
                    text = tw.get("text", "")
                    if len(text) > 280:
                        errors.append(f"[38] {ads_path}: tweets[{i}] text exceeds 280 chars")

    elif ads_channel == "reddit":
        if "posts" not in ads_data:
            errors.append(f"[38] {ads_path}: missing required key 'posts' (channel: reddit)")
        posts = ads_data.get("posts", [])
        if isinstance(posts, list):
            if len(posts) < 2:
                errors.append(f"[38] {ads_path}: posts needs at least 2 variations")
            for i, post in enumerate(posts):
                if isinstance(post, dict):
                    headline = post.get("headline", "")
                    if len(headline) > 300:
                        errors.append(f"[38] {ads_path}: posts[{i}] headline exceeds 300 chars")

    guardrails = ads_data.get("guardrails", {})
    max_cpc = None
    max_cpc_is_int = False
    if isinstance(guardrails, dict):
        max_cpc = guardrails.get("max_cpc_cents")
        max_cpc_is_int = isinstance(max_cpc, int) and not isinstance(max_cpc, bool)

    budget = ads_data.get("budget", {})
    if isinstance(budget, dict):
        total_raw = budget.get("total_budget_cents", 0)
        total = 0 if total_raw is None else total_raw
        total_is_int = isinstance(total, int) and not isinstance(total, bool)
        if not total_is_int or total < 0:
            errors.append(
                f"[38] {ads_path}: budget.total_budget_cents must be an integer cents value (got {total_raw!r})"
            )
            total_is_valid = False
        else:
            total_is_valid = True

        override_present = "cap_override_approved_by" in budget
        override = budget.get("cap_override_approved_by")
        override_is_valid = (
            isinstance(override, str) and bool(override.strip())
        )
        if override_present and not override_is_valid:
            errors.append(
                f"[38] {ads_path}: budget.cap_override_approved_by must be a non-empty string naming who approved the raise"
            )
        if override_present and ads_channel != "google-ads":
            errors.append(
                f"[38] {ads_path}: budget.cap_override_approved_by is only supported for google-ads"
            )

        if ads_channel == "google-ads":
            override_active = override_present and override_is_valid
            if total_is_valid and total > 75000 and not override_active:
                errors.append(
                    f"[38] {ads_path}: budget.total_budget_cents ({total}) exceeds max 75000 ($750); for > $50/mo products, ask your Team Lead and set budget.cap_override_approved_by"
                )
            if max_cpc_is_int and max_cpc > 250 and not override_active:
                errors.append(
                    f"[38] {ads_path}: guardrails.max_cpc_cents ({max_cpc}) exceeds default max 250; for > $50/mo products, ask your Team Lead and set budget.cap_override_approved_by"
                )
            if override_active:
                click_target = budget.get("click_target")
                click_target_valid = (
                    isinstance(click_target, int)
                    and not isinstance(click_target, bool)
                    and click_target in {100, 300}
                )
                if not click_target_valid:
                    errors.append(
                        f"[38] {ads_path}: cap override requires budget.click_target of 100 (Phase 1) or 300 (Phase 2)"
                    )
                if total_is_valid and total > 200000:
                    errors.append(
                        f"[38] {ads_path}: cap override total_budget_cents ({total}) exceeds absolute max 200000 ($2000)"
                    )
                if total_is_valid and max_cpc_is_int and click_target_valid:
                    expected_total = click_target * max_cpc
                    if total != expected_total:
                        errors.append(
                            f"[38] {ads_path}: cap override bundle identity requires budget.total_budget_cents to equal budget.click_target x guardrails.max_cpc_cents ({click_target} x {max_cpc} = {expected_total}, got {total})"
                        )
        elif total_is_valid and total > 75000:
            errors.append(
                f"[38] {ads_path}: budget.total_budget_cents ({total}) exceeds max 75000 ($750)"
            )

    if isinstance(guardrails, dict):
        if ads_channel == "google-ads":
            max_cpc = guardrails.get("max_cpc_cents")
            if max_cpc is None:
                errors.append(f"[38] {ads_path}: missing guardrails.max_cpc_cents")
            elif isinstance(max_cpc, bool) or not isinstance(max_cpc, int) or max_cpc <= 0:
                errors.append(
                    f"[38] {ads_path}: guardrails.max_cpc_cents must be an integer > 0 (got {max_cpc!r})"
                )

    thresholds = ads_data.get("thresholds", {})
    if isinstance(thresholds, dict):
        exp_act = thresholds.get("expected_activations")
        if exp_act is None:
            errors.append(f"[38] {ads_path}: missing thresholds.expected_activations")
        elif not isinstance(exp_act, int) or exp_act < 0:
            errors.append(
                f"[38] {ads_path}: thresholds.expected_activations must be an integer >= 0 (got {exp_act!r})"
            )
        go_signal = thresholds.get("go_signal")
        if not go_signal or not isinstance(go_signal, str) or not go_signal.strip():
            errors.append(f"[38] {ads_path}: thresholds.go_signal must be a non-empty string")
        no_go_signal = thresholds.get("no_go_signal")
        if not no_go_signal or not isinstance(no_go_signal, str) or not no_go_signal.strip():
            errors.append(f"[38] {ads_path}: thresholds.no_go_signal must be a non-empty string")

    phase = ads_data.get("phase")
    phase_present = "phase" in ads_data
    phase_is_valid = (
        isinstance(phase, int) and not isinstance(phase, bool) and phase in (1, 2)
    )
    if phase_present and not phase_is_valid:
        errors.append(f"[38] {ads_path}: phase must be 1 or 2 (got {phase!r})")
    if phase_is_valid and phase == 2 and ads_channel == "google-ads":
        campaign_name = ads_data.get("campaign_name", "")
        if "phase2" not in str(campaign_name).lower():
            errors.append(
                f"[38] {ads_path}: phase 2 campaign_name '{campaign_name}' must contain the 'phase2' token — /iterate --cross --phase2 isolates Phase 2 traffic by LIKE-matching phase2.utm_campaign_like (default '%phase2%') against utm_campaign, which mirrors the campaign name"
            )
        probe_present = "dayzero_probe_passed_at" in ads_data
        probe = ads_data.get("dayzero_probe_passed_at")
        # PyYAML parses an unquoted YYYY-MM-DD into datetime.date — accept both forms.
        probe_is_valid = isinstance(probe, datetime.date) or (
            isinstance(probe, str)
            and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", probe.strip()))
        )
        if not probe_present:
            errors.append(
                f"[38] {ads_path}: phase 2 requires dayzero_probe_passed_at — run the day-0 relay probe (Phase 2 Playbook §5 step 10), then record the PASS date (YYYY-MM-DD) via the §5 step 11 prompt"
            )
        elif not probe_is_valid:
            errors.append(
                f"[38] {ads_path}: dayzero_probe_passed_at must be a YYYY-MM-DD date (got {probe!r})"
            )

    return errors


def check_39_ads_campaign_name(ads_data: dict, idea_data: dict, ads_path: str) -> list[str]:
    """Check 39: ads.yaml campaign_name matches experiment.yaml name."""
    errors: list[str] = []
    idea_name = idea_data.get("name", "")
    campaign_name = ads_data.get("campaign_name", "")
    if idea_name and campaign_name:
        if not str(campaign_name).startswith(str(idea_name)):
            errors.append(
                f"[39] {ads_path}: campaign_name '{campaign_name}' does not start with "
                f"experiment.yaml name '{idea_name}'"
            )
    return errors


def check_ads_for_distribute(
    ads_data: dict,
    ads_path: str,
    experiment_path: str = "experiment/experiment.yaml",
) -> list[str]:
    """Compose the ads checks `make distribute` runs: schema (38) + campaign-name prefix (39).

    Loads experiment.yaml itself (guarded) because the Makefile one-liner
    cannot express try/except. Missing or malformed experiment.yaml degrades
    to schema-only validation (check_39 no-ops without an idea name).
    """
    errors = check_38_ads_yaml_schema(ads_data, ads_path)
    idea_data: dict = {}
    try:
        with open(experiment_path) as f:
            raw = yaml.safe_load(f)
        if isinstance(raw, dict):
            idea_data = raw
    except (OSError, yaml.YAMLError):
        idea_data = {}
    errors.extend(check_39_ads_campaign_name(ads_data, idea_data, ads_path))
    return errors


def check_45_visit_landing_variant_property(events_data: dict | None) -> list[str]:
    """Check 45: visit_landing event has variant property (when present)."""
    errors: list[str] = []
    events_path = "experiment/EVENTS.yaml"
    if not events_data or not isinstance(events_data, dict):
        return errors

    flat_events = events_data.get("events", {})
    # Only validate when visit_landing exists — events are project-specific,
    # not all projects will have this event name.
    if isinstance(flat_events, dict) and "visit_landing" in flat_events:
        visit_landing_event = flat_events["visit_landing"]
        props = visit_landing_event.get("properties", {}) if isinstance(visit_landing_event, dict) else {}
        if not isinstance(props, dict) or "variant" not in props:
            errors.append(
                f"[45] {events_path}: visit_landing event is missing "
                f"a 'variant' property (needed for experiment matrix)"
            )
    return errors
