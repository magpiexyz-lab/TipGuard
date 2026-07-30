# STATE 1: GATHER_DATA

**PRECONDITIONS:**
- Context read (STATE 0 POSTCONDITIONS met)

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
> web-app + service: deploy then iterate | cli: publish via npm/GH then iterate (or surface=none manual feedback)

### 1a: Attempt auto-query for funnel numbers

Read the analytics stack file (`.claude/stacks/analytics/<value>.md`). If it has an "Auto Query" section, follow its credential check and query procedure to automatically fetch funnel data.

If the auto-query succeeds, present the results for user verification:

```
## Auto-fetched Funnel Data (last <N> days)
| Event | Unique Users |
|-------|-------------|
| <first event from experiment/EVENTS.yaml> | <count> |
| <second event from experiment/EVENTS.yaml> | <count> |
| ... | ... |
Source: Analytics Query API (project_name = "<name>")
**Please verify.** Reply "looks good" to proceed, or provide corrections.
```

- Show all events from the query, including those with 0 counts
- Wait for user confirmation before proceeding to STATE 2
- If the user replies "looks good" (or any affirmative), proceed to STATE 2 with the auto-fetched data
- If the user provides corrections (e.g., "visit_landing should be 500"), update the affected counts and re-present the table for confirmation. Use the corrected values in STATE 2.

### 1b: Handle missing credentials or query failure

If the analytics stack file has no "Auto Query" section, warn the user: "Your analytics provider's stack file is missing an `## Auto Query` section, so funnel data can't be fetched automatically. Falling back to manual input — please file a template observation so the maintainer can add Auto Query support." Then proceed to the manual-input path below (same fallback as a query failure).

If credentials are missing (personal API key file not found), prefer auto-query. Show the credential setup steps and ask the user to create the key — but accept manual input as a fallback for users who cannot create one (read-only org policy, etc.):

> PostHog personal API key not found at `~/.posthog/personal-api-key`.
>
> This key is required for `/iterate` to query your funnel data. Create one now:
> 1. Go to PostHog -> click your profile (bottom left) -> **Personal API keys**
> 2. Click **Create personal API key**
> 3. Label: `cli` (or anything)
> 4. Scopes: set **Query** to **Read** (all others can stay No access)
> 5. Click **Create key** and copy the key (it starts with `phx_`)
> 6. Save it:
> ```
> mkdir -p ~/.posthog && echo 'phx_YOUR_KEY' > ~/.posthog/personal-api-key
> ```
> Then re-run `/iterate`.
>
> If you cannot create a personal API key (e.g., restricted org policy), reply **manual** to enter funnel numbers by hand instead.

If the user replies "manual", fall through to the manual-input path below.

If credentials exist but the query fails (network error, auth error, unexpected response), fall back to manual input.

Tell the user how to get the numbers. See the analytics stack file's "Dashboard Navigation" section for provider-specific instructions on how to pull funnel numbers. If no stack file exists or it lacks a "Dashboard Navigation" section, give general guidance.

> **How to get your funnel numbers:**
> Follow the dashboard instructions in your analytics stack file (`.claude/stacks/analytics/<value>.md`).
>
> Create a funnel using events from the experiment/EVENTS.yaml `events` map, filtered by `requires` (match experiment stack) and `archetypes` (match experiment type), ordered by funnel_stage (reach -> demand -> activate -> monetize -> retain).
>
> Filter by `project_name` equals your experiment.yaml `name` value. Present the actual event names to the user so they can find them in their dashboard.
>
> If you haven't deployed yet, the app isn't collecting data. For web-app and service archetypes, run `/deploy` first; for CLI archetypes, publish via `npm publish` or GitHub Releases (see the archetype file). Then return to `/iterate` after a few days of live traffic. For CLI tools with no surface (`surface: none`), `/deploy` and `/distribute` do not apply -- publish manually and collect feedback directly from users. If you haven't set up analytics yet, rough estimates are fine too (e.g., "about 200 landing page visits, maybe 20 signups").

Ask the user to provide funnel numbers -- for each event in the experiment/EVENTS.yaml `events` map (filtered by `requires` and `archetypes`), how many users? Present the actual event names from experiment/EVENTS.yaml so the user knows what to look for in their dashboard.

> **Insufficient data check:** If `visit_landing` count is fewer than 10, tell the user: "Not enough traffic for meaningful analysis (fewer than 10 visits). Run `/distribute` to drive traffic, wait a few days, and re-run `/iterate`." Proceed to STATE 2 only if the user wants analysis despite low volume.

### 1c: Ask for qualitative data

Whether funnel numbers came from auto-query (1a) or manual input (1b), also ask the user to provide whatever they have. Not all of these will be available -- use what you get:

1. **Additional event numbers** -- if experiment/EVENTS.yaml has events not already fetched in 1a (e.g., archetype-specific events), ask for counts of each. Include these in the STATE 2 diagnosis as supplementary data below the funnel table.

2. **Timeline** -- how far into the experiment timeline are we?

3. **Qualitative feedback** -- any user quotes, complaints, feature requests, support messages?

4. **Observations** -- anything the team has noticed (e.g., "users sign up but never create an invoice", "landing page bounce rate is high")

5. **Variant comparison (if experiment.yaml has `variants`)** -- per-variant metrics:
   - `visit_landing` count per variant (filter by `variant` property)
   - `signup_complete` count per variant (if available, filter by UTM content or variant context)
   - `activate` count per variant (if available)
   - Which variant is getting the most traffic and which has the best conversion?

6. **Ads data (if /distribute has been run)** -- if `experiment/ads.yaml` exists:
   - Total spend so far
   - Clicks and CTR
   - Cost per click (CPC)
   - Conversions attributed to ads (`activate` events filtered by `utm_source` matching the channel from ads.yaml)

   How to get ads data: Open the campaign dashboard for your distribution channel and check Clicks, CTR, Avg CPC/CPM, Cost. For conversions: filter events in the analytics dashboard by `utm_source` matching the channel (e.g., `"google"`, `"twitter"`, `"reddit"` -- see ads.yaml `channel` field).

**POSTCONDITIONS:**
- Funnel data gathered (either auto-queried or manually provided)
- User has confirmed the funnel data
- Qualitative data collected (whatever was available)

- **Write data artifact** (`.runs/iterate-data.json`):
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  data = {
      'funnel_data': {},
      'qualitative_data': [],
      'data_source': '<auto-query|manual>'
  }
  print(json.dumps(data))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/iterate-data.json \
    --payload "$PAYLOAD" \
    --skill iterate
  ```

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/iterate-data.json')); assert isinstance(d.get('funnel_data'), dict) and len(d['funnel_data'])>0, 'funnel_data empty'; assert isinstance(d.get('qualitative_data'), list), 'qualitative_data not a list'; assert d.get('data_source') in ('auto-query','manual'), 'data_source=%s' % d.get('data_source')"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh iterate 1
```

**NEXT:** Read [state-2-compute-verdicts.md](state-2-compute-verdicts.md) to continue.
