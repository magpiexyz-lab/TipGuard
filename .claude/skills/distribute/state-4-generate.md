# STATE 4: GENERATE

**PRECONDITIONS:**
- Implementation verified (STATE 3b POSTCONDITIONS met)

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
> web-app: read src/app/page.tsx for headlines | service: read root route handler | cli: read site/index.html

### 4a: Research targeting

Read `experiment/experiment.yaml`: `description`, `target_user`, `name`, `behaviors`.

Read the selected channel's stack file "Targeting Model" section, then generate targeting research appropriate for the channel:

**For keyword-based channels (e.g., google-ads):**

```
## Keyword Research

**Target user intent:** [what the target_user would search for when experiencing the problem]
**Competitor landscape:** [known alternatives mentioned in problem statement]
**Search volume estimate:** [high/medium/low for this niche]

**Recommended keywords:**
- Exact match: [5-8 keywords] — highest intent, most specific
- Phrase match: [3-5 keywords] — moderate intent
- Broad match: [2-3 keywords] — discovery, wider net
- Negative: [5+ keywords] — exclude irrelevant traffic (enterprise, existing tools, etc.)
```

Keyword rules (google-ads):
- Minimum 3 exact, 2 phrase, 1 broad, 2 negative
- Exact match keywords target users actively looking for this type of solution
- Phrase match captures related searches with moderate intent
- Broad match casts a wider net for discovery
- Negative keywords exclude enterprise, existing well-known tools, and irrelevant traffic

**For interest/audience-based channels (e.g., twitter):**

```
## Audience Research

**Target user profile:** [who the target_user is on this platform]
**Competitor/influencer accounts:** [relevant handles to target]

**Recommended targeting:**
- Interests: [3-5 interest categories]
- Follower lookalikes: [3-5 competitor/influencer handles]
- Timeline keywords: [3-5 keywords users tweet about]
```

**For community-based channels (e.g., reddit):**

```
## Community Research

**Target communities:** [where the target_user congregates]
**Community tone:** [how this community expects to be addressed]

**Recommended targeting:**
- Subreddits: [3-5 relevant subreddits]
- Interest categories: [2-3 Reddit interest categories]
```

### 4b: Generate creative

Derive from experiment.yaml `name`, `description`, and `thesis`.

#### Ad format constraints

Read the selected channel's stack file "Ad Format Constraints" section for character limits, creative format, and minimum variations. Apply these constraints when generating ad copy.

#### Copy principles
- Headline = outcome for target_user (what they get)
- Description/body = proof + CTA (why believe + what to do next)
- Include the landing URL with UTM parameters — read the channel's stack file "UTM Parameters" section for `utm_source` and `utm_medium` values: `?utm_source={channel_source}&utm_medium={channel_medium}&utm_campaign={campaign_name}`

#### Hypothesis alignment (when spec-manifest.json exists)

If hypothesis context was loaded in State 1_5:

- **Headlines**: derive from `demand` hypothesis `statement`. If the hypothesis says "freelancers want AI-generated invoices from time logs", the headline should address that angle directly (e.g., "Turn Time Logs Into Invoices in Seconds").
- **CTA**: align with the hypothesis `metric.formula`'s desired user action. If the formula is "signup_complete / visit_landing", the CTA should drive signups ("Start Free" > "Learn More"). If the formula is "cta_click / visit_landing", the CTA should be prominent and action-oriented.
- **Targeting angle**: if a `reach` hypothesis specifies a channel or audience (e.g., "freelancers on Reddit respond to invoicing pain"), use it to inform the targeting research in Step 4a.

This is additive guidance — it refines the copy principles above, not replaces them. Message match rules from messaging.md still apply.

#### Message match
Follow the message match rules in `.claude/patterns/messaging.md`. Ad headlines must be shortened versions of the landing page headline (the value proposition, not the product name). If the app has already been bootstrapped, read the surface source to extract the actual landing headline and derive ad headlines from it: for web-app read `src/app/page.tsx`; for service read the root route handler (path per framework stack file); for CLI read `site/index.html`. Note that character constraints are channel-specific — read the stack file's "Ad Format Constraints" for the channel's limits.

#### Variant ad groups (when experiment.yaml has `variants`)
When experiment.yaml has a `variants` field, generate per-variant creative:
- Create a separate ad group/creative set per variant
- Each variant's creative is derived from that variant's `headline` field (not from the shared `description`)
- Each variant's landing URL includes `utm_content={slug}` (e.g., `?utm_source={source}&utm_medium={medium}&utm_campaign={campaign_name}&utm_content=speed`)
- Each variant's landing URL points to `/v/{slug}` (e.g., `https://example.vercel.app/v/speed?...`)
- Follow messaging.md Section D: ad headlines for a variant match that variant's landing page headline
- See `experiment/ads.example.yaml` for schema format examples

### 4b.5: Generate sitelinks (google-ads only)

**Skip condition:** If the channel is not `google-ads`, skip this step entirely. Sitelinks are a Google Ads-specific extension.

#### Step 1: Identify candidate pages

Read `golden_path` from `experiment/experiment.yaml`. Extract all unique `page` values. Filter to candidate pages:
- Must be a user-facing page (has a corresponding `page.tsx` or equivalent route file, not an API route)
- Exclude `landing` (the main ad already links there)
- Keep auth pages (signup) if in golden_path — they are valid sitelink targets

Count the independent candidate pages.

#### Step 2: Threshold check and anchor fallback

**If independent pages >= 2:** Proceed to Step 3 using these pages (up to 4, prioritizing pages earlier in the golden_path).

**If independent pages < 2:** Scan the landing page component for section IDs:
- **web-app**: Read `src/app/page.tsx` (or the landing component it imports). Search for JSX/HTML elements with `id` attributes on major sections (e.g., `<section id="features">`, `<div id="pricing">`, `<section id="faq">`). Ignore utility IDs (e.g., `id="root"`, `id="__next"`).
- **service/cli (detached)**: Read `site/index.html`. Search for elements with `id` attributes on sections.
- Collect section IDs as anchor sitelink candidates.

Combine independent pages + anchor sections:
- **Combined total >= 2:** Proceed to Step 3 (prioritize independent pages over anchors)
- **Combined total < 2:** Skip sitelinks. Write `sitelinks: []` with a comment explaining why (e.g., `# No sitelinks: only 1 qualifying destination found`). Log the reason and proceed to step 4c.

#### Step 3: Generate sitelink copy

For each candidate (up to 4, prioritizing independent pages over anchors):

1. Find the golden_path step and matching behavior for this page (behavior whose `event` matches the step's `event`)
2. Apply messaging.md Section F copy rules:
   - `link_text`: imperative verb + noun from step description (max 25 chars)
   - `description_1`: benefit from behavior `then` clause (max 35 chars)
   - `description_2`: qualifier from experiment.yaml `description` or behavior `given` clause (max 35 chars)
3. For anchor sitelinks: derive copy from the section content on the landing page per messaging.md Section F "Anchor Sitelinks" rules

#### Step 4: Construct URLs

Read UTM parameter template from the channel stack file "UTM Parameters" section.

- **Independent page:** `{landing_url}/{page}?utm_source=google&utm_medium=cpc&utm_campaign={campaign_name}&utm_content=sitelink_{page}`
- **Anchor section:** `{landing_url}?utm_source=google&utm_medium=cpc&utm_campaign={campaign_name}&utm_content=sitelink_anchor_{section_id}#{section_id}`

Note: UTM query params must come BEFORE the fragment identifier (`?...#section`). Reversing this breaks analytics tracking.

#### Step 5: Validate

- Each `link_text` <= 25 characters
- Each `description_1` <= 35 characters
- Each `description_2` <= 35 characters
- All `final_url` values are unique
- No `final_url` equals the main ad landing URL (without UTM params)
- At least 2 sitelink entries

Store the generated sitelinks array for inclusion in ads.yaml (Step 4d).

### 4c: Calculate thresholds

#### Phase 1 defaults

Apply the standardized budget and duration defaults:

| Setting | Default |
|---------|---------|
| `duration_days` | 7 |
| `total_budget_cents` | 25000 ($250 MAX cap) |
| `daily_budget_cents` | 2000 ($20.00/day) |
| `click_target` | 100 paid clicks |
| `initial_max_cpc_cents` | 140 ($1.40 starting bid) |
| `guardrails.max_cpc_cents` | 250 ($2.50 CPC ceiling) |

These are defaults — if experiment.yaml or user input specifies different values, those take precedence.

Read the channel's stack file "Cost Model" section to understand the pricing model, then use first-principles reasoning specific to this MVP:

**For CPC channels (e.g., google-ads):**
1. Parse `budget.total_budget_cents` and estimate CPC for the targeting category
2. Calculate: expected clicks = budget / CPC
3. Estimate funnel conversion rates:
   - Landing -> signup: 5-15% for cold paid traffic
   - Signup -> activate: 20-40% depending on activation friction
4. Calculate expected volume at each stage

**For CPM channels (e.g., twitter, reddit):**
1. Parse `budget.total_budget_cents` and estimate CPM for the targeting category
2. Calculate: expected impressions = budget / (CPM / 1000)
3. Calculate: expected clicks = impressions x estimated CTR
4. Estimate funnel conversion rates (same as above)
5. Calculate expected volume at each stage

Show the reasoning chain, not just the numbers:

```
## Threshold Reasoning

Budget: $20/day, 7-day nominal window (set as End date), $250 MAX cap; stop at 100 paid clicks or the cap
Estimated [CPC/CPM] for [targeting category]: ~$X.XX
Expected [clicks/impressions]: [calculation]
Expected signups: [clicks * landing-to-signup rate] ([rate]% -- [reasoning])
Expected activations: [signups * signup-to-activate rate] ([rate]% -- [reasoning])

Go signal: [N]+ activations from paid traffic within experiment timeline
No-go signal: 0 activations after $[half-budget] spend, or <1% CTR after 500 impressions
```

Define go/no-go signals based on experiment.yaml `thesis` and `funnel` thresholds.

#### Schema rules for ads.yaml
- `channel`: the selected distribution channel (e.g., `google-ads`, `twitter`, `reddit`)
- `campaign_name`: auto-generated following the channel's config schema pattern (e.g., `{project-name}-search-v{N}` for google-ads, `{project-name}-twitter-v{N}` for twitter)
- `budget.total_budget_cents`: Phase 1 default 25000 ($250) = `click_target` x `guardrails.max_cpc_cents`. Overridable by user.
- `budget.duration_days`: Phase 1 default 7 days, a nominal window written into the campaign End date. Overridable by user.
- `budget.click_target`: Phase 1 default 100 paid clicks.
- `budget.initial_max_cpc_cents`: Phase 1 default 140 ($1.40 starting bid).
- `guardrails.max_cpc_cents`: CPC ceiling default 250 ($2.50); bids may raise toward it, never above it.
- `guardrails.auto_pause_rules`: encode stop A (`clicks >= click_target`), stop B (`total_spend >= total_budget_cents`), and the manual end-date-extension note. Do not encode elapsed days as a pause rule.
- `guardrails`: channel-specific — CPC channels require `max_cpc_cents`; other channels may use `max_cpe_cents` or just `auto_pause_rules`
- `thresholds`: AI-generated from experiment.yaml context using first-principles reasoning

### 4d: Assemble ads.yaml

Write the complete `experiment/ads.yaml` file. Include `channel: <selected-channel>` as the first field. Follow the selected channel's stack file "Config Schema" section for the channel-specific structure. See `experiment/ads.example.yaml` for full schema examples across channels.

After the `ads` block (or `ad_groups` block if variants are present), include the `sitelinks` array generated in Step 4b.5. If Step 4b.5 produced an empty array, write `sitelinks: []` with a comment explaining why (e.g., `# No sitelinks: only 1 user-facing page`).

#### Phase 1 Playbook injection

**If channel is `google-ads`:**

After writing the standard ads.yaml fields (channel, campaign_name, keywords, ads, budget, targeting, conversions, guardrails, thresholds), inject a `playbook` block at the top level. This block contains standardized Phase 1 Playbook settings that override campaign-level defaults:

```yaml
# Phase 1 Playbook (auto-injected, do not modify)
playbook:
  phase: 1
  bidding_strategy: manual_cpc
  match_type: phrase
  network: search_only
  ad_schedule: "24/7"
  geo: <from experiment.yaml target_geo field, default [US, GB, CA, AU, NZ]>
  negative_keywords:
    <read the full "Negative Keywords (Universal)" list from the channel stack file at .claude/stacks/distribution/google-ads.md and include all 50 keywords>
  rsa_count: 2
  ad_group_count: 1
```

The `geo` field is read from experiment.yaml `target_geo`. If `target_geo` is not set, default to `[US, GB, CA, AU, NZ]`.

**Playbook fields override campaign-level settings but preserve AI-generated content:**
- `playbook.bidding_strategy` overrides `budget.bidding_strategy` — campaign MUST use `manual_cpc`
- `playbook.match_type` applies to all keywords — ensure keywords use phrase match format
- `playbook.negative_keywords` are ADDED to any AI-generated negative keywords (union, no duplicates)
- `playbook.rsa_count` and `playbook.ad_group_count` constrain the `ads` section (2 RSAs, 1 ad group)
- `playbook.network` enforces Google Search only (no Search Partners, no Display Network)
- Keywords (exact, phrase, broad), ad headlines, and ad descriptions remain AI-generated from steps 4a-4b

**If channel is NOT `google-ads`:** Do not inject a playbook block. The Phase 1 Playbook is Google Ads-specific. Other channels use their own stack file defaults.

Present the full config for review.

### 4e: Commit ads.yaml to branch

- Commit `experiment/ads.yaml` to the branch with message: imperative mood (e.g., "Add ads.yaml campaign config for {channel}")
- Do NOT create a PR yet (that happens in State 5)

**POSTCONDITIONS:**
- Targeting research generated appropriate to the selected channel type
- Ad creative generated with headlines, descriptions/body, and CTAs
- Channel-specific format constraints applied (character limits, variation counts)
- Landing URLs include correct UTM parameters
- Message match verified against landing page headline
- Threshold reasoning chain documented with calculations
- Go/no-go signals defined based on experiment thesis
- `experiment/ads.yaml` exists with complete campaign configuration
- `channel` is the first field in the file
- Config follows the selected channel's schema from its stack file
- If google-ads: `playbook` block present with all standardized fields
- Playbook negative_keywords include the universal keywords from the stack file
- If variants exist: per-variant ad groups generated with utm_content and /v/{slug} URLs
- Sitelinks generated from golden_path (2-4 entries with valid char limits and unique URLs), OR explicitly skipped with `sitelinks: []` and documented reason
- All committed to branch

**VERIFY:**
```bash
python3 -c "import yaml; d=yaml.safe_load(open('experiment/ads.yaml')); assert d.get('channel'), 'channel empty'; ags=d.get('ad_groups') or d.get('ads') or [d]; assert any(a.get('headlines') or a.get('descriptions') for a in (ags if isinstance(ags,list) else [ags])), 'no headlines or descriptions'; assert 'utm_source' in str(d) or 'utm_' in str(d), 'no UTM parameters'; sl=d.get('sitelinks'); assert sl is None or isinstance(sl, list), 'sitelinks must be a list'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh distribute 4
```

**NEXT:** Read [state-5-approve-and-ship.md](state-5-approve-and-ship.md) to continue.
